"""Command line: search for the final reel sets and save their configs.

    python -m slot_reel_designer.solve [--mode sum_all|full_only|both] [--seed N] [--out-dir DIR]

Runs ``search.search`` for each requested payout mode, prints a summary and
writes configs/reels.json (sum_all) and/or configs/reels_full_only.json.
``--seed N`` anneals with seeds N .. N + 9 (``search.RESTARTS`` runs), so
neighbouring seeds share most runs. With the defaults (both modes, seed 0)
it rewrites the committed configs byte for byte, in about 45 s; that has
been checked on one platform only, since the annealing steers by floating
point. A reel set that breaks a hard requirement is not saved, and the exit
code is then 1.
"""

from __future__ import annotations

import argparse
import time
from collections.abc import Sequence
from pathlib import Path

from .files import save
from .game import PayoutMode
from .search import (
    CONFIG_DIR,
    CONFIG_PATHS,
    DEFAULT_SEED,
    RESTARTS,
    config_json,
    describe,
    search,
)

MODES: dict[str, tuple[PayoutMode, ...]] = {
    **{str(mode): (mode,) for mode in PayoutMode},
    "both": tuple(PayoutMode),
}


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse the command line."""
    parser = argparse.ArgumentParser(
        prog="python -m slot_reel_designer.solve",
        description="Search for reel sets with an RTP of exactly 19/20 and save their configs.",
    )
    parser.add_argument("--mode", choices=list(MODES), default="both", help="default: both")
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        metavar="N",
        help=f"anneal with seeds N .. N+{RESTARTS - 1} (default: {DEFAULT_SEED})",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=CONFIG_DIR,
        help="directory for reels.json and reels_full_only.json (default: configs/)",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Search the requested modes and save each config; return the exit code."""
    args = parse_args(argv)
    status = 0
    for mode in MODES[args.mode]:
        start = time.perf_counter()
        try:
            result = search(mode, args.seed)
        except RuntimeError as error:
            print(f"[{mode}] search failed: {error}")
            status = 1
            continue
        print(describe(result))
        print(f"  searched in {time.perf_counter() - start:.1f}s")
        if result.violations:
            print("  hard requirements broken; nothing saved")
            status = 1
            continue
        path = args.out_dir / CONFIG_PATHS[mode].name
        print(f"  saved {path} ({save(config_json(result), path)})")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
