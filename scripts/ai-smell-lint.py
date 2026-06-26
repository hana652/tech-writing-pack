#!/usr/bin/env python3
"""
ai-smell-lint: 技術ブログ記事のAI臭症状とコロケーション崩れを機械検出する。

guides/03-anti-ai.md の症状①〜⑮ と guides/04-collocation.md のコロケーション崩れに
対応した正規表現で、記事(Markdown/HTML)をスキャンし、症状別に検出箇所を出力する。
目視に頼らず「候補を必ず拾う」ためのゲート。

使い方:
  python3 ai-smell-lint.py <記事.md|.html> [<記事2> ...]
  python3 ai-smell-lint.py --strict <記事.md>   # mention も警告として数える（厳格モード）

終了コード:
  0 = 致命症状(fatal)なし（warnのみ or クリーン）
  1 = 致命症状あり（記号NG / ⑫章境界 / ⑬テンプレ比喩 / ⑧否定対比が2回以上）
      → 直してから公開する

use と mention の区別（このツールの肝）:
  AI臭の語やNG構文を「自分の文章で使う(use)」のと、「悪い例として引用する(mention)」のは
  まったく別物。前者だけがAI臭で、後者は良い記事にむしろ必要（→ guides/03-anti-ai.md
  「引用(mention)と使用(use)の区別」）。このツールは検出した語が次のどちらかに当たるとき、
  📎mention（引用・例示の可能性）として FATAL/warn 判定から自動で除外する:
    1. 引用符（「」『』""【】《》〝〟）の中にある
    2. 同じ行に「悪い例」「お気に入りの言葉」「たとえば〜」など、語そのものを話題に
       するマーカーがある
  ただし機械判定は完璧ではない。📎mention でも地の文で実際に使っていれば直すべきだし、
  FATAL でも中身が引用なら合格にしてよい。最終判断は人。

注意:
  - コードブロック(``` ```)・インラインコード(`...`)は検査対象から除外する
    （コード内の記号や英単語を誤検出しないため）
  - grep困難な症状③(均等対称)・⑦(助詞省略)・⑮(短文化/常体落ち)は機械検出できない → 目視で確認
  - 検出は「候補」。正当な文脈（記事タイトルの「設計」など）は人が最終判断する
"""
import sys
import re

# (パターンリスト, 深刻度)  深刻度: 'fatal'=1件で致命 / 'fatal2'=2件以上で致命 / 'warn'=警告
SYMPTOMS = {
    # --- AI臭症状（03-anti-ai.md）---
    '①ヘッジ(保険)': (['と言えるでしょう', 'かもしれません', 'のではないでしょうか', '可能性があります', '注意が必要です'], 'warn'),
    '②メタ発言/作業実況': (['解説します', '紹介します', 'について説明します', '見ていきましょう', '見ていきます', 'ここでは', 'まず最初に', '確認しよう', 'から始めよう'], 'warn'),
    '③SEOテンプレ定型': (['いかがでしたか', 'いかがでしたでしょうか', 'ぜひ参考に', 'ぜひ試し', 'おわかりいただけ', '徹底解説', '完全ガイド', '保存版'], 'warn'),
    '④過剰共感': (['ですよね', 'ますよね', 'よね。', 'と思いませんか', 'ってなりますよね'], 'warn'),
    '⑤網羅欲': (['さまざまな', '様々な', '包括的', '網羅的', '多岐にわたる'], 'warn'),
    '⑤個数予告': (['理由は3つ', '理由は2つ', 'ポイントは3', 'ポイントは2', 'つあります。', '点あります。'], 'warn'),
    '⑧否定対比構文': (['じゃない。', 'ではない。', 'じゃなくて', 'のではなく', 'だけじゃない', 'だけではない'], 'fatal2'),
    '⑨構造化動詞': (['仕組みにする', '構造化する', '可視化する', '抽象化する', '言語化する'], 'warn'),
    '⑩エモ抽象化': (['温度感', '解像度を', '手触り', '輪郭を', '質感', 'グラデーション'], 'warn'),
    '⑪ぼかし語尾': (['という話', 'のではないか', 'のかもしれない', 'のように思う', 'という名の', 'が起きている', '問われている'], 'warn'),
    '⑫章境界アナウンス': (['ここから', 'ここまでが', 'ここまで見', 'してきました', '次の章', '順番に見', '掘っていき', '整理します', 'まとめます', 'ということです。'], 'fatal'),
    '⑬テンプレ比喩': (['地図', '仕様書', '設計書', '羅針盤', 'コンパス', '屋台骨', '潤滑油', '車の両輪', '両翼', '3本柱', 'スパイス', 'レシピ', '調味料', '筋トレ', '加速装置'], 'fatal'),
    '⑭過去形の乱用': (['であった。', 'がわかった。', 'が見られた。', 'が確認された。', 'だったのだ。'], 'warn'),

    # --- コロケーション崩れ（04-collocation.md）★このパックの目玉 ---
    'CO動詞ミスマッチ': (['課題を改善', '問題を改善', '目標を成功', '目標を実現する', '効果を与え', '影響を発揮', 'ニーズを叶え', '期待を満た', '経験を貯め', '知識を覚え', '役割を行', '責任を行', '成長を達成', '成果を達成', '対策を作', '疑問を思', 'リスクを解決', '失敗を解決', 'バグを解決', 'パフォーマンスを強化', 'セキュリティを高く', 'メモリを削減', 'コストを節約'], 'warn'),
    'CO自他動詞': (['速度を向上する', '速度を向上します', 'エラーを発生する', 'エラーを発生します', '値を変化する', '処理を完了する'], 'warn'),
    'CO形容詞ミス': (['濃い理解', '高い課題', '大きい精度', '濃い相関', '太い影響', 'ハードルが大き'], 'warn'),
    'CO副詞ミス': (['大幅に解決', '劇的に達成', '急激に解決', '徐々に達成', '圧倒的に解決'], 'warn'),
    'CO慣用句崩れ': (['的を得', '采配を振う', '物議を呼', '汚名を回復', '公算が強', '足元をすくわれ', '怒り心頭に達'], 'warn'),
    'CO重言': (['まず最初に', '一番最初', '必ず必要', '後で後悔', '違和感を感じ', '過半数を超え', 'を投げる例外', '約', '各'], 'warn'),  # 「約」「各」は後段で重言形のみ判定
    'CO翻訳調': (['影響を作', '決定を作', '努力を作', '違いを作る', '質問を持っている', 'を可能にさせる', 'クオリティを持'], 'warn'),

    # --- AI偏愛語の擦り倒し（04の最頻発カテゴリ）★ ---
    'AI偏愛動詞(比喩被せ)': (['仕組みが壊れ', '関係が壊れ', '仕組みが回', '問いが立', '仮説が立', '言葉を紡', '物語を紡', '未来を描', '世界観を描', '本質を照ら', '浮き彫り', '紐解', '魂が宿', '思想が宿', '常識を揺さぶ', '人柄が滲', '情報が落ち', '視点が落ち'], 'warn'),
    'AI偏愛(システム語の比喩)': (['人生を設計', '人生をハック', '思考をハック', '思考をアップデート', '思考をリファクタ', '人生をリファクタ', '思考のOS', '意識のレイヤー', '課題の解像度', '学びの解像度', '思考の解像度'], 'warn'),
    'AI偏愛名詞': (['本質的に', '本質はここ', '解像度を', '手触り', '質感', '温度感', '熱量', 'まなざし', '眼差し', '血の通っ', '地に足', '等身大', '腹落ち', 'メンタルモデル', 'グラデーション', 'という装置', 'という営み'], 'warn'),


    # --- 記号NG ---
    '記号NG(罫線/EMダッシュ)': (['──', '—', '─', '：　', '： '], 'fatal'),
    'お役所表現': (['当該', '上記の通り', '以下に示す', '前述の'], 'warn'),
}

# 重言の中でも誤検出しやすい「約」「各」は、正規表現で重言形のときだけ拾う
REDUNDANT_RE = [
    (re.compile(r'約[^。、]{0,6}(程度|くらい|ほど)'), 'CO重言(約〜程度)'),
    (re.compile(r'各[^。、]{0,8}ごとに'), 'CO重言(各〜ごとに)'),
    (re.compile(r'[a-zA-Z]+を(投げる|入力する|出力する|ダウンロードする)'), 'CO重言(英単語+和訳)'),
    (re.compile(r'は、[^。、]{2,30}(だった|していた|ていた|であった)。'), 'AI観察断定(〜は、〜だった)'),
]

HEADING_RE = re.compile(r'<h[1-6]|^\s*#{1,6}\s')

# --- use/mention 判定 ---------------------------------------------------------
# 開き→閉じが別文字の引用符ペア（ASCIIの " ＂ は同一文字なので別処理）
QUOTE_PAIRS = {'「': '」', '『': '』', '“': '”', '‘': '’', '【': '】', '《': '》', '〈': '〉', '〝': '〟'}
QUOTE_CLOSERS = set(QUOTE_PAIRS.values())

# 同じ行にあると「語そのものを話題にしている（引用・例示）」とみなすマーカー。
# 保守的に「語を引いていることが明白なもの」だけに絞る（地の文の通常使用を巻き込まないため）。
META_MARKERS = [
    '悪い例', '悪例', 'NG例', 'NG表現', '禁止語', 'お気に入りの言葉', '偏愛語',
    'という表現', 'という言葉', 'といった言葉', 'という単語', 'といったフレーズ',
    'と書きたくなっ', 'と書きそうになっ', 'を擦り倒', 'を多用', 'の連発', 'が頻発',
    'たとえば「', '例えば「', '例として', '〜は', 'のように書',
]


def quote_spans(line):
    """行内の引用符で囲まれた範囲を [(start, end), ...] で返す（endは閉じ括弧の次）。"""
    spans = []
    stack = []          # [(期待する閉じ括弧, 開始index), ...]
    dq_open = False     # ASCIIダブルクオートのトグル
    dq_start = 0
    for i, ch in enumerate(line):
        if ch == '"' or ch == '＂':
            if not dq_open:
                dq_open, dq_start = True, i
            else:
                spans.append((dq_start, i + 1))
                dq_open = False
        elif ch in QUOTE_PAIRS:
            stack.append((QUOTE_PAIRS[ch], i))
        elif ch in QUOTE_CLOSERS and stack and ch == stack[-1][0]:
            _, s = stack.pop()
            spans.append((s, i + 1))
    return spans


def in_spans(pos, spans):
    return any(s <= pos < e for s, e in spans)


def classify(pos, spans, has_meta):
    """検出位置が use か mention かを返す。引用符内 or メタ行 → mention。"""
    return 'mention' if (in_spans(pos, spans) or has_meta) else 'use'


def find_positions(text, pat):
    """text 中の pat の全出現開始位置を返す。"""
    out, start = [], 0
    while True:
        idx = text.find(pat, start)
        if idx < 0:
            break
        out.append(idx)
        start = idx + 1
    return out


def strip_code_and_tags(text: str):
    """fencedコードブロック・インラインコード・style/scriptを空白化し（行数維持）、各行のHTMLタグを除く。"""
    def blank(m):
        return '\n' * m.group(0).count('\n')
    # fenced code block ``` ... ```
    text = re.sub(r'```[\s\S]*?```', blank, text)
    text = re.sub(r'~~~[\s\S]*?~~~', blank, text)
    # style / script
    text = re.sub(r'<style[\s\S]*?</style>', blank, text, flags=re.IGNORECASE)
    text = re.sub(r'<script[\s\S]*?</script>', blank, text, flags=re.IGNORECASE)
    lines = text.split('\n')
    out = []
    for ln in lines:
        is_heading = bool(HEADING_RE.search(ln))
        no_inline = re.sub(r'`[^`]*`', '', ln)        # インラインコード除去
        no_attr = re.sub(r'<[^>]+>', '', no_inline)   # HTMLタグ除去
        out.append((no_attr, is_heading))
    return out


def lint_file(path: str, strict: bool = False):
    try:
        raw = open(path, encoding='utf-8').read()
    except Exception as e:
        print(f"[ERROR] {path}: {e}")
        return 2
    lines = strip_code_and_tags(raw)

    # 症状 -> [(lineno, text, is_heading, kind)]  kind: 'use' / 'mention'
    findings = {}

    def add(sym, lineno, txt, is_head, kind):
        findings.setdefault(sym, []).append((lineno, txt.strip()[:80], is_head, kind))

    for i, (txt, is_head) in enumerate(lines, 1):
        spans = quote_spans(txt)
        has_meta = any(m in txt for m in META_MARKERS)

        for sym, (pats, sev) in SYMPTOMS.items():
            if sym == 'CO重言':
                continue  # 「約」「各」「を投げる例外」の単純包含は誤検出多→ REDUNDANT_RE で判定
            for p in pats:
                for pos in find_positions(txt, p):
                    add(sym, i, txt, is_head, classify(pos, spans, has_meta))

        for rgx, label in REDUNDANT_RE:
            for m in rgx.finditer(txt):
                add(label, i, txt, is_head, classify(m.start(), spans, has_meta))

        # CO重言の単純語（まず最初に等。「約」「各」を除いた分）
        for p in ['まず最初に', '一番最初', '必ず必要', '後で後悔', '違和感を感じ', '過半数を超え']:
            for pos in find_positions(txt, p):
                add('CO重言', i, txt, is_head, classify(pos, spans, has_meta))

    SEV = {k: v[1] for k, v in SYMPTOMS.items()}
    fatal = False
    use_total = men_total = 0
    print(f"\n===== ai-smell-lint: {path} =====")
    if not findings:
        print("  ✅ クリーン（機械検出される症状なし）")

    for sym in list(SYMPTOMS.keys()) + [l for _, l in REDUNDANT_RE]:
        hits = findings.get(sym, [])
        if not hits:
            continue
        use_hits = [h for h in hits if h[3] == 'use']
        men_hits = [h for h in hits if h[3] == 'mention']
        sev = SEV.get(sym, 'warn')

        # strictモードでは mention も use と同様に扱う
        judged = (use_hits + men_hits) if strict else use_hits
        n = len(judged)
        head_hit = any(h[2] for h in judged)
        is_fatal = (
            (sev == 'fatal' and n >= 1)
            or (sev == 'fatal2' and n >= 2)
            or (sym == '⑧否定対比構文' and head_hit and n >= 1)
            or ('記号NG' in sym and head_hit and n >= 1)
        )
        if is_fatal:
            fatal = True

        if use_hits:
            use_total += len(use_hits)
            mark = '🚨FATAL' if is_fatal else '⚠️warn'
            print(f"  {mark} {sym}: {len(use_hits)}件(use)")
            for (lineno, t, ih, _) in use_hits[:5]:
                tag = '[見出し]' if ih else ''
                print(f"      L{lineno}{tag}: {t}")
        if men_hits:
            men_total += len(men_hits)
            tag_strict = '（strict: 判定対象）' if strict else '（判定から除外・要人確認）'
            print(f"  📎mention {sym}: {len(men_hits)}件 〔引用/例示の可能性{tag_strict}〕")
            for (lineno, t, ih, _) in men_hits[:5]:
                tag = '[見出し]' if ih else ''
                print(f"      L{lineno}{tag}: {t}")

    print(f"  --- 集計: use {use_total}件 / 📎mention {men_total}件")
    print(f"  --- 判定: {'🚨 FATALあり（公開前に修正）' if fatal else '✅ 致命なし（warnは目視で要否判断）'}")
    print("  ※ コードブロック・インラインコードは検査対象外。")
    print("  ※ 📎mention＝引用符内 or「悪い例/たとえば」等のメタ行。引用なら直さず合格。地の文で使っていれば手で直す。")
    print("  ※ 症状③均等対称・⑦助詞省略・⑮短文化/常体落ちは機械検出外。目視で確認。")
    print("  ※ COはコロケーション崩れ候補。正当な文脈もあるので最終判断は人。")
    return 1 if fatal else 0


def main():
    args = sys.argv[1:]
    strict = False
    if '--strict' in args:
        strict = True
        args = [a for a in args if a != '--strict']
    if not args:
        print("usage: python3 ai-smell-lint.py [--strict] <article.md|.html> [...]")
        sys.exit(2)
    rc = 0
    for path in args:
        rc = max(rc, lint_file(path, strict=strict))
    sys.exit(rc)


if __name__ == '__main__':
    main()
