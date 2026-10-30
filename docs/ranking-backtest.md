# 排名選股完整回測 — 實作與驗收（2026-10-29）

把 `selection.py` 的「評分 → 排名 → 前 N」真正接進回測，並把現金股息接入每日權益，
同時解決六年回測的效能瓶頸。所有結果皆為 EXPLORATORY，非歷史全市場股票池，不宣稱有效策略。

## 實作內容

| 檔案 | 內容 |
| --- | --- |
| `src/hk_quant/backtest/ranking.py` | `run_ranking_backtest`：一次載入價格 panel + 公司行動，記憶體內評分/排名/前N/等權，T 收盤決策 → T+1 開盤成交；現金股息於除淨日入帳 |
| `src/hk_quant/backtest/dividends.py` | `dividend_cash_flows`（前一輪已建，本輪接入權益） |
| `tests/backtest/test_ranking.py` | 前N、調倉賣出、同分、缺資料、少於N、PIT、股息（有/無持倉、同日兩筆、不重複入帳） |
| `examples/run_ranking_backtest.py` | 排名回測 CLI |

## 關鍵約定

- **決策 vs 成交**：調倉日 T 只用 `trade_date <= T` 的資料評分排名；成交用下一個交易日的 raw Open（與既有回測一致），絕不用 T+1 資料決定 T 訊號。
- **股息入帳時點**：除淨日（`event_date`）開盤前，對「當日進入時持有的股數」入帳 `股數 × 每股現金`；
  除淨日當天買進不領息，當天賣出仍領息（因前一日收盤仍持有）。
- **distribution_in_kind**：不估值、不當零價值；樣本內出現時加警示，結果仍標 EXPLORATORY。
- **未核實公告日**：不作為策略當時已知資訊（沿用前一輪 `announcement_date > event_date` 警示）。

## 效能（優化前後）

| 路徑 | 耗時（3 檔） |
| --- | --- |
| 舊固定門檻回測（逐日逐股查 DuckDB/Parquet） | 約 0.47s/日；60 日 ≈ 28.5s，六年單次估約 700s |
| 新排名回測（一次載入 + 記憶體） | **六年 2020–2025 單次 ≈ 0.53s** |

優化方式：`run_ranking_backtest` 只在開頭呼叫一次 `get_daily_prices` 與 `get_corporate_actions`，
之後全程在記憶體中按日期取值；不再逐日開 DuckDB 連線。

## 六年實測（0700 / 0005 / 0941，2020-01-01..2025-12-31）

| 組合 | total_return | sharpe | max_drawdown | 成交數 | 股息事件 | 耗時 |
| --- | --- | --- | --- | --- | --- | --- |
| momentum_20 前 2，每 20 日調倉 | 0.971 | 0.620 | -0.411 | 105 | 4 | 0.53s |
| 等權買入持有（基準） | 0.610 | 0.477 | -0.448 | 3 | 6 | 0.27s |
| 超額 | +0.361 | — | — | — | — | — |

時間切分（該次 split 的 test=2025 未單獨執行，`final_test_viewed=false`；
**注意：上面的全期間 2020–2025 回測已看過 2025，因此 2025 不是從未接觸的 final test**）：

| 區間 | candidate | baseline | 超額 |
| --- | --- | --- | --- |
| train 2020–2022 | +0.094 | -0.181 | +0.275 |
| validation 2023–2024 | +0.335 | +0.429 | -0.094 |

validation 超額為負 → **示例因子不構成可信的選股優勢**，與「EXPLORATORY」標示一致。

## 驗證結論

- ✅ 排名策略**真的**驅動成交：六年 105 筆成交、74 個調倉日。
- ✅ 現金股息**真的**進入每日權益：`daily.dividend_cash` 與 `cash` 反映除淨日入帳。
- ✅ 六年回測由約 700s 降至 0.53s（一次載入 + 記憶體）。
- ✅ 該次時間切分 `final_test_viewed=false`（test=2025 未單獨跑）；但全期間 2020–2025 回測已看過 2025，不能把它標成未接觸的 final test。
- ⚠️ 仍屬 EXPLORATORY：3 檔不是歷史全市場股票池；示例因子在 validation 不具超額。

## 剩餘限制

1. `distribution_in_kind` 價值與現金股息以外的總回報仍不完整（股息已入帳，分派股份未估值）。
2. 無 listing/delisting → 非歷史全市場股票池。
3. 首個調倉日需 lookback（momentum 需 21 日）；無歷史時首日不選股（誠實跳過，不猜）。
