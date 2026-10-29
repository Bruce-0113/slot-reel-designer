"""Tests for the reel search: count model, strip builder, search, exact finish and checks."""

import json
import random
from collections import Counter
from dataclasses import replace
from fractions import Fraction
from itertools import groupby, product

import pytest

from slot_reel_designer.evaluator import evaluate, evaluate_bruteforce
from slot_reel_designer.game import PATTERNS, SYMBOLS, PayoutMode, pattern_hits, window
from slot_reel_designer.search import (
    EXTRA_SHIFT,
    OBJECTIVES,
    PAY,
    PAY_SCALE,
    RUN_SHIFT,
    SINGLE_SHIFT,
    TARGET_RTP,
    Objective,
    ReelCounts,
    ReelSpec,
    _alternating_fill,
    _cyclic_order,
    anneal,
    build_strip,
    check_preferences,
    check_requirements,
    config_json,
    count_reels,
    describe,
    evaluate_counts,
    exact_finish,
    excess_coefficients,
    fast_stats,
    full_screen_weight,
    in_domain,
    reel_states,
    rtp_excess,
    rtp_numerator,
    search,
    strip_counts,
    symbol_hit_numerators,
    symbol_hit_prob,
    to_config,
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


# Three equal reels: one run of 37 zeros, one run of 3 of every other symbol, 2 singletons.
# RTP (sum_all) is about 0.961, a little above the target.
SMALL = ReelSpec((1, 1, 1, 1, 1), (35, 1, 1, 1, 1), 2)


def pivot_of(start, specs) -> int | None:
    """The reel the finish varied: the others keep their runs and move few singletons."""
    for p in range(3):
        others_kept = all(
            specs[i].runs == start[i].runs
            and specs[i].extra == start[i].extra
            and abs(specs[i].singles - start[i].singles) <= SINGLE_SHIFT
            for i in range(3)
            if i != p
        )
        runs_near = all(abs(a - b) <= RUN_SHIFT for a, b in zip(specs[p].runs, start[p].runs))
        extra_near = all(
            abs(a - b) <= EXTRA_SHIFT[b >= 10] for a, b in zip(specs[p].extra, start[p].extra)
        )
        if others_kept and runs_near and extra_near:
            return p
    return None


class TestDomain:
    def test_in_domain(self):
        assert in_domain(SMALL)
        assert not in_domain(ReelSpec((1, 1, 1, 1, 0), (35, 1, 1, 1, 0), 2))  # no run of 4s
        assert not in_domain(ReelSpec((1, 1, 1, 1, 1), (35, 1, 1, 1, 0), 2))  # no 4, 4, 4
        assert in_domain(ReelSpec((1, 1, 1, 1, 1), (135, 1, 1, 1, 1), 1))  # 150 symbols
        assert not in_domain(ReelSpec((1, 1, 1, 1, 1), (135, 1, 1, 1, 1), 2))  # 151 symbols
        assert not in_domain(ReelSpec((1, 1, 1, 1, 1), (35, 1, 1, 1, 1), -1))

    def test_domain_reels_meet_h3_to_h5(self):
        reels = [build_strip(SMALL)] * 3
        ev = evaluate(reels)
        assert [v for v in check_requirements(ev, reels) if not v.startswith("H1")] == []
        assert check_preferences(ev, reels)[0].startswith("S1")  # equal reels: equal odds


class TestObjective:
    def test_rtp_term(self):
        obj = Objective()
        hits, lengths = [0.5, 0.1, 0.05, 0.02, 0.01], [100, 100, 100]
        on_target = obj.penalty(0.95, 0.6, hits, lengths)
        assert obj.penalty(0.96, 0.6, hits, lengths) == pytest.approx(on_target + 10)
        assert obj.penalty(0.96, 0.6, hits, lengths, with_rtp=False) == pytest.approx(on_target)

    def test_priorities(self):
        obj = Objective()
        hits, lengths = [0.5, 0.1, 0.05, 0.02, 0.01], [100, 100, 100]
        base = obj.penalty(0.95, 0.6, hits, lengths)
        inverted = obj.penalty(0.95, 0.6, [0.5, 0.1, 0.05, 0.01, 0.02], lengths)
        too_high = obj.penalty(0.95, 0.75, hits, lengths)
        too_low = obj.penalty(0.95, 0.54, hits, lengths)
        longer = obj.penalty(0.95, 0.6, hits, [150, 150, 150])
        # Longer reels cost least, then leaving the S3 band; H2 and S1 breaches cost most.
        assert base < longer < too_high < min(inverted, too_low)

    def test_full_only_drops_smoothness(self):
        assert OBJECTIVES[SUM_ALL].w_smooth > 0
        assert OBJECTIVES[FULL_ONLY] == replace(OBJECTIVES[SUM_ALL], w_smooth=0.0)


class TestExactFinish:
    def test_rtp_excess(self):
        specs = (SMALL, SMALL, SMALL)
        ev = evaluate_counts([s.counts for s in specs], SUM_ALL)
        assert rtp_excess(specs, SUM_ALL) == PAY_SCALE * ev.total_outcomes * (ev.rtp - TARGET_RTP)
        assert rtp_excess(specs, SUM_ALL) > 0 > rtp_excess(specs, FULL_ONLY)

    @pytest.mark.parametrize("mode", MODES)
    @pytest.mark.parametrize("pivot", range(3))
    def test_excess_is_affine_in_the_pivot(self, mode, pivot):
        rng = random.Random(pivot)
        specs = (SMALL, ReelSpec((2, 1, 3, 1, 1), (20, 3, 2, 1, 4), 4), random_spec(rng))
        f0, coefs, gamma = excess_coefficients(specs, pivot, mode)
        for _ in range(50):
            spec = random_spec(rng)
            moved = specs[:pivot] + (spec,) + specs[pivot + 1 :]
            counters = (*spec.runs, *spec.extra)
            linear = sum(c * v for c, v in zip(coefs, counters, strict=True))
            assert rtp_excess(moved, mode) == f0 + linear + gamma * spec.singles

    def test_lands_on_19_20(self):
        start = (SMALL, SMALL, SMALL)
        candidates = exact_finish(start, SUM_ALL)
        assert len(candidates) >= 100
        penalties = [c.penalty for c in candidates]
        assert penalties == sorted(penalties)
        assert len({c.specs for c in candidates}) == len(candidates)
        for candidate in candidates:
            assert rtp_excess(candidate.specs, SUM_ALL) == 0
            assert all(in_domain(spec) for spec in candidate.specs)
            assert pivot_of(start, candidate.specs) is not None
        for candidate in candidates[:3]:
            reels = [build_strip(spec) for spec in candidate.specs]
            ev = evaluate(reels, SUM_ALL)
            assert ev.rtp == Fraction(19, 20)
            assert check_requirements(ev, reels) == []

    def test_recovers_a_perturbed_solution(self):
        solution = exact_finish((SMALL, SMALL, SMALL), SUM_ALL)[0].specs
        off = (replace(solution[0], singles=solution[0].singles + 1), *solution[1:])
        assert rtp_excess(off, SUM_ALL) != 0
        candidates = exact_finish(off, SUM_ALL, single_shift=1, run_shift=1, extra_shift=(1, 1))
        assert solution in [c.specs for c in candidates]

    def test_nothing_out_of_reach(self):
        """RTP far below target: singletons only lower it, so no nearby set is exact."""
        low = ReelSpec((1, 1, 1, 1, 1), (20, 1, 1, 1, 1), 2)
        assert exact_finish((low, low, low), SUM_ALL) == []


class TestAnneal:
    def test_deterministic_and_near_target(self):
        first = anneal(SUM_ALL, seed=3, steps=1500)
        assert anneal(SUM_ALL, seed=3, steps=1500) == first
        penalty, specs = first
        assert all(in_domain(spec) for spec in specs)
        rtp, hit_rate, _ = fast_stats([s.counts for s in specs], full_screen_weight(SUM_ALL))
        assert rtp == pytest.approx(0.95, abs=0.01)
        assert hit_rate > 0.55
        assert anneal(SUM_ALL, seed=4, steps=1500) != first


@pytest.fixture(scope="module")
def quick():
    """A short search (2 restarts of 2000 steps) in sum_all."""
    return search(SUM_ALL, seed=7, restarts=2, steps=2000)


class TestSearch:
    def test_exact_and_valid(self, quick):
        ev = quick.evaluation
        assert ev.rtp == Fraction(19, 20)
        assert ev == evaluate(quick.reels, SUM_ALL)
        assert quick.violations == []
        assert quick.reels == tuple(build_strip(spec) for spec in quick.specs)
        assert quick.symbol_hit_prob == symbol_hit_prob(count_reels(quick.reels))
        assert sum(quick.symbol_hit_prob.values()) == ev.hit_rate
        assert quick.exact_candidates >= 1
        assert (quick.mode, quick.seed) == (SUM_ALL, 7)

    def test_to_config(self, quick):
        config = to_config(quick)
        assert list(config) == [
            "mode",
            "reels",
            "lengths",
            "rtp",
            "hit_rate",
            "hit_rate_decimal",
            "win_rate_above_bet",
            "total_outcomes",
            "seed",
        ]
        assert config["mode"] == "sum_all"
        assert config["rtp"] == "19/20"
        assert config["lengths"] == [len(reel) for reel in quick.reels]
        assert config["seed"] == 7

    def test_config_json(self, quick):
        text = config_json(quick)
        assert json.loads(text) == to_config(quick)
        assert text.endswith("}\n")
        reel_lines = [line for line in text.splitlines() if line.startswith("    [")]
        reels = [json.loads(line.strip().rstrip(",")) for line in reel_lines]
        assert reels == to_config(quick)["reels"]
        assert not any(line.strip().rstrip(",").isdigit() for line in text.splitlines())

    def test_describe(self, quick):
        text = describe(quick)
        assert "RTP 19/20 = 0.950000" in text
        assert "hard requirements: all met" in text


FIVE = [0, 0, 0, 1, 1, 1, 2, 2, 2, 3, 3, 3, 4, 4, 4]  # a run of 3 of every symbol


def codes(messages: list[str]) -> list[str]:
    """The requirement codes (H1, S3, ...) of check messages."""
    return [message.split(":")[0] for message in messages]


@pytest.fixture(scope="module")
def passing():
    """An evaluation and reels that meet H1-H5, with the hit rate set to 3/5."""
    reels = [FIVE, FIVE, FIVE]
    return replace(evaluate(reels), rtp=Fraction(19, 20), hit_rate=Fraction(3, 5)), reels


class TestCheckRequirements:
    def test_passing(self, passing):
        assert check_requirements(*passing) == []

    @pytest.mark.parametrize(
        ("hit_rate", "expected"),
        [
            (Fraction(11, 20), []),
            (Fraction(10999, 20000), ["H2"]),
            (Fraction(1, 2), ["H2"]),
            (Fraction(11001, 20000), []),
            (Fraction(1), []),
        ],
    )
    def test_hit_rate_boundary(self, passing, hit_rate, expected):
        ev, reels = passing
        assert codes(check_requirements(replace(ev, hit_rate=hit_rate), reels)) == expected

    @pytest.mark.parametrize(
        ("rtp", "expected"),
        [
            (Fraction(95, 100), []),
            (Fraction(19, 20) + Fraction(1, 10**12), ["H1"]),
            (Fraction(19, 20) - Fraction(1, 10**12), ["H1"]),
            (Fraction(9, 4), ["H1"]),
        ],
    )
    def test_rtp_must_be_exact(self, passing, rtp, expected):
        ev, reels = passing
        assert codes(check_requirements(replace(ev, rtp=rtp), reels)) == expected

    @pytest.mark.parametrize("symbol", SYMBOLS)
    def test_symbol_without_rtp(self, passing, symbol):
        ev, reels = passing
        by_symbol = {**ev.rtp_by_symbol, symbol: Fraction(0)}
        violations = check_requirements(replace(ev, rtp_by_symbol=by_symbol), reels)
        assert violations == [f"H3: symbol {symbol} pays no RTP"]

    @pytest.mark.parametrize("pattern", list(PATTERNS))
    def test_pattern_never_hits(self, passing, pattern):
        ev, reels = passing
        prob = {**ev.pattern_hit_prob, pattern: Fraction(0)}
        violations = check_requirements(replace(ev, pattern_hit_prob=prob), reels)
        assert violations == [f"H4: pattern {pattern} never hits"]

    @pytest.mark.parametrize("reel", range(3))
    def test_missing_symbol(self, passing, reel):
        ev, reels = passing
        reels = [*reels]
        reels[reel] = [x for x in FIVE if x != 2]
        assert check_requirements(ev, reels) == [f"H5: reel {reel + 1} lacks symbols [2]"]

    def test_single_symbol_reel(self, passing):
        ev, reels = passing
        violations = check_requirements(ev, [reels[0], [3, 3, 3], reels[2]])
        assert violations == [
            "H5: reel 2 lacks symbols [0, 1, 2, 4]",
            "H5: reel 2 repeats the single symbol 3",
        ]

    def test_reports_every_violation(self, passing):
        ev, reels = passing
        ev = replace(ev, rtp=Fraction(1), hit_rate=Fraction(1, 2))
        assert codes(check_requirements(ev, [[0, 0, 1], *reels[1:]])) == ["H1", "H2", "H5"]

    def test_real_evaluation(self):
        reels = [FIVE, FIVE, FIVE]
        assert codes(check_requirements(evaluate(reels), reels)) == ["H1", "H2"]

    def test_rejects_invalid_reels(self, passing):
        with pytest.raises(ValueError):
            check_requirements(passing[0], [[0], [9], [1]])


class TestCheckPreferences:
    def test_equal_reels_break_s1_only(self, passing):
        ev, reels = passing
        assert codes(check_preferences(ev, reels)) == ["S1"] * 4

    def test_s2_needs_a_triple_on_every_reel(self, passing):
        ev, reels = passing
        no_444 = [0, 0, 0, 1, 1, 1, 2, 2, 2, 3, 3, 3, 4, 4, 1, 4]
        unmet = check_preferences(ev, [reels[0], no_444, reels[2]])
        assert "S2: no full screen of symbol 4 is possible" in unmet

    @pytest.mark.parametrize(
        ("hit_rate", "in_band"),
        [
            (Fraction(11, 20), True),
            (Fraction(7, 10), True),
            (Fraction(10999, 20000), False),
            (Fraction(7001, 10000), False),
        ],
    )
    def test_s3_band(self, passing, hit_rate, in_band):
        ev, reels = passing
        unmet = codes(check_preferences(replace(ev, hit_rate=hit_rate), reels))
        assert ("S3" not in unmet) is in_band

    def test_s4_length_cap(self, passing):
        ev, reels = passing
        assert "S4" not in codes(check_preferences(ev, [FIVE * 10, *reels[1:]]))  # 150
        long_reel = FIVE * 10 + [0]  # 151
        unmet = check_preferences(ev, [reels[0], long_reel, reels[2]])
        assert "S4: reel 2 has 151 symbols, more than 150" in unmet
