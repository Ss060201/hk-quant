"""Replayable research over a frozen input bundle, with exposure tracking."""
from __future__ import annotations

import hashlib
import io
import json
import math
import operator
from pathlib import Path
import sqlite3
import uuid

import pandas as pd

from hk_quant.data.calendar import TradingCalendar
from hk_quant.data.quality import validate_daily_prices
from hk_quant.workflow.spec import ResearchSpec, field_info

OPS = {">":operator.gt, ">=":operator.ge, "<":operator.lt, "<=":operator.le,
       "==":operator.eq, "!=":operator.ne}


class FrozenRepository:
    """Only reads this run's captured frames; never reaches mutable live data."""
    def __init__(self, prices, actions, facts, sessions, *, universe=None, version=None):
        self.prices, self.actions, self.facts = prices.copy(), actions.copy(), facts.copy()
        self.sessions, self.universe = list(sessions), universe
        self.version = version or self.content_hash()

    def content_hash(self):
        data = self.to_dict()
        return "HK_FROZEN_" + hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()

    def get_daily_prices(self, stock_ids=None, start_date=None, end_date=None):
        frame = self.prices.copy()
        dates = pd.to_datetime(frame.trade_date)
        if stock_ids is not None:
            frame = frame[frame.stock_id.isin(stock_ids)]
        if start_date:
            frame = frame[dates.loc[frame.index] >= pd.Timestamp(start_date)]
        if end_date:
            frame = frame[dates.loc[frame.index] <= pd.Timestamp(end_date)]
        return frame

    def get_calendar(self):
        return TradingCalendar(self.sessions)

    def get_corporate_actions(self, stock_ids=None):
        return self.actions if self.actions.empty or stock_ids is None else self.actions[self.actions.stock_id.isin(stock_ids)]

    def get_data_version(self):
        return self.version

    def to_dict(self):
        return {"prices":self.prices.to_json(orient="table",date_format="iso"),
                "actions":self.actions.to_json(orient="table",date_format="iso"),
                "facts":self.facts.to_json(orient="table",date_format="iso"),
                "sessions":[str(pd.Timestamp(d).date()) for d in self.sessions],"universe":self.universe}

    @classmethod
    def from_dict(cls, data):
        return cls(*(pd.read_json(io.StringIO(data[name]),orient="table") for name in ("prices","actions","facts")),
                   data["sessions"],universe=data.get("universe"))


def fact_value(facts, stock, metric, day):
    if facts.empty:
        return None
    required = {"stock_id","metric","value","period_end","available_date","pit_verified","currency","unit","source_url"}
    if not required.issubset(facts.columns):
        return None
    subset = facts[(facts.stock_id==stock) & (facts.metric==metric) & (facts.pit_verified==True)].copy()
    # Date-only announcements become usable the NEXT day (release time unknown).
    known = pd.to_datetime(subset.available_date,errors="coerce")
    subset = subset[known < pd.Timestamp(day)]
    if subset.empty:
        return None
    subset = subset.sort_values(["period_end","available_date"])
    value = float(subset.iloc[-1]["value"])
    return value if math.isfinite(value) else None


def make_scorer(spec, repo):
    def field_value(name, sub, stock, day):
        kind, window = field_info(name)
        if kind == "fundamental":
            return fact_value(repo.facts,stock,window,day)
        if kind in sub.columns:
            value = sub.iloc[-1][kind]
            return float(value) if pd.notna(value) else None
        n = int(window)
        close = sub.close.astype(float)
        if len(sub) < n+1:
            return None
        if kind=="momentum": return float(close.iloc[-1]/close.iloc[-n-1]-1)
        if kind=="sma": return float(close.tail(n).mean())
        if kind=="volatility": return float(close.pct_change().tail(n).std(ddof=1))
        if kind=="volume_ratio":
            average = sub.volume.iloc[-n-1:-1].astype(float).mean()
            return float(sub.volume.iloc[-1]/average) if average>0 else None
        delta = close.diff().tail(n)
        up, down = delta.clip(lower=0).mean(), -delta.clip(upper=0).mean()
        return 50.0 if up==down==0 else (100.0 if down==0 else float(100-100/(1+up/down)))

    def scorer(history, stock):
        if history.empty: return None
        day = pd.to_datetime(history.trade_date).max()
        sub = history[history.stock_id==stock].sort_values("trade_date")
        if sub.empty or pd.Timestamp(sub.iloc[-1].trade_date)!=day or float(sub.iloc[-1].volume)<=0:
            return None
        if spec.universe=="historical":
            members = [r for r in (repo.universe or {}).get("rows",[]) if r["stock_id"]==stock]
            if not any(pd.Timestamp(r["listing_date"])<=day and (not r.get("delisting_date") or day<pd.Timestamp(r["delisting_date"])) for r in members):
                return None
        # Indicators use only verified split factors effective by this decision
        # date. Execution and portfolio valuation remain on original raw prices.
        sub=sub.copy()
        if not repo.actions.empty:
            for action in repo.actions.to_dict("records"):
                if action.get("stock_id")!=stock or action.get("action_type") not in {"split","bonus"}:
                    continue
                event=pd.Timestamp(action["event_date"])
                if event>day: continue
                if action.get("verified") is not True:
                    raise ValueError("unverified split cannot be used in indicator history")
                factor=float(action["factor"])
                if not math.isfinite(factor) or factor<=0:raise ValueError("invalid split factor")
                prior=pd.to_datetime(sub.trade_date)<event
                sub.loc[prior,["open","high","low","close"]]/=factor
                sub.loc[prior,"volume"]*=factor
        for rule in spec.filters:
            value = field_value(rule["field"],sub,stock,day)
            if value is None or not math.isfinite(value) or not OPS[rule["op"]](value,rule["value"]):
                return None
        score = field_value(spec.score,sub,stock,day)
        return None if score is None else (-score if spec.ascending else score)
    return scorer


def preflight(spec, repo, *, action_coverage=None):
    blockers = []
    days = repo.get_calendar().get_trading_days(spec.start,spec.end)
    if not days: blockers.append("NO_TRADING_SESSIONS")
    for stock in spec.stocks:
        frame = repo.get_daily_prices([stock],spec.start,spec.end)
        missing = sorted(set(days)-set(pd.to_datetime(frame.trade_date).dt.date))
        if missing: blockers.append(f"{stock}: missing sessions {','.join(map(str,missing[:10]))}")
        try: validate_daily_prices(frame,required_fields=spec.required_prices)
        except Exception as exc: blockers.append(f"{stock}: {exc}")
        needed=max([int(field_info(n)[1])+1 for n in spec.fields if field_info(n)[0] in {"momentum","volatility","sma","rsi","volume_ratio"}]+[1])
        if days and len(repo.get_daily_prices([stock],end_date=str(days[0])))<needed:
            blockers.append(f"{stock}: insufficient warmup; need {needed} observations by first session")
    if spec.universe=="historical":
        u=repo.universe or {}
        if not u.get("verified") or not u.get("includes_delisted") or not u.get("source_url"):
            blockers.append("VERIFIED_HISTORICAL_UNIVERSE_REQUIRED")
        else:
            eligible={r["stock_id"] for r in u["rows"] if r["listing_date"]<=spec.end and (not r.get("delisting_date") or r["delisting_date"]>spec.start)}
            if not eligible.issubset(set(spec.stocks)):
                blockers.append("HISTORICAL_UNIVERSE_MEMBERS_MISSING_FROM_STOCKS")
    coverage = action_coverage or {}
    for stock in spec.stocks:
        entry = coverage.get(stock,{})
        if not entry.get("verified") or not entry.get("source_url") or entry.get("start","9999")>spec.start or entry.get("end","")<spec.end:
            blockers.append(f"{stock}: VERIFIED_CORPORATE_ACTION_COVERAGE_REQUIRED")
    for metric in spec.metrics:
        if not repo.facts.empty and "metric" in repo.facts:
            relevant=repo.facts[repo.facts.metric==metric]
            if not relevant.empty and {"currency","unit"}.issubset(relevant):
                if len(relevant[["currency","unit"]].drop_duplicates())>1:
                    blockers.append(f"{metric}: INCOMPATIBLE_FINANCIAL_UNITS_OR_CURRENCIES")
        for stock in spec.stocks:
            for day in days[::spec.rebalance]:
                if fact_value(repo.facts,stock,metric,day) is None:
                    blockers.append(f"{stock}: no verified {metric} available before {day}");break
    return list(dict.fromkeys(blockers))


def run_frozen(spec, repo, output_root="experiments/workflows", *, action_coverage=None):
    blockers = preflight(spec,repo,action_coverage=action_coverage)
    if blockers: return {"status":"BLOCKED","blockers":blockers,"strategy_hash":spec.digest}
    from hk_quant.backtest.models import BacktestConfig
    from hk_quant.backtest.ranking import run_ranking_backtest
    root=Path(output_root);root.mkdir(parents=True,exist_ok=True)
    run_id=uuid.uuid4().hex; dest=root/run_id;dest.mkdir(exist_ok=False)
    payload={"spec":spec.to_dict(),"data":repo.to_dict(),"action_coverage":action_coverage}
    snapshot=json.dumps(payload,sort_keys=True,ensure_ascii=False)
    (dest/"snapshot.json").write_text(snapshot,encoding="utf-8")
    digest=hashlib.sha256(snapshot.encode()).hexdigest()
    (dest/"snapshot.sha256").write_text(digest,encoding="ascii")
    # Record exposure BEFORE evaluating; a failed run can still expose data.
    # NOTE: sqlite3.Connection used as a context manager commits/rolls back but does
    # NOT close the handle; on Windows an open handle keeps the file locked and the
    # temp directory cannot be removed. Close explicitly.
    connection = sqlite3.connect(root/"exposure.sqlite3")
    try:
        with connection:
            connection.execute("CREATE TABLE IF NOT EXISTS exposure (run_id TEXT PRIMARY KEY, start TEXT, end TEXT, strategy_hash TEXT, data_version TEXT)")
            connection.execute("INSERT INTO exposure VALUES (?,?,?,?,?)",(run_id,spec.start,spec.end,spec.digest,repo.version))
    finally:
        connection.close()
    config=BacktestConfig(initial_capital=spec.initial_capital,commission_rate=spec.commission_rate,slippage_rate=spec.slippage_rate)
    common=dict(repository=repo,stock_ids=spec.stocks,start_date=spec.start,end_date=spec.end,config=config,action_policy=spec.action_policy)
    try:
        candidate=run_ranking_backtest(**common,scorer=make_scorer(spec,repo),top_n=spec.top_n,rebalance_frequency=spec.rebalance)
        baseline=run_ranking_backtest(**common,scorer=lambda h,s: 1.0 if not h[h.stock_id==s].empty else None,
                                      top_n=len(spec.stocks),rebalance_frequency=spec.rebalance)
        for name,result in (("candidate",candidate),("baseline",baseline)):
            for table in ("daily","orders","trades","decisions","dividends","positions"):
                getattr(result,table).to_csv(dest/f"{name}-{table}.csv",index=False)
        report={"status":"EXPLORATORY","run_id":run_id,"strategy_hash":spec.digest,"data_version":repo.version,
                "snapshot_sha256":digest,"candidate":candidate.metrics,"baseline":baseline.metrics,
                "baseline_name":"equal_weight_same_rebalance_schedule","config":config.to_dict(),
                "untouched_final_test":False,"exposed_interval":[spec.start,spec.end],
                "warnings":list(dict.fromkeys(candidate.warnings+baseline.warnings)),
                "action_policy":spec.action_policy,"spec":spec.to_dict()}
    except Exception as exc:
        report={"status":"BLOCKED","run_id":run_id,"blockers":[f"{type(exc).__name__}: {exc}"],"snapshot_sha256":digest}
    (dest/"report.json").write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding="utf-8")
    return report


def replay(snapshot_path, output_root):
    path=Path(snapshot_path)
    text=path.read_text(encoding="utf-8")
    if hashlib.sha256(text.encode()).hexdigest()!=path.with_suffix(".sha256").read_text().strip():
        raise ValueError("snapshot checksum mismatch")
    payload=json.loads(text)
    return run_frozen(ResearchSpec.from_dict(payload["spec"]),FrozenRepository.from_dict(payload["data"]),output_root,
                      action_coverage=payload["action_coverage"])
