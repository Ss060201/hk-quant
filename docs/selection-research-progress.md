# 選股研究推進記錄 — 2026-10-29

從「只有固定門檻示例」推進到「可提出選股想法、寫規則、跑初步研究」的實際操作記錄。
本文件所有「完成」都指已實際執行並驗證，不等於策略有投資價值。

## 1. 資料保護

- Git HEAD：`345524d7d30a9309be2f889600fdd2909b7d8c63`（工作區乾淨）
- 起始 `data_version`：`HK_DATA_50d9abe94a802405178f`
- 新備份（repo 外）：`D:\hk-quant-backup-20261029-054708`（raw + processed + experiments，37 檔案）
- 既有備份未覆蓋：`…-20261015-014007`、`…-20261029-043246`

## 2. 公司行動修正（已完成）

- 網路重匯入 `ingest_corporate_actions(stock_ids=['0700'], overwrite=True)` 成功。
- stored 現為 **27 筆 = 23 dividend + 4 distribution_in_kind（0 bonus）**。
- 四筆分派別家公司股份（閱文/騰訊音樂/京東/美團）已由舊 `bonus` 改為 `distribution_in_kind`，
  `factor=None`，不增加騰訊持股數、不調騰訊股價。
- 同日 2009-05-06 兩筆現金股息 `0.25`、`0.10` 各保留一筆。
- 新 `data_version`：`HK_DATA_6d5b5ef6ed5722289827`。

## 3. 研究資料（已完成下載並通過品質門檻）

指令：

```powershell
python examples/prepare_research_data.py --stocks 0700 0005 0941 --start 2020-01-01 --end 2025-12-31 --backup-dir D:\hk-quant-research-backup-20261029
```

結果：

| 股票 | 交易日數 | 起訖 | 缺值 | 重複 | coverage | 來源 |
| --- | --- | --- | --- | --- | --- | --- |
| 0700 | 1476 | 2020-01-02..2025-12-31 | 0 | 0 | 1.0 | AKShare/Sina |
| 0005 | 1476 | 2020-01-02..2025-12-31 | 0 | 0 | 1.0 | AKShare/Sina |
| 0941 | 1476 | 2020-01-02..2025-12-31 | 0 | 0 | 1.0 | AKShare/Sina |

- 品質門檻：`READY_FOR_EXPLORATORY_VALIDATION`
- `data_version`：`HK_DATA_a40bbc861da745d0a46c`
- 這是**明確指定的 3 檔試驗樣本**，不是歷史全市場股票池（listing/delisting 仍全 null）。

## 4. 選股功能（新模組，已實作並測試）

`src/hk_quant/selection.py`：`score → rank → top-N → 等權`，嚴格 PIT。

- `momentum_scorer(window)` 為明確寫出的示例因子（不是已驗證策略）。
- `rank_by_score` 排除 `None`/NaN，同分以 stock_id 穩定排序。
- `select_top_n` 等權；少於 N 檔只選可評分的；無可評分則空。
- `build_selection_schedule` 每次只把 `trade_date <= 決策日` 的資料交給 scorer。
- 測試：同分、缺資料、停牌（無資料→排除）、少於 N 檔、PIT（改 T+1 不影響 T 選股）。

真實資料示例（`examples/run_selection.py --date 2025-06-30 --top-n 2`）：

```text
0005: 0.0265  0700: 0.0092  0941: -0.0108
Top 2 = 0005(50%), 0700(50%)
```

## 5. 回測的分紅問題

- 價格口徑：`adjust_prices` 只調整 split/bonus，**現金股息不摺入價格** → 價格回報不重複計算股息。
- 新增 `src/hk_quant/backtest/dividends.py`：`dividend_cash_flows(holdings, actions)`
  依除淨日計算現金股息，附手算測試（100 股 × (0.25+0.10+0.50)）。
- `distribution_in_kind` 不估值、不當零價值：coverage 警示 + `run_research_validation` 預設阻止，
  需 `--allow-unmodeled-actions` 才以 EXPLORATORY 價格回報執行。
- 未核實的「最新公告日期」不冒充首次公告日（`announcement_date > event_date` 仍標警示）。

## 6. 端到端驗收

- 單次真實回測（0700/0005/0941，2025-01-02..03-31，60 日）：13 筆成交、14 筆委託、
  含成本、`EXPLORATORY`，耗時 ~29s。
- 完整驗證（`run_research_validation.py`，2025-01-02..06-30，`--min-sessions 100
  --allow-unmodeled-actions`）：train/validation 切分 + `equal_weight_buy_and_hold` 基準
  + 成本穩健性 + 實驗登記，結果：

```text
experiment_id:   f3a495d0ff874e378253947cb3dbba13
data_version:    HK_DATA_a40bbc861da745d0a46c
baseline_name:   equal_weight_buy_and_hold
final_test_viewed: false
test_previously_exposed: false
split: train 2025-01-02..04-17 / validation 04-22..05-27 / test 05-28..06-30（保留）
status: EXPLORATORY
```

- **BLOCKED**：完整 2020–2025 六年驗證未跑完 —— 回測引擎逐日逐股查 DuckDB/parquet，
  約 0.47s/日，六年單次回測估約 12 分鐘、完整驗證約 35 分鐘，超出環境時限。
  這是**效能瓶頸**，不是資料不足或正確性問題。

## 測試結果

```text
pytest -m 'not integration'  : 254 passed, 13 deselected
pytest -m integration        : 12 passed, 1 skipped（dividend endpoint DNS 不穩）
```

## 尚未完成 / 待辦

1. 回測資料存取優化（把逐日查詢改為一次載入 panel，再跑六年驗證）。
2. 把 `dividend_cash_flows` 接進回測每日權益（現為獨立可測單元）。
3. 歷史全市場股票池（listing/delisting）來源。
4. 把使用者自訂選股條件接成 `Scorer` 的標準流程與文件。
