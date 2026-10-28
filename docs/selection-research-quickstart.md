# 本機選股研究：先修資料，再驗證固定規則

從 repo 根目錄執行；Python 3.11+ 且已安裝 `pip install -e ".[dev,ml]"`。
示例股票僅用來試資料管線，不是推薦名單，也不是歷史港股股票池。

## 1. 重建 0700 公司行動

這個資料源曾將「分派別家公司的股份」標成騰訊自身的 bonus。
新版解析器把無法證明是本公司紅股的股份分派記為 `distribution_in_kind`，
不據此增加騰訊股數或調整其歷史價格。舊 processed 資料仍保留原分類，
須在備份 `data/raw`、`data/processed` 後重匯入。`overwrite=True` 只替換
AKShare 對該股票已保存的公司行動；若新來源筆數變少會拒絕替換。

```powershell
cd D:\hk-quant
# 先將 data/raw 和 data/processed 備份到 repo 外的新目錄。
.\.venv\Scripts\python.exe -c "from hk_quant.data.ingestion import ingest_corporate_actions; print(ingest_corporate_actions(stock_ids=['0700'], overwrite=True)['action_type'].value_counts())"
```

預期原先四筆分派別家股份的 `bonus` 改為 `distribution_in_kind`，
現金股息兩筆同日不同金額仍各保留一筆；若來源修訂了筆數或方案，人工比較 raw 與備份。
`最新公告日期` 並不證明首次公告日，不能用除淨日代填；
其他公司股票的價值及現金分紅尚未納入回測總回報。

## 2. 下載明確指定的多股票樣本

先確認 AKShare 資料來源條款和本機磁碟空間。指令先備份到新建的 repo 外資料夾，
依序攝取每隻股票，寫入帶 `data_version` 的覆蓋報告；中途失敗可從備份恢復。
只會列出已觀察到的交易日，缺日可能是停牌或資料缺口，需人工檢查。

```powershell
.\.venv\Scripts\python.exe examples/prepare_research_data.py --stocks 0700 0005 0941 --start 2020-01-01 --end 2025-12-31 --backup-dir D:\hk-quant-research-backup-001
```

輸出在 `experiments/data_checks/`，`BLOCKED` 表示至少一隻股票未滿
預設的 252 個觀察交易日、相對觀察日覆蓋率低於 80%、有空值或重複資料。
這是資料檢查門檻，不是策略績效門檻。請記錄資料來源與版本；
現在股票清單缺歷史上市及退市日期，不能稱作全市場歷史選股。

## 3. 用已固定的策略和成本做探索性驗證

目前示例規則是收盤價條件，沒有多股票排名、選前 N 名的能力；
要研究你自己的排名策略，先把規則寫清楚並實作與測試。
以下命令先驗證價格資料，然後調用既有成本後回測與同成本基準比較，
將 train/validation/test 依時間分開；**預設不查看 final test**。
實驗資訊登記於 `experiments/validation_real/`。

```powershell
.\.venv\Scripts\python.exe examples/run_research_validation.py --strategy strategies/examples/price_threshold_strategy.yaml --stocks 0700 0005 0941 --start 2020-01-01 --end 2025-12-31
```

有公司行動發生於樣本內時會停止，因為現有回測不處理現金分紅及分派股份。
要單純試價格訊號流程，可另加 `--allow-unmodeled-actions`，輸出只能標為
`EXPLORATORY`，不能當成真實總回報或證明選股有效。
要做可信的跨股票策略評估，還需要歷史股票池、充分市場資料、完整公司行動與
交易成本假設；完整產物請保存 processed 快照，不只記 hash。
