"""Strategy artifact storage.

Strategies are stored as ``strategies/<strategy_id>/v<version>.yaml``.
A published version is immutable: saving different content under an existing
version raises :class:`StrategyImmutabilityError`.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Union

import yaml

from hk_quant.strategy.config import load_strategy_definition
from hk_quant.strategy.models import StrategyDefinition

PathLike = Union[str, os.PathLike[str]]


class StrategyImmutabilityError(Exception):
    """Raised when attempting to overwrite an existing strategy version."""


def _version_filename(version: str) -> str:
    return f"v{version}.yaml"


def save_strategy(
    strategy: StrategyDefinition,
    strategies_dir: PathLike = "strategies",
) -> Path:
    """Save a strategy artifact, enforcing version immutability."""
    root = Path(strategies_dir)
    dest_dir = root / strategy.strategy_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / _version_filename(strategy.version)

    if path.exists():
        existing = load_strategy_definition(path)
        if existing.to_hashable_dict() != strategy.to_hashable_dict():
            raise StrategyImmutabilityError(
                f"strategy {strategy.strategy_id} v{strategy.version} already exists "
                "with different content; bump the version instead"
            )
        return path

    path.write_text(
        yaml.safe_dump(strategy.to_dict(), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return path


def load_strategy(
    strategy_id: str,
    version: str,
    strategies_dir: PathLike = "strategies",
) -> StrategyDefinition:
    """Load a saved strategy version back into a definition."""
    path = Path(strategies_dir) / strategy_id / _version_filename(version)
    return load_strategy_definition(path)
