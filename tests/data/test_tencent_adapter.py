"""Tencent HK adapter unit tests (no network; _paginate mocked)."""

from __future__ import annotations

import pandas as pd
import pytest

from hk_quant.data.adapters.tencent import TencentHKProvider


def _bars(rows):
    # Tencent order: [date, open, close, high, low, volume]
    return [[d, str(o), str(c), str(h), str(l), str(v)] for (d, o, c, h, l, v) in rows]


def test_column_mapping_and_amount_null(monkeypatch) -> None:
    provider = TencentHKProvider()
    monkeypatch.setattr(
        provider, "_paginate",
        lambda sid, s, e: _bars([("2026-11-02", 387.600, 392.200, 397.600, 384.600, 22621767)]),
    )
    raw = provider.fetch_raw_daily_prices(["0700"], "2026-11-02", "2026-11-02")
    canonical = provider.normalize_daily_prices(raw, "0700")

    row = canonical.iloc[0]
    assert row["stock_id"] == "0700"
    assert row["open"] == pytest.approx(387.600)
    assert row["close"] == pytest.approx(392.200)
    assert row["high"] == pytest.approx(397.600)
    assert row["low"] == pytest.approx(384.600)
    assert row["volume"] == pytest.approx(22621767)
    assert pd.isna(row["amount"])  # Tencent has no 成交額
    assert pd.isna(row["turnover_rate"])
    assert row["source"] == "tencent"
    # volume must never be mistaken for amount
    assert row["volume"] != row["amount"]


def test_rejects_bad_ohlc(monkeypatch) -> None:
    provider = TencentHKProvider()
    monkeypatch.setattr(
        provider, "_paginate",
        lambda sid, s, e: _bars([("2026-09-04", 78.5, 77.5, 78.8, 78.05, 29691804)]),
    )
    with pytest.raises(ValueError, match="OHLC"):
        provider.fetch_raw_daily_prices(["1299"], "2026-09-04", "2026-09-04")


def test_rejects_incomplete_history(monkeypatch) -> None:
    provider = TencentHKProvider()
    monkeypatch.setattr(
        provider, "_paginate",
        lambda sid, s, e: _bars([("2024-10-22", 1, 1, 1, 1, 1), ("2024-10-23", 1, 1, 1, 1, 1)]),
    )
    with pytest.raises(ValueError, match="incomplete"):
        provider.fetch_raw_daily_prices(["0700"], "2020-01-01", "2026-11-03")


def test_normalize_is_raw_not_adjusted(monkeypatch) -> None:
    provider = TencentHKProvider()
    monkeypatch.setattr(
        provider, "_paginate",
        lambda sid, s, e: _bars([("2026-11-02", 387.6, 392.2, 397.6, 384.6, 1)]),
    )
    raw = provider.fetch_raw_daily_prices(["0700"], "2026-11-02", "2026-11-02")
    assert raw.iloc[0]["close"] == pytest.approx(392.2)  # passed through unchanged


def test_paginate_walks_backward(monkeypatch) -> None:
    provider = TencentHKProvider()
    calls: list[tuple[str, str]] = []

    def fake_request(stock_id, start, end):
        calls.append((start, end))
        if end == "2026-11-03":
            # first page returns the latest bars ending at end
            return _bars([("2024-10-22", 1, 1, 1, 1, 1), ("2026-11-03", 2, 2, 2, 2, 2)])
        return _bars([("2020-01-02", 3, 3, 3, 3, 3)])

    monkeypatch.setattr(provider, "_request", fake_request)
    bars = provider._paginate("0700", "2020-01-01", "2026-11-03")
    assert bars  # walked back once the first page's earliest date still exceeded start
    assert ("2020-01-01", "2024-10-21") in calls  # second page requested backward
