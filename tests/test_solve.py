"""Tests for `python -m slot_reel_designer.solve`."""

import json
import subprocess
import sys
from dataclasses import replace

import pytest

from slot_reel_designer import solve
from slot_reel_designer.evaluator import evaluate
from slot_reel_designer.game import PayoutMode, validate_reels
from slot_reel_designer.poc import build_reels
from slot_reel_designer.search import (
    CONFIG_DIR,
    CONFIG_PATHS,
    DEFAULT_SEED,
    SearchResult,
    count_reels,
    symbol_hit_prob,
)

SUM_ALL = PayoutMode.SUM_ALL
FULL_ONLY = PayoutMode.FULL_ONLY


def result_from_reels(reels, mode: PayoutMode, seed: int = DEFAULT_SEED) -> SearchResult:
    """A SearchResult for given reels, standing in for a real (20 s) search."""
    reels = validate_reels(reels)
    hits = symbol_hit_prob(count_reels(reels))
    return SearchResult(mode, seed, (), reels, evaluate(reels, mode), hits, 0.0, 0)


def saved_result(mode: PayoutMode) -> SearchResult:
    """The committed config of ``mode`` as a SearchResult."""
    return result_from_reels(json.loads(CONFIG_PATHS[mode].read_text())["reels"], mode)


@pytest.fixture
def calls(monkeypatch) -> list[tuple[PayoutMode, int]]:
    """Replace the search with the committed results; record (mode, seed) of each call."""
    made: list[tuple[PayoutMode, int]] = []

    def fake_search(mode, seed):
        made.append((PayoutMode(mode), seed))
        return replace(saved_result(PayoutMode(mode)), seed=seed)

    monkeypatch.setattr(solve, "search", fake_search)
    return made


def test_defaults():
    args = solve.parse_args([])
    assert (args.mode, args.seed, args.out_dir) == ("both", DEFAULT_SEED, CONFIG_DIR)


def test_default_run_writes_the_committed_configs(calls, tmp_path, capsys):
    assert solve.main(["--out-dir", str(tmp_path)]) == 0
    assert calls == [(SUM_ALL, 0), (FULL_ONLY, 0)]
    for path in CONFIG_PATHS.values():
        assert (tmp_path / path.name).read_bytes() == path.read_bytes()
    out = capsys.readouterr().out
    assert "[sum_all] seed 0" in out and "[full_only] seed 0" in out
    assert "RTP 19/20 = 0.950000" in out
    assert out.count("(created)") == 2


def test_rerun_reports_unchanged_files(calls, tmp_path, capsys):
    solve.main(["--out-dir", str(tmp_path)])
    capsys.readouterr()
    assert solve.main(["--out-dir", str(tmp_path)]) == 0
    assert capsys.readouterr().out.count("(unchanged)") == 2


def test_one_mode_and_a_seed(calls, tmp_path, capsys):
    assert solve.main(["--mode", "full_only", "--seed", "5", "--out-dir", str(tmp_path)]) == 0
    assert calls == [(FULL_ONLY, 5)]
    assert [p.name for p in tmp_path.iterdir()] == ["reels_full_only.json"]
    assert json.loads((tmp_path / "reels_full_only.json").read_text())["seed"] == 5
    assert "seed 5" in capsys.readouterr().out


def test_sum_all_only(calls, tmp_path):
    assert solve.main(["--mode", "sum_all", "--out-dir", str(tmp_path)]) == 0
    assert calls == [(SUM_ALL, 0)]
    assert [p.name for p in tmp_path.iterdir()] == ["reels.json"]


def test_existing_file_is_updated(calls, tmp_path, capsys):
    (tmp_path / "reels.json").write_text("{}\n")
    assert solve.main(["--mode", "sum_all", "--out-dir", str(tmp_path)]) == 0
    assert "(updated)" in capsys.readouterr().out
    assert (tmp_path / "reels.json").read_bytes() == CONFIG_PATHS[SUM_ALL].read_bytes()


def test_broken_requirements_save_nothing(monkeypatch, tmp_path, capsys):
    poc = result_from_reels(build_reels(3, 2, 15, 9), SUM_ALL)  # an all-zero middle reel
    monkeypatch.setattr(solve, "search", lambda mode, seed: poc)
    assert solve.main(["--mode", "sum_all", "--out-dir", str(tmp_path)]) == 1
    assert list(tmp_path.iterdir()) == []
    assert "nothing saved" in capsys.readouterr().out


def test_failed_search_is_reported(monkeypatch, tmp_path, capsys):
    def no_solution(mode, seed):
        raise RuntimeError("no reel set found")

    monkeypatch.setattr(solve, "search", no_solution)
    assert solve.main(["--out-dir", str(tmp_path)]) == 1
    assert capsys.readouterr().out.count("no reel set found") == 2
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("argv", [["--mode", "both_modes"], ["--seed", "x"]])
def test_rejects_bad_arguments(argv):
    with pytest.raises(SystemExit) as error:
        solve.parse_args(argv)
    assert error.value.code == 2


def test_runs_as_a_module():
    done = subprocess.run(
        [sys.executable, "-m", "slot_reel_designer.solve", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0
    assert "--mode" in done.stdout
    assert "anneal with seeds N .. N+9" in done.stdout  # --seed N starts 10 restarts


@pytest.mark.slow
def test_defaults_reproduce_the_committed_configs(tmp_path):
    """The real search with default arguments rewrites both configs byte for byte (~45 s)."""
    assert solve.main(["--out-dir", str(tmp_path)]) == 0
    for path in CONFIG_PATHS.values():
        assert (tmp_path / path.name).read_bytes() == path.read_bytes()
