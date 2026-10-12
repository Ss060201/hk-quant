"""Raw vs adjusted price handling.

Adjusted research prices are derived in-house::

    Raw price + corporate actions -> adjusted price

We never treat a provider's "adjusted close" as the adjustment framework.
Dividends are NOT applied to prices here; they are kept as ``cash_amount``
on the corporate action for later total-return work.
"""

from __future__ import annotations

import pandas as pd

from hk_quant.data import models

#: Action types that change the share count and therefore adjust prices.
PRICE_ADJUSTING_ACTIONS: tuple[str, ...] = (models.ACTION_SPLIT, models.ACTION_BONUS)

_OHLC: tuple[str, ...] = ("open", "high", "low", "close")


def adjust_prices(
    raw_prices: pd.DataFrame, actions: pd.DataFrame, *, as_of_date: object | None = None
) -> pd.DataFrame:
    """Adjust raw OHLC prices for split/bonus actions.

    ``factor`` semantics: multiplicative effect on share count
    (2-for-1 split -> 2.0; 1 bonus share per 10 held -> 1.1).

    Historical prices *before* an event are divided by the cumulative factor
    of all later events, so the whole series is expressed on the latest share
    basis. Prices on/after an event are unchanged.

    When ``as_of_date`` is supplied, only actions both publicly announced
    and effective by that day may change the price basis. Null announcement
    dates are excluded: their first knowable date cannot be established.
    Without ``as_of_date``, this helper produces a retrospective series;
    callers generating historical signals must pass their decision date.
    """
    result = raw_prices.copy()
    if actions is None or actions.empty:
        return result

    price_actions = actions[actions["action_type"].isin(PRICE_ADJUSTING_ACTIONS)].copy()
    if price_actions.empty:
        return result

    price_actions["event_date"] = pd.to_datetime(price_actions["event_date"], errors="coerce")
    price_actions = price_actions.dropna(subset=["event_date", "factor"])
    if as_of_date is not None:
        cutoff = pd.Timestamp(as_of_date)
        if pd.isna(cutoff):
            raise ValueError(f"invalid as_of_date: {as_of_date!r}")
        cutoff = cutoff.tz_localize(None) if cutoff.tzinfo is not None else cutoff
        if "announcement_date" not in price_actions:
            raise ValueError("corporate actions require announcement_date for as-of adjustment")
        announced = pd.to_datetime(price_actions["announcement_date"], errors="coerce")
        price_actions = price_actions[(announced.notna()) & (announced <= cutoff)
                                      & (price_actions["event_date"] <= cutoff)]

    for stock_id in result["stock_id"].unique():
        stock_mask = result["stock_id"] == stock_id
        dates = pd.to_datetime(result.loc[stock_mask, "trade_date"])
        events = price_actions[price_actions["stock_id"] == stock_id].sort_values("event_date")

        factors = pd.Series(1.0, index=dates.index)
        for event_date, factor in zip(events["event_date"], events["factor"]):
            factors[dates < event_date] *= float(factor)

        for col in _OHLC:
            result.loc[stock_mask, col] = result.loc[stock_mask, col] / factors.values

    return result
