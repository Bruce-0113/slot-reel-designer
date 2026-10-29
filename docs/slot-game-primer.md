# Slot Game Primer

[繁體中文版](slot-game-primer.zh-TW.md)

A short introduction to the slot-game concepts used in this project. It covers only what is needed to understand the reel design problem — not a general guide to gambling games.

---

## 1. Anatomy of a Slot Game

### Reel and reel strip

A **reel** is a cyclic sequence of symbols — picture a strip of paper wrapped around a rotating drum. In software it is simply an array that wraps around.

```
Reel strip (length 8):  [0, 0, 1, 0, 3, 0, 2, 4]
                          ↑ index 0            ↑ index 7 → wraps back to index 0
```

The **reel strip** — the exact symbol sequence of each reel — is the main design variable of a slot game.

### Stop and window

On each spin, every reel independently stops at a uniformly random index (the **stop**). The player sees a **window** of consecutive symbols starting from that stop.

```
Reel strip:  [0, 0, 1, 0, 3, 0, 2, 4]
Stop = 6  →  window shows indices 6, 7, 0  →  (2, 4, 0)
```

A 3×3 game uses three reels; each reel supplies one **column** of the window:

```
          Reel 1   Reel 2   Reel 3
Row 1  │  r1[s1]   r2[s2]   r3[s3]   │
Row 2  │  r1[s1+1] r2[s2+1] r3[s3+1] │
Row 3  │  r1[s1+2] r2[s2+2] r3[s3+2] │
```

Two structural facts follow, and they drive the whole design:

- **Columns are independent** — each reel stops independently.
- **Rows within a column are correlated** — they are *adjacent* symbols on the same strip, not independent draws.

A 3×3 screen is therefore **not** nine independent random symbols. To make two vertically adjacent cells match, the designer places identical symbols next to each other on the strip.

### Outcome space

If the reels have lengths L₁, L₂, L₃, there are exactly **N = L₁ × L₂ × L₃** equally likely outcomes. Every probability in the game is a fraction with denominator N, so all metrics can be computed **exactly** by enumeration, not only estimated by simulation.

---

## 2. Winning Rules

| Term | Meaning |
|---|---|
| **Payline / pattern** | A predefined set of cells; if all cells show the same symbol, the spin wins. |
| **Paytable** | The multiplier for each symbol. Rarer symbols usually pay more. |
| **Payout** | `bet × multiplier` (sometimes with an extra factor, e.g. ×5 for a full-screen win). |
| **Line evaluation** | When several patterns hit on one spin, most games **sum** their payouts. |

Other common mechanics (not used here): *ways-to-win* (e.g. 243 ways), wilds, scatters, free spins, multipliers.

---

## 3. Key Metrics

### RTP — Return to Player

The long-run expected payout per unit bet:

```
RTP = E[payout] / bet
```

An RTP of 0.95 means a player betting 100 units gets back 95 units on average. Typical commercial values are 0.92–0.97, and regulators often set a minimum.

### House edge

`1 − RTP`. At RTP 0.95 the operator keeps 5% of total bets in the long run.

### Hit frequency (win rate)

The probability that a spin returns **any** payout:

```
Hit frequency = P(payout > 0)
```

### Volatility

The variance (or standard deviation) of the payout per spin.

- **Low volatility**: frequent small wins.
- **High volatility**: rare but large wins.

### RTP vs. hit frequency

These are independent design dimensions:

| | Low hit frequency | High hit frequency |
|---|---|---|
| **Same RTP** | Rare, large wins | Frequent, small wins |

A game can have a high hit frequency and still a modest RTP, as long as most wins are small.

---

## 4. Losses Disguised as Wins (LDW)

A win that pays **less than the bet** is still announced as a "win":

```
Bet 1 → symbol multiplier 0.25 → payout 0.25 → net result −0.75
```

Low-multiplier symbols (< 1×) are a standard industry tool for raising hit frequency cheaply. This matters when interpreting a "win rate" requirement. It can mean either:

- `P(payout > 0)` — any payout counts as a win, **or**
- `P(payout > bet)` — only a net profit counts as a win.

---

## 5. How Designers Tune a Game

The main levers:

1. **Reel length** — longer reels give finer control over probabilities.
2. **Symbol frequency** — how many times each symbol appears on each reel.
3. **Symbol placement** — clustering identical symbols (*stacking*) makes vertical matches more likely.
4. **Per-reel asymmetry** — reels need not be identical. For example, a high-paying symbol can be made rare on the middle reel to limit how often it completes a pattern.

The result is documented in a **PAR sheet** (Probability Accounting Report): for every winning combination, it lists the probability, payout, and contribution to RTP. Regulators review it before a game ships.

Two related concepts:

- **RNG (Random Number Generator)**: picks each reel's stop; it must be certified and unpredictable.
- **Virtual reels**: physical machines map a few physical positions onto many virtual positions to shape probabilities. "Unlimited reel length" in a design problem plays the same role.

---

## 6. Mapping to This Project

| Project requirement | Slot-game concept |
|---|---|
| 3 reels, 3×3 window | Reel strips + window |
| Five winning patterns (four 2×2 blocks + full screen) | Custom paylines |
| Symbol multipliers `{0: 0.25, 1: 0.55, 2: 1, 3: 3, 4: 5}` | Paytable |
| Full-screen payout × 5 | Bonus multiplier |
| RTP = 0.95 | Primary design target |
| Win rate ≥ 55% | Hit-frequency constraint (low-multiplier symbols help — see LDW) |
| No limit on reel length | Design freedom used to reach the exact RTP |

In short, the goal is to design three reel strips — a miniature PAR sheet — so the game hits an exact RTP and a minimum hit frequency, and then to verify both by exact computation and simulation.
