"""Data ingestion pipeline.

Flow::

    Provider -> Raw response -> Save raw -> Normalize -> Canonical
             -> Basic validation -> Save processed

The pipeline takes a provider and storage explicitly so it can be unit tested
with fakes. If they are omitted, defaults are built from ``configs/data.yaml``.
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Union

import pandas as pd

from hk_quant import get_logger
from hk_quant.data import models
from hk_quant.data.adapters.akshare import AKShareProvider
from hk_quant.data.corporate_actions import empty_corporate_actions
from hk_quant.data.quality import (
    validate_corporate_actions,
    validate_daily_prices,
    validate_stock_master,
)
from hk_quant.data.storage import DataStorage

PathLike = Union[str, os.PathLike[str]]

logger = get_logger("hk_quant.data.ingestion")

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_CONFIG_PATH = _PROJECT_ROOT / "configs" / "data.yaml"


def _run_date() -> str:
    return date.today().isoformat()


def _resolve_dir(value: str, root: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def _defaults(config_path: PathLike | None = None) -> tuple[AKShareProvider, DataStorage]:
    from hk_quant.config import load_config

    config = load_config(config_path if config_path is not None else _DEFAULT_CONFIG_PATH)
    provider_name = config.provider.primary
    if provider_name != "akshare":
        raise ValueError(f"unsupported data provider: {provider_name!r}")

    storage = DataStorage(
        raw_dir=_resolve_dir(config.storage.raw_dir, _PROJECT_ROOT),
        processed_dir=_resolve_dir(config.storage.processed_dir, _PROJECT_ROOT),
    )
    return AKShareProvider(), storage


def ingest_stock_master(
    provider: AKShareProvider | None = None,
    storage: DataStorage | None = None,
    *,
    overwrite: bool = False,
    config_path: PathLike | None = None,
) -> pd.DataFrame:
    """Download, validate and persist the stock master table.

    Returns the canonical stock master DataFrame.
    """
    if provider is None or storage is None:
        default_provider, default_storage = _defaults(config_path)
        provider = provider or default_provider
        storage = storage or default_storage

    run_date = _run_date()
    raw = provider.fetch_raw_stock_master()
    raw_path = storage.save_raw_stock_master(raw, provider.name, run_date)
    logger.info("saved raw stock master: %s", raw_path)

    canonical = provider.normalize_stock_master(raw)
    canonical = validate_stock_master(canonical)
    processed_path = storage.save_stock_master(canonical)
    logger.info("saved processed stock master: %s (rows=%d)", processed_path, len(canonical))
    return canonical


def ingest_daily_prices(
    provider: AKShareProvider | None = None,
    storage: DataStorage | None = None,
    *,
    stock_ids: list[str],
    start_date: str,
    end_date: str,
    overwrite: bool = False,
    config_path: PathLike | None = None,
) -> pd.DataFrame:
    """Download, validate and persist daily prices for the given stocks/range.

    Completed processed ranges are skipped unless ``overwrite=True``. A raw
    response left by a failed normalization/write is reused on the next run.
    """
    if provider is None or storage is None:
        default_provider, default_storage = _defaults(config_path)
        provider = provider or default_provider
        storage = storage or default_storage

    run_date = _run_date()
    frames: list[pd.DataFrame] = []
    for stock_id in stock_ids:
        if not overwrite and storage.daily_prices_completed(
            provider.name, stock_id, start_date, end_date
        ):
            logger.info("skip %s (%s..%s): already ingested", stock_id, start_date, end_date)
            continue

        raw_path = None if overwrite else storage.find_raw_daily_prices(
            provider.name, stock_id, start_date, end_date
        )
        if raw_path is not None:
            try:
                raw = pd.read_parquet(raw_path)
            except (OSError, ValueError):
                logger.warning("unreadable saved raw prices %s; refetching", raw_path)
                raw_path = None
        if raw_path is None:
            raw = provider.fetch_raw_daily_prices([stock_id], start_date, end_date)
        if raw.empty:
            logger.warning("no data for %s (%s..%s)", stock_id, start_date, end_date)
            continue

        if raw_path is None:
            raw_path = storage.save_raw_daily_prices(
                raw, provider.name, run_date, stock_id, start_date, end_date
            )
            logger.info("saved raw daily prices: %s", raw_path)

        canonical = provider.normalize_daily_prices(raw, stock_id)
        canonical = validate_daily_prices(canonical)
        storage.save_daily_prices(canonical)
        storage.mark_daily_prices_complete(
            provider.name, stock_id, start_date, end_date,
            raw_path=raw_path, canonical=canonical,
        )
        logger.info("saved processed daily prices for %s (rows=%d)", stock_id, len(canonical))
        frames.append(canonical)

    if frames:
        return pd.concat(frames, ignore_index=True)
    return pd.DataFrame(columns=list(models.DAILY_PRICE_COLUMNS))


def ingest_corporate_actions(
    provider: AKShareProvider | None = None,
    storage: DataStorage | None = None,
    *,
    stock_ids: list[str],
    overwrite: bool = False,
    config_path: PathLike | None = None,
) -> pd.DataFrame:
    """Download, validate and persist corporate actions for the given stocks.

    Newly fetched actions are merged into the existing processed table and
    deduplicated on ``(stock_id, event_date, action_type, announcement_date)``.
    """
    if provider is None or storage is None:
        default_provider, default_storage = _defaults(config_path)
        provider = provider or default_provider
        storage = storage or default_storage

    run_date = _run_date()
    fetched: list[pd.DataFrame] = []
    for stock_id in stock_ids:
        raw = provider.fetch_raw_corporate_actions(stock_id)
        if raw.empty:
            logger.warning("no corporate actions for %s", stock_id)
            continue

        raw_path = storage.save_raw_corporate_actions(
            raw, provider.name, run_date, stock_id
        )
        logger.info("saved raw corporate actions: %s", raw_path)

        canonical = provider.normalize_corporate_actions(raw)
        canonical = validate_corporate_actions(canonical)
        fetched.append(canonical)

    if not fetched:
        return empty_corporate_actions()

    combined = pd.concat(fetched, ignore_index=True)
    existing = storage.load_corporate_actions()
    if not existing.empty:
        combined = pd.concat([existing, combined], ignore_index=True)
        # Two distinct distributions can share the same (stock, event date,
        # action type, announcement date) with different cash/factor, so the
        # economic terms are part of the identity key.
        combined = combined.drop_duplicates(
            subset=["stock_id", "event_date", "action_type", "announcement_date",
                    "cash_amount", "factor"],
            keep="last",
        )

    combined = combined.sort_values(["stock_id", "event_date"]).reset_index(drop=True)
    path = storage.save_corporate_actions(combined)
    logger.info("saved processed corporate actions: %s (rows=%d)", path, len(combined))
    return combined
