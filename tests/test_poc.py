"""Tests for the proof-of-concept reel family and its saved configuration."""

import json
from dataclasses import replace
from fractions import Fraction

import pytest

from slot_reel_designer.evaluator import evaluate, evaluate_bruteforce
from slot_reel_designer.game import PayoutMode, validate_reels
from slot_reel_designer.poc import (
    CONFIG_PATH,
    MIDDLE_REEL,
    MIN_HIT_RATE,
    TARGET_RTP,
    build_reels,
    meets_targets,
    scan,
    to_config,
    zero_run_strip,
)

SUM_ALL = PayoutMode.SUM_ALL
FULL_ONLY = PayoutMode.FULL_ONLY
CONFIG_KEYS = {
    "mode",
    "reels",
    "rtp",
    "hit_rate",
    "hit_rate_decimal",
    "win_rate_above_bet",
    "total_outcomes",
}


def family_params(max_length: int) -> list[tuple[int, int, int, int]]:
    """All (L1, k1, L3, k3) with 2 <= k < L <= max_length."""
    return [
        (l1, k1, l3, k3)
        for l1 in range(3, max_length + 1)
        for k1 in range(2, l1)
        for l3 in range(3, max_length + 1)
        for k3 in range(2, l3)
    ]


def family_rtp(l1: int, k1: int, l3: int, k3: int, mode: PayoutMode) -> Fraction:
    """Closed-form RTP from docs/poc.md.

    A and C pay 1/4 when the left column shows a zero pair on their rows
    (k1 - 1 stops each), B and D likewise on the right, and a full screen
    needs three zeros in both outer columns. Under sum_all it adds E's 5/4
    on top of the four blocks; under full_only it replaces their 4 * 1/4.
    """
    full_screen_extra = Fraction(5, 4) if mode is SUM_ALL else Fraction(1, 4)
    return (
        Fraction(k1 - 1, 2 * l1)
        + Fraction(k3 - 1, 2 * l3)
        + full_screen_extra * Fraction((k1 - 2) * (k3 - 2), l1 * l3)
    )


def family_hit_rate(l1: int, k1: int, l3: int, k3: int) -> Fraction:
    """Closed-form hit rate: k of an outer reel's L windows hold a zero pair."""
    return 1 - (1 - Fraction(k1, l1)) * (1 - Fraction(k3, l3))


STRIP_SIZES = [(k, n) for n in range(1, 13) for k in range(1, n + 1)]  # (zeros, length)

# Every (L1, k1, L3, k3) that scan(40) returns, in order (docs/poc.md).
SCAN_40 = {
    SUM_ALL: [
        (5, 4, 10, 8),
        (10, 6, 15, 12),
        (10, 5, 17, 16),
        (15, 9, 15, 11),
        (15, 11, 15, 9),
        (10, 5, 24, 22),
        (15, 7, 19, 17),
        (5, 4, 30, 21),
        (10, 6, 25, 19),
        (10, 7, 25, 16),
        (6, 5, 30, 18),
    ],
    FULL_ONLY: [(10, 9, 23, 20), (15, 12, 18, 17)],
}


def mirrored(params: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """The parameters of the left-right mirror image."""
    l1, k1, l3, k3 = params
    return l3, k3, l1, k1


class TestZeroRunStrip:
    @pytest.mark.parametrize(("zeros", "length"), STRIP_SIZES)
    def test_layout(self, zeros, length):
        strip = zero_run_strip(zeros, length)
        assert len(strip) == length
        assert validate_reels([strip, strip, strip])[0] == strip
        assert strip[:zeros] == (0,) * zeros
        assert all(symbol != 0 for symbol in strip[zeros:])

    @pytest.mark.parametrize(("zeros", "length"), STRIP_SIZES)
    def test_only_the_zero_run_has_equal_neighbours(self, zeros, length):
        """Cyclically, equal neighbours appear only inside the zero run (k - 1 pairs)."""
        strip = zero_run_strip(zeros, length)
        equal = [i for i in range(length) if strip[i] == strip[(i + 1) % length]]
        if zeros < length:
            assert equal == list(range(zeros - 1))
        else:  # an all-zero strip wraps onto itself
            assert equal == list(range(length))

    def test_examples(self):
        assert zero_run_strip(4, 5) == (0, 0, 0, 0, 1)
        assert zero_run_strip(8, 10) == (0,) * 8 + (1, 2)
        assert zero_run_strip(2, 7) == (0, 0, 1, 2, 1, 2, 1)
        assert zero_run_strip(3, 3) == (0, 0, 0)

    @pytest.mark.parametrize(("zeros", "length"), [(0, 5), (-1, 5), (6, 5), (1, 0)])
    def test_rejects_bad_sizes(self, zeros, length):
        with pytest.raises(ValueError):
            zero_run_strip(zeros, length)


class TestFamily:
    def test_build_reels(self):
        assert build_reels(5, 4, 10, 8) == (
            (0, 0, 0, 0, 1),
            MIDDLE_REEL,
            (0, 0, 0, 0, 0, 0, 0, 0, 1, 2),
        )
        assert set(MIDDLE_REEL) == {0}

    @pytest.mark.parametrize("mode", [SUM_ALL, FULL_ONLY])
    def test_closed_form_matches_evaluator(self, mode):
        """The formulas in docs/poc.md agree with the exact evaluator."""
        for params in family_params(7):
            ev = evaluate(build_reels(*params), mode)
            assert ev.rtp == family_rtp(*params, mode), params
            assert ev.hit_rate == family_hit_rate(*params), params

    @pytest.mark.parametrize("params", [(5, 4, 10, 8), (3, 2, 4, 3), (6, 3, 7, 5)])
    @pytest.mark.parametrize("mode", [SUM_ALL, FULL_ONLY])
    def test_evaluator_matches_bruteforce(self, params, mode):
        reels = build_reels(*params)
        assert evaluate(reels, mode) == evaluate_bruteforce(reels, mode)


class TestScan:
    def test_smallest_sum_all_solution(self):
        solutions = scan(18)
        assert solutions, "expected at least one solution with total length 18"
        best = solutions[0]
        assert best.params == (5, 4, 10, 8)
        assert best.total_length == 18
        assert best.mode is SUM_ALL
        assert best.evaluation.rtp == TARGET_RTP
        assert best.evaluation.hit_rate == Fraction(24, 25)

    def test_nothing_shorter(self):
        assert scan(17) == []

    def test_every_solution_is_exact_and_sorted(self):
        solutions = scan(28)
        assert len(solutions) >= 2
        keys = [(s.total_length, s.params) for s in solutions]
        assert keys == sorted(keys)
        for solution in solutions:
            l1, _, l3, _ = solution.params
            assert l1 <= l3
            assert solution.total_length <= 28
            assert solution.reels == build_reels(*solution.params)
            assert solution.evaluation == evaluate(solution.reels)
            assert meets_targets(solution.evaluation)

    @pytest.mark.parametrize(
        ("params", "hit_rate"),
        [((10, 9, 23, 20), Fraction(227, 230)), ((15, 12, 18, 17), Fraction(89, 90))],
    )
    def test_full_only_alternatives(self, params, hit_rate):
        """The two full_only solutions of total length 36 quoted in docs/poc.md."""
        reels = build_reels(*params)
        assert sum(len(reel) for reel in reels) == 36
        ev = evaluate(reels, FULL_ONLY)
        assert ev.rtp == TARGET_RTP
        assert ev.hit_rate == hit_rate
        assert meets_targets(ev)
        assert ev == evaluate_bruteforce(reels, FULL_ONLY)
        assert evaluate(reels, SUM_ALL).rtp != TARGET_RTP

    def test_meets_targets_needs_exact_rtp_and_hit_rate(self):
        ev = evaluate(build_reels(5, 4, 10, 8))
        assert meets_targets(ev)
        assert not meets_targets(evaluate(build_reels(5, 3, 10, 8)))
        assert not meets_targets(evaluate(build_reels(5, 4, 10, 8), FULL_ONLY))

    def test_meets_targets_hit_rate_boundary(self):
        ev = evaluate(build_reels(5, 4, 10, 8))
        assert meets_targets(replace(ev, hit_rate=Fraction(11, 20)))
        assert not meets_targets(replace(ev, hit_rate=Fraction(1, 2)))
        assert not meets_targets(replace(ev, hit_rate=Fraction(10999, 20000)))

    @pytest.mark.parametrize("mode", [SUM_ALL, FULL_ONLY])
    def test_pinned_scan_40_matches_closed_form(self, mode):
        """The pinned lists follow from the closed forms in docs/poc.md (a fast stand-in)."""
        found = [
            (l1, k1, l3, k3)
            for l1 in range(3, 19)
            for l3 in range(l1, 38 - l1)
            for k1 in range(2, l1)
            for k3 in range(2, l3)
            if family_rtp(l1, k1, l3, k3, mode) == TARGET_RTP
            and family_hit_rate(l1, k1, l3, k3) >= MIN_HIT_RATE
        ]
        assert sorted(found, key=lambda p: (p[0] + p[2], p)) == SCAN_40[mode]

    def test_pinned_scan_40_up_to_mirroring(self):
        """11 sum_all solutions with L1 <= L3, 10 up to mirroring; 2 for full_only."""
        assert len(SCAN_40[SUM_ALL]) == 11
        assert len({min(p, mirrored(p)) for p in SCAN_40[SUM_ALL]}) == 10
        assert len({min(p, mirrored(p)) for p in SCAN_40[FULL_ONLY]}) == 2

    @pytest.mark.slow
    @pytest.mark.parametrize("mode", [SUM_ALL, FULL_ONLY])
    def test_scan_40(self, mode):
        """scan(40) itself (about 4 s per mode), the source of docs/poc.md's counts."""
        assert [s.params for s in scan(40, mode)] == SCAN_40[mode]


@pytest.fixture(scope="module")
def config() -> dict:
    """The saved proof-of-concept configuration."""
    return json.loads(CONFIG_PATH.read_text())


class TestSavedConfig:
    def test_keys(self, config):
        assert set(config) == CONFIG_KEYS
        assert config["mode"] == "sum_all"

    def test_meets_targets(self, config):
        ev = evaluate(config["reels"], config["mode"])
        assert ev.rtp == Fraction(19, 20)
        assert ev.hit_rate >= Fraction(11, 20)
        assert Fraction(config["rtp"]) == Fraction(19, 20)
        assert Fraction(config["hit_rate"]) >= MIN_HIT_RATE

    def test_stored_metrics_match_evaluator(self, config):
        ev = evaluate(config["reels"], config["mode"])
        assert config["rtp"] == "19/20"
        assert Fraction(config["hit_rate"]) == ev.hit_rate
        assert config["hit_rate_decimal"] == pytest.approx(float(ev.hit_rate))
        assert Fraction(config["win_rate_above_bet"]) == ev.win_rate_above_bet
        assert config["total_outcomes"] == ev.total_outcomes

    def test_evaluator_matches_bruteforce(self, config):
        reels, mode = config["reels"], config["mode"]
        assert evaluate(reels, mode) == evaluate_bruteforce(reels, mode)

    def test_is_the_smallest_scan_result(self, config):
        """The saved file is what `python -m slot_reel_designer.poc` writes."""
        assert config == to_config(scan(18)[0])
