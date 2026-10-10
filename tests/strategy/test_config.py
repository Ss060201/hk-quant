"""Strategy config parsing tests."""

from __future__ import annotations

import pytest

from hk_quant.strategy.config import StrategyConfigError, load_strategy_definition


def _write(tmp_path, text: str):
    path = tmp_path / "strategy.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_load_strategy_definition(tmp_path) -> None:
    path = _write(
        tmp_path,
        """
id: turnover_strategy
name: Turnover Strategy
version: 1.0.0
research:
  research_id: turnover_forward_return_v1
  source_status: WORTH_FURTHER_RESEARCH
universe:
  type: observed_price_universe
entry:
  all:
    - source: data
      field: turnover_rate
      operator: ">"
      value: 0.40
      unit: ratio
holding_period:
  type: trading_days
  value: 30
exit:
  type: holding_period
status: draft
""",
    )
    definition = load_strategy_definition(path)
    assert definition.strategy_id == "turnover_strategy"
    assert definition.version == "1.0.0"
    assert definition.research.research_id == "turnover_forward_return_v1"
    assert definition.entry.logic == "all"
    assert definition.entry.conditions[0].value == 0.40
    assert definition.status.value == "DRAFT"


def test_nested_conditions_parse(tmp_path) -> None:
    path = _write(
        tmp_path,
        """
id: nested_strategy
name: Nested
version: 1.0.0
universe:
  type: observed_price_universe
entry:
  all:
    - source: data
      field: close
      operator: ">"
      value: 10
    - any:
        - source: data
          field: volume
          operator: ">"
          value: 1000
        - source: data
          field: amount
          operator: ">"
          value: 5000
holding_period:
  type: trading_days
  value: 5
""",
    )
    definition = load_strategy_definition(path)
    assert definition.entry.logic == "all"
    assert len(definition.entry.conditions) == 2
    nested = definition.entry.conditions[1]
    assert nested.logic == "any"


def test_missing_id_raises(tmp_path) -> None:
    path = _write(tmp_path, "name: X\nversion: 1.0.0\nentry:\n  all: []\n")
    with pytest.raises(StrategyConfigError):
        load_strategy_definition(path)


def test_missing_version_raises(tmp_path) -> None:
    path = _write(tmp_path, "id: X\nname: X\nentry:\n  all: []\n")
    with pytest.raises(StrategyConfigError):
        load_strategy_definition(path)
