"""End-to-end data ingestion demo.

Proves the full path::

    AKShare -> raw parquet -> canonical parquet -> DuckDB -> query

Run from the project root with the virtualenv active::

    python examples/ingest_demo.py
"""

from __future__ import annotations

import sys

from hk_quant.config import load_config
from hk_quant.data.adapters.akshare import AKShareProvider
from hk_quant.data.ingestion import ingest_daily_prices, ingest_stock_master
from hk_quant.data.repository import DataRepository
from hk_quant.data.storage import DataStorage


def main() -> int:
    config = load_config("configs/data.yaml")
    storage = DataStorage(config.storage.raw_dir, config.storage.processed_dir)
    provider = AKShareProvider()

    print("1) Ingesting stock master ...")
    master = ingest_stock_master(provider, storage)
    print(f"   stock master rows: {len(master)}")

    print("2) Ingesting daily prices for 0700 (2025-01) ...")
    prices = ingest_daily_prices(
        provider,
        storage,
        stock_ids=["0700"],
        start_date="2025-01-01",
        end_date="2025-01-31",
    )
    print(f"   daily price rows: {len(prices)}")

    print("3) Querying via DuckDB repository ...")
    repo = DataRepository(storage.processed_root)
    result = repo.get_daily_prices(
        stock_ids=["0700"], start_date="2025-01-01", end_date="2025-01-31"
    )
    print(result.to_string(index=False))

    print("4) Querying stock master via DuckDB repository ...")
    master_result = repo.get_stock_master()
    print(f"   stock master rows: {len(master_result)}")
    print(master_result.head(5).to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
