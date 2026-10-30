"""PAR sheet: exact probability and payout accounting of the saved reel sets.

    python -m slot_reel_designer.report [--out-dir DIR]

Reads configs/reels.json (sum_all, primary) and configs/reels_full_only.json
(full_only, alternative) and writes docs/par-sheet.md in English and
docs/par-sheet.zh-TW.md in Traditional Chinese. Each page covers the reel
strips, per-reel symbol counts, pairs and triples, hits and RTP by pattern
and symbol, per-pattern and per-symbol totals, the overall RTP, hit rate
and win rate above bet, the payout distribution and the standard deviation
of the payout per spin. Every number comes from the exact evaluator, so
the pages are deterministic; tests check that the committed pages are
current.
"""

from __future__ import annotations

import argparse
import math
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

from .evaluator import Evaluation, evaluate, outcome_counts, payout_distribution, payout_variance
from .files import save
from .game import (
    FULL_SCREEN,
    FULL_SCREEN_FACTOR,
    MULTIPLIERS,
    PATTERNS,
    SYMBOLS,
    PayoutMode,
    pattern_payouts,
)
from .search import CONFIG_DIR, CONFIG_PATHS, ReelCounts, count_reels, load_config

Reels = tuple[tuple[int, ...], ...]

ROOT = CONFIG_DIR.parent
DOCS_DIR = ROOT / "docs"
REPORT_PATHS = {"en": DOCS_DIR / "par-sheet.md", "zh-TW": DOCS_DIR / "par-sheet.zh-TW.md"}
GENERATOR = "python -m slot_reel_designer.report"


def pays(name: str, symbol: int) -> Fraction:
    """What pattern ``name`` pays when it is paid on ``symbol``, for a bet of 1."""
    return MULTIPLIERS[symbol] * (FULL_SCREEN_FACTOR if name == FULL_SCREEN else 1)


@dataclass(frozen=True)
class ParSheet:
    """Exact PAR data of one reel set; counts are numbers of stop combinations (spins)."""

    source: str  # config path shown on the page
    mode: PayoutMode
    reels: Reels
    counts: tuple[ReelCounts, ...]
    evaluation: Evaluation
    hits: dict[tuple[str, int], int]  # (pattern, symbol): spins on which it hits
    paid: dict[tuple[str, int], int]  # ... and on which that hit is paid
    wins: dict[int, int]  # symbol: spins that win on it
    distribution: dict[Fraction, Fraction]  # payout: probability
    variance: Fraction  # of the payout per spin

    def contribution(self, name: str, symbol: int) -> Fraction:
        """RTP paid through pattern ``name`` on ``symbol``."""
        return pays(name, symbol) * self.paid[name, symbol] / self.evaluation.total_outcomes


def build_sheet(mode: PayoutMode | str, reels: Sequence[Sequence[int]], source: str) -> ParSheet:
    """Compute the PAR data of ``reels`` under ``mode``."""
    mode = PayoutMode(mode)
    counts = count_reels(reels)
    strips = tuple(tuple(reel) for reel in reels)
    keys = [(name, x) for name in PATTERNS for x in SYMBOLS]
    hits, paid = Counter(dict.fromkeys(keys, 0)), Counter(dict.fromkeys(keys, 0))
    wins = Counter(dict.fromkeys(SYMBOLS, 0))
    for key, count in outcome_counts(strips).items():
        hit = dict(key)
        paid_names = pattern_payouts(hit, mode)
        for name, x in hit.items():
            hits[name, x] += count
            if name in paid_names:
                paid[name, x] += count
        for x in set(hit.values()):
            wins[x] += count
    distribution = payout_distribution(strips, mode)
    return ParSheet(
        source=source,
        mode=mode,
        reels=strips,
        counts=counts,
        evaluation=evaluate(strips, mode),
        hits=dict(hits),
        paid=dict(paid),
        wins=dict(wins),
        distribution=distribution,
        variance=payout_variance(distribution),
    )


def load_sheets(paths: Iterable[Path] = CONFIG_PATHS.values()) -> list[ParSheet]:
    """PAR data of saved configs, by default both of them, primary first."""
    sheets = []
    for path in paths:
        mode, reels = load_config(path)
        try:
            source = str(path.resolve().relative_to(ROOT))
        except ValueError:
            source = path.name
        sheets.append(build_sheet(mode, reels, source))
    return sheets


# --------------------------------------------------------------------------- formatting


def amount(value: Fraction) -> str:
    """Exact decimal form of a payout (multiples of 1/20 always terminate)."""
    text = f"{Decimal(value.numerator) / Decimal(value.denominator):f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def decimal(value: Fraction | float) -> str:
    """Fixed-point decimal with at least 6 places and 4 significant digits."""
    x = float(value)
    if x == 0:
        return "0"
    places = max(6, 3 - math.floor(math.log10(abs(x))))
    return f"{x:.{places}f}"


def _one_in(p: Fraction) -> str:
    """1 / p, the mean number of spins between events of probability p."""
    if p == 0:
        return "—"
    v = 1 / float(p)
    return f"{v:,.2f}" if v < 100 else f"{v:,.0f}"


def _share(part: Fraction, whole: Fraction) -> str:
    """``part`` as a percentage of ``whole``."""
    return f"{float(part / whole):.2%}" if whole else "—"


def _per_reel(values: Iterable[int]) -> str:
    """One number per reel: 'a / b / c'."""
    return " / ".join(f"{v:,}" for v in values)


def _runs(strip: Sequence[int]) -> str:
    """The strip as symbol×length runs from index 0, without joining the ends."""
    runs: list[list[int]] = []
    for x in strip:
        if runs and runs[-1][0] == x:
            runs[-1][1] += 1
        else:
            runs.append([x, 1])
    return " ".join(f"{x}×{k}" for x, k in runs)


def _table(header: Sequence[str], align: str, rows: Iterable[Sequence[str]]) -> list[str]:
    """A Markdown table; ``align`` has one 'l' or 'r' per column."""
    rule = ["---:" if a == "r" else "---" for a in align]
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join(rule) + "|"]
    return lines + ["| " + " | ".join(row) + " |" for row in rows]


# --------------------------------------------------------------------------- text

TEXT: dict[str, dict[str, str]] = {
    "en": {
        "title": "# PAR Sheet",
        "languages": "English | [繁體中文](par-sheet.zh-TW.md)",
        "generated": (
            "> **Generated file; do not edit by hand.** Regenerate it with `{generator}` "
            "after a config changes."
        ),
        "intro": (
            "Probability accounting report (PAR sheet) for the final reel sets. Every number "
            "is exact: it is counted over all L1 × L2 × L3 equally likely stop combinations, "
            "called *spins* below, with integers and fractions. The bet is 1, so payouts are "
            "multiples of the bet and the RTP is the expected payout per spin. For the Monte "
            "Carlo cross-check, run `python -m slot_reel_designer.verify`."
        ),
        "summary": "## Summary",
        "summary_header": (
            "Config|Design|Mode|Reel lengths|Spins|RTP|Hit rate (payout > 0)"
            "|Win rate (payout > bet)|Payout s.d."
        ),
        "primary": "Primary",
        "alternative": "Alternative",
        "paytable": "## Paytable",
        "paytable_header": (
            "Symbol|Multiplier m|Each 2×2 block (A–D)|Full screen (E) alone"
            "|Full-screen spin, `sum_all` (4m + 5m)|Full-screen spin, `full_only` (5m)"
        ),
        "paytable_note": (
            "Patterns A, B, C and D are the top-left, top-right, bottom-left and bottom-right "
            "2×2 blocks; E is the full screen. A full screen also completes all four blocks: "
            "`sum_all` pays all five patterns, `full_only` pays E alone."
        ),
        "section": "## {role} design: `{mode}` (`{source}`)",
        "overview": "### Overview",
        "overview_header": "Metric|Exact|Decimal",
        "rtp": "RTP",
        "hit_rate": "Hit rate (payout > 0)",
        "above_bet": "Win rate (payout > bet)",
        "spins": "Spins (stop combinations)",
        "variance": "Payout variance per spin",
        "sd": "Payout standard deviation per spin (volatility)",
        "strips": "### Reel strips",
        "strips_note": (
            "Runs are listed from index 0 as symbol×length; each strip wraps around from its "
            "last symbol to its first."
        ),
        "strips_header": "Reel|Length|Runs",
        "full_strips": "Full strips:",
        "counts": "### Symbol counts per reel",
        "counts_note": (
            "*Pairs* count the cyclic positions i with r[i] = r[i+1] = x and *triples* those "
            "with r[i] = r[i+1] = r[i+2] = x. With the reel lengths, these counts determine "
            "every probability on this page."
        ),
        "counts_header": "Symbol|Count (R1 / R2 / R3)|Pairs (R1 / R2 / R3)|Triples (R1 / R2 / R3)",
        "total": "Total",
        "by_pattern_symbol": "### Hits by pattern and symbol",
        "by_pattern_symbol_note": (
            "*Hits* are the spins on which the pattern shows the symbol on all of its cells; "
            "*paid* are the hits that pay. Under `full_only` a 2×2 block is not paid on a full "
            "screen, so it is paid less often than it hits. RTP contribution = pays × paid / "
            "spins."
        ),
        "by_pattern_symbol_header": (
            "Pattern|Symbol|Pays|Hits|Paid|Probability|1 in|RTP contribution"
        ),
        "by_pattern": "### By pattern",
        "by_pattern_header": "Pattern|Hits|Probability|1 in|RTP contribution|Share of RTP",
        "by_symbol": "### By symbol",
        "by_symbol_note": (
            "Every pattern covers the middle reel, so all wins of one spin are on one symbol, "
            "and the per-symbol win probabilities add up to the hit rate."
        ),
        "by_symbol_header": (
            "Symbol|Multiplier|Winning spins|Probability|1 in|RTP contribution|Exact|Share of RTP"
        ),
        "distribution": "### Payout distribution",
        "distribution_note": (
            "Each distinct payout of one spin (the sum of its paid patterns) with its "
            "probability. The standard deviation above is that of this distribution."
        ),
        "distribution_header": "Payout|Spins|Probability|1 in|RTP contribution",
    },
    "zh-TW": {
        "title": "# PAR Sheet（機率與派彩明細）",
        "languages": "[English](par-sheet.md) | 繁體中文",
        "generated": (
            "> **本檔案由程式自動產生，請勿手動編輯。** 設定檔變更後，請執行 `{generator}` "
            "重新產生。"
        ),
        "intro": (
            "最終 reel 設計的機率與派彩明細（PAR sheet）。所有數字都是精確值：在 "
            "L1 × L2 × L3 種機率相同的 stop 組合（下文稱為 *spin*）上，以整數與分數逐一計數"
            "而得。押注為 1，因此 payout 即為押注的倍數，RTP 就是每次 spin 的期望 payout。"
            "Monte Carlo 交叉驗證請執行 `python -m slot_reel_designer.verify`。"
        ),
        "summary": "## 摘要",
        "summary_header": (
            "設定檔|設計|模式|Reel 長度|Spin 總數|RTP|勝率（payout > 0）"
            "|勝率（payout > 押注）|Payout 標準差"
        ),
        "primary": "主要",
        "alternative": "替代",
        "paytable": "## 賠率表",
        "paytable_header": (
            "符號|倍率 m|每個 2×2 方塊（A–D）|全盤（E）本身"
            "|全盤 spin，`sum_all`（4m + 5m）|全盤 spin，`full_only`（5m）"
        ),
        "paytable_note": (
            "型態 A、B、C、D 分別是左上、右上、左下、右下的 2×2 方塊，E 是全盤。全盤中獎時，"
            "4 個 2×2 方塊也同時成立：`sum_all` 五個型態全部派彩，`full_only` 只派全盤（E）。"
        ),
        "section": "## {role}設計：`{mode}`（`{source}`）",
        "overview": "### 總覽",
        "overview_header": "指標|精確值|小數",
        "rtp": "RTP",
        "hit_rate": "勝率（payout > 0）",
        "above_bet": "勝率（payout > 押注）",
        "spins": "Spin 總數（stop 組合數）",
        "variance": "每次 spin payout 的變異數",
        "sd": "每次 spin payout 的標準差（波動度）",
        "strips": "### Reel strip",
        "strips_note": "以「符號×長度」列出從 index 0 開始的連續區段；每條 strip 頭尾相接。",
        "strips_header": "Reel|長度|連續區段",
        "full_strips": "完整 strip：",
        "counts": "### 各 reel 的符號統計",
        "counts_note": (
            "*成對數* 是滿足 r[i] = r[i+1] = x 的循環位置 i 的個數，*三連數* 是滿足 "
            "r[i] = r[i+1] = r[i+2] = x 的個數。加上 reel 長度，這些數字就決定了本頁的所有機率。"
        ),
        "counts_header": "符號|個數（R1 / R2 / R3）|成對數（R1 / R2 / R3）|三連數（R1 / R2 / R3）",
        "total": "合計",
        "by_pattern_symbol": "### 各型態與符號的中獎統計",
        "by_pattern_symbol_note": (
            "*中獎次數* 是該型態所有格子都顯示該符號的 spin 數；*派彩次數* 是其中實際派彩的次數。"
            "`full_only` 模式下，全盤時 2×2 方塊不派彩，所以派彩次數會少於中獎次數。"
            "RTP 貢獻 = 派彩金額 × 派彩次數 ÷ spin 總數。"
        ),
        "by_pattern_symbol_header": "型態|符號|派彩金額|中獎次數|派彩次數|機率|1 / 機率|RTP 貢獻",
        "by_pattern": "### 各型態合計",
        "by_pattern_header": "型態|中獎次數|機率|1 / 機率|RTP 貢獻|佔 RTP 比例",
        "by_symbol": "### 各符號合計",
        "by_symbol_note": (
            "每個型態都涵蓋中間的 reel，所以同一次 spin 的所有中獎都是同一個符號，"
            "各符號的中獎機率加總即為勝率。"
        ),
        "by_symbol_header": "符號|倍率|中獎 spin 數|機率|1 / 機率|RTP 貢獻|精確值|佔 RTP 比例",
        "distribution": "### Payout 分布",
        "distribution_note": (
            "單次 spin 的每一種 payout（所有派彩型態的總和）及其機率。上方的標準差即為此分布的標準差。"
        ),
        "distribution_header": "Payout|Spin 數|機率|1 / 機率|RTP 貢獻",
    },
}


# --------------------------------------------------------------------------- rendering


def _role(sheet: ParSheet, t: dict[str, str]) -> str:
    """'Primary' for sum_all, 'Alternative' for full_only, in the page's language."""
    return t["primary"] if sheet.mode is PayoutMode.SUM_ALL else t["alternative"]


def _summary(sheets: Sequence[ParSheet], t: dict[str, str]) -> list[str]:
    """One row per reel set."""
    rows = []
    for sheet in sheets:
        ev = sheet.evaluation
        rows.append([
            f"[`{sheet.source}`](../{sheet.source})",
            _role(sheet, t),
            f"`{sheet.mode}`",
            _per_reel(len(reel) for reel in sheet.reels),
            f"{ev.total_outcomes:,}",
            str(ev.rtp),
            decimal(ev.hit_rate),
            decimal(ev.win_rate_above_bet),
            decimal(math.sqrt(sheet.variance)),
        ])
    return [t["summary"], "", *_table(t["summary_header"].split("|"), "lllrrlrrr", rows)]


def _paytable(t: dict[str, str]) -> list[str]:
    """Multipliers and what each pattern pays."""
    rows = [
        [str(x), amount(m), amount(pays("A", x)), amount(pays(FULL_SCREEN, x)),
         amount(4 * m + pays(FULL_SCREEN, x)), amount(pays(FULL_SCREEN, x))]
        for x, m in MULTIPLIERS.items()
    ]
    table = _table(t["paytable_header"].split("|"), "lrrrrr", rows)
    return [t["paytable"], "", *table, "", t["paytable_note"]]


def _section(sheet: ParSheet, t: dict[str, str]) -> list[str]:
    """Everything about one reel set."""
    ev = sheet.evaluation
    n = ev.total_outcomes
    out = [t["section"].format(role=_role(sheet, t), mode=sheet.mode, source=sheet.source), ""]

    out += [t["overview"], ""]
    out += _table(t["overview_header"].split("|"), "lrr", [
        [t["rtp"], str(ev.rtp), decimal(ev.rtp)],
        [t["hit_rate"], str(ev.hit_rate), decimal(ev.hit_rate)],
        [t["above_bet"], str(ev.win_rate_above_bet), decimal(ev.win_rate_above_bet)],
        [t["spins"], f"{n:,}", ""],
        [t["variance"], str(sheet.variance), decimal(sheet.variance)],
        [t["sd"], "", decimal(math.sqrt(sheet.variance))],
    ])

    out += ["", t["strips"], "", t["strips_note"], ""]
    out += _table(t["strips_header"].split("|"), "lrl", [
        [str(i), str(len(reel)), _runs(reel)] for i, reel in enumerate(sheet.reels, start=1)
    ])
    out += ["", t["full_strips"], "", "```text"]
    out += [f"reel {i}: {list(reel)}" for i, reel in enumerate(sheet.reels, start=1)]
    out += ["```"]

    out += ["", t["counts"], "", t["counts_note"], ""]
    rows = [
        [str(x), _per_reel(reel.count(x) for reel in sheet.reels),
         _per_reel(c.pairs[x] for c in sheet.counts),
         _per_reel(c.triples[x] for c in sheet.counts)]
        for x in SYMBOLS
    ]
    rows.append([
        t["total"], _per_reel(c.length for c in sheet.counts),
        _per_reel(sum(c.pairs) for c in sheet.counts),
        _per_reel(sum(c.triples) for c in sheet.counts),
    ])
    out += _table(t["counts_header"].split("|"), "llll", rows)

    out += ["", t["by_pattern_symbol"], "", t["by_pattern_symbol_note"], ""]
    rows = []
    for name in PATTERNS:
        for x in SYMBOLS:
            p = Fraction(sheet.hits[name, x], n)
            rows.append([
                name, str(x), amount(pays(name, x)), f"{sheet.hits[name, x]:,}",
                f"{sheet.paid[name, x]:,}", decimal(p), _one_in(p),
                decimal(sheet.contribution(name, x)),
            ])
    out += _table(t["by_pattern_symbol_header"].split("|"), "llrrrrrr", rows)

    out += ["", t["by_pattern"], ""]
    rows = [
        [name, f"{sum(sheet.hits[name, x] for x in SYMBOLS):,}",
         decimal(ev.pattern_hit_prob[name]), _one_in(ev.pattern_hit_prob[name]),
         decimal(ev.rtp_by_pattern[name]), _share(ev.rtp_by_pattern[name], ev.rtp)]
        for name in PATTERNS
    ]
    rows.append([t["total"], "", "", "", decimal(ev.rtp), _share(ev.rtp, ev.rtp)])
    out += _table(t["by_pattern_header"].split("|"), "lrrrrr", rows)

    out += ["", t["by_symbol"], "", t["by_symbol_note"], ""]
    rows = []
    for x in SYMBOLS:
        p = Fraction(sheet.wins[x], n)
        rtp = ev.rtp_by_symbol[x]
        rows.append([
            str(x), amount(MULTIPLIERS[x]), f"{sheet.wins[x]:,}", decimal(p), _one_in(p),
            decimal(rtp), str(rtp), _share(rtp, ev.rtp),
        ])
    rows.append([
        t["total"], "", f"{sum(sheet.wins.values()):,}", decimal(ev.hit_rate),
        _one_in(ev.hit_rate), decimal(ev.rtp), str(ev.rtp), _share(ev.rtp, ev.rtp),
    ])
    out += _table(t["by_symbol_header"].split("|"), "lrrrrrrr", rows)

    out += ["", t["distribution"], "", t["distribution_note"], ""]
    rows = [
        [amount(value), f"{int(p * n):,}", decimal(p), _one_in(p), decimal(value * p)]
        for value, p in sheet.distribution.items()
    ]
    rows.append([t["total"], f"{n:,}", "1", "", decimal(ev.rtp)])
    out += _table(t["distribution_header"].split("|"), "rrrrr", rows)
    return out


def render(sheets: Sequence[ParSheet], lang: str) -> str:
    """The PAR sheet page in ``lang`` ('en' or 'zh-TW')."""
    t = TEXT[lang]
    sources = " and ".join(sheet.source for sheet in sheets)
    lines = [
        f"<!-- Generated by `{GENERATOR}` from {sources}; do not edit by hand. -->",
        "",
        t["title"],
        "",
        t["languages"],
        "",
        t["generated"].format(generator=GENERATOR),
        "",
        t["intro"],
        "",
        *_summary(sheets, t),
        "",
        *_paytable(t),
    ]
    for sheet in sheets:
        lines += ["", *_section(sheet, t)]
    return "\n".join(lines) + "\n"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse the command line."""
    parser = argparse.ArgumentParser(
        prog=GENERATOR, description="Write the PAR sheet pages from the saved configs."
    )
    parser.add_argument(
        "--out-dir", type=Path, default=DOCS_DIR, help="output directory (default: docs/)"
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Render both pages from both configs and write them; return the exit code."""
    args = parse_args(argv)
    sheets = load_sheets()
    for lang, path in REPORT_PATHS.items():
        out = args.out_dir / path.name
        print(f"wrote {out} ({save(render(sheets, lang), out)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
