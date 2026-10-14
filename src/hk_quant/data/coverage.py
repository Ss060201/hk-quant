"""Observed dataset coverage, with explicit limits on what can be inferred.

Counts describe stored rows, never an external provider's completeness.
They help decide whether a research question is supported before execution.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd


def _available(df: pd.DataFrame, column: str) -> int:
    return int(df[column].notna().sum()) if column in df else 0


def _date_bounds(df: pd.DataFrame, column: str) -> tuple[str | None, str | None]:
    if column not in df or df.empty:
        return None, None
    dates = pd.to_datetime(df[column], errors="coerce").dropna()
    if dates.empty:
        return None, None
    return dates.min().date().isoformat(), dates.max().date().isoformat()


def report_data_coverage(repository: Any) -> dict[str, Any]:
    """Return a JSON-ready report from the repository's currently stored data.

    This is a deliberate one-off inspection (it loads price rows to count
    coverage). It is not designed for a per-signal hot path.
    """
    prices = repository.get_daily_prices()
    master = repository.get_stock_master()
    actions = repository.get_corporate_actions()
    fundamentals = repository.get_fundamentals()
    start, end = _date_bounds(prices, "trade_date")
    calendar_path = repository.processed_root / "calendar" / "calendar.parquet"
    calendar_mode = "stored" if calendar_path.exists() else (
        "observed" if not prices.empty else "unavailable"
    )
    result: dict[str, Any] = {
        "data_version": repository.get_data_version(),
        "daily_prices": {
            "row_count": len(prices),
            "stock_count": int(prices["stock_id"].nunique()) if "stock_id" in prices else 0,
            "start_date": start, "end_date": end,
            "turnover_rate_nonnull": _available(prices, "turnover_rate"),
            "amount_nonnull": _available(prices, "amount"),
        },
        "stock_master": {
            "row_count": len(master),
            "listing_date_nonnull": _available(master, "listing_date"),
            "delisting_date_nonnull": _available(master, "delisting_date"),
        },
        "corporate_actions": {
            "row_count": len(actions),
            "announcement_date_nonnull": _available(actions, "announcement_date"),
            "action_types": (
                {str(k): int(v) for k, v in actions["action_type"].value_counts().items()}
                if "action_type" in actions else {}
            ),
        },
        "fundamentals": {
            "row_count": len(fundamentals),
            "announcement_date_nonnull": _available(fundamentals, "announcement_date"),
        },
        "calendar": {"mode": calendar_mode},
        "limitations": [],
    }
    limitations = result["limitations"]
    if prices.empty:
        limitations.append("No processed daily prices are available.")
    if result["daily_prices"]["turnover_rate_nonnull"] == 0:
        limitations.append("Turnover rate is unavailable; amount is not turnover rate.")
    if result["stock_master"]["listing_date_nonnull"] == 0:
        limitations.append("Historical listing dates are unavailable; observed stocks are not a historical universe.")
    if calendar_mode == "observed":
        limitations.append("Calendar is derived from observed prices, not an authoritative exchange calendar.")
    if calendar_mode == "stored":
        limitations.append("Stored calendar source has not been verified by this report.")
    if actions.empty:
        limitations.append("No corporate actions are available; split-adjusted price history cannot be verified.")
    else:
        limitations.append("Recorded corporate actions do not prove complete split, bonus or rights coverage.")
    if not actions.empty and "announcement_date" in actions and "event_date" in actions:
        announced = pd.to_datetime(actions["announcement_date"], errors="coerce")
        effective = pd.to_datetime(actions["event_date"], errors="coerce")
        if (announced.notna() & effective.notna() & (announced > effective)).any():
            limitations.append(
                "Some corporate actions have announcement_date after event_date; "
                "those announcement dates are not verified point-in-time dates."
            )
    if fundamentals.empty:
        limitations.append("Point-in-time fundamentals are unavailable.")
    return result


def write_coverage_report(report: dict[str, Any], path: str | os.PathLike[str]) -> Path:
    """Write a coverage inspection atomically for a versioned research run."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".coverage-", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2, ensure_ascii=False)
        os.replace(name, target)
    finally:
        Path(name).unlink(missing_ok=True)
    return target
