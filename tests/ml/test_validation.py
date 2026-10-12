"""Forward-only folds, purging and explicit independent backtest requirement."""

import importlib.util
import math
import unittest

import pandas as pd

from hk_quant.experiments.registry import ExperimentRegistry
from hk_quant.ml import (build_conditional_dataset, evaluate_conditional_model,
                         register_conditional_result, walk_forward_splits)
import tempfile


class PurgeTests(unittest.TestCase):
    def test_train_labels_do_not_cross_test(self):
        dates = pd.bdate_range("2025-01-01", periods=100)
        rows = pd.DataFrame({"signal_date": dates[:80],
                             "label_period_end": dates[20:], "label": 0})
        first = next(walk_forward_splits(rows, initial_train_dates=60, test_dates=10))
        self.assertEqual(first.purged_train_samples, 20)
        self.assertEqual(len(first.train_indices), 40)
        self.assertTrue((rows.iloc[list(first.train_indices)].label_period_end <
                         pd.Timestamp(first.first_test_date)).all())
        self.assertEqual(len(first.test_indices), 10)

    @unittest.skipUnless(importlib.util.find_spec("sklearn"), "optional scikit-learn not installed")
    def test_oos_model_reports_baseline_and_blocks_unverified_net_comparison(self):
        dates = pd.bdate_range("2025-01-01", periods=145)
        prices = pd.DataFrame({"stock_id": "A", "trade_date": dates,
                               "close": [100 + 15 * math.sin(i / 8) for i in range(145)]})
        sig = pd.DataFrame({"stock_id": "A", "signal_date": dates[:100], "signal": "BUY"})
        features = pd.DataFrame({"stock_id": "A", "available_at": dates,
                                 "lagged_feature": [math.sin(i / 8) for i in range(145)]})
        data = build_conditional_dataset(sig, features, prices,
                                         strategy_id="fixed", strategy_version="v1",
                                         data_version="version", feature_source="synthetic",
                                         feature_columns=["lagged_feature"])
        result = evaluate_conditional_model(data, initial_train_dates=65,
                                            test_dates=15, min_train_samples=25)
        self.assertEqual(result.status, "EVALUATED")
        self.assertEqual(result.comparison_status, "BLOCKED")
        self.assertGreater(len(result.predictions), 0)
        self.assertTrue(all(fold["purged_train_samples"] >= 20 for fold in result.fold_metrics))
        self.assertTrue(all("prevalence_baseline" in fold for fold in result.fold_metrics))
        self.assertTrue(any("not been probability-calibrated" in w for w in result.warnings))
        with tempfile.TemporaryDirectory() as directory:
            registry = ExperimentRegistry(directory)
            record = register_conditional_result(result, data, registry)
            saved = registry.load_experiment_artifacts(record.experiment_id)
            self.assertEqual(record.status, "COMPLETED")
            self.assertEqual(len(saved["dataset.json"]), len(data.samples))
            self.assertEqual(len(saved["predictions.json"]), len(result.predictions))
        # Perturb a feature only after the first test window: the first fold
        # remains bit-for-bit identical because its preprocessing fits on train.
        future = data.samples.loc[data.samples.signal_date >= dates[90], "lagged_feature"]
        data.samples.loc[future.index, "lagged_feature"] = 9999.
        rerun = evaluate_conditional_model(data, initial_train_dates=65,
                                           test_dates=15, min_train_samples=25)
        pd.testing.assert_frame_equal(result.predictions.loc[result.predictions.fold == 0].reset_index(drop=True),
                                      rerun.predictions.loc[rerun.predictions.fold == 0].reset_index(drop=True))

    def test_no_valid_signals_blocks_model(self):
        empty = build_conditional_dataset(
            pd.DataFrame(columns=["stock_id", "signal_date", "signal"]),
            pd.DataFrame(columns=["stock_id", "available_at", "x"]),
            pd.DataFrame(columns=["stock_id", "trade_date", "close"]),
            strategy_id="fixed", strategy_version="v1", data_version=None,
            feature_source="synthetic", feature_columns=["x"])
        result = evaluate_conditional_model(empty)
        self.assertEqual(result.status, "BLOCKED")
        self.assertEqual(len(result.predictions), 0)
        with tempfile.TemporaryDirectory() as directory:
            registry = ExperimentRegistry(directory)
            record = register_conditional_result(result, empty, registry)
            self.assertEqual(record.status, "BLOCKED")
            snapshot = registry.load_experiment_artifacts(record.experiment_id)
            self.assertEqual(snapshot["dataset.json"], [])
            self.assertEqual(snapshot["summary.json"]["comparison_status"], "BLOCKED")
