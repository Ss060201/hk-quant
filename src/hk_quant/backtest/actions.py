"""Explicit action accounting: entitlements are assets, not spendable cash.

Unverified events and rights requiring an election block the run. No fair value
or FX conversion is invented. A verified in-kind event needs recipient prices.
"""
from __future__ import annotations

import math
import pandas as pd

from hk_quant.portfolio.models import Position


class ActionLedger:
    def __init__(self, actions, *, policy="strict"):
        if policy not in {"strict","price_only","legacy_exploratory"}:
            raise ValueError("unknown corporate action policy")
        self.policy = policy
        self.actions = actions.to_dict("records") if not actions.empty else []
        self.receivables = []
        self.records = []

    @property
    def value(self):
        return sum(item["amount"] for item in self.receivables)

    def apply(self, day, portfolio, row_map, marks):
        cash_paid = 0.0
        entering = {s:p.quantity for s,p in portfolio.positions.items()}
        for action in self.actions:
            if pd.isna(action.get("event_date")) or pd.Timestamp(action["event_date"]).date() != day:
                continue
            stock = str(action["stock_id"])
            quantity = entering.get(stock,0)
            if not quantity:
                continue
            kind = action.get("action_type")
            if kind == "dividend" and self.policy == "price_only":
                continue
            if self.policy != "legacy_exploratory" and action.get("verified") is not True:
                raise ValueError(f"UNVERIFIED_CORPORATE_ACTION: {stock} {day} {kind}")
            if kind == "dividend":
                per_share = float(action.get("cash_amount",float("nan")))
                if not math.isfinite(per_share) or per_share < 0:
                    raise ValueError("invalid cash dividend amount")
                if self.policy == "legacy_exploratory":
                    payment = day
                else:
                    if action.get("currency") != "HKD" or pd.isna(action.get("payment_date")):
                        raise ValueError("DIVIDEND_CURRENCY_OR_PAYMENT_DATE_REQUIRED")
                    payment = pd.Timestamp(action["payment_date"]).date()
                    if payment < day:
                        raise ValueError("dividend payment cannot precede ex-date")
                amount = quantity * per_share
                self.receivables.append({"amount":amount,"payment_date":payment})
                self.records.append({"event_date":str(day),"stock_id":stock,"shares":quantity,
                                     "cash_per_share":per_share,"cash_flow":amount,"payment_date":str(payment)})
            elif kind in {"split","bonus"}:
                factor = float(action.get("factor",float("nan")))
                new_quantity = quantity * factor
                if not math.isfinite(factor) or factor <= 0 or not math.isclose(new_quantity,round(new_quantity),abs_tol=1e-8):
                    raise ValueError("verified positive split factor and whole-share entitlement required")
                position = portfolio.positions[stock]
                position.quantity = round(new_quantity)
                position.cost_basis /= factor
                if stock in marks:
                    marks[stock] /= factor
            elif kind == "distribution_in_kind":
                if self.policy == "legacy_exploratory":
                    continue
                recipient = str(action.get("recipient_stock_id", ""))
                ratio = float(action.get("recipient_ratio",float("nan")))
                units = quantity * ratio
                if not recipient or not math.isfinite(units) or units <= 0 or not math.isclose(units,round(units),abs_tol=1e-8):
                    raise ValueError("IN_KIND_RECIPIENT_AND_WHOLE_SHARE_RATIO_REQUIRED")
                if pd.isna(action.get("delivery_date")) or pd.Timestamp(action["delivery_date"]).date() != day:
                    raise ValueError("IN_KIND_DELAYED_DELIVERY_NOT_MODELED")
                row = row_map.get(recipient)
                if not row or not math.isfinite(float(row.get("open",float("nan")))) or float(row["open"]) <= 0:
                    raise ValueError("IN_KIND_RECIPIENT_RAW_PRICE_REQUIRED")
                old = portfolio.positions.get(recipient)
                if old:
                    old.cost_basis = old.cost_basis*old.quantity/(old.quantity+round(units))
                    old.quantity += round(units)
                else:
                    portfolio.positions[recipient] = Position(recipient,round(units),0.0,str(day))
                marks[recipient] = float(row["open"])
            else:
                raise ValueError(f"UNMODELED_CORPORATE_ACTION: {stock} {day} {kind}")
        unpaid = []
        for item in self.receivables:
            if item["payment_date"] <= day:
                portfolio.cash += item["amount"]
                cash_paid += item["amount"]
            else:
                unpaid.append(item)
        self.receivables = unpaid
        return cash_paid
