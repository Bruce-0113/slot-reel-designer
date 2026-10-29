"""Tests for the exact evaluator, cross-checked against brute-force enumeration."""

import random
import time
from dataclasses import fields
from fractions import Fraction
from math import prod

import pytest

from slot_reel_designer.evaluator import (
    Evaluation,
    evaluate,
    evaluate_bruteforce,
    window_counts,
)
from slot_reel_designer.game import FULL_SCREEN_FACTOR, MULTIPLIERS, PATTERNS, PayoutMode

SUM_ALL = PayoutMode.SUM_ALL
FULL_ONLY = PayoutMode.FULL_ONLY
EVALUATORS = [evaluate, evaluate_bruteforce]
ZERO_BY_SYMBOL = dict.fromkeys(MULTIPLIERS, Fraction(0))


def assert_same(actual: Evaluation, expected: Evaluation) -> None:
    """Compare two evaluations field by field, for readable failures."""
    for field in fields(Evaluation):
        assert getattr(actual, field.name) == getattr(expected, field.name), field.name


def assert_consistent(ev: Evaluation) -> None:
    """Exact types, and breakdowns that add up to the RTP."""
    assert isinstance(ev.rtp, Fraction)
    assert list(ev.pattern_hit_prob) == list(PATTERNS)
    assert list(ev.rtp_by_pattern) == list(PATTERNS)
    assert list(ev.rtp_by_symbol) == list(MULTIPLIERS)
    assert sum(ev.rtp_by_pattern.values()) == ev.rtp
    assert sum(ev.rtp_by_symbol.values()) == ev.rtp
    assert 0 <= ev.win_rate_above_bet <= ev.hit_rate <= 1


class TestWindowCounts:
    def test_single_symbol_reel(self):
        assert window_counts([3]) == {(3, 3, 3): 1}

    def test_two_symbol_reel_wraps(self):
        assert window_counts([1, 2]) == {(1, 2, 1): 1, (2, 1, 2): 1}

    def test_three_symbol_reel_rotates(self):
        assert window_counts([0, 1, 2]) == {(0, 1, 2): 1, (1, 2, 0): 1, (2, 0, 1): 1}

    def test_counts_every_stop(self):
        assert window_counts([0, 0, 1, 0]) == {
            (0, 0, 1): 1,
            (0, 1, 0): 1,
            (1, 0, 0): 1,
            (0, 0, 0): 1,
        }
        assert window_counts([2, 2, 2, 2]) == {(2, 2, 2): 4}


@pytest.mark.parametrize("evaluator", EVALUATORS)
class TestHandComputed:
    ALL_ZERO = ([0], [0, 0], [0, 0, 0])

    def test_all_zero_sum_all(self, evaluator):
        # Every spin is a full screen of 0: 4 * 1/4 + 5 * 1/4 = 9/4.
        ev = evaluator(self.ALL_ZERO, SUM_ALL)
        assert ev.total_outcomes == 6
        assert ev.rtp == Fraction(9, 4)
        assert ev.hit_rate == 1
        assert ev.win_rate_above_bet == 1
        assert ev.pattern_hit_prob == dict.fromkeys(PATTERNS, Fraction(1))
        assert ev.rtp_by_pattern == {
            "A": Fraction(1, 4),
            "B": Fraction(1, 4),
            "C": Fraction(1, 4),
            "D": Fraction(1, 4),
            "E": Fraction(5, 4),
        }
        assert ev.rtp_by_symbol == {**ZERO_BY_SYMBOL, 0: Fraction(9, 4)}

    def test_all_zero_full_only(self, evaluator):
        # Every spin pays E alone: 5 * 1/4 = 5/4.
        ev = evaluator(self.ALL_ZERO, FULL_ONLY)
        assert ev.rtp == Fraction(5, 4)
        assert ev.hit_rate == 1
        assert ev.win_rate_above_bet == 1
        assert ev.pattern_hit_prob == dict.fromkeys(PATTERNS, Fraction(1))
        assert ev.rtp_by_pattern == {**dict.fromkeys("ABCD", Fraction(0)), "E": Fraction(5, 4)}
        assert ev.rtp_by_symbol == {**ZERO_BY_SYMBOL, 0: Fraction(5, 4)}

    def test_no_hits(self, evaluator):
        # Adjacent columns never share a vertical pair, so nothing can hit.
        ev = evaluator(([0, 1], [2, 3], [4]), SUM_ALL)
        assert ev.total_outcomes == 4
        assert ev.rtp == 0
        assert ev.hit_rate == 0
        assert ev.pattern_hit_prob == dict.fromkeys(PATTERNS, Fraction(0))
        assert_consistent(ev)

    def test_payout_equal_to_bet_is_not_above_bet(self, evaluator):
        # Windows: reel 1 (2,2,0) (2,0,2) (0,2,2); reel 2 (2,2,1) (2,1,2) (1,2,2);
        # reel 3 is all 3s, so only A and C can hit, each with symbol 2 paying 1.
        # A needs stops (0, 0), C needs stops (2, 2): 2 of 9 spins pay exactly 1.
        ev = evaluator(([2, 2, 0], [2, 2, 1], [3]), SUM_ALL)
        assert ev.total_outcomes == 9
        assert ev.rtp == Fraction(2, 9)
        assert ev.hit_rate == Fraction(2, 9)
        assert ev.win_rate_above_bet == 0
        assert ev.pattern_hit_prob == {
            **dict.fromkeys(PATTERNS, Fraction(0)),
            "A": Fraction(1, 9),
            "C": Fraction(1, 9),
        }
        assert ev.rtp_by_symbol == {**ZERO_BY_SYMBOL, 2: Fraction(2, 9)}

    # Reels R1 = [1,1,1,0], R2 = [1,1,1], R3 = [1,1,1,0,0]; m = 11/20 (symbol 1).
    # Windows by stop (wrapping):
    #   R1: (1,1,1) (1,1,0) (1,0,1) (0,1,1)        -> A at s1 in {0,1}, C at s1 in {0,3}
    #   R2: always (1,1,1)
    #   R3: (1,1,1) (1,1,0) (1,0,0) (0,0,1) (0,1,1) -> B at s3 in {0,1}, D at s3 in {0,4}
    # 4 * 3 * 5 = 60 spins; R2 is constant, so work over the 20 (s1, s3) pairs.
    # P(A) = P(C) = 1/2, P(B) = P(D) = 2/5, P(E) = (1/4)(1/5) = 1/20.
    # sum_all RTP   = m (1/2 + 1/2 + 2/5 + 2/5) + 5m/20 = 41m/20 = 451/400.
    # full_only RTP = sum_all - 4m P(E) = 37m/20 = 407/400.
    # No hit only for s1 = 2 and s3 in {2,3}: hit rate = 18/20 = 9/10.
    # One block pays 0.55 <= 1, two or more pay > 1. Blocks per s1: 2,1,0,1;
    # per s3: 2,1,0,0,1. Pairs with >= 2 blocks: 5 + 3 + 1 + 3 = 12 -> 3/5.
    # full_only by pattern: 2x2 blocks pay only when E misses,
    # e.g. A = (1/2 - 1/20) m = 99/400 and B = (2/5 - 1/20) m = 77/400.
    MIXED = ([1, 1, 1, 0], [1, 1, 1], [1, 1, 1, 0, 0])

    @pytest.mark.parametrize(
        ("mode", "rtp", "by_pattern"),
        [
            (
                SUM_ALL,
                Fraction(451, 400),
                {"A": Fraction(11, 40), "B": Fraction(11, 50), "C": Fraction(11, 40),
                 "D": Fraction(11, 50), "E": Fraction(11, 80)},
            ),
            (
                FULL_ONLY,
                Fraction(407, 400),
                {"A": Fraction(99, 400), "B": Fraction(77, 400), "C": Fraction(99, 400),
                 "D": Fraction(77, 400), "E": Fraction(11, 80)},
            ),
        ],
    )
    def test_mixed_reels(self, evaluator, mode, rtp, by_pattern):
        ev = evaluator(self.MIXED, mode)
        assert ev.total_outcomes == 60
        assert ev.rtp == rtp
        assert ev.hit_rate == Fraction(9, 10)
        assert ev.win_rate_above_bet == Fraction(3, 5)
        assert ev.pattern_hit_prob == {
            "A": Fraction(1, 2),
            "B": Fraction(2, 5),
            "C": Fraction(1, 2),
            "D": Fraction(2, 5),
            "E": Fraction(1, 20),
        }
        assert ev.rtp_by_pattern == by_pattern
        assert ev.rtp_by_symbol == {**ZERO_BY_SYMBOL, 1: rtp}
        assert_consistent(ev)

    def test_mode_accepts_strings(self, evaluator):
        assert evaluator(self.ALL_ZERO, "full_only").rtp == Fraction(5, 4)

    @pytest.mark.parametrize("reels", [([0], [1]), ([0], [], [1]), ([0], [1], [7])])
    def test_rejects_invalid_reels(self, evaluator, reels):
        with pytest.raises(ValueError):
            evaluator(reels)


def random_reels(seed: int) -> list[list[int]]:
    """Small reels (length 1..7) over a shared palette of few symbols, so hits are common."""
    rng = random.Random(seed)
    palette = rng.sample(sorted(MULTIPLIERS), rng.randint(1, 3))
    reels = []
    for _ in range(3):
        symbols = palette + [rng.choice(sorted(MULTIPLIERS))]  # occasional outsider
        weights = [4] * len(palette) + [1]
        reels.append(rng.choices(symbols, weights, k=rng.randint(1, 7)))
    return reels


SEEDS = range(100)


@pytest.mark.parametrize("mode", list(PayoutMode))
@pytest.mark.parametrize("seed", SEEDS)
def test_fast_matches_bruteforce(seed, mode):
    reels = random_reels(seed)
    fast = evaluate(reels, mode)
    assert_same(fast, evaluate_bruteforce(reels, mode))
    assert fast.total_outcomes == prod(len(reel) for reel in reels)
    assert_consistent(fast)


def test_random_reels_exercise_all_patterns():
    """Guard against a vacuous cross-check: the random sets must produce real hits."""
    evaluations = [evaluate(random_reels(seed)) for seed in SEEDS]
    assert sum(ev.rtp > 0 for ev in evaluations) >= 50
    assert sum(ev.pattern_hit_prob["E"] > 0 for ev in evaluations) >= 10
    assert sum(0 < ev.hit_rate < 1 for ev in evaluations) >= 30
    for name in PATTERNS:
        assert any(ev.pattern_hit_prob[name] > 0 for ev in evaluations)


def linear_rtp(reels, mode: PayoutMode) -> Fraction:
    """Independent RTP from linearity: sum of P(pattern hits with x) * pay.

    Columns are independent, so P(pattern hits with x) is the product over
    columns of P(that column shows x on all of the pattern's rows in it).
    """

    def column_prob(reel, rows, symbol):
        n = len(reel)
        return Fraction(sum(all(reel[(s + r) % n] == symbol for r in rows) for s in range(n)), n)

    rtp = Fraction(0)
    for symbol, m in MULTIPLIERS.items():
        p = {
            name: prod(
                column_prob(reel, {r for r, c in cells if c == col}, symbol)
                for col, reel in enumerate(reels)
            )
            for name, cells in PATTERNS.items()
        }
        rtp += m * (p["A"] + p["B"] + p["C"] + p["D"]) + FULL_SCREEN_FACTOR * m * p["E"]
        if mode is FULL_ONLY:
            rtp -= 4 * m * p["E"]  # a full screen's four 2x2 blocks go unpaid
    return rtp


@pytest.mark.parametrize("mode", list(PayoutMode))
def test_long_reels_are_exact_and_fast(mode):
    rng = random.Random(2024)
    reels = [rng.choices(sorted(MULTIPLIERS), k=n) for n in (2000, 2500, 3000)]
    start = time.perf_counter()
    ev = evaluate(reels, mode)
    elapsed = time.perf_counter() - start
    assert ev.total_outcomes == 2000 * 2500 * 3000
    assert ev.rtp == linear_rtp(reels, mode)
    assert_consistent(ev)
    assert elapsed < 2.0, f"evaluate took {elapsed:.2f}s"
