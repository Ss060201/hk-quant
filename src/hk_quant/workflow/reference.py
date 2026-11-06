"""Sourced reference import and AASTOCKS/sample reconciliation.

References augment coverage; they never overwrite a market quote automatically.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
import uuid

import pandas as pd

from hk_quant.data.normalization import normalize_stock_id
from hk_quant.data.storage import DataStorage
from hk_quant.workflow.data import writer_lock

KINDS={"calendar","universe","facts","actions","action_coverage","quotes"}


def validate_reference(kind, data):
    if kind not in KINDS or not isinstance(data,dict): raise ValueError("unknown reference kind")
    if not isinstance(data.get("source_url"),str) or not data["source_url"].startswith(("https://","http://")):
        raise ValueError("source_url is required")
    if data.get("verified") is not True: raise ValueError("reference needs explicit verified=true")
    if kind=="calendar":
        start,end=pd.Timestamp(data["start"]),pd.Timestamp(data["end"])
        dates=[pd.Timestamp(d) for d in data["sessions"]]
        if start>end or len(dates)!=len(set(dates)) or any(d<start or d>end for d in dates):
            raise ValueError("invalid calendar dates")
        return data
    if not isinstance(data.get("rows"),list): raise ValueError("reference rows required")
    for row in data["rows"]:
        row["stock_id"]=normalize_stock_id(row["stock_id"])
        row.setdefault("source_url",data["source_url"])
        if kind=="facts":
            for name in ("period_end","available_date"):
                if pd.isna(pd.Timestamp(row[name])):raise ValueError(f"invalid {name}")
            if pd.Timestamp(row["available_date"])<pd.Timestamp(row["period_end"]):
                raise ValueError("financial availability precedes report period")
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,79}",row["metric"]): raise ValueError("invalid metric")
            if not math.isfinite(float(row["value"])) or not row.get("currency") or not row.get("unit"):
                raise ValueError("finite fact, currency and unit required")
            row["pit_verified"]=True
        elif kind=="universe":
            listed=pd.Timestamp(row["listing_date"])
            if row.get("delisting_date") and pd.Timestamp(row["delisting_date"])<listed:
                raise ValueError("delisting precedes listing")
        elif kind=="actions":
            pd.Timestamp(row["event_date"])
            row["verified"]=True
            row.setdefault("source","verified_reference")
            row.setdefault("ingested_at",pd.Timestamp.now("UTC").isoformat())
            row.setdefault("factor",None);row.setdefault("cash_amount",None)
            row.setdefault("announcement_date",None)
            if row["action_type"]=="dividend":
                if not row.get("currency") or not row.get("payment_date"):
                    raise ValueError("dividend currency and payment date required")
                if not math.isfinite(float(row["cash_amount"])) or float(row["cash_amount"])<0:
                    raise ValueError("invalid dividend")
            elif row["action_type"] in {"split","bonus"}:
                if not math.isfinite(float(row["factor"])) or float(row["factor"])<=0:
                    raise ValueError("invalid split factor")
            elif row["action_type"]=="distribution_in_kind":
                row["recipient_stock_id"]=normalize_stock_id(row["recipient_stock_id"])
            elif row["action_type"]!="rights": raise ValueError("unknown action type")
        elif kind=="action_coverage":
            if pd.Timestamp(row["start"])>pd.Timestamp(row["end"]): raise ValueError("invalid coverage interval")
            row["verified"]=True
    return data


def import_reference(kind, path, root="data"):
    data=validate_reference(kind,json.loads(Path(path).read_text(encoding="utf-8")))
    root=Path(root)
    with writer_lock(root):
        target=root/"reference"/f"{kind}.json"
        if target.exists():
            archive=root/"reference"/"history"/f"{kind}-{uuid.uuid4().hex}.json"
            archive.parent.mkdir(parents=True,exist_ok=True)
            archive.write_bytes(target.read_bytes())
        if target.exists() and kind=="facts":
            old=json.loads(target.read_text(encoding="utf-8"))
            data["rows"]=old["rows"]+data["rows"]
            keys={}
            for row in data["rows"]:
                key=tuple(row[k] for k in ("stock_id","metric","period_end","available_date"))
                if key in keys and keys[key]["value"]!=row["value"]:
                    raise ValueError("conflicting revisions need different verified availability dates")
                keys[key]=row
            data["rows"]=list(keys.values())
        DataStorage._atomic_json(data,target)
    return {"status":"IMPORTED","kind":kind,"rows":len(data.get("rows",data.get("sessions",[]))),
            "sha256":hashlib.sha256(target.read_bytes()).hexdigest()}


def display_interval(value):
    """Displayed 22.27M is a rounding interval, not 22,270,000 exact shares."""
    if isinstance(value,(int,float)):
        if not math.isfinite(value): raise ValueError("non-finite reference")
        return float(value),0.0
    text=str(value).strip().replace(",","")
    match=re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)([KMB]?)",text,re.I)
    if not match: raise ValueError("unknown displayed number")
    factor={"":1,"K":1e3,"M":1e6,"B":1e9}[match[2].upper()]
    decimals=len(match[1].partition(".")[2])
    return float(match[1])*factor, 0.5*factor*10**(-decimals)


def compare_quotes(quotes,prices):
    rows=[]
    mapping={"open":"open","high":"high","low":"low","close":"close","volume":"volume","turnover":"amount","turnover_rate":"turnover_rate"}
    for ref in quotes["rows"]:
        stock=normalize_stock_id(ref["stock_id"])
        day=pd.Timestamp(ref["trade_date"])
        sub=prices[(prices.stock_id==stock)&(pd.to_datetime(prices.trade_date)==day)]
        for external,local in mapping.items():
            if external not in ref: continue
            result={"stock_id":stock,"trade_date":str(day.date()),"field":local}
            if ref.get("currency")!="HKD" or ref.get("adjustment")!="raw_unadjusted":
                result["status"]="INCOMPARABLE_BASIS"
            elif external=="close" and ref.get("session_status")!="final":
                result["status"]="UNCONFIRMED_CLOSE"
            elif external!="open" and ref.get("session_status")!="final":
                result["status"]="UNCONFIRMED_SESSION"
            elif len(sub)!=1 or pd.isna(sub.iloc[0].get(local)):
                result["status"]="MISSING_LOCAL"
            elif external=="volume" and ref.get("volume_unit")!="shares":
                result["status"]="INCOMPARABLE_UNIT"
            else:
                value,tolerance=display_interval(ref[external])
                if external=="turnover_rate":
                    if ref.get("turnover_rate_unit")!="percent":
                        result["status"]="INCOMPARABLE_UNIT";rows.append(result);continue
                    value/=100;tolerance/=100
                actual=float(sub.iloc[0][local]); difference=abs(actual-value)
                result.update(status="MATCH" if difference<=tolerance+1e-8 else "MISMATCH",
                              reference=value,local=actual,tolerance=tolerance,difference=difference)
            rows.append(result)
    return {"rows":rows,"scope":"only these fields, securities and dates; no historical certification"}
