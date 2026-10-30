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
3. A full-screen win also satisfies all four 2×2 patterns. The primary deliverable pays all five patterns (**`sum_all`**: 4 × multiplier + 5 × multiplier = 9 × multiplier, consistent with assumption 2): [`configs/reels.json`](configs/reels.json). A configuration for the other reading (**`full_only`**: the full screen pays 5 × multiplier alone) is also provided in [`configs/reels_full_only.json`](configs/reels_full_only.json).
4. "Win" means `payout > 0`. Results under `payout > bet` are also reported.
5. Bet = 1 unit per spin; RTP = E[payout] / bet.

## Design Requirements

The targets above fix only the RTP and the win rate. To read like a real game, the final reel sets are designed against these requirements (details: [`docs/methodology.md`](docs/methodology.md#1-notation-and-requirements)):

- **Hard** (checked exactly): H1 RTP = 19/20 exactly in the config's payout mode · H2 win rate ≥ 11/20 · H3 every symbol pays some RTP · H4 every pattern can hit · H5 every reel contains all 5 symbols.
- **Preferences** (in priority order): S1 the higher a symbol's multiplier, the less often a spin wins on it · S2 a full screen of every symbol is possible · S3 win rate in [0.55, 0.70] · S4 at most 150 symbols per reel.

## Result

Both reel sets meet H1–H5 exactly. The exact column is computed over every stop combination with fractions; the simulation column is `python -m slot_reel_designer.verify` (n = 10⁷ spins, seed 0), shown as estimate ± the 95% confidence-interval half-width (1.96 standard errors).

### Primary: `sum_all` ([`configs/reels.json`](configs/reels.json))

| Reel | Length | Strip (runs from index 0 as symbol×length; wraps around) |
|---|---|---|
| 1 | 130 | `0×50 1×9 4×3 0×50 1×9 2×5 3×3 4×1` |
| 2 | 132 | `1×16 2×5 1×16 0×83 2×4 3×5 4×3` |
| 3 | 149 | `0×55 1×10 2×9 3×4 4×3 0×55 1×10 2×1 3×1 4×1` |

<details>
<summary>Full strips</summary>

```text
reel 1: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 4, 4, 4, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 2, 3, 3, 3, 4]
reel 2: [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 2, 2, 2, 2, 3, 3, 3, 3, 3, 4, 4, 4]
reel 3: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 2, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 2, 3, 4]
```

</details>

| Metric | Exact (enumeration of 2,556,840 stop combinations) | Simulation (n = 10⁷) |
|---|---|---|
| RTP | 19/20 = 0.95 | 0.950049 ± 0.000618 |
| Win rate (payout > 0) | 153437/232440 ≈ 0.660114 | 0.660066 ± 0.000294 |
| Win rate (payout > bet) | 189845/511368 ≈ 0.371249 | 0.371318 ± 0.000299 |
| Payout s.d. per spin | 0.997510 | 0.997523 |

| Symbol | Multiplier | P(spin wins on symbol) | RTP contribution |
|---|---:|---:|---:|
| 0 | 0.25 | 0.590696 | 0.862253 |
| 1 | 0.55 | 0.060841 | 0.067716 |
| 2 | 1 | 0.006166 | 0.009163 |
| 3 | 3 | 0.001654 | 0.006493 |
| 4 | 5 | 0.000757 | 0.004375 |

Requirements: H1–H5 met; preferences S1–S4 all met.

### Alternative: `full_only` ([`configs/reels_full_only.json`](configs/reels_full_only.json))

| Reel | Length | Strip (runs from index 0 as symbol×length; wraps around) |
|---|---|---|
| 1 | 143 | `4×3 0×130 4×1 1×3 2×3 3×3` |
| 2 | 138 | `2×3 4×3 2×3 0×118 1×6 3×4 4×1` |
| 3 | 149 | `0×137 1×3 2×3 3×3 4×3` |

<details>
<summary>Full strips</summary>

```text
reel 1: [4, 4, 4, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 4, 1, 1, 1, 2, 2, 2, 3, 3, 3]
reel 2: [2, 2, 2, 4, 4, 4, 2, 2, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 3, 3, 3, 3, 4]
reel 3: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 2, 2, 2, 3, 3, 3, 4, 4, 4]
```

</details>

| Metric | Exact (enumeration of 2,940,366 stop combinations) | Simulation (n = 10⁷) |
|---|---|---|
| RTP | 19/20 = 0.95 | 0.949879 ± 0.000312 |
| Win rate (payout > 0) | 109103/127842 ≈ 0.853421 | 0.853397 ± 0.000219 |
| Win rate (payout > bet) | 2011195/2940366 ≈ 0.683995 | 0.683921 ± 0.000288 |
| Payout s.d. per spin | 0.502890 | 0.502709 |

| Symbol | Multiplier | P(spin wins on symbol) | RTP contribution |
|---|---:|---:|---:|
| 0 | 0.25 | 0.848794 | 0.939766 |
| 1 | 0.55 | 0.001574 | 0.001093 |
| 2 | 1 | 0.001379 | 0.001590 |
| 3 | 3 | 0.000984 | 0.003577 |
| 4 | 5 | 0.000689 | 0.003974 |

Requirements: H1–H5 met; preferences S1, S2 and S4 met. S3 is missed: the win rate is above 0.70, because under `full_only` a full screen of symbol 0 pays only 1.25 and S1 and S2 rank higher than S3 ([why](docs/methodology.md#6-the-two-payout-modes)).

In both simulations every exact value lies inside its 95% interval (|z| ≤ 0.76), and `verify` passes both configs.

RTP contribution by symbol and pattern, and the full payout distribution: see [`docs/par-sheet.md`](docs/par-sheet.md)

## Approach

1. **Proof of concept first** — a deliberately simple reel family reaches RTP = 19/20 exactly and exercises the whole pipeline ([`docs/poc.md`](docs/poc.md)); its weaknesses (every win on symbol 0, a 96% win rate) led to the design requirements above.
2. **Exact evaluator** — every reel reduces to counts of its distinct windows, and outer windows that cannot complete a 2×2 block with the middle one are merged into one blank column, so all L₁·L₂·L₃ stop combinations are covered with at most 125 × 10 × 10 scored grids. All arithmetic uses `fractions.Fraction`, so RTP equality is checked exactly, with no floating-point error.
3. **Counts model** — every statistic depends only on each reel's length and, per symbol, its cyclic pairs and triples (16 states per reel, 4,096 state combinations), not on how the strip is arranged. 20·L₁·L₂·L₃·RTP is an integer, so "RTP = 19/20" is integer bookkeeping.
4. **Search** — seeded simulated annealing over run counts (10 runs of 60,000 steps) minimises a penalty that follows the requirements' priorities. An exact finish then makes the RTP exactly 19/20: with two reels fixed, the integer RTP excess is affine in the third reel's run counts, so a meet-in-the-middle enumeration finds the counts that cancel it. Candidates with a hit rate below 11/20 are dropped before the best one is chosen.
5. **Strip construction** — the chosen run counts are laid out so that runs of one symbol never touch, and the built strips are re-checked with the exact evaluator.
6. **Verification** — exact enumeration, brute-force cross-checks, Monte Carlo simulation with 95% confidence intervals, and 2,490 tests.

Details: [`docs/methodology.md`](docs/methodology.md)

## Quick Start

Requires Python 3.10 or later.

```bash
python -m venv .venv
source .venv/bin/activate                 # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python -m slot_reel_designer.solve        # search both payout modes and rewrite configs/*.json (about 45 s)
python -m slot_reel_designer.verify       # exact check (H1–H5) + Monte Carlo with 10^7 spins per config
python -m slot_reel_designer.report       # regenerate docs/par-sheet.md and docs/par-sheet.zh-TW.md
pytest                                    # fast suite: 2,483 tests, a few seconds
pytest -m slow                            # 7 slow checks: search reruns, brute force (a few minutes)
```

- `solve` takes `--mode sum_all|full_only|both`, `--seed N` and `--out-dir DIR`. With the defaults it reproduces the committed configs byte for byte.
- `verify` takes `--config PATH ...`, `--n SPINS` and `--seed N`. It exits with code 1 if a config breaks H1–H5 or disagrees with the simulation by more than 4 standard errors.
- `python -m slot_reel_designer.poc` reruns the proof-of-concept scan and saves `configs/poc_reels.json`.

## Project Structure

```
.
├── README.md
├── README.zh-TW.md
├── pyproject.toml                # project metadata; pytest settings and the `slow` marker
├── requirements.txt              # numpy, pytest
├── configs/
│   ├── reels.json                # final reel strips, sum_all (primary)
│   ├── reels_full_only.json      # final reel strips, full_only (alternative)
│   └── poc_reels.json            # proof-of-concept reel strips
├── docs/
│   ├── problem.md                # problem statement
│   ├── problem.zh-TW.md          # Traditional Chinese version
│   ├── slot-game-primer.md       # background on slot-game mechanics
│   ├── slot-game-primer.zh-TW.md # Traditional Chinese version
│   ├── poc.md                    # proof of concept
│   ├── methodology.md            # evaluator, counts model, search and verification
│   ├── methodology.zh-TW.md      # Traditional Chinese version
│   ├── par-sheet.md              # PAR sheet: final probability/payout breakdown (generated)
│   └── par-sheet.zh-TW.md        # Traditional Chinese version (generated)
├── slot_reel_designer/
│   ├── game.py                   # window, patterns, payout rules and modes
│   ├── evaluator.py              # exact RTP / win-rate computation, payout distribution
│   ├── poc.py                    # proof-of-concept reel family and scan
│   ├── search.py                 # counts model, strip builder, search and exact finish
│   ├── simulate.py               # Monte Carlo simulation
│   ├── solve.py                  # CLI: search and save configs
│   ├── verify.py                 # CLI: exact check + Monte Carlo
│   └── report.py                 # CLI: generate the PAR sheets
└── tests/                        # pytest suite: one file per module, plus test_configs.py
```
