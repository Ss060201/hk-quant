"""Point-in-time / as-of filtering tests."""

from __future__ import annotations

import pandas as pd
import pytest

from hk_quant.data.point_in_time import get_available_as_of, get_fundamentals_as_of
from hk_quant.data.quality import validate_fundamentals


def _fundamentals() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "stock_id": ["TEST001", "TEST_NULL", "TEST002"],
            "period_end": pd.to_datetime(["2026-06-30", "2026-06-30", "2026-06-30"]),
            "announcement_date": pd.to_datetime(
                ["2026-08-20", None, "2026-08-21"]
            ),
            "effective_date": [None, None, None],
            "metric": ["revenue", "revenue", "revenue"],
            "value": [100.0, 200.0, 300.0],
            "source": ["synthetic", "synthetic", "synthetic"],
            "ingested_at": [pd.Timestamp.now("UTC")] * 3,
        }
    )


def test_before_announcement_not_visible() -> None:
    result = get_available_as_of(_fundamentals(), "2026-08-19")
    assert result.empty


def test_on_announcement_visible() -> None:
    result = get_available_as_of(_fundamentals(), "2026-08-20")
    assert result["stock_id"].tolist() == ["TEST001"]


def test_after_announcement_visible() -> None:
    result = get_available_as_of(_fundamentals(), "2026-08-21")
    assert set(result["stock_id"]) == {"TEST001", "TEST002"}


def test_null_announcement_never_visible() -> None:
    result = get_available_as_of(_fundamentals(), "2030-01-01")
    # the row whose announcement_date is null is excluded, never assumed known
    assert "TEST_NULL" not in set(result["stock_id"])
    assert set(result["stock_id"]) == {"TEST001", "TEST002"}


def test_fundamentals_filters() -> None:
    result = get_fundamentals_as_of(
        _fundamentals(), "2026-08-21", stock_ids=["TEST002"], metric="revenue"
    )
    assert result["stock_id"].tolist() == ["TEST002"]
    assert result["value"].tolist() == [300.0]


def test_invalid_as_of_raises() -> None:
    with pytest.raises(ValueError):
        get_available_as_of(_fundamentals(), "not-a-date")


def test_fundamentals_validation_passes() -> None:
    validate_fundamentals(_fundamentals())
