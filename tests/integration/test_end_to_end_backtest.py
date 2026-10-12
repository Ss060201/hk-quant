"""End-to-end synthetic DataStorage -> Repository -> Signal -> Backtest.

These tests need the project's installed Parquet/DuckDB dependencies, but no
network or live market prices. The example strategy has no claimed alpha.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from hk_quant.backtest import BacktestConfig, run_backtest
from hk_quant.data.repository import DataRepository
from hk_quant.data.storage import DataStorage
from hk_quant.strategy.config import load_strategy_definition


pytestmark = pytest.mark.integration


def test_processed_prices_flow_into_signals_and_raw_open_fills(tmp_path):
    days = ["2026-01-02", "2026-01-05", "2026-01-06"]
    frame = pd.DataFrame([
        {
            "stock_id": "0700", "trade_date": pd.Timestamp(day).date(),
            "open": open_, "high": max(open_, close), "low": min(open_, close),
            "close": close, "volume": 100000.0, "amount": 10000000.0,
            "turnover_rate": None, "source": "synthetic",
            "ingested_at": pd.Timestamp("2026-01-07", tz="UTC"),
        }
        for day, open_, close in zip(days, (100.0, 100.0, 110.0), (500.0, 110.0, 110.0))
    ])
    storage = DataStorage(tmp_path / "raw", tmp_path / "processed")
    storage.save_daily_prices(frame)
    repository = DataRepository(storage.processed_root)
    strategy = load_strategy_definition(
        Path(__file__).resolve().parents[2] / "strategies/examples/price_threshold_strategy.yaml"
    )
    result = run_backtest(
        strategy, days[0], days[-1], repository,
        BacktestConfig(initial_capital=1000, commission_rate=0, slippage_rate=0),
        universe=["0700"], output_dir=tmp_path / "result",
    )
    assert result.signals.iloc[0]["signal"] == "BUY"
    assert result.trades.iloc[0].execution_date == days[1]
    assert result.trades.iloc[0].raw_open == 100
    assert result.trades.iloc[0].quantity == 10
    assert result.daily.iloc[-1].equity == 1100
    assert result.metadata["status"] == "EXPLORATORY"
    assert (tmp_path / "result" / "summary.json").exists()
