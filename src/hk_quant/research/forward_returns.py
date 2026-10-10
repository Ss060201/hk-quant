"""Forward return computation.

Forward returns are outcomes measured *after* an event. They are computed
separately from event detection so that future data can never influence
whether an event happened.

Trading-day arithmetic uses a :class:`TradingCalendar` (from the data layer);
we never add ``timedelta(days=n)``.
"""

from __future__ import annotations

import math

import pandas as pd

from hk_quant.data.calendar import TradingCalendar
from hk_quant.research.models import ResearchDefinition

FORWARD_RETURN_COLUMNS: tuple[str, ...] = (
    "stock_id",
    "event_date",
    "variable_name",
    "variable_value",
    "threshold",
    "forward_period",
    "forward_return",
    "valid_sample",
    "exit_date",
)


def compute_forward_returns(
    events: pd.DataFrame,
    panel: pd.DataFrame,
    calendar: TradingCalendar,
    definition: ResearchDefinition,
) -> pd.DataFrame:
    """Compute forward returns for every event x forward period.

    Missing or out-of-range exit prices are represented as ``NaN`` with
    ``valid_sample=False``; they are never forward-filled or back-filled.
    """
    entry_col = definition.return_definition.entry
    exit_col = definition.return_definition.exit

    price_map: dict[tuple[str, object], dict[str, float]] = {}
    for _, row in panel.iterrows():
        day = pd.Timestamp(row["trade_date"]).date()
        key = (row["stock_id"], day)
        price_map.setdefault(key, {})
        for col in ("open", "high", "low", "close"):
            if col in row:
                price_map[key][col] = row[col]

    records: list[dict] = []
    for _, event in events.iterrows():
        stock_id = event["stock_id"]
        event_date = pd.Timestamp(event["event_date"]).date()
        entry_price = price_map.get((stock_id, event_date), {}).get(entry_col)

        for period in definition.forward_periods:
            try:
                exit_date = calendar.forward_trading_date(event_date, period)
            except ValueError:
                exit_date = None

            exit_price = (
                price_map.get((stock_id, exit_date), {}).get(exit_col)
                if exit_date is not None
                else None
            )

            valid = (
                entry_price is not None
                and exit_price is not None
                and not _is_nan(entry_price)
                and not _is_nan(exit_price)
                and float(entry_price) != 0.0
            )
            forward_return = (
                float(exit_price) / float(entry_price) - 1.0 if valid else float("nan")
            )

            records.append(
                {
                    "stock_id": stock_id,
                    "event_date": event["event_date"],
                    "variable_name": event["variable_name"],
                    "variable_value": event["variable_value"],
                    "threshold": event["threshold"],
                    "forward_period": period,
                    "forward_return": forward_return,
                    "valid_sample": valid,
                    "exit_date": exit_date,
                }
            )

    return pd.DataFrame(records, columns=list(FORWARD_RETURN_COLUMNS))


def _is_nan(value: object) -> bool:
    try:
        return bool(math.isnan(float(value)))
    except (TypeError, ValueError):
        return True
