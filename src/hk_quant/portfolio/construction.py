"""Simple long-only target construction without involuntary HOLD sales."""

from __future__ import annotations

from collections.abc import Iterable


def equal_weight_targets(
    held_stock_ids: Iterable[str],
    buy_stock_ids: Iterable[str],
    sell_stock_ids: Iterable[str] = (),
) -> dict[str, float]:
    """Split 100% gross target across held names and new BUY names.

    Weights describe *buying targets*, not mandatory rebalance orders: already
    held shares are never sold merely because the denominator changed.
    """
    eligible = (set(held_stock_ids) - set(sell_stock_ids)) | set(buy_stock_ids)
    if not eligible:
        return {}
    weight = 1.0 / len(eligible)
    return {stock_id: weight for stock_id in sorted(eligible)}
