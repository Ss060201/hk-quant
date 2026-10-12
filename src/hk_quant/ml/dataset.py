"""Build one conditional failure label while keeping future values out of features."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

import numpy as np
import pandas as pd

from hk_quant.ml.models import (
    ConditionalDataset,
    HORIZON_TRADING_DAYS,
    LOSS_THRESHOLD,
)

_TARGET_NAMES = {"label", "target", "future_return", "forward_return", "exit_date",
                 "label_period_end", "outcome"}


def _required(frame: pd.DataFrame, name: str, columns: set[str]) -> None:
    missing = columns.difference(frame.columns)
    if missing:
        raise ValueError(f"{name} missing required columns: {sorted(missing)}")


def build_conditional_dataset(
    signals: pd.DataFrame,
    features: pd.DataFrame,
    raw_prices: pd.DataFrame,
    *,
    strategy_id: str,
    strategy_version: str,
    data_version: str | None,
    feature_source: str,
    feature_columns: Sequence[str],
) -> ConditionalDataset:
    """Label BUY signals where raw close(T+20)/raw close(T)-1 < -0.05.

    Input raw_prices must be UNADJUSTED stock/date/close; corporate actions
    and dividends remain outside this limited price-return label. A distinct
    `available_at` on each feature row is mandatory; snapshots released after
    the signal date are never joined. Trading dates come from the observed
    price panel and must not be mistaken for an official exchange calendar.
    Feature producers must separately guarantee that their input data was
    available by `available_at`; this builder cannot certify external inputs.
    """
    if not strategy_id or not strategy_version or not feature_source:
        raise ValueError("strategy_id, strategy_version and feature_source are required")
    selected = tuple(feature_columns)
    if not selected or len(set(selected)) != len(selected):
        raise ValueError("feature_columns must be nonempty and unique")
    if any(column.lower() in _TARGET_NAMES or column.startswith(("future_", "forward_", "label_"))
           for column in selected):
        raise ValueError("future/label/outcome fields cannot be features")
    _required(signals, "signals", {"stock_id", "signal_date", "signal"})
    _required(features, "features", {"stock_id", "available_at", *selected})
    _required(raw_prices, "raw_prices", {"stock_id", "trade_date", "close"})
    if signals.empty:
        return ConditionalDataset(pd.DataFrame(), selected, strategy_id, strategy_version,
                                  data_version, feature_source, {"no_buy_signals": 0},
                                  ["No strategy signals provided; real-data model evaluation BLOCKED."])
    sig = signals.copy()
    sig["signal_date"] = pd.to_datetime(sig.signal_date, errors="raise").dt.normalize()
    feat = features.copy()
    feat["available_at"] = pd.to_datetime(feat.available_at, errors="raise").dt.normalize()
    prices = raw_prices.copy()
    prices["trade_date"] = pd.to_datetime(prices.trade_date, errors="raise").dt.normalize()
    for name, frame, date_column in [("signals", sig, "signal_date"),
                                     ("features", feat, "available_at"),
                                     ("raw_prices", prices, "trade_date")]:
        if frame[date_column].isna().any() or frame.stock_id.isna().any():
            raise ValueError(f"{name} contains null identity/date")
    if sig.duplicated(["stock_id", "signal_date"]).any():
        raise ValueError("duplicate signal stock/date would double count samples")
    if feat.duplicated(["stock_id", "available_at"]).any():
        raise ValueError("duplicate feature snapshot stock/available_at")
    if prices.duplicated(["stock_id", "trade_date"]).any():
        raise ValueError("duplicate raw price stock/date")
    if not sig.signal.isin(["BUY", "SELL", "HOLD"]).all():
        raise ValueError("signal must be BUY, SELL or HOLD")
    if {"strategy_id", "strategy_version"}.issubset(sig.columns):
        if (sig.strategy_id != strategy_id).any() or (sig.strategy_version != strategy_version).any():
            raise ValueError("mixed strategy versions are not allowed")
    elif "strategy_id" in sig.columns or "strategy_version" in sig.columns:
        raise ValueError("signal strategy provenance requires both id and version")
    if "status" in sig.columns and not sig.loc[sig.signal == "BUY", "status"].isin(["VALID"]).all():
        raise ValueError("non-VALID BUY signals cannot enter a conditional outcome dataset")
    for column in selected:
        if not pd.api.types.is_numeric_dtype(feat[column]):
            raise ValueError(f"feature {column} must be numeric")
        feat[column] = pd.to_numeric(feat[column], errors="coerce").replace([np.inf, -np.inf], np.nan)
    prices["close"] = pd.to_numeric(prices.close, errors="coerce")
    if (~np.isfinite(prices.close)).any() or (prices.close <= 0).any():
        raise ValueError("raw prices must have finite positive close")
    dates = sorted(prices.trade_date.unique())
    date_idx = {date: i for i, date in enumerate(dates)}
    close = {(stock, date): float(value)
             for stock, date, value in prices[["stock_id", "trade_date", "close"]].itertuples(index=False, name=None)}
    grouped_features = {stock: group.sort_values("available_at")
                        for stock, group in feat.groupby("stock_id")}
    discarded: Counter[str] = Counter()
    records: list[dict] = []
    for signal in sig.loc[sig.signal == "BUY"].itertuples(index=False):
        stock, signal_date = signal.stock_id, signal.signal_date
        start_idx = date_idx.get(signal_date)
        if start_idx is None or close.get((stock, signal_date)) is None:
            discarded["missing_entry_price"] += 1
            continue
        if start_idx + HORIZON_TRADING_DAYS >= len(dates):
            discarded["future_horizon_unavailable"] += 1
            continue
        end = dates[start_idx + HORIZON_TRADING_DAYS]
        if (stock, end) not in close:
            discarded["missing_exit_price"] += 1
            continue
        stock_features = grouped_features.get(stock)
        if stock_features is None:
            discarded["no_as_of_features"] += 1
            continue
        available = stock_features.loc[stock_features.available_at <= signal_date]
        if available.empty:
            discarded["no_as_of_features"] += 1
            continue
        feature = available.iloc[-1]
        future_return = close[(stock, end)] / close[(stock, signal_date)] - 1.0
        records.append({
            "stock_id": stock, "signal_date": signal_date,
            "strategy_id": strategy_id, "strategy_version": strategy_version,
            "features_as_of": feature.available_at,
            "label_period_start": signal_date, "label_period_end": end,
            "label": int(future_return < LOSS_THRESHOLD),
            "future_return": future_return, "data_version": data_version,
            **{column: feature[column] for column in selected},
        })
    discarded["no_buy_signals"] = int((sig.signal != "BUY").sum())
    warnings = ["Observed trading dates are derived from input prices, not an official HKEX calendar.",
                "Raw price-return label excludes dividends and can be distorted by corporate actions.",
                "Feature as-of timestamps are supplied by the caller; audit upstream feature computation for PIT correctness."]
    if not data_version:
        warnings.append("Data version unavailable; provenance is incomplete.")
    if discarded["future_horizon_unavailable"] or discarded["missing_exit_price"]:
        warnings.append("Unlabelled recent or suspended BUY signals are excluded, not assigned a guessed outcome.")
    if not records:
        warnings.append("No complete real labelled signals; model evaluation BLOCKED.")
    return ConditionalDataset(pd.DataFrame.from_records(records), selected, strategy_id,
                              strategy_version, data_version, feature_source,
                              dict(discarded), warnings)
