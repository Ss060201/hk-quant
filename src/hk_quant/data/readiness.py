"""Conservative coverage check for an explicitly selected research cohort."""

from __future__ import annotations

import pandas as pd


def assess_price_panel(
    prices: pd.DataFrame, stock_ids: list[str], start_date: str, end_date: str,
    *, min_sessions: int = 252, min_coverage: float = 0.8,
) -> dict:
    """Compare each stock with observed sessions; this is not an HKEX calendar.

    Missing bars may mean a suspension or missing provider data. Neither can
    be filled by inventing a price, so both remain visible in the report.
    """
    if len(stock_ids) < 2 or len(stock_ids) != len(set(stock_ids)):
        raise ValueError("select at least two distinct stock IDs")
    if not 0 < min_coverage <= 1 or min_sessions < 1:
        raise ValueError("min_coverage must be (0,1] and min_sessions positive")
    start, end = pd.Timestamp(start_date), pd.Timestamp(end_date)
    if start > end:
        raise ValueError("start_date must not exceed end_date")
    required = {"stock_id", "trade_date", "open", "high", "low", "close", "volume", "amount"}
    if not required.issubset(prices.columns):
        raise ValueError(f"daily prices missing columns: {sorted(required - set(prices.columns))}")
    frame = prices[prices["stock_id"].isin(stock_ids)].copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="coerce")
    if frame["trade_date"].isna().any():
        raise ValueError("daily prices contain invalid trade dates")
    frame = frame[frame["trade_date"].between(start, end)]
    dates = set(frame["trade_date"])
    rows = []
    for stock_id in stock_ids:
        subset = frame[frame["stock_id"] == stock_id]
        observed = set(subset["trade_date"])
        missing = sorted(dates - observed)
        count = len(observed)
        coverage = count / len(dates) if dates else 0.0
        duplicates = int(subset.duplicated(["stock_id", "trade_date"]).sum())
        bad_values = int(subset[["open", "high", "low", "close", "volume", "amount"]].isna().any(axis=1).sum())
        rows.append({
            "stock_id": stock_id, "sessions": count,
            "observed_session_coverage": round(coverage, 4),
            "missing_observed_dates": [day.date().isoformat() for day in missing],
            "duplicate_rows": duplicates, "null_price_rows": bad_values,
            "ready": count >= min_sessions and coverage >= min_coverage and not duplicates and not bad_values,
        })
    return {
        "status": "READY_FOR_EXPLORATORY_VALIDATION" if all(row["ready"] for row in rows) else "BLOCKED",
        "start_date": start.date().isoformat(), "end_date": end.date().isoformat(),
        "observed_sessions": len(dates), "stocks": rows,
        "min_sessions": min_sessions, "min_coverage": min_coverage,
        "limitations": [
            "Dates are observed across this cohort, not an official exchange calendar.",
            "This is an explicitly selected cohort, not a historical listing/delisting-aware universe.",
            "Missing dates may be suspensions or missing data and require inspection.",
        ],
    }
