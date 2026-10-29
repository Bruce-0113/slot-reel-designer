"""Tests for `python -m slot_reel_designer.verify`."""

import json
import re
import subprocess
import sys
from dataclasses import replace

import pytest

from slot_reel_designer import verify
from slot_reel_designer.evaluator import evaluate
from slot_reel_designer.game import PayoutMode
from slot_reel_designer.poc import CONFIG_PATH as POC_CONFIG
from slot_reel_designer.search import CONFIG_DIR, CONFIG_PATHS, load_config
from slot_reel_designer.simulate import simulate

SPINS = "20000"  # small n keeps each run well under a second
POC_SHOWN = "configs/poc_reels.json"  # how verify prints POC_CONFIG from the repo root


@pytest.fixture(autouse=True)
def repo_root(monkeypatch):
    """Run from the repository root, where verify prints config paths relative to it."""
    monkeypatch.chdir(CONFIG_DIR.parent)


def run(argv: list[str], capsys) -> tuple[int, str]:
    """Exit code and printed output of verify.main(argv)."""
    code = verify.main(argv)
    return code, capsys.readouterr().out


def test_defaults():
    args = verify.parse_args([])
    assert args.config == list(CONFIG_PATHS.values())
    assert (args.n, args.seed) == (10_000_000, 0)


def test_both_configs_pass(capsys):
    code, out = run(["--n", SPINS], capsys)
    assert code == 0
    assert out.count("PASS") == 2 and "FAIL" not in out
    assert "configs/reels.json: sum_all" in out
    assert "configs/reels_full_only.json: full_only" in out
    assert out.count("RTP                 19/20 = 0.950000") == 2
    assert "hit rate            153437/232440 = 0.660114" in out
    assert "win rate above bet  2011195/2940366 = 0.683995" in out
    for label in ("H1", "H2", "H3", "H4", "H5"):
        assert out.count(f"{label} pass") == 2
    assert out.count("simulation: 20,000 spins, seed 0") == 2
    assert out.rstrip().endswith("all 2 configs passed")


def test_printed_estimates_match_simulate(capsys):
    config = str(CONFIG_PATHS[PayoutMode.SUM_ALL])
    code, out = run(["--config", config, "--n", SPINS, "--seed", "3"], capsys)
    assert code == 0
    mode, reels = load_config(CONFIG_PATHS[PayoutMode.SUM_ALL])
    sim = simulate(reels, int(SPINS), mode, seed=3)
    low, high = sim.rtp_ci95
    line = next(row for row in out.splitlines() if row.strip().startswith("RTP  ") and "[" in row)
    assert f"{sim.rtp_mean:.6f}" in line
    assert f"[{low:.6f}, {high:.6f}]" in line
    z = (sim.rtp_mean - 0.95) / sim.rtp_stderr
    assert f"{z:+.2f}" in line
    assert line.split()[-2:] == (["yes", "ok"] if low <= 0.95 <= high else ["no", "ok"])
    assert "seed 3" in out


def test_exact_section_matches_evaluator(capsys):
    _, out = run(["--config", str(CONFIG_PATHS[PayoutMode.FULL_ONLY]), "--n", SPINS], capsys)
    mode, reels = load_config(CONFIG_PATHS[PayoutMode.FULL_ONLY])
    ev = evaluate(reels, mode)
    assert f"{ev.rtp} = {float(ev.rtp):.6f}" in out
    assert f"{ev.hit_rate} = {float(ev.hit_rate):.6f}" in out
    assert f"{ev.win_rate_above_bet} = {float(ev.win_rate_above_bet):.6f}" in out
    assert "reels of 143, 138, 149 symbols, 2,940,366 stop combinations" in out


def test_broken_requirements_fail(capsys):
    """The proof-of-concept config has an all-zero middle reel: H3 and H5 fail."""
    code, out = run(["--config", str(POC_CONFIG), "--n", SPINS], capsys)
    assert code == 1
    assert "H1 pass" in out and "H2 pass" in out
    assert "H3 FAIL" in out and "H5 FAIL" in out
    assert "reel 2 repeats the single symbol 0" in out
    assert out.rstrip().endswith("1 of 1 configs failed: " + POC_SHOWN)


def test_one_failure_fails_the_run(capsys):
    configs = [str(POC_CONFIG), str(CONFIG_PATHS[PayoutMode.SUM_ALL])]
    code, out = run(["--config", *configs, "--n", SPINS], capsys)
    assert code == 1
    assert out.count("PASS") == 1 and out.count("FAIL\n") >= 1
    assert "1 of 2 configs failed" in out


def test_simulation_disagreement_fails(monkeypatch, capsys):
    """An estimate 10 standard errors off the exact RTP is a failure, not bad luck."""

    def biased(*args, **kwargs):
        sim = simulate(*args, **kwargs)
        mean = 0.95 + 10 * sim.rtp_stderr
        return replace(sim, rtp_mean=mean, rtp_ci95=(mean - 0.001, mean + 0.001))

    monkeypatch.setattr(verify, "simulate", biased)
    code, out = run(["--config", str(CONFIG_PATHS[PayoutMode.SUM_ALL]), "--n", SPINS], capsys)
    assert code == 1
    rtp_line = next(line for line in out.splitlines() if "+10.00" in line)
    assert rtp_line.split()[-2:] == ["no", "FAIL"]
    assert "H1 pass" in out


def test_z_check_tolerates_a_miss_of_the_95_interval(monkeypatch, capsys):
    """2.5 standard errors off lies outside the 95% CI but inside the 4 s.e. limit."""

    def unlucky(*args, **kwargs):
        sim = simulate(*args, **kwargs)
        mean = 0.95 + 2.5 * sim.rtp_stderr
        half = verify.Z95 * sim.rtp_stderr
        return replace(sim, rtp_mean=mean, rtp_ci95=(mean - half, mean + half))

    monkeypatch.setattr(verify, "simulate", unlucky)
    code, out = run(["--config", str(CONFIG_PATHS[PayoutMode.SUM_ALL]), "--n", SPINS], capsys)
    assert code == 0
    rtp_line = next(line for line in out.splitlines() if "+2.50" in line)
    assert rtp_line.split()[-2:] == ["no", "ok"]


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        '{"mode": "sum_all"}',
        '{"mode": "x", "reels": [[0], [0], [0]]}',
        '{"mode": "sum_all", "reels": [[0], [9], [0]]}',
    ],
)
def test_unreadable_config_fails(tmp_path, capsys, content):
    path = tmp_path / "bad.json"
    path.write_text(content)
    code, out = run(["--config", str(path), "--n", SPINS], capsys)
    assert code == 1
    assert f"{path}: cannot load" in out


def test_missing_config_fails(tmp_path, capsys):
    code, out = run(["--config", str(tmp_path / "missing.json"), "--n", SPINS], capsys)
    assert code == 1
    assert "cannot load" in out


def test_custom_config(tmp_path, capsys):
    """A hand-written config: the sum_all reels scored under full_only."""
    path = tmp_path / "copy.json"
    config = json.loads(CONFIG_PATHS[PayoutMode.SUM_ALL].read_text())
    path.write_text(json.dumps({"mode": "full_only", "reels": config["reels"]}))
    code, out = run(["--config", str(path), "--n", SPINS], capsys)
    assert code == 1  # the sum_all reels pay less than 19/20 under full_only
    assert re.search(r"H1 FAIL  RTP is \d+/\d+, not 19/20", out)


@pytest.mark.parametrize("argv", [["--n", "1"], ["--n", "ten"], ["--seed", "x"], ["--config"]])
def test_rejects_bad_arguments(argv):
    with pytest.raises(SystemExit) as error:
        verify.parse_args(argv)
    assert error.value.code == 2


@pytest.mark.parametrize(
    ("config", "code"), [(CONFIG_PATHS[PayoutMode.SUM_ALL], 0), (POC_CONFIG, 1)]
)
def test_exit_code_as_a_module(config, code):
    done = subprocess.run(
        [sys.executable, "-m", "slot_reel_designer.verify", "--config", str(config), "--n", "1000"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == code, done.stdout + done.stderr
