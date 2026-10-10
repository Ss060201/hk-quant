"""Research config loading tests."""

from __future__ import annotations

import pytest

from hk_quant.research.config import ResearchConfigError, load_research_definition


def test_load_research_definition(tmp_path) -> None:
    path = tmp_path / "research.yaml"
    path.write_text(
        """
research:
  name: turnover_v1
  variable:
    name: turnover_rate
    unit: ratio
    thresholds: [0.10, 0.50]
  forward_periods: [1, 5, 30]
  event_mode: daily
  return:
    entry: close
    exit: close
""",
        encoding="utf-8",
    )
    definition = load_research_definition(path)
    assert definition.name == "turnover_v1"
    assert definition.variable.name == "turnover_rate"
    assert definition.variable.thresholds == [0.1, 0.5]
    assert definition.forward_periods == [1, 5, 30]
    assert definition.event_mode == "daily"


def test_percent_unit_is_normalized_to_ratio(tmp_path) -> None:
    path = tmp_path / "research.yaml"
    path.write_text(
        """
research:
  name: turnover_v1
  variable:
    name: turnover_rate
    unit: percent
    thresholds: [10, 50]
  forward_periods: [1]
""",
        encoding="utf-8",
    )
    definition = load_research_definition(path)
    assert definition.variable.thresholds == [0.1, 0.5]
    assert definition.variable.unit == "ratio"


def test_missing_name_raises(tmp_path) -> None:
    path = tmp_path / "research.yaml"
    path.write_text("research:\n  variable:\n    name: x\n    thresholds: [0.1]\n", encoding="utf-8")
    with pytest.raises(ResearchConfigError):
        load_research_definition(path)


def test_invalid_event_mode_raises(tmp_path) -> None:
    path = tmp_path / "research.yaml"
    path.write_text(
        """
research:
  name: turnover_v1
  variable:
    name: turnover_rate
    thresholds: [0.1]
  forward_periods: [1]
  event_mode: nonsense
""",
        encoding="utf-8",
    )
    with pytest.raises(ResearchConfigError):
        load_research_definition(path)
