"""Factor engine: compute factor values from historical prices.

Factor values are point-in-time: the value at date ``T`` only uses closes at
``T`` and earlier trading days.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Sequence, Union

import pandas as pd

from hk_quant.factors.models import FactorDefinition
from hk_quant.factors.registry import DEFAULT_REGISTRY, FactorRegistry

PathLike = Union[str, os.PathLike[str]]

FACTOR_RESULT_COLUMNS: tuple[str, ...] = (
    "stock_id",
    "trade_date",
    "factor_id",
    "factor_version",
    "value",
)


class FactorEngine:
    def __init__(
        self,
        repository: Any,
        registry: FactorRegistry | None = None,
        cache_dir: PathLike | None = None,
    ) -> None:
        self.repository = repository
        self.registry = registry or DEFAULT_REGISTRY
        self.cache_dir = Path(cache_dir) if cache_dir is not None else None

    def calculate(
        self,
        factor_id: str,
        date: object,
        stock_ids: Sequence[str] | None = None,
        *,
        adjusted: bool = False,
    ) -> pd.DataFrame:
        definition = self.registry.get(factor_id)
        calculator = self.registry.get_calculator(factor_id)
        signal_date = pd.Timestamp(date).date()

        cached = self._load_cache(factor_id, definition.version, signal_date, stock_ids)
        if cached is not None:
            return cached

        window = int(definition.parameters.get("window", 20))
        start = (
            pd.Timestamp(signal_date) - pd.Timedelta(days=max(window * 3, 30))
        ).date().isoformat()

        prices = self.repository.get_prices(
            stock_ids=stock_ids,
            start_date=start,
            end_date=signal_date.isoformat(),
            adjusted=adjusted,
        )
        if prices.empty:
            return pd.DataFrame(columns=list(FACTOR_RESULT_COLUMNS))

        rows: list[dict] = []
        for stock_id, group in prices.groupby("stock_id"):
            group = group.sort_values("trade_date").drop_duplicates(
                subset=["trade_date"], keep="last"
            )
            close = group["close"].astype("float64").dropna()
            value = calculator(close)
            rows.append(
                {
                    "stock_id": stock_id,
                    "trade_date": signal_date,
                    "factor_id": factor_id,
                    "factor_version": definition.version,
                    "value": value,
                }
            )

        result = pd.DataFrame(rows, columns=list(FACTOR_RESULT_COLUMNS))
        if self.cache_dir is not None:
            self._save_cache(result, factor_id, definition.version, signal_date)
        return result

    def _cache_path(self, factor_id: str, version: str, signal_date: object) -> Path:
        assert self.cache_dir is not None
        day = pd.Timestamp(signal_date).date().isoformat()
        return self.cache_dir / factor_id / f"v{version}" / f"{day}.parquet"

    def _load_cache(
        self, factor_id: str, version: str, signal_date: object, stock_ids: Any
    ) -> pd.DataFrame | None:
        if self.cache_dir is None:
            return None
        path = self._cache_path(factor_id, version, signal_date)
        if not path.exists():
            return None
        df = pd.read_parquet(path)
        if stock_ids is not None:
            ids = [stock_ids] if isinstance(stock_ids, str) else list(stock_ids)
            df = df[df["stock_id"].isin(ids)]
        return df.reset_index(drop=True)

    def _save_cache(
        self, df: pd.DataFrame, factor_id: str, version: str, signal_date: object
    ) -> None:
        path = self._cache_path(factor_id, version, signal_date)
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path, index=False)


def calculate_factor(
    factor_id: str,
    date: object,
    stock_ids: Sequence[str] | None = None,
    repository: Any | None = None,
    cache_dir: PathLike | None = None,
    *,
    adjusted: bool = False,
) -> pd.DataFrame:
    """Calculate a factor value for the given date (module-level helper)."""
    if repository is None:
        raise ValueError("repository is required to calculate a factor")
    engine = FactorEngine(repository, DEFAULT_REGISTRY, cache_dir=cache_dir)
    return engine.calculate(factor_id, date, stock_ids=stock_ids, adjusted=adjusted)
