# Proof of Concept

A first reel set that meets both targets exactly. It proves the targets can be reached and checks the whole pipeline: rules, exact evaluator, search and saved config. The design is deliberately simple and is not the final answer.

Code: [`slot_reel_designer/poc.py`](../slot_reel_designer/poc.py) · Config: [`configs/poc_reels.json`](../configs/poc_reels.json) · Tests: [`tests/test_poc.py`](../tests/test_poc.py)

```bash
.venv/bin/python -m slot_reel_designer.poc   # scans both payout modes (~7 s) and saves the sum_all config
```

## Construction

- **Reel 2** is all zeros: `[0, 0, 0]`.
- **Reels 1 and 3** each hold one run of `k` zeros followed by the filler `1, 2, 1, 2, ...`, `L` symbols in all (`2 <= k < L`).

Every pattern covers the middle column, which always shows `0, 0, 0`, so only symbol 0 can ever win. The filler is non-zero, so the outer reels show zero pairs only inside the run. The filler also never puts two equal symbols next to each other, which keeps the strips free of stray pairs if the middle reel changes later.

## Why it works

An outer column shows rows `(s, s+1, s+2)`. Inside a run of `k` zeros on a reel of length `L`:

| Event in one outer column | Stops | Pays through |
|---|---|---|
| rows 0-1 are zero | `k - 1` | A (left) or B (right) |
| rows 1-2 are zero | `k - 1` | C (left) or D (right) |
| rows 0-2 are zero | `k - 2` | E when the other outer column is also all zeros |
| some zero pair (any win) | `k` | |

Every pattern pays `0.25` per 2×2 block, and a full screen pays `5 × 0.25` extra under `sum_all` (on top of the four blocks). Under `full_only` it pays `5 × 0.25` instead of the blocks' `4 × 0.25`, a net extra of `0.25`. So:

```
RTP (sum_all)   = (k1-1)/(2 L1) + (k3-1)/(2 L3) + (5/4)(k1-2)(k3-2)/(L1 L3)
RTP (full_only) = (k1-1)/(2 L1) + (k3-1)/(2 L3) + (1/4)(k1-2)(k3-2)/(L1 L3)
hit rate        = 1 - (1 - k1/L1)(1 - k3/L3)
```

`tests/test_poc.py` checks these formulas against `evaluate` for every family member with `L <= 7` in both modes. The scan does not use the formulas: it scores each candidate with `evaluate`.

## Search

`scan(max_total, mode)` tries every `L1 <= L3`, `2 <= k < L` with `L1 + L2 + L3 <= max_total`. Mirroring the reels left to right gives the same statistics, so only `L1 <= L3` is scanned. It keeps the candidates where `RTP == 19/20` (exact `Fraction`) and `hit rate >= 11/20`, sorted by total length. With `max_total = 40`:

- `sum_all`: 11 solutions with L1 <= L3 (10 up to mirroring: `(L1, k1, L3, k3) = (15, 9, 15, 11)` and `(15, 11, 15, 9)` are mirror images). The smallest has total length 18 and is the only one at that length, up to mirroring. The next shortest has total length 28.
- `full_only`: 2 solutions with L1 <= L3, both with total length 36. Nothing shorter exists in this family.

`tests/test_poc.py` pins both solution lists.

## Chosen configuration (sum_all)

| Reel | Length | Strip |
|---|---|---|
| 1 | 5 | `[0, 0, 0, 0, 1]` (L1 = 5, k1 = 4) |
| 2 | 3 | `[0, 0, 0]` |
| 3 | 10 | `[0, 0, 0, 0, 0, 0, 0, 0, 1, 2]` (L3 = 10, k3 = 8) |

`RTP = 3/10 + 7/20 + (5/4)(2·6)/50 = 3/10 + 7/20 + 3/10 = 19/20`.

| Metric | Exact | Decimal |
|---|---|---|
| Outcomes (L1·L2·L3) | 150 | |
| RTP | 19/20 | 0.95 |
| Hit rate (payout > 0) | 24/25 | 0.96 |
| Win rate (payout > bet) | 6/25 | 0.24 |
| RTP via A / B / C / D / E | 3/20, 7/40, 3/20, 7/40, 3/10 | |

`evaluate` and `evaluate_bruteforce` agree on every field.

## full_only alternative

If the full screen pays only `5×` (README assumption 3), the smallest family members both have total length 36:

| L1, k1, L3, k3 | Reels 1 / 3 (reel 2 = `[0, 0, 0]`) | Hit rate | Win rate > bet |
|---|---|---|---|
| 10, 9, 23, 20 | 9 zeros + `1`; 20 zeros + `1, 2, 1` | 227/230 ≈ 0.987 | 63/115 ≈ 0.548 |
| 15, 12, 18, 17 | 12 zeros + `1, 2, 1`; 17 zeros + `1` | 89/90 ≈ 0.989 | 5/9 ≈ 0.556 |

Both have `RTP = 19/20` under `full_only` and miss it under `sum_all`. They are not saved as the main config.

## Limitations

- **Degenerate.** Every win is on symbol 0. Symbols 3 and 4 never appear, and 1 and 2 are only filler. All the RTP comes from the lowest multiplier.
- **Poor play feel.** 96% of spins "win", but 72% of spins pay only 0.25 to 0.75, below the bet. Only full screens (24%, paying 2.25) pay more than the bet.
- **Tiny reels.** There are only 150 outcomes and the pattern is obvious.
- **Narrow scan.** Allowing an all-zero outer reel (`k = L`) gives an even shorter set, `[0], [0, 0, 0], [0, 0, 0, 1, 2]`, with a 100% hit rate. It is left out on purpose because it is even more degenerate.

The final design will use all five symbols, give the higher symbols a share of the RTP, and keep the hit rate nearer the 55% floor. It will be checked with the same exact evaluator.
