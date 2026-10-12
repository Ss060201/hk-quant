# HK Quantitative Research Platform

一個 **AI-native 香港股票量化研究平台**。

## 1. 項目是什麼

本專案旨在建立一個以自然語言研究問題為起點的香港股票量化研究平台，
讓研究流程可以從「問問題」一路走到「研究報告」。

## 2. 長期目標

```
Natural Language Research Question
→ Research Engine
→ 發現市場規律
→ Strategy
→ Backtest / OOS
→ Risk / ML / News Research
→ Paper Trading
→ Research Report
```

## 3. 目前完成什麼

### Phase 1: Project Foundation

- Python package 結構（src layout）
- `pyproject.toml` 專案設定
- YAML configuration 結構與簡單 config loader
- 基本 logging system
- pytest test framework
- 基本 CLI / entry point

### Phase 2: Data Engine

- Data Provider Adapter（以 AKShare 為第一個 provider，通過 Adapter 隔離）
- Canonical Data Schema（Daily Price / Stock Master）
- Raw Data Storage（Parquet，保留原始 provider response）
- Processed Data Storage（Canonical Parquet，按 stock_id/year/month 分區）
- Data Ingestion Pipeline（下載 → raw → canonical → 驗證 → 保存，含增量跳過）
- Data Repository（DuckDB 查詢接口）
- 基本 Data Quality Checks

### Phase 3: Data Correctness / Historical Data Integrity

- Point-in-Time / As-of Data Layer（依 `announcement_date` 決定可見性）
- Historical Universe Layer（依 listing/delisting date 重建，含明確的 data-unavailable 處理）
- Trading Calendar Layer（由 observed market dates 推導）
- Corporate Actions Layer（canonical schema + 驗證）
- Raw / Adjusted Price 分離（自家 split/bonus 調整，不套用 provider adjusted close）
- Data Provenance / Data Version
- Historical Data Quality Validation

### Phase 4: Research Engine

- Generic Research Engine（variable × thresholds × forward periods，非寫死單一變量）
- Event Detection（`daily` / `first_crossing` 兩種模式，嚴格只用事件日已知資料）
- Forward Return Engine（用交易日曆計算 1D..180D，非 `timedelta`）
- Research Statistics（sample count / mean / median / std / win rate / quantiles / bootstrap CI）
- Relationship Analysis（Spearman rank correlation + increasing/decreasing/non-monotonic 分類）
- Visualization（heatmap、threshold-return、holding-period-return、sample size）
- Research Result Artifact（summary.json + events/forward_returns parquet + plots，可重現）

**Schema 修正**：Phase 2 的 `turnover` 實際是成交額（amount），已更名為
`amount`，並新增 nullable `turnover_rate`（換手率，目前 provider 不提供，
絕不用 amount 冒充）。

### Phase 5: Strategy Builder

- Strategy Definition（結構化、可版本化、可追溯的規則定義）
- Entry / Exit Condition（`>` `>=` `<` `<=` `==` `!=` + ALL/ANY + 有限 nesting）
- Data field vs Derived factor 分離（factor registry 尚未建立時明確報錯）
- Holding Period（交易日，非自然日）
- Strategy Validator（schema / field / numeric / universe / version）
- Research → Strategy 來源追溯（research_id + source_status）
- Immutable Versioning（v1.0.0 不可覆蓋，改動需 v1.1.0）
- Deterministic Strategy Hash
- Strategy Storage（`strategies/<id>/v<version>.yaml`，save/load round-trip）

### Phase 6: Factor Registry + Signal Engine

- Factor Registry（factor_id → FactorDefinition + calculator，版本化）
- 第一個真正可用 factor：`momentum_20`、`volatility_20`（嚴格 PIT）
- Factor Engine（用 DataRepository 取數、Parquet cache、版本記錄）
- Condition Evaluation（三值邏輯：True / False / unavailable）
- Signal Engine（BUY / SELL / HOLD，結構化 reason，deterministic）
- Position State（記錄 entry_date，支援 holding-period exit）
- Missing data / out-of-universe 明確處理（不默認 False）
- Batch signal 保存（parquet + metadata.json，可重現）

**Phase 1–6 當時尚未實作**：Portfolio Construction、Position Sizing、Backtest、
Risk Model、Transaction Cost、ML、News/Filing、Paper Trading、
Broker API、Dashboard、Signal Ranking；以及完整的 PIT fundamentals
provider、官方港股交易日曆、split/rights 的 provider 資料、
turnover rate 的 provider 資料。

上段記錄最初 Phase 1–6 的基線；Phase 7–20 的最新狀態見本文件末尾的狀態表。

## 4. 如何安裝

要求 Python 3.11+。

```bash
# 建立並啟動虛擬環境（可選）
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

# 安裝專案（含開發依賴 pytest；ML 需要額外依賴）
pip install -e ".[dev,ml]"
```

## 5. 如何執行

```bash
# 使用 entry point
hk-quant

# 或使用 module 方式
python -m hk_quant
```

預期輸出：

```text
HK Quant Research Platform
Status: OK
```

## 6. 如何跑 tests

```bash
# 一般 unit tests（不訪問外部 API）
python -m pytest

# 不依賴 DuckDB / PyArrow 的邊界測試
PYTHONPATH=src python -m unittest discover -s tests/unit_stdlib -v

# 真正訪問 AKShare 的 integration tests
pytest -m integration
```

## 7. 當前 repository structure

```text
hk-quant/
├── README.md
├── pyproject.toml
├── .gitignore
│
├── configs/
│   ├── data.yaml
│   ├── research.yaml
│   ├── backtest.yaml
│   ├── risk.yaml
│   ├── paper.yaml
│   └── research/
│       └── turnover_forward_return.yaml
│
├── src/
│   └── hk_quant/
│       ├── __init__.py
│       ├── __main__.py
│       ├── cli.py
│       ├── config.py
│       ├── logging_config.py
│       ├── data/
│       │   ├── __init__.py
│       │   ├── models.py
│       │   ├── interfaces.py
│       │   ├── normalization.py
│       │   ├── ingestion.py
│       │   ├── repository.py
│       │   ├── storage.py
│       │   ├── quality.py
│       │   ├── point_in_time.py
│       │   ├── universe.py
│       │   ├── calendar.py
│       │   ├── corporate_actions.py
│       │   ├── adjustments.py
│       │   ├── provenance.py
│       │   └── adapters/
│       │       ├── __init__.py
│       │       └── akshare.py
│       ├── research/
│       │   ├── __init__.py
│       │   ├── models.py
│       │   ├── config.py
│       │   ├── events.py
│       │   ├── forward_returns.py
│       │   ├── statistics.py
│       │   ├── relationships.py
│       │   ├── visualization.py
│       │   ├── engine.py
│       │   └── results.py
│       ├── factors/
│       │   ├── __init__.py
│       │   ├── models.py
│       │   ├── registry.py
│       │   ├── engine.py
│       │   └── builtins.py
│       ├── signal/
│       │   ├── __init__.py
│       │   ├── models.py
│       │   ├── evaluator.py
│       │   ├── engine.py
│       │   └── state.py
│       └── strategy/
│           ├── __init__.py
│           ├── models.py
│           ├── config.py
│           ├── validators.py
│           ├── builder.py
│           └── storage.py
│
├── tests/
│   ├── __init__.py
│   ├── test_import.py
│   ├── test_config.py
│   ├── data/
│   │   ├── conftest.py
│   │   ├── test_models.py
│   │   ├── test_normalization.py
│   │   ├── test_quality.py
│   │   ├── test_storage.py
│   │   ├── test_repository.py
│   │   ├── test_ingestion.py
│   │   ├── test_pit.py
│   │   ├── test_universe.py
│   │   ├── test_calendar.py
│   │   ├── test_corporate_actions.py
│   │   ├── test_adjustments.py
│   │   └── test_provenance.py
│   ├── research/
│   │   ├── test_models.py
│   │   ├── test_config.py
│   │   ├── test_events.py
│   │   ├── test_forward_returns.py
│   │   ├── test_statistics.py
│   │   ├── test_relationships.py
│   │   ├── test_results.py
│   │   └── test_engine.py
│   ├── strategy/
│   │   ├── test_models.py
│   │   ├── test_config.py
│   │   ├── test_validators.py
│   │   ├── test_builder.py
│   │   └── test_storage.py
│   ├── factors/
│   │   ├── test_models.py
│   │   ├── test_registry.py
│   │   ├── test_engine.py
│   │   └── test_builtins.py
│   ├── signal/
│   │   ├── conftest.py
│   │   ├── test_models.py
│   │   ├── test_evaluator.py
│   │   ├── test_engine.py
│   │   ├── test_state.py
│   │   └── test_missing_data.py
│   └── integration/
│       ├── test_akshare_provider.py
│       ├── test_historical_data_integrity.py
│       ├── test_strategy_builder.py
│       ├── test_strategy_to_signal.py
│       └── test_turnover_research.py
│
├── examples/
│   ├── ingest_demo.py
│   ├── run_research.py
│   └── run_signals.py
│
├── data/
│   ├── raw/
│   ├── processed/
│   └── reference/
│
├── strategies/
│   └── examples/
│       ├── turnover_strategy_v1.yaml
│       ├── synthetic_momentum_strategy.yaml
│       └── price_threshold_strategy.yaml
├── experiments/
├── reports/
└── notebooks/
```

## Data Engine 使用範例

```python
from hk_quant.data.adapters.akshare import AKShareProvider
from hk_quant.data.ingestion import ingest_daily_prices, ingest_stock_master
from hk_quant.data.repository import DataRepository
from hk_quant.data.storage import DataStorage
from hk_quant.config import load_config

config = load_config("configs/data.yaml")
storage = DataStorage(config.storage.raw_dir, config.storage.processed_dir)
provider = AKShareProvider()

# 下載並保存 Stock Master
master = ingest_stock_master(provider, storage)

# 下載並保存某股票、某區間的日線資料
prices = ingest_daily_prices(
    provider, storage,
    stock_ids=["0700"],
    start_date="2025-01-01",
    end_date="2025-01-31",
)

# 透過 DuckDB Repository 查詢
repo = DataRepository(storage.processed_root)
result = repo.get_daily_prices(
    stock_ids=["0700"],
    start_date="2025-01-01",
    end_date="2025-01-31",
)
```

End-to-end demo：

```bash
python examples/ingest_demo.py
```

## Phase 3 使用範例

```python
from hk_quant.data.repository import DataRepository

repo = DataRepository("data/processed")

# 歷史 universe（目前 provider 缺 listing/delisting date 時會明確報錯）
universe = repo.get_universe("2022-05-10")

# 某一天當時知道的資料（Point-in-Time）
known = repo.get_data_as_of(as_of_date="2022-05-10")

# 交易日曆
repo.is_trading_day("2022-05-10")
repo.forward_trading_date("2022-05-10", 10)   # 10 個交易日

# 公司行動
repo.get_corporate_actions(stock_ids=["0700"])

# Raw vs Adjusted price
raw = repo.get_prices(stock_ids=["0700"], adjusted=False)
adj = repo.get_prices(stock_ids=["0700"], end_date="2022-05-10",
                      adjusted=True, as_of_date="2022-05-10")
```

## 已知資料來源限制（Phase 3）

| 功能 | 現狀 | 說明 |
|---|---|---|
| Historical Universe | ❌ 不可用 | AKShare 未可靠提供港股 listing/delisting date；`get_universe()` 會 raise `UniverseDataUnavailableError`，不會用今日股票清單冒充 |
| Trading Calendar | ⚠️ Observed | 由已驗證 market price dates 推導，**非**官方 HKEX 假期日曆；週末／假期以「無價格日」表示 |
| Corporate Actions | ⚠️ 部分 | AKShare 提供 dividend / 股票派發（`stock_hk_dividend_payout_em`）；split / rights 暫無可靠來源 |
| Adjusted Price | ⚠️ 自家邏輯 | 僅 split / bonus 調整；dividend 保留為 `cash_amount`，不摺入價格 |
| PIT Fundamentals | ⚠️ Synthetic only | 已建立 schema 與 filtering，但 AKShare 尚無完整 PIT fundamentals provider |

## Phase 4 使用範例

```python
from hk_quant.research import load_research_definition, run_research
from hk_quant.data.repository import DataRepository

definition = load_research_definition("configs/research/turnover_forward_return.yaml")
repo = DataRepository("data/processed")

result = run_research(definition, repository=repo)
print(result.status)          # NO_EVIDENCE / WEAK_PATTERN / ...
print(result.statistics)      # threshold × holding period 統計
print(result.warnings)        # survivorship / multiple testing 等警告
```

CLI demo：

```bash
# 真實資料（turnover_rate 目前不可用，會明確失敗並說明原因）
python examples/run_research.py --config configs/research/turnover_forward_return.yaml

# 完整 synthetic pipeline（不訪問網絡）
python examples/run_research.py --synthetic
```

## 已知資料來源限制（Phase 4）

| 功能 | 現狀 | 說明 |
|---|---|---|
| Turnover Rate（換手率） | ❌ 不可用 | 目前 provider 只提供成交額（amount），不提供換手率；Research Engine 會 raise `ResearchDataError`，不拿 amount 冒充 |
| Historical Universe | ❌ 不可用 | 同上；`observed_price_universe` 會自動附加 survivorship bias 警告 |
| Trading Calendar | ⚠️ Observed | 由 market price dates 推導，非官方 HKEX 假期日曆 |
| Multiple Testing | ⚠️ 探索性 | 每次 sweep 記錄 tested combinations，結果標記 `exploratory_research=true`，需獨立驗證 |
| Research Conclusion | ⚠️ 描述性 | `NO_EVIDENCE / WEAK_PATTERN / NOTABLE_PATTERN / WORTH_FURTHER_RESEARCH` 是研究狀態，不是 BUY/SELL 投資評級 |

## Phase 5 使用範例

```python
from hk_quant.strategy import build_strategy, load_strategy, validate_strategy

# 建立 + 驗證 + 保存
strategy = build_strategy(
    "strategies/examples/synthetic_momentum_strategy.yaml",
    strategies_dir="strategies",
)
print(strategy.strategy_hash)

# 重新載入（save → load 得到相同 definition）
loaded = load_strategy(strategy.strategy_id, strategy.version, "strategies")
assert loaded.to_dict() == strategy.to_dict()

# turnover_rate 範例只能展示 schema，validate 會誠實報錯
validate_strategy(strategy)  # 對 synthetic 例子通過
```

Strategy 狀態：`DRAFT → VALIDATED → ACTIVE → RETIRED`（本階段只建立到
`DRAFT`/`VALIDATED`，lifecycle 由後續階段控制）。

## 已知限制（Phase 5）

| 項目 | 現狀 | 說明 |
|---|---|---|
| turnover_rate field | ❌ 不可用 | Validator 會 raise `StrategyValidationError`，不拿 amount 冒充 |
| factor（如 momentum_20） | ✅ Phase 6 已建立 registry | 可用 `momentum_20`、`volatility_20`；舊策略示例仍需按當前資料覆蓋檢查 |
| historical_universe | ❌ 不可用 | 若 DataRepository 無法提供會 raise `StrategyValidationError` |
| Signal 產生 | ✅ Phase 6 已實作 | Strategy 是規則，Signal 是規則套到某天的結果 |

## Phase 6 使用範例

```python
from hk_quant.signal import generate_signal, generate_signals
from hk_quant.strategy.config import load_strategy_definition
from hk_quant.data.repository import DataRepository
from hk_quant.factors import FactorEngine, get_factor, list_factors

strategy = load_strategy_definition(
    "strategies/examples/synthetic_momentum_strategy.yaml"
)
repository = DataRepository("data/processed")
engine = FactorEngine(repository)

# 單一股票
signal = generate_signal(strategy, "2026-09-24", "0700", repository=repository)
# signal.signal      -> BUY / SELL / HOLD / None
# signal.status      -> VALID / DATA_UNAVAILABLE / OUT_OF_UNIVERSE
# signal.reason      -> 結構化 condition_results（可回答「為什麼 BUY」）

# 整個 universe
signals = generate_signals(strategy, "2026-09-24", repository=repository)
```

CLI demo：

```bash
# synthetic（不訪問網絡，展示 BUY/HOLD/SELL/DATA_UNAVAILABLE）
python examples/run_signals.py --synthetic --date 2026-09-24

# real data（close field）
python examples/run_signals.py \
    --strategy strategies/examples/price_threshold_strategy.yaml \
    --date 2025-01-02
```

## 已知限制（Phase 6）

| 項目 | 現狀 | 說明 |
|---|---|---|
| turnover_rate | ❌ 不可用 | 只有成交額 amount，signal 使用它時會明確 DATA_UNAVAILABLE |
| historical_universe | ❌ 不可用 | 缺 listing/delisting date，不 fallback 到 observed universe |
| factor registry | ⚠️ 只有 2 個 | `momentum_20`、`volatility_20`（未 annualize，明確標示） |
| Signal 只輸出 BUY/SELL/HOLD | ✅ | 不排序、不加權、不交易、不產生 Order |
| Execution timing | ✅ Phase 7 的合成回測 | Signal 不等於成交；假設下一交易日開盤成交，並記錄成本和拒單 |
| Backtest / weights | ⚠️ 已提供基礎實作 | 尚需依賴齊備的全套測試與真實資料驗證；研究結果不可視為已驗證收益 |

## Phase 7–20 目前狀態

以下「合成通過」表示離線程式碼及合成案例存在，**不表示**真實港股資料、券商帳戶或生產連線已驗證。

| Phase | 功能 | 現況與可驗證範圍 |
| --- | --- | --- |
| 7 | 組合與回測 | 基礎引擎、成本、T+1 執行及合成案例已實作；真實數據效果未驗證 |
| 8 | 資料覆蓋 | 內容 hash、完整度報告、寫入恢復及 PIT 修正已實作；歷史股票池、官方日曆、換手率仍缺來源 |
| 9 | 實驗登記 | SQLite 唯一 ID、不可覆蓋產物及來源版本已實作 |
| 10–11 | 固定策略驗證、多變量研究 | 合成 OOS、walk-forward、purge、比較基準和多變量分析已實作；未作真實資料確認 |
| 12 | 風險 | 歷史風險及回測介接已完成合成測試；缺足夠已驗證的市場資料 |
| 13 | 條件失敗模型 | 固定標籤、purged 評估及基準已實作；獨立、扣成本後的模型增益比較 **BLOCKED** |
| 14–15 | 文件研究、條件式協調 | 有來源版本、時間界線、證據與限額的合成管線已實作；具授權的正式文件來源 **BLOCKED** |
| 16–17 | 外部模擬帳戶、監控 | Futu 港股 PAPER adapter 與假帳戶測試已實作；真實 OpenD / PAPER 帳戶讀取及訂單 **BLOCKED** |
| 18–19 | 研究工具與自然語言規劃 | 有限的 Python JSON 工具、Pi extension、保守問句解析已實作；Pi CLI 真正載入 **未驗證** |
| 20 | 報告與介面 | 靜態唯讀 HTML 索引與研究報告輸出已實作；即時互動介面及正式環境驗證 **未完成** |

### 先跑可驗證的路徑

```bash
python examples/run_backtest.py          # 合成資料，不代表市場收益
python examples/run_validation.py        # 合成資料，保留 final test
python examples/run_multivariable.py     # 合成研究
PYTHONPATH=src python -m unittest discover -s tests/unit_stdlib -v
python -m pytest -q -m 'not integration' tests
python -m pytest -q tests/integration/test_end_to_end_backtest.py
```

詳細接入順序、資料權限、Paper 安全檢查、驗收與已知缺口見[執行指南](docs/implementation-guide.md)，資料契約見[資料就緒說明](docs/data-readiness.md)，風險與模型限制見[風險/ML 說明](docs/risk_ml.md)。
