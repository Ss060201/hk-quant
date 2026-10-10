"""Signal model tests."""

from __future__ import annotations

from hk_quant.signal.models import Signal, SignalStatus, SignalType


def test_signal_types() -> None:
    assert {s.value for s in SignalType} == {"BUY", "SELL", "HOLD"}


def test_signal_statuses() -> None:
    assert {
        s.value for s in SignalStatus
    } == {"VALID", "DATA_UNAVAILABLE", "OUT_OF_UNIVERSE", "INVALID"}


def test_signal_to_dict() -> None:
    signal = Signal(
        strategy_id="s",
        strategy_version="1.0.0",
        strategy_hash="abc",
        stock_id="0700",
        signal_date="2026-09-24",
        signal="BUY",
        status=SignalStatus.VALID,
        reason={"entry": {"passed": True}},
        data_version="HK_DAILY_2026_09_24",
        factor_versions={"momentum_20": "1.0.0"},
    )
    data = signal.to_dict()
    assert data["signal"] == "BUY"
    assert data["status"] == "VALID"
    assert data["factor_versions"] == {"momentum_20": "1.0.0"}
