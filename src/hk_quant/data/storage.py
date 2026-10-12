"""Save and load raw and processed market data.

Storage only deals with *how data is persisted*. It has no knowledge of
research, strategy, backtest or ML concepts.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import date
from pathlib import Path
from typing import Union

import pandas as pd

from hk_quant.data import models
from hk_quant.data.provenance import hash_file, update_data_manifest

PathLike = Union[str, os.PathLike[str]]


class DataStorage:
    """Filesystem storage for raw and processed parquet data."""

    def __init__(self, raw_dir: PathLike, processed_dir: PathLike) -> None:
        self.raw_root = Path(raw_dir)
        self.processed_root = Path(processed_dir)
        self.raw_root.mkdir(parents=True, exist_ok=True)
        self.processed_root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _safe_component(value: str) -> str:
        """Reject separators and traversal in identifiers used as path parts."""
        value = str(value)
        if value in {".", ".."} or not re.fullmatch(r"[A-Za-z0-9_.-]+", value):
            raise ValueError(f"invalid identifier for data path: {value!r}")
        return value

    @staticmethod
    def _safe_date(value: str) -> str:
        return date.fromisoformat(str(value)).isoformat()

    @staticmethod
    def _atomic_parquet(df: pd.DataFrame, path: Path) -> None:
        """Replace a parquet file only after the new file is fully written."""
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=".writing-", suffix=".parquet.tmp", dir=path.parent)
        os.close(fd)
        try:
            df.to_parquet(name, index=False)
            os.replace(name, path)
        finally:
            Path(name).unlink(missing_ok=True)

    @staticmethod
    def _atomic_json(data: dict, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=".writing-", suffix=".json.tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(data, stream, indent=2, ensure_ascii=False)
            os.replace(name, path)
        finally:
            Path(name).unlink(missing_ok=True)

    def _save_processed(self, df: pd.DataFrame, path: Path) -> Path:
        self._atomic_parquet(df, path)
        update_data_manifest(self.processed_root, [path])
        return path

    # ------------------------------------------------------------------ raw

    def save_raw_stock_master(self, df: pd.DataFrame, provider: str, run_date: str) -> Path:
        """Save a raw stock master response under ``<raw>/<provider>/stock_master/<run_date>/``."""
        dest = self.raw_root / self._safe_component(provider) / "stock_master" / self._safe_date(run_date)
        dest.mkdir(parents=True, exist_ok=True)
        path = dest / "stock_master.parquet"
        self._atomic_parquet(df, path)
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
        dest = self.raw_root / self._safe_component(provider) / "daily_prices" / self._safe_date(run_date)
        dest.mkdir(parents=True, exist_ok=True)
        path = dest / (f"{self._safe_component(stock_id)}_"
                       f"{self._safe_date(start_date)}_{self._safe_date(end_date)}.parquet")
        self._atomic_parquet(df, path)
        return path

    def save_raw_corporate_actions(
        self, df: pd.DataFrame, provider: str, run_date: str, stock_id: str
    ) -> Path:
        """Save a raw corporate action response under ``<raw>/<provider>/corporate_actions/<run_date>/``."""
        dest = self.raw_root / self._safe_component(provider) / "corporate_actions" / self._safe_date(run_date)
        dest.mkdir(parents=True, exist_ok=True)
        path = dest / f"{self._safe_component(stock_id)}.parquet"
        self._atomic_parquet(df, path)
        return path

    def raw_daily_prices_exists(
        self, provider: str, stock_id: str, start_date: str, end_date: str
    ) -> bool:
        """Return True if raw daily prices for the exact range were already saved."""
        return self.find_raw_daily_prices(provider, stock_id, start_date, end_date) is not None

    def find_raw_daily_prices(
        self, provider: str, stock_id: str, start_date: str, end_date: str
    ) -> Path | None:
        """Locate the latest saved response for an exact download range."""
        base = self.raw_root / self._safe_component(provider) / "daily_prices"
        if not base.exists():
            return None
        filename = (f"{self._safe_component(stock_id)}_"
                    f"{self._safe_date(start_date)}_{self._safe_date(end_date)}.parquet")
        matches = sorted(base.glob(f"*/{filename}"))
        return matches[-1] if matches else None

    def _daily_completion_path(
        self, provider: str, stock_id: str, start_date: str, end_date: str
    ) -> Path:
        return (
            self.processed_root / "ingestion" / self._safe_component(provider) / "daily_prices"
            / self._safe_component(stock_id)
            / f"{self._safe_date(start_date)}_{self._safe_date(end_date)}.json"
        )

    def mark_daily_prices_complete(
        self, provider: str, stock_id: str, start_date: str, end_date: str,
        *, raw_path: Path, canonical: pd.DataFrame,
    ) -> Path:
        """Record completion only after processed prices have been saved."""
        path = self._daily_completion_path(provider, stock_id, start_date, end_date)
        dates = pd.to_datetime(canonical["trade_date"]).dt.strftime("%Y-%m-%d").tolist()
        canonical_ids = canonical["stock_id"].unique().tolist()
        if len(canonical_ids) != 1:
            raise ValueError("daily price batch must contain exactly one canonical stock_id")
        self._atomic_json(
            {"provider": provider, "stock_id": stock_id,
             "canonical_stock_id": str(canonical_ids[0]),
             "start_date": start_date, "end_date": end_date,
             "raw_sha256": hash_file(raw_path), "trade_dates": sorted(dates)},
            path,
        )
        return path

    def daily_prices_completed(
        self, provider: str, stock_id: str, start_date: str, end_date: str
    ) -> bool:
        """Require the saved raw response and every completed processed date.

        Existing raw responses without a completion marker must be retried.
        A missing or malformed marker is treated as incomplete.
        """
        path = self._daily_completion_path(provider, stock_id, start_date, end_date)
        raw_path = self.find_raw_daily_prices(provider, stock_id, start_date, end_date)
        if not path.exists() or raw_path is None:
            return False
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            if record["raw_sha256"] != hash_file(raw_path):
                return False
            dates = record["trade_dates"]
            if not dates or not all(isinstance(d, str) for d in dates):
                return False
            if (record["provider"], record["stock_id"], record["start_date"],
                    record["end_date"]) != (provider, stock_id, start_date, end_date):
                return False
            stored = self.load_daily_prices(stock_id=record["canonical_stock_id"],
                                            start_date=start_date, end_date=end_date)
            available = set(pd.to_datetime(stored["trade_date"]).dt.strftime("%Y-%m-%d"))
            return set(dates).issubset(available)
        except (OSError, ValueError, KeyError, TypeError):
            return False

    # ------------------------------------------------------------- processed

    def save_stock_master(self, df: pd.DataFrame) -> Path:
        """Save canonical stock master data (single parquet file)."""
        dest = self.processed_root / "stock_master"
        dest.mkdir(parents=True, exist_ok=True)
        path = dest / "stock_master.parquet"
        return self._save_processed(df, path)

    def load_stock_master(self) -> pd.DataFrame:
        """Load canonical stock master data."""
        path = self.processed_root / "stock_master" / "stock_master.parquet"
        if not path.exists():
            raise FileNotFoundError(f"no processed stock master at {path}")
        return pd.read_parquet(path)

    def save_daily_prices(self, df: pd.DataFrame) -> list[Path]:
        """Upsert canonical daily prices by ``stock_id/year/month``.

        Preserve other days in the same month; incoming rows replace matching
        ``(stock_id, trade_date)`` rows. Single-writer operation is assumed.
        """
        result = df.copy()
        dates = pd.to_datetime(result["trade_date"], errors="coerce")
        if dates.isna().any():
            raise ValueError("daily prices require valid trade_date values")
        if result["stock_id"].isna().any():
            raise ValueError("daily prices require stock_id values")
        result["trade_date"] = dates
        result["_year"] = dates.dt.year
        result["_month"] = dates.dt.month

        paths: list[Path] = []
        groups = result.groupby(["stock_id", "_year", "_month"], sort=True)
        for (stock_id, year, month), group in groups:
            group = group.drop(columns=["_year", "_month"])
            dest = (
                self.processed_root
                / "daily_prices"
                / self._safe_component(str(stock_id))
                / f"{int(year):04d}"
                / f"{int(month):02d}"
            )
            dest.mkdir(parents=True, exist_ok=True)
            path = dest / "data.parquet"
            if path.exists():
                existing = pd.read_parquet(path)
                existing["trade_date"] = pd.to_datetime(existing["trade_date"])
                group = pd.concat([existing, group], ignore_index=True)
            group = group.drop_duplicates(["stock_id", "trade_date"], keep="last")
            group = group.sort_values(["stock_id", "trade_date"]).reset_index(drop=True)
            self._atomic_parquet(group, path)
            paths.append(path)
        if paths:
            update_data_manifest(self.processed_root, paths)
        return paths

    def load_daily_prices(
        self,
        stock_id: str | list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        """Load canonical daily prices, optionally filtered by stock/date."""
        base = self.processed_root / "daily_prices"
        if stock_id is None:
            folders = [base]
        else:
            ids = [stock_id] if isinstance(stock_id, str) else list(stock_id)
            folders = [base / self._safe_component(s) for s in ids]
        files = sorted(file for folder in folders if folder.exists()
                       for file in folder.rglob("*.parquet"))
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
        return self._save_processed(df, path)

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
        return self._save_processed(df, path)

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
        return self._save_processed(df, path)

    def load_calendar(self) -> pd.DataFrame:
        """Load the trading calendar (empty frame if not present)."""
        path = self.processed_root / "calendar" / "calendar.parquet"
        if not path.exists():
            return pd.DataFrame(columns=list(models.CALENDAR_COLUMNS))
        return pd.read_parquet(path)
