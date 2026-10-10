"""Integration tests hitting the real AKShare API.

These are excluded from the default ``pytest`` run. Run explicitly with::

    pytest -m integration
"""

from __future__ import annotations

from datetime import date

import pytest

pytestmark = pytest.mark.integration


def test_akshare_provider_daily_prices() -> None:
    from hk_quant.data.adapters.akshare import AKShareProvider

    provider = AKShareProvider()
    df = provider.get_daily_prices(
        stock_ids=["0700"], start_date="2025-01-01", end_date="2025-01-31"
    )
    assert not df.empty
    assert set(df["stock_id"]) == {"0700"}
    assert df["trade_date"].min() >= date(2025, 1, 1)
    assert df["trade_date"].max() <= date(2025, 1, 31)


def test_akshare_provider_stock_master() -> None:
    from hk_quant.data.adapters.akshare import AKShareProvider

    provider = AKShareProvider()
    df = provider.get_stock_master()
    assert not df.empty
    assert "0700" in set(df["stock_id"])
