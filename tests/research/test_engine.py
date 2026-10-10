"""Research engine end-to-end tests (synthetic, no network)."""

from __future__ import annotations

import pandas as pd
import pytest

from hk_quant.research.engine import ResearchDataError, run_research
from hk_quant.research.events import build_events
from hk_quant.research.models import (
    ResearchDefinition,
    ResearchStatus,
    UniverseSpec,
    VariableSpec,
)


def _synthetic_panel() -> pd.DataFrame:
    dates = pd.bdate_range("2020-01-02", periods=40)
    rows = []
    price = 100.0
    for i, day in enumerate(dates):
        price *= 1.005
        rows.append(
            {
                "stock_id": "TEST001",
                "trade_date": day.date(),
                "open": price,
                "high": price * 1.01,
                "low": price * 0.99,
                "close": price,
                "volume": 1_000_000.0,
                "amount": 100_000_000.0,
                "turnover_rate": 0.04 + (i % 20) * 0.05,
                "source": "synthetic",
                "ingested_at": pd.Timestamp.now("UTC"),
            }
        )
    return pd.DataFrame(rows)


def _definition() -> ResearchDefinition:
    return ResearchDefinition(
        name="turnover_v1",
        variable=VariableSpec(name="turnover_rate", thresholds=[0.1, 0.3, 0.5]),
        forward_periods=[1, 2, 3, 5],
    )


def test_run_research_end_to_end(tmp_path) -> None:
    result = run_research(
        _definition(),
        panel=_synthetic_panel(),
        output_dir=tmp_path / "research" / "turnover_v1",
    )

    assert not result.events.empty
    assert not result.forward_returns.empty
    assert len(result.statistics) == 3 * 4  # thresholds x periods
    assert result.tested_combinations == 12
    assert result.status in list(ResearchStatus)
    assert any("survivorship" in w for w in result.warnings)

    root = tmp_path / "research" / "turnover_v1"
    assert (root / "summary.json").exists()
    assert (root / "events.parquet").exists()
    assert (root / "forward_returns.parquet").exists()
    assert (root / "plots" / "heatmap.png").exists()


def test_event_detection_is_independent_of_future_prices() -> None:
    panel = _synthetic_panel()
    definition = _definition()

    events_before = build_events(panel, definition)

    # Change every price (including future) dramatically; events must not change
    modified = panel.copy()
    modified["close"] = modified["close"] * 2 + 100
    modified["open"] = 999.0
    modified["high"] = 999.0
    modified["low"] = 999.0

    events_after = build_events(modified, definition)
    pd.testing.assert_frame_equal(events_before, events_after)


def test_missing_variable_raises_clear_error() -> None:
    panel = _synthetic_panel().drop(columns=["turnover_rate"])
    with pytest.raises(ResearchDataError, match="turnover_rate"):
        run_research(_definition(), panel=panel)


def test_all_null_variable_raises_clear_error() -> None:
    panel = _synthetic_panel()
    panel["turnover_rate"] = float("nan")
    with pytest.raises(ResearchDataError, match="unavailable"):
        run_research(_definition(), panel=panel)


def test_historical_universe_unavailable_raises() -> None:
    definition = _definition()
    definition.universe = UniverseSpec(mode="historical_universe")
    with pytest.raises(ResearchDataError, match="historical universe"):
        run_research(definition, repository=object())


def test_no_events_yields_no_evidence() -> None:
    panel = _synthetic_panel()
    panel["turnover_rate"] = 0.01  # below every threshold
    result = run_research(_definition(), panel=panel)
    assert result.events.empty
    assert result.status == ResearchStatus.NO_EVIDENCE
