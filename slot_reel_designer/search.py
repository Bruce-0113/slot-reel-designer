"""Reel search: an exact count model of the game and strips built from run counts.

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
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction
from functools import cached_property
from itertools import product
from math import lcm

from .evaluator import Evaluation, HitKey, _summarize
from .game import (
    FULL_SCREEN,
    FULL_SCREEN_FACTOR,
    MULTIPLIERS,
    SYMBOLS,
    PayoutMode,
    validate_reels,
)

NSYM = len(SYMBOLS)  # symbols are 0..NSYM-1, so they double as indices
# Multipliers in units of 1/PAY_SCALE = 1/20, where each is an integer: 5, 11, 20, 60, 100.
PAY_SCALE = lcm(*(m.denominator for m in MULTIPLIERS.values()))
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
