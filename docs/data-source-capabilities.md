# 資料來源能力與未完成事項

來源研究：

- Vibe-Trading 的 HK 資料路由： https://github.com/HKUDS/Vibe-Trading/blob/main/agent/src/skills/data-routing/SKILL.md
- Vibe-Trading 港股財報 report identifiers： https://github.com/HKUDS/Vibe-Trading/blob/main/agent/src/tools/financial_statements_tool.py
- AKShare 港股歷史接口： https://akshare.akfamily.xyz/data/stock/stock_quote.html
- HKEX 公開日曆： https://www.hkex.com.hk/News/HKEX-Calendar

本輪新東財 client 為自行實作，借鑑上述來源的端點／report identifiers，沒有整套複製 Vibe。
既有 Tencent adapter 的版權說明保留。開源程式授權不代表第三方市場資料授權。

| 資料 | 接法 | 限制 |
| --- | --- | --- |
| OHLCV | 東財 raw kline，Sina raw，Tencent raw | 不混用復權價；三來源共用上游亦可能有相同錯誤 |
| 成交額 | 東財、Sina | Tencent 不提供；缺值不可冒充成交量 |
| 換手率 | 東財 kline f61，百分比轉 ratio | 分母定義仍需獨立確認 |
| 財報 | RPT_HKF10_FN_INCOME/BALANCE/CASHFLOW/GMAININDICATOR | 全量 raw 保存；不是已核實的歷史 PIT 資料庫 |
| 估值 | AKShare stock_hk_spot_em 現況快照 | 實際回傳哪些欄位就保存哪些，不能補造歷史 PE/PB/股本 |
| 股息及分派 | 既有 stock_hk_dividend_payout_em + 有來源參考 | 非完整拆股／供股資料；最新公告日期不當首次公告日 |
| 指標 | 本機由已檢查價格計算 | 拆股只用截至訊號日已生效且核實的事件 |
| 日曆 | 參考清單或 exchange_calendars XHKG | 需對特殊停市抽查 |
| 歷史全市場 | 有來源名單匯入 | 未取得完整上市／退市庫，仍是資料缺口 |
| 沽空、南向、持股、新聞 | 尚未接入此統一入口 | 規格遇到未支援欄位明確拒絕；不拿 A 股功能冒充港股 |

1299 的舊 Sina low 與 close 內部矛盾；Tencent 的 low=77.45 是待獨立核實的替代觀測。
僅有另一來源數字合法，不足以證明它就是官方正確值。新流程遇到來源衝突不會自動覆蓋舊檔。
