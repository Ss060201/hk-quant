"""Strategy Builder.

Turns an explicit, human-authored strategy config into a validated, versioned
strategy artifact. A ``ResearchResult`` is only used for provenance — the
actual entry/exit/holding rules always come from the strategy config, never
guessed from the research result.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Union

from hk_quant.research.models import ResearchResult
from hk_quant.strategy.config import load_strategy_definition, parse_strategy_definition
from hk_quant.strategy.models import (
    ResearchProvenance,
    StrategyDefinition,
    compute_strategy_hash,
)
from hk_quant.strategy.storage import save_strategy
from hk_quant.strategy.validators import validate_strategy

PathLike = Union[str, os.PathLike[str]]


def build_strategy(
    config_path: PathLike,
    repository: Any | None = None,
    strategies_dir: PathLike | None = None,
) -> StrategyDefinition:
    """Parse -> validate -> hash -> save a strategy definition."""
    definition = load_strategy_definition(config_path)
    definition = validate_strategy(definition, repository=repository)
    definition.strategy_hash = compute_strategy_hash(definition)

    if strategies_dir is not None:
        save_strategy(definition, strategies_dir)
    return definition


def build_strategy_from_dict(
    data: dict[str, Any],
    repository: Any | None = None,
    strategies_dir: PathLike | None = None,
) -> StrategyDefinition:
    """Build a strategy from an in-memory mapping (used in tests)."""
    definition = parse_strategy_definition(data)
    definition = validate_strategy(definition, repository=repository)
    definition.strategy_hash = compute_strategy_hash(definition)

    if strategies_dir is not None:
        save_strategy(definition, strategies_dir)
    return definition


def create_strategy_from_research(
    research_result: ResearchResult,
    strategy_config: PathLike | dict[str, Any],
    repository: Any | None = None,
    strategies_dir: PathLike | None = None,
) -> StrategyDefinition:
    """Create a strategy and link it to a research result (provenance only).

    The entry/exit/holding rules come from ``strategy_config``; the
    ``ResearchResult`` supplies ``research_id`` and the research status at
    creation time. It never auto-derives rules from the research result.
    """
    if isinstance(strategy_config, dict):
        definition = parse_strategy_definition(strategy_config)
    else:
        definition = load_strategy_definition(strategy_config)

    provenance = ResearchProvenance(
        research_id=research_result.research_id,
        source_status=research_result.status.value,
    )
    if definition.research is not None:
        if definition.research.research_id != research_result.research_id:
            raise ValueError(
                f"strategy research_id {definition.research.research_id!r} does not "
                f"match research result {research_result.research_id!r}"
            )
        provenance.research_result_path = definition.research.research_result_path
    definition.research = provenance

    definition = validate_strategy(definition, repository=repository)
    definition.strategy_hash = compute_strategy_hash(definition)

    if strategies_dir is not None:
        save_strategy(definition, strategies_dir)
    return definition
