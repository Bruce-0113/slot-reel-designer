"""Tests that the hand-written numbers in the READMEs and the methodology match the code."""

import json
import math
import re
from fractions import Fraction
from itertools import groupby

import pytest

from slot_reel_designer.evaluator import (
    Evaluation,
    evaluate,
    payout_distribution,
    payout_variance,
)
from slot_reel_designer.game import MULTIPLIERS, SYMBOLS, PayoutMode
from slot_reel_designer.search import CONFIG_DIR, CONFIG_PATHS, count_reels, symbol_hit_prob
from slot_reel_designer.simulate import Z95, simulate

ROOT = CONFIG_DIR.parent
LANGS = ["en", "zh-TW"]
README = {"en": ROOT / "README.md", "zh-TW": ROOT / "README.zh-TW.md"}
METHODOLOGY = {"en": ROOT / "docs" / "methodology.md", "zh-TW": ROOT / "docs/methodology.zh-TW.md"}
VERIFY_SPINS = 10_000_000  # `python -m slot_reel_designer.verify` defaults: 10**7 spins, seed 0


def result_sections(text: str) -> dict[PayoutMode, str]:
    """The README Result subsection of each config, keyed by its payout mode."""
    sections = {}
    for chunk in re.split(r"^#{2,3} ", text, flags=re.MULTILINE):
        heading = chunk.splitlines()[0] if chunk else ""
        for mode, path in CONFIG_PATHS.items():
            if f"(configs/{path.name})" in heading:
                sections[mode] = chunk
    return sections


def tables(text: str) -> list[list[list[str]]]:
    """Every Markdown table in ``text`` as rows of cells, header first, without the rule."""
    found: list[list[list[str]]] = []
    rows: list[list[str]] = []
    for line in [*text.splitlines(), ""]:
        if line.startswith("|"):
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if not all(set(cell) <= set("-:") for cell in cells):
                rows.append(cells)
        elif rows:
            found.append(rows)
            rows = []
    return found


def runs(reel) -> str:
    """symbol×length runs from index 0, as the strip tables write them."""
    return " ".join(f"{x}×{len(list(group))}" for x, group in groupby(reel))


@pytest.fixture(scope="module", params=LANGS)
def readme(request) -> dict[PayoutMode, str]:
    """The Result subsections of one README."""
    sections = result_sections(README[request.param].read_text())
    assert set(sections) == set(PayoutMode)
    return sections


@pytest.fixture(scope="module", params=list(PayoutMode), ids=str)
def mode(request) -> PayoutMode:
    """The payout mode whose Result subsection is under test."""
    return request.param


@pytest.fixture(scope="module")
def reels(mode) -> list[list[int]]:
    """The committed reels of ``mode``."""
    return json.loads(CONFIG_PATHS[mode].read_text())["reels"]


@pytest.fixture(scope="module")
def section_tables(readme, mode) -> list[list[list[str]]]:
    """Strip, metric and symbol tables of one Result subsection."""
    found = tables(readme[mode])
    assert len(found) == 3
    return found


def test_strip_table(section_tables, reels):
    rows = section_tables[0][1:]
    expected = [[str(i), str(len(reel)), f"`{runs(reel)}`"] for i, reel in enumerate(reels, 1)]
    assert rows == expected


def test_full_strips(readme, mode, reels):
    shown = re.findall(r"^reel (\d): (\[.*\])$", readme[mode], flags=re.MULTILINE)
    assert [(int(i), json.loads(strip)) for i, strip in shown] == list(enumerate(reels, 1))


def test_exact_metrics(section_tables, mode, reels):
    header, rtp, hit, above, sd = section_tables[1]
    ev = evaluate(reels, mode)
    assert f"{ev.total_outcomes:,}" in header[1]
    assert ev.rtp == Fraction(19, 20) and rtp[1] == "19/20 = 0.95"
    assert hit[1] == f"{ev.hit_rate} ≈ {float(ev.hit_rate):.6f}"
    assert above[1] == f"{ev.win_rate_above_bet} ≈ {float(ev.win_rate_above_bet):.6f}"
    assert sd[1] == f"{math.sqrt(payout_variance(payout_distribution(reels, mode))):.6f}"


def test_symbol_table(section_tables, mode, reels):
    ev = evaluate(reels, mode)
    hits = symbol_hit_prob(count_reels(reels))
    expected = [
        [
            str(x),
            f"{float(MULTIPLIERS[x]):g}",
            f"{float(hits[x]):.6f}",
            f"{float(ev.rtp_by_symbol[x]):.6f}",
        ]
        for x in SYMBOLS
    ]
    assert section_tables[2][1:] == expected


def signed(z: float) -> str:
    """A z-score as the docs write it, with a Unicode minus sign."""
    return f"{z:+.2f}".replace("-", "−")


def test_quoted_simulation_figures():
    """The simulation column and z-scores are `verify` with its defaults (under a second)."""
    z_scores = {}
    for mode, path in CONFIG_PATHS.items():
        reels = json.loads(path.read_text())["reels"]
        ev = evaluate(reels, mode)
        sim = simulate(reels, VERIFY_SPINS, mode, seed=0)
        estimates = [
            (sim.rtp_mean, sim.rtp_stderr, ev.rtp),
            (sim.hit_rate, sim.hit_rate_stderr, ev.hit_rate),
            (sim.win_rate_above_bet, sim.win_rate_above_bet_stderr, ev.win_rate_above_bet),
        ]
        z_scores[mode] = [(mean - float(exact)) / se for mean, se, exact in estimates]
        for lang in LANGS:
            metrics = tables(result_sections(README[lang].read_text())[mode])[1]
            for row, (mean, se, _) in zip(metrics[1:4], estimates):
                assert row[2] == f"{mean:.6f} ± {Z95 * se:.6f}"
            assert metrics[4][2] == f"{sim.payout_sd:.6f}"
    largest = max(abs(z) for zs in z_scores.values() for z in zs)
    assert all(f"|z| ≤ {largest:.2f}" in README[lang].read_text() for lang in LANGS)
    (a, b, c), (d, e, f) = ([signed(z) for z in z_scores[mode]] for mode in CONFIG_PATHS)
    english = METHODOLOGY["en"].read_text()
    assert f"z-scores are {a}, {b} and {c} (sum_all" in english
    assert f"and {d}, {e} and {f} (full_only)" in english
    chinese = METHODOLOGY["zh-TW"].read_text()
    assert f"z 值為 {a}、{b}、{c}（sum_all" in chinese
    assert f"與 {d}、{e}、{f}（full_only）" in chinese


@pytest.fixture(scope="module")
def evaluations() -> dict[PayoutMode, dict[PayoutMode, Evaluation]]:
    """Each committed config evaluated under both payout modes: [config mode][scored mode]."""
    out = {}
    for config_mode, path in CONFIG_PATHS.items():
        reels = json.loads(path.read_text())["reels"]
        out[config_mode] = {mode: evaluate(reels, mode) for mode in PayoutMode}
    return out


@pytest.mark.parametrize("lang", LANGS)
def test_methodology_figures(lang, evaluations):
    """Exact figures quoted in methodology sections 3 and 6 (both languages)."""
    text = METHODOLOGY[lang].read_text()
    sum_all, full_only = PayoutMode.SUM_ALL, PayoutMode.FULL_ONLY
    for mode in PayoutMode:
        n = evaluations[mode][mode].total_outcomes
        scaled = 20 * evaluations[mode][mode].rtp * n  # 20 * N * RTP, an integer
        assert scaled.denominator == 1
        assert f"{int(scaled):,} = 19 × {n:,}" in text
    for config_mode, other in [(sum_all, full_only), (full_only, sum_all)]:
        rtp = evaluations[config_mode][other].rtp
        assert f"{rtp} ≈ {float(rtp):.6f}" in text
    ev = evaluations[full_only][full_only]
    reels = json.loads(CONFIG_PATHS[full_only].read_text())["reels"]
    assert f"{float(ev.hit_rate):.6f}" in text
    assert f"{float(symbol_hit_prob(count_reels(reels))[0]):.2%}" in text
    assert f"{float(ev.rtp_by_symbol[0]):.6f}" in text


@pytest.mark.parametrize("lang", LANGS)
def test_full_screen_figures(lang, evaluations):
    """The 'full screen is not rare' note in methodology section 6."""
    figures = {}
    for mode in PayoutMode:
        ev = evaluations[mode][mode]
        p = ev.pattern_hit_prob["E"]
        figures[mode] = (p, p / ev.hit_rate, ev.rtp_by_pattern["E"] / ev.rtp)
    (p_sum, wins_sum, rtp_sum), (p_full, wins_full, rtp_full) = figures.values()
    assert Fraction(45, 100) < wins_sum < Fraction(55, 100)  # "about half"
    if lang == "en":
        quoted = (
            f"it hits on {float(p_sum):.1%} of sum_all spins (1 in {float(1 / p_sum):.2f}, "
            f"about half of the winning spins, {float(rtp_sum):.0%} of the RTP) and on "
            f"{float(p_full):.1%} of full_only spins ({float(wins_full):.0%} of the winning "
            f"spins, {float(rtp_full):.0%} of the RTP)"
        )
    else:
        quoted = (
            f"sum_all 下全盤出現在 {float(p_sum):.1%} 的 spin（約每 {float(1 / p_sum):.2f} 次一次，"
            f"約佔中獎 spin 的一半，貢獻 {float(rtp_sum):.0%} 的 RTP），full_only 下則為 "
            f"{float(p_full):.1%}（佔中獎 spin 的 {float(wins_full):.0%}，"
            f"貢獻 {float(rtp_full):.0%} 的 RTP）"
        )
    assert quoted in METHODOLOGY[lang].read_text()


def test_full_screens_are_almost_all_of_symbol_zero():
    """The note says 'almost always of symbol 0'."""
    for mode, path in CONFIG_PATHS.items():
        counts = count_reels(json.loads(path.read_text())["reels"])
        on_zero = math.prod(c.triples[0] for c in counts)
        every = sum(math.prod(c.triples[x] for c in counts) for x in SYMBOLS)
        assert on_zero / every > 0.99
