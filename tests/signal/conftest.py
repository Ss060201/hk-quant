"""Shared fixtures for signal tests."""

from __future__ import annotations

import pandas as pd
import pytest

from hk_quant.data.calendar import TradingCalendar
from hk_quant.data.universe import UniverseDataUnavailableError


class FakeRepository:
    """Minimal in-memory repository for signal tests."""

    def __init__(self, panel: pd.DataFrame, universe_df: pd.DataFrame | None = None) -> None:
        self.panel = panel
        self._calendar = TradingCalendar.from_prices(panel)
        self.universe_df = universe_df

    def get_daily_prices(self, stock_ids=None, start_date=None, end_date=None) -> pd.DataFrame:
        return self._filter(stock_ids, start_date, end_date)

    def get_prices(self, stock_ids=None, start_date=None, end_date=None, *, adjusted=False):
        return self._filter(stock_ids, start_date, end_date)

    def get_calendar(self) -> TradingCalendar:
        return self._calendar

    def get_universe(self, as_of_date) -> pd.DataFrame:
        if self.universe_df is None:
            raise UniverseDataUnavailableError("listing_date unavailable")
        return self.universe_df

    def _filter(self, stock_ids, start_date, end_date) -> pd.DataFrame:
        df = self.panel
        if stock_ids:
            ids = [stock_ids] if isinstance(stock_ids, str) else list(stock_ids)
            df = df[df["stock_id"].isin(ids)]
        if start_date:
            df = df[pd.to_datetime(df["trade_date"]) >= pd.Timestamp(start_date)]
        if end_date:
            df = df[pd.to_datetime(df["trade_date"]) <= pd.Timestamp(end_date)]
        return df.reset_index(drop=True)


def make_rows(
    stock_id: str,
    days: int,
    end: str,
    drift: float = 0.0,
    start_close: float = 100.0,
    missing_last: bool = False,
) -> list[dict]:
    dates = pd.bdate_range(end=pd.Timestamp(end), periods=days)
    rows = []
    close = start_close
    for i, day in enumerate(dates):
        close *= 1.0 + drift
        value = float("nan") if (missing_last and i == days - 1) else close
        rows.append(
            {
                "stock_id": stock_id,
                "trade_date": day.date(),
                "open": value,
                "high": value,
                "low": value,
                "close": value,
                "volume": 1_000_000.0,
                "amount": 100_000_000.0,
                "turnover_rate": float("nan"),
                "source": "synthetic",
                "ingested_at": pd.Timestamp.now("UTC"),
            }
        )
    return rows


@pytest.fixture
def make_repository():
    def _make(rows: list[dict], universe_df: pd.DataFrame | None = None) -> FakeRepository:
        return FakeRepository(pd.DataFrame(rows), universe_df)
    return _make
