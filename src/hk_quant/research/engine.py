"""Research engine orchestration.

Flow::

    ResearchDefinition
        -> Validate
        -> Load data (DataRepository only)
        -> Validate data availability
        -> Build events
        -> Calculate forward returns (separate step)
        -> Statistics
        -> Relationship analysis
        -> Plots
        -> ResearchResult
        -> Save artifact

The engine only talks to the data layer through ``DataRepository``; it never
imports AKShare or re-implements calendar / PIT / adjustment logic.
"""

from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any, Union

import pandas as pd

from hk_quant.data.calendar import TradingCalendar
from hk_quant.data.provenance import make_data_version
from hk_quant.research.events import build_events
from hk_quant.research.forward_returns import compute_forward_returns
from hk_quant.research.models import ResearchDefinition, ResearchResult, ResearchStatus
from hk_quant.research.relationships import analyze_relationships
from hk_quant.research.results import save_research_result
from hk_quant.research.statistics import summarize_forward_returns
from hk_quant.research.visualization import (
    plot_heatmap,
    plot_holding_period_vs_return,
    plot_sample_sizes,
    plot_threshold_vs_return,
)

PathLike = Union[str, os.PathLike[str]]


class ResearchDataError(Exception):
    """Raised when required research data is unavailable or incompatible."""


def run_research(
    definition: ResearchDefinition,
    repository: Any | None = None,
    panel: pd.DataFrame | None = None,
    output_dir: PathLike | None = None,
    data_version: str | None = None,
) -> ResearchResult:
    """Run a research definition end to end.

    Args:
        definition: Validated research definition.
        repository: A ``DataRepository`` (used to load prices + calendar).
        panel: Optional pre-built research panel (used in tests). If omitted,
            ``repository`` is required.
        output_dir: If given, the full artifact is saved here.
        data_version: Optional version label; defaults to ``HK_DAILY_<date>``.
    """
    if panel is None:
        if repository is None:
            raise ValueError("provide either repository or panel")
        panel = _load_panel(repository, definition)

    warnings: list[str] = _build_warnings(definition)

    variable = definition.variable.name
    _validate_panel(panel, definition, variable)

    calendar = _build_calendar(repository, panel)
    data_version = data_version or make_data_version("HK_DAILY")

    events = build_events(panel, definition, data_version=data_version)
    forward_returns = compute_forward_returns(events, panel, calendar, definition)
    statistics = summarize_forward_returns(forward_returns, definition)
    relationships = analyze_relationships(
        statistics, definition.thresholds, definition.forward_periods
    )
    status = _determine_status(relationships, statistics)

    result = ResearchResult(
        research_id=definition.research_id,
        name=definition.name,
        data_version=data_version,
        parameters=definition.to_dict(),
        events=events,
        forward_returns=forward_returns,
        statistics=statistics,
        relationship_analysis=relationships,
        warnings=warnings,
        status=status,
        tested_combinations=len(definition.thresholds) * len(definition.forward_periods),
        exploratory=definition.exploratory,
    )

    if output_dir is not None:
        save_research_result(result, output_dir)
        _generate_plots(statistics, definition, Path(output_dir) / "plots")

    return result


def _load_panel(repository: Any, definition: ResearchDefinition) -> pd.DataFrame:
    if definition.universe.mode == "historical_universe":
        raise ResearchDataError(
            "historical universe data is unavailable from the current provider; "
            "use 'observed_price_universe' (survivorship-biased, exploratory only)"
        )

    return repository.get_prices(
        stock_ids=None,
        start_date=definition.date_range.start,
        end_date=definition.date_range.end,
        adjusted=definition.price.adjusted,
    )


def _validate_panel(
    panel: pd.DataFrame,
    definition: ResearchDefinition,
    variable: str,
) -> None:
    entry = definition.return_definition.entry
    exit_col = definition.return_definition.exit
    base_required = {"stock_id", "trade_date", entry, exit_col}
    missing = base_required - set(panel.columns)
    if missing:
        raise ResearchDataError(
            f"required columns missing from research data: {sorted(missing)}"
        )

    if variable not in panel.columns or panel[variable].isna().all():
        raise ResearchDataError(
            f"Required variable `{variable}` is unavailable or semantically "
            "incompatible with current data."
        )


def _build_calendar(repository: Any | None, panel: pd.DataFrame) -> TradingCalendar:
    if repository is not None and hasattr(repository, "get_calendar"):
        return repository.get_calendar()
    return TradingCalendar.from_prices(panel)


def _build_warnings(definition: ResearchDefinition) -> list[str]:
    warnings: list[str] = []
    if definition.universe.mode == "observed_price_universe":
        warnings.append(
            "historical listing/delisting information is unavailable; "
            "results may contain survivorship bias"
        )
    warnings.append(
        "exploratory research: multiple thresholds/periods were tested "
        "simultaneously; findings need independent validation"
    )
    if definition.return_definition.dividend == "excluded":
        warnings.append("return is price_return; dividends are excluded")
    return warnings


def _determine_status(relationships: dict[str, Any], statistics: pd.DataFrame) -> ResearchStatus:
    if statistics["valid_sample_count"].sum() == 0:
        return ResearchStatus.NO_EVIDENCE

    significant_rhos: list[float] = []
    for item in relationships["threshold_return_relationships"]:
        rho = item.get("spearman_mean_rho")
        p_value = item.get("spearman_mean_p")
        if _is_significant(rho, p_value):
            significant_rhos.append(abs(float(rho)))
    for item in relationships["holding_period_relationships"]:
        rho = item.get("spearman_rho")
        p_value = item.get("spearman_p")
        if _is_significant(rho, p_value):
            significant_rhos.append(abs(float(rho)))

    if not significant_rhos:
        return ResearchStatus.NO_EVIDENCE

    strongest = max(significant_rhos)
    if strongest < 0.2:
        return ResearchStatus.WEAK_PATTERN
    if strongest < 0.5:
        return ResearchStatus.NOTABLE_PATTERN
    return ResearchStatus.WORTH_FURTHER_RESEARCH


def _is_significant(rho: Any, p_value: Any) -> bool:
    if rho is None or p_value is None:
        return False
    try:
        return not math.isnan(float(rho)) and not math.isnan(float(p_value)) and float(p_value) <= 0.05
    except (TypeError, ValueError):
        return False


def _generate_plots(
    statistics: pd.DataFrame,
    definition: ResearchDefinition,
    plots_dir: Path,
) -> None:
    plots_dir.mkdir(parents=True, exist_ok=True)
    plot_heatmap(statistics, plots_dir / "heatmap.png")

    period = _pick_period(definition.forward_periods)
    threshold = _pick_threshold(definition.thresholds)
    plot_threshold_vs_return(statistics, period, plots_dir / f"threshold_vs_return_{period}d.png")
    plot_holding_period_vs_return(statistics, threshold, plots_dir / f"holding_period_vs_return_{threshold:.2f}.png")
    plot_sample_sizes(statistics, plots_dir / "sample_sizes.png")


def _pick_period(periods: list[int]) -> int:
    for candidate in (30, 20, 60, 10, 5):
        if candidate in periods:
            return candidate
    return periods[len(periods) // 2]


def _pick_threshold(thresholds: list[float]) -> float:
    return thresholds[len(thresholds) // 2]
