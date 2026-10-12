"""Historical risk metrics calculated only from data dated on/before analysis day.

Volatility is sample std of simple daily returns times sqrt(annualization).
Downside volatility is sqrt(mean(min(return, 0)^2)) times sqrt(annualization),
using a zero daily target and *all* valid observations in its denominator.
Drawdown uses each observed equity's highest prior observed equity, including
the initial equity when provided. Values are fractions, not percentages.
No metric in this module is a prediction or a buy/sell recommendation.
"""

from __future__ import annotations

from collections.abc import Sequence
from math import sqrt

import numpy as np
import pandas as pd

from hk_quant.risk.models import RiskResult


def _dated(frame: pd.DataFrame, date_col: str, as_of: pd.Timestamp) -> pd.DataFrame:
    if date_col not in frame:
        raise ValueError(f"missing required date column {date_col}")
    result = frame.copy()
    result[date_col] = pd.to_datetime(result[date_col], errors="raise").dt.normalize()
    if result[date_col].isna().any():
        raise ValueError(f"null {date_col} is not allowed")
    return result.loc[result[date_col] <= as_of].copy()


def _number(series: pd.Series) -> pd.Series:
    value = pd.to_numeric(series, errors="coerce")
    return value.where(np.isfinite(value))


def _drawdown(equity: pd.Series, initial_equity: float | None = None) -> float | None:
    clean = _number(equity).dropna()
    if initial_equity is not None:
        clean = pd.concat([pd.Series([initial_equity]), clean], ignore_index=True)
    if clean.empty or (clean <= 0).any():
        return None
    return float((clean / clean.cummax() - 1.0).min())


def _volatility(returns: pd.Series, annualization: int) -> float | None:
    clean = _number(returns).dropna()
    if len(clean) < 2:
        return None
    return float(clean.std(ddof=1) * sqrt(annualization))


def _downside(returns: pd.Series, annualization: int) -> float | None:
    clean = _number(returns).dropna()
    if clean.empty:
        return None
    return float(sqrt(float(np.mean(np.minimum(clean.to_numpy(), 0.0) ** 2)) * annualization))


def _loss_streak(returns: pd.Series) -> int:
    longest = current = 0
    for value in _number(returns):
        current = current + 1 if pd.notna(value) and value < 0 else 0
        longest = max(longest, current)
    return longest


def _validated_weights(positions: pd.DataFrame | None, as_of: pd.Timestamp, warnings: list[str]) -> pd.DataFrame:
    if positions is None or positions.empty:
        warnings.append("Position weights unavailable; concentration and exposures are unavailable.")
        return pd.DataFrame(columns=["stock_id", "weight"])
    held = _dated(positions, "trade_date", as_of)
    if held.empty:
        warnings.append("No position snapshot on or before analysis date.")
        return pd.DataFrame(columns=["stock_id", "weight"])
    if not {"stock_id", "weight"}.issubset(held.columns):
        raise ValueError("positions require stock_id, trade_date and weight")
    held = held.loc[held.trade_date == held.trade_date.max()].copy()
    if held.stock_id.duplicated().any():
        raise ValueError("duplicate stock_id in most recent position snapshot")
    held["weight"] = _number(held.weight)
    if held.weight.isna().any() or (held.weight < 0).any() or held.weight.sum() > 1.0000001:
        raise ValueError("long-only weights must be finite, nonnegative and sum to <= 1")
    return held.loc[held.weight > 0, ["stock_id", "weight"]]


def analyze_risk(
    stock_prices: pd.DataFrame,
    *,
    as_of_date: str,
    data_version: str | None,
    strategy_version: str | None = None,
    strategy_id: str | None = None,
    portfolio_daily: pd.DataFrame | None = None,
    positions: pd.DataFrame | None = None,
    attributes: pd.DataFrame | None = None,
    attribute_source: str | None = None,
    annualization: int = 252,
    window: int = 252,
    extra_cost_bps: Sequence[float] = (0.0, 10.0, 25.0),
    initial_equity: float | None = None,
) -> RiskResult:
    """Describe observed risk at *as_of_date*, without projecting future prices.

    stock_prices must contain stock_id/trade_date/close and may contain
    open/amount. amount is traded value, *not* turnover_rate. portfolio_daily
    must contain trade_date/equity and may contain daily_return/turnover, the
    latter measured as traded notional divided by portfolio equity. positions
    is a daily snapshot with stock_id/trade_date/weight (weights include no
    cash). attributes, if supplied, has stock_id/available_at/sector and/or
    numeric factor_* columns; attribute_source is mandatory so this data can
    be traced. Missing metrics are None, never imputed.
    """
    as_of = pd.Timestamp(as_of_date).normalize()
    if pd.isna(as_of) or annualization <= 0 or window < 2:
        raise ValueError("as_of_date, annualization or window is invalid")
    if initial_equity is not None and (not np.isfinite(initial_equity) or initial_equity <= 0):
        raise ValueError("initial_equity must be positive and finite")
    if any(not np.isfinite(bps) or bps < 0 for bps in extra_cost_bps):
        raise ValueError("extra_cost_bps must contain finite nonnegative values")
    if not {"stock_id", "trade_date", "close"}.issubset(stock_prices.columns):
        raise ValueError("stock_prices require stock_id, trade_date and close")
    warnings: list[str] = []
    if not data_version:
        warnings.append("Data version unavailable; results cannot be reproduced from metadata alone.")
    prices = _dated(stock_prices, "trade_date", as_of).sort_values(["stock_id", "trade_date"])
    if prices.duplicated(["stock_id", "trade_date"]).any():
        raise ValueError("duplicate stock/date price rows")
    prices["close"] = _number(prices.close)
    if prices.close.isna().any() or (prices.close <= 0).any():
        raise ValueError("close prices must be positive and finite")
    prices["daily_return"] = prices.groupby("stock_id").close.pct_change(fill_method=None)
    records: list[dict] = []
    for stock_id, full in prices.groupby("stock_id", sort=True):
        rows = full.tail(window + 1).copy()  # window daily returns need window+1 closes
        returns = rows.daily_return.tail(window).dropna()
        if len(returns) < 2:
            warnings.append(f"{stock_id}: insufficient returns for sample volatility.")
        open_gap: float | None = None
        if "open" in rows:
            opening = _number(rows.open)
            gaps = opening / rows.close.shift(1) - 1.0
            valid_gaps = gaps.replace([np.inf, -np.inf], np.nan).dropna()
            if not valid_gaps.empty:
                open_gap = float(min(0.0, valid_gaps.min()))
        median_amount: float | None = None
        if "amount" in rows:
            amount = _number(rows.amount).dropna()
            if not amount.empty:
                median_amount = float(amount.median())
        records.append({
            "stock_id": stock_id,
            "last_trade_date": rows.trade_date.iloc[-1].date().isoformat(),
            "observations": len(returns),
            "historical_volatility": _volatility(returns, annualization),
            "downside_volatility": _downside(returns, annualization),
            "worst_daily_return": float(returns.min()) if len(returns) else None,
            "worst_overnight_gap": open_gap,
            "median_daily_traded_amount": median_amount,
        })
    stock_metrics = pd.DataFrame.from_records(records)
    wide = prices.pivot(index="trade_date", columns="stock_id", values="daily_return")
    correlations: list[dict] = []
    for i, first in enumerate(wide.columns):
        for second in wide.columns[i + 1:]:
            pair = wide[[first, second]].dropna().tail(window)
            corr = (float(pair.iloc[:, 0].corr(pair.iloc[:, 1]))
                    if len(pair) >= 2 and pair.iloc[:, 0].nunique() > 1
                    and pair.iloc[:, 1].nunique() > 1 else np.nan)
            correlations.append({"stock_a": first, "stock_b": second,
                                 "observations": len(pair), "correlation": corr if np.isfinite(corr) else None})

    held = _validated_weights(positions, as_of, warnings)
    portfolio: dict = {"concentration_hhi": None, "largest_position_weight": None,
                       "sector_exposure": None, "factor_exposure": None,
                       "historical_volatility": None, "max_drawdown": None,
                       "drawdown_contribution": None}
    if not held.empty:
        portfolio["concentration_hhi"] = float((held.weight ** 2).sum())
        portfolio["largest_position_weight"] = float(held.weight.max())
    if attributes is not None and not attributes.empty:
        if not attribute_source or not {"stock_id", "available_at"}.issubset(attributes.columns):
            raise ValueError("attributes require stock_id, available_at and attribute_source")
        attr = _dated(attributes, "available_at", as_of).sort_values("available_at")
        attr = attr.drop_duplicates("stock_id", keep="last")
        merged = held.merge(attr, on="stock_id", how="left")
        if "sector" in merged and not merged.sector.isna().all():
            portfolio["sector_exposure"] = merged.dropna(subset=["sector"]).groupby("sector").weight.sum().to_dict()
            if merged.sector.isna().any():
                warnings.append("Sector classifications missing for some held stocks; sector exposure is partial.")
        factors = [column for column in merged if column.startswith("factor_")]
        if factors:
            exposures: dict[str, float] = {}
            for factor in factors:
                value = _number(merged[factor])
                if value.notna().all() and not value.empty:
                    exposures[factor] = float((merged.weight * value).sum())
            portfolio["factor_exposure"] = exposures or None
    if portfolio["sector_exposure"] is None:
        warnings.append("Sector exposure unavailable without dated sector classifications.")
    if portfolio["factor_exposure"] is None:
        warnings.append("Factor exposure unavailable without dated factor attributes.")
    warnings.append("Drawdown contribution unavailable without daily pre-return position weights.")

    strategy: dict = {"max_drawdown": None, "longest_loss_streak": None,
                      "positive_month_fraction": None, "cost_sensitivity": None}
    if portfolio_daily is not None and not portfolio_daily.empty:
        daily = _dated(portfolio_daily, "trade_date", as_of).sort_values("trade_date").tail(window + 1)
        if daily.trade_date.duplicated().any():
            raise ValueError("duplicate portfolio dates")
        if "equity" not in daily:
            raise ValueError("portfolio_daily requires equity")
        equity = _number(daily.equity)
        if equity.isna().any() or (equity <= 0).any():
            raise ValueError("portfolio equity must be positive and finite")
        daily["computed_return"] = equity.pct_change(fill_method=None)
        if initial_equity is not None:
            daily.loc[daily.index[0], "computed_return"] = equity.iloc[0] / initial_equity - 1.0
        returns = daily.computed_return.dropna().tail(window)
        strategy["max_drawdown"] = _drawdown(equity, initial_equity)
        strategy["longest_loss_streak"] = _loss_streak(returns)
        month_end = daily.set_index("trade_date").equity.resample("ME").last()
        monthly = month_end.pct_change(fill_method=None).dropna()
        if not monthly.empty:
            strategy["positive_month_fraction"] = float((monthly > 0).mean())
        portfolio["historical_volatility"] = _volatility(returns, annualization)
        portfolio["max_drawdown"] = strategy["max_drawdown"]
        if "turnover" in daily:
            traded = _number(daily.turnover)
            if traded.isna().any() or (traded < 0).any():
                warnings.append("Invalid or missing turnover; cost sensitivity unavailable.")
            else:
                strategy["cost_sensitivity"] = {
                    str(float(bps)): float(((1 + daily.computed_return.fillna(0) - traded * bps / 10_000).prod() - 1))
                    for bps in extra_cost_bps
                }
        else:
            warnings.append("Portfolio turnover unavailable; cost sensitivity unavailable.")
    else:
        warnings.append("Backtest daily equity unavailable; strategy and portfolio path risk unavailable.")

    return RiskResult(
        as_of_date=as_of.date().isoformat(), data_version=data_version,
        strategy_version=strategy_version, strategy_id=strategy_id,
        parameters={"annualization": annualization, "window_trading_observations": window,
                    "daily_return": "close_to_close_simple", "volatility": "sample_ddof_1",
                    "downside_target": 0.0, "extra_cost_bps": list(extra_cost_bps),
                    "attribute_source": attribute_source, "initial_equity": initial_equity,
                    "missing": "no_imputation"},
        stock_metrics=stock_metrics, strategy_metrics=strategy,
        portfolio_metrics=portfolio, correlations=pd.DataFrame.from_records(correlations),
        warnings=warnings,
    )
