"""Reel search: reel sets with an RTP of exactly 19/20 that read like a real paytable.

Count model. For one cyclic reel, a stop's window (a, b, c) is reduced to
the state ``T = a if a == b else None`` and ``U = b if b == c else None``.
Every pattern only compares these states across the three reels:

    A: T1 == T2 == x    B: T2 == T3 == x    C: U1 == U2 == x    D: U2 == U3 == x
    E: all three windows are (x, x, x), i.e. T_i == U_i == x on every reel

One reel's state distribution depends only on its length L and, per symbol
x, ``pairs[x]`` (cyclic i with r[i] == r[i+1] == x) and ``triples[x]``
(cyclic i with r[i] == r[i+1] == r[i+2] == x):

    stops with (T, U) = (x, None) or (None, x):  pairs[x] - triples[x] each
    stops with (T, U) = (x, x):                  triples[x]

That gives 16 states per reel and 16**3 state triples, so every statistic
of a reel set follows exactly from its counts. Scaled by 20 * L1 * L2 * L3,
the RTP is an integer, which makes RTP == 19/20 integer bookkeeping.

Strips. A reel is described by its runs (``ReelSpec``): a run of length
k >= 2 adds k - 1 pairs and k - 2 triples, a singleton adds none, and the
strip is laid out so that neighbouring runs (cyclically) differ in symbol.

Search. Seeded simulated annealing over the run specs of the three reels
minimises an ``Objective`` whose weights follow the design priorities
(RTP near 0.95, hit rate >= 0.55, per-symbol hit frequency falling with the
multiplier, then a realistic hit rate and short reels). The domain keeps a
run of three or more of every symbol on every reel (a full screen of every
symbol is possible) and at most 150 symbols per reel. After each move one
reel's singleton count is re-solved in closed form so the RTP stays near
0.95. The exact finish then uses that, with two reels fixed,
20 * L1 * L2 * L3 * (RTP - 19/20) is affine in the third reel's run counts:
small changes around the best annealing results are enumerated meet in the
middle, the singleton count that makes the RTP exactly 19/20 is solved for,
and the best exact candidate is built into strips and scored with
``evaluate``.

Run ``python -m slot_reel_designer.search`` to search both payout modes and
save configs/reels.json (sum_all) and configs/reels_full_only.json.
"""

from __future__ import annotations

import json
import math
import random
import re
import time
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction
from functools import cached_property
from itertools import product
from pathlib import Path
from typing import Any

import numpy as np

from .evaluator import Evaluation, HitKey, _summarize, evaluate
from .game import (
    FULL_SCREEN,
    FULL_SCREEN_FACTOR,
    MULTIPLIERS,
    PATTERNS,
    SYMBOLS,
    PayoutMode,
    validate_reels,
)

Reels = tuple[tuple[int, ...], ...]
Specs = tuple["ReelSpec", ...]  # one spec per reel

TARGET_RTP = Fraction(19, 20)  # H1
MIN_HIT_RATE = Fraction(11, 20)  # H2
HIT_RATE_RANGE = (Fraction(11, 20), Fraction(7, 10))  # S3
MAX_LENGTH = 150  # S4
CONFIG_DIR = Path(__file__).resolve().parent.parent / "configs"
CONFIG_PATHS = {
    PayoutMode.SUM_ALL: CONFIG_DIR / "reels.json",
    PayoutMode.FULL_ONLY: CONFIG_DIR / "reels_full_only.json",
}

NSYM = len(SYMBOLS)  # symbols are 0..NSYM-1, so they double as indices
# Multipliers in units of 1/PAY_SCALE = 1/20, where each is an integer: 5, 11, 20, 60, 100.
PAY_SCALE = math.lcm(*(m.denominator for m in MULTIPLIERS.values()))
PAY: tuple[int, ...] = tuple(int(PAY_SCALE * MULTIPLIERS[x]) for x in SYMBOLS)
PAY_FLOAT: tuple[float, ...] = tuple(float(MULTIPLIERS[x]) for x in SYMBOLS)

State = tuple[int | None, int | None]  # (T, U) of one stop
STATES: tuple[State, ...] = (
    (None, None),
    *((x, None) for x in SYMBOLS),
    *((None, x) for x in SYMBOLS),
    *((x, x) for x in SYMBOLS),
)


# --------------------------------------------------------------------------- count model


@dataclass(frozen=True)
class ReelCounts:
    """Everything the game statistics depend on for one reel."""

    length: int
    pairs: tuple[int, ...]  # pairs[x]: cyclic i with r[i] == r[i+1] == x
    triples: tuple[int, ...]  # triples[x]: cyclic i with r[i] == r[i+1] == r[i+2] == x


def strip_counts(strip: Sequence[int]) -> ReelCounts:
    """Count the cyclic pairs and triples of each symbol on one strip."""
    n = len(strip)
    pairs = [0] * NSYM
    triples = [0] * NSYM
    for i, x in enumerate(strip):
        if strip[(i + 1) % n] == x:
            pairs[x] += 1
            if strip[(i + 2) % n] == x:
                triples[x] += 1
    return ReelCounts(n, tuple(pairs), tuple(triples))


def count_reels(reels: Sequence[Sequence[int]]) -> tuple[ReelCounts, ...]:
    """Validate three strips and return their counts."""
    return tuple(strip_counts(strip) for strip in validate_reels(reels))


def reel_states(counts: ReelCounts) -> dict[State, int]:
    """Number of stops in each of the 16 (T, U) states."""
    states = dict.fromkeys(STATES, 0)
    for x in SYMBOLS:
        states[(x, None)] = states[(None, x)] = counts.pairs[x] - counts.triples[x]
        states[(x, x)] = counts.triples[x]
    states[(None, None)] = counts.length - sum(states.values())
    return states


def _state_hits(left: State, mid: State, right: State) -> HitKey:
    """(pattern, symbol) pairs that hit on any grid with these column states, in A..E order."""
    (t1, u1), (t2, u2), (t3, u3) = left, mid, right
    hits: list[tuple[str, int]] = []
    if t2 is not None:
        hits += [("A", t2)] if t1 == t2 else []
        hits += [("B", t2)] if t3 == t2 else []
    if u2 is not None:
        hits += [("C", u2)] if u1 == u2 else []
        hits += [("D", u2)] if u3 == u2 else []
    if t2 is not None and t2 == u2 and left == mid == right:
        hits.append((FULL_SCREEN, t2))
    return tuple(hits)


def _state_outcomes(counts: Sequence[ReelCounts]) -> Counter[HitKey]:
    """Weight of every hit combination over all L1 * L2 * L3 stops, from the state triples."""
    columns = [[(s, n) for s, n in reel_states(c).items() if n] for c in counts]
    outcomes: Counter[HitKey] = Counter()
    for (s1, n1), (s2, n2), (s3, n3) in product(*columns):
        outcomes[_state_hits(s1, s2, s3)] += n1 * n2 * n3
    return outcomes


def evaluate_counts(
    counts: Sequence[ReelCounts], mode: PayoutMode | str = PayoutMode.SUM_ALL
) -> Evaluation:
    """Exact ``Evaluation`` of any reel set with these counts (equal to ``evaluate``)."""
    return _summarize(_state_outcomes(counts), mode)


def symbol_hit_prob(counts: Sequence[ReelCounts]) -> dict[int, Fraction]:
    """P(a spin wins on symbol x); these sum to the hit rate.

    Every pattern covers the middle column, whose state names at most one
    symbol, so all hits of one spin share a symbol.
    """
    outcomes = _state_outcomes(counts)
    total = outcomes.total()
    wins = Counter({x: 0 for x in SYMBOLS})
    for key, n in outcomes.items():
        for x in {symbol for _, symbol in key}:
            wins[x] += n
    return {x: Fraction(wins[x], total) for x in SYMBOLS}


def full_screen_weight(mode: PayoutMode | str) -> int:
    """What a full screen adds, in multiples of m, on top of its four 2x2 blocks.

    sum_all pays the blocks plus 5m; full_only pays 5m instead of the blocks' 4m.
    """
    blocks = 4 if PayoutMode(mode) is PayoutMode.FULL_ONLY else 0
    return FULL_SCREEN_FACTOR - blocks


def rtp_numerator(counts: Sequence[ReelCounts], mode: PayoutMode | str) -> int:
    """Return ``20 * L1 * L2 * L3 * RTP`` exactly.

    With a = pairs / L and t = triples / L per reel,
    RTP = sum_x m(x) [2 a2 (a1 + a3) + w t1 t2 t3], w = ``full_screen_weight``.
    """
    c1, c2, c3 = counts
    weight = full_screen_weight(mode)
    total = 0
    for x in SYMBOLS:
        blocks = 2 * c2.pairs[x] * (c1.pairs[x] * c3.length + c3.pairs[x] * c1.length)
        full = weight * c1.triples[x] * c2.triples[x] * c3.triples[x]
        total += PAY[x] * (blocks + full)
    return total


def symbol_hit_numerators(counts: Sequence[ReelCounts]) -> tuple[int, ...]:
    """Return ``L1 * L2 * L3 * P(a spin wins on x)`` for each symbol x.

    With p = a - t and b = 2a - t = P(T = x or U = x) per reel,
    P(win on x) = 2 p2 [1 - (1 - a1)(1 - a3)] + t2 [1 - (1 - b1)(1 - b3)].
    """
    c1, c2, c3 = counts
    l1, l3 = c1.length, c3.length
    out = []
    for x in SYMBOLS:
        p1, p3 = c1.pairs[x], c3.pairs[x]
        b1 = 2 * p1 - c1.triples[x]
        b3 = 2 * p3 - c3.triples[x]
        either = p1 * l3 + p3 * l1 - p1 * p3
        both = b1 * l3 + b3 * l1 - b1 * b3
        out.append(2 * (c2.pairs[x] - c2.triples[x]) * either + c2.triples[x] * both)
    return tuple(out)


def fast_stats(counts: Sequence[ReelCounts], weight: int) -> tuple[float, float, list[float]]:
    """Float (RTP, hit rate, per-symbol hit probability) for the search's inner loop.

    ``weight`` is ``full_screen_weight(mode)``; the formulas are those of
    ``rtp_numerator`` and ``symbol_hit_numerators``.
    """
    c1, c2, c3 = counts
    l1, l2, l3 = c1.length, c2.length, c3.length
    rtp = 0.0
    hits = [0.0] * NSYM
    for x in SYMBOLS:
        a1, a2, a3 = c1.pairs[x] / l1, c2.pairs[x] / l2, c3.pairs[x] / l3
        t1, t2, t3 = c1.triples[x] / l1, c2.triples[x] / l2, c3.triples[x] / l3
        rtp += PAY_FLOAT[x] * (2 * a2 * (a1 + a3) + weight * t1 * t2 * t3)
        b1, b3 = 2 * a1 - t1, 2 * a3 - t3
        hits[x] = 2 * (a2 - t2) * (a1 + a3 - a1 * a3) + t2 * (b1 + b3 - b1 * b3)
    return rtp, sum(hits), hits


# --------------------------------------------------------------------------- strips


@dataclass(frozen=True)
class ReelSpec:
    """Run-level description of one reel.

    ``runs[x]`` runs of symbol x have length >= 2 and together hold
    ``extra[x]`` symbols beyond length 2, so pairs[x] = runs[x] + extra[x]
    and triples[x] = extra[x]. ``singles`` singleton symbols only add
    length; ``singles_by_symbol`` decides which symbols they show.
    """

    runs: tuple[int, ...]
    extra: tuple[int, ...]
    singles: int

    @cached_property
    def length(self) -> int:
        """Number of symbols on the strip."""
        return sum(2 * n + e for n, e in zip(self.runs, self.extra)) + self.singles

    @cached_property
    def counts(self) -> ReelCounts:
        """Counts of every strip built from this spec."""
        pairs = tuple(n + e for n, e in zip(self.runs, self.extra))
        return ReelCounts(self.length, pairs, tuple(self.extra))

    def singles_by_symbol(self) -> list[int]:
        """Spread the singletons so every symbol appears and item counts stay balanced.

        Each symbol without a run gets one singleton first (while any are
        left); every further singleton goes to the symbol with the fewest
        items (runs plus singletons), the highest symbol on ties.
        """
        items = list(self.runs)
        singles = [0] * NSYM
        left = self.singles
        for x in SYMBOLS:
            if items[x] == 0 and left > 0:
                items[x] += 1
                singles[x] += 1
                left -= 1
        for _ in range(left):
            x = min(SYMBOLS, key=lambda y: (items[y], -y))
            items[x] += 1
            singles[x] += 1
        return singles

    def is_buildable(self) -> bool:
        """True if a cyclic strip with these runs exists and shows all five symbols.

        Items (runs and singletons) of one symbol must never touch, which is
        possible exactly when no symbol has more than half of the items.
        """
        if self.singles < 0 or any(
            n < 0 or e < 0 or (n == 0 and e > 0) for n, e in zip(self.runs, self.extra)
        ):
            return False
        items = [n + s for n, s in zip(self.runs, self.singles_by_symbol())]
        return min(items) >= 1 and max(items) <= sum(items) // 2


def _symbol_items(runs: int, extra: int, singles: int) -> list[int]:
    """Item lengths of one symbol, in strip order.

    The runs share ``extra`` evenly; long and short runs alternate, and a
    singleton follows every second run (the rest come last).
    """
    lengths = [2 + extra // runs + (i < extra % runs) for i in range(runs)] if runs else []
    lengths.sort(reverse=True)
    mixed = []
    lo, hi = 0, len(lengths) - 1
    while lo <= hi:
        mixed.append(lengths[lo])
        if lo != hi:
            mixed.append(lengths[hi])
        lo, hi = lo + 1, hi - 1
    items = []
    left = singles
    for i, k in enumerate(mixed):
        items.append(k)
        if left and i % 2 == 1:
            items.append(1)
            left -= 1
    return items + [1] * left


def _cyclic_order(counts: list[int]) -> list[int]:
    """Order items (``counts[x]`` of symbol x) cyclically so no two neighbours share a symbol.

    Greedy: take the symbol with the most items left that differs from the
    previous one (the starting symbol first on ties, so it is used up early,
    then the lowest). Falls back to ``_alternating_fill`` if that fails.
    """
    left = list(counts)
    total = sum(left)
    first = max(range(len(left)), key=lambda y: (left[y], -y))
    order: list[int] = []
    prev = None
    for step in range(total):
        options = [y for y in range(len(left)) if left[y] > 0 and y != prev]
        if step == total - 1:
            options = [y for y in options if y != first] or options
        if not options:
            break
        y = max(options, key=lambda z: (left[z], z == first, -z))
        order.append(y)
        left[y] -= 1
        prev = y
    if len(order) == total and all(order[i] != order[i - 1] for i in range(total)):
        return order
    return _alternating_fill(counts)


def _alternating_fill(counts: list[int]) -> list[int]:
    """Fill slots 0, 2, 4, ... then 1, 3, ... with the symbols in descending count order.

    No two cyclic neighbours share a symbol whenever max(counts) <= sum(counts) // 2.
    """
    total = sum(counts)
    by_count = sorted(range(len(counts)), key=lambda y: (-counts[y], y))
    sequence = [y for y in by_count for _ in range(counts[y])]
    out = [0] * total
    for slot, y in zip([*range(0, total, 2), *range(1, total, 2)], sequence):
        out[slot] = y
    return out


def build_strip(spec: ReelSpec) -> tuple[int, ...]:
    """Lay out a cyclic strip whose counts equal ``spec.counts``.

    Raises ValueError if the spec is not buildable.
    """
    if not spec.is_buildable():
        raise ValueError(f"spec cannot be built into a strip with all symbols: {spec}")
    singles = spec.singles_by_symbol()
    items = [_symbol_items(spec.runs[x], spec.extra[x], singles[x]) for x in SYMBOLS]
    cursor = [0] * NSYM
    strip: list[int] = []
    for x in _cyclic_order([len(symbol_items) for symbol_items in items]):
        strip += [x] * items[x][cursor[x]]
        cursor[x] += 1
    built = tuple(strip)
    if strip_counts(built) != spec.counts:
        raise AssertionError(f"strip built from {spec} does not match its counts")
    return built


# --------------------------------------------------------------------------- search

TARGET_FLOAT = float(TARGET_RTP)
DEFAULT_SEED = 0
RESTARTS = 10  # annealing runs, seeded seed, seed + 1, ...
SA_STEPS = 60_000
T_START, T_END = 3.0, 1e-3  # geometric cooling
FINISH_TOP = 3  # best annealing results handed to the exact finish
SINGLE_SHIFT = 4  # singleton changes tried on the two non-pivot reels
RUN_SHIFT = 2  # run-count changes tried on the pivot reel
EXTRA_SHIFT = (3, 12)  # extra changes tried on the pivot reel: below 10, from 10 up


@dataclass(frozen=True)
class Objective:
    """Penalty to minimise; larger weights encode higher priorities.

    RTP comes first (exactness is left to the finish), then the hit-rate
    floor (H2) and a strictly falling per-symbol hit frequency (S1), then a
    paytable-like spacing between symbols, the realistic hit-rate band (S3),
    and mild preferences for a hit rate near 0.60 and short reels.
    """

    w_rtp: float = 1000.0  # times |RTP - 0.95|
    hit_min: float = 0.555  # H2 floor (0.55) with a margin
    w_hit_min: float = 1000.0
    strict: float = 1.03  # S1: h[x] >= strict * h[x + 1] ...
    w_strict: float = 200.0
    rho: float = 1.25  # ... and ideally h[x] >= rho * h[x + 1]
    w_rho: float = 5.0
    w_smooth: float = 1.0  # times log(max h[x] / h[x + 1]): a gradual decline
    s3: tuple[float, float] = (0.56, 0.69)  # S3 band [0.55, 0.70] with a margin
    w_s3: float = 50.0
    hit_mid: float = 0.60
    w_mid: float = 1.0
    w_len: float = 0.3  # per 3 * MAX_LENGTH symbols in all

    def penalty(
        self,
        rtp: float,
        hit_rate: float,
        hits: Sequence[float],
        lengths: Sequence[int],
        with_rtp: bool = True,
    ) -> float:
        """Penalty from the RTP, hit rate, per-symbol hit probabilities and reel lengths."""
        pen = self.w_rtp * abs(rtp - TARGET_FLOAT) if with_rtp else 0.0
        pen += self.w_hit_min * max(0.0, self.hit_min - hit_rate)
        worst = 1.0
        for x in SYMBOLS[:-1]:
            ratio = hits[x] / hits[x + 1] if hits[x + 1] > 0 else 1e3
            worst = max(worst, ratio)
            pen += self.w_strict * max(0.0, self.strict - ratio)
            pen += self.w_rho * max(0.0, self.rho - ratio)
        pen += self.w_smooth * math.log(worst)
        pen += self.w_s3 * (max(0.0, self.s3[0] - hit_rate) + max(0.0, hit_rate - self.s3[1]))
        pen += self.w_mid * abs(hit_rate - self.hit_mid)
        return pen + self.w_len * sum(lengths) / (3 * MAX_LENGTH)


# Under full_only, S3 looks out of reach together with H1, H2 and S1 at these lengths (a
# continuous relaxation of the counts tops out near RTP 0.91 with the hit rate in the S3 band),
# so the smoothness term is dropped there and the S3 terms just push the hit rate down.
OBJECTIVES: dict[PayoutMode, Objective] = {
    PayoutMode.SUM_ALL: Objective(),
    PayoutMode.FULL_ONLY: Objective(w_smooth=0.0),
}


def in_domain(spec: ReelSpec) -> bool:
    """True if a reel may be used: a run of >= 3 of every symbol, <= MAX_LENGTH, buildable."""
    return (
        min(spec.runs) >= 1
        and min(spec.extra) >= 1
        and spec.singles >= 0
        and spec.length <= MAX_LENGTH
        and spec.is_buildable()
    )


def _score(specs: Specs, weight: int, objective: Objective, with_rtp: bool = True) -> float:
    """Objective penalty of a spec triple (``weight`` is ``full_screen_weight(mode)``)."""
    rtp, hit_rate, hits = fast_stats([spec.counts for spec in specs], weight)
    return objective.penalty(rtp, hit_rate, hits, [spec.length for spec in specs], with_rtp)


def _random_spec(rng: random.Random) -> ReelSpec:
    """A seeded starting reel: symbol 0 heavy (the hit rate comes from it), the rest small."""
    while True:
        runs = [rng.randint(1, 4) for _ in SYMBOLS]
        extra = [rng.randint(10, 60)] + [rng.randint(1, 6) for _ in SYMBOLS[1:]]
        spec = ReelSpec(tuple(runs), tuple(extra), rng.randint(0, 5))
        if in_domain(spec):
            return spec


def _neighbour(spec: ReelSpec, rng: random.Random) -> ReelSpec:
    """Change one counter, or move symbols between two counters of the reel."""
    runs, extra, singles = list(spec.runs), list(spec.extra), spec.singles
    step = rng.choice((-1, 1)) * (1 if rng.random() < 0.6 else rng.randint(2, 5))
    move = rng.random()
    if move < 0.45:  # one counter
        which = rng.randrange(2 * NSYM + 1)
        if which < NSYM:
            runs[which] += step
        elif which < 2 * NSYM:
            extra[which - NSYM] += step
        else:
            singles += step
    elif move < 0.85:  # extra from one symbol to another (length kept)
        x, y = rng.sample(range(NSYM), 2)
        extra[x] += abs(step)
        extra[y] -= abs(step)
    else:  # between singletons and one symbol's extra (length kept)
        x = rng.randrange(NSYM)
        extra[x] += step
        singles -= step
    return ReelSpec(tuple(runs), tuple(extra), singles)


def _with_singles(specs: Specs, i: int, singles: int) -> Specs:
    """``specs`` with reel ``i``'s singleton count replaced."""
    spec = specs[i]
    return specs[:i] + (ReelSpec(spec.runs, spec.extra, singles),) + specs[i + 1 :]


def _repair(
    specs: Specs, i: int, weight: int, objective: Objective
) -> tuple[float, Specs] | None:
    """Reset reel ``i``'s singletons to bring the RTP as close to 0.95 as the domain allows.

    With the other reels fixed, RTP = A / L + B in this reel's length L
    (B = 0 for the middle reel), so the best L follows in closed form; its
    floor and ceiling are scored. Returns (penalty, specs), or None if no
    singleton count keeps the reel in the domain.
    """
    core = specs[i].length - specs[i].singles

    def rtp(singles: int) -> float:
        reels = _with_singles(specs, i, singles)
        return fast_stats([spec.counts for spec in reels], weight)[0]

    r0, r1 = rtp(0), rtp(1)
    slope = (r0 - r1) / (1 / core - 1 / (core + 1))
    offset = r0 - slope / core
    room = MAX_LENGTH - core
    if slope <= 0 or TARGET_FLOAT <= offset:
        ideal = float(room)
    else:
        ideal = slope / (TARGET_FLOAT - offset) - core
    best = None
    for singles in sorted({math.floor(ideal), math.ceil(ideal)}):
        candidate = _with_singles(specs, i, min(room, max(0, singles)))
        if in_domain(candidate[i]):
            pen = _score(candidate, weight, objective)
            if best is None or pen < best[0]:
                best = (pen, candidate)
    return best


def anneal(
    mode: PayoutMode | str,
    seed: int,
    objective: Objective | None = None,
    steps: int = SA_STEPS,
) -> tuple[float, Specs]:
    """One seeded simulated-annealing run; returns the best (penalty, specs) it visited.

    A move changes one reel's spec (``_neighbour``); then each reel's
    singletons are re-solved for the RTP in turn (``_repair``) and the best
    of those repaired sets is the proposal, which makes compound two-reel
    moves. Proposals are accepted by the Metropolis rule.
    """
    mode = PayoutMode(mode)
    objective = objective or OBJECTIVES[mode]
    weight = full_screen_weight(mode)
    rng = random.Random(seed)
    while True:
        specs = tuple(_random_spec(rng) for _ in range(3))
        for i in range(3):
            repaired = _repair(specs, i, weight, objective)
            if repaired is None:
                break
            specs = repaired[1]
        else:
            break
    current = _score(specs, weight, objective)
    best = (current, specs)
    decay = (T_END / T_START) ** (1 / steps)
    temp = T_START
    for _ in range(steps):
        temp *= decay
        i = rng.randrange(3)
        spec = _neighbour(specs[i], rng)
        if min(spec.runs) < 1 or min(spec.extra) < 1 or spec.length - spec.singles > MAX_LENGTH:
            continue
        moved = specs[:i] + (spec,) + specs[i + 1 :]
        # Repairing another reel keeps this reel's singletons, so it must be valid as moved.
        targets = range(3) if in_domain(spec) else (i,)
        repaired = [r for r in (_repair(moved, j, weight, objective) for j in targets) if r]
        if not repaired:
            continue
        pen, proposal = min(repaired, key=lambda r: r[0])
        if pen <= current or rng.random() < math.exp((current - pen) / temp):
            current, specs = pen, proposal
            if current < best[0]:
                best = (current, specs)
    return best


# --------------------------------------------------------------------------- exact finish


def rtp_excess(specs: Specs, mode: PayoutMode | str) -> int:
    """``20 * L1 * L2 * L3 * (RTP - 19/20)`` exactly; zero means the RTP is exactly 19/20."""
    counts = [spec.counts for spec in specs]
    outcomes = math.prod(c.length for c in counts)
    return rtp_numerator(counts, mode) - int(PAY_SCALE * TARGET_RTP) * outcomes


def excess_coefficients(
    specs: Specs, pivot: int, mode: PayoutMode | str
) -> tuple[int, list[int], int]:
    """Affine form of ``rtp_excess`` in the pivot reel's counters, the other reels fixed.

    Returns (f0, coefs, gamma) such that, for any pivot spec,
    rtp_excess = f0 + coefs . (runs + extra) + gamma * singles. It is affine
    because the RTP numerator is linear in each reel's length, pairs and
    triples, which are linear in its runs, extra and singletons.
    """
    zero = (0,) * NSYM

    def excess(runs: Sequence[int], extra: Sequence[int], singles: int) -> int:
        spec = ReelSpec(tuple(runs), tuple(extra), singles)
        return rtp_excess(specs[:pivot] + (spec,) + specs[pivot + 1 :], mode)

    f0 = excess(zero, zero, 0)
    units = [tuple(int(v == j) for v in range(2 * NSYM)) for j in range(2 * NSYM)]
    coefs = [excess(unit[:NSYM], unit[NSYM:], 0) - f0 for unit in units]
    return f0, coefs, excess(zero, zero, 1) - f0


def _neighbourhood(
    coefs: Sequence[int], bases: Sequence[int], shifts: Sequence[int]
) -> tuple[np.ndarray, np.ndarray]:
    """Every value tuple within +-shift of ``bases`` (values >= 1) and its dot with ``coefs``."""
    ranges = [range(max(1, b - d), b + d + 1) for b, d in zip(bases, shifts)]
    values = np.array(list(product(*ranges)), dtype=np.int64)
    return values, values @ np.array(coefs, dtype=np.int64)


@dataclass(frozen=True)
class Candidate:
    """A spec triple with an RTP of exactly 19/20, and its penalty without the RTP term."""

    penalty: float
    specs: Specs


def exact_finish(
    specs: Specs,
    mode: PayoutMode | str,
    objective: Objective | None = None,
    *,
    single_shift: int = SINGLE_SHIFT,
    run_shift: int = RUN_SHIFT,
    extra_shift: tuple[int, int] = EXTRA_SHIFT,
) -> list[Candidate]:
    """Every in-domain spec triple near ``specs`` with an RTP of exactly 19/20, best first.

    Each reel in turn is the pivot. The other two keep their runs and change
    their singleton count by up to ``single_shift``; the pivot's run counts
    change by up to ``run_shift`` and its extras by up to ``extra_shift``
    (the second value for extras of 10 or more). RTP == 19/20 is then
    f0 + coefs . v + gamma * singles == 0 for the pivot's counters v, so
    the counters are split into two groups whose partial sums are matched
    on their residues mod |gamma|, and each match fixes ``singles`` exactly.
    """
    mode = PayoutMode(mode)
    objective = objective or OBJECTIVES[mode]
    weight = full_screen_weight(mode)
    group_a, group_b = [0, 5, 1, 6, 2], [7, 3, 8, 4, 9]  # runs are 0..4, extras 5..9
    found: dict[Specs, Candidate] = {}
    for pivot in range(3):
        others = [i for i in range(3) if i != pivot]
        start = specs[pivot]
        bases = [*start.runs, *start.extra]
        shifts = [run_shift] * NSYM + [extra_shift[e >= 10] for e in start.extra]
        for deltas in product(range(-single_shift, single_shift + 1), repeat=2):
            base = list(specs)
            for i, delta in zip(others, deltas):
                base[i] = ReelSpec(specs[i].runs, specs[i].extra, specs[i].singles + delta)
            if not all(in_domain(base[i]) for i in others):
                continue
            f0, coefs, gamma = excess_coefficients(tuple(base), pivot, mode)
            if gamma == 0:
                continue
            modulus = abs(gamma)
            values_a, sums_a = _neighbourhood(
                *([lst[v] for v in group_a] for lst in (coefs, bases, shifts))
            )
            values_b, sums_b = _neighbourhood(
                *([lst[v] for v in group_b] for lst in (coefs, bases, shifts))
            )
            sums_a = sums_a + f0
            rows_b: dict[int, list[int]] = defaultdict(list)
            for row, residue in enumerate((sums_b % modulus).tolist()):
                rows_b[residue].append(row)
            for row_a, residue in enumerate((sums_a % modulus).tolist()):
                for row_b in rows_b.get(-residue % modulus, ()):
                    singles = -(int(sums_a[row_a]) + int(sums_b[row_b])) // gamma
                    if singles < 0:
                        continue
                    counters = [0] * (2 * NSYM)
                    for v, value in zip(group_a, values_a[row_a].tolist()):
                        counters[v] = value
                    for v, value in zip(group_b, values_b[row_b].tolist()):
                        counters[v] = value
                    spec = ReelSpec(tuple(counters[:NSYM]), tuple(counters[NSYM:]), singles)
                    if not in_domain(spec):
                        continue
                    triple = tuple(base[:pivot]) + (spec,) + tuple(base[pivot + 1 :])
                    if triple not in found:
                        pen = _score(triple, weight, objective, with_rtp=False)
                        found[triple] = Candidate(pen, triple)
    candidates = sorted(found.values(), key=lambda c: (c.penalty, _spec_key(c.specs)))
    if any(rtp_excess(c.specs, mode) for c in candidates):
        raise AssertionError("exact finish produced a spec triple off the target RTP")
    return candidates


def _spec_key(specs: Specs) -> list[tuple]:
    """Sort key that orders spec triples deterministically."""
    return [(spec.runs, spec.extra, spec.singles) for spec in specs]


# --------------------------------------------------------------------------- requirements


def check_requirements(ev: Evaluation, reels: Sequence[Sequence[int]]) -> list[str]:
    """Return the hard requirements H1-H5 that a reel set breaks; an empty list means OK.

    ``ev`` is the reel set's evaluation in the payout mode being designed for.
    """
    strips = validate_reels(reels)
    violations = []
    if ev.rtp != TARGET_RTP:
        violations.append(f"H1: RTP is {ev.rtp}, not {TARGET_RTP}")
    if ev.hit_rate < MIN_HIT_RATE:
        violations.append(f"H2: hit rate {ev.hit_rate} is below {MIN_HIT_RATE}")
    violations += [f"H3: symbol {x} pays no RTP" for x in SYMBOLS if ev.rtp_by_symbol[x] <= 0]
    violations += [f"H4: pattern {p} never hits" for p in PATTERNS if ev.pattern_hit_prob[p] <= 0]
    for i, strip in enumerate(strips, start=1):
        if missing := sorted(set(SYMBOLS) - set(strip)):
            violations.append(f"H5: reel {i} lacks symbols {missing}")
        if len(set(strip)) == 1:
            violations.append(f"H5: reel {i} repeats the single symbol {strip[0]}")
    return violations


def check_preferences(ev: Evaluation, reels: Sequence[Sequence[int]]) -> list[str]:
    """Return the soft preferences S1-S4 that a reel set misses; an empty list means all hold."""
    strips = validate_reels(reels)
    counts = [strip_counts(strip) for strip in strips]
    hits = symbol_hit_prob(counts)
    unmet = [
        f"S1: symbol {x} wins no more often than symbol {x + 1} "
        f"({float(hits[x]):.6f} <= {float(hits[x + 1]):.6f})"
        for x in SYMBOLS[:-1]
        if hits[x] <= hits[x + 1]
    ]
    unmet += [
        f"S2: no full screen of symbol {x} is possible"
        for x in SYMBOLS
        if any(c.triples[x] == 0 for c in counts)
    ]
    low, high = HIT_RATE_RANGE
    if not low <= ev.hit_rate <= high:
        band = f"[{float(low):.2f}, {float(high):.2f}]"
        unmet.append(f"S3: hit rate {float(ev.hit_rate):.6f} is outside {band}")
    unmet += [
        f"S4: reel {i} has {len(strip)} symbols, more than {MAX_LENGTH}"
        for i, strip in enumerate(strips, start=1)
        if len(strip) > MAX_LENGTH
    ]
    return unmet


# --------------------------------------------------------------------------- driver


@dataclass(frozen=True)
class SearchResult:
    """The chosen reel set of one search, with its exact evaluation."""

    mode: PayoutMode
    seed: int
    specs: Specs
    reels: Reels
    evaluation: Evaluation
    symbol_hit_prob: dict[int, Fraction]  # P(a spin wins on x)
    penalty: float  # objective without the RTP term
    exact_candidates: int  # exact spec triples the finish found, over all starts

    @property
    def violations(self) -> list[str]:
        """Hard requirements H1-H5 that the reel set breaks."""
        return check_requirements(self.evaluation, self.reels)

    @property
    def unmet_preferences(self) -> list[str]:
        """Soft preferences S1-S4 that the reel set misses."""
        return check_preferences(self.evaluation, self.reels)


def search(
    mode: PayoutMode | str = PayoutMode.SUM_ALL,
    seed: int = DEFAULT_SEED,
    *,
    restarts: int = RESTARTS,
    steps: int = SA_STEPS,
    objective: Objective | None = None,
) -> SearchResult:
    """Search for a reel set with an RTP of exactly 19/20 in ``mode``; deterministic per seed.

    Anneals from seeds ``seed .. seed + restarts - 1``, runs the exact finish
    from the best ``FINISH_TOP`` results and keeps the exact candidate with
    the lowest penalty. Raises RuntimeError if the finish finds none.
    """
    mode = PayoutMode(mode)
    objective = objective or OBJECTIVES[mode]
    runs = [(*anneal(mode, seed + j, objective, steps), j) for j in range(restarts)]
    runs.sort(key=lambda run: (run[0], run[2]))
    best: Candidate | None = None
    found = 0
    for _, specs, _ in runs[:FINISH_TOP]:
        candidates = exact_finish(specs, mode, objective)
        found += len(candidates)
        if candidates and (best is None or candidates[0].penalty < best.penalty):
            best = candidates[0]
    if best is None:
        raise RuntimeError(f"no reel set with RTP {TARGET_RTP} found for {mode}, seed {seed}")
    reels = tuple(build_strip(spec) for spec in best.specs)
    ev = evaluate(reels, mode)
    if ev.rtp != TARGET_RTP:
        raise AssertionError(f"evaluate disagrees with the count model: RTP {ev.rtp}")
    hits = symbol_hit_prob([spec.counts for spec in best.specs])
    return SearchResult(mode, seed, best.specs, reels, ev, hits, best.penalty, found)


def to_config(result: SearchResult) -> dict[str, Any]:
    """Return the JSON-ready record saved to the mode's config file."""
    ev = result.evaluation
    return {
        "mode": str(result.mode),
        "reels": [list(reel) for reel in result.reels],
        "lengths": [len(reel) for reel in result.reels],
        "rtp": str(ev.rtp),
        "hit_rate": str(ev.hit_rate),
        "hit_rate_decimal": round(float(ev.hit_rate), 6),
        "win_rate_above_bet": str(ev.win_rate_above_bet),
        "total_outcomes": ev.total_outcomes,
        "seed": result.seed,
    }


_NUMBER_LIST = re.compile(r"\[\s+(-?\d+(?:,\s+-?\d+)*)\s+\]")  # as json.dumps indents it


def config_json(result: SearchResult) -> str:
    """The saved config text: indented JSON with each list of numbers (a reel) on one line."""

    def one_line(match: re.Match[str]) -> str:
        return "[" + ", ".join(re.split(r",\s+", match[1])) + "]"

    return _NUMBER_LIST.sub(one_line, json.dumps(to_config(result), indent=2)) + "\n"


def _exact(value: Fraction) -> str:
    """A fraction with its decimal value."""
    return f"{value} = {float(value):.6f}"


def _runs(strip: Sequence[int]) -> list[tuple[int, int]]:
    """(symbol, length) of each run of the strip in order, without joining the ends."""
    runs: list[tuple[int, int]] = []
    for x in strip:
        if runs and runs[-1][0] == x:
            runs[-1] = (x, runs[-1][1] + 1)
        else:
            runs.append((x, 1))
    return runs


def describe(result: SearchResult) -> str:
    """Return a few readable lines about ``result``."""
    ev = result.evaluation
    lines = [
        f"[{result.mode}] seed {result.seed}, lengths {[len(r) for r in result.reels]}, "
        f"penalty {result.penalty:.4f}, {result.exact_candidates} exact candidates",
        *(
            f"  reel {i} runs (symbol*length): "
            + " ".join(f"{x}*{k}" for x, k in _runs(reel))
            for i, reel in enumerate(result.reels, start=1)
        ),
        f"  RTP {_exact(ev.rtp)}",
        f"  hit rate {_exact(ev.hit_rate)}",
        f"  win rate above bet {_exact(ev.win_rate_above_bet)}",
        f"  outcomes {ev.total_outcomes}",
        *(
            f"  symbol {x}: RTP {_exact(ev.rtp_by_symbol[x])}, "
            f"hit {_exact(result.symbol_hit_prob[x])}"
            for x in SYMBOLS
        ),
        f"  hard requirements: {result.violations or 'all met'}",
        f"  soft preferences: {result.unmet_preferences or 'all met'}",
    ]
    return "\n".join(lines)


def main(seed: int = DEFAULT_SEED) -> None:
    """Search both payout modes and save their configs."""
    for mode, path in CONFIG_PATHS.items():
        start = time.perf_counter()
        result = search(mode, seed)
        print(describe(result))
        print(f"  searched in {time.perf_counter() - start:.1f}s")
        if result.violations:
            raise SystemExit(f"{mode}: hard requirements broken; nothing saved")
        path.parent.mkdir(exist_ok=True)
        path.write_text(config_json(result))
        print(f"  saved {path}")


if __name__ == "__main__":
    main()
