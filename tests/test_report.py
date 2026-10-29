"""Tests for the PAR sheet generator and the generated docs/par-sheet*.md."""

import re
from fractions import Fraction

import pytest

from slot_reel_designer import report
from slot_reel_designer.evaluator import evaluate, payout_distribution, payout_variance
from slot_reel_designer.game import MULTIPLIERS, PATTERNS, SYMBOLS, PayoutMode
from slot_reel_designer.search import CONFIG_PATHS, count_reels, load_config, symbol_hit_prob

SUM_ALL = PayoutMode.SUM_ALL
FULL_ONLY = PayoutMode.FULL_ONLY
LANGS = ["en", "zh-TW"]
# Hand-checked in test_evaluator: RTP 451/400 (sum_all), 407/400 (full_only), hit rate 9/10.
MIXED = ([1, 1, 1, 0], [1, 1, 1], [1, 1, 1, 0, 0])


@pytest.fixture(scope="module")
def sheets() -> list[report.ParSheet]:
    """PAR data of both saved configs, primary first."""
    return report.load_sheets()


def rendered_rtps(text: str) -> list[str]:
    """The exact RTP of each config section, as printed in its overview table."""
    return re.findall(r"^\| RTP \| (\d+/\d+|\d+) \| \d+\.\d{6} \|$", text, flags=re.MULTILINE)


class TestSheetData:
    def test_order_and_sources(self, sheets):
        assert [sheet.mode for sheet in sheets] == [SUM_ALL, FULL_ONLY]
        assert [sheet.source for sheet in sheets] == [
            "configs/reels.json",
            "configs/reels_full_only.json",
        ]

    def test_matches_the_evaluator(self, sheets):
        for sheet in sheets:
            mode, reels = load_config(CONFIG_PATHS[sheet.mode])
            assert (sheet.mode, sheet.reels) == (mode, reels)
            assert sheet.evaluation == evaluate(reels, mode)
            assert sheet.counts == count_reels(reels)
            assert sheet.distribution == payout_distribution(reels, mode)
            assert sheet.variance == payout_variance(sheet.distribution)

    @pytest.mark.parametrize("mode", list(PayoutMode))
    @pytest.mark.parametrize("reels", [MIXED, ([0], [0, 0], [0, 0, 0])])
    def test_breakdowns_add_up(self, sheets, reels, mode):
        for sheet in [*sheets, report.build_sheet(mode, reels, "mixed.json")]:
            ev, n = sheet.evaluation, sheet.evaluation.total_outcomes
            for name in PATTERNS:
                hits = sum(sheet.hits[name, x] for x in SYMBOLS)
                assert Fraction(hits, n) == ev.pattern_hit_prob[name]
                assert sum(sheet.contribution(name, x) for x in SYMBOLS) == ev.rtp_by_pattern[name]
                assert all(sheet.paid[name, x] <= sheet.hits[name, x] for x in SYMBOLS)
            for x in SYMBOLS:
                assert sum(sheet.contribution(name, x) for name in PATTERNS) == ev.rtp_by_symbol[x]
            wins = {x: Fraction(sheet.wins[x], n) for x in SYMBOLS}
            assert wins == symbol_hit_prob(sheet.counts)
            assert sum(wins.values()) == ev.hit_rate

    def test_full_only_does_not_pay_blocks_on_a_full_screen(self, sheets):
        full_only = sheets[1]
        for x in SYMBOLS:
            full = full_only.hits["E", x]
            assert full > 0
            assert all(full_only.paid[name, x] == full_only.hits[name, x] - full for name in "ABCD")
        sum_all = sheets[0]
        assert sum_all.paid == sum_all.hits

    def test_pays(self):
        assert report.pays("A", 1) == Fraction(11, 20)
        assert report.pays("E", 4) == 25


class TestRender:
    @pytest.mark.parametrize("lang", LANGS)
    def test_deterministic(self, lang):
        first, second = report.load_sheets(), report.load_sheets()
        assert report.render(first, lang) == report.render(second, lang)

    @pytest.mark.parametrize("lang", LANGS)
    def test_rendered_rtp_equals_the_evaluator(self, sheets, lang):
        text = report.render(sheets, lang)
        expected = [str(evaluate(sheet.reels, sheet.mode).rtp) for sheet in sheets]
        assert rendered_rtps(text) == expected == ["19/20", "19/20"]

    @pytest.mark.parametrize("lang", LANGS)
    @pytest.mark.parametrize(("mode", "rtp"), [(SUM_ALL, "451/400"), (FULL_ONLY, "407/400")])
    def test_rendered_rtp_of_other_reels(self, lang, mode, rtp):
        text = report.render([report.build_sheet(mode, MIXED, "mixed.json")], lang)
        assert rendered_rtps(text) == [rtp]
        assert "| 9/10 | 0.900000 |" in text  # hit rate

    @pytest.mark.parametrize("lang", LANGS)
    def test_tables(self, sheets, lang):
        text = report.render(sheets, lang)
        for sheet in sheets:
            n = sheet.evaluation.total_outcomes
            assert f"{n:,}" in text
            for reel in sheet.reels:
                assert str(list(reel)) in text  # the full strip
            for value, p in sheet.distribution.items():
                assert f"| {report.amount(value)} | {int(p * n):,} |" in text
        # 25 pattern x symbol rows per config
        rows = re.findall(r"^\| [A-E] \| [0-4] \| ", text, flags=re.MULTILINE)
        assert len(rows) == len(sheets) * len(PATTERNS) * len(SYMBOLS)

    def test_generated_marker_and_language_links(self, sheets):
        english = report.render(sheets, "en")
        chinese = report.render(sheets, "zh-TW")
        for text in (english, chinese):
            assert text.startswith("<!-- Generated by `python -m slot_reel_designer.report`")
            assert "do not edit by hand" in text.splitlines()[0]
            assert text.endswith("\n") and not text.endswith("\n\n")
        assert "English | [繁體中文](par-sheet.zh-TW.md)" in english
        assert "[English](par-sheet.md) | 繁體中文" in chinese
        assert "請勿手動編輯" in chinese

    def test_chinese_uses_taiwan_terms(self, sheets):
        chinese = report.render(sheets, "zh-TW")
        for term in ("機率", "變異數", "標準差", "勝率", "押注"):
            assert term in chinese
        for mainland in ("概率", "方差", "数", "设置", "默认"):
            assert mainland not in chinese

    def test_amount(self):
        assert report.amount(Fraction(0)) == "0"
        assert report.amount(Fraction(1, 4)) == "0.25"
        assert report.amount(Fraction(99, 20)) == "4.95"
        assert report.amount(Fraction(45)) == "45"
        assert [report.amount(m) for m in MULTIPLIERS.values()] == ["0.25", "0.55", "1", "3", "5"]

    def test_small_numbers_keep_four_significant_digits(self):
        assert report.decimal(Fraction(2, 3)) == "0.666667"
        assert report.decimal(Fraction(1, 95_000)) == "0.00001053"
        assert report.decimal(Fraction(0)) == "0"


class TestGeneratedDocs:
    @pytest.mark.parametrize("lang", LANGS)
    def test_committed_docs_are_up_to_date(self, sheets, lang):
        """Rerun `python -m slot_reel_designer.report` if this fails after a config change."""
        assert report.REPORT_PATHS[lang].read_text() == report.render(sheets, lang)

    def test_main_writes_both_pages(self, tmp_path, capsys):
        assert report.main(["--out-dir", str(tmp_path)]) == 0
        for lang, path in report.REPORT_PATHS.items():
            assert (tmp_path / path.name).read_text() == path.read_text()
        assert capsys.readouterr().out.count("(created)") == 2
        assert report.main(["--out-dir", str(tmp_path)]) == 0
        assert capsys.readouterr().out.count("(unchanged)") == 2
