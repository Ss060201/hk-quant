# HK Quant 執行指南（Phase 7–20）

這個 repo 面向單一使用者。所有策略評估先以可重跑、可檢查的離線結果為準；紙上交易需要使用者自己的外部模擬帳戶。本文件的「通過」只指已實際執行過的測試，沒有把合成結果當成真實市場成效。

## 優先處理的三件事

1. **驗證資料與可重現性。** 在可安裝依賴的環境執行下方 CI 同款測試及 synthetic end-to-end；對既有 `data/processed` 保存內容 manifest 與快照，再確認 `amount`/`turnover_rate` 欄位、歷史股票池和公告日期。成功標準：相同快照得到同一 `data_version`，同月補數不遺失舊交易日，故障重試不跳過未處理資料。詳見 [data-readiness.md](data-readiness.md)。
2. **完成固定策略的真實資料 OOS 閘門。** 先固定策略版本、股票池、成本及分割日期，登記實驗 ID；只跑開發/驗證區，保留 final test。確認 baseline、樣本數、交易明細、缺失資料及敏感性，若原始欄位缺失就停止。成功標準：可追溯每個訊號的當日輸入，獨立驗證不低於預先訂定的門檻，final test 未被反覆查看。暫不宣稱有 alpha。
3. **完成外部接入的安全驗證。** 如要啟用 Futu 模擬交易，先用自己的本機 OpenD 和港股模擬股票帳戶執行只讀 `get_account()`、`get_positions()`、`get_open_orders()`，人工核對 HK/PAPER 身分、手數、現金欄位；再以明確確認進行單筆紙上訂單及查詢/取消測試。沒有真實帳戶時維持 BLOCKED。成功標準：任何帳戶類型不明、資金欄位缺失、連線逾時均阻止重送，沒有任何真實交易入口。

## 本地驗收順序

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev,ml]'
python -m compileall -q src tests examples
PYTHONPATH=src python -m unittest discover -s tests/unit_stdlib -v
PYTHONPATH=src python -m unittest discover -s tests/risk -v
PYTHONPATH=src python -m unittest discover -s tests/ml -v
python -m pytest -q -m 'not integration' tests
python -m pytest -q tests/integration/test_end_to_end_backtest.py
python examples/run_backtest.py
python examples/run_validation.py
python examples/run_multivariable.py
```

`tests/integration/test_akshare_provider.py` 等測試會訪問外部 API；只在確認網絡和來源條款後另外執行。CI 的工作流程位於 `.github/workflows/ci.yml`。目前本地環境缺 `pytest`、`duckdb`、`pyarrow` 等且封鎖安裝代理；根據可用依賴，已執行 Python 編譯、stdlib 邊界測試及 risk/ML 孤立測試。整套 pytest 與 Parquet/DuckDB synthetic integration 仍待 CI 執行，不能據此宣稱全套通過。

## 資料與實驗

- `data/processed` 的 manifest 反映**目前**資料內容，不自動保存每個歷史版本。要重現舊實驗，同時封存原本的 processed Parquet 快照、manifest、配置與程式 commit；只保存 hash 無法重建原始資料。`DataRepository.get_data_coverage()` 列出缺口。
- `ExperimentRegistry(root)` 為每次執行建立配置 hash、產物校驗值、資料版本和警告；完成的記錄不可覆蓋。`python examples/register_experiment.py` 可示範合成登記。
- 回測以原始開盤價於下一個可用交易日執行、記錄成本與拒單。實際交易日曆目前由觀測資料推得；停牌、現金分紅、退市和缺少報價可能改變結果。`python examples/run_backtest.py --real --start YYYY-MM-DD --end YYYY-MM-DD` 只讀已攝取的本地資料。
- 驗證模組採固定策略和 split；最終測試集查看行為會留下記錄。ML 輸出只供失敗風險研究，成本後比較需要獨立回測回呼，否則標為 BLOCKED。

## 文件與研究協調

`DocumentStore('data/news')` 接受使用者**有權處理**的文字及來源、發佈/抓取時間；以晚於兩者的時間作為可用時間，修訂版保留在本地。`ResearchOrchestrator` 需要候選的 `available_at`、`rule_version`、`candidate_source`，以及具時間戳的風險和文件；預設日期截止點為該港股交易日 00:00+08:00，如需當日稍後時點，明確傳入帶時區的 `as_of_at`。研究包可以 `register_packet(...)` 存進實驗登記。例子使用合成文字，不會下載外部公告或調用 LLM。

[HKEXnews 公司公告搜尋](https://www.hkexnews.hk/homelcicontentsearch.html)可供公眾查看，但 [HKEX 網站條款](https://www.hkex.com.hk/Global/Exchange/Terms-of-Use?sc_lang=en) 限制程式化擷取與文字/資料探勘；請在擁有明確許可的來源或自有文本上使用抽取流程，不要以本 repo 擷取 HKEX 網站內容。當前沒有授權的批量新聞/公告接入，也沒有人工核對的事件標註集，因此實際新聞模型的精確率和召回率尚不可報告。

## Paper 接入操作

```bash
python -m pip install -e '.[paper]'
# 先在使用者電腦啟動 Futu OpenD，確認帳號確為港股 STOCK SIMULATE。
# 帳號 ID 從帳戶清單人工核對，切勿貼入 repo、日誌或公開 issue。
```

用 `FutuPaperBroker.connect_local(account_id=<verified paper account id>, journal_path='data/paper/orders.sqlite3')` 連到本機 OpenD。預設 `allow_paper_orders=False`，`place_paper_order(..., dry_run=True)` 只返回預覽；需要紙上送單時，使用者必須明確建立 `allow_paper_orders=True` 的實例，並對**每單**傳入 `dry_run=False, confirmed=True`。送單前重新核實模擬帳戶、HK 權限、券商靜態資料手數及股票狀態、HKD 現金/購買力與持倉。`propose_paper_order` 只能根據固定版本訊號生成待人工審核的提案，不呼叫券商。逾時時本地訂單轉 `INDETERMINATE`，需 `reconcile_order(client_order_id)` 或人工到券商 UI 查清，不能盲目重送。

券商模擬帳戶的成交明細與費用 API 可用性有限；監控模組以只讀帳戶、持倉、訂單快照及差異類別開始，不能把訂單的成交數量說成完整逐筆成交憑證。目前沒有用戶的 OpenD 或帳戶，真實讀取、委託和成交核對均未驗證。

官方核對資料：[港股模擬帳戶類型](https://openapi.futunn.com/futu-api-doc/en/trade/get-acc-list.html)、[明確傳入模擬交易環境下單](https://openapi.futunn.com/futu-api-doc/en/trade/place-order.html)、[股票手數資料](https://openapi.futunn.com/futu-api-doc/en/quote/get-static-info.html)、[歷史訂單查詢](https://openapi.futunn.com/futu-api-doc/en/trade/get-history-order-list.html)、[今日成交 API 限制](https://openapi.futunn.com/futu-api-doc/en/trade/get-order-fill-list.html)。

## 研究工具、報告與展示

`PYTHONPATH=src python -m hk_quant.agent` 在 stdin 接受單條 `{"tool":"get_data_coverage","arguments":{}}`，回傳有限、帶錯誤碼的 JSON。Pi 專案 extension 位於 `.pi/extensions/hk_quant.ts`，只暴露已核准工具；本地尚無 Pi 可執行檔，extension 能否在實際 Pi 安裝中載入仍待驗證。報告 `hk_quant.reports` 讀取已登記產物並輸出靜態、唯讀 HTML，尚不是互動式即時儀表板；不顯示未連接的 PAPER 帳戶。

## 階段閘門

| 閘門 | 開始前必備 | 尚缺／不可宣稱 |
| --- | --- | --- |
| 真實研究 | 有來源、時間、覆蓋和資料版本的港股價格及研究欄位 | 換手率、可靠歷史股票池、公司行動完整來源 |
| 真實 OOS | 固定策略版本/成本、尚未查看的 final test、可重跑資料快照 | 現有例子只用合成資料 |
| 真實文件事件 | 明確的內容使用許可、時間戳及人工標註評估集 | HKEX 批量擷取／挖掘授權未取得 |
| 真實 PAPER | 本機 OpenD、本人可用的 HK 股票模擬帳戶及人工確認 | 本地沒有外部帳戶或實單測試；不提供 live 入口 |
| 正式操作介面 | 依賴安裝、CI 綠燈、可讀的本地註冊產物 | Pi extension 與互動式 UI 尚未正式驗證 |
