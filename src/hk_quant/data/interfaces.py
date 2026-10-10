"""Provider abstractions for market data."""

from __future__ import annotations

from typing import Protocol

import pandas as pd


class MarketDataProvider(Protocol):
    """Minimal market data provider interface.

    Providers return *canonical* DataFrames (see ``hk_quant.data.models``),
    so upper layers never depend on provider-specific column names.
    """

    def get_stock_master(self) -> pd.DataFrame:
        """Return canonical stock master data."""
        ...

    def get_daily_prices(
        self,
        stock_ids: list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        """Return canonical daily prices for the given stocks and date range."""
        ...
