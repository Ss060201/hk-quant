"""Create reviewable paper proposals from fixed-version signals.

Planning never calls a broker. ``FutuPaperBroker.place_paper_order`` performs
account, stock metadata and buying-power checks again before an actual PAPER
submission. A proposal is not an order or a fill.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from typing import Any

from hk_quant.paper.futu_adapter import PaperOrderError


@dataclass(frozen=True)
class PaperProposal:
    client_order_id: str
    strategy_id: str
    strategy_version: str
    strategy_hash: str
    signal_date: str
    data_version: str
    code: str
    side: str
    qty: int
    limit_price: float
    lot_size: int
    status: str = "PROPOSED_REQUIRES_HUMAN_REVIEW"


def propose_paper_order(signal: Any, *, limit_price: float, lot_size: int,
                        available_cash: float, held_qty: int,
                        max_notional: float) -> PaperProposal | None:
    """Size one BUY/SELL from a valid signal; HOLD creates no proposal.

    The caller must supply a recent independent quote and a verified lot size.
    The broker independently checks both lot size and account before submission.
    """
    status = getattr(signal.status, "value", signal.status)
    if status != "VALID" or not signal.strategy_id or not signal.strategy_version or not signal.strategy_hash or not signal.data_version:
        raise PaperOrderError("valid fixed-version signal with data provenance required")
    if not re.fullmatch(r"\d{1,5}", signal.stock_id) or int(signal.stock_id) <= 0:
        raise PaperOrderError("paper proposals require canonical HK numeric stock IDs")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", signal.signal_date):
        raise PaperOrderError("signal date required")
    if signal.signal == "HOLD":
        return None
    if signal.signal not in ("BUY", "SELL"):
        raise PaperOrderError("signal has no supported side")
    if isinstance(lot_size, bool) or not isinstance(lot_size, int) or lot_size <= 0:
        raise PaperOrderError("positive lot size required")
    if isinstance(held_qty, bool) or not isinstance(held_qty, int) or held_qty < 0:
        raise PaperOrderError("verified nonnegative whole-share holding required")
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or
           not math.isfinite(value) or value < 0 for value in
           (limit_price, available_cash, max_notional)) or limit_price <= 0 or max_notional <= 0:
        raise PaperOrderError("finite positive price and allocation cap required")
    if signal.signal == "BUY":
        if held_qty:
            raise PaperOrderError("existing holding must be reviewed before another BUY")
        qty = math.floor(min(available_cash, max_notional) / limit_price / lot_size) * lot_size
    else:
        qty = held_qty // lot_size * lot_size
    if qty <= 0:
        raise PaperOrderError("not enough verified cash/holdings for one lot")
    code = f"HK.{int(signal.stock_id):05d}"
    identity = "|".join((signal.strategy_hash, signal.signal_date, code, signal.signal))
    client_order_id = hashlib.sha256(identity.encode()).hexdigest()[:32]
    return PaperProposal(client_order_id, signal.strategy_id,
                         signal.strategy_version, signal.strategy_hash,
                         signal.signal_date, signal.data_version, code,
                         signal.signal, qty, float(limit_price), lot_size)
