"""Phase 8 readiness: counts are observed and limitations are explicit."""

from __future__ import annotations

import json

from hk_quant.data.coverage import write_coverage_report
from hk_quant.data.repository import DataRepository
from hk_quant.data.storage import DataStorage


def test_empty_coverage_marks_unavailable(tmp_path) -> None:
    report = DataRepository(tmp_path / "processed").get_data_coverage()
    assert report["daily_prices"]["row_count"] == 0
    assert report["calendar"]["mode"] == "unavailable"
    assert report["stock_master"]["listing_date_nonnull"] == 0
    assert any("Turnover rate" in item for item in report["limitations"])


def test_observed_price_coverage_reports_dates_and_limitations(tmp_path, prices_df, master_df) -> None:
    storage = DataStorage(tmp_path / "raw", tmp_path / "processed")
    storage.save_stock_master(master_df)
    storage.save_daily_prices(prices_df)
    report = DataRepository(storage.processed_root).get_data_coverage()
    assert report["daily_prices"] == {
        "row_count": 3, "stock_count": 1,
        "start_date": "2025-01-02", "end_date": "2025-02-03",
        "turnover_rate_nonnull": 0, "amount_nonnull": 3,
    }
    assert report["calendar"]["mode"] == "observed"
    manifest = json.loads(storage.processed_root.joinpath(
        "provenance", "manifest.json"
    ).read_text(encoding="utf-8"))
    assert report["data_version"] == manifest["data_version"]
    assert report["data_version"].startswith("HK_DATA_")
    path = write_coverage_report(report, tmp_path / "report" / "coverage.json")
    assert json.loads(path.read_text(encoding="utf-8")) == report
