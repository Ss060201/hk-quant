"""Conservative parser for a *small* subset of research questions.

Ambiguous questions produce a request for missing parameters. An LLM may suggest
a config, but it must still pass the same validation and coverage gate as this
parser before it can run. No threshold or historical range is guessed.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Mapping


_TURNOVER = re.compile(r"換手率|换手率|turnover[_\s-]?rate", re.IGNORECASE)
_AMOUNT = re.compile(r"成交額|成交额|trading[_\s-]?amount", re.IGNORECASE)
_PERCENT = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s*[%％]")
_PERIODS = re.compile(r"(?:未來|未来|future|forward)\s*([\d\s,，、及和/]+)\s*(?:個|个)?\s*(?:交易日|trading\s*days?|days?)", re.IGNORECASE)
_DAY = re.compile(r"\d+(?:\.\d+)?")
_MAX_LENGTH = 2000


def plan_research(
    question: str,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    thresholds: list[float] | None = None,
    forward_periods: list[int] | None = None,
    universe: str = "observed_price_universe",
) -> dict[str, Any]:
    """Return READY with an explicit ResearchDefinition config or NEEDS_INPUT.

    Percentages in the question map to ratio units, e.g. 10% -> 0.1.
    ``amount`` is never substituted for ``turnover_rate``. Only turnover rate
    is understood by this constrained parser; other variables require a fully
    explicit structured research config submitted to the tool.
    """
    if not isinstance(question, str) or not question.strip() or len(question) > _MAX_LENGTH:
        raise ValueError("question must be a non-empty string of at most 2000 characters")
    if universe != "observed_price_universe":
        raise ValueError("planner only supports the observed_price_universe")
    for value in (start_date, end_date):
        if value is not None:
            if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                raise ValueError("dates must use YYYY-MM-DD")
            date.fromisoformat(value)
    if start_date is not None and end_date is not None and start_date > end_date:
        raise ValueError("start_date must be on or before end_date")

    normalized = question.strip()
    variable = "turnover_rate" if _TURNOVER.search(normalized) else None
    if variable is None:
        return {"status": "NEEDS_INPUT", "missing": ["variable"], "question": normalized}
    if _AMOUNT.search(normalized):
        return {
            "status": "NEEDS_INPUT",
            "missing": ["variable"],
            "question": normalized,
            "warnings": ["turnover_rate and trading amount refer to different fields; specify one"],
        }

    if thresholds is None:
        parsed = [float(number) / 100 for number in _PERCENT.findall(normalized)]
        thresholds = sorted(set(parsed)) or None
    if forward_periods is None:
        match = _PERIODS.search(normalized)
        if match:
            # A hyphenated range (1–180) is ambiguous about which horizons
            # should be tested; ask for a finite explicit list instead.
            text = match.group(1)
            if not re.search(r"[-–—~至到]", text):
                forward_periods = [int(day) for day in _DAY.findall(text)] or None

    missing: list[str] = []
    if not thresholds:
        missing.append("thresholds (for example 5%, 10%, 20%)")
    if not forward_periods:
        missing.append("forward_periods (finite trading-day horizons, for example 1, 5, 20)")
    if start_date is None or end_date is None:
        missing.append("start_date and end_date (YYYY-MM-DD)")
    if missing:
        return {"status": "NEEDS_INPUT", "missing": missing, "question": normalized}

    return {
        "status": "READY",
        "question": normalized,
        "config": {
            "name": "turnover_rate_forward_returns",
            "variable": {"name": variable, "thresholds": thresholds, "unit": "ratio"},
            "forward_periods": forward_periods,
            "event_mode": "daily",
            "date_range": {"start": start_date, "end": end_date},
            "universe": {"mode": universe},
            "price": {"adjusted": False},
            "exploratory": True,
        },
        "assumptions": [
            "The provided percentages denote turnover_rate thresholds in ratio units.",
            "The observed-price universe is exploratory and may have survivorship bias.",
            "Returns exclude dividends unless an explicit config states otherwise.",
        ],
    }
