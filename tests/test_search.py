"""Tests for the count model and the strip builder of the reel search."""

import random
from collections import Counter
from fractions import Fraction
from itertools import groupby, product

import pytest

from slot_reel_designer.evaluator import evaluate, evaluate_bruteforce
from slot_reel_designer.game import SYMBOLS, PayoutMode, pattern_hits, window
from slot_reel_designer.search import (
    PAY,
    PAY_SCALE,
    ReelCounts,
    ReelSpec,
    _alternating_fill,
    _cyclic_order,
    build_strip,
    count_reels,
    evaluate_counts,
    fast_stats,
    full_screen_weight,
    reel_states,
    rtp_numerator,
    strip_counts,
    symbol_hit_numerators,
    symbol_hit_prob,
)

SUM_ALL = PayoutMode.SUM_ALL
FULL_ONLY = PayoutMode.FULL_ONLY
MODES = list(PayoutMode)


def random_strip(rng: random.Random, max_length: int = 40) -> list[int]:
    """A clumpy strip over a few symbols, so pairs, triples and full screens are common."""
    alphabet = rng.sample(SYMBOLS, rng.randint(1, len(SYMBOLS)))
    length = rng.randint(1, max_length)
    strip = [rng.choice(alphabet)]
    while len(strip) < length:
        strip.append(strip[-1] if rng.random() < 0.5 else rng.choice(alphabet))
    return strip


def random_reels(seed: int, max_length: int = 40) -> list[list[int]]:
    """Three random clumpy strips."""
    rng = random.Random(seed)
    return [random_strip(rng, max_length) for _ in range(3)]


def random_spec(rng: random.Random) -> ReelSpec:
    """A random buildable run spec, with runs of every length from 2 up."""
    while True:
        runs = tuple(rng.randint(0, 5) for _ in SYMBOLS)
        extra = tuple(rng.randint(0, 8) if n else 0 for n in runs)
        spec = ReelSpec(runs, extra, rng.randint(0, 12))
        if spec.is_buildable():
            return spec


def window_state(strip, stop: int) -> tuple[int | None, int | None]:
    """(T, U) of one stop, straight from its window."""
    n = len(strip)
    a, b, c = (strip[(stop + row) % n] for row in range(3))
    return (a if a == b else None, b if b == c else None)


def cyclic_runs(strip) -> list[tuple[int, int]]:
    """(symbol, length) of every maximal run, going once round the cyclic strip."""
    n = len(strip)
    starts = [i for i in range(n) if strip[i] != strip[i - 1]]
    if not starts:  # one symbol all the way round
        return [(strip[0], n)]
    rotated = list(strip[starts[0]:]) + list(strip[:starts[0]])
    return [(x, len(list(group))) for x, group in groupby(rotated)]


SEEDS = range(150)


class TestCounts:
    def test_strip_counts_wrap(self):
        # [0,0,0,1,1,2]: pairs at 0, 1 (zeros) and 3 (ones); one zero triple.
        assert strip_counts([0, 0, 0, 1, 1, 2]) == ReelCounts(
            6, (2, 1, 0, 0, 0), (1, 0, 0, 0, 0)
        )
        # [2,1,1,2,2]: 2 at index 4 wraps onto index 0, giving 2,2,2 at 3,4,0.
        assert strip_counts([2, 1, 1, 2, 2]) == ReelCounts(
            5, (0, 1, 2, 0, 0), (0, 0, 1, 0, 0)
        )
        assert strip_counts([3, 3]) == ReelCounts(2, (0, 0, 0, 2, 0), (0, 0, 0, 2, 0))

    def test_reel_states_example(self):
        # Windows of [0,0,0,1,1,2] by stop: (0,0,0) (0,0,1) (0,1,1) (1,1,2) (1,2,0) (2,0,0).
        states = reel_states(strip_counts([0, 0, 0, 1, 1, 2]))
        assert {s: n for s, n in states.items() if n} == {
            (0, 0): 1,
            (0, None): 1,
            (None, 1): 1,
            (1, None): 1,
            (None, None): 1,
            (None, 0): 1,
        }
        assert len(states) == 16

    @pytest.mark.parametrize("seed", range(300))
    def test_reel_states_match_windows(self, seed):
        """A reel's (T, U) distribution depends only on L, pairs and triples."""
        strip = random_strip(random.Random(seed))
        direct = Counter(window_state(strip, stop) for stop in range(len(strip)))
        states = reel_states(strip_counts(strip))
        assert {s: n for s, n in states.items() if n} == direct
        assert sum(states.values()) == len(strip)

    def test_count_reels_validates(self):
        with pytest.raises(ValueError):
            count_reels([[0], [7], [1]])
        assert count_reels([[1], [1, 1], [0, 1]])[2] == ReelCounts(2, (0,) * 5, (0,) * 5)


class TestCountModel:
    @pytest.mark.parametrize("mode", MODES)
    @pytest.mark.parametrize("seed", SEEDS)
    def test_matches_evaluate(self, seed, mode):
        """Every Evaluation field, from counts alone."""
        reels = random_reels(seed)
        assert evaluate_counts(count_reels(reels), mode) == evaluate(reels, mode)

    @pytest.mark.parametrize("mode", MODES)
    @pytest.mark.parametrize("seed", range(10))
    def test_matches_bruteforce(self, seed, mode):
        reels = random_reels(1000 + seed, max_length=12)
        assert evaluate_counts(count_reels(reels), mode) == evaluate_bruteforce(reels, mode)

    def test_random_reels_are_not_vacuous(self):
        evaluations = [evaluate(random_reels(seed)) for seed in SEEDS]
        assert sum(ev.pattern_hit_prob["E"] > 0 for ev in evaluations) >= 20
        assert sum(0 < ev.hit_rate < 1 for ev in evaluations) >= 50
        assert sum(0 < ev.win_rate_above_bet < ev.hit_rate for ev in evaluations) >= 20

    @pytest.mark.parametrize("mode", MODES)
    @pytest.mark.parametrize("seed", SEEDS)
    def test_closed_forms(self, seed, mode):
        """The integer and float closed forms used by the search agree with the model."""
        counts = count_reels(random_reels(seed))
        ev = evaluate_counts(counts, mode)
        scale = PAY_SCALE * ev.total_outcomes
        assert rtp_numerator(counts, mode) == ev.rtp * scale
        hits = symbol_hit_numerators(counts)
        assert Fraction(sum(hits), ev.total_outcomes) == ev.hit_rate
        rtp, hit_rate, by_symbol = fast_stats(counts, full_screen_weight(mode))
        assert rtp == pytest.approx(float(ev.rtp), abs=1e-12)
        assert hit_rate == pytest.approx(float(ev.hit_rate), abs=1e-12)
        assert by_symbol == pytest.approx([h / ev.total_outcomes for h in hits], abs=1e-12)

    def test_integer_pays(self):
        assert PAY_SCALE == 20
        assert PAY == (5, 11, 20, 60, 100)

    def test_full_screen_weight(self):
        # Beyond the four blocks, a full screen adds 5m (sum_all) or 5m - 4m (full_only).
        assert full_screen_weight(SUM_ALL) == 5
        assert full_screen_weight("full_only") == 1


class TestSymbolHitProb:
    @pytest.mark.parametrize("seed", range(40))
    def test_matches_stop_enumeration(self, seed):
        """P(a spin wins on symbol x), counted stop by stop."""
        reels = random_reels(2000 + seed, max_length=10)
        wins: Counter[int] = Counter()
        stops = list(product(*(range(len(r)) for r in reels)))
        for stop in stops:
            symbols = set(pattern_hits(window(reels, stop)).values())
            assert len(symbols) <= 1  # two symbols never win on one spin
            wins.update(symbols)
        expected = {x: Fraction(wins[x], len(stops)) for x in SYMBOLS}
        assert symbol_hit_prob(count_reels(reels)) == expected

    @pytest.mark.parametrize("seed", range(20))
    def test_sums_to_hit_rate(self, seed):
        reels = random_reels(seed)
        assert sum(symbol_hit_prob(count_reels(reels)).values()) == evaluate(reels).hit_rate


class TestReelSpec:
    def test_length_and_counts(self):
        # Two zero runs share 3 extra zeros; every other symbol has one run of 3.
        spec = ReelSpec((2, 1, 1, 1, 1), (3, 1, 1, 1, 1), 2)
        assert spec.length == 2 * 2 + 3 + 4 * 3 + 2
        assert spec.counts == ReelCounts(21, (5, 2, 2, 2, 2), (3, 1, 1, 1, 1))

    def test_singles_go_to_missing_symbols_first(self):
        assert ReelSpec((3, 0, 0, 1, 1), (0, 0, 0, 0, 0), 4).singles_by_symbol() == [0, 1, 1, 1, 1]
        assert ReelSpec((3, 0, 0, 1, 1), (0, 0, 0, 0, 0), 1).singles_by_symbol() == [0, 1, 0, 0, 0]
        assert ReelSpec((1,) * 5, (0,) * 5, 3).singles_by_symbol() == [0, 0, 1, 1, 1]

    @pytest.mark.parametrize(
        "spec",
        [
            ReelSpec((1, 1, 1, 1, -1), (0,) * 5, 5),  # negative run count
            ReelSpec((1,) * 5, (0, 0, 0, 0, -1), 0),  # negative extra
            ReelSpec((1, 1, 1, 1, 0), (0, 0, 0, 0, 2), 1),  # extra without a run
            ReelSpec((1,) * 5, (0,) * 5, -1),  # negative singletons
            ReelSpec((1, 1, 1, 1, 0), (0,) * 5, 0),  # symbol 4 never appears
            ReelSpec((6, 1, 1, 1, 1), (0,) * 5, 0),  # 6 zero runs among 10 items must touch
        ],
    )
    def test_unbuildable(self, spec):
        assert not spec.is_buildable()
        with pytest.raises(ValueError):
            build_strip(spec)

    def test_dominant_symbol_at_the_limit(self):
        spec = ReelSpec((5, 1, 1, 1, 1), (0,) * 5, 1)  # 5 zero runs among 10 items
        assert spec.is_buildable()
        assert strip_counts(build_strip(spec)) == spec.counts


class TestBuildStrip:
    def test_example(self):
        strip = build_strip(ReelSpec((1, 1, 1, 1, 1), (2, 1, 0, 0, 0), 2))
        assert strip_counts(strip) == ReelCounts(15, (3, 2, 1, 1, 1), (2, 1, 0, 0, 0))
        assert set(strip) == set(SYMBOLS)

    @pytest.mark.parametrize("seed", range(300))
    def test_runs_are_exactly_the_spec(self, seed):
        """Counts match, and no two items of one symbol touch (cyclically)."""
        spec = random_spec(random.Random(seed))
        strip = build_strip(spec)
        assert len(strip) == spec.length
        assert strip_counts(strip) == spec.counts
        runs = cyclic_runs(strip)
        assert all(runs[i][0] != runs[i - 1][0] for i in range(len(runs)))
        singles = spec.singles_by_symbol()
        for x in SYMBOLS:
            lengths = [k for y, k in runs if y == x]
            long_runs = [k for k in lengths if k >= 2]
            assert len(long_runs) == spec.runs[x]
            assert sum(k - 2 for k in long_runs) == spec.extra[x]
            assert lengths.count(1) == singles[x]
            assert not long_runs or max(long_runs) - min(long_runs) <= 1  # extra spread evenly
        assert set(strip) == set(SYMBOLS)

    def test_deterministic(self):
        spec = ReelSpec((2, 2, 1, 1, 1), (96, 14, 3, 1, 1), 1)
        assert build_strip(spec) == build_strip(spec)


@pytest.mark.parametrize("order", [_cyclic_order, _alternating_fill])
def test_item_orders_never_repeat_a_symbol(order):
    """Both item orders work for every count vector where no symbol has over half the items."""
    for counts in product(range(1, 7), repeat=len(SYMBOLS)):
        if max(counts) <= sum(counts) // 2:
            out = order(list(counts))
            assert Counter(out) == dict(enumerate(counts))
            assert all(out[i] != out[i - 1] for i in range(len(out))), counts
