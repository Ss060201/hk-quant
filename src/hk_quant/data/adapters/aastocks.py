"""Small public quote samples for reconciliation, never a history backfill."""
from __future__ import annotations
from html.parser import HTMLParser
import re
from urllib.request import Request,urlopen

import pandas as pd

from hk_quant.data.normalization import normalize_stock_id


class _Text(HTMLParser):
    def __init__(self):
        super().__init__();self.parts=[];self.hidden=0
    def handle_starttag(self,tag,attrs):
        if tag in {"script","style"}:self.hidden+=1
    def handle_endtag(self,tag):
        if tag in {"script","style"}:self.hidden=max(0,self.hidden-1)
    def handle_data(self,data):
        if not self.hidden and data.strip():self.parts.append(data.strip())


def parse_quote(html,stock_id):
    parser=_Text();parser.feed(html)
    text=" ".join(parser.parts)
    code=normalize_stock_id(stock_id)
    if not re.search(r"\(0*"+str(int(code))+r"\)",text):
        raise ValueError("AASTOCKS page does not identify requested security")
    stamp=re.search(r"Last Updated\s*:?\s*(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})",text,re.I)
    if not stamp:raise ValueError("AASTOCKS quote timestamp missing; page is not a verified quote")
    row={"stock_id":code,"trade_date":stamp[1],"quote_time":stamp[2],
         "session_status":"unconfirmed","adjustment":"raw_unadjusted","volume_unit":"shares"}
    if not re.search(r"Lot Size\s*/\s*Currency\s+[^/]+/\s*HKD",text,re.I):
        raise ValueError("AASTOCKS HKD currency not identified")
    row["currency"]="HKD"
    for label,field in [("Open","open"),("Day High","high"),("Day Low","low"),
                         ("Last Price","close"),("Volume","volume"),("Turnover","turnover")]:
        match=re.search(r"\b"+label+r"\s*:?\s*([0-9][0-9,]*(?:\.[0-9]+)?[KMB]?)\b",text,re.I)
        if not match:raise ValueError(f"AASTOCKS field missing: {label}")
        row[field]=match[1]
    # A delayed quote at 16:08 does not prove final closing auction completion.
    return row


def capture_samples(stock_ids, fetch=None):
    if len(stock_ids)>7:raise ValueError("AASTOCKS sample limit is seven securities")
    rows,failures,raw=[],[],[]
    for stock in stock_ids:
        stock=normalize_stock_id(stock)
        url="https://www.aastocks.com/pkages/web/bankcomm/eng/whatshot/quote_v2.asp?symbol="+stock.zfill(5)
        try:
            if fetch is None:
                request=Request(url,headers={"User-Agent":"Mozilla/5.0"})
                with urlopen(request,timeout=20) as response:
                    payload=response.read(2_000_001)
                if len(payload)>2_000_000:raise ValueError("quote response too large")
                html=payload.decode("utf-8",errors="replace")
            else:html=fetch(url)
            raw.append({"url":url,"html":html})
            row=parse_quote(html,stock);row["source_url"]=url;rows.append(row)
        except Exception as exc:
            failures.append({"stock_id":stock,"error":str(exc)[:300]})
    return {"source_url":"https://www.aastocks.com/","verified":True,
            "verification_scope":"identity/date/currency parsed; final close NOT verified",
            "fetched_at":pd.Timestamp.now("UTC").isoformat(),"rows":rows,"failures":failures,"raw_pages":raw}
