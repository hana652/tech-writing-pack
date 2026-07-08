#!/usr/bin/env python3
"""writing-lint.py v2 — 決定的な機械校閲（/kouetsu STEP2の実体）

v2.4 (2026-07-08): コードフェンス（``` 〜 ```）内を全カウンタから除外。ツリー図の罫線─が
B-5ダッシュに、コード内文字列が各カウンタに誤ヒットするため（v2.3の箇条書き除外と同方向）。
v2.3 (2026-07-07): mention除外（短い「」引用は密度カウンタから除く）＋箇条書き・見出し行を
B-2/B-10の文抽出から除外（リストの並列・常体は正当なため）。
v2.2: A-1転用ペア（確定的な名詞×動詞結合・1,000字1回）＋WATCH（落ちる/回す/流す等の
高頻度転用動詞の参考カウント＝違反にせず要文脈判断で人間/LLMへ渡す）を追加。
v2.1: ai-buntai-ruleset-v0.3 完全版のリストを反映（B-6/B-9/B-13/B-14追加、
慣用句混交12種、転用動詞・強調語・比喩名詞を拡充。納品レジスターで上限0のカウンタに対応）。
正本: guides/07-ai-buntai-laws.md ＞ guides/08-ai-buntai-ruleset.md
     guides/04-collocation.md（偏愛語）
※密度の正はv0.3総表。lintは近似実装（体言止め・比喩系統数・談話接続は人間/LLMレビュー側）

使い方:
    python3 writing-lint.py <file> [--type article|deck|report|mail]
                                   [--register standard|deliverable|buzz]

- FATAL: 個人名・慣用句混交・壊れた句読点＝事故ルール違反。exit code 1
- DENSITY: パターン別カウンタ。閾値超過のみ違反（法則1: AI臭は誤用でなく密度）
- SHOULD: 偏愛語・指紋・章境界アナウンス等の候補（文脈で正当ならOK判定可）
- INFO: 金額など人間確認対象
- レジスター: standard=技術/SEO記事, deliverable=クライアント納品(閾値半分),
             buzz=X/note長文(閾値2倍)。B-10文体混在だけは全レジスター0回
"""
import argparse
import math
import re
import sys
from pathlib import Path

# ══ FATAL ══════════════════════════════════════════════
PERSONAL_NAMES = []  # 運用先で自分・関係者の固有名詞を追記する（納品物への混入をFATAL検出）
BROKEN_PUNCT = [r"、、", r"。。", r"！！！", r"？？"]
IDIOM_MIX = {  # A-4 慣用句混交（0回・修正先つき・v0.3の12種）
    "的を得": "的を射る", "頭ひとつ飛び出": "頭ひとつ抜ける",
    "汚名挽回": "汚名返上", "二の舞を踏": "二の舞を演じる",
    "熱にうなされ": "熱に浮かされる", "押しも押されぬ": "押しも押されもせぬ",
    "足元をすくわれ": "足をすくわれる", "論戦を張": "論陣を張る",
    "火蓋が切って落とされ": "火蓋が切られる", "のみに徹底させ": "に徹する・専念させる",
    "を振り当て": "を割り当てる",
}

# ══ DENSITY カウンタ（法則1: 上限つき・全削除しない） ══════════
# (キー, 正規表現, standard上限, 説明, mult適用するか)
COUNTERS = [
    ("B-1 対比構文", r"では\s?なく|じゃなく|というより", 2, "「AではなくB」。肯定形に畳む", True),
    ("B-5 ダッシュ", r"――|——|──|─", 2, "em-dash系。括弧・読点・「つまり」に開く", True),
    ("B-11 するだけ", r"するだけ|だけで(?:OK|完了|済)", 2, "簡便の誇張", True),
    ("B-3 切り詰め", r"たった|一択", 2, "切り詰め・断定", True),
    ("B-7 してくれます", r"してくれ(?:ます|る)", 2, "擬人的サービス表現", True),
    ("B-12 換算表現", r"に換算する?と|で言えば約|時間に直すと", 2, "換算インフレ。効く単位1つに絞る", True),
    ("B-6 メタ談話予告", r"大事な話をし|の話をさせてください|するとどうなるか", 1, "予告は削除しても情報が失われない", True),
    ("B-13 二人称断定", r"あなたも", 1, "断定フックは疑問形・条件形に緩める", True),
    ("B-14 伝聞エピソード", r"知人が|自分の周りで|と話してました|と言ってました", 1, "検証可能性必須。納品0回", True),
    ("B-9 つまり", r"つまり", 2, "全レジスター2回まで。接続なしで通る箇所から削る", False),
]
# 同一語1記事1回まで（A-1転用動詞・A-3強調語。2回目から違反。v0.3準拠＋誤検知しにくい語のみ）
PER_WORD_LIMIT1 = [
    "かなり", "正直", "ちゃんと", "一番", "決定的", "本命", "確実に", "圧倒的",
    "デカい", "肝心", "最強", "劇的", "爆速", "地味に", "驚くほど", "とてつもなく",
    "刺さる", "詰む", "溶ける", "溶かす", "蒸発", "古びる", "ブレる",
    "事故る", "溺れ", "彷徨", "垂れ流",
]
ZERO_PHRASES = [  # B-7 0回定型句＋法則6 指紋（1件でも違反）
    "なんですよね", "を可能にします", "は別の話", "種明かしをす",
    "ここが、一番", "ここに尽きます", "お気づきでしょうか", "控えめに言って",
    "というやつ", "だから、今なんです", "これだけ。",
]
# A-1 転用ペア（名詞×動詞の結合が確定的にAI転用のもの。上限=本文1,000字あたり1回）
TENYO_PAIRS = [
    r"(?:時間|工数)を溶か", r"(?:トークン|メモリ|リソース|容量|時間)を食",
    r"(?:コンテキスト|文脈)が(?:汚れ|蒸発)", r"言葉が渋滞",
    r"(?:ノート|ドキュメント|記事|メモ)が(?:育|回)", r"質問を潰",
    r"(?:詳細|情報)を逃が", r"海を彷徨", r"(?:キャパ|予定|枠)が埋ま",
    r"循環が回", r"思考が固ま", r"(?:ドキュメント|情報|知識)が古び",
]
# 高頻度で正当用法も多い転用動詞（違反にしない。参考カウント＝要文脈判断で人間/LLMに渡す）
WATCH_VERBS = [
    ("落ちる系", r"(?:が|も)落ち"), ("回す系", r"を回す|を回し|が回る|が回り"),
    ("流す系", r"を流す|を流し|が流れ|垂れ流"), ("効く系", r"が効く|に効く|が効い"),
    ("食う系", r"を食う|を食い|を食っ"), ("張る系", r"を張る|を張っ"),
    ("握る系", r"を握る|を握っ"), ("浮く系", r"が浮く|が浮い"),
    ("潰す系", r"を潰す|を潰し"), ("埋まる系", r"が埋ま"), ("ズレる系", r"がズレ|がずれ"),
]

# ══ SHOULD（候補提示・文脈判断可） ══════════════════════════
AI_FAVORED = [  # 偏愛語＋頻出比喩名詞（正本: collocation.md と ai-buntai v0.3 A-2）
    "解像度", "寄り添", "紐解", "浮き彫り", "羅針盤", "処方箋",
    "本質的", "唯一無二", "珠玉", "織りなす", "彩る", "加速させ",
    "進化を遂げ", "という物語", "を体現", "が肝", "インパクト", "深掘り",
    "滲む", "息づく", "紡ぐ", "物語る",
    "温床", "交通整理", "見取り図", "攻略本", "過積載", "手触り", "肌触り", "土足",
]
CHAPTER_ANNOUNCE = [
    "次の章では", "次のセクションでは", "ここまで見てきた", "見ていきましょう",
    "解説していきます", "いかがでしたか", "それでは早速",
]
MONEY_PATTERNS = [r"[¥￥][\d,]+", r"\d+万円", r"\d+億円"]

TAG_RE = re.compile(r"<[^>]+>")
SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b.*?</\1>", re.S | re.I)
KEITAI_RE = re.compile(r"(です|ます|ません|でした|ました|でしょう|ですね|ですよ|ください)(?:[ねよ])?$")
JOUTAI_RE = re.compile(r"(だ|である|だった|する|した|ない|だろう|しよう|くる|いる|ある|れる)$")


CODE_FENCE_RE = re.compile(r"^\s*(?:```|~~~)")


def mask_code_fences(lines: list[str]) -> list[str]:
    """コードフェンス内を空行化（行番号は維持）。図・コード・コマンドは文章密度の対象外"""
    out, in_fence = [], False
    for ln in lines:
        if CODE_FENCE_RE.match(ln):
            in_fence = not in_fence
            out.append("")
            continue
        out.append("" if in_fence else ln)
    return out


def load_lines(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() in (".html", ".htm"):
        text = SCRIPT_STYLE_RE.sub(lambda m: "\n" * m.group(0).count("\n"), text)
        return [TAG_RE.sub("", ln) for ln in text.splitlines()]
    return mask_code_fences(text.splitlines())


def scan(lines, patterns, regex=True):
    hits = []
    for pat in patterns:
        cre = re.compile(pat if regex else re.escape(pat))
        for i, ln in enumerate(lines, 1):
            for m in cre.finditer(ln):
                ctx = ln.strip()
                if len(ctx) > 56:
                    s = max(0, m.start() - 18)
                    ctx = "…" + ln[s : m.end() + 18].strip() + "…"
                hits.append((i, m.group(0), ctx))
    return hits


BULLET_RE = re.compile(r"^\s*(?:[-*>•｜|]|\d+\.|#{1,6}\s)")
SHORT_QUOTE_RE = re.compile(r"「[^「」]{1,25}」")


def sentences_with_lines(lines):
    """(行番号, 文) のリスト。句点・？！で分割。
    箇条書き・引用・見出し行は除外（リストの並列・常体は正当なためB-2/B-10誤検知になる）"""
    out = []
    for i, ln in enumerate(lines, 1):
        if BULLET_RE.match(ln):
            continue
        for s in re.split(r"(?<=[。！？])", ln.strip()):
            s = s.strip().rstrip("。！？")
            if len(s) >= 8:  # 表ラベル等の短片を除外（三連反復の誤検知対策）
                out.append((i, s))
    return out


def strip_short_quotes(lines):
    """短い「」引用（用語・例示のmention）を除去した行リスト。密度カウンタ用"""
    return [SHORT_QUOTE_RE.sub("〈引〉", ln) for ln in lines]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--type", default="article", choices=["article", "deck", "report", "mail"])
    ap.add_argument("--register", default=None, choices=["standard", "deliverable", "buzz"])
    args = ap.parse_args()

    # レジスター既定: deck/report/mail=納品扱い、article=standard
    reg = args.register or ("deliverable" if args.type in ("deck", "report", "mail") else "standard")
    mult = {"standard": 1.0, "deliverable": 0.5, "buzz": 2.0}[reg]

    path = Path(args.file).expanduser()
    if not path.exists():
        print(f"ERROR: file not found: {path}")
        return 2
    lines = load_lines(path)
    sents = sentences_with_lines(lines)
    clines = strip_short_quotes(lines)  # 密度カウンタは短い「」引用（mention）を除外して数える

    # ---- FATAL ----
    fatal = scan(lines, PERSONAL_NAMES, regex=False) + scan(lines, BROKEN_PUNCT)
    for wrong, right in IDIOM_MIX.items():
        for i, w, c in scan(lines, [wrong], regex=False):
            fatal.append((i, f"{w}→{right}", c))

    # ---- DENSITY ----
    density_report, density_over = [], 0
    for name, pat, base, note, use_mult in COUNTERS:
        limit = math.floor(base * mult) if use_mult else base  # 納品は上限0になり得る
        hits = scan(clines, [pat])
        over = len(hits) > limit
        density_over += over
        density_report.append((name, len(hits), limit, over, note, hits[:4]))
    # 同一語上限1
    for w in PER_WORD_LIMIT1:
        hits = scan(clines, [w], regex=False)
        limit = 2 if reg == "buzz" else 1
        if len(hits) > limit:
            density_over += 1
            density_report.append((f"A系 同一語反復「{w}」", len(hits), limit, True,
                                   "同一の転用動詞・強調語は1記事1回", hits[:4]))
    # A-1 転用ペア（上限=1,000字1回×レジスター係数。納品は実質0回）
    total_chars = sum(len(ln) for ln in lines)
    pair_hits = scan(clines, TENYO_PAIRS)
    pair_limit = math.floor(max(1, total_chars // 1000) * mult)
    if pair_hits:
        over = len(pair_hits) > pair_limit
        density_over += over
        density_report.append(("A-1 転用ペア(確定)", len(pair_hits), pair_limit, over,
                               "本文1,000字あたり1回まで。標準語彙に開く", pair_hits[:4]))
    # 0回定型句・指紋
    zero_hits = scan(clines, ZERO_PHRASES, regex=False)
    # B-2 三連反復（連続3文の末尾3字一致。地の文=ひらがな終わりのみ対象、
    # 表ラベル・体言止めの列挙は誤検知になるため除外）
    triple = []
    prose = [(i, s) for i, s in sents if re.search(r"[ぁ-ん]$", s)]
    for k in range(len(prose) - 2):
        e = [s[-3:] for _, s in prose[k:k+3]]
        if e[0] == e[1] == e[2]:
            triple.append((prose[k][0], f"…{e[0]}×3連続", prose[k][1][-24:]))
    # B-10 文体混在（全レジスター0回）
    kei = [(i, s) for i, s in sents if KEITAI_RE.search(s)]
    jou = [(i, s) for i, s in sents if not KEITAI_RE.search(s) and JOUTAI_RE.search(s)]
    mixed = []
    if len(kei) + len(jou) >= 8 and kei and jou:
        minority = kei if len(kei) < len(jou) else jou
        if len(minority) / (len(kei) + len(jou)) < 0.3:
            mixed = [(i, "文体混在(少数派)", s[-30:]) for i, s in minority[:5]]

    # ---- SHOULD / INFO ----
    should = scan(lines, AI_FAVORED, regex=False) + scan(lines, CHAPTER_ANNOUNCE, regex=False)
    info = scan(lines, MONEY_PATTERNS) if args.type in ("deck", "report", "mail") else []

    # ══ 出力 ══
    print(f"## writing-lint v2: {path.name} (type={args.type}, register={reg}, {len(lines)}行/{len(sents)}文)")
    print(f"\n### FATAL: {len(fatal)}件（個人名・慣用句混交・壊れ句読点）")
    for i, w, c in sorted(set(fatal)):
        print(f"- L{i}: 「{w}」 → {c}")

    print(f"\n### DENSITY: 超過{density_over}カウンタ（法則1: 間引いて上限内に。全削除はしない）")
    for name, n, limit, over, note, hits in density_report:
        mark = "🔴超過" if over else "OK"
        print(f"- [{mark}] {name}: {n}回 / 上限{limit}（{note}）")
        if over:
            for i, w, c in hits:
                print(f"    L{i}: {c}")
    if zero_hits:
        density_over += 1
        print(f"- [🔴超過] 指紋・0回定型句: {len(zero_hits)}回 / 上限0（法則6: 固定フレーズは1件でNG）")
        for i, w, c in sorted(set(zero_hits))[:6]:
            print(f"    L{i}: 「{w}」 → {c}")
    if triple:
        density_over += 1
        print(f"- [🔴超過] B-2 三連反復: {len(triple)}箇所（2回目以降は形を変える・法則3）")
        for i, w, c in triple[:4]:
            print(f"    L{i}: {w}（{c}）")
    if mixed:
        density_over += 1
        print(f"- [🔴超過] B-10 文体混在: 少数派{len(mixed)}文（全レジスター0回・要目視確認）")
        for i, w, c in mixed:
            print(f"    L{i}: …{c}")

    watch = [(n, scan(clines, [p])) for n, p in WATCH_VERBS]
    watch = [(n, h) for n, h in watch if len(h) >= 2]
    if watch:
        print("\n### WATCH（転用動詞・参考カウント: 違反ではない。転用か実体ある用法か目視判断）")
        for n, h in watch:
            locs = ",".join(f"L{i}" for i, _, _ in h[:5])
            print(f"- {n}: {len(h)}回（{locs}） 例: {h[0][2]}")

    print(f"\n### SHOULD: {len(should)}件（偏愛語・章境界。正当用法は理由つきでOK可）")
    for i, w, c in sorted(set(should))[:12]:
        print(f"- L{i}: 「{w}」 → {c}")
    print(f"\n### INFO(要人間確認): {len(info)}件")
    for i, w, c in sorted(set(info)):
        print(f"- L{i}: 「{w}」 → {c}")

    print(f"\n### 判定: FATAL {len(fatal)} / DENSITY超過 {density_over} / SHOULD {len(should)}")
    if fatal:
        print("→ FATALを修正するまで書き出し禁止（exit 1）")
        return 1
    if density_over:
        print("→ DENSITY超過あり。上限内まで間引く（超過のまま出すなら書き手の判断）")
    else:
        print("→ FATAL・DENSITY超過なし。SHOULDは文脈判断のうえ対応")
    return 0


if __name__ == "__main__":
    sys.exit(main())
