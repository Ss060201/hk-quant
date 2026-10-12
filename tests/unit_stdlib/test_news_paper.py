"""Offline regressions runnable with unittest when optional dependencies are absent."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from hk_quant.news import DocumentStore
from hk_quant.orchestration import ResearchOrchestrator
from hk_quant.paper import (FutuPaperBroker, PaperOrderError, PaperMonitor,
                            StrategyLifecycle, propose_paper_order)


class DocumentTests(unittest.TestCase):
    def test_versions_and_point_in_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = DocumentStore(tmp)
            params = dict(source_id="hkex", document_id="announcement-1",
                          source_url="https://example.org/announcement-1",
                          stock_ids=("0700",), document_type="announcement", language="zh",
                          published_at="2025-01-01T10:00:00+08:00",
                          retrieved_at="2025-01-02T10:00:00+08:00")
            first = store.add_document(text="Original dividend notice.", **params)
            self.assertEqual(first.revision, 1)
            self.assertEqual(store.add_document(text="Original dividend notice.", **params), first)
            self.assertEqual(store.as_of("2025-01-01T23:59:00+08:00"), [])
            self.assertEqual(len(store.as_of("2025-01-03T00:00:00+08:00", "0700")), 1)
            second = store.add_document(text="Revised dividend notice.",
                                        **{**params, "retrieved_at": "2025-01-04T10:00:00+08:00"})
            self.assertEqual(second.revision, 2)
            self.assertEqual(store.as_of("2025-01-05T00:00:00+08:00"), [second])
            self.assertEqual(len(store.as_of("2025-01-05T00:00:00+08:00", all_versions=True)), 2)
            event = store.extract(first, lambda _: dict(event_type="DIVIDEND", direction="unknown",
                                  confidence=.8, evidence_quote="Original dividend notice.", entities=["0700"]),
                                  model_version="test-v1")
            self.assertGreaterEqual(event.available_at, first.available_at)
            with self.assertRaises(ValueError):
                store.extract(second, lambda _: {"evidence_quote": "hallucinated"}, model_version="test-v1")


class OrchestrationTests(unittest.TestCase):
    def test_budget_and_pit(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = []
            def candidates(strategy, day):
                calls.append(strategy)
                common = {"trigger_reason": "momentum", "rule_version": "v1",
                          "candidate_source": "synthetic signal", "available_at": "2025-01-01T03:00:00Z"}
                return [{"stock_id": "0700", **common}, {"stock_id": "0005", **common}]
            documents = lambda stock, day: [{"source_id": "hkex", "available_at": "2025-01-01T03:00:00Z"}]
            runner = ResearchOrchestrator(candidate_tool=candidates,
                                          coverage_tool=lambda: {"status": "AVAILABLE"},
                                          risk_tool=lambda stock, day: {"status": "AVAILABLE"},
                                          document_tool=documents, output_dir=tmp,
                                          max_candidates=1, max_documents=1)
            result = runner.run("fixed-v1", "2025-01-02", strategy_hash="abc", data_version="v1")
            self.assertEqual(len(result.candidates), 1)
            self.assertEqual(result.skipped_count, 1)
            self.assertEqual(result.run_id, runner.run("fixed-v1", "2025-01-02",
                                                     strategy_hash="abc", data_version="v1").run_id)
            self.assertEqual(calls, ["fixed-v1"])
            from hk_quant.experiments import ExperimentRegistry
            experiment_id = runner.register_packet(result, ExperimentRegistry(Path(tmp) / "registry"),
                                                    strategy_hash="abc", data_version="v1")
            self.assertEqual(len(experiment_id), 32)
            other = ResearchOrchestrator(candidate_tool=candidates,
                                         coverage_tool=lambda: {"status": "AVAILABLE"},
                                         risk_tool=lambda stock, day: {},
                                         document_tool=lambda stock, day: [{"source_id": "hkex", "available_at": "2025-01-04T00:00:00Z"}],
                                         output_dir=Path(tmp) / "other", max_candidates=1)
            with self.assertRaises(ValueError):
                other.run("fixed-v1", "2025-01-02", strategy_hash="abc", data_version="v1")
            same_day = ResearchOrchestrator(candidate_tool=candidates,
                                            coverage_tool=lambda: {"status": "AVAILABLE"},
                                            risk_tool=lambda stock, day: {},
                                            document_tool=lambda stock, day: [{"source_id": "hkex", "available_at": "2025-01-02T01:00:00Z"}],
                                            output_dir=Path(tmp) / "same_day", max_candidates=1)
            with self.assertRaises(ValueError):
                same_day.run("fixed-v1", "2025-01-02", strategy_hash="abc", data_version="v1")
            future_candidate = ResearchOrchestrator(
                candidate_tool=lambda _s, _d: [{"stock_id": "0700", "trigger_reason": "news",
                    "rule_version": "v1", "candidate_source": "synthetic",
                    "available_at": "2025-01-02T01:00:00Z"}],
                coverage_tool=lambda: {"status": "AVAILABLE"}, risk_tool=lambda _s, _d: {},
                document_tool=lambda _s, _d: [], output_dir=Path(tmp) / "future")
            with self.assertRaises(ValueError):
                future_candidate.run("fixed-v1", "2025-01-02", strategy_hash="abc", data_version="v1")


class _Table:
    def __init__(self, rows): self.rows = rows
    def to_dict(self, orient):
        assert orient == "records"
        return self.rows


class _FutuContext:
    def __init__(self, environment="SIMULATE"):
        self.environment = environment
        self.placed = []
        self.closed = False

    def get_acc_list(self):
        return 0, _Table([{"acc_id": 123, "trd_env": self.environment,
                           "sim_acc_type": "STOCK", "trdmarket_auth": ["HK"],
                           "acc_status": "ACTIVE"}])

    def accinfo_query(self, **kwargs):
        assert kwargs["trd_env"] == "SIMULATE" and kwargs["acc_id"] == 123
        return 0, _Table([{"hk_cash": 100000.0, "hkd_net_cash_power": 100000.0}])

    def position_list_query(self, **kwargs):
        return 0, _Table([{"code": "HK.00700", "qty": 100}])

    def order_list_query(self, **kwargs):
        return 0, _Table([])

    def place_order(self, **kwargs):
        self.placed.append(kwargs)
        return 0, _Table([{"order_id": "paper-123"}])

    def close(self): self.closed = True


class _UncertainContext(_FutuContext):
    def place_order(self, **kwargs):
        self.placed.append(kwargs)
        raise TimeoutError("outcome unknown")

    def history_order_list_query(self, **kwargs):
        return 0, _Table([{"order_id": "paper-later", "remark": "uncertain",
                           "code": "HK.00700", "trd_side": "BUY", "qty": 100,
                           "price": 100, "order_status": "FILLED_PART"}])


class _QuoteContext:
    def get_stock_basicinfo(self, market, stock_type, code_list):
        assert market == "HK" and stock_type == "STOCK"
        return 0, _Table([{"code": code_list[0], "stock_type": "STOCK",
                           "suspension": False, "delisting": False, "lot_size": 100}])

    def close(self): pass


_SDK = SimpleNamespace(RET_OK=0, TrdEnv=SimpleNamespace(SIMULATE="SIMULATE"),
                       Market=SimpleNamespace(HK="HK"), SecurityType=SimpleNamespace(STOCK="STOCK"),
                       TrdSide=SimpleNamespace(BUY="BUY", SELL="SELL"),
                       OrderType=SimpleNamespace(NORMAL="NORMAL"),
                       ModifyOrderOp=SimpleNamespace(CANCEL="CANCEL"))


class PaperTests(unittest.TestCase):
    def test_fixed_signal_creates_reviewable_lot_sized_proposal(self):
        signal = SimpleNamespace(status="VALID", strategy_id="s", strategy_version="1.0.0",
                                 strategy_hash="abc", data_version="content-v1",
                                 stock_id="0700", signal_date="2025-01-02", signal="BUY")
        args = dict(limit_price=100., lot_size=100, available_cash=15000.,
                    held_qty=0, max_notional=12000.)
        proposal = propose_paper_order(signal, **args)
        self.assertEqual((proposal.code, proposal.qty, proposal.status),
                         ("HK.00700", 100, "PROPOSED_REQUIRES_HUMAN_REVIEW"))
        self.assertEqual(proposal.client_order_id,
                         propose_paper_order(signal, **args).client_order_id)
        signal.signal = "HOLD"
        self.assertIsNone(propose_paper_order(signal, **args))
        signal.status = "DATA_UNAVAILABLE"
        with self.assertRaises(PaperOrderError):
            propose_paper_order(signal, **args)

    def test_uncertain_order_reconciled_without_duplicate_send(self):
        with tempfile.TemporaryDirectory() as tmp:
            context = _UncertainContext()
            broker = FutuPaperBroker(context, _SDK, account_id=123,
                                    journal_path=Path(tmp) / "orders.sqlite3",
                                    allow_paper_orders=True, quote_context=_QuoteContext())
            args = dict(client_order_id="uncertain", code="HK.00700", side="BUY",
                        qty=100, limit_price=100., lot_size=100, dry_run=False, confirmed=True)
            with self.assertRaises(TimeoutError):
                broker.place_paper_order(**args)
            with self.assertRaises(PaperOrderError):
                broker.place_paper_order(**args)
            recovered = broker.reconcile_order("uncertain")
            self.assertEqual(recovered.broker_order_id, "paper-later")
            self.assertEqual(recovered.status, "FILLED_PART")
            self.assertEqual(len(context.placed), 1)

    def test_nonfinite_funds_or_wrong_lot_blocks_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            class BadFunds(_FutuContext):
                def accinfo_query(self, **kwargs):
                    return 0, _Table([{"hk_cash": float("nan"),
                                       "hkd_net_cash_power": 100000.0}])
            context = BadFunds()
            broker = FutuPaperBroker(context, _SDK, account_id=123,
                                    journal_path=Path(tmp) / "orders.sqlite3",
                                    allow_paper_orders=True, quote_context=_QuoteContext())
            args = dict(client_order_id="bad-funds", code="HK.00700", side="BUY",
                        qty=100, limit_price=100., lot_size=100, dry_run=False, confirmed=True)
            with self.assertRaises(PaperOrderError):
                broker.place_paper_order(**args)
            with self.assertRaises(PaperOrderError):
                broker.place_paper_order(**{**args, "lot_size": 50})
            self.assertEqual(context.placed, [])

    def test_rejects_live_account_and_requires_explicit_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(PaperOrderError):
                FutuPaperBroker(_FutuContext("REAL"), _SDK, account_id=123,
                                journal_path=Path(tmp)/"orders.sqlite3")
            context = _FutuContext()
            broker = FutuPaperBroker(context, _SDK, account_id=123,
                                    journal_path=Path(tmp)/"orders.sqlite3", allow_paper_orders=True,
                                    quote_context=_QuoteContext())
            args = dict(client_order_id="one", code="HK.00700", side="BUY",
                        qty=100, limit_price=100., lot_size=100)
            self.assertEqual(broker.place_paper_order(**args).status, "DRY_RUN")
            with self.assertRaises(PaperOrderError):
                broker.place_paper_order(**args, dry_run=False)
            placed = broker.place_paper_order(**args, dry_run=False, confirmed=True)
            self.assertEqual(placed.broker_order_id, "paper-123")
            self.assertEqual(context.placed[0]["trd_env"], "SIMULATE")
            self.assertEqual(broker.place_paper_order(**args, dry_run=False, confirmed=True), placed)
            self.assertEqual(len(context.placed), 1)
            monitor = PaperMonitor(Path(tmp) / "snapshots")
            snapshot = monitor.sync(broker, strategy_id="s", strategy_version="1.0.0", data_version="v1")
            self.assertEqual(monitor.compare_positions(snapshot, {"HK.00700": 200})[0]["reason"],
                             "UNEXPLAINED_POSITION_MISMATCH")

    def test_lifecycle_requires_evidence_and_valid_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            lifecycle = StrategyLifecycle(Path(tmp) / "lifecycle.sqlite3")
            with self.assertRaises(ValueError):
                lifecycle.transition("s", "1.0.0", "PAPER_TRADING", actor="me", reason="test", evidence_id="x")
            lifecycle.transition("s", "1.0.0", "BACKTESTED", actor="me", reason="reviewed", evidence_id="run1")
            self.assertEqual(lifecycle.current("s", "1.0.0"), "BACKTESTED")


if __name__ == "__main__":
    unittest.main()
