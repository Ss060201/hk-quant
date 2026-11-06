# 統一研究流程

本次基於 `48ba599` 開發。以下將「程式已實作」與「真實資料已驗收」分開。
示例設定是測試介面用的規則，不是使用者提出的策略，也不代表有投資價值。

## 入口

安裝 `python -m pip install -e '.[dev,ml]'` 後：

```sh
hk-quant workflow plan --spec configs/workflows/example_turnover.json
hk-quant workflow prepare --spec configs/workflows/example_turnover.json
hk-quant workflow status --spec configs/workflows/example_turnover.json
hk-quant workflow run --spec configs/workflows/example_turnover.json
hk-quant workflow replay --file experiments/workflows/RUN_ID/snapshot.json
hk-quant workflow capture-quotes --stocks 0700 0005 0941
```

亦可用 `python -m hk_quant workflow ...`。`run` 先準備資料，再驗收，最後回測；
`--offline` 使用已有資料。`update` 與 `prepare` 共用入口，可由系統排程呼叫；
沒有擅自在使用者電腦建立排程。更新至哪一天由設定的 `end` 決定，不下載今天未完結的日線。
`--refresh` 重新核對區間。既有數值衝突會保留舊值並回報，不能以刷新悄悄改掉。
每檔股票可獨立成功，失敗不會擦掉其他股票已儲存的資料。

Pi 擴充提供 `plan_workflow`、`prepare_workflow`、`run_workflow`，使用同一份結構化設定。
Agent 每次最多七檔，CLI 最多 3000 檔。這不是新的自然語言模型：由對話中的 Agent
根據使用者意思填設定，Python 負責驗證；不從含糊句子自行猜持有期或策略。

## 已實作與仍需要來源的界線

| 工作 | 程式 | 真實資料限制 |
| --- | --- | --- |
| 騰訊日期、數值、分頁檢查 | 已修，含回歸測試 | 長區間仍需獨立交易日曆驗收 |
| 多來源 | 東財、Sina、騰訊順序重試與備援 | 每個來源是否可達，依執行環境實測 |
| 換手率 | 東財日線接口，百分比除以100一次 | 欄位非空不等於分母定義已與 AASTOCKS 相同 |
| 財報 | 東財四種報表分頁下載、保存原始回應 | 尚無獨立核實的歷史首次公布日／修訂版本庫；不冒充 PIT |
| 估值／股本等現況欄位 | 保存東財現況快照 | 最新快照不能填成歷史資料 |
| 日曆 | 有來源的本地參考或 exchange_calendars XHKG | 後者是規則日曆，並非 HKEX 認證；特殊停市需核對 |
| 歷史股票池 | 可匯入具來源、包含退市股票的歷史清單並檢查 | 未購買或捏造歷史名單 |
| AASTOCKS 等樣本比對 | 日期、價格口徑、幣別及顯示精度比較 | 不承諾所有網頁可讀；抽樣不是完整歷史認證 |
| 公司行動 | 股息應收／派付、整股拆股、受限的實物分派；未知情況阻止 | 現有 provider 缺支付日／幣別／完整性證據，需要有來源參考資料 |
| 供股／延遲交付分派／碎股／FX | 明確 BLOCKED | 尚未建模，不當零價值，也不稱總回報完整 |
| 策略 | 原始欄位、動量、波動率、均線、RSI、量比、PIT 財務篩選／排名 | 不自動加入使用者未提出的策略 |
| 回測 | 同一開盤權益計算目標，先減持再買入，保留成本 | 整股成交；手數、稅項、深度與部分成交仍未建模 |
| 重跑 | JSON 快照與 SHA256、不可覆蓋 run 目錄、曝露區間 SQLite | 既有 2025 已看過，任何這裡的結果不宣稱 untouched final test |

## 必需資料的閘門

價格策略不要求財報或換手率；換手率策略不能拿成交額替代。
缺欄位、缺交易日或有未解決來源衝突時輸出 `BLOCKED`（exit 2）。
`READY_FOR_PREFLIGHT` 只表示下載階段通過，**不是回測就緒**；`status` 再驗收公司行動、
財報公布日期、股票池和 warmup。所有研究結果均為 `EXPLORATORY`。

`action_policy=strict` 要求事件核實、股息 HKD 與派付日；除淨日只增加應收股息，
派付日才增加可用現金。`price_only` 明確不計股息，但仍不能忽略拆股、供股等持股變動。
底層排名引擎另保留 `legacy_exploratory` 供舊結果遷移，不在統一入口暴露。

## 有來源參考資料匯入

```sh
hk-quant workflow import-reference --kind calendar --file local-calendar.json
hk-quant workflow import-reference --kind facts --file local-facts.json
hk-quant workflow import-reference --kind actions --file local-actions.json
hk-quant workflow import-reference --kind action_coverage --file local-action-coverage.json
hk-quant workflow import-reference --kind universe --file local-universe.json
hk-quant workflow compare --file local-aastocks-samples.json
```

參考資料頂層均要求真實 `source_url` 與 `verified: true`。`verified` 是匯入者對其來源
證據的聲明，程式不能代替來源核實。不能為了繞過閘門而將未知資料改成 true。
以下為欄位說明，並非真實市場資料：

- calendar：`start/end/sessions`，日期清單需涵蓋宣告區間內所有交易日。
- facts.rows：`stock_id/metric/value/period_end/available_date/currency/unit/source_url`。
  日期精度公布資料保守延至下一日可用；同期間修訂保留不同可用日期。
  跨公司比較相同 metric 時幣種及單位須一致；不拿今天股本推算過去換手率。
- actions.rows：`stock_id/event_date/action_type`；dividend 另需 `cash_amount/currency/payment_date`；
  split/bonus 另需已核實 share multiplier `factor`；distribution_in_kind 另需
  `recipient_stock_id/recipient_ratio/delivery_date`。目前只支援事件日即交付且整股的實物分派，
  必須另外有受派股票原始價格。不得把其他公司股票當原公司送股。
- action_coverage.rows：每檔 `stock_id/start/end/source_url/verified`，表示對該區間公司行動的核對範圍。
- universe：`includes_delisted: true`；rows 含 `stock_id/listing_date/delisting_date`。
- quotes.rows：`stock_id/trade_date/currency/adjustment`，以及要比對的 `open/high/low/close/volume/turnover/turnover_rate`。
  必須標 `adjustment=raw_unadjusted`、`volume_unit=shares`、`turnover_rate_unit=percent`；
  `session_status=final` 才把 close 當正式收盤。`turnover` 指成交額。
  `22.27M` 按顯示精度區間比較，不當成精確的 22,270,000 股。

參考資料歷史保留於 `data/reference/history`。原始回應、失敗紀錄、行情與快照都不進 Git。
`capture-quotes` 只讀公開頁面的當前報價，保留原頁與時間；找不到頁面、代碼或單位時拒絕。
不繞過登入／訪問限制、不抓全歷史。頁面未提供正式收市證據時，累計成交量等日終欄位
標為 `UNCONFIRMED_SESSION`，不把延遲報價硬當收盤。`compare` 不會改行情檔。
資料根目錄有單寫入鎖；中斷後殘留鎖要先確認沒有更新程序，才可移除。

## 測試

```sh
python -m unittest tests.workflow.test_workflow -v
python -m pytest -q -m 'not integration'
```

新增離線案例覆蓋來源切換、資料衝突、不覆蓋成交額、單位轉換、缺日、PIT、
股息付款、拆股、供股阻止、真正等權減持、快照重播及篡改拒絕。
外部來源驗證與使用者 Windows 本機資料覆蓋需另列結果，不用合成測試替代。
