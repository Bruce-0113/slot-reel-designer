"""Tests for the Monte Carlo simulator, against exact grid scoring and the evaluator."""

import json
import math
import random
import time
from fractions import Fraction
from itertools import product

import numpy as np
import pytest

from slot_reel_designer.evaluator import evaluate, payout_distribution, payout_variance
from slot_reel_designer.game import MULTIPLIERS, PayoutMode, evaluate_grid, window
from slot_reel_designer.search import CONFIG_PATHS
from slot_reel_designer.simulate import (
    CHUNK,
    PAY_UNITS,
    Z95,
    SimulationResult,
    SpinScorer,
    simulate,
)

SUM_ALL = PayoutMode.SUM_ALL
FULL_ONLY = PayoutMode.FULL_ONLY
ALL_ZERO = ([0], [0, 0], [0, 0, 0])
NO_HITS = ([0, 1], [2, 3], [4])
# Hand-checked in test_evaluator: RTP 451/400 (sum_all), 407/400 (full_only), hit rate 9/10.
MIXED = ([1, 1, 1, 0], [1, 1, 1], [1, 1, 1, 0, 0])
TOLERANCE = 4  # standard errors allowed between an estimate and the exact value


def random_reels(seed: int) -> list[list[int]]:
    """Small reels over a few symbols, so that every pattern hits now and then."""
    rng = random.Random(seed)
    palette = rng.sample(sorted(MULTIPLIERS), rng.randint(1, 3))
    return [rng.choices(palette, k=rng.randint(1, 8)) for _ in range(3)]


def assert_close(estimate: float, exact: Fraction, sd: float, n: int) -> None:
    """|estimate - exact| is within TOLERANCE standard errors, with the exact s.d. per spin."""
    assert abs(estimate - float(exact)) <= TOLERANCE * sd / math.sqrt(n) + 1e-12


def assert_agrees_with_exact(result: SimulationResult, reels, mode: PayoutMode) -> None:
    """RTP, hit rate and win rate above bet all lie within TOLERANCE standard errors."""
    ev = evaluate(reels, mode)
    sd = math.sqrt(payout_variance(payout_distribution(reels, mode)))
    assert_close(result.rtp_mean, ev.rtp, sd, result.n)
    for estimate, p in [
        (result.hit_rate, ev.hit_rate),
        (result.win_rate_above_bet, ev.win_rate_above_bet),
    ]:
        assert_close(estimate, p, math.sqrt(p * (1 - p)), result.n)


class TestSpinScorer:
    @pytest.mark.parametrize("mode", list(PayoutMode))
    @pytest.mark.parametrize("seed", range(60))
    def test_matches_evaluate_grid_on_every_stop(self, seed, mode):
        reels = random_reels(seed)
        stops = np.array(list(product(*(range(len(reel)) for reel in reels))))
        payouts = SpinScorer(reels, mode).payouts(stops)
        assert payouts.dtype == np.int64
        expected = [evaluate_grid(window(reels, s), mode)[0] * PAY_UNITS for s in stops]
        assert payouts.tolist() == expected

    def test_pay_units_make_every_payout_whole(self):
        assert PAY_UNITS == 20
        assert all((m * PAY_UNITS).denominator == 1 for m in MULTIPLIERS.values())

    def test_lengths(self):
        assert SpinScorer(MIXED, SUM_ALL).lengths == (4, 3, 5)

    def test_rejects_invalid_reels(self):
        with pytest.raises(ValueError):
            SpinScorer(([0], [1], [7]), SUM_ALL)


class TestSimulate:
    def test_deterministic_for_a_seed(self):
        first = simulate(MIXED, 20_000, SUM_ALL, seed=7)
        assert simulate(MIXED, 20_000, SUM_ALL, seed=7) == first
        other = simulate(MIXED, 20_000, SUM_ALL, seed=8)
        assert (other.total_payout, other.hits) != (first.total_payout, first.hits)

    def test_chunk_size_does_not_change_the_result(self):
        whole = simulate(MIXED, 10_000, FULL_ONLY, seed=3)
        assert simulate(MIXED, 10_000, FULL_ONLY, seed=3, chunk=999) == whole
        assert simulate(MIXED, 10_000, FULL_ONLY, seed=3, chunk=1) == simulate(
            MIXED, 10_000, FULL_ONLY, seed=3, chunk=10_000
        )

    @pytest.mark.parametrize(
        ("mode", "rtp"), [(SUM_ALL, Fraction(9, 4)), (FULL_ONLY, Fraction(5, 4))]
    )
    def test_all_zero_reels_are_exact(self, mode, rtp):
        result = simulate(ALL_ZERO, 5_000, mode, seed=1)
        assert result.total_payout == rtp * 5_000
        assert result.rtp_mean == float(rtp)
        assert result.rtp_stderr == 0
        assert result.rtp_ci95 == (float(rtp), float(rtp))
        assert result.payout_sd == 0
        assert result.hits == result.above_bet == 5_000
        assert result.hit_rate == result.win_rate_above_bet == 1
        assert result.hit_rate_ci95 == result.win_rate_above_bet_ci95 == (1.0, 1.0)

    def test_no_hits(self):
        result = simulate(NO_HITS, 1_000, SUM_ALL, seed=0)
        assert result.total_payout == 0
        assert result.rtp_mean == result.hit_rate == result.win_rate_above_bet == 0
        assert result.rtp_ci95 == result.hit_rate_ci95 == (0.0, 0.0)

    def test_fields_are_consistent(self):
        result = simulate(MIXED, 30_000, SUM_ALL, seed=5)
        n = result.n
        assert (result.mode, n, result.seed) == (SUM_ALL, 30_000, 5)
        assert result.rtp_mean == float(result.total_payout / n)
        assert result.hit_rate == result.hits / n
        assert result.win_rate_above_bet == result.above_bet / n
        assert 0 <= result.above_bet <= result.hits <= n
        assert result.rtp_stderr == pytest.approx(result.payout_sd / math.sqrt(n))
        low, high = result.rtp_ci95
        assert low == pytest.approx(result.rtp_mean - Z95 * result.rtp_stderr)
        assert high == pytest.approx(result.rtp_mean + Z95 * result.rtp_stderr)
        p = result.hit_rate
        stderr = math.sqrt(p * (1 - p) / (n - 1))
        assert result.hit_rate_stderr == pytest.approx(stderr)
        assert result.hit_rate_ci95 == pytest.approx((p - Z95 * stderr, p + Z95 * stderr))
        assert Z95 == pytest.approx(1.959964)

    def test_proportion_intervals_stay_in_unit_interval(self):
        result = simulate(MIXED, 50, SUM_ALL, seed=0)
        for low, high in (result.hit_rate_ci95, result.win_rate_above_bet_ci95):
            assert 0 <= low <= high <= 1

    def test_mode_accepts_strings(self):
        assert simulate(ALL_ZERO, 10, "full_only", seed=0).rtp_mean == 1.25

    @pytest.mark.parametrize(("n", "chunk"), [(1, CHUNK), (0, CHUNK), (10, 0)])
    def test_rejects_bad_sizes(self, n, chunk):
        with pytest.raises(ValueError):
            simulate(MIXED, n, SUM_ALL, seed=0, chunk=chunk)

    def test_rejects_invalid_reels(self):
        with pytest.raises(ValueError):
            simulate(([0], [], [1]), 100)


@pytest.mark.parametrize("mode", list(PayoutMode))
@pytest.mark.parametrize("seed", range(20))
def test_agrees_with_exact_on_small_reels(seed, mode):
    reels = random_reels(seed)
    assert_agrees_with_exact(simulate(reels, 20_000, mode, seed=seed), reels, mode)


def test_small_reels_exercise_wins():
    """Guard against a vacuous comparison: the random sets must pay something."""
    rtps = [evaluate(random_reels(seed)).rtp for seed in range(20)]
    assert sum(rtp > 0 for rtp in rtps) >= 10


@pytest.mark.parametrize("mode", list(PayoutMode), ids=str)
def test_agrees_with_exact_on_configs(mode):
    reels = json.loads(CONFIG_PATHS[mode].read_text())["reels"]
    result = simulate(reels, 200_000, mode, seed=0)
    assert_agrees_with_exact(result, reels, mode)
    low, high = result.rtp_ci95
    assert low < 0.95 < high
    exact_sd = math.sqrt(payout_variance(payout_distribution(reels, mode)))
    assert result.payout_sd == pytest.approx(exact_sd, rel=0.05)


def test_a_million_spins_take_under_a_second():
    """So the default 10**7 spins stay within a few seconds (about 0.4 s when written)."""
    reels = json.loads(CONFIG_PATHS[SUM_ALL].read_text())["reels"]
    start = time.perf_counter()
    simulate(reels, 1_000_000, SUM_ALL, seed=0)
    elapsed = time.perf_counter() - start
    assert elapsed < 1.0, f"10**6 spins took {elapsed:.2f}s"
