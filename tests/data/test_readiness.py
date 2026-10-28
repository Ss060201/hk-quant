"""Coverage gates do not confuse a current stock list with a historical universe."""

import pandas as pd

from hk_quant.data.readiness import assess_price_panel


def test_missing_stock_and_missing_observed_session_block_validation():
    prices = pd.DataFrame([
        {"stock_id": stock, "trade_date": day, "open": 1., "high": 1.,
         "low": 1., "close": 1., "volume": 10., "amount": 10.}
        for stock, day in [("0700", "2025-01-02"), ("0700", "2025-01-03"),
                           ("0005", "2025-01-02")]
    ])
    result = assess_price_panel(prices, ["0700", "0005", "0941"],
                                "2025-01-02", "2025-01-03", min_sessions=2)
    assert result["status"] == "BLOCKED"
    assert result["stocks"][1]["missing_observed_dates"] == ["2025-01-03"]
    assert result["stocks"][2]["sessions"] == 0


def test_complete_small_cohort_passes_explicit_threshold():
    prices = pd.DataFrame([
        {"stock_id": stock, "trade_date": day, "open": 1., "high": 1.,
         "low": 1., "close": 1., "volume": 10., "amount": 10.}
        for stock in ("0700", "0005") for day in ("2025-01-02", "2025-01-03")
    ])
    result = assess_price_panel(prices, ["0700", "0005"],
                                "2025-01-02", "2025-01-03", min_sessions=2)
    assert result["status"] == "READY_FOR_EXPLORATORY_VALIDATION"
