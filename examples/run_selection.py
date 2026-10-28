"""Ranking-based selection demo (example factor, NOT a validated strategy).

Runs the score -> rank -> top-N -> equal-weight flow over local processed data.
The example factor is 20-day close momentum; its result must not be read as an
investable or validated signal.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from hk_quant.data.repository import DataRepository
from hk_quant.selection import build_selection_schedule, momentum_scorer, rank_by_score

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ranking selection demo")
    parser.add_argument("--stocks", nargs="+", default=["0700", "0005", "0941"])
    parser.add_argument("--date", required=True, help="Decision date YYYY-MM-DD")
    parser.add_argument("--top-n", type=int, default=2)
    parser.add_argument("--window", type=int, default=20)
    args = parser.parse_args(argv)

    repository = DataRepository(ROOT / "data" / "processed")
    panel = repository.get_daily_prices(stock_ids=args.stocks)
    if panel.empty:
        print("No local processed prices; run examples/prepare_research_data.py first.")
        return 2

    cutoff = pd.Timestamp(args.date)
    history = panel[pd.to_datetime(panel["trade_date"]) <= cutoff]
    scorer = momentum_scorer(window=args.window)
    scores = {s: scorer(history, s) for s in args.stocks}
    targets = build_selection_schedule(panel, args.stocks, [args.date], scorer, top_n=args.top_n)

    print(f"Decision date: {args.date}")
    print(f"Scores (momentum_{args.window}, PIT):")
    for stock_id in rank_by_score(scores):
        value = scores[stock_id]
        print(f"  {stock_id}: {value:.4f}")
    scored = set(rank_by_score(scores))
    for stock_id in args.stocks:
        if stock_id not in scored:
            print(f"  {stock_id}: None (insufficient history / suspended)")
    print(f"\nTop {args.top_n} equal-weight targets:")
    for stock_id, weight in targets[cutoff.date().isoformat()].items():
        print(f"  {stock_id}: {weight:.4f}")
    print("\nEXPLORATORY — example factor only, not a validated strategy.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
