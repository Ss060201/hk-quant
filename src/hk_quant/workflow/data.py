"""Bounded downloads, conservative merges and explicit coverage reports."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import timedelta
import hashlib
import json
import math
from pathlib import Path
import shutil
import time
import uuid

import pandas as pd

from hk_quant.data.quality import validate_daily_prices
from hk_quant.data.storage import DataStorage
from hk_quant.data.adapters.akshare import AKShareProvider
from hk_quant.data.adapters.tencent import TencentHKProvider
from hk_quant.data.adapters.eastmoney import EastmoneyHKProvider, EastmoneyHKFinancials
from hk_quant.workflow.spec import ResearchSpec
from hk_quant.workflow.conflicts import persist_conflicts, relevant_conflicts, unresolved_conflicts, ConflictHistoryError

OHLCV = ["open", "high", "low", "close", "volume"]


@contextmanager
def writer_lock(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    lock = root / ".workflow.lock"
    try:
        stream = lock.open("x", encoding="utf-8")
    except FileExistsError as exc:
        raise RuntimeError("another update is running; inspect .workflow.lock after an interrupted run") from exc
    try:
        with stream:
            stream.write(json.dumps({"started": pd.Timestamp.now("UTC").isoformat()}))
        yield
    finally:
        lock.unlink(missing_ok=True)


def merge_prices(existing, incoming):
    """Never replace a conflicting observation or silently erase an optional field.

    Missing fields can be supplemented only when every OHLCV value agrees.
    Returned conflicts block readiness but leave previously stored data intact.
    """
    records, conflicts = {}, []
    for frame in (existing, incoming):
        for raw in frame.to_dict("records"):
            row = dict(raw)
            key = (str(row["stock_id"]), pd.Timestamp(row["trade_date"]).date())
            row["trade_date"] = key[1]
            old = records.get(key)
            if old is None:
                if not isinstance(row.get("field_sources"),str):
                    row["field_sources"] = json.dumps({c: str(row.get("source")) for c in OHLCV + ["amount", "turnover_rate"] if pd.notna(row.get(c))},sort_keys=True)
                records[key] = row
                continue
            differences = [c for c in OHLCV if not math.isclose(float(old[c]),float(row[c]),rel_tol=1e-6,abs_tol=1e-8)]
            for c in ("amount", "turnover_rate"):
                if pd.notna(old.get(c)) and pd.notna(row.get(c)) and not math.isclose(float(old[c]),float(row[c]),rel_tol=1e-6,abs_tol=1e-8):
                    differences.append(c)
            if differences:
                conflicts.append({"stock_id":key[0], "date":str(key[1]), "fields":differences,
                                  "stored_values":{c:float(old[c]) for c in differences},
                                  "incoming_values":{c:float(row[c]) for c in differences},
                                  "stored_source":old.get("source"), "incoming_source":row.get("source")})
                continue
            provenance = json.loads(old.get("field_sources") or "{}")
            for c in ("amount", "turnover_rate"):
                if pd.isna(old.get(c)) and pd.notna(row.get(c)):
                    old[c] = row[c]
                    provenance[c] = row.get("source")
            old["field_sources"] = json.dumps(provenance,sort_keys=True)
    return pd.DataFrame(list(records.values())), conflicts


class DataRouter:
    def __init__(self, providers=None, *, attempts=2, delay=0.25):
        self.providers = providers if providers is not None else [EastmoneyHKProvider(),AKShareProvider(),TencentHKProvider()]
        if not 1 <= attempts <= 3:
            raise ValueError("attempts must be 1..3")
        self.attempts, self.delay = attempts, delay
        self.next_request = 0.0

    def fetch(self, stock, start, end, required, existing, expected, storage, run_dir):
        merged, failures, conflicts = existing.copy(), [], []
        raw_root = Path(run_dir) / "responses"
        raw_root.mkdir(parents=True,exist_ok=True)
        for provider in self.providers:
            for attempt in range(self.attempts):
                try:
                    pause = self.next_request - time.monotonic()
                    if pause > 0:
                        time.sleep(min(pause, 1.0))
                    self.next_request = time.monotonic() + self.delay
                    raw = provider.fetch_raw_daily_prices([stock],start,end)
                    if raw.empty:
                        raise ValueError("EMPTY_RESPONSE")
                    raw_path = raw_root / f"{stock}-{provider.name}-{attempt}.json"
                    raw_path.write_text(raw.to_json(orient="table",date_format="iso"),encoding="utf-8")
                    normalized = provider.normalize_daily_prices(raw,stock)
                    validate_daily_prices(normalized,required_fields=OHLCV)
                    dates = pd.to_datetime(normalized.trade_date)
                    if not dates.between(pd.Timestamp(start),pd.Timestamp(end)).all():
                        raise ValueError("OUT_OF_RANGE_RESPONSE")
                    merged, issues = merge_prices(merged,normalized)
                    if issues:
                        # Persist before returning or saving merged prices, including
                        # when a later provider or disk write fails.
                        if Path(run_dir).parent.name != "preparations":
                            raise ConflictHistoryError("conflicts require a data/preparations/run directory")
                        persist_conflicts(Path(run_dir).parent.parent, issues)
                    conflicts.extend(issues)
                    break
                except ConflictHistoryError:
                    raise
                except Exception as exc:
                    failures.append({"stock_id":stock,"source":provider.name,"attempt":attempt+1,
                                     "error":f"{type(exc).__name__}: {exc}"[:400]})
                    if attempt + 1 < self.attempts:
                        time.sleep(self.delay * (2 ** attempt))
            if not merged.empty:
                available = set(pd.to_datetime(merged.trade_date).dt.date)
                has_fields = not merged[required].isna().any().any()
                # With no independent calendar, try remaining sources. An observed
                # date union never establishes full coverage by itself.
                if expected is not None and set(expected).issubset(available) and has_fields:
                    break
        return merged, failures, conflicts


def expected_sessions(root, start, end):
    """Use an explicitly sourced local reference; do not fabricate weekdays."""
    path = Path(root) / "reference" / "calendar.json"
    if not path.exists():
        try:
            import exchange_calendars as xcals
        except ImportError:
            return None
        calendar = xcals.get_calendar("XHKG", start=start, end=end)
        dates = calendar.sessions_in_range(start,end)
        # This is a rule-based independent calendar, not an HKEX-certified feed.
        return [pd.Timestamp(day).date() for day in dates]
    data = json.loads(path.read_text(encoding="utf-8"))
    if not data.get("source_url") or not data.get("verified"):
        raise ValueError("calendar reference needs source_url and verified=true")
    if data["start"] > start or data["end"] < end:
        raise ValueError("calendar reference does not cover the requested range")
    return sorted({pd.Timestamp(x).date() for x in data["sessions"] if start <= x <= end})


def prepare_data(spec: ResearchSpec, root="data", *, router=None, refresh=False, fetch_financials=True,
                 storage_factory=DataStorage, actions_provider=None, financials_provider=None, budget_seconds=600):
    """Update each symbol independently; a failure yields BLOCKED, never success.

    Output includes exact missing dates/fields, quarantined response diagnostics,
    data version and a unique persistent preparation record.
    """
    root = Path(root).resolve()
    with writer_lock(root):
        return _prepare(spec,root,router or DataRouter(),refresh,fetch_financials,
                        storage_factory,actions_provider,financials_provider,budget_seconds)


def _prepare(spec, root, router, refresh, fetch_financials, storage_factory, actions_provider, financials_provider, budget_seconds):
    storage = storage_factory(root/"raw",root/"processed")
    deadline = time.monotonic() + budget_seconds
    run_id = uuid.uuid4().hex
    run_dir = root / "preparations" / run_id
    run_dir.mkdir(parents=True,exist_ok=False)
    start = (pd.Timestamp(spec.start)-timedelta(days=spec.warmup_days)).date().isoformat()
    blockers, failures, conflicts, rows = [], [], [], []
    conflicts = relevant_conflicts(spec, unresolved_conflicts(root, persist_conflicts(root)))
    try:
        sessions = expected_sessions(root,spec.start,spec.end)
    except ValueError as exc:
        sessions = None
        blockers.append(str(exc))
    if sessions is None:
        blockers.append("INDEPENDENT_CALENDAR_REQUIRED: import a sourced calendar covering the research dates")
    for stock in spec.stocks:
        if time.monotonic() > deadline:
            blockers.append(f"{stock}: UPDATE_BUDGET_EXCEEDED; rerun resumes saved stocks")
            continue
        existing = storage.load_daily_prices(stock,start,spec.end)
        if not existing.empty:
            try:
                validate_daily_prices(existing,required_fields=OHLCV)
            except ValueError:
                raise
            except Exception as exc:
                blockers.append(f"{stock}: stored data invalid: {exc}")
                continue
        available = set(pd.to_datetime(existing.trade_date).dt.date) if not existing.empty else set()
        missing = set(sessions or [])-available
        incomplete = existing.empty or any(c not in existing or existing[c].isna().any() for c in spec.required_prices)
        # Once a complete snapshot exists, unchanged reruns avoid requests.
        needed = refresh or incomplete or missing or sessions is None
        if needed:
            fetch_start = start
            if not refresh and not existing.empty and not incomplete and missing and min(missing) > max(available):
                fetch_start = min(missing).isoformat()
            merged, errors, issues = router.fetch(stock,fetch_start,spec.end,spec.required_prices,
                                                  existing,sessions,storage,run_dir)
            failures.extend(errors); conflicts.extend(issues)
            if not merged.empty:
                for period in pd.to_datetime(merged.trade_date).dt.to_period("M").unique():
                    relative = Path("daily_prices")/stock/f"{period.year:04d}"/f"{period.month:02d}"/"data.parquet"
                    original = root/"processed"/relative
                    if original.exists():
                        backup = run_dir/"before_processed"/relative
                        backup.parent.mkdir(parents=True,exist_ok=True)
                        shutil.copy2(original,backup)
                storage.save_daily_prices(merged)
        else:
            merged = existing
        if merged.empty:
            blockers.append(f"{stock}: NO_PRICES")
            rows.append({"stock_id":stock,"rows":0}); continue
        dates = pd.to_datetime(merged.trade_date)
        sample = merged[dates.between(spec.start,spec.end)]
        missing = sorted(set(sessions or [])-set(pd.to_datetime(sample.trade_date).dt.date))
        nulls = {c:int(sample[c].isna().sum()) for c in spec.required_prices}
        rows.append({"stock_id":stock,"rows":len(sample),"first":str(dates.min().date()),
                     "last":str(dates.max().date()),"missing_dates":[str(x) for x in missing],"nulls":nulls})
        if sample.empty or missing or any(nulls.values()):
            blockers.append(f"{stock}: required prices/fields missing; see stocks report")
    conflicts = relevant_conflicts(spec, unresolved_conflicts(root, persist_conflicts(root, conflicts)))
    if conflicts:
        blockers.append("SOURCE_CONFLICT: existing values retained; unresolved conflicts need a sourced correction")

    # Corporate actions are independently fetched so an endpoint failure cannot
    # erase prices or a previously stored action history.
    from hk_quant.data.ingestion import ingest_corporate_actions
    original = root/"processed"/"corporate_actions"/"corporate_actions.parquet"
    if original.exists():
        target=run_dir/"before_processed"/"corporate_actions.parquet"
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(original,target)
    for stock in spec.stocks:
        if time.monotonic() > deadline:
            failures.append({"stock_id":stock,"source":"corporate_actions","error":"UPDATE_BUDGET_EXCEEDED"})
            continue
        try:
            ingest_corporate_actions(storage=storage,provider=actions_provider or AKShareProvider(),stock_ids=[stock],overwrite=False)
        except Exception as exc:
            failures.append({"stock_id":stock,"source":"corporate_actions","error":str(exc)[:400]})
    financials = financials_provider or EastmoneyHKFinancials()
    try:
        if time.monotonic() > deadline:raise TimeoutError("UPDATE_BUDGET_EXCEEDED")
        storage._atomic_json(financials.fetch_snapshot(spec.stocks),run_dir/"valuation-snapshot.json")
    except Exception as exc:
        failures.append({"source":"valuation_snapshot","error":str(exc)[:400]})
    if spec.metrics and fetch_financials:
        for stock in spec.stocks:
            for statement in financials.reports:
                try:
                    if time.monotonic() > deadline:raise TimeoutError("UPDATE_BUDGET_EXCEEDED")
                    response = financials.fetch(stock,statement)
                    storage._atomic_json(response, run_dir / "financials" / f"{stock}-{statement}.json")
                except Exception as exc:
                    failures.append({"stock_id":stock,"source":f"financials:{statement}","error":str(exc)[:400]})
        # Raw financial reports do NOT acquire a fake historical disclosure date.
    if spec.universe == "historical" and not (root/"reference"/"universe.json").exists():
        blockers.append("HISTORICAL_UNIVERSE_REQUIRED")
    from hk_quant.data.provenance import get_data_version
    report = {"run_id":run_id,"status":"BLOCKED" if blockers else "READY_FOR_PREFLIGHT",
              "spec":spec.to_dict(),"strategy_hash":spec.digest,"data_version":get_data_version(root/"processed"),
              "stocks":rows,"failures":failures,"conflicts":conflicts,"blockers":blockers,
              "limitations":["Provider availability is not independent accuracy verification.",
                              "Financial raw observations require verified availability dates before historical use.",
                              "Corporate action completeness is not established by nonempty rows."]}
    storage._atomic_json(report,run_dir/"report.json")
    return report
