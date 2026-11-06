"""Small declarative strategy contract; no eval or arbitrary code execution."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
import hashlib
import json
import math
import re

import pandas as pd

from hk_quant.data.normalization import normalize_stock_id

PRICE_FIELDS = {"open", "high", "low", "close", "volume", "amount", "turnover_rate"}
DERIVED = {"momentum", "volatility", "sma", "rsi", "volume_ratio"}
OPS = {">", ">=", "<", "<=", "==", "!="}


def field_info(name):
    if name in PRICE_FIELDS:
        return name, None
    match = re.fullmatch(r"(momentum|volatility|sma|rsi|volume_ratio)_(\d+)", name)
    if match and 2 <= int(match[2]) <= 756:
        return match[1], int(match[2])
    if re.fullmatch(r"fundamental\.[A-Za-z][A-Za-z0-9_]{0,79}", name):
        return "fundamental", name.split(".", 1)[1]
    raise ValueError(f"unsupported strategy field: {name}")


@dataclass(frozen=True)
class ResearchSpec:
    name: str
    stocks: list[str]
    start: str
    end: str
    score: str
    top_n: int
    rebalance: int
    filters: list[dict] = field(default_factory=list)
    ascending: bool = False
    action_policy: str = "strict"
    commission_rate: float = 0.001
    slippage_rate: float = 0.001
    initial_capital: float = 1_000_000
    warmup_days: int = 400
    universe: str = "explicit"

    @classmethod
    def from_dict(cls, value):
        spec = cls(**value)
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", spec.name):
            raise ValueError("name must be a short safe identifier")
        if not isinstance(spec.stocks,list) or any(not re.fullmatch(r"(?:HK\.)?\d{1,5}(?:\.HK)?",str(x),re.I) for x in spec.stocks):
            raise ValueError("stocks must be explicit HK numeric symbols")
        ids = [normalize_stock_id(x) for x in spec.stocks]
        if not ids or len(ids) != len(set(ids)) or len(ids) > 3000:
            raise ValueError("stocks must contain 1..3000 distinct explicit symbols")
        for key in ("start", "end"):
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", getattr(spec, key)):
                raise ValueError("dates must be YYYY-MM-DD")
        if pd.Timestamp(spec.start) > pd.Timestamp(spec.end):
            raise ValueError("start exceeds end")
        if pd.Timestamp(spec.end).date() >= pd.Timestamp.now("Asia/Hong_Kong").date():
            raise ValueError("use completed historical days, ending before today in Hong Kong")
        for key, maximum in (("top_n",len(ids)), ("rebalance",756), ("warmup_days",3000)):
            n = getattr(spec,key)
            if isinstance(n,bool) or not isinstance(n,int) or not 1 <= n <= maximum:
                raise ValueError(f"invalid {key}")
        if not isinstance(spec.ascending,bool) or spec.action_policy not in {"strict", "price_only"}:
            raise ValueError("invalid ascending or action_policy")
        if spec.universe not in {"explicit", "historical"}:
            raise ValueError("universe must be explicit or historical")
        if len(spec.filters) > 20:
            raise ValueError("at most 20 filters")
        for rule in spec.filters:
            if set(rule) != {"field", "op", "value"} or rule["op"] not in OPS:
                raise ValueError("filters require field, op and numeric value")
            if isinstance(rule["value"],bool) or not isinstance(rule["value"],(float,int)) or not math.isfinite(rule["value"]):
                raise ValueError("filter value must be finite")
        for name in spec.fields:
            field_info(name)
        from hk_quant.backtest.models import BacktestConfig
        BacktestConfig(initial_capital=spec.initial_capital, commission_rate=spec.commission_rate,
                       slippage_rate=spec.slippage_rate)
        object.__setattr__(spec,"stocks",ids)
        return spec

    @property
    def fields(self):
        return sorted({self.score, *(rule["field"] for rule in self.filters)})

    @property
    def required_prices(self):
        return sorted({"open", "high", "low", "close", "volume"} | (set(self.fields) & PRICE_FIELDS))

    @property
    def metrics(self):
        return [name.split(".",1)[1] for name in self.fields if name.startswith("fundamental.")]

    @property
    def digest(self):
        return hashlib.sha256(json.dumps(asdict(self),sort_keys=True).encode()).hexdigest()

    def to_dict(self):
        return asdict(self)
