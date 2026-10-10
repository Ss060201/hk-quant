"""Strategy -> Factor -> Signal integration tests.

Synthetic chain (deterministic) and a real-data chain via AKShare/DataRepository.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from hk_quant.signal import (
    PositionState,
    SignalStatus,
    SignalType,
    generate_signals,
)
from hk_quant.strategy.config import load_strategy_definition
from hk_quant.strategy.validators import validate_strategy
from tests.signal.conftest import FakeRepository, make_rows

pytestmark = pytest.mark.integration

_EXAMPLES = Path(__file__).resolve().parents[2] / "strategies" / "examples"

SIGNAL_DATE = "2026-09-24"


def test_synthetic_strategy_to_signal(tmp_path) -> None:
    strategy = load_strategy_definition(_EXAMPLES / "synthetic_momentum_strategy.yaml")
    validate_strategy(strategy)

    rows = []
    rows += make_rows("TEST001", 30, SIGNAL_DATE, drift=0.01)  # momentum > 5% -> BUY
    rows += make_rows("TEST002", 30, SIGNAL_DATE, drift=0.0)   # momentum ~0 -> HOLD
    rows += make_rows("TEST003", 5, SIGNAL_DATE, drift=0.01)   # insufficient history -> DATA_UNAVAILABLE
    rows += make_rows("TEST004", 30, SIGNAL_DATE, drift=0.01)  # position -> SELL

    repository = FakeRepository(pd.DataFrame(rows))
    calendar = repository.get_calendar()
    days = calendar.get_trading_days(end_date=SIGNAL_DATE)
    entry_date = days[-6].isoformat()  # 5 trading days before signal date

    state = {
        "TEST004": PositionState("TEST004", entry_date, strategy.strategy_id, strategy.version)
    }
    signals = generate_signals(
        strategy,
        SIGNAL_DATE,
        universe=["TEST001", "TEST002", "TEST003", "TEST004"],
        state=state,
        repository=repository,
    )
    by_id = {s.stock_id: s for s in signals}

    assert by_id["TEST001"].signal == SignalType.BUY.value
    assert by_id["TEST001"].status == SignalStatus.VALID
    assert by_id["TEST001"].factor_versions == {"momentum_20": "1.0.0"}

    assert by_id["TEST002"].signal == SignalType.HOLD.value

    assert by_id["TEST003"].signal is None
    assert by_id["TEST003"].status == SignalStatus.DATA_UNAVAILABLE

    assert by_id["TEST004"].signal == SignalType.SELL.value


def test_real_data_strategy_to_signal(tmp_path) -> None:
    import requests

    from hk_quant.data.adapters.akshare import AKShareProvider
    from hk_quant.data.ingestion import ingest_daily_prices
    from hk_quant.data.repository import DataRepository
    from hk_quant.data.storage import DataStorage

    storage = DataStorage(tmp_path / "raw", tmp_path / "processed")
    provider = AKShareProvider()
    try:
        ingest_daily_prices(
            provider,
            storage,
            stock_ids=["0700"],
            start_date="2025-01-01",
            end_date="2025-01-31",
        )
    except requests.exceptions.ConnectionError as exc:
        pytest.skip(f"AKShare unreachable: {exc}")

    repository = DataRepository(storage.processed_root)
    strategy = load_strategy_definition(_EXAMPLES / "price_threshold_strategy.yaml")
    validate_strategy(strategy)

    signals = generate_signals(strategy, "2025-01-02", repository=repository)
    by_id = {s.stock_id: s for s in signals}
    assert "0700" in by_id
    assert by_id["0700"].status == SignalStatus.VALID
    assert by_id["0700"].signal is not None
