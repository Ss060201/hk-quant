"""Hand-checkable historical risk calculations and point-in-time exclusions."""

import math
import unittest

import pandas as pd

from hk_quant.risk import analyze_risk


class RiskEngineTests(unittest.TestCase):
    def setUp(self):
        days = pd.bdate_range("2025-01-01", periods=5)
        self.days = days
        first = [100, 110, 99, 118.8, 95.04]
        second = [200, 220, 198, 237.6, 190.08]
        self.prices = pd.DataFrame([
            {"stock_id": stock, "trade_date": day, "open": opening,
             "close": price, "amount": 1000}
            for stock, closes, opens in [("A", first, [100, 111, 90, 120, 90]),
                                         ("B", second, second)]
            for day, opening, price in zip(days, opens, closes)
        ])
        self.portfolio = pd.DataFrame({"trade_date": days, "equity": first,
                                       "turnover": [0, 0.1, 0.2, 0.1, 0]})
        self.positions = pd.DataFrame({"trade_date": [days[-1], days[-1]],
                                       "stock_id": ["A", "B"], "weight": [0.6, 0.3]})

    def analyze(self, **kwargs):
        return analyze_risk(self.prices, as_of_date=str(self.days[-1].date()),
                            data_version="data-v1", strategy_version="1.0.0",
                            portfolio_daily=self.portfolio, positions=self.positions,
                            annualization=1, window=4, **kwargs)

    def test_hand_calculated_metrics(self):
        result = self.analyze()
        a = result.stock_metrics.set_index("stock_id").loc["A"]
        self.assertEqual(result.classification, "HISTORICAL_DESCRIPTIVE")
        self.assertAlmostEqual(a.historical_volatility, math.sqrt(.1 / 3))
        self.assertAlmostEqual(a.downside_volatility, math.sqrt(.05 / 4))
        self.assertAlmostEqual(a.worst_overnight_gap, 90 / 118.8 - 1)
        self.assertEqual(a.median_daily_traded_amount, 1000)
        self.assertAlmostEqual(result.correlations.iloc[0].correlation, 1)
        self.assertAlmostEqual(result.portfolio_metrics["concentration_hhi"], .45)
        self.assertAlmostEqual(result.strategy_metrics["max_drawdown"], -.2)
        self.assertEqual(result.strategy_metrics["longest_loss_streak"], 1)
        self.assertIsNone(result.portfolio_metrics["drawdown_contribution"])

    def test_future_prices_positions_and_attributes_never_affect_past(self):
        prior = self.analyze()
        last = self.days[-1] + pd.Timedelta(days=3)
        self.prices = pd.concat([self.prices, pd.DataFrame([
            {"stock_id": "A", "trade_date": last, "close": 1_000_000, "open": 1_000_000, "amount": 999999}
        ])], ignore_index=True)
        self.portfolio = pd.concat([self.portfolio, pd.DataFrame([
            {"trade_date": last, "equity": 1_000_000, "turnover": 1.0}
        ])], ignore_index=True)
        self.positions = pd.concat([self.positions, pd.DataFrame([
            {"trade_date": last, "stock_id": "A", "weight": 1.0}
        ])], ignore_index=True)
        attrs = pd.DataFrame([
            {"stock_id": "A", "available_at": self.days[0], "sector": "tech", "factor_beta": 1.0},
            {"stock_id": "B", "available_at": self.days[0], "sector": "finance", "factor_beta": -.5},
            {"stock_id": "A", "available_at": last, "sector": "later", "factor_beta": 99},
        ])
        now = self.analyze(attributes=attrs, attribute_source="test")
        self.assertAlmostEqual(now.stock_metrics.loc[0, "historical_volatility"],
                               prior.stock_metrics.loc[0, "historical_volatility"])
        self.assertAlmostEqual(now.strategy_metrics["max_drawdown"], -.2)
        self.assertAlmostEqual(now.portfolio_metrics["concentration_hhi"], .45)
        self.assertEqual(now.portfolio_metrics["sector_exposure"], {"finance": .3, "tech": .6})
        self.assertAlmostEqual(now.portfolio_metrics["factor_exposure"]["factor_beta"], .45)

    def test_short_sample_zero_vol_and_bad_weight(self):
        one = self.prices.loc[(self.prices.stock_id == "A") &
                              (self.prices.trade_date == self.days[0])]
        result = analyze_risk(one, as_of_date=str(self.days[0].date()),
                              data_version=None, window=2)
        self.assertIsNone(result.stock_metrics.iloc[0].historical_volatility)
        self.assertTrue(any("insufficient" in w for w in result.warnings))
        flat = self.prices.copy()
        flat["close"] = 100.0
        zero = analyze_risk(flat, as_of_date=str(self.days[-1].date()),
                            data_version="v1", window=4)
        self.assertEqual(zero.stock_metrics.iloc[0].historical_volatility, 0)
        self.assertIsNone(zero.correlations.iloc[0].correlation)
        self.positions.loc[0, "weight"] = 1.1
        with self.assertRaises(ValueError):
            self.analyze()
