"""Trading calendar tests."""

from __future__ import annotations

from datetime import date

import pytest

from hk_quant.data.calendar import TradingCalendar
from hk_quant.data.quality import DataQualityError, validate_trade_dates


def _calendar() -> TradingCalendar:
    # 2025-01-02 .. 2025-01-10, skipping 01-01 (holiday) and 01-04/05 (weekend)
    return TradingCalendar(
        [
            "2025-01-02",
            "2025-01-03",
            "2025-01-06",
            "2025-01-07",
            "2025-01-08",
            "2025-01-09",
            "2025-01-10",
        ]
    )


def test_is_trading_day() -> None:
    cal = _calendar()
    assert cal.is_trading_day("2025-01-02")
    assert not cal.is_trading_day("2025-01-04")  # Saturday
    assert not cal.is_trading_day("2025-01-01")  # holiday (observed absent)


def test_get_trading_days_range() -> None:
    cal = _calendar()
    days = cal.get_trading_days("2025-01-03", "2025-01-08")
    assert days == [
        date(2025, 1, 3),
        date(2025, 1, 6),
        date(2025, 1, 7),
        date(2025, 1, 8),
    ]


def test_next_and_previous_trading_day() -> None:
    cal = _calendar()
    assert cal.next_trading_day("2025-01-03") == date(2025, 1, 6)
    assert cal.previous_trading_day("2025-01-06") == date(2025, 1, 3)


def test_forward_trading_date_counts_trading_days() -> None:
    cal = _calendar()
    # 5 trading days after 2025-01-02 = 2025-01-09 (not calendar day +5)
    assert cal.forward_trading_date("2025-01-02", 5) == date(2025, 1, 9)
    assert cal.forward_trading_date("2025-01-02", 1) == date(2025, 1, 3)


def test_forward_trading_date_errors() -> None:
    cal = _calendar()
    with pytest.raises(ValueError):
        cal.forward_trading_date("2025-01-10", 1)  # not enough days
    with pytest.raises(ValueError):
        cal.forward_trading_date("2025-01-02", -1)


def test_validate_trade_dates() -> None:
    cal = _calendar()
    valid = validate_trade_dates(["2025-01-02", "2025-01-06"], cal)
    assert valid == [date(2025, 1, 2), date(2025, 1, 6)]

    with pytest.raises(DataQualityError):
        validate_trade_dates(["2025-01-04"], cal)  # weekend
