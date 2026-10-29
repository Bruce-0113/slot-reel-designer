"""Proof of concept: a simple reel family that reaches the targets exactly.

Reel 2 shows only zeros. Reels 1 and 3 each hold one run of ``k`` zeros
followed by a filler of 1, 2, 1, 2, ..., so 0 is the only symbol that ever
sits next to itself and every win is paid on symbol 0. Scanning the run
lengths and reel lengths finds members with an RTP of exactly 19/20; see
docs/poc.md for the closed-form RTP and hit rate.

Run ``python -m slot_reel_designer.poc`` to print the smallest solution in
each payout mode and save the sum_all one to configs/poc_reels.json.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

from .evaluator import Evaluation, evaluate
from .game import PayoutMode

Reels = tuple[tuple[int, ...], ...]
Params = tuple[int, int, int, int]  # (L1, k1, L3, k3)

TARGET_RTP = Fraction(19, 20)
MIN_HIT_RATE = Fraction(11, 20)
MIDDLE_REEL: tuple[int, ...] = (0, 0, 0)
MAX_TOTAL = 40  # default bound on L1 + L2 + L3 for the scan
CONFIG_PATH = Path(__file__).resolve().parent.parent / "configs" / "poc_reels.json"


@dataclass(frozen=True)
class Solution:
    """A family member that meets both targets, with its exact evaluation."""

    params: Params
    mode: PayoutMode
    reels: Reels
    evaluation: Evaluation

    @property
    def total_length(self) -> int:
        """Sum of the three reel lengths."""
        return sum(len(reel) for reel in self.reels)


def zero_run_strip(zeros: int, length: int) -> tuple[int, ...]:
    """Return ``zeros`` zeros followed by a 1, 2, 1, 2, ... filler, ``length`` symbols in all.

    The run is at least one zero long, so the filler is bounded by zeros on
    both sides (cyclically) and no two filler symbols sit next to each other
    with the same value.
    """
    if not 1 <= zeros <= length:
        raise ValueError(f"need 1 <= zeros <= length, got zeros={zeros}, length={length}")
    return (0,) * zeros + tuple(1 + i % 2 for i in range(length - zeros))


def build_reels(l1: int, k1: int, l3: int, k3: int) -> Reels:
    """Return the family member with outer reels of lengths L1, L3 and zero runs k1, k3."""
    return zero_run_strip(k1, l1), MIDDLE_REEL, zero_run_strip(k3, l3)


def meets_targets(ev: Evaluation) -> bool:
    """True if the RTP is exactly 19/20 and the hit rate is at least 11/20."""
    return ev.rtp == TARGET_RTP and ev.hit_rate >= MIN_HIT_RATE


def scan(
    max_total: int = MAX_TOTAL, mode: PayoutMode | str = PayoutMode.SUM_ALL
) -> list[Solution]:
    """Return every family member with L1 + L2 + L3 <= ``max_total`` that meets both targets.

    Runs satisfy 2 <= k < L, so each outer reel has a zero pair and a
    non-empty filler. Only L1 <= L3 is scanned, because mirroring the reels
    left to right gives the same statistics. Every candidate is scored with
    ``evaluate``. Results are sorted by total length, then by (L1, k1, L3, k3),
    so the first one is the shortest.
    """
    mode = PayoutMode(mode)
    budget = max_total - len(MIDDLE_REEL)  # room left for L1 + L3
    solutions = []
    for l1 in range(3, budget // 2 + 1):
        for l3 in range(l1, budget - l1 + 1):
            for k1 in range(2, l1):
                for k3 in range(2, l3):
                    params = (l1, k1, l3, k3)
                    reels = build_reels(*params)
                    ev = evaluate(reels, mode)
                    if meets_targets(ev):
                        solutions.append(Solution(params, mode, reels, ev))
    return sorted(solutions, key=lambda s: (s.total_length, s.params))


def to_config(solution: Solution) -> dict[str, Any]:
    """Return the JSON-ready record saved to configs/poc_reels.json."""
    ev = solution.evaluation
    return {
        "mode": str(solution.mode),
        "reels": [list(reel) for reel in solution.reels],
        "rtp": str(ev.rtp),
        "hit_rate": str(ev.hit_rate),
        "hit_rate_decimal": round(float(ev.hit_rate), 6),
        "win_rate_above_bet": str(ev.win_rate_above_bet),
        "total_outcomes": ev.total_outcomes,
    }


def describe(solution: Solution) -> str:
    """Return a few readable lines about ``solution``."""
    ev = solution.evaluation
    l1, k1, l3, k3 = solution.params
    lines = [
        f"L1={l1} k1={k1} L3={l3} k3={k3} (total length {solution.total_length})",
        *(f"  reel {i}: {list(reel)}" for i, reel in enumerate(solution.reels, start=1)),
        f"  RTP {ev.rtp} = {float(ev.rtp):.4f}",
        f"  hit rate {ev.hit_rate} = {float(ev.hit_rate):.4f}",
        f"  win rate above bet {ev.win_rate_above_bet} = {float(ev.win_rate_above_bet):.4f}",
        f"  outcomes {ev.total_outcomes}",
    ]
    return "\n".join(lines)


def main(max_total: int = MAX_TOTAL) -> None:
    """Print the smallest solution in each mode and save the sum_all one."""
    best: dict[PayoutMode, Solution] = {}
    for mode in PayoutMode:
        solutions = scan(max_total, mode)
        print(f"[{mode}] {len(solutions)} solutions with L1 <= L3 and total length <= {max_total}")
        if solutions:
            best[mode] = solutions[0]
            print(describe(solutions[0]))
    if PayoutMode.SUM_ALL not in best:
        raise SystemExit("no sum_all solution found; raise max_total")
    CONFIG_PATH.parent.mkdir(exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(to_config(best[PayoutMode.SUM_ALL]), indent=2) + "\n")
    print(f"saved {CONFIG_PATH}")


if __name__ == "__main__":
    main()
