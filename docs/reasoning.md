# Reasoning: From the Rules to an Answer

[繁體中文版](reasoning.zh-TW.md)

This page is the chain of thought behind the project, in the order it was worked out. Each step says what was noticed, why it matters and what it led to. The [methodology](methodology.md) and the code hold the details; this page holds the argument.

## 1. What Is Actually Random

- On each spin every reel stops at a uniformly random index, and the window shows 3 consecutive symbols of each reel. The 9 cells are therefore **not** 9 independent draws: the three cells of a column are three neighbouring positions on one strip.
- With reel lengths L₁, L₂, L₃ there are exactly N = L₁ · L₂ · L₃ equally likely outcomes, so every probability is a fraction with denominator N.

**Consequence:** RTP can be computed exactly by enumeration, and "RTP = 0.95" can be checked as the fraction equality RTP = 19/20, with no rounding and no "close enough". Simulation is only a cross-check.

## 2. What the Rules Leave Open

Before computing anything, the readings that had to be chosen were written down (README, [Assumptions](../README.md#assumptions)):

- Stops are uniform and independent, and the window wraps around the strip.
- When several patterns hit on one spin, their payouts are **summed**, because the rules price each pattern separately.
- A full screen also completes all four 2×2 blocks. Summing them (9 × multiplier) follows from the previous point, so that is the primary reading (`sum_all`). Paying the full screen alone (5 × multiplier) is also plausible, so a second configuration is delivered for that reading (`full_only`) instead of betting on one.
- "Win" means payout > 0; payout > bet is reported as well.

## 3. Two Observations That Shrink the Problem

**(a) Every pattern contains the centre cell.** A, B, C, D and E all include row 2, column 2. So all patterns that hit on one spin show the same symbol, the centre one. Wins on different symbols never mix, and per-symbol statistics simply add up.

**(b) A 2×2 block is two vertical pairs side by side.** Block A hits with symbol x exactly when column 1 shows x in rows 1–2 *and* column 2 shows x in rows 1–2. So a column matters only through two facts: which symbol, if any, forms its top pair, and which forms its bottom pair. A column showing x, x, x has both.

On a reel, "the window's top pair is x" happens at exactly as many stops as the strip has adjacent x, x positions (counting cyclically), and "x, x, x" at as many stops as it has adjacent triples. Therefore:

> Every statistic of the game (RTP, win rate, each pattern's probability) depends only on each reel's length and, per symbol, its number of adjacent **pairs** and **triples**. How the strip is arranged beyond that does not matter.

Writing aᵢ(x) = pairs / Lᵢ and tᵢ(x) = triples / Lᵢ for reel i, and m(x) for the multiplier, the `sum_all` RTP is

```
RTP = Σₓ m(x) · 2 · a₂(x) · (a₁(x) + a₃(x))   +   5 · Σₓ m(x) · t₁(x) · t₂(x) · t₃(x)
      blocks A + C use reels 1–2,                  full screen
      blocks B + D use reels 2–3
```

The middle reel appears in every term: it takes part in all five patterns.

## 4. The Simplest Answer

The cheapest way to win often is the lowest symbol, 0 (multiplier 0.25). The simplest family built on it:

- the middle reel holds only 0s, so it always shows a top and a bottom pair of 0;
- each outer reel holds one run of k zeros followed by a few other symbols that never repeat.

A run of k zeros gives k − 1 pairs and k − 2 triples, so the formula above becomes

```
RTP = (k₁ − 1) / (2L₁) + (k₃ − 1) / (2L₃) + (5/4) · (k₁ − 2)(k₃ − 2) / (L₁L₃)
```

Scanning small integers, the smallest solution is L₁ = 5, k₁ = 4, L₃ = 10, k₃ = 8:

| Reel | Strip |
|---|---|
| 1 | `[0, 0, 0, 0, 1]` |
| 2 | `[0, 0, 0]` |
| 3 | `[0, 0, 0, 0, 0, 0, 0, 0, 1, 2]` |

It can be checked by hand over its 5 × 3 × 10 = 150 outcomes:

- Reel 1 shows a top pair of 0 at 3 of its 5 stops, a bottom pair at 3, and three 0s at 2.
- Reel 3 shows a top pair of 0 at 7 of its 10 stops, a bottom pair at 7, and three 0s at 6.
- Reel 2 always shows three 0s.

So P(A) = P(C) = 3/5, P(B) = P(D) = 7/10, P(E) = 2/5 × 6/10 = 6/25, and

```
RTP = 0.25 × (3/5 + 7/10 + 3/5 + 7/10) + 1.25 × 6/25 = 0.65 + 0.30 = 0.95
```

A spin loses only when neither outer reel shows a pair of 0, which happens with probability 1/5 × 2/10 = 1/25, so the win rate is 24/25 = 96%.

This already answers the question exactly. It is the [proof of concept](poc.md) that was built and verified first ([`configs/poc_reels.json`](../configs/poc_reels.json)).

## 5. Make Sure It Is Right

Before improving anything, the answer has to be trustworthy, and a closed form derived by hand is easy to get wrong. So it was checked three ways:

- an exact evaluator that enumerates every stop combination with fractions;
- a naive brute force that loops over every stop, compared with the exact evaluator on hundreds of random reel sets;
- Monte Carlo simulation, as an independent sanity check of the exact numbers.

## 6. Criticise the Answer

The minimal answer is correct, but it is not a game. 96% of spins win, every win is on symbol 0, symbols 1–4 never pay, and the middle reel is a single symbol. Those complaints were turned into explicit requirements ([methodology, section 1](methodology.md#1-notation-and-requirements)):

- **Hard:** RTP exactly 19/20, win rate ≥ 55%, every symbol pays some RTP, every pattern can hit, every reel contains all five symbols.
- **Preferences, in priority order:** the higher the multiplier, the rarer the win (S1); a full screen of every symbol is possible (S2); win rate in [0.55, 0.70] (S3); at most 150 symbols per reel (S4).

## 7. Think Before Searching: What the Requirements Force

- The average payout of a winning spin is RTP / win rate. With a win rate between 0.55 and 0.70, a winning spin must pay between 1.36 and 1.73 on average.
- Symbol 0 must be the most frequent winner (S1). Without a full screen, one spin completes at most three 2×2 blocks (checked by brute force over all grids), so a symbol-0 win without a full screen pays at most 0.75. A full screen of 0 pays 9 × 0.25 = 2.25 under `sum_all`.
- So unless symbols 1–4 win often, which S1 rules out, full screens of 0 must be common. That needs long stacks of 0 on all three reels.

**Prediction:** the final reels will be dominated by long runs of 0, and full screens will not be rare. The search confirmed both. In the final `sum_all` configuration a full screen appears on 32.5% of spins (about half of the winning spins, 43% of the RTP), and symbol 0 supplies 91% of the RTP.

Under `full_only` a symbol-0 win pays at most 1.25. With a win rate of at most 0.70, symbol 0 could then supply at most 0.875 of the 0.95, and symbols 1–4 would have to supply the rest while still winning less often than 0. The search found no such design with reels of at most 150 symbols, so the `full_only` configuration keeps S1 and gives up S3 (win rate 85.3%).

## 8. Search Over Integers, Not Strips

Because only the pair and triple counts matter (step 3), a design is a handful of integers per reel, not a strip of 150 symbols.

1. Simulated annealing over those counts gets close to 0.95 while following the requirements' priorities.
2. Exactness is then integer bookkeeping: 20 · N · RTP is always an integer. With two reels fixed, it is affine in the third reel's counts, so the counts that make it exactly 19 · N can be solved for directly.
3. The counts are laid out as a strip in which runs of the same symbol never touch, and the strip is re-checked with the exact evaluator.

## 9. Result

| | `sum_all` (primary) | `full_only` (alternative) |
|---|---|---|
| Config | [`configs/reels.json`](../configs/reels.json) | [`configs/reels_full_only.json`](../configs/reels_full_only.json) |
| Reel lengths | 130, 132, 149 | 143, 138, 149 |
| RTP | 19/20 exactly (48,579,960 = 19 × 2,556,840) | 19/20 exactly (55,866,954 = 19 × 2,940,366) |
| Win rate | 66.0% | 85.3% |
| Requirements | all hard ones; all preferences | all hard ones; S3 missed (step 7) |

## 10. Limits and Next Steps

- The search is a heuristic. It finds valid designs, not provably optimal ones, and the `full_only` result depends on the seed.
- Realism is limited by the rules themselves (step 7). With these patterns and multipliers, a 55–70% win rate at RTP 0.95 forces frequent full screens of the cheapest symbol.
- With more time: map the trade-off between win rate and full-screen frequency when longer reels are allowed, and try to make the stricter win rate (payout > bet) reach 55% as well.
