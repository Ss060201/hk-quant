"""Corporate actions tests."""

from __future__ import annotations

import pandas as pd
import pytest

from hk_quant.data.corporate_actions import (
    canonicalize_corporate_actions,
    empty_corporate_actions,
    parse_dividend_scheme,
)
from hk_quant.data.models import ACTION_BONUS, ACTION_DIVIDEND
from hk_quant.data.quality import DataQualityError, validate_corporate_actions


def test_parse_cash_dividend() -> None:
    assert parse_dividend_scheme("每股派港币5.3元") == (ACTION_DIVIDEND, 5.3, None)
    assert parse_dividend_scheme("每股派港币4.5元") == (ACTION_DIVIDEND, 4.5, None)


def test_parse_bonus_share() -> None:
    action_type, cash, factor = parse_dividend_scheme(
        "特殊说明:每10股分派1股美团B类普通股股份(相当于每股派18.13港元)"
    )
    assert action_type == ACTION_BONUS
    assert cash is None
    assert factor == pytest.approx(1.1)


def test_parse_unknown_scheme_is_not_guessed() -> None:
    assert parse_dividend_scheme("每股派特别股息") == (ACTION_DIVIDEND, None, None)


def test_canonicalize_corporate_actions() -> None:
    df = pd.DataFrame(
        {
            "stock_id": ["00700"],
            "event_date": ["2025-05-16"],
            "announcement_date": ["2025-05-14"],
            "action_type": ["dividend"],
            "factor": [None],
            "cash_amount": ["4.5"],
        }
    )
    result = canonicalize_corporate_actions(df, "akshare")
    assert result.loc[0, "stock_id"] == "0700"
    assert result.loc[0, "cash_amount"] == 4.5
    assert result.loc[0, "source"] == "akshare"
    assert pd.notna(result.loc[0, "ingested_at"])


def test_validate_corporate_actions() -> None:
    valid = pd.DataFrame(
        {
            "stock_id": ["0700"],
            "event_date": pd.to_datetime(["2025-05-16"]),
            "announcement_date": pd.to_datetime(["2025-05-14"]),
            "action_type": ["dividend"],
            "factor": [None],
            "cash_amount": [4.5],
            "source": ["akshare"],
            "ingested_at": [pd.Timestamp.now("UTC")],
        }
    )
    validate_corporate_actions(valid)


def test_validate_unknown_action_type_raises() -> None:
    df = pd.DataFrame(
        {
            "stock_id": ["0700"],
            "event_date": pd.to_datetime(["2025-05-16"]),
            "announcement_date": [pd.NaT],
            "action_type": ["mystery"],
            "factor": [None],
            "cash_amount": [None],
        }
    )
    with pytest.raises(DataQualityError, match="unknown action_type"):
        validate_corporate_actions(df)


def test_empty_corporate_actions() -> None:
    df = empty_corporate_actions()
    assert df.empty
    assert list(df.columns) == [
        "stock_id",
        "event_date",
        "announcement_date",
        "action_type",
        "factor",
        "cash_amount",
        "source",
        "ingested_at",
    ]
