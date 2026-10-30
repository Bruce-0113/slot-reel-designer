"""Rules of the 3x3 slot game: symbols, winning patterns, windows and payouts.

All amounts are exact ``Fraction`` values for a bet of 1 unit.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import Enum
from fractions import Fraction
from numbers import Integral

ROWS = 3
COLS = 3  # one reel per column
BET = 1

MULTIPLIERS: dict[int, Fraction] = {
    0: Fraction(1, 4),
    1: Fraction(11, 20),
    2: Fraction(1),
    3: Fraction(3),
    4: Fraction(5),
}
SYMBOLS: tuple[int, ...] = tuple(MULTIPLIERS)
FULL_SCREEN = "E"
FULL_SCREEN_FACTOR = 5

Cell = tuple[int, int]  # (row, col)
Grid = tuple[tuple[int, ...], ...]  # grid[row][col]

PATTERNS: dict[str, tuple[Cell, ...]] = {
    "A": ((0, 0), (0, 1), (1, 0), (1, 1)),  # top-left 2x2
    "B": ((0, 1), (0, 2), (1, 1), (1, 2)),  # top-right 2x2
    "C": ((1, 0), (1, 1), (2, 0), (2, 1)),  # bottom-left 2x2
    "D": ((1, 1), (1, 2), (2, 1), (2, 2)),  # bottom-right 2x2
    FULL_SCREEN: tuple((row, col) for row in range(ROWS) for col in range(COLS)),
}


class PayoutMode(str, Enum):
    """How a full screen is paid, given that it also completes all four 2x2 blocks."""

    SUM_ALL = "sum_all"  # pay every hit pattern: 4 * m + 5 * m = 9 * m
    FULL_ONLY = "full_only"  # pay pattern E alone: 5 * m

    def __str__(self) -> str:
        return self.value


def validate_reels(reels: Sequence[Sequence[int]]) -> tuple[tuple[int, ...], ...]:
    """Check that ``reels`` holds 3 non-empty strips of symbols 0..4.

    Returns the reels as tuples of plain ints; raises ValueError otherwise.
    """
    try:
        strips = [list(reel) for reel in reels]
    except TypeError:
        raise ValueError(f"reels must be a sequence of {COLS} symbol sequences") from None
    if len(strips) != COLS:
        raise ValueError(f"expected {COLS} reels, got {len(strips)}")
    for i, strip in enumerate(strips):
        if not strip:
            raise ValueError(f"reels[{i}] is empty")
        for j, symbol in enumerate(strip):
            is_int = isinstance(symbol, Integral) and not isinstance(symbol, bool)
            if not is_int or symbol not in MULTIPLIERS:
                raise ValueError(
                    f"reels[{i}][{j}] = {symbol!r} is an invalid symbol; "
                    f"expected an int in {min(SYMBOLS)}..{max(SYMBOLS)}"
                )
    return tuple(tuple(int(symbol) for symbol in strip) for strip in strips)


def window(reels: Sequence[Sequence[int]], stops: Sequence[int]) -> Grid:
    """Return the grid shown when reel ``i`` stops at index ``stops[i]``.

    Column ``i`` shows ``reels[i][stops[i] + row]`` for rows 0..2, wrapping
    around the end of the reel.
    """
    if len(stops) != COLS:
        raise ValueError(f"expected {COLS} stops, got {len(stops)}")
    columns = [
        tuple(reel[(stop + row) % len(reel)] for row in range(ROWS))
        for reel, stop in zip(reels, stops, strict=True)
    ]
    return tuple(zip(*columns))


def pattern_hits(grid: Grid) -> dict[str, int]:
    """Map each pattern whose cells all show one symbol to that symbol, in A..E order."""
    hits: dict[str, int] = {}
    for name, cells in PATTERNS.items():
        first = grid[cells[0][0]][cells[0][1]]
        if all(grid[row][col] == first for row, col in cells):
            hits[name] = first
    return hits


def pattern_payouts(
    hits: Mapping[str, int], mode: PayoutMode | str = PayoutMode.SUM_ALL
) -> dict[str, Fraction]:
    """Return what each hit pattern pays under ``mode``; unpaid hits are left out.

    ``hits`` maps pattern names to symbols, as returned by ``pattern_hits``.
    """
    if PayoutMode(mode) is PayoutMode.FULL_ONLY and FULL_SCREEN in hits:
        hits = {FULL_SCREEN: hits[FULL_SCREEN]}
    return {
        name: MULTIPLIERS[symbol] * (FULL_SCREEN_FACTOR if name == FULL_SCREEN else 1)
        for name, symbol in hits.items()
    }


def evaluate_grid(
    grid: Grid, mode: PayoutMode | str = PayoutMode.SUM_ALL
) -> tuple[Fraction, tuple[str, ...]]:
    """Return ``(payout, hit_patterns)`` for one grid and a bet of 1.

    ``hit_patterns`` lists every pattern that hits, whatever the mode: under
    FULL_ONLY a full screen lists A..E but pays E alone.
    """
    hits = pattern_hits(grid)
    payout = sum(pattern_payouts(hits, mode).values(), Fraction(0))
    return payout, tuple(hits)
