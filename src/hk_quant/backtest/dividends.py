"""Cash dividend cash flows for simple holdings.

Price return excludes dividends (``adjust_prices`` never folds ``cash_amount``
into prices), so a total-return view must add dividend cash separately. This
module provides that small, deterministic piece. Shares distributed in another
issuer (``distribution_in_kind``) are NOT valued here; they must stay blocked
until a reliable valuation/tradable price exists.
"""

from __future__ import annotations

import pandas as pd

from hk_quant.data import models


def dividend_cash_flows(
    holdings: list[dict],
    actions: pd.DataFrame,
) -> pd.DataFrame:
    """Compute cash dividends received by simple buy-and-hold positions.

    ``holdings``: list of ``{"stock_id", "shares", "entry_date", "exit_date"}``
    where ``exit_date`` is ``None`` if still held. A holding receives
    ``cash_amount * shares`` on every ex-date within ``[entry_date, exit_date)``.

    ``actions``: canonical corporate actions (``event_date`` is the ex-date).
    Returns a DataFrame with one row per (holding, ex-date) cash flow.
    """
    rows: list[dict] = []
    for holding in holdings:
        stock_id = holding["stock_id"]
        shares = float(holding["shares"])
        entry = pd.Timestamp(holding["entry_date"])
        exit_ = pd.Timestamp(holding["exit_date"]) if holding.get("exit_date") else None

        dividends = actions[
            (actions["stock_id"] == stock_id)
            & (actions["action_type"] == models.ACTION_DIVIDEND)
            & (actions["cash_amount"].notna())
        ]
        for _, action in dividends.iterrows():
            ex_date = pd.Timestamp(action["event_date"])
            if pd.isna(ex_date):
                continue
            if ex_date < entry:
                continue
            if exit_ is not None and ex_date >= exit_:
                continue
            cash_per_share = float(action["cash_amount"])
            rows.append(
                {
                    "stock_id": stock_id,
                    "event_date": ex_date.date().isoformat(),
                    "shares": shares,
                    "cash_per_share": cash_per_share,
                    "cash_flow": cash_per_share * shares,
                }
            )
    return pd.DataFrame(
        rows,
        columns=["stock_id", "event_date", "shares", "cash_per_share", "cash_flow"],
    )
