"""Data provenance tests."""

from __future__ import annotations

from datetime import date

from hk_quant.data.provenance import (
    DataProvenance,
    build_data_manifest,
    build_provenance,
    get_data_version,
    make_data_version,
    read_data_manifest,
    read_provenance,
    write_provenance,
)
from hk_quant.data.storage import DataStorage


def test_make_data_version() -> None:
    assert make_data_version("HK_DAILY", date(2026, 9, 24)) == "HK_DAILY_2026_09_24"


def test_build_provenance() -> None:
    prov = build_provenance("akshare", "HK_DAILY", provider_version="1.18.97")
    assert prov.source == "akshare"
    assert prov.data_version.startswith("HK_DAILY_")
    assert prov.provider_version == "1.18.97"
    assert prov.ingested_at  # non-empty ISO timestamp


def test_write_and_read_provenance(tmp_path) -> None:
    prov = DataProvenance(
        source="synthetic",
        ingested_at="2026-09-24T00:00:00+00:00",
        data_version="HK_DAILY_2026_09_24",
    )
    path = write_provenance(prov, tmp_path, "daily_prices")
    assert path.exists()

    loaded = read_provenance(tmp_path, "daily_prices")
    assert loaded == prov


def test_processed_content_version_changes_when_same_day_price_changes(tmp_path, prices_df) -> None:
    storage = DataStorage(tmp_path / "raw", tmp_path / "processed")
    storage.save_daily_prices(prices_df)
    first = get_data_version(storage.processed_root)
    stored = read_data_manifest(storage.processed_root)
    assert stored["data_version"] == first
    assert stored == build_data_manifest(storage.processed_root)

    amended = prices_df.iloc[[0]].copy()
    amended["close"] = 434.0
    storage.save_daily_prices(amended)
    second = get_data_version(storage.processed_root)
    assert first != second
    assert read_data_manifest(storage.processed_root)["data_version"] == second


def test_out_of_band_processed_edit_is_detected(tmp_path, prices_df) -> None:
    storage = DataStorage(tmp_path / "raw", tmp_path / "processed")
    paths = storage.save_daily_prices(prices_df)
    first = get_data_version(storage.processed_root)
    paths[0].write_bytes(paths[0].read_bytes() + b"changed outside DataStorage")
    assert get_data_version(storage.processed_root) != first
