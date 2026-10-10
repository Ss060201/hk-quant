"""Position state tests."""

from __future__ import annotations

from hk_quant.signal.state import PositionState


def test_position_state_fields() -> None:
    state = PositionState(
        stock_id="0700",
        entry_date="2026-09-17",
        strategy_id="turnover_strategy",
        strategy_version="1.0.0",
    )
    assert state.stock_id == "0700"
    assert state.entry_date == "2026-09-17"
    assert state.strategy_id == "turnover_strategy"
