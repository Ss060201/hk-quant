"""Shared fixtures for backtest tests."""

from __future__ import annotations

import pandas as pd
import pytest

from hk_quant.data.calendar import TradingCalendar


class FakeBacktestRepository:
    def __init__(
        self,
        prices: pd.DataFrame,
        actions: pd.DataFrame | None = None,
        data_version: str = "test-v1",
    ) -> None:
        self.prices = prices
        self.actions = actions if actions is not None else pd.DataFrame()
        self.data_version = data_version

    def get_daily_prices(self, start_date=None, end_date=None, stock_ids=None):
        df = self.prices
        if stock_ids:
            ids = [stock_ids] if isinstance(stock_ids, str) else list(stock_ids)
            df = df[df["stock_id"].isin(ids)]
        if start_date:
            df = df[pd.to_datetime(df["trade_date"]) >= pd.Timestamp(start_date)]
        if end_date:
            df = df[pd.to_datetime(df["trade_date"]) <= pd.Timestamp(end_date)]
        return df.reset_index(drop=True)

    def get_calendar(self):
        return TradingCalendar.from_prices(self.prices)

    def get_corporate_actions(self, stock_ids=None):
        df = self.actions
        if df.empty or "stock_id" not in df.columns:
            return df.reset_index(drop=True)
        if stock_ids:
            ids = [stock_ids] if isinstance(stock_ids, str) else list(stock_ids)
            df = df[df["stock_id"].isin(ids)]
        return df.reset_index(drop=True)

    def get_data_version(self):
        return self.data_version


def price_rows(stock_id: str, n_days: int, end: str, *, start_close: float = 100.0,
               closes: list[float] | None = None) -> list[dict]:
    """Build price rows with explicit closes (hand-calculable)."""
    dates = pd.bdate_range(end=pd.Timestamp(end), periods=n_days)
    if closes is None:
        closes = [start_close] * n_days
    assert len(closes) == n_days
    rows = []
    for day, close in zip(dates, closes):
        rows.append(
            {
                "stock_id": stock_id,
                "trade_date": day.date(),
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "volume": 1_000_000.0,
                "amount": 10_000_000.0,
                "turnover_rate": None,
                "source": "synthetic",
                "ingested_at": pd.Timestamp.now("UTC"),
            }
        )
    return rows


@pytest.fixture
def make_repo():
    def _make(prices: pd.DataFrame, actions: pd.DataFrame | None = None) -> FakeBacktestRepository:
        return FakeBacktestRepository(prices, actions)
    return _make
