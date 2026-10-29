# slot-reel-designer

[English](README.md) | 繁體中文

為 3×3 slot game 設計 reel strip，使 **RTP 精確等於 0.95**，且 **勝率（hit frequency）不低於 55%**，並以完整窮舉與 Monte Carlo 模擬驗證結果。

> 不熟悉 slot game？請先閱讀 [Slot Game 入門](docs/slot-game-primer.zh-TW.md)。

## 問題定義

- 3×3 盤面、3 條 reel（各條長度可不同，無長度上限）
- 5 種符號，倍率為 `{0: 0.25, 1: 0.55, 2: 1, 3: 3, 4: 5}`
- 5 種中獎型態：4 個 2×2 方塊（payout = `押注 × 倍率`），以及全盤（payout = `押注 × 倍率 × 5`）
- 目標：**RTP = 0.95**，且 **勝率 ≥ 55%**

完整敘述：[`docs/problem.md`](docs/problem.md)

## 假設

1. 每條 reel 以相同機率停在任一位置，各 reel 互相獨立；盤面顯示連續 3 個符號（頭尾相接）。
2. 一次 spin 同時符合多個型態時，各型態的 payout **加總**。
3. 全盤中獎時，4 個 2×2 型態也同時成立；此情況的處理方式為：_待定（全部加總 = 9 倍／只計全盤 = 5 倍）_。
4. 「中獎」定義為 `payout > 0`；同時另外報告 `payout > 押注` 定義下的結果。
5. 每次 spin 押注 1 單位；RTP = E[payout] / 押注。

## 結果

| Reel | 長度 | Strip |
|---|---|---|
| 1 | — | `[...]` |
| 2 | — | `[...]` |
| 3 | — | `[...]` |

| 指標 | 精確值（窮舉） | 模擬值（n = 10⁷） |
|---|---|---|
| RTP | 19/20 = 0.95 | — ± — |
| 勝率（payout > 0） | — | — |
| 勝率（payout > 押注） | — | — |

各符號與各型態對 RTP 的貢獻：見 [`docs/par-sheet.md`](docs/par-sheet.md)

## 方法

1. **精確評估**：以 `fractions.Fraction` 窮舉全部 L₁·L₂·L₃ 種停止位置組合，RTP 是否相等以精確分數判斷，不受浮點誤差影響。
2. **搜尋配置**：_待定（例如結構化建構 + 局部搜尋／ILP）_。
3. **驗證**：Monte Carlo 模擬，並附信賴區間。

詳細說明：[`docs/methodology.md`](docs/methodology.md)

## 快速開始

```bash
pip install -r requirements.txt
python -m slot_reel_designer.solve      # 搜尋符合條件的配置
python -m slot_reel_designer.verify     # 精確驗證 + Monte Carlo 模擬
pytest
```

## 專案結構

```
.
├── README.md
├── README.zh-TW.md
├── docs/
│   ├── problem.md                 # 問題敘述
│   ├── slot-game-primer.md        # slot game 機制說明（英文）
│   ├── slot-game-primer.zh-TW.md  # slot game 機制說明（繁體中文）
│   ├── methodology.md             # 推導與搜尋方法
│   └── par-sheet.md               # 最終機率與 payout 拆解
├── slot_reel_designer/
│   ├── game.py                    # 盤面、中獎型態、payout 規則
│   ├── evaluator.py               # 精確計算 RTP／勝率
│   ├── search.py                  # 配置搜尋
│   └── simulate.py                # Monte Carlo 驗證
├── configs/
│   └── reels.json                 # 最終 reel strip
└── tests/
```
