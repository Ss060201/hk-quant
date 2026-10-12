"""Risk result consumes backtest ledger and persists a registry record."""

import tempfile
import unittest
from types import SimpleNamespace

import pandas as pd

from hk_quant.experiments.registry import ExperimentRegistry
from hk_quant.risk import analyze_backtest_risk, register_risk_result


class BacktestRiskIntegrationTests(unittest.TestCase):
    def test_backtest_adaptation_and_registry(self):
        dates = pd.bdate_range("2025-01-01", periods=4)
        prices = pd.DataFrame({"trade_date": dates, "stock_id": "A",
                               "close": [100, 110, 99, 90]})
        daily = pd.DataFrame({"trade_date": dates, "equity": [90, 100, 95, 85],
                              "turnover": [0.5, 0., 0., 0.]})
        positions = pd.DataFrame({"trade_date": [dates[-1]], "stock_id": ["A"],
                                  "market_value": [42.5], "mark_status": ["CLOSE"]})
        # Match the BacktestResult ledger shape without importing provider
        # dependencies in this isolated unit test.
        backtest = SimpleNamespace(
            daily=daily, trades=pd.DataFrame(), positions=positions,
            orders=pd.DataFrame(), metrics={}, warnings=["Observed universe."],
            metadata={"data_version": "hash-v1", "strategy_version": "v1",
                      "status": "EXPLORATORY"},
            config=SimpleNamespace(initial_capital=100, annual_trading_days=252),
        )
        report = analyze_backtest_risk(backtest, prices)
        self.assertEqual(report.strategy_version, "v1")
        self.assertAlmostEqual(report.portfolio_metrics["largest_position_weight"], .5)
        self.assertAlmostEqual(report.strategy_metrics["max_drawdown"], -.15)
        self.assertTrue(any("Observed universe" in message for message in report.warnings))
        with tempfile.TemporaryDirectory() as directory:
            registry = ExperimentRegistry(directory)
            registered = register_risk_result(report, registry)
            self.assertEqual(registered.status, "COMPLETED")
            self.assertEqual(registry.load_experiment_artifacts(registered.experiment_id)["summary.json"]["classification"],
                             "HISTORICAL_DESCRIPTIVE")
            self.assertEqual(report.experiment_id, registered.experiment_id)
