"""Save and load raw and processed market data.

Storage only deals with *how data is persisted*. It has no knowledge of
research, strategy, backtest or ML concepts.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Union

import pandas as pd

from hk_quant.data import models

PathLike = Union[str, os.PathLike[str]]


class DataStorage:
    """Filesystem storage for raw and processed parquet data."""

    def __init__(self, raw_dir: PathLike, processed_dir: PathLike) -> None:
        self.raw_root = Path(raw_dir)
        self.processed_root = Path(processed_dir)
        self.raw_root.mkdir(parents=True, exist_ok=True)
        self.processed_root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ raw

    def save_raw_stock_master(self, df: pd.DataFrame, provider: str, run_date: str) -> Path:
        """Save a raw stock master response under ``<raw>/<provider>/stock_master/<run_date>/``."""
        dest = self.raw_root / provider / "stock_master" / str(run_date)
        dest.mkdir(parents=True, exist_ok=True)
        path = dest / "stock_master.parquet"
        df.to_parquet(path, index=False)
        return path

    def save_raw_daily_prices(
        self,
        df: pd.DataFrame,
        provider: str,
        run_date: str,
        stock_id: str,
        start_date: str,
        end_date: str,
    ) -> Path:
        """Save a raw daily price response under ``<raw>/<provider>/daily_prices/<run_date>/``."""
        dest = self.raw_root / provider / "daily_prices" / str(run_date)
        dest.mkdir(parents=True, exist_ok=True)
        path = dest / f"{stock_id}_{start_date}_{end_date}.parquet"
        df.to_parquet(path, index=False)
        return path

    def save_raw_corporate_actions(
        self, df: pd.DataFrame, provider: str, run_date: str, stock_id: str
    ) -> Path:
        """Save a raw corporate action response under ``<raw>/<provider>/corporate_actions/<run_date>/``."""
        dest = self.raw_root / provider / "corporate_actions" / str(run_date)
        dest.mkdir(parents=True, exist_ok=True)
        path = dest / f"{stock_id}.parquet"
        df.to_parquet(path, index=False)
        return path

    def raw_daily_prices_exists(
        self, provider: str, stock_id: str, start_date: str, end_date: str
    ) -> bool:
        """Return True if raw daily prices for the exact range were already saved."""
        base = self.raw_root / provider / "daily_prices"
        if not base.exists():
            return False
        filename = f"{stock_id}_{start_date}_{end_date}.parquet"
        return any(base.rglob(filename))

    # ------------------------------------------------------------- processed

    def save_stock_master(self, df: pd.DataFrame) -> Path:
        """Save canonical stock master data (single parquet file)."""
        dest = self.processed_root / "stock_master"
        dest.mkdir(parents=True, exist_ok=True)
        path = dest / "stock_master.parquet"
        df.to_parquet(path, index=False)
        return path

    def load_stock_master(self) -> pd.DataFrame:
        """Load canonical stock master data."""
        path = self.processed_root / "stock_master" / "stock_master.parquet"
        if not path.exists():
            raise FileNotFoundError(f"no processed stock master at {path}")
        return pd.read_parquet(path)

    def save_daily_prices(self, df: pd.DataFrame) -> list[Path]:
        """Save canonical daily prices, partitioned by ``stock_id/year/month``."""
        result = df.copy()
        dates = pd.to_datetime(result["trade_date"], errors="coerce")
        result["_year"] = dates.dt.year
        result["_month"] = dates.dt.month

        paths: list[Path] = []
        groups = result.groupby(["stock_id", "_year", "_month"], sort=True)
        for (stock_id, year, month), group in groups:
            group = group.drop(columns=["_year", "_month"])
            dest = (
                self.processed_root
                / "daily_prices"
                / str(stock_id)
                / f"{int(year):04d}"
                / f"{int(month):02d}"
            )
            dest.mkdir(parents=True, exist_ok=True)
            path = dest / "data.parquet"
            group.to_parquet(path, index=False)
            paths.append(path)
        return paths

    def load_daily_prices(
        self,
        stock_id: str | list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        """Load canonical daily prices, optionally filtered by stock/date."""
        base = self.processed_root / "daily_prices"
        files = list(base.rglob("*.parquet")) if base.exists() else []
        if not files:
            return pd.DataFrame(columns=list(models.DAILY_PRICE_COLUMNS))

        df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
        df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce")

        if stock_id is not None:
            ids = [stock_id] if isinstance(stock_id, str) else list(stock_id)
            df = df[df["stock_id"].isin(ids)]
        if start_date is not None:
            df = df[df["trade_date"] >= pd.to_datetime(start_date)]
        if end_date is not None:
            df = df[df["trade_date"] <= pd.to_datetime(end_date)]

        return df.sort_values(["stock_id", "trade_date"]).reset_index(drop=True)

    def save_fundamentals(self, df: pd.DataFrame) -> Path:
        """Save canonical fundamentals (single parquet file)."""
        dest = self.processed_root / "fundamentals"
        dest.mkdir(parents=True, exist_ok=True)
        path = dest / "fundamentals.parquet"
        df.to_parquet(path, index=False)
        return path

    def load_fundamentals(self) -> pd.DataFrame:
        """Load canonical fundamentals (empty frame if not present)."""
        path = self.processed_root / "fundamentals" / "fundamentals.parquet"
        if not path.exists():
            return pd.DataFrame(columns=list(models.FUNDAMENTAL_COLUMNS))
        return pd.read_parquet(path)

    def save_corporate_actions(self, df: pd.DataFrame) -> Path:
        """Save canonical corporate actions (single parquet file)."""
        dest = self.processed_root / "corporate_actions"
        dest.mkdir(parents=True, exist_ok=True)
        path = dest / "corporate_actions.parquet"
        df.to_parquet(path, index=False)
        return path

    def load_corporate_actions(self) -> pd.DataFrame:
        """Load canonical corporate actions (empty frame if not present)."""
        path = self.processed_root / "corporate_actions" / "corporate_actions.parquet"
        if not path.exists():
            return pd.DataFrame(columns=list(models.CORPORATE_ACTION_COLUMNS))
        return pd.read_parquet(path)

    def save_calendar(self, df: pd.DataFrame) -> Path:
        """Save a trading calendar (single-column frame of trade dates)."""
        dest = self.processed_root / "calendar"
        dest.mkdir(parents=True, exist_ok=True)
        path = dest / "calendar.parquet"
        df.to_parquet(path, index=False)
        return path

    def load_calendar(self) -> pd.DataFrame:
        """Load the trading calendar (empty frame if not present)."""
        path = self.processed_root / "calendar" / "calendar.parquet"
        if not path.exists():
            return pd.DataFrame(columns=list(models.CALENDAR_COLUMNS))
        return pd.read_parquet(path)
