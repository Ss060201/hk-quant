"""Turnover research integration tests (real AKShare data).

Key honest check: the current provider does NOT supply turnover rate
(換手率), so a turnover_rate research must fail with a clear error rather
than silently substituting trading amount (成交額). A second test proves the
generic engine works on a variable that IS available (volume).
"""

from __future__ import annotations

import pytest

from hk_quant.data.repository import DataRepository
from hk_quant.research import ResearchDataError, run_research
from hk_quant.research.models import ResearchDefinition, ResearchStatus, VariableSpec

pytestmark = pytest.mark.integration


def _build_repo(tmp_path) -> DataRepository:
    from hk_quant.data.adapters.akshare import AKShareProvider
    from hk_quant.data.ingestion import ingest_daily_prices
    from hk_quant.data.storage import DataStorage

    storage = DataStorage(tmp_path / "raw", tmp_path / "processed")
    provider = AKShareProvider()
    ingest_daily_prices(
        provider,
        storage,
        stock_ids=["0700"],
        start_date="2024-01-01",
        end_date="2025-12-31",
    )
    return DataRepository(storage.processed_root)


def test_turnover_rate_unavailable_on_real_data(tmp_path) -> None:
    repository = _build_repo(tmp_path)
    definition = ResearchDefinition(
        name="turnover_real",
        variable=VariableSpec(name="turnover_rate", thresholds=[0.1, 0.5]),
        forward_periods=[1, 5],
    )
    with pytest.raises(ResearchDataError, match="turnover_rate"):
        run_research(definition, repository=repository)


def test_generic_engine_runs_on_real_available_variable(tmp_path) -> None:
    repository = _build_repo(tmp_path)
    definition = ResearchDefinition(
        name="volume_real",
        variable=VariableSpec(name="volume", thresholds=[1e7, 5e7]),
        forward_periods=[1, 2, 3, 5],
    )
    result = run_research(definition, repository=repository)

    assert not result.events.empty
    assert not result.forward_returns.empty
    assert result.status in list(ResearchStatus)
    assert result.tested_combinations == 8
