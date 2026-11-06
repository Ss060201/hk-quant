"""Bounded HK data clients. Financial responses are observations, not verified PIT.

Report identifiers were checked against HKUDS/Vibe-Trading's financial statement
client. This implementation uses its own transport and schema; no upstream code
is copied. Endpoint availability and licensing are separate from code licensing.
"""
from __future__ import annotations

import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

from hk_quant.data.normalization import canonicalize_daily_prices, normalize_stock_id


def get_json(url: str, params: dict) -> dict:
    request = Request(url + "?" + urlencode(params), headers={"User-Agent": "hk-quant/0.2"})
    with urlopen(request, timeout=20) as response:
        payload = response.read(20_000_001)
    if len(payload) > 20_000_000:
        raise ValueError("provider response exceeds 20 MB")
    result = json.loads(payload)
    if not isinstance(result, dict):
        raise ValueError("provider response is not an object")
    return result


class EastmoneyHKProvider:
    name = "eastmoney_hk"
    fields = frozenset({"open", "high", "low", "close", "volume", "amount", "turnover_rate"})

    def __init__(self, transport=get_json):
        self.transport = transport

    def fetch_raw_daily_prices(self, stock_ids, start_date, end_date):
        frames = []
        for symbol in stock_ids:
            stock = normalize_stock_id(symbol)
            payload = self.transport("https://push2his.eastmoney.com/api/qt/stock/kline/get", {
                "secid": f"116.{stock.zfill(5)}", "klt": "101", "fqt": "0",
                "beg": str(start_date).replace("-", ""), "end": str(end_date).replace("-", ""),
                "lmt": "100000", "fields1": "f1,f2,f3,f4,f5,f6",
                "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            })
            if payload.get("rc", 0) != 0:
                raise ValueError("Eastmoney rejected daily price request")
            data = payload.get("data") or {}
            if data.get("code") and str(data["code"]).zfill(5) != stock.zfill(5):
                raise ValueError("Eastmoney returned another security")
            rows = [line.split(",") for line in data.get("klines", [])]
            if not rows:
                continue
            if any(len(row) != 11 for row in rows):
                raise ValueError("Eastmoney daily schema changed")
            frame = pd.DataFrame(rows, columns=["date", "open", "close", "high", "low",
                "volume", "amount", "amplitude_pct", "change_pct", "change", "turnover_pct"])
            frame["symbol"] = stock.zfill(5)
            frame["fetched_at"] = pd.Timestamp.now("UTC")
            frames.append(frame)
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    def normalize_daily_prices(self, raw, stock_id):
        frame = raw.rename(columns={"date": "trade_date"}).copy()
        frame["stock_id"] = normalize_stock_id(stock_id)
        # Provider percentages -> canonical ratios, exactly once: 0.45 -> 0.0045.
        frame["turnover_rate"] = pd.to_numeric(frame["turnover_pct"], errors="coerce") / 100
        return canonicalize_daily_prices(frame, self.name)

    def get_daily_prices(self, stock_ids, start_date, end_date):
        frames = []
        for stock in stock_ids:
            raw = self.fetch_raw_daily_prices([stock], start_date, end_date)
            if not raw.empty:
                frames.append(self.normalize_daily_prices(raw, stock))
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


class EastmoneyHKFinancials:
    name = "eastmoney_hk_financials"
    reports = {"income": "RPT_HKF10_FN_INCOME", "balance": "RPT_HKF10_FN_BALANCE",
               "cashflow": "RPT_HKF10_FN_CASHFLOW", "indicators": "RPT_HKF10_FN_GMAININDICATOR"}

    def __init__(self, transport=get_json):
        self.transport = transport

    def fetch(self, stock_id, statement):
        report = self.reports[statement]
        rows, seen = [], set()
        for page in range(1, 21):
            payload = self.transport("https://datacenter.eastmoney.com/securities/api/data/v1/get", {
                "reportName": report, "columns": "ALL",
                "filter": f'(SECURITY_CODE="{normalize_stock_id(stock_id).zfill(5)}")',
                "sortColumns": "REPORT_DATE", "sortTypes": "-1",
                "pageNumber": str(page), "pageSize": "100", "source": "F10", "client": "PC",
            })
            if payload.get("success") is False:
                raise ValueError("Eastmoney rejected financial report request")
            result = payload.get("result")
            if not isinstance(result, dict):
                raise ValueError("financial response has no result; not a successful empty dataset")
            batch = result.get("data") or []
            signature = json.dumps(batch, sort_keys=True)
            if batch and signature in seen:
                raise ValueError("financial pagination made no progress")
            seen.add(signature)
            rows.extend(batch)
            if page >= int(result.get("pages", 1)):
                break
        else:
            raise ValueError("financial pagination budget exceeded")
        return {"stock_id": normalize_stock_id(stock_id), "statement": statement,
                "source": self.name, "fetched_at": pd.Timestamp.now("UTC").isoformat(),
                "historical_pit_verified": False, "rows": rows}

    def fetch_snapshot(self, stock_ids):
        """Save current valuation fields as a timestamped snapshot, never history."""
        from hk_quant.data.adapters.calls import call_akshare
        frame = call_akshare("stock_hk_spot_em")
        if frame is None or frame.empty or "代码" not in frame:
            raise ValueError("empty or unknown HK spot schema")
        frame = frame.copy()
        frame["stock_id"] = frame["代码"].map(normalize_stock_id)
        frame = frame[frame.stock_id.isin(stock_ids)]
        return {"fetched_at": pd.Timestamp.now("UTC").isoformat(), "kind": "current_snapshot",
                "source": "akshare_eastmoney_spot", "rows": json.loads(frame.to_json(orient="records"))}
