"""Futu OpenD adapter restricted to a verified HK stock simulation account.

Requires the optional ``futu-api`` SDK and a locally running OpenD. No OpenD
session or paper account is available in this repository; the adapter must be
tested against a user's own verified PAPER account before enabling writes.
Official API: https://openapi.futunn.com/futu-api-doc/en/qa/trade.html
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


@contextmanager
def _journal_db(path: str | Path) -> Iterator[sqlite3.Connection]:
    """Open a SQLite journal, commit the transaction, and always close."""
    connection = sqlite3.connect(path)
    try:
        with connection:
            yield connection
    finally:
        connection.close()


_HK_CODE = re.compile(r"^HK\.\d{5}$")


def _label(value: Any) -> str:
    return str(getattr(value, "value", value)).split(".")[-1].upper()


def _finite_number(value: Any) -> float:
    if isinstance(value, bool):
        raise PaperOrderError("boolean is not a valid amount")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise PaperOrderError("broker amount is missing or invalid") from exc
    if not math.isfinite(number):
        raise PaperOrderError("broker amount is not finite")
    return number


class PaperOrderError(RuntimeError):
    """Paper account or order state is unsafe or unavailable."""


@dataclass(frozen=True)
class PaperOrder:
    client_order_id: str
    code: str
    side: str
    qty: int
    limit_price: float
    broker_order_id: str | None = None
    status: str = "DRY_RUN"


class FutuPaperBroker:
    """Explicit SIMULATE-only wrapper; no live order method exists.

    The caller supplies an HK-filtered SDK context and an explicit account ID.
    A fake context can be used for tests. Never fall back to acc_index=0.
    """

    def __init__(self, context: Any, sdk: Any, *, account_id: int,
                 journal_path: str | Path, allow_paper_orders: bool = False,
                 quote_context: Any = None) -> None:
        if isinstance(account_id, bool) or not isinstance(account_id, int) or account_id <= 0:
            raise PaperOrderError("explicit positive paper account ID required")
        self.context = context
        self.sdk = sdk
        self.quote_context = quote_context
        self.account_id = account_id
        self.allow_paper_orders = allow_paper_orders
        self.journal_path = Path(journal_path)
        self.journal_path.parent.mkdir(parents=True, exist_ok=True)
        with _journal_db(self.journal_path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS orders (
                client_order_id TEXT PRIMARY KEY, payload TEXT NOT NULL,
                status TEXT NOT NULL, updated_at TEXT NOT NULL
            )""")
        self._verify_account()

    @classmethod
    def connect_local(cls, *, account_id: int, journal_path: str | Path,
                      port: int = 11111, allow_paper_orders: bool = False) -> "FutuPaperBroker":
        """Connect only to local HK OpenD; importing SDK never places an order."""
        try:
            import futu  # type: ignore[import-not-found]
        except ImportError as exc:
            raise PaperOrderError("install optional futu-api and run local OpenD") from exc
        context = futu.OpenSecTradeContext(
            filter_trdmarket=futu.TrdMarket.HK, host="127.0.0.1", port=port,
            security_firm=futu.SecurityFirm.FUTUSECURITIES,
        )
        quote = None
        try:
            quote = futu.OpenQuoteContext(host="127.0.0.1", port=port)
            return cls(context, futu, account_id=account_id,
                       journal_path=journal_path, allow_paper_orders=allow_paper_orders,
                       quote_context=quote)
        except Exception:
            if quote is not None:
                quote.close()
            context.close()
            raise

    def _call(self, method: str, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        ret, data = getattr(self.context, method)(*args, **kwargs)
        if ret != self.sdk.RET_OK:
            raise PaperOrderError(f"{method} failed: {str(data)[:250]}")
        if not hasattr(data, "to_dict"):
            raise PaperOrderError(f"{method} did not return a table")
        return data.to_dict(orient="records")

    def _verify_account(self) -> None:
        accounts = self._call("get_acc_list")
        matches = [row for row in accounts if str(row.get("acc_id")) == str(self.account_id)]
        if len(matches) != 1:
            raise PaperOrderError("specified paper account not found or ambiguous")
        row = matches[0]
        if _label(row.get("trd_env", "")) != "SIMULATE":
            raise PaperOrderError("account is not explicitly a SIMULATE account")
        if _label(row.get("sim_acc_type", "")) != "STOCK":
            raise PaperOrderError("account is not explicitly an HK stock simulation account")
        markets = row.get("trdmarket_auth")
        if not isinstance(markets, (list, tuple)) or "HK" not in [_label(x) for x in markets]:
            raise PaperOrderError("account has no verified HK market authorization")
        if _label(row.get("acc_status", "")) != "ACTIVE":
            raise PaperOrderError("paper account is not ACTIVE")

    def _paper_kwargs(self) -> dict[str, Any]:
        self._verify_account()
        return {"trd_env": self.sdk.TrdEnv.SIMULATE, "acc_id": self.account_id}

    def get_account(self) -> dict[str, Any]:
        rows = self._call("accinfo_query", refresh_cache=True, **self._paper_kwargs())
        if len(rows) != 1:
            raise PaperOrderError("account funds response is unavailable or ambiguous")
        return rows[0]

    def get_positions(self) -> list[dict[str, Any]]:
        return self._call("position_list_query", refresh_cache=True, **self._paper_kwargs())

    def get_open_orders(self) -> list[dict[str, Any]]:
        rows = self._call("order_list_query", refresh_cache=True, **self._paper_kwargs())
        terminal = {"FILLED_ALL", "CANCELLED_ALL", "CANCELLED_PART", "FILLCANCELLED",
                    "FAILED", "SUBMIT_FAILED", "DELETED", "DISABLED"}
        return [row for row in rows if _label(row.get("order_status", "")) not in terminal]

    def get_order_status(self, order_id: str) -> dict[str, Any]:
        if not order_id:
            raise PaperOrderError("order ID required")
        rows = self._call("order_list_query", order_id=str(order_id),
                          refresh_cache=True, **self._paper_kwargs())
        if not rows:
            # Current order list only retains filled/cancelled orders for 24 hours.
            rows = [row for row in self._call("history_order_list_query", **self._paper_kwargs())
                    if str(row.get("order_id")) == str(order_id)]
        if len(rows) != 1:
            raise PaperOrderError("order status unavailable or ambiguous (history query covers only its configured period)")
        return rows[0]

    def _journal(self, order: PaperOrder) -> None:
        with _journal_db(self.journal_path) as db:
            db.execute("INSERT OR REPLACE INTO orders VALUES (?,?,?,?)",
                       (order.client_order_id, json.dumps(asdict(order)), order.status,
                        datetime.now(timezone.utc).isoformat()))

    def _previous(self, client_order_id: str) -> PaperOrder | None:
        with _journal_db(self.journal_path) as db:
            row = db.execute("SELECT payload FROM orders WHERE client_order_id=?",
                             (client_order_id,)).fetchone()
        return PaperOrder(**json.loads(row[0])) if row else None

    def reconcile_order(self, client_order_id: str) -> PaperOrder:
        """Resolve an uncertain submission without ever sending another order.

        An absent remark is inconclusive (delayed/expired broker history), so
        it remains blocked until the account owner investigates the broker UI.
        """
        prior = self._previous(client_order_id)
        if prior is None:
            raise PaperOrderError("unknown client order ID")
        self._paper_kwargs()
        current = self._call("order_list_query", refresh_cache=True, **self._paper_kwargs())
        history = self._call("history_order_list_query", **self._paper_kwargs())
        matches = {str(row["order_id"]): row for row in current + history
                   if row.get("remark") == client_order_id and row.get("order_id")}
        if len(matches) != 1:
            raise PaperOrderError("broker order absent or ambiguous; manual reconciliation required")
        broker_id, row = next(iter(matches.items()))
        if (row.get("code") != prior.code or _label(row.get("trd_side")) != prior.side or
                _finite_number(row.get("qty")) != prior.qty or
                _finite_number(row.get("price")) != prior.limit_price):
            raise PaperOrderError("broker order does not match original request")
        order = PaperOrder(**{**asdict(prior), "broker_order_id": broker_id,
                              "status": _label(row.get("order_status"))})
        self._journal(order)
        return order

    def _verify_security(self, code: str, lot_size: int) -> None:
        if self.quote_context is None:
            raise PaperOrderError("broker quote context required to verify lot size")
        ret, table = self.quote_context.get_stock_basicinfo(
            self.sdk.Market.HK, self.sdk.SecurityType.STOCK, [code],
        )
        if ret != self.sdk.RET_OK or not hasattr(table, "to_dict"):
            raise PaperOrderError("broker stock metadata unavailable")
        rows = table.to_dict(orient="records")
        if len(rows) != 1 or rows[0].get("code") != code:
            raise PaperOrderError("broker stock metadata ambiguous")
        row = rows[0]
        if (_label(row.get("stock_type")) != "STOCK" or
                row.get("suspension") not in (False, 0, "False", "false") or
                row.get("delisting") not in (False, 0, "False", "false") or
                _finite_number(row.get("lot_size")) != lot_size):
            raise PaperOrderError("broker stock type/status/lot size not verified")

    def place_paper_order(
        self, *, client_order_id: str, code: str, side: str,
        qty: int, limit_price: float, lot_size: int,
        dry_run: bool = True, confirmed: bool = False,
    ) -> PaperOrder:
        if not client_order_id or len(client_order_id.encode("utf-8")) > 64:
            raise PaperOrderError("client order ID must be nonempty and <=64 UTF-8 bytes")
        if not _HK_CODE.fullmatch(code) or side not in ("BUY", "SELL"):
            raise PaperOrderError("only HK five-digit stocks and BUY/SELL are supported")
        if (isinstance(qty, bool) or not isinstance(qty, int) or qty <= 0 or
                isinstance(lot_size, bool) or not isinstance(lot_size, int)
                or lot_size <= 0 or qty % lot_size):
            raise PaperOrderError("quantity must be a positive multiple of verified lot size")
        if not 0 < _finite_number(limit_price) < 1_000_000:
            raise PaperOrderError("positive finite limit price required")
        prior = self._previous(client_order_id)
        if prior is not None:
            if (prior.code, prior.side, prior.qty, prior.limit_price) != (code, side, qty, limit_price):
                raise PaperOrderError("client order ID already used for different order")
            if prior.status in ("PENDING", "INDETERMINATE"):
                raise PaperOrderError("previous request uncertain; reconcile broker order before retry")
            return prior

        request = PaperOrder(client_order_id, code, side, qty, float(limit_price))
        if dry_run:
            return request
        if not self.allow_paper_orders or not confirmed:
            raise PaperOrderError("paper order submission disabled or not confirmed")
        kwargs = self._paper_kwargs()
        self._verify_security(code, lot_size)
        for item in self.get_open_orders():
            if item.get("remark") == client_order_id:
                raise PaperOrderError("duplicate broker order remark already exists")
            if item.get("code") == code and _label(item.get("trd_side")) == side:
                raise PaperOrderError("another open order has the same stock and direction")
        account = self.get_account()
        if side == "BUY":
            # A security account may not populate available_funds (futures-only).
            # Require both HKD cash and cash buying power; unknown fields fail closed.
            if min(_finite_number(account.get("hk_cash")),
                   _finite_number(account.get("hkd_net_cash_power"))) < qty * limit_price:
                raise PaperOrderError("verified HKD cash or buying power is insufficient")
        else:
            positions = self.get_positions()
            held = sum(_finite_number(row.get("qty")) for row in positions if row.get("code") == code)
            if held < qty:
                raise PaperOrderError("insufficient verified position")

        self._journal(PaperOrder(**{**asdict(request), "status": "PENDING"}))
        try:
            rows = self._call(
                "place_order", price=float(limit_price), qty=qty, code=code,
                trd_side=self.sdk.TrdSide.BUY if side == "BUY" else self.sdk.TrdSide.SELL,
                order_type=self.sdk.OrderType.NORMAL, remark=client_order_id,
                **kwargs,
            )
            if len(rows) != 1 or not rows[0].get("order_id"):
                raise PaperOrderError("broker returned no unique order ID")
            placed = PaperOrder(**{**asdict(request),
                                   "broker_order_id": str(rows[0]["order_id"]),
                                   "status": "SUBMITTED"})
            self._journal(placed)
            return placed
        except Exception:
            self._journal(PaperOrder(**{**asdict(request), "status": "INDETERMINATE"}))
            raise

    def cancel_order(self, order_id: str, *, confirmed: bool = False) -> dict[str, Any]:
        if not self.allow_paper_orders or not confirmed:
            raise PaperOrderError("paper order cancellation disabled or not confirmed")
        current = self.get_order_status(order_id)
        if str(current.get("order_id")) != str(order_id):
            raise PaperOrderError("order does not belong to this account")
        rows = self._call("modify_order", self.sdk.ModifyOrderOp.CANCEL,
                          str(order_id), 0, 0, **self._paper_kwargs())
        return rows[0] if rows else {"order_id": str(order_id), "status": "CANCEL_REQUESTED"}

    def close(self) -> None:
        self.context.close()
        if self.quote_context is not None:
            self.quote_context.close()
