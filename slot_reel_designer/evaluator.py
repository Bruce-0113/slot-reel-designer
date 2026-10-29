"""Exact RTP and win-rate evaluation of a reel set over all stop combinations.

Every statistic is an exact ``Fraction``; no floating point is involved.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from itertools import product

from .game import (
    BET,
    PATTERNS,
    ROWS,
    SYMBOLS,
    PayoutMode,
    pattern_hits,
    pattern_payouts,
    validate_reels,
    window,
)

Triple = tuple[int, ...]  # one column of the window, top to bottom
HitKey = tuple[tuple[str, int], ...]  # (pattern, symbol) pairs that hit on a grid

# Stand-in outer column that never matches a real symbol (see `evaluate`).
_BLANK: Triple = (-1,) * ROWS


@dataclass(frozen=True)
class Evaluation:
    """Exact statistics of a reel set; probabilities are over all stop combinations."""

    total_outcomes: int  # L1 * L2 * L3 equally likely stop combinations
    rtp: Fraction  # expected payout per unit bet
    hit_rate: Fraction  # P(payout > 0)
    win_rate_above_bet: Fraction  # P(payout > bet)
    pattern_hit_prob: dict[str, Fraction]  # P(pattern hits), whether or not it is paid
    rtp_by_pattern: dict[str, Fraction]  # RTP paid through each pattern; sums to rtp
    rtp_by_symbol: dict[int, Fraction]  # RTP paid on each symbol; sums to rtp


def window_counts(reel: Sequence[int]) -> Counter[Triple]:
    """Count how many stops of ``reel`` show each (top, middle, bottom) triple."""
    n = len(reel)
    return Counter(tuple(reel[(stop + row) % n] for row in range(ROWS)) for stop in range(n))


def evaluate(
    reels: Sequence[Sequence[int]], mode: PayoutMode | str = PayoutMode.SUM_ALL
) -> Evaluation:
    """Exact evaluation that enumerates distinct windows instead of stops.

    Each reel is reduced to counts of its distinct window triples, and the
    product of left, middle and right triples is scored with count-product
    weights. For a fixed middle triple, an outer triple that completes no
    2x2 block with it takes part in no hit (every pattern that touches an
    outer column contains such a block), so all of those score alike and
    are merged into one blank column carrying their total count. That keeps
    the work to at most 125 x 10 x 10 grids, however long the reels are.
    """
    return _summarize(outcome_counts(reels), mode)


def outcome_counts(reels: Sequence[Sequence[int]]) -> Counter[HitKey]:
    """Number of stop combinations behind each set of (pattern, symbol) hits.

    Uses the window enumeration of ``evaluate``. The counts total
    L1 * L2 * L3, and the empty key holds the spins on which nothing hits.
    """
    strips = validate_reels(reels)
    left, middle, right = (window_counts(strip) for strip in strips)
    outcomes: Counter[HitKey] = Counter()
    for mid, mid_count in middle.items():
        for (left_col, left_count), (right_col, right_count) in product(
            _merge_idle(left, mid), _merge_idle(right, mid)
        ):
            grid = tuple(zip(left_col, mid, right_col))
            outcomes[tuple(pattern_hits(grid).items())] += left_count * mid_count * right_count
    return outcomes


def payout_distribution(
    reels: Sequence[Sequence[int]], mode: PayoutMode | str = PayoutMode.SUM_ALL
) -> dict[Fraction, Fraction]:
    """Exact P(payout == v) for every payout v that occurs, in increasing order of v."""
    outcomes = outcome_counts(reels)
    by_payout: Counter[Fraction] = Counter()
    for key, count in outcomes.items():
        by_payout[sum(pattern_payouts(dict(key), mode).values(), Fraction(0))] += count
    total = outcomes.total()
    return {value: Fraction(count, total) for value, count in sorted(by_payout.items())}


def payout_variance(distribution: Mapping[Fraction, Fraction]) -> Fraction:
    """Exact variance of the payout per spin, from a ``payout_distribution``."""
    if sum(distribution.values()) != 1:
        raise ValueError("probabilities must sum to 1")
    mean = sum((value * p for value, p in distribution.items()), Fraction(0))
    return sum(((value - mean) ** 2 * p for value, p in distribution.items()), Fraction(0))


def evaluate_bruteforce(
    reels: Sequence[Sequence[int]], mode: PayoutMode | str = PayoutMode.SUM_ALL
) -> Evaluation:
    """Reference evaluation that scores all L1 * L2 * L3 stop combinations one by one."""
    strips = validate_reels(reels)
    outcomes: Counter[HitKey] = Counter()
    for stops in product(*(range(len(strip)) for strip in strips)):
        outcomes[tuple(pattern_hits(window(strips, stops)).items())] += 1
    return _summarize(outcomes, mode)


def _completes_block(outer: Triple, mid: Triple) -> bool:
    """True if two adjacent columns show one symbol on rows 0-1 or rows 1-2."""
    return any(
        outer[row] == outer[row + 1] == mid[row] == mid[row + 1] for row in range(ROWS - 1)
    )


def _merge_idle(counts: Counter[Triple], mid: Triple) -> list[tuple[Triple, int]]:
    """Keep outer triples that complete a block with ``mid``; merge the rest into a blank."""
    active = [(col, count) for col, count in counts.items() if _completes_block(col, mid)]
    idle = counts.total() - sum(count for _, count in active)
    if idle:
        active.append((_BLANK, idle))
    return active


def _summarize(outcomes: Counter[HitKey], mode: PayoutMode | str) -> Evaluation:
    """Turn outcome counts, keyed by the patterns hit, into exact statistics."""
    total = outcomes.total()
    hit_count = above_bet_count = 0
    pattern_count = dict.fromkeys(PATTERNS, 0)
    paid_by_pattern = dict.fromkeys(PATTERNS, Fraction(0))
    paid_by_symbol = dict.fromkeys(SYMBOLS, Fraction(0))
    for key, count in outcomes.items():
        hits = dict(key)
        paid = pattern_payouts(hits, mode)
        payout = sum(paid.values(), Fraction(0))
        if payout > 0:
            hit_count += count
        if payout > BET:
            above_bet_count += count
        for name in hits:
            pattern_count[name] += count
        for name, amount in paid.items():
            paid_by_pattern[name] += amount * count
            paid_by_symbol[hits[name]] += amount * count
    return Evaluation(
        total_outcomes=total,
        rtp=sum(paid_by_pattern.values(), Fraction(0)) / total,
        hit_rate=Fraction(hit_count, total),
        win_rate_above_bet=Fraction(above_bet_count, total),
        pattern_hit_prob={name: Fraction(n, total) for name, n in pattern_count.items()},
        rtp_by_pattern={name: paid / total for name, paid in paid_by_pattern.items()},
        rtp_by_symbol={symbol: paid / total for symbol, paid in paid_by_symbol.items()},
    )
