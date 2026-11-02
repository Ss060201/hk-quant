# 第二資料來源：Tencent Finance（備用／核對）

研究 Vibe-Trading（HKUDS/Vibe-Trading，MIT License）的港股來源後，實作一個獨立、可選用的
Tencent 港股日線 adapter，解決 Sina 更新延遲，並核對 1299 的異常日。

## 來源資訊

- 端點：`https://web.ifzq.gtimg.cn/appstock/app/kline/kline`（原始價，`day`）
  - 前復權價在 `.../fqkline/get`（`qfqday`），**本專案只使用原始 `kline`，絕不用 fqkline**。
- 免費、無需 API key、據 Vibe-Trading 稱「從未被 IP 封鎖」。
- 欄位順序：`[date, open, close, high, low, volume]`（注意 close 在 high 之前）。
- 成交量單位：**股數**（HK endpoint）；不提供成交額（amount）。
- 單次回應上限 **500 根**，且只回「窗口最後 500 根」；多期需**向後分頁**。
- 部分 bar 帶第 7 個元素（分紅資訊 dict，含 `FHcontent`／`paixiri` 除息日），adapter 目前忽略。
- 授權：端點格式與 raw/前復權口徑借鑒 Vibe-Trading（MIT），已在
  `src/hk_quant/data/adapters/tencent.py` 頂部保留版權聲明。

## 實測結果（唯讀，未動 hk-quant raw/processed）

| 項目 | Tencent 原始價 | AASTOCKS | hk-quant(Sina) | 結論 |
|---|---|---|---|---|
| 0700 2026-11-02 收盤 | 392.200 | 392.200 | （Sina 無 11-02） | ✅ Tencent 有 11-02，與 AASTOCKS 一致 |
| 0700 2026-11-02 開/高/低/量 | 387.6 / 397.6 / 384.6 / 22,621,767 | 387.6 / 397.6 / 384.6 / 22.62M | — | ✅ 全一致 |
| 0700 2026-10-30 | 376.4 / 383.6 / 387.6 / 375.2 / 22,269,954 | 同左 | 同左 | ✅ 三方一致 |
| 1299 2026-09-04 low | **77.450** | — | **78.05（錯）** | ✅ Sina 的 low 是來源錯誤；正確為 77.45 |

- **1299 異常判定**：Sina 在 2026-09-04 把 `low` 誤給成 78.05（> 收盤 77.5），
  Tencent 顯示正確 `low=77.450`（≤ 收盤 77.5），故該「OHLC 異常」是 **Sina 來源資料錯誤**，非市場異常。
- **11-02 可靠日線**：✅ Tencent 提供 0700/0005 等 2026-11-02 日線，與 AASTOCKS 一致。
- **長區間**：單次請求只回最近 500 根（實測 0700 2020–2026 單次 = 500 根、起 2024-10-22）；
  adapter 採向後分頁，且**起訖日期達不到會明確報錯，不靜默截斷**。

## 使用（獨立、可選用，不覆蓋 Sina）

```python
from hk_quant.data.adapters.tencent import TencentHKProvider
provider = TencentHKProvider()
df = provider.get_daily_prices(["0700"], "2026-11-02", "2026-11-02")
# amount（成交額）與 turnover_rate 為空；volume 為股數。
```

- `amount` 為空（Tencent 無成交額），**不拿 volume 冒充 amount**。
- 拒絕錯誤 OHLC、未知價格口徑、不完整歷史。
- 未接入既有 `ingest_daily_prices`（其需要 amount 非空）；作為獨立核對／備用 provider。

## 測試

- `tests/data/test_tencent_adapter.py`（5 個單元測試：欄位對應、amount 為空、拒壞 OHLC、
  拒不完整歷史、raw 不復權、向後分頁）。
- `tests/integration/test_tencent_provider.py`（2 個實測：0700 11-02 對 AASTOCKS、
  1299 09-04 low 修正）。

## 仍缺

- Tencent 不提供成交額（amount），成交額仍需 Sina／East Money／HKEX。
- 歷史全港股日線、上市/退市、換手率仍缺。
