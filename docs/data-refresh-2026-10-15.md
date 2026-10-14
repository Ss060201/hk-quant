# Data Refresh 記錄 — 2026-10-15

本文件記錄一次針對 `data/raw` 與 `data/processed` 的資料重跑與核對。
原始（raw）與處理後（processed）資料仍由 `.gitignore` 忽略，不進入版控。

## 執行資訊

| 項目 | 值 |
| --- | --- |
| 執行日期 | 2026-10-15（+08:00，約 01:40） |
| Git HEAD | `4e88a43f2fa9c6a955b4dcb6a61fba69152c1ec4` |
| 備份位置 | `D:\hk-quant-backup-20261015-014007\`（raw + processed，7 個檔案） |

## 資料來源與查詢範圍

| 資料集 | 來源 | 查詢範圍 | 結果 |
| --- | --- | --- | --- |
| daily_prices | AKShare `stock_hk_daily`（Sina 後端） | `0700`，2025-01-02 → 2025-01-28 | 19 個交易日 |
| corporate_actions | AKShare `stock_hk_dividend_payout_em`（East Money `datacenter`） | `0700` | 27 筆 |
| stock_master | 既有 `stock_hk_spot`（未重跑） | — | 2807 檔（listing/delisting 仍 null） |

## data_version 對照

| 時點 | data_version |
| --- | --- |
| 重跑前 | `HK_DATA_2f4f0e5ad90484a24180` |
| 日線重跑後（公司行動尚未匯入） | `HK_DATA_24705a839b82d773361d` |
| 公司行動匯入後（最終） | `HK_DATA_50d9abe94a802405178f` |

## 欄位對照（日線）

| 資料 | 舊欄位 | 新欄位 | 內容 |
| --- | --- | --- | --- |
| raw | `amount` | `amount` | 成交額（Sina 原生即 `amount`） |
| processed | `turnover`（Phase 2 命名） | `amount` | 成交額，只是正名 |
| processed | — | `turnover_rate` | 換手率，目前 provider 不提供 → 全空 |

重跑後 processed 欄位：
`stock_id, trade_date, open, high, low, close, volume, amount, turnover_rate, source, ingested_at`

## 價格比對結果（vs 備份）

| 欄位 | 是否一致 |
| --- | --- |
| open | identical |
| high | identical |
| low | identical |
| close | identical |
| volume | identical |
| 舊 `turnover` vs 新 `amount` | 完全相等 |

**結論**：19 個交易日無遺失、無重複（unique=19, duplicated=0）；`amount_nonnull` 由 0 → 19；`turnover_rate` 維持空值（符合預期，未以成交額填入）。

## 公司行動核對（27 筆）

| 檢查項 | 結果 |
| --- | --- |
| 股票代號 | raw `00700` → canonical `0700`（單一股票） |
| event_date 範圍 | 2005-04-19 → 2026-05-15（27 筆全非空） |
| action_type | dividend 23、bonus 4 |
| 完全重複列 | 0 |
| 重複 key `(stock_id, event_date, action_type, announcement_date)` | 1 組（2 筆） |

重複 key 詳情：`2009-05-06` 同日有兩筆 dividend，`cash_amount` 分別為 `0.25` 與 `0.10`，
屬於**同一天兩筆不同的現金分派**（首次匯入未套用去重，兩筆都被保留，為正確行為；
該去重 key 對「同日多筆分派」過粗，僅在與既有資料合併時才使用）。

### 欄位對照（公司行動，adapter）

```text
raw.最新公告日期  ->  announcement_date
raw.除净日        ->  event_date
raw.分红方案      ->  scheme（解析出 action_type / cash_amount / factor）
```

對齊排序後逐筆比對：`announcement_date == raw.最新公告日期` 與
`event_date == raw.除净日` 均為 **True**（27/27），映射正確。

### 公告時間的警示（含 bonus 逐筆核對）

- 覆蓋報告的 `announcement_date_nonnull` 只計算**非空筆數**，不能據此判定
  公告時間準確或公司行動完整（見 `src/hk_quant/data/coverage.py` 的 `_available`）。
- 抽查發現來源資料的 `最新公告日期` 對**較舊紀錄**可能不是原始公告日：
  例如 event_date `2005-04-19` 對應 announcement_date `2007-06-07`（公告晚於除淨日）。
- **4 筆 bonus 逐筆核對**（`action_type=bonus`）：

| # | event_date | announcement_date | 公告晚於除淨日 | scheme |
| --- | --- | --- | --- | --- |
| 0 | 2017-10-18 | 2017-10-16 | 否 | 每1256股分派1股 China Literature 預留股份 |
| 1 | 2018-12-28 | 2018-12-13 | 否 | 每3900股分派1股 Tencent Music 美預託 |
| 2 | **2022-01-20** | **2022-03-25** | **是** | 每21股分派1股京東 A 類普通股 |
| 3 | 2023-01-05 | 2022-11-16 | 否 | 每10股分派1股美團 B 類普通股 |

- **bonus #2（京東分派）的 `announcement_date`（2022-03-25）晚於 `event_date`
  （2022-01-20）**，來源「最新公告日期」不是首次公告日；因此該來源日期
  **不可視為已核實的 PIT 日期**。**不以除淨日回填首次公告日。**
- 已於 `src/hk_quant/data/coverage.py` 加入警示：只要存在
  `announcement_date > event_date`，覆蓋報告就會標示
  「those announcement dates are not verified point-in-time dates」。

### 同日多筆分派的去重修正

- 兩筆 2009-05-06 的 dividend，`announcement_date` 皆為 `2009-05-14`（相同），
  `cash_amount` 分別為 `0.25` 與 `0.10` —— 是同一天兩筆不同的現金分派。
- 原去重 key `(stock_id, event_date, action_type, announcement_date)` 過粗，
  重跑合併時會誤刪其中一筆。
- 已修正 `ingest_corporate_actions` 的去重 key，加入 `cash_amount`、`factor`；
  並新增回歸測試 `test_ingest_corporate_actions_preserves_same_day_distributions`
  （兩次匯入後仍保留兩筆）。

## 測試結果（2026-10-15）

```text
pytest -m 'not integration'   : 232 passed, 13 deselected
pytest -m integration         : 13 passed, 232 deselected (58.95s)
```

本次 integration 涵蓋資料匯入（`test_akshare_provider`、`test_turnover_research`、
`test_strategy_to_signal`）、公司行動（`test_historical_data_integrity` 的
`test_real_akshare_corporate_actions`）與 PIT/universe/calendar 情境。
**無外部端點失敗**；先前 `datacenter.eastmoney.com` 的 DNS 問題本次已消失，
股息端點成功取得資料。

## 結論與殘留事項

1. 日線欄位已由 `turnover` 正名為 `amount`，並新增空的 `turnover_rate`。
2. 價格數值未變動，僅 schema 更新。
3. 公司行動 27 筆已匯入且映射正確；但公告日期僅為 provider 提供值，未驗證其
   歷史準確性與完整性；其中 bonus #2 的公告日已證實晚於除淨日，不可當 PIT 日。
4. 同日多筆分派的去重 key 已加入 `cash_amount`、`factor`，並附回歸測試。
5. `data/raw`、`data/processed` 仍留在 `.gitignore`（`data/raw/*`、`data/processed/*`，
   僅保留 `.gitkeep`）。
