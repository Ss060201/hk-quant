"""Back up local data and ingest an explicit multi-stock exploratory cohort.

Example (PowerShell from repository root)::

    python examples/prepare_research_data.py --stocks 0700 0005 0941 \
      --start 2020-01-01 --end 2025-12-31 --backup-dir D:\\hk-quant-backup-new
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import pandas as pd

from hk_quant.data.ingestion import ingest_daily_prices
from hk_quant.data.normalization import normalize_stock_id
from hk_quant.data.readiness import assess_price_panel
from hk_quant.data.repository import DataRepository


ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Back up and ingest a bounded research cohort")
    parser.add_argument("--stocks", nargs="+", required=True, help="Explicit stock IDs, at least two")
    parser.add_argument("--start", required=True, help="First date YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="Last date YYYY-MM-DD")
    parser.add_argument("--backup-dir", type=Path, required=True, help="New directory outside the repository")
    parser.add_argument("--overwrite", action="store_true", help="Refetch completed ranges")
    parser.add_argument("--min-sessions", type=int, default=252)
    parser.add_argument("--min-coverage", type=float, default=0.8)
    args = parser.parse_args(argv)

    stocks = [normalize_stock_id(stock) for stock in args.stocks]
    # Validate options before any backups or writes.
    assess_price_panel(
        pd.DataFrame(columns=[
            "stock_id", "trade_date", "open", "high", "low", "close", "volume", "amount"
        ]), stocks, args.start, args.end,
        min_sessions=args.min_sessions, min_coverage=args.min_coverage,
    )
    backup = args.backup_dir.resolve()
    if backup == ROOT or ROOT in backup.parents:
        parser.error("backup must be outside the repository")
    backup.mkdir(parents=True, exist_ok=False)
    for name in ("raw", "processed"):
        source = ROOT / "data" / name
        if source.exists():
            shutil.copytree(source, backup / name)
    print(f"Backup: {backup}")

    for stock in stocks:
        result = ingest_daily_prices(stock_ids=[stock], start_date=args.start,
                                     end_date=args.end, overwrite=args.overwrite)
        print(f"{stock}: fetched {len(result)} rows (0 may mean completed or missing)")

    repo = DataRepository(ROOT / "data" / "processed")
    prices = repo.get_daily_prices(stock_ids=stocks, start_date=args.start, end_date=args.end)
    report = assess_price_panel(prices, stocks, args.start, args.end,
                                min_sessions=args.min_sessions, min_coverage=args.min_coverage)
    report["data_version"] = repo.get_data_version()
    output = ROOT / "experiments" / "data_checks"
    output.mkdir(parents=True, exist_ok=True)
    path = output / f"{report['data_version']}_{args.start}_{args.end}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Coverage: {path}; status: {report['status']}")
    return 0 if report["status"] != "BLOCKED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
