# slot-reel-designer

English | [繁體中文](README.zh-TW.md)

Design slot reel strips for a 3×3 game that achieve an **exact RTP of 0.95** with a **hit frequency of at least 55%**, verified by exhaustive enumeration and Monte Carlo simulation.

> New to slot games? Start with the [Slot Game Primer](docs/slot-game-primer.md) ([繁體中文](docs/slot-game-primer.zh-TW.md)).

## Problem

- 3×3 window, 3 reels (strips may differ in length; no length limit)
- 5 symbols with multipliers `{0: 0.25, 1: 0.55, 2: 1, 3: 3, 4: 5}`
- 5 winning patterns: four 2×2 blocks (pays `bet × multiplier`) and full screen (pays `bet × multiplier × 5`)
- Targets: **RTP = 0.95** and **win rate ≥ 55%**

Full statement: [`docs/problem.md`](docs/problem.md)

## Assumptions

1. Each reel stops at a uniformly random index; reels are independent; the window shows 3 consecutive (wrapping) symbols.
2. When multiple patterns hit on one spin, payouts are **summed**.
3. A full-screen win also satisfies all four 2×2 patterns; this is treated as: _TBD (sum all = 9× / full-screen only = 5×)_.
4. "Win" means `payout > 0`. Results under `payout > bet` are also reported.
5. Bet = 1 unit per spin; RTP = E[payout] / bet.

## Result

<!-- Fill in after solving. -->

| Reel | Length | Strip |
|---|---|---|
| 1 | — | `[...]` |
| 2 | — | `[...]` |
| 3 | — | `[...]` |

| Metric | Exact (enumeration) | Simulation (n = 10⁷) |
|---|---|---|
| RTP | 19/20 = 0.95 | — ± — |
| Win rate (payout > 0) | — | — |
| Win rate (payout > bet) | — | — |

RTP contribution by symbol and pattern: see [`docs/par-sheet.md`](docs/par-sheet.md)

## Approach

1. **Exact evaluator** — enumerate all L₁·L₂·L₃ stop combinations with `fractions.Fraction`, so RTP equality is checked exactly, with no floating-point error.
2. **Search** — _TBD (e.g. structured construction + local search / ILP)_.
3. **Verification** — Monte Carlo simulation with confidence intervals.

Details: [`docs/methodology.md`](docs/methodology.md)

## Quick Start

```bash
pip install -r requirements.txt
python -m slot_reel_designer.solve      # search for a valid configuration
python -m slot_reel_designer.verify     # exact check + Monte Carlo
pytest
```

## Project Structure

```
.
├── README.md
├── README.zh-TW.md
├── docs/
│   ├── problem.md            # problem statement
│   ├── problem.zh-TW.md      # Traditional Chinese version
│   ├── slot-game-primer.md   # background on slot-game mechanics
│   ├── slot-game-primer.zh-TW.md  # Traditional Chinese version
│   ├── methodology.md        # derivation and search method
│   └── par-sheet.md          # final probability/payout breakdown
├── slot_reel_designer/
│   ├── game.py               # window, patterns, payout rules
│   ├── evaluator.py          # exact RTP / win-rate computation
│   ├── search.py             # configuration search
│   └── simulate.py           # Monte Carlo verification
├── configs/
│   └── reels.json            # final reel strips
└── tests/
```
