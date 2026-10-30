"""Monte Carlo simulation of spins, an independent check on the exact evaluator.

Each pattern shows one symbol on all of its cells exactly when, in every
column it touches, the reel shows one symbol on the pattern's rows and
those symbols agree. So for every (column, rows) pair that some pattern
uses, ``SpinScorer`` stores per stop the symbol shown on all of those rows,
or -1. A spin then costs a few array lookups and comparisons, with no
grid built, and payouts are whole numbers of 1/20 of the bet, so every
total is exact.

Stops are drawn uniformly and independently with numpy's default
generator, a chunk of spins at a time to bound memory. Confidence
intervals are normal approximations: estimate +- 1.96 standard errors,
with the sample standard deviation.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction
from statistics import NormalDist

import numpy as np

from .game import (
    BET,
    FULL_SCREEN,
    FULL_SCREEN_FACTOR,
    MULTIPLIERS,
    PATTERNS,
    PayoutMode,
    validate_reels,
)

DEFAULT_SPINS = 10_000_000
DEFAULT_SEED = 0
CHUNK = 1_000_000  # spins scored per batch
Z95 = NormalDist().inv_cdf(0.975)  # two-sided 95% normal quantile, about 1.96
# Payouts in units of 1/PAY_UNITS of the bet are whole numbers.
PAY_UNITS = math.lcm(*(m.denominator for m in MULTIPLIERS.values()))

ColumnRows = tuple[int, tuple[int, ...]]  # (column, rows of that column a pattern covers)
Interval = tuple[float, float]


def _pattern_columns() -> dict[str, tuple[ColumnRows, ...]]:
    """For each pattern, the rows it covers in each column it touches."""
    columns: dict[str, tuple[ColumnRows, ...]] = {}
    for name, cells in PATTERNS.items():
        rows: defaultdict[int, set[int]] = defaultdict(set)
        for row, col in cells:
            rows[col].add(row)
        columns[name] = tuple((col, tuple(sorted(rows[col]))) for col in sorted(rows))
    return columns


def _uniform_symbol(strip: np.ndarray, rows: tuple[int, ...]) -> np.ndarray:
    """Per stop, the symbol the reel shows on every one of ``rows``, or -1 if they differ."""
    shown = [np.roll(strip, -row) for row in rows]  # shown[i][s] = strip[(s + rows[i]) % L]
    same = np.logical_and.reduce([column == shown[0] for column in shown])
    return np.where(same, shown[0], -1).astype(np.int8)


class SpinScorer:
    """Vectorised payouts of one reel set under one payout mode."""

    def __init__(self, reels: Sequence[Sequence[int]], mode: PayoutMode | str) -> None:
        strips = [np.asarray(strip, dtype=np.int8) for strip in validate_reels(reels)]
        self.mode = PayoutMode(mode)
        self.lengths: tuple[int, ...] = tuple(len(strip) for strip in strips)
        self._columns = _pattern_columns()
        keys = {key for columns in self._columns.values() for key in columns}
        self._codes = {(col, rows): _uniform_symbol(strips[col], rows) for col, rows in keys}
        units = np.array([int(m * PAY_UNITS) for m in MULTIPLIERS.values()], dtype=np.int64)
        self._pay = {
            name: units * (FULL_SCREEN_FACTOR if name == FULL_SCREEN else 1) for name in PATTERNS
        }

    def payouts(self, stops: np.ndarray) -> np.ndarray:
        """Payout of each spin in units of 1/PAY_UNITS of the bet; ``stops`` has shape (n, 3)."""
        stops = np.asarray(stops)
        shown = {key: codes[stops[:, key[0]]] for key, codes in self._codes.items()}
        total = np.zeros(len(stops), dtype=np.int64)
        full_hit = full_pay = None
        for name, columns in self._columns.items():
            symbol = shown[columns[0]]
            hit = symbol >= 0
            for key in columns[1:]:
                hit &= shown[key] == symbol
            # symbol is -1 where the pattern misses; that lookup is masked out by `hit`.
            amount = np.where(hit, self._pay[name][symbol], 0)
            total += amount
            if name == FULL_SCREEN:
                full_hit, full_pay = hit, amount
        if self.mode is PayoutMode.FULL_ONLY and full_hit is not None:
            total = np.where(full_hit, full_pay, total)  # a full screen pays E alone
        return total


@dataclass(frozen=True)
class SimulationResult:
    """Estimates from ``n`` simulated spins; ``*_ci95`` are 95% confidence intervals."""

    mode: PayoutMode
    n: int
    seed: int | None
    total_payout: Fraction  # exact sum of all payouts, bet 1 per spin
    hits: int  # spins with payout > 0
    above_bet: int  # spins with payout > bet
    rtp_mean: float
    rtp_stderr: float
    rtp_ci95: Interval
    payout_sd: float  # sample standard deviation of the payout per spin
    hit_rate: float
    hit_rate_stderr: float
    hit_rate_ci95: Interval
    win_rate_above_bet: float
    win_rate_above_bet_stderr: float
    win_rate_above_bet_ci95: Interval


def _estimate(total: Fraction, squares: Fraction, n: int) -> tuple[float, float, float]:
    """(mean, sample standard deviation, standard error) from a sum and a sum of squares."""
    variance = (squares - total * total / n) / (n - 1)
    sd = math.sqrt(variance)
    return float(total / n), sd, sd / math.sqrt(n)


def _ci95(mean: float, stderr: float, low: float = -math.inf, high: float = math.inf) -> Interval:
    """Normal 95% interval around ``mean``, clipped to [low, high]."""
    return max(low, mean - Z95 * stderr), min(high, mean + Z95 * stderr)


def simulate(
    reels: Sequence[Sequence[int]],
    n: int = DEFAULT_SPINS,
    mode: PayoutMode | str = PayoutMode.SUM_ALL,
    seed: int | None = DEFAULT_SEED,
    *,
    chunk: int = CHUNK,
) -> SimulationResult:
    """Simulate ``n`` spins with stops drawn uniformly; deterministic for an int ``seed``.

    In practice the result depends only on (reels, n, mode, seed), not on
    ``chunk``, since numpy draws the same stops in batches as at once.
    """
    if n < 2:
        raise ValueError(f"need at least 2 spins for a standard error, got {n}")
    if chunk < 1:
        raise ValueError(f"chunk must be positive, got {chunk}")
    scorer = SpinScorer(reels, mode)
    rng = np.random.default_rng(seed)
    high = np.array(scorer.lengths)
    total = squares = hits = above_bet = 0
    done = 0
    while done < n:
        size = min(chunk, n - done)
        pay = scorer.payouts(rng.integers(0, high, size=(size, len(high))))
        total += int(pay.sum())
        squares += int(pay @ pay)
        hits += int(np.count_nonzero(pay))
        above_bet += int(np.count_nonzero(pay > BET * PAY_UNITS))
        done += size
    unit = Fraction(1, PAY_UNITS)
    rtp, sd, rtp_se = _estimate(total * unit, squares * unit * unit, n)
    hit_rate, _, hit_se = _estimate(Fraction(hits), Fraction(hits), n)
    above, _, above_se = _estimate(Fraction(above_bet), Fraction(above_bet), n)
    return SimulationResult(
        mode=scorer.mode,
        n=n,
        seed=seed,
        total_payout=total * unit,
        hits=hits,
        above_bet=above_bet,
        rtp_mean=rtp,
        rtp_stderr=rtp_se,
        rtp_ci95=_ci95(rtp, rtp_se),
        payout_sd=sd,
        hit_rate=hit_rate,
        hit_rate_stderr=hit_se,
        hit_rate_ci95=_ci95(hit_rate, hit_se, 0.0, 1.0),
        win_rate_above_bet=above,
        win_rate_above_bet_stderr=above_se,
        win_rate_above_bet_ci95=_ci95(above, above_se, 0.0, 1.0),
    )
