"""Tencent HK provider integration tests (live endpoint, read-only)."""

from __future__ import annotations

import pandas as pd
import pytest

from hk_quant.data.adapters.tencent import TencentHKProvider

pytestmark = pytest.mark.integration


def test_live_0700_2026_11_02_matches_aastocks() -> None:
    provider = TencentHKProvider()
    df = provider.get_daily_prices(["0700"], "2026-11-02", "2026-11-02")
    assert len(df) == 1
    row = df.iloc[0]
    # AASTOCKS 2026-11-02: Open 387.600, High 397.600, Low 384.600,
    # Last 392.200, Volume 22.62M.
    assert row["open"] == pytest.approx(387.600)
    assert row["close"] == pytest.approx(392.200)
    assert row["high"] == pytest.approx(397.600)
    assert row["low"] == pytest.approx(384.600)
    assert row["volume"] == pytest.approx(22_621_767)
    assert pd.isna(row["amount"])


def test_live_1299_2026_09_04_low_is_corrected() -> None:
    provider = TencentHKProvider()
    df = provider.get_daily_prices(["1299"], "2026-09-03", "2026-09-05")
    row = df[pd.to_datetime(df["trade_date"]) == pd.Timestamp("2026-09-04")].iloc[0]
    # Tencent shows low = 77.450 (Sina's 78.05 was a source error);
    # 77.450 <= close 77.500, so the OHLC anomaly is resolved.
    assert row["low"] == pytest.approx(77.450)
    assert row["low"] <= row["close"]
