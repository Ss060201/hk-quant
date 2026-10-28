"""Cash dividend cash-flow tests (hand-calculated)."""

from __future__ import annotations

import pandas as pd
import pytest

from hk_quant.backtest.dividends import dividend_cash_flows


def _actions() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "stock_id": ["0700", "0700", "0700"],
            "event_date": pd.to_datetime(["2009-05-06", "2009-05-06", "2010-05-10"]),
            "announcement_date": pd.to_datetime(["2009-05-14", "2009-05-14", "2010-05-12"]),
            "action_type": ["dividend", "dividend", "dividend"],
            "factor": [None, None, None],
            "cash_amount": [0.25, 0.10, 0.50],
            "source": ["akshare"] * 3,
            "ingested_at": [pd.Timestamp.now("UTC")] * 3,
        }
    )


def test_hand_calculated_dividend_cash() -> None:
    flows = dividend_cash_flows(
        [{"stock_id": "0700", "shares": 100, "entry_date": "2009-01-01", "exit_date": None}],
        _actions(),
    )
    # Two ex-dates: 2009-05-06 (0.25 + 0.10) and 2010-05-10 (0.50)
    assert len(flows) == 3
    total = flows["cash_flow"].sum()
    assert total == pytest.approx(100 * (0.25 + 0.10 + 0.50))


def test_dividend_after_exit_is_excluded() -> None:
    flows = dividend_cash_flows(
        [{"stock_id": "0700", "shares": 100, "entry_date": "2009-01-01", "exit_date": "2010-01-01"}],
        _actions(),
    )
    # 2010-05-10 is after exit -> excluded
    assert flows["event_date"].tolist() == ["2009-05-06", "2009-05-06"]
    assert flows["cash_flow"].sum() == pytest.approx(100 * 0.35)


def test_distribution_in_kind_is_never_valued() -> None:
    actions = _actions()
    actions.loc[0, "action_type"] = "distribution_in_kind"
    actions.loc[0, "cash_amount"] = None
    flows = dividend_cash_flows(
        [{"stock_id": "0700", "shares": 100, "entry_date": "2009-01-01", "exit_date": None}],
        actions,
    )
    # Only the two cash dividends remain; distribution_in_kind contributes nothing.
    assert len(flows) == 2
    assert flows["cash_flow"].sum() == pytest.approx(100 * (0.10 + 0.50))
