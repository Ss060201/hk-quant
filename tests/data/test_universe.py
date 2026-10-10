"""Historical universe construction tests."""

from __future__ import annotations

import pandas as pd
import pytest

from hk_quant.data.quality import validate_universe
from hk_quant.data.universe import UniverseDataUnavailableError, get_universe


def _master() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "stock_id": ["TEST_A", "TEST_B", "TEST_C", "TEST_D"],
            "symbol": ["A", "B", "C", "D"],
            "name": ["A", "B", "C", "D"],
            "listing_date": pd.to_datetime(
                ["2020-01-01", "2021-07-01", "2020-01-01", "2020-01-01"]
            ),
            "delisting_date": pd.to_datetime(
                [None, None, "2021-05-31", "2022-12-31"]
            ),
            "status": ["listed", "listed", "delisted", "delisted"],
            "source": ["synthetic"] * 4,
            "ingested_at": [pd.Timestamp.now("UTC")] * 4,
        }
    )


def test_universe_rules() -> None:
    as_of = pd.Timestamp("2021-06-01")

    result = get_universe(_master(), as_of)
    ids = set(result["stock_id"])

    # TEST_A listed before, still listed -> included
    assert "TEST_A" in ids
    # TEST_B listed after as_of -> excluded
    assert "TEST_B" not in ids
    # TEST_C delisted before as_of -> excluded
    assert "TEST_C" not in ids
    # TEST_D delisted after as_of -> included before delisting
    assert "TEST_D" in ids


def test_universe_all_listing_null_raises() -> None:
    master = _master()
    master["listing_date"] = None
    with pytest.raises(UniverseDataUnavailableError):
        get_universe(master, "2021-06-01")


def test_universe_missing_columns_raises() -> None:
    master = _master().drop(columns=["listing_date"])
    with pytest.raises(UniverseDataUnavailableError):
        get_universe(master, "2021-06-01")


def test_universe_validation_listing_after_delisting_raises() -> None:
    master = _master()
    master.loc[0, "delisting_date"] = pd.Timestamp("2019-12-31")
    with pytest.raises(Exception):
        validate_universe(master)
