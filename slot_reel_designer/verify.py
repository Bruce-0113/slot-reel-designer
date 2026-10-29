"""Command line: check saved reel configs exactly and by Monte Carlo simulation.

    python -m slot_reel_designer.verify [--config PATH ...] [--n 10000000] [--seed N]

For each config (default: configs/reels.json and configs/reels_full_only.json)
it prints the exact metrics over all stop combinations (fractions and
decimals), the hard requirements H1-H5, and a simulation of n spins: each
estimate with its 95% confidence interval, the exact value, the z-score
(estimate - exact) / standard error, and whether the exact value lies
inside the 95% interval.

A config passes when it loads, H1-H5 hold and every exact value lies
within ``Z_LIMIT`` = 4 standard errors of its estimate. A 95% interval
misses the exact value 1 time in 20 by chance, so that alone is reported
but not failed on; 4 standard errors are exceeded by chance about 6 times
in 100,000. The exit code is 0 when every config passes and 1 otherwise.
"""

from __future__ import annotations

import argparse
import math
import time
from collections.abc import Sequence
from fractions import Fraction
from pathlib import Path

from .evaluator import evaluate, payout_distribution, payout_variance
from .search import CONFIG_PATHS, MIN_HIT_RATE, TARGET_RTP, check_requirements, load_config
from .simulate import DEFAULT_SEED, DEFAULT_SPINS, Z95, simulate

Z_LIMIT = 4.0  # standard errors allowed between a simulated estimate and the exact value
REQUIREMENTS = {
    "H1": f"RTP is exactly {TARGET_RTP}",
    "H2": f"hit rate >= {MIN_HIT_RATE}",
    "H3": "every symbol pays some RTP",
    "H4": "every pattern can hit",
    "H5": "every reel shows all 5 symbols",
}
LABEL = 20  # width of the metric column

__all__ = ["REQUIREMENTS", "Z95", "Z_LIMIT", "main", "parse_args", "verify_config"]


def _spins(text: str) -> int:
    """argparse type for --n: an int of at least 2."""
    try:
        n = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not an integer: {text!r}") from None
    if n < 2:
        raise argparse.ArgumentTypeError(f"need at least 2 spins, got {n}")
    return n


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse the command line; ``config`` defaults to both saved configs."""
    parser = argparse.ArgumentParser(
        prog="python -m slot_reel_designer.verify",
        description="Check reel configs exactly (H1-H5) and by Monte Carlo simulation.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        nargs="+",
        action="extend",
        metavar="PATH",
        help="config files (default: configs/reels.json configs/reels_full_only.json)",
    )
    parser.add_argument(
        "--n", type=_spins, default=DEFAULT_SPINS, help=f"spins (default: {DEFAULT_SPINS:_})"
    )
    parser.add_argument(
        "--seed", type=int, default=DEFAULT_SEED, help=f"simulation seed (default: {DEFAULT_SEED})"
    )
    args = parser.parse_args(argv)
    if args.config is None:
        args.config = list(CONFIG_PATHS.values())
    return args


def _shown(path: Path) -> str:
    """``path`` relative to the working directory when it lies inside it."""
    try:
        return str(path.resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(path)


def _exact(value: Fraction) -> str:
    """A fraction with its decimal value."""
    return f"{value} = {float(value):.6f}"


def _z(estimate: float, exact: float, stderr: float) -> float:
    """(estimate - exact) / stderr; 0 or +-inf when the standard error is 0."""
    if stderr > 0:
        return (estimate - exact) / stderr
    return 0.0 if estimate == exact else math.copysign(math.inf, estimate - exact)


def verify_config(path: Path, n: int, seed: int) -> bool:
    """Print the checks of one config; return True if it passes."""
    name = _shown(path)
    try:
        mode, reels = load_config(path)
    except (OSError, ValueError) as error:
        print(f"{name}: cannot load: {error}")
        print("  FAIL")
        return False
    ev = evaluate(reels, mode)
    exact_sd = math.sqrt(payout_variance(payout_distribution(reels, mode)))
    lengths = ", ".join(str(len(reel)) for reel in reels)
    print(f"{name}: {mode}, reels of {lengths} symbols, {ev.total_outcomes:,} stop combinations")

    print("  exact (all stop combinations)")
    exact = {"RTP": ev.rtp, "hit rate": ev.hit_rate, "win rate above bet": ev.win_rate_above_bet}
    for label, value in exact.items():
        print(f"    {label:<{LABEL}}{_exact(value)}")
    print(f"    {'payout s.d.':<{LABEL}}{exact_sd:.6f}")

    print("  requirements")
    violations = check_requirements(ev, reels)
    for code, text in REQUIREMENTS.items():
        failed = [v.split(": ", 1)[1] for v in violations if v.startswith(f"{code}:")]
        print(f"    {code} " + (f"FAIL  {'; '.join(failed)}" if failed else f"pass  {text}"))

    start = time.perf_counter()
    sim = simulate(reels, n, mode, seed)
    print(f"  simulation: {n:,} spins, seed {seed}, {time.perf_counter() - start:.2f}s")
    header = f"{'metric':<{LABEL}}{'estimate':<11}{'95% CI':<24}{'exact':<11}{'z':>7}"
    print(f"    {header}  in CI check")
    estimates = {
        "RTP": (sim.rtp_mean, sim.rtp_stderr, sim.rtp_ci95),
        "hit rate": (sim.hit_rate, sim.hit_rate_stderr, sim.hit_rate_ci95),
        "win rate above bet": (
            sim.win_rate_above_bet,
            sim.win_rate_above_bet_stderr,
            sim.win_rate_above_bet_ci95,
        ),
    }
    agree = True
    for label, (estimate, stderr, (low, high)) in estimates.items():
        value = float(exact[label])
        z = _z(estimate, value, stderr)
        inside = "yes" if low <= value <= high else "no"
        ok = abs(z) <= Z_LIMIT
        agree &= ok
        interval = f"[{low:.6f}, {high:.6f}]"
        print(
            f"    {label:<{LABEL}}{estimate:<11.6f}{interval:<24}{value:<11.6f}{z:>+7.2f}"
            f"  {inside:<5} {'ok' if ok else 'FAIL'}"
        )
    print(f"    {'payout s.d.':<{LABEL}}{sim.payout_sd:<11.6f}{'':<24}{exact_sd:.6f}")

    passed = not violations and agree
    print("  PASS" if passed else "  FAIL")
    return passed


def main(argv: Sequence[str] | None = None) -> int:
    """Verify every requested config; return the exit code."""
    args = parse_args(argv)
    failed = []
    for i, path in enumerate(args.config):
        if i:
            print()
        if not verify_config(path, args.n, args.seed):
            failed.append(_shown(path))
    print()
    total = len(args.config)
    if failed:
        print(f"{len(failed)} of {total} configs failed: {', '.join(failed)}")
        return 1
    print(f"all {total} configs passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
