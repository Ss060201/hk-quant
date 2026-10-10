"""Trading calendar.

The calendar is an *observed* calendar derived from market price dates, not
an official HKEX holiday calendar. Weekends and market holidays are therefore
represented only insofar as they appear as absent price dates.

Do not treat Monday-Friday as a trading day; ask the calendar.
"""

from __future__ import annotations

from datetime import date
from typing import Iterable

import pandas as pd


def _to_date(value: object) -> date:
    ts = pd.Timestamp(value)
    if ts is pd.NaT:
        raise ValueError(f"invalid date: {value!r}")
    return ts.date()


class TradingCalendar:
    """A trading calendar backed by an explicit set of trading dates."""

    def __init__(self, dates: Iterable[object]) -> None:
        parsed = sorted({_to_date(d) for d in dates})
        self._sorted: list[date] = parsed
        self._days = set(parsed)

    @classmethod
    def from_prices(cls, prices: pd.DataFrame) -> "TradingCalendar":
        """Build an observed calendar from a canonical price frame's dates."""
        return cls(pd.to_datetime(prices["trade_date"], errors="coerce").tolist())

    def is_trading_day(self, d: object) -> bool:
        """Return True if ``d`` is in the observed set of trading days."""
        return _to_date(d) in self._days

    def get_trading_days(
        self,
        start_date: object | None = None,
        end_date: object | None = None,
    ) -> list[date]:
        """Return trading days, optionally bounded by ``start_date``/``end_date``."""
        days = self._sorted
        if start_date is not None:
            start = _to_date(start_date)
            days = [d for d in days if d >= start]
        if end_date is not None:
            end = _to_date(end_date)
            days = [d for d in days if d <= end]
        return list(days)

    def next_trading_day(self, d: object) -> date:
        """Return the first trading day strictly after ``d``."""
        target = _to_date(d)
        for day in self._sorted:
            if day > target:
                return day
        raise ValueError(f"no trading day after {target}")

    def previous_trading_day(self, d: object) -> date:
        """Return the last trading day strictly before ``d``."""
        target = _to_date(d)
        earlier = [day for day in self._sorted if day < target]
        if not earlier:
            raise ValueError(f"no trading day before {target}")
        return earlier[-1]

    def forward_trading_date(self, d: object, periods: int) -> date:
        """Return the date ``periods`` trading days after ``d``.

        ``periods`` counts *trading* days, not calendar days. For example
        ``forward_trading_date(d, 5)`` is the 5th trading day after ``d``
        (the start date itself is not counted).
        """
        if periods < 0:
            raise ValueError("periods must be >= 0")
        target = _to_date(d)
        if periods == 0:
            return target

        after = [day for day in self._sorted if day > target]
        if len(after) < periods:
            raise ValueError(
                f"not enough trading days after {target} for {periods} periods"
            )
        return after[periods - 1]
