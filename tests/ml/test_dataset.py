"""A future outcome must never enter a signal-date feature row."""

import unittest

import pandas as pd

from hk_quant.ml import build_conditional_dataset


class ConditionalDatasetTests(unittest.TestCase):
    def test_fixed_20_day_failure_label_and_as_of_join(self):
        days = pd.bdate_range("2025-01-01", periods=23)
        close = [100.0] * 23
        close[20] = 94.0
        prices = pd.DataFrame({"stock_id": "A", "trade_date": days, "close": close})
        signals = pd.DataFrame({"stock_id": ["A", "A"],
                                "signal_date": [days[0], days[22]],
                                "signal": ["BUY", "BUY"]})
        features = pd.DataFrame({"stock_id": ["A", "A"],
                                 "available_at": [days[0], days[1]],
                                 "momentum": [.3, 999.0]})
        result = build_conditional_dataset(
            signals, features, prices, strategy_id="fixed", strategy_version="v1",
            data_version="data-v1", feature_source="synthetic", feature_columns=["momentum"])
        self.assertEqual(len(result.samples), 1)
        self.assertEqual(result.samples.iloc[0].label, 1)
        self.assertEqual(result.samples.iloc[0].momentum, .3)
        self.assertAlmostEqual(result.samples.iloc[0].future_return, -.06)
        self.assertEqual(result.samples.iloc[0].label_period_end, days[20])
        self.assertEqual(result.discarded["future_horizon_unavailable"], 1)

    def test_leaky_feature_and_wrong_strategy_rejected(self):
        days = pd.bdate_range("2025-01-01", periods=23)
        sig = pd.DataFrame({"stock_id": ["A"], "signal_date": [days[0]],
                            "signal": ["BUY"], "strategy_id": ["wrong"],
                            "strategy_version": ["v1"]})
        feat = pd.DataFrame({"stock_id": ["A"], "available_at": [days[0]],
                             "future_return": [.2], "x": [1.0]})
        prices = pd.DataFrame({"stock_id": "A", "trade_date": days, "close": 100.})
        args = dict(strategy_id="fixed", strategy_version="v1", data_version="d",
                    feature_source="demo")
        with self.assertRaises(ValueError):
            build_conditional_dataset(sig, feat, prices,
                                      feature_columns=["future_return"], **args)
        with self.assertRaises(ValueError):
            build_conditional_dataset(sig, feat, prices, feature_columns=["x"], **args)
