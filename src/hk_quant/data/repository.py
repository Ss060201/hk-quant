"""DuckDB-backed query interface over processed parquet data.

The repository is the only interface upper layers should use to read data.
It also owns the *data layer* logic for point-in-time filtering, historical
universe construction, trading calendars, corporate actions and raw/adjusted
prices, so research/backtest code never re-implements those rules.
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Sequence, Union

import duckdb
import pandas as pd

from hk_quant.data import models
from hk_quant.data.adjustments import adjust_prices
from hk_quant.data.calendar import TradingCalendar
from hk_quant.data.point_in_time import get_fundamentals_as_of
from hk_quant.data.provenance import get_data_version
from hk_quant.data.universe import get_universe

PathLike = Union[str, os.PathLike[str]]


def _parquet_path_literal(path: Path) -> str:
    """Quote a filesystem path as an SQL string, including embedded apostrophes.

    ``read_parquet`` needs a constant path when binding the file's schema;
    user supplied stock IDs and dates remain separately parameterized.
    """
    return "'" + path.as_posix().replace("'", "''") + "'"


class DataRepository:
    """Query canonical processed data with DuckDB."""

    def __init__(self, processed_dir: PathLike) -> None:
        self.processed_root = Path(processed_dir)

    # ---------------------------------------------------------------- prices

    def get_daily_prices(
        self,
        stock_ids: Sequence[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        """Query daily prices for the given stocks and date range."""
        base = self.processed_root / "daily_prices"
        if not base.exists() or not any(base.rglob("*.parquet")):
            return pd.DataFrame(columns=list(models.DAILY_PRICE_COLUMNS))

        glob_path = base / "**" / "*.parquet"
        sql = f"SELECT * FROM read_parquet({_parquet_path_literal(glob_path)})"
        params: list[object] = []

        conditions: list[str] = []
        if stock_ids:
            ids = list(dict.fromkeys(stock_ids))
            conditions.append(f"stock_id IN ({', '.join('?' for _ in ids)})")
            params.extend(ids)
        if start_date is not None:
            conditions.append("trade_date >= CAST(? AS DATE)")
            params.append(start_date)
        if end_date is not None:
            conditions.append("trade_date <= CAST(? AS DATE)")
            params.append(end_date)
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY stock_id, trade_date"

        con = duckdb.connect()
        try:
            return con.execute(sql, params).df()
        finally:
            con.close()

    def get_prices(
        self,
        stock_ids: Sequence[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        *,
        adjusted: bool = False,
        as_of_date: object | None = None,
    ) -> pd.DataFrame:
        """Query daily prices, returning RAW or ADJUSTED research prices.

        ``adjusted=False`` returns raw provider prices. ``adjusted=True``
        uses only split/bonus actions effective and announced as of the
        selected date: ``as_of_date`` if given, otherwise ``end_date`` (or
        the last returned trade date). Call with end_date=T for a T signal.
        A full retrospectively adjusted historical panel can still encode
        future information in its early rows; backtests must calculate each
        historical signal with its own T cutoff. Dividends stay separate.
        """
        effective_end = end_date
        if as_of_date is not None:
            as_of = pd.Timestamp(as_of_date)
            if pd.isna(as_of):
                raise ValueError("invalid as_of_date")
            cutoff_date = as_of.date()
            if end_date is not None and pd.Timestamp(end_date).date() > cutoff_date:
                raise ValueError("end_date must not exceed as_of_date")
            effective_end = end_date if end_date is not None else cutoff_date.isoformat()
        raw = self.get_daily_prices(stock_ids, start_date, effective_end)
        if not adjusted or raw.empty:
            return raw
        cutoff = pd.Timestamp(as_of_date if as_of_date is not None else
                              end_date if end_date is not None else raw["trade_date"].max())
        if pd.isna(cutoff):
            raise ValueError("invalid as_of_date")
        actions = self.get_corporate_actions(stock_ids=stock_ids)
        return adjust_prices(raw, actions, as_of_date=cutoff)

    def get_data_version(self) -> str:
        """Return the verified content fingerprint for current processed data."""
        return get_data_version(self.processed_root)

    def get_data_coverage(self) -> dict:
        """Report observed coverage and explicit current provider limitations."""
        from hk_quant.data.coverage import report_data_coverage

        return report_data_coverage(self)

    def get_stock_master(self) -> pd.DataFrame:
        """Return the full canonical stock master table."""
        path = self.processed_root / "stock_master" / "stock_master.parquet"
        if not path.exists():
            return pd.DataFrame(columns=list(models.STOCK_MASTER_COLUMNS))

        con = duckdb.connect()
        try:
            sql = f"SELECT * FROM read_parquet({_parquet_path_literal(path)}) ORDER BY stock_id"
            return con.execute(sql).df()
        finally:
            con.close()

    # --------------------------------------------------------- point-in-time

    def _read_parquet_or_empty(
        self, rel_path: str, columns: tuple[str, ...]
    ) -> pd.DataFrame:
        path = self.processed_root / rel_path
        if not path.exists():
            return pd.DataFrame(columns=list(columns))
        return pd.read_parquet(path)

    def get_fundamentals(self) -> pd.DataFrame:
        """Return the full canonical fundamentals table (empty if absent)."""
        return self._read_parquet_or_empty(
            "fundamentals/fundamentals.parquet", models.FUNDAMENTAL_COLUMNS
        )

    def get_data_as_of(
        self,
        as_of_date: object,
        stock_ids: Sequence[str] | None = None,
        metric: str | None = None,
    ) -> pd.DataFrame:
        """Return fundamentals that were known as of ``as_of_date``."""
        fundamentals = self.get_fundamentals()
        return get_fundamentals_as_of(
            fundamentals, as_of_date, stock_ids=stock_ids, metric=metric
        )

    # -------------------------------------------------------------- universe

    def get_universe(self, as_of_date: object) -> pd.DataFrame:
        """Return the historical universe as of ``as_of_date``.

        Raises :class:`UniverseDataUnavailableError` if the stock master has
        no listing/delisting dates (current provider limitation).
        """
        return get_universe(self.get_stock_master(), as_of_date)

    # -------------------------------------------------------------- calendar

    def get_calendar(self) -> TradingCalendar:
        """Return the trading calendar.

        Uses a stored calendar if present; otherwise derives an *observed*
        calendar from processed daily price dates.
        """
        cal_path = self.processed_root / "calendar" / "calendar.parquet"
        if cal_path.exists():
            cal_df = pd.read_parquet(cal_path)
            return TradingCalendar(cal_df["trade_date"].tolist())
        return TradingCalendar.from_prices(self.get_daily_prices())

    def is_trading_day(self, d: object) -> bool:
        return self.get_calendar().is_trading_day(d)

    def get_trading_days(
        self, start_date: object | None = None, end_date: object | None = None
    ) -> list[date]:
        return self.get_calendar().get_trading_days(start_date, end_date)

    def next_trading_day(self, d: object) -> date:
        return self.get_calendar().next_trading_day(d)

    def previous_trading_day(self, d: object) -> date:
        return self.get_calendar().previous_trading_day(d)

    def forward_trading_date(self, d: object, periods: int) -> date:
        return self.get_calendar().forward_trading_date(d, periods)

    # ----------------------------------------------------- corporate actions

    def get_corporate_actions(
        self, stock_ids: Sequence[str] | None = None
    ) -> pd.DataFrame:
        """Return canonical corporate actions, optionally filtered by stock."""
        df = self._read_parquet_or_empty(
            "corporate_actions/corporate_actions.parquet",
            models.CORPORATE_ACTION_COLUMNS,
        )
        if stock_ids:
            ids = list(dict.fromkeys(stock_ids))
            df = df[df["stock_id"].isin(ids)]
        return df.reset_index(drop=True)
