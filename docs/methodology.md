# Methodology

English | [繁體中文](methodology.zh-TW.md)

How the final reel sets in [`configs/`](../configs) were designed and checked: the exact evaluator, the counts model behind the search, the search and its exact finish, the strip construction, the two payout modes, and the verification. The results themselves are in the [README](../README.md#result) and the [PAR sheet](par-sheet.md).

> **The proof of concept came first.** [`docs/poc.md`](poc.md) builds a deliberately simple reel family (an all-zero middle reel) that reaches RTP = 19/20 exactly and exercises the whole pipeline. Its weaknesses (every win on symbol 0, a 96% hit rate, 150 outcomes) set the extra requirements below.

---

## 1. Notation and requirements

- Reel i has length L<sub>i</sub> and stops uniformly at s<sub>i</sub>; its column shows r<sub>i</sub>[s<sub>i</sub>], r<sub>i</sub>[s<sub>i</sub>+1], r<sub>i</sub>[s<sub>i</sub>+2] top to bottom, indices mod L<sub>i</sub>.
- There are N = L<sub>1</sub>·L<sub>2</sub>·L<sub>3</sub> equally likely *spins* (stop combinations). The bet is 1.
- m(x) is the multiplier of symbol x: `{0: 1/4, 1: 11/20, 2: 1, 3: 3, 4: 5}`. Patterns A–D (2×2 blocks) pay m(x), and E (full screen) pays 5·m(x).
- *Hit rate* = P(payout > 0) (the README's "win rate"); *win rate above bet* = P(payout > 1).

The problem fixes only the RTP and the hit rate. The final reel sets must also be usable as a real game, so they are designed against these requirements (`check_requirements` and `check_preferences` in [`search.py`](../slot_reel_designer/search.py)):

| | Requirement | Kind |
|---|---|---|
| H1 | RTP is exactly 19/20 in the config's payout mode | hard |
| H2 | hit rate ≥ 11/20 | hard |
| H3 | every symbol 0–4 pays some RTP | hard |
| H4 | every pattern A–E can hit | hard |
| H5 | every reel contains all 5 symbols (so no reel is a single repeated symbol) | hard |
| S1 | the more a symbol pays, the less often a spin wins on it, like a real paytable | preference 1 |
| S2 | a full screen of every symbol is possible | preference 2 |
| S3 | hit rate in [0.55, 0.70], a realistic value rather than nearly every spin | preference 3 |
| S4 | each reel has at most 150 symbols, so strips stay readable | preference 4 |

Hard requirements are checked exactly with `Fraction`s. Preferences are listed in priority order; the search trades a lower one for a higher one.

## 2. Exact evaluator

Code: [`evaluator.py`](../slot_reel_designer/evaluator.py).

**Brute force (reference).** `evaluate_bruteforce` builds the window of every one of the N spins and scores it with the game rules in [`game.py`](../slot_reel_designer/game.py). It is the definition of correct, but its cost grows with N.

**Window counting.** A reel's stops matter only through the window (top, middle, bottom) they show, so each reel is first reduced to the counts of its distinct windows (`window_counts`). There are at most 5³ = 125 of them; the final reels have 15 to 19 each. A (left, middle, right) window combination stands for left count × middle count × right count spins.

**Blank-column merge.** Fix a middle window. Every pattern that touches an outer column contains a 2×2 block made of that column and the middle one (A and C on the left, B and D on the right, and E contains them all). So an outer window that completes no 2×2 block with the middle window takes part in no hit, and all such windows score alike. They are merged into one *blank* column that matches nothing and carries their total count. A middle window with a pair keeps at most 9 outer windows plus the blank on each side, and one without a pair keeps only the blank. That bounds the work at 125 × 10 × 10 scored grids, however long the reels are. The tests evaluate random reels of lengths 2,000, 2,500 and 3,000 (1.5 × 10¹⁰ spins) exactly within a 2-second limit.

`outcome_counts` returns the number of spins behind each set of (pattern, symbol) hits. Everything else is derived from it with integers and `Fraction`s: `evaluate` (RTP, hit rate, win rate above bet, per-pattern and per-symbol figures), `payout_distribution` and `payout_variance`. No floating point is involved, so "RTP == 19/20" is an exact equality test.

## 3. The counts model: 16 states per reel

Code: the "count model" section of [`search.py`](../slot_reel_designer/search.py).

### States

For one reel at stop s with window (a, b, c), define

```
T = a if a == b else None     (a pair on rows 0-1)
U = b if b == c else None     (a pair on rows 1-2)
```

T and U can only both be set when a = b = c, so each stop is in one of 16 states: (None, None), and (x, None), (None, x), (x, x) for each of the 5 symbols.

### Every pattern is a condition on states

With T<sub>i</sub>, U<sub>i</sub> the state of reel i:

| Pattern | Hits with symbol x exactly when |
|---|---|
| A (top-left) | T<sub>1</sub> = T<sub>2</sub> = x |
| B (top-right) | T<sub>2</sub> = T<sub>3</sub> = x |
| C (bottom-left) | U<sub>1</sub> = U<sub>2</sub> = x |
| D (bottom-right) | U<sub>2</sub> = U<sub>3</sub> = x |
| E (full screen) | T<sub>i</sub> = U<sub>i</sub> = x on all three reels, i.e. every column is (x, x, x) |

For example, A's cells are rows 0–1 of reels 1 and 2, and they all show x exactly when both reels have a rows 0–1 pair of x.

### One reel's state distribution depends only on its counts

For a cyclic strip r of length L and a symbol x, let

```
pairs(x)   = #{i : r[i] = r[i+1] = x}
triples(x) = #{i : r[i] = r[i+1] = r[i+2] = x}      (indices mod L)
```

Then, over the L stops of the reel:

| State | Stops |
|---|---|
| (x, None) | pairs(x) − triples(x) |
| (None, x) | pairs(x) − triples(x) |
| (x, x) | triples(x) |
| (None, None) | the rest |

**Proof sketch.**

1. T(s) = x exactly when s is a pair position of x, so pairs(x) stops have T = x.
2. U(s) = x exactly when s + 1 is a pair position of x. The shift s ↦ s + 1 is a bijection of the cyclic index set, so pairs(x) stops have U = x as well.
3. T(s) = U(s) = x exactly when r[s] = r[s+1] = r[s+2] = x, so triples(x) stops have both. T = x with U = y ≠ x is impossible, because both name the middle symbol r[s+1].
4. Inclusion–exclusion gives the table.
5. The reels stop independently and uniformly, so the three states are independent, each with the distribution above. Every pattern hit is a function of the three states, and so is every payout. Hence the joint distribution of all hits depends only on L<sub>i</sub>, pairs<sub>i</sub> and triples<sub>i</sub>: the RTP, hit rate, win rate above bet, per-pattern and per-symbol figures and the whole payout distribution. ∎

**Consequence: the arrangement does not matter.** Two strips with the same length, pairs and triples give identical statistics, wherever their runs sit and in whatever order. A reel set is fully described by 3 × 11 integers, and `evaluate_counts` evaluates it exactly from the 16³ = 4,096 state combinations. The tests check that it equals `evaluate` on every field.

### Closed forms

With a<sub>i</sub> = pairs<sub>i</sub>(x) / L<sub>i</sub> and t<sub>i</sub> = triples<sub>i</sub>(x) / L<sub>i</sub>, independence gives P(A hits with x) = P(C hits with x) = a<sub>1</sub>a<sub>2</sub>, P(B) = P(D) = a<sub>2</sub>a<sub>3</sub> and P(E) = t<sub>1</sub>t<sub>2</sub>t<sub>3</sub>, so

```
RTP = Σ_x m(x) · [ 2·a2·(a1 + a3) + w·t1·t2·t3 ]        w = 5 (sum_all), 1 (full_only)
```

w is what a full screen adds on top of its four 2×2 blocks, which the first term already counts (see section 6).

**Exactness is integer bookkeeping.** 20·m(x) is an integer (5, 11, 20, 60, 100), so

```
20·N·RTP = Σ_x 20·m(x) · [ 2·P2·(P1·L3 + P3·L1) + w·T1·T2·T3 ]      (P = pairs(x), T = triples(x))
```

is an integer, and RTP = 19/20 exactly when it equals 19·N. For the final configs it is 48,579,960 = 19 × 2,556,840 (sum_all) and 55,866,954 = 19 × 2,940,366 (full_only).

**Per-symbol win probability (for S1).** Every pattern covers the middle column, whose state names at most one symbol, so a spin wins on at most one symbol and the per-symbol win probabilities add up to the hit rate. With p = a − t and b = 2a − t = P(T = x or U = x):

```
P(spin wins on x) = 2·p2·[1 − (1 − a1)(1 − a3)] + t2·[1 − (1 − b1)(1 − b3)]
```

`rtp_numerator` and `symbol_hit_numerators` compute these exactly, and `fast_stats` is their floating-point twin for the search's inner loop.

## 4. Strip construction

Code: `ReelSpec` and `build_strip` in [`search.py`](../slot_reel_designer/search.py).

Because only the counts matter, the search works on a run-level description and builds strips at the end. A `ReelSpec(runs, extra, singles)` holds, per symbol x, `runs[x]` runs of length ≥ 2 that together carry `extra[x]` symbols beyond length 2, plus `singles` singleton symbols. A run of length k ≥ 2 contributes k − 1 pairs and k − 2 triples, and a singleton contributes none, provided neighbouring runs (cyclically) show different symbols. So

```
L = Σ_x (2·runs[x] + extra[x]) + singles      pairs[x] = runs[x] + extra[x]      triples[x] = extra[x]
```

are all linear in the spec's 11 counters.

`build_strip` lays a spec out:

1. **Singletons.** Each symbol without a run gets one singleton first. Every further singleton goes to the symbol with the fewest items (runs plus singletons), the highest symbol on ties.
2. **Run lengths.** A symbol's runs share its extra symbols evenly, and long and short runs alternate.
3. **Cyclic order.** Items are ordered so that no two items of one symbol touch, even across the wrap. This is possible exactly when no symbol has more than half of the items (`is_buildable`). A greedy order (most items left first, never repeating the previous symbol) is used. It has worked on every count vector tried, but that is not proven, so its result is checked and an alternating fill (slots 0, 2, 4, … then 1, 3, …), which always succeeds under that condition, stays as a fallback.
4. **Check.** The built strip's pairs and triples are recounted and must equal the spec's, or the build fails.

For example, reel 1 of the sum_all config is `0×50 1×9 4×3 0×50 1×9 2×5 3×3 4×1` (symbol×length, wrapping back to the first run).

## 5. Search and exact finish

Code: the "search" and "exact finish" sections of [`search.py`](../slot_reel_designer/search.py). Run it with `python -m slot_reel_designer.solve`.

### Domain

Every reel has at least one run of length ≥ 3 of every symbol (`runs[x] ≥ 1` and `extra[x] ≥ 1`), at most 150 symbols, and must be buildable. A run of three of every symbol on every reel makes a full screen of every symbol possible (S2), and with it H3, H4 and H5.

### Objective

`Objective.penalty` is minimised. Its weights follow the priorities (h<sub>x</sub> = P(spin wins on x)):

| Term | Weight | Purpose |
|---|---:|---|
| \|RTP − 0.95\| | 1000 | H1 (exactness is left to the finish) |
| max(0, 0.555 − hit rate) | 1000 | H2, with a margin |
| max(0, 1.03 − h<sub>x</sub>/h<sub>x+1</sub>) for each x | 200 | S1: strictly falling win frequency |
| max(0, 1.25 − h<sub>x</sub>/h<sub>x+1</sub>) for each x | 5 | S1: a paytable-like spacing |
| ln(max<sub>x</sub> h<sub>x</sub>/h<sub>x+1</sub>) | 1 (0 in full_only) | S1: a gradual decline |
| distance of the hit rate outside [0.56, 0.69] | 50 | S3, with a margin |
| \|hit rate − 0.60\| | 1 | a hit rate near 0.60 |
| (L<sub>1</sub> + L<sub>2</sub> + L<sub>3</sub>) / 450 | 0.3 | S4: shorter reels |

S2, S4's hard cap and H3–H5 are enforced by the domain instead.

### Simulated annealing

- 10 runs, seeded `seed`, `seed + 1`, …, of 60,000 steps each, with geometric cooling from temperature 3 to 10⁻³ and the Metropolis acceptance rule.
- A move changes one reel's spec: one counter, extra symbols moved from one symbol to another, or symbols traded between singletons and one symbol's extra.
- **Repair.** With the other reels fixed, the RTP is A / L + B in one reel's length L (B = 0 for the middle reel), and changing only that reel's singleton count changes only L. So after each move, each reel's singleton count is re-solved in closed form to bring the RTP as close to 0.95 as the domain allows, and the best of the three repaired sets is the proposal. This keeps the walk near the target RTP.
- The loop uses the floating-point closed forms (`fast_stats`); only the finish works in exact integers.

### Exact finish

Annealing gets close to 0.95 but rarely exactly on 19/20. The finish starts from the 3 best annealing results and makes the RTP exact.

1. Define the *excess* E = 20·N·(RTP − 19/20) = 20·N·RTP − 19·N, an integer that is zero exactly when H1 holds (`rtp_excess`).
2. Pick one reel as the *pivot* and fix the other two. 20·N·RTP and N are linear in each reel's length, pairs and triples, and those are linear in the spec's counters, so E is affine in the pivot's counters: E = f<sub>0</sub> + c·v + γ·singles, where v holds the 5 run counts and 5 extras (`excess_coefficients`).
3. Enumerate a neighbourhood: the pivot's run counts ±2, its extras ±3 (±12 for extras of 10 or more), and the other two reels' singleton counts ±4.
4. **Meet in the middle.** Split the 10 pivot counters into two groups of 5 and enumerate each group's partial sums of c·v with numpy. E = 0 needs f<sub>0</sub> + S<sub>a</sub> + S<sub>b</sub> ≡ 0 (mod |γ|), so group B's sums are bucketed by residue and each group A row looks up the matching bucket. Every match fixes the singleton count exactly, singles = −(f<sub>0</sub> + S<sub>a</sub> + S<sub>b</sub>) / γ, and is kept if that count is ≥ 0 and the spec is in the domain.
5. Each reel takes a turn as the pivot. All exact candidates are ranked by the penalty without its RTP term, the best one is built into strips, and the strips are re-checked with `evaluate`; the search fails loudly if that check disagrees.

With seed 0 the finish found 9,286 exact candidates in sum_all (chosen penalty 2.6233) and 2 in full_only (chosen penalty 9.2532). The search is deterministic per seed: `python -m slot_reel_designer.solve` with the defaults rewrites both committed configs byte for byte, in about 26 s (sum_all) and 18 s (full_only).

## 6. The two payout modes

A full screen also completes all four 2×2 blocks, and the rules do not say whether those are paid too (README assumption 3). Both readings are supported (`PayoutMode` in [`game.py`](../slot_reel_designer/game.py)):

| Mode | A full screen of x pays | w in the RTP formula | Config |
|---|---|---:|---|
| `sum_all` (primary) | 4·m(x) + 5·m(x) = 9·m(x) | 5 | [`configs/reels.json`](../configs/reels.json) |
| `full_only` (alternative) | 5·m(x) | 1 | [`configs/reels_full_only.json`](../configs/reels_full_only.json) |

- **Same hits, different pay.** Which patterns hit does not depend on the mode, so the hit rate and the pattern hit probabilities of a reel set are the same in both. The RTP, the payout distribution and the win rate above bet can differ.
- **One reel set cannot serve both.** The sum_all config has an RTP of 3976079/6392100 ≈ 0.622030 under full_only, and the full_only config has 9595777/5880732 ≈ 1.631732 under sum_all. Each mode therefore has its own search and config.
- **Why the full_only hit rate is higher.** A spin that wins on symbol 0 pays at most 0.75 without a full screen, because all four blocks hitting forces every column to (0, 0, 0). With a full screen it pays 2.25 under sum_all but only 1.25 under full_only. Under S1, symbol 0 (the cheapest) wins most often and carries most of the RTP. Under full_only it can supply at most 1.25 × hit rate, which is 0.875 at a hit rate of 0.70, so the remainder would have to come from rarer, higher symbols. The search found no full_only set that keeps H1, H2, S1 and S2 with the hit rate inside the S3 band. Since S1 and S2 rank higher, the full_only config keeps them and accepts a hit rate of 0.853421. In it, symbol 0 wins on 84.88% of spins and supplies 0.939766 of the 0.95 RTP.

## 7. Verification

Every reported figure is exact, and each layer is checked by an independent one.

1. **Exact enumeration.** `evaluate` covers all N spins of each config with `Fraction`s, and `check_requirements` tests H1–H5 exactly. `python -m slot_reel_designer.verify` prints these figures, and `python -m slot_reel_designer.report` builds the [PAR sheet](par-sheet.md) from the same evaluator.
2. **Brute-force cross-checks.**
   - `evaluate` equals `evaluate_bruteforce` on every field, in both modes, for 100 random small reel sets. The payout distribution and the outcome counts are checked the same way.
   - On random reels of lengths 2,000, 2,500 and 3,000, the RTP equals an independent formula built from per-column probabilities.
   - The counts model equals `evaluate` on every field, in both modes, for 150 random reel sets, and `evaluate_bruteforce` on smaller ones. The state counts match the windows of 300 random strips, and the closed forms match the model.
   - For both final configs, an independent numpy enumeration of every stop combination, written straight from the nine cells and the pattern definitions, reproduces every `Evaluation` field. A slow test also runs `evaluate_bruteforce` over all 2,556,840 and 2,940,366 spins.
3. **Monte Carlo** ([`simulate.py`](../slot_reel_designer/simulate.py)). Stops are drawn uniformly and independently with numpy's default generator. Payouts are counted in whole units of 1/20 of the bet, so totals are exact. Each estimate gets a 95% confidence interval, estimate ± 1.96 standard errors. `verify` fails a config only when an estimate is more than 4 standard errors from the exact value: a 95% interval misses the true value 1 time in 20 by chance, so failing on it would fail correct configs about 10% of the time. Whether the exact value is inside the interval is still printed. With n = 10⁷ spins (seed 0, about 0.4 s per config), every exact value lies inside its interval; the z-scores are +0.16, −0.33 and +0.45 (sum_all RTP, hit rate, win rate above bet) and −0.76, −0.22 and −0.50 (full_only). The numbers are in the [README](../README.md#result).
   - The simulator's per-spin payout equals `evaluate_grid` on every stop of 60 random reel sets in both modes. Its estimates fall within 4 standard errors of the exact values on 20 small random reel sets per mode and on both configs at 200,000 spins.
4. **Tests.** 2,490 tests: 2,483 run by default in a few seconds, and 7 marked `slow` (`pytest -m slow`, a few minutes). The slow ones rerun the search for both configs, run `solve` with the defaults and compare both files byte for byte, brute-force both configs, and rerun the proof of concept's `scan(40)`. Further tests cover the strip builder (300 random specs, both item orderings on every count vector from 1 to 6, the per-symbol item layout, and rebuilding every committed reel from its run spec), the exact finish (the affine identity, a crafted case that lands on 19/20, recovery of a perturbed solution), the requirement checks at their boundaries, the command-line tools' exit codes, and that the committed PAR sheets match a fresh render.
