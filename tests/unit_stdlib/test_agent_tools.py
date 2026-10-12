"""Safe agent boundaries that do not require a data provider or model."""

from __future__ import annotations

import unittest

from hk_quant.agent.tools import ResearchTools


class _CoverageOnly:
    def get_data_coverage(self):
        return {"daily_prices": {"row_count": 100, "turnover_rate_nonnull": 0}}


class AgentToolTests(unittest.TestCase):
    def setUp(self):
        self.tools = ResearchTools(_CoverageOnly(), "experiments", registry=object())

    def test_planner_reports_assumptions_without_running(self):
        result = self.tools.call("plan_research", {
            "question": "研究換手率 5%、10% 與未來 1、5 交易日收益",
            "start_date": "2025-01-01", "end_date": "2025-06-30",
            "thresholds": [0.05, 0.1], "forward_periods": [1, 5],
        })
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["status"], "READY")

    def test_missing_turnover_rate_never_substitutes_amount(self):
        config = {"name": "turnover", "variable": {"name": "turnover_rate", "thresholds": [0.1]},
                  "forward_periods": [5], "date_range": {"start": "2025-01-01", "end": "2025-06-30"}}
        result = self.tools.call("run_research", {"config": config})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "DATA_UNAVAILABLE")
        self.assertIn("turnover_rate", result["error"]["message"])

    def test_untrusted_paths_and_sql_are_rejected_before_any_data_call(self):
        for argument in ("../../private", "0700') OR 1=1 --"):
            result = self.tools.call("get_market_data", {
                "stock_ids": [argument], "start_date": "2025-01-01", "end_date": "2025-01-31",
            })
            self.assertFalse(result["ok"])
            self.assertEqual(result["error"]["code"], "INVALID_INPUT")


if __name__ == "__main__":
    unittest.main()
