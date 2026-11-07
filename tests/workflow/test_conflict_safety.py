"""Regression tests for preserved observations and durable conflict blocking."""
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from hk_quant.data.adapters.tencent import TencentHKProvider
from hk_quant.data.storage import DataStorage
from hk_quant.backtest.execution import raw_open_or_rejection
from hk_quant.workflow.conflicts import (
    collect_conflicts, persist_conflicts, conflict_blockers, ConflictHistoryError,
    resolve_conflict, unresolved_conflicts,
)
from hk_quant.workflow.data import DataRouter, merge_prices, prepare_data
from hk_quant.workflow.cli import execute, build_repository, main
from tests.workflow.test_workflow import prices, spec


def conflict():
    old = prices(("0700",))
    new = old.copy()
    new.loc[new.index[0], "amount"] = 9999.
    new["source"] = "other"
    return old, new, merge_prices(old, new)[1]


class ObservationTests(unittest.TestCase):
    def test_zero_volume_preserved_and_not_executable(self):
        provider = TencentHKProvider()
        with patch.object(provider, "_paginate", return_value=[["2020-01-02", 10, 10, 10, 10, 0]]):
            frame = provider.get_daily_prices(["0700"], "2020-01-02", "2020-01-02")
        self.assertEqual(len(frame), 1)
        self.assertEqual(raw_open_or_rejection(frame.iloc[0].to_dict())[1], "UNTRADABLE_VOLUME")

    def test_invalid_volume_never_silently_disappears(self):
        for value in (-1, "bad", None, float("nan"), float("inf")):
            provider = TencentHKProvider()
            bars = [["2020-01-02", 10, 10, 10, 10, value], ["2020-01-03", 10, 10, 10, 10, 100]]
            with self.subTest(value=value), patch.object(provider, "_paginate", return_value=bars):
                with self.assertRaises(ValueError):
                    provider.fetch_raw_daily_prices(["0700"], "2020-01-02", "2020-01-03")


class ConflictTests(unittest.TestCase):
    def test_resolution_requires_matching_data_and_keeps_audit(self):
        old, _, issues = conflict()
        class Store:
            def load_daily_prices(self, *args): return old.iloc[:1].copy()
        with tempfile.TemporaryDirectory() as root:
            row = persist_conflicts(root, issues)[0]
            evidence = Path(root)/"source.txt"; evidence.write_text("Fixture source, amount=10000")
            request = dict(conflict_id=row["conflict_id"], reason="fixture reviewed", source_url="https://example.com/fixture",
                           reviewed_by="fixture reviewer", evidence_file="source.txt", accepted_values={"amount":10000.})
            path = Path(root)/"decision.json"; path.write_text(json.dumps(request))
            resolve_conflict(root, path, storage=Store())
            self.assertEqual(unresolved_conflicts(root, storage=Store()), [])
            self.assertEqual(len(collect_conflicts(root)), 1)  # original never deleted
            old.loc[old.index[0], "amount"] = 9998.
            self.assertEqual(len(unresolved_conflicts(root, storage=Store())), 1)

    def test_resolution_rejects_wrong_value_and_missing_evidence(self):
        old, _, issues = conflict()
        class Store:
            def load_daily_prices(self, *args): return old.iloc[:1].copy()
        with tempfile.TemporaryDirectory() as root:
            row = persist_conflicts(root, issues)[0]
            request = dict(conflict_id=row["conflict_id"], reason="fixture", source_url="https://example.com",
                           reviewed_by="fixture", evidence_file="missing.txt", accepted_values={"amount":9999.})
            path = Path(root)/"decision.json"; path.write_text(json.dumps(request))
            with self.assertRaisesRegex(ValueError, "differ"):
                resolve_conflict(root, path, storage=Store())
            request["accepted_values"]["amount"] = 10000.; path.write_text(json.dumps(request))
            with self.assertRaises(FileNotFoundError): resolve_conflict(root, path, storage=Store())

    def test_resolution_evidence_tampering_blocks(self):
        old, _, issues = conflict()
        class Store:
            def load_daily_prices(self, *args): return old.iloc[:1].copy()
        with tempfile.TemporaryDirectory() as root:
            row = persist_conflicts(root, issues)[0]
            evidence = Path(root)/"source.txt"; evidence.write_text("fixture")
            request = dict(conflict_id=row["conflict_id"], reason="fixture", source_url="https://example.com",
                           reviewed_by="fixture", evidence_file="source.txt", accepted_values={"amount":10000.})
            path = Path(root)/"decision.json"; path.write_text(json.dumps(request))
            result = resolve_conflict(root, path, storage=Store())
            (Path(root)/"quality/resolutions"/(result["resolution_id"]+".evidence")).write_text("changed")
            with self.assertRaises(ConflictHistoryError): unresolved_conflicts(root, storage=Store())

    def test_numbers_are_recorded_and_old_values_preserved(self):
        old, new, issues = conflict()
        merged, _ = merge_prices(old, new)
        self.assertEqual(issues[0]["stored_values"]["amount"], 10000.)
        self.assertEqual(issues[0]["incoming_values"]["amount"], 9999.)
        self.assertEqual(merged.iloc[0].amount, 10000.)

    def test_persist_rerun_and_deduplicate(self):
        with tempfile.TemporaryDirectory() as root:
            issues = conflict()[2]
            persist_conflicts(root, issues)
            persist_conflicts(root, issues)
            self.assertEqual(len(collect_conflicts(root)), 1)
            self.assertTrue(conflict_blockers(spec(), root))
            persist_conflicts(root)
            self.assertTrue(conflict_blockers(spec(), root))

    def test_old_reports_are_imported_without_making_up_values(self):
        with tempfile.TemporaryDirectory() as root:
            old = dict(stock_id="0700", date="2020-01-02", fields=["close"], stored_source="sina", incoming_source="tencent")
            DataStorage._atomic_json({"conflicts": [old]}, Path(root)/"preparations/old/report.json")
            rows = persist_conflicts(root)
            self.assertNotIn("stored_values", rows[0])
            self.assertTrue(conflict_blockers(spec(), root))

    def test_offline_run_and_status_cannot_bypass(self):
        with tempfile.TemporaryDirectory() as root:
            persist_conflicts(root, conflict()[2])
            with self.assertRaisesRegex(ValueError, "UNRESOLVED_SOURCE_CONFLICT"):
                execute(spec(), root, offline=True)
            with self.assertRaisesRegex(ValueError, "UNRESOLVED_SOURCE_CONFLICT"):
                build_repository(spec(), root)
            config = Path(root)/"spec.json"
            config.write_text(json.dumps(spec().to_dict()))
            import io
            from contextlib import redirect_stdout
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["status", "--data-root", root, "--spec", str(config)])
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(output.getvalue())["status"], "BLOCKED")

    def test_warmup_conflict_blocks_but_other_stock_does_not(self):
        with tempfile.TemporaryDirectory() as root:
            rows = conflict()[2]
            rows[0]["date"] = "2019-12-20"
            persist_conflicts(root, rows)
            self.assertTrue(conflict_blockers(spec(), root))
            self.assertFalse(conflict_blockers(spec(stocks=["0941"]), root))

    def test_corrupt_history_blocks(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)/"preparations/old/report.json"
            path.parent.mkdir(parents=True)
            path.write_text("{broken")
            with self.assertRaises(ConflictHistoryError):
                build_repository(spec(), root)

    def test_failure_to_save_evidence_aborts_router(self):
        old, new, _ = conflict()
        class Provider:
            name = "fixture"
            def fetch_raw_daily_prices(self, *args): return new
            def normalize_daily_prices(self, raw, stock): return raw
        with tempfile.TemporaryDirectory() as root:
            run = Path(root)/"preparations/run"
            with patch.object(DataStorage, "_atomic_json", side_effect=OSError("disk full")):
                with self.assertRaises(ConflictHistoryError):
                    DataRouter([Provider()], attempts=1, delay=0).fetch("0700", "2020-01-02", "2020-01-09", ["close"], old, None, None, run)

    def test_router_saves_before_processed_write(self):
        old, new, _ = conflict()
        class Provider:
            name = "fixture"
            def fetch_raw_daily_prices(self, *args): return new
            def normalize_daily_prices(self, raw, stock): return raw
        with tempfile.TemporaryDirectory() as root:
            DataRouter([Provider()], attempts=1, delay=0).fetch("0700", "2020-01-02", "2020-01-09", ["close"], old, None, None, Path(root)/"preparations/run")
            self.assertTrue(conflict_blockers(spec(), root))

    def test_complete_cache_still_blocked_without_download(self):
        class Store:
            _atomic_json = staticmethod(DataStorage._atomic_json)
            def load_daily_prices(self, stock, *args): return prices((stock,))
            def save_daily_prices(self, frame): raise AssertionError("unexpected write")
        class Router:
            def fetch(self, *args): raise AssertionError("cache should avoid download")
        class Actions:
            name = "fixture"
            def fetch_raw_corporate_actions(self, stock): return pd.DataFrame()
        class Financials:
            def fetch_snapshot(self, stocks): return {"rows": []}
        with tempfile.TemporaryDirectory() as root:
            persist_conflicts(root, conflict()[2])
            sessions = sorted(set(prices().trade_date))
            with patch("hk_quant.workflow.data.expected_sessions", return_value=sessions):
                result = prepare_data(spec(), root, router=Router(), storage_factory=lambda *a: Store(),
                                      actions_provider=Actions(), financials_provider=Financials())
            self.assertEqual(result["status"], "BLOCKED")
            self.assertEqual(len(result["conflicts"]), 1)


if __name__ == "__main__": unittest.main()
