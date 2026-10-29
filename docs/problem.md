# Problem Statement

[繁體中文版](problem.zh-TW.md)

Design a set of reel strips for a 3×3 slot game that meets a target return and a minimum win frequency.

## Game Setup

- **Window**: 3 columns × 3 rows. Each column is supplied by its own reel.
- **Reels**: 3 reels. They may have different lengths, and there is no upper limit on length. Each reel can be pictured as a large rotating drum.
- **Symbols**: 5 symbols, each with a payout multiplier:

| Symbol | Multiplier |
|---|---|
| 0 | 0.25 |
| 1 | 0.55 |
| 2 | 1 |
| 3 | 3 |
| 4 | 5 |

## Winning Patterns

A pattern wins when every marked cell (■) shows the same symbol.

**Pattern A — top-left 2×2**

```
■ ■ ·
■ ■ ·
· · ·
```

**Pattern B — top-right 2×2**

```
· ■ ■
· ■ ■
· · ·
```

**Pattern C — bottom-left 2×2**

```
· · ·
■ ■ ·
■ ■ ·
```

**Pattern D — bottom-right 2×2**

```
· · ·
· ■ ■
· ■ ■
```

**Pattern E — full screen**

```
■ ■ ■
■ ■ ■
■ ■ ■
```

## Payout Rules

| Pattern | Payout |
|---|---|
| A, B, C, D | bet × symbol multiplier |
| E | bet × symbol multiplier × 5 |

## Design Targets

1. **RTP = 0.95** — for every 100 units bet, the expected return to the player is 95 units.
2. **Win rate ≥ 55%** — at least 55% of spins must result in a win.

## Deliverable

Any reel configuration that satisfies both targets, together with evidence that it does.

Points the rules leave open (how overlapping patterns are paid, how "win" is defined) are resolved in the [Assumptions](../README.md#assumptions) section of the README.
