"""Factor engine tests."""

from __future__ import annotations

import pandas as pd
import pytest

from hk_quant.factors import FactorEngine


class _Repo:
    def __init__(self, panel: pd.DataFrame) -> None:
        self.panel = panel

    def get_prices(self, stock_ids=None, start_date=None, end_date=None, *, adjusted=False):
        df = self.panel
        if stock_ids:
            ids = [stock_ids] if isinstance(stock_ids, str) else list(stock_ids)
            df = df[df["stock_id"].isin(ids)]
        if start_date:
            df = df[pd.to_datetime(df["trade_date"]) >= pd.Timestamp(start_date)]
        if end_date:
            df = df[pd.to_datetime(df["trade_date"]) <= pd.Timestamp(end_date)]
        return df.reset_index(drop=True)


def _rows(stock_id: str, days: int, end: str, drift: float = 0.01) -> list[dict]:
    dates = pd.bdate_range(end=pd.Timestamp(end), periods=days)
    rows = []
    close = 100.0
    for day in dates:
        close *= 1.0 + drift
        rows.append(
            {
                "stock_id": stock_id,
                "trade_date": day.date(),
                "close": close,
            }
        )
    return rows


def test_calculate_factor_records_value_and_version() -> None:
    end = "2026-09-24"
    panel = pd.DataFrame(_rows("TEST001", 25, end, drift=0.01))
    engine = FactorEngine(_Repo(panel))

    result = engine.calculate("momentum_20", end, stock_ids=["TEST001"])
    assert len(result) == 1
    assert result.iloc[0]["factor_version"] == "1.0.0"
    assert result.iloc[0]["factor_id"] == "momentum_20"
    assert pd.notna(result.iloc[0]["value"])


def test_factor_lookahead_does_not_change_value() -> None:
    signal_date = "2026-09-24"
    # panel includes T+1 (2026-09-25); the engine only fetches up to T
    panel = pd.DataFrame(_rows("TEST001", 26, end="2026-09-25", drift=0.01))
    repo = _Repo(panel)
    engine = FactorEngine(repo)

    before = engine.calculate("momentum_20", signal_date, stock_ids=["TEST001"]).iloc[0]["value"]

    # Mutate T+1 dramatically; factor at T must not change.
    panel.loc[panel["trade_date"] == pd.Timestamp("2026-09-25").date(), "close"] = 99999.0
    after = engine.calculate("momentum_20", signal_date, stock_ids=["TEST001"]).iloc[0]["value"]

    assert before == pytest.approx(after)


def test_factor_cache_round_trip(tmp_path) -> None:
    end = "2026-09-24"
    panel = pd.DataFrame(_rows("TEST001", 25, end, drift=0.01))
    engine = FactorEngine(_Repo(panel), cache_dir=tmp_path / "factors")

    first = engine.calculate("momentum_20", end, stock_ids=["TEST001"])
    second = engine.calculate("momentum_20", end, stock_ids=["TEST001"])
    pd.testing.assert_frame_equal(first, second)
    assert list((tmp_path / "factors" / "momentum_20").rglob("*.parquet"))
