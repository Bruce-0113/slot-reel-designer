"""Tests for the game rules: constants, reel validation, windows and grid payouts."""

from fractions import Fraction

import pytest

from slot_reel_designer.game import (
    COLS,
    FULL_SCREEN_FACTOR,
    MULTIPLIERS,
    PATTERNS,
    ROWS,
    PayoutMode,
    evaluate_grid,
    pattern_hits,
    pattern_payouts,
    validate_reels,
    window,
)

SUM_ALL = PayoutMode.SUM_ALL
FULL_ONLY = PayoutMode.FULL_ONLY
BLOCKS = ("A", "B", "C", "D")


def grid_with(pattern: str, symbol: int) -> tuple[tuple[int, ...], ...]:
    """Grid showing `symbol` on the pattern's cells and another symbol elsewhere.

    Every 2x2 block contains the centre cell, so any other block mixes the two
    symbols and only `pattern` hits (for a 2x2 pattern).
    """
    other = (symbol + 1) % len(MULTIPLIERS)
    cells = set(PATTERNS[pattern])
    return tuple(
        tuple(symbol if (row, col) in cells else other for col in range(COLS))
        for row in range(ROWS)
    )


def full(symbol: int) -> tuple[tuple[int, ...], ...]:
    """Grid showing `symbol` on all nine cells."""
    return ((symbol,) * COLS,) * ROWS


class TestConstants:
    def test_multipliers_are_exact(self):
        assert MULTIPLIERS == {
            0: Fraction(1, 4),
            1: Fraction(11, 20),
            2: Fraction(1),
            3: Fraction(3),
            4: Fraction(5),
        }
        assert all(isinstance(m, Fraction) for m in MULTIPLIERS.values())

    def test_full_screen_factor(self):
        assert FULL_SCREEN_FACTOR == 5

    def test_pattern_cells(self):
        assert list(PATTERNS) == ["A", "B", "C", "D", "E"]
        assert set(PATTERNS["A"]) == {(0, 0), (0, 1), (1, 0), (1, 1)}
        assert set(PATTERNS["B"]) == {(0, 1), (0, 2), (1, 1), (1, 2)}
        assert set(PATTERNS["C"]) == {(1, 0), (1, 1), (2, 0), (2, 1)}
        assert set(PATTERNS["D"]) == {(1, 1), (1, 2), (2, 1), (2, 2)}
        assert set(PATTERNS["E"]) == {(r, c) for r in range(3) for c in range(3)}

    def test_every_pattern_contains_the_centre(self):
        assert all((1, 1) in cells for cells in PATTERNS.values())

    def test_payout_mode_values(self):
        assert PayoutMode("sum_all") is SUM_ALL
        assert PayoutMode("full_only") is FULL_ONLY
        assert str(FULL_ONLY) == "full_only"


class TestValidateReels:
    def test_returns_reels_as_int_tuples(self):
        assert validate_reels([[0, 1], (2,), [3, 4, 4]]) == ((0, 1), (2,), (3, 4, 4))

    @pytest.mark.parametrize(
        ("reels", "message"),
        [
            ([[0], [1]], "expected 3 reels, got 2"),
            ([[0], [1], [2], [3]], "expected 3 reels, got 4"),
            ([[0], [], [2]], r"reels\[1\] is empty"),
            ([[0], [1], [2, 5]], r"reels\[2\]\[1\] = 5"),
            ([[-1], [1], [2]], r"reels\[0\]\[0\] = -1"),
            ([[1.0], [1], [2]], "invalid symbol"),
            ([["1"], [1], [2]], "invalid symbol"),
            ([[True], [1], [2]], "invalid symbol"),
            ([[None], [1], [2]], "invalid symbol"),
            ([[0], 3, [2]], "sequence"),
            (5, "sequence"),
        ],
    )
    def test_rejects_invalid_reels(self, reels, message):
        with pytest.raises(ValueError, match=message):
            validate_reels(reels)


class TestWindow:
    REELS = ([0, 1, 2, 3], [4, 3, 2, 1], [1, 1, 2, 2])

    def test_rows_are_consecutive_symbols(self):
        # Columns: (0, 1, 2), (3, 2, 1), (2, 2, 1).
        assert window(self.REELS, (0, 1, 2)) == ((0, 3, 2), (1, 2, 2), (2, 1, 1))

    def test_wraps_around_the_reel_end(self):
        # Columns: (3, 0, 1), (1, 4, 3), (2, 1, 1).
        assert window(self.REELS, (3, 3, 3)) == ((3, 1, 2), (0, 4, 1), (1, 3, 1))

    def test_short_and_unequal_reels(self):
        # Columns: (4, 4, 4), (2, 1, 2), (2, 0, 1).
        reels = ([4], [1, 2], [0, 1, 2])
        assert window(reels, (0, 1, 2)) == ((4, 2, 2), (4, 1, 0), (4, 2, 1))

    def test_rejects_wrong_number_of_stops(self):
        with pytest.raises(ValueError):
            window(self.REELS, (0, 0))


class TestEvaluateGrid:
    @pytest.mark.parametrize("mode", list(PayoutMode))
    def test_no_hit_pays_nothing(self, mode):
        assert evaluate_grid(((0, 1, 2), (3, 4, 0), (1, 2, 3)), mode) == (0, ())

    @pytest.mark.parametrize("mode", list(PayoutMode))
    @pytest.mark.parametrize("symbol", sorted(MULTIPLIERS))
    @pytest.mark.parametrize("pattern", BLOCKS)
    def test_single_block_pays_multiplier(self, pattern, symbol, mode):
        payout, hits = evaluate_grid(grid_with(pattern, symbol), mode)
        assert hits == (pattern,)
        assert payout == MULTIPLIERS[symbol]
        assert isinstance(payout, Fraction)

    def test_block_payouts_by_symbol(self):
        assert evaluate_grid(grid_with("A", 0))[0] == Fraction(1, 4)
        assert evaluate_grid(grid_with("B", 1))[0] == Fraction(11, 20)
        assert evaluate_grid(grid_with("C", 2))[0] == 1
        assert evaluate_grid(grid_with("D", 3))[0] == 3
        assert evaluate_grid(grid_with("D", 4))[0] == 5

    @pytest.mark.parametrize("symbol", sorted(MULTIPLIERS))
    def test_full_screen_sum_all_pays_every_pattern(self, symbol):
        payout, hits = evaluate_grid(full(symbol), SUM_ALL)
        assert hits == ("A", "B", "C", "D", "E")
        assert payout == 4 * MULTIPLIERS[symbol] + 5 * MULTIPLIERS[symbol]

    @pytest.mark.parametrize("symbol", sorted(MULTIPLIERS))
    def test_full_screen_full_only_pays_e_alone(self, symbol):
        payout, hits = evaluate_grid(full(symbol), FULL_ONLY)
        assert hits == ("A", "B", "C", "D", "E")  # all hit, only E is paid
        assert payout == FULL_SCREEN_FACTOR * MULTIPLIERS[symbol]

    def test_full_screen_explicit_values(self):
        assert evaluate_grid(full(1), SUM_ALL)[0] == Fraction(99, 20)  # 9 * 0.55
        assert evaluate_grid(full(1), FULL_ONLY)[0] == Fraction(11, 4)  # 5 * 0.55
        assert evaluate_grid(full(4), SUM_ALL)[0] == 45
        assert evaluate_grid(full(4), FULL_ONLY)[0] == 25

    @pytest.mark.parametrize("mode", list(PayoutMode))
    @pytest.mark.parametrize(
        ("grid", "hits", "payout"),
        [
            # A + C: left two columns uniform.
            (((3, 3, 0), (3, 3, 1), (3, 3, 0)), ("A", "C"), Fraction(6)),
            # B + D: right two columns uniform.
            (((0, 4, 4), (1, 4, 4), (0, 4, 4)), ("B", "D"), Fraction(10)),
            # A + D: diagonal blocks sharing only the centre cell.
            (((2, 2, 0), (2, 2, 2), (1, 2, 2)), ("A", "D"), Fraction(2)),
            # A + B + C: everything but the bottom-right corner.
            (((1, 1, 1), (1, 1, 1), (1, 1, 0)), ("A", "B", "C"), Fraction(33, 20)),
        ],
    )
    def test_overlapping_blocks_are_summed(self, grid, hits, payout, mode):
        # Without a full screen, both modes pay every hit block.
        assert evaluate_grid(grid, mode) == (payout, hits)

    def test_mode_accepts_strings(self):
        assert evaluate_grid(full(2), "sum_all")[0] == 9
        assert evaluate_grid(full(2), "full_only")[0] == 5

    def test_rejects_unknown_mode(self):
        with pytest.raises(ValueError):
            evaluate_grid(full(2), "full_screen")

    def test_pattern_hits_reports_symbols(self):
        assert pattern_hits(((2, 2, 0), (2, 2, 2), (1, 2, 2))) == {"A": 2, "D": 2}
        assert pattern_hits(full(0)) == dict.fromkeys("ABCDE", 0)

    def test_pattern_payouts_per_mode(self):
        hits = pattern_hits(full(3))
        assert pattern_payouts(hits, SUM_ALL) == {"A": 3, "B": 3, "C": 3, "D": 3, "E": 15}
        assert pattern_payouts(hits, FULL_ONLY) == {"E": 15}
        assert pattern_payouts({"A": 1, "C": 1}, FULL_ONLY) == {
            "A": Fraction(11, 20),
            "C": Fraction(11, 20),
        }
