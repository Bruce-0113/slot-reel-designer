"""Tests for the final reel configurations, configs/reels.json and configs/reels_full_only.json."""

import json
import random
from collections import Counter
from fractions import Fraction
from math import prod

import numpy as np
import pytest

from slot_reel_designer.evaluator import Evaluation, evaluate, evaluate_bruteforce
from slot_reel_designer.game import (
    FULL_SCREEN,
    FULL_SCREEN_FACTOR,
    MULTIPLIERS,
    PATTERNS,
    ROWS,
    SYMBOLS,
    PayoutMode,
)
from slot_reel_designer.search import (
    CONFIG_PATHS,
    DEFAULT_SEED,
    MAX_LENGTH,
    check_preferences,
    check_requirements,
    config_json,
    count_reels,
    evaluate_counts,
    load_config,
    search,
    symbol_hit_prob,
    to_config,
)

SUM_ALL = PayoutMode.SUM_ALL
FULL_ONLY = PayoutMode.FULL_ONLY
CONFIG_KEYS = [
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
MAX_ENUMERATED = 3_000_000  # stop combinations scored one by one in `enumerate_stops`
PAY_UNITS = 20  # pays in 1/20 of the bet are integers
PAY = {x: int(PAY_UNITS * m) for x, m in MULTIPLIERS.items()}


def enumerate_stops(reels, mode: PayoutMode) -> Evaluation:
    """Exact statistics from every stop combination, in integer pay units.

    Independent of the evaluator and the count model: for each middle stop,
    all (left, right) stop pairs are scored at once with numpy, straight
    from the nine cells and the pattern definitions.
    """
    left, mid, right = (np.asarray(reel, dtype=np.int64) for reel in reels)
    # shown[row][s] is the symbol in that row when the reel stops at s.
    shown = [[np.roll(reel, -row) for row in range(ROWS)] for reel in (left, mid, right)]
    pay_of = np.array([PAY[x] for x in SYMBOLS], dtype=np.int64)
    shape = (len(left), len(right))
    hits = above_bet = 0
    pattern_count: Counter[str] = Counter()
    paid_pattern: Counter[str] = Counter()
    paid_symbol: Counter[int] = Counter()
    for stop in range(len(mid)):
        cells = {}
        for row in range(ROWS):
            cells[row, 0] = np.broadcast_to(shown[0][row][:, None], shape)
            cells[row, 1] = np.full(shape, shown[1][row][stop])
            cells[row, 2] = np.broadcast_to(shown[2][row][None, :], shape)
        masks, symbols, pays = {}, {}, {}
        for name, pattern_cells in PATTERNS.items():
            first = cells[pattern_cells[0]]
            mask = np.ones(shape, dtype=bool)
            for cell in pattern_cells[1:]:
                mask &= cells[cell] == first
            factor = FULL_SCREEN_FACTOR if name == FULL_SCREEN else 1
            masks[name], symbols[name] = mask, first
            pays[name] = np.where(mask, pay_of[first] * factor, 0)
        if mode is FULL_ONLY:  # a full screen pays E alone
            for name in pays:
                if name != FULL_SCREEN:
                    pays[name] = np.where(masks[FULL_SCREEN], 0, pays[name])
        payout = sum(pays.values())
        hits += int(np.count_nonzero(payout > 0))
        above_bet += int(np.count_nonzero(payout > PAY_UNITS))
        for name in PATTERNS:
            pattern_count[name] += int(masks[name].sum())
            paid_pattern[name] += int(pays[name].sum())
            for x in SYMBOLS:
                paid_symbol[x] += int(pays[name][symbols[name] == x].sum())
    total = prod(len(reel) for reel in reels)
    scale = PAY_UNITS * total
    return Evaluation(
        total_outcomes=total,
        rtp=Fraction(sum(paid_pattern.values()), scale),
        hit_rate=Fraction(hits, total),
        win_rate_above_bet=Fraction(above_bet, total),
        pattern_hit_prob={name: Fraction(pattern_count[name], total) for name in PATTERNS},
        rtp_by_pattern={name: Fraction(paid_pattern[name], scale) for name in PATTERNS},
        rtp_by_symbol={x: Fraction(paid_symbol[x], scale) for x in SYMBOLS},
    )


@pytest.mark.parametrize("mode", list(PayoutMode))
@pytest.mark.parametrize("seed", range(30))
def test_enumerate_stops_matches_bruteforce(seed, mode):
    """The reference used below agrees with the evaluator's own brute force."""
    rng = random.Random(seed)
    palette = rng.sample(SYMBOLS, rng.randint(1, 3))
    reels = [rng.choices(palette, k=rng.randint(1, 9)) for _ in range(3)]
    assert enumerate_stops(reels, mode) == evaluate_bruteforce(reels, mode)


@pytest.fixture(scope="module", params=list(PayoutMode), ids=str)
def mode(request) -> PayoutMode:
    """The payout mode whose config is under test."""
    return request.param


@pytest.fixture(scope="module")
def config(mode) -> dict:
    """The saved configuration of ``mode``."""
    return json.loads(CONFIG_PATHS[mode].read_text())


@pytest.fixture(scope="module")
def evaluation(config) -> Evaluation:
    """The exact evaluation of the saved reels."""
    return evaluate(config["reels"], config["mode"])


def test_config_files():
    assert CONFIG_PATHS[SUM_ALL].name == "reels.json"
    assert CONFIG_PATHS[FULL_ONLY].name == "reels_full_only.json"


def test_load_config(mode, config):
    reels = tuple(tuple(reel) for reel in config["reels"])
    assert load_config(CONFIG_PATHS[mode]) == (mode, reels)
    assert load_config(str(CONFIG_PATHS[mode])) == (mode, reels)


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        "[1, 2]",
        '{"mode": "sum_all"}',
        '{"reels": [[0], [1], [2]]}',
        '{"mode": "both", "reels": [[0], [1], [2]]}',
        '{"mode": "sum_all", "reels": [[0], [1]]}',
        '{"mode": "sum_all", "reels": [[0], [1], [5]]}',
    ],
)
def test_load_config_rejects_malformed_files(tmp_path, content):
    path = tmp_path / "bad.json"
    path.write_text(content)
    with pytest.raises(ValueError):
        load_config(path)


class TestSavedConfig:
    def test_keys(self, config, mode):
        assert list(config) == CONFIG_KEYS
        assert config["mode"] == str(mode)
        assert config["seed"] == DEFAULT_SEED

    def test_hard_requirements(self, config, evaluation):
        """H1-H5 hold exactly."""
        assert evaluation.rtp == Fraction(19, 20)
        assert evaluation.hit_rate >= Fraction(11, 20)
        assert check_requirements(evaluation, config["reels"]) == []

    def test_stored_metrics_match_evaluator(self, config, evaluation):
        assert config["rtp"] == "19/20"
        assert config["hit_rate"] == str(evaluation.hit_rate)
        assert config["hit_rate_decimal"] == round(float(evaluation.hit_rate), 6)
        assert config["win_rate_above_bet"] == str(evaluation.win_rate_above_bet)
        assert config["total_outcomes"] == evaluation.total_outcomes
        assert config["lengths"] == [len(reel) for reel in config["reels"]]

    def test_evaluator_matches_stop_enumeration(self, config, evaluation, mode):
        """Every Evaluation field, against scoring all stop combinations independently."""
        assert evaluation.total_outcomes <= MAX_ENUMERATED
        assert enumerate_stops(config["reels"], mode) == evaluation

    def test_count_model_matches_evaluator(self, config, evaluation, mode):
        assert evaluate_counts(count_reels(config["reels"]), mode) == evaluation

    def test_symbol_hit_frequency_falls_with_multiplier(self, config, evaluation):
        """S1: symbol 0 forms wins most often, symbol 4 least."""
        hits = symbol_hit_prob(count_reels(config["reels"]))
        assert sum(hits.values()) == evaluation.hit_rate
        assert all(hits[x] > hits[x + 1] for x in SYMBOLS[:-1])
        assert all(evaluation.rtp_by_symbol[x] > 0 for x in SYMBOLS)

    def test_full_screen_of_every_symbol_is_possible(self, config):
        """S2: every reel shows (x, x, x) somewhere, for every symbol x."""
        for reel in config["reels"]:
            n = len(reel)
            windows = [tuple(reel[(i + row) % n] for row in range(ROWS)) for i in range(n)]
            assert {w[0] for w in windows if len(set(w)) == 1} == set(SYMBOLS)

    def test_preferences(self, config, evaluation, mode):
        """S1, S2 and S4 hold in both modes; full_only trades S3 for S1 and S2."""
        assert all(len(reel) <= MAX_LENGTH for reel in config["reels"])
        unmet = check_preferences(evaluation, config["reels"])
        if mode is SUM_ALL:
            assert unmet == []
            assert Fraction(11, 20) <= evaluation.hit_rate <= Fraction(7, 10)
        else:
            assert [message.split(":")[0] for message in unmet] == ["S3"]
            assert evaluation.hit_rate > Fraction(7, 10)

    def test_pinned_results(self, config):
        """The exact numbers quoted for the final designs."""
        expected = {
            "sum_all": ([130, 132, 149], "153437/232440", "189845/511368"),
            "full_only": ([143, 138, 149], "109103/127842", "2011195/2940366"),
        }
        lengths, hit_rate, above_bet = expected[config["mode"]]
        assert config["lengths"] == lengths
        assert config["hit_rate"] == hit_rate
        assert config["win_rate_above_bet"] == above_bet


@pytest.mark.slow
def test_search_reproduces_config(mode, config):
    """The saved file is exactly what `python -m slot_reel_designer.search` writes."""
    result = search(mode, config["seed"])
    assert to_config(result) == config
    assert config_json(result) == CONFIG_PATHS[mode].read_text()


@pytest.mark.slow
def test_evaluator_matches_bruteforce(config, evaluation):
    assert evaluate_bruteforce(config["reels"], config["mode"]) == evaluation
