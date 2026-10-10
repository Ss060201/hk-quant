"""Data provenance tests."""

from __future__ import annotations

from datetime import date

from hk_quant.data.provenance import (
    DataProvenance,
    build_provenance,
    make_data_version,
    read_provenance,
    write_provenance,
)


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
