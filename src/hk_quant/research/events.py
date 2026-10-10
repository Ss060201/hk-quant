"""Event detection.

Finds every historical occurrence that matches a research condition. Event
detection only ever uses information available on the event date itself; it
never looks at future prices.
"""

from __future__ import annotations

import pandas as pd

from hk_quant.research.models import EventMode, ResearchDefinition

EVENT_COLUMNS: tuple[str, ...] = (
    "stock_id",
    "event_date",
    "variable_name",
    "variable_value",
    "threshold",
)


def build_events(
    panel: pd.DataFrame,
    definition: ResearchDefinition,
    data_version: str | None = None,
) -> pd.DataFrame:
    """Return a canonical event DataFrame for the given research definition.

    ``event_mode``:

    * ``daily`` — every day with ``value > threshold`` is an event.
    * ``first_crossing`` — only the first day a stock moves from
      ``value <= threshold`` to ``value > threshold`` is an event.
    """
    variable = definition.variable.name
    missing = [c for c in ("stock_id", "trade_date", variable) if c not in panel.columns]
    if missing:
        raise ValueError(f"research panel is missing columns: {missing}")

    df = panel[["stock_id", "trade_date", variable]].copy()
    df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce")
    df["value"] = pd.to_numeric(df[variable], errors="coerce")
    df = df.sort_values(["stock_id", "trade_date"]).reset_index(drop=True)

    records: list[dict] = []
    for threshold in definition.thresholds:
        above = df["value"] > threshold

        if definition.event_mode == EventMode.FIRST_CROSSING.value:
            previous = df.groupby("stock_id")["value"].shift(1)
            mask = above & (previous <= threshold)
            # a stock's first observation has no previous value -> not a crossing
        else:
            mask = above

        matched = df[mask]
        for _, row in matched.iterrows():
            records.append(
                {
                    "stock_id": row["stock_id"],
                    "event_date": row["trade_date"],
                    "variable_name": variable,
                    "variable_value": row["value"],
                    "threshold": threshold,
                }
            )

    result = pd.DataFrame(records, columns=list(EVENT_COLUMNS))
    if not result.empty:
        result = result.drop_duplicates(
            subset=["stock_id", "event_date", "threshold"]
        ).reset_index(drop=True)

    if data_version is not None:
        result["data_version"] = data_version
    return result
