"""Tests for the YAML configuration loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from hk_quant.config import Config, ConfigError, load_config

CONFIGS_DIR = Path(__file__).resolve().parent.parent / "configs"


def test_load_data_config() -> None:
    config = load_config(CONFIGS_DIR / "data.yaml")
    assert config.market.name == "HK"
    assert config.market.timezone == "Asia/Hong_Kong"
    assert config.provider.primary == "akshare"
    assert config.storage.raw_dir == "data/raw"
    assert config.storage.processed_dir == "data/processed"
    assert config.storage.reference_dir == "data/reference"
    assert config.ingestion.overwrite is False


def test_load_research_config() -> None:
    config = load_config(CONFIGS_DIR / "research.yaml")
    periods = config.research.default_forward_periods
    assert isinstance(periods, list)
    assert 30 in periods
    assert 180 in periods


def test_other_configs_are_loadable() -> None:
    for name in ("backtest.yaml", "risk.yaml", "paper.yaml"):
        config = load_config(CONFIGS_DIR / name)
        assert isinstance(config, Config)


def test_missing_path_raises_config_error() -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_config(CONFIGS_DIR / "does_not_exist.yaml")


def test_directory_path_raises_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not a file"):
        load_config(tmp_path)


def test_invalid_yaml_raises_config_error(tmp_path: Path) -> None:
    bad_file = tmp_path / "bad.yaml"
    bad_file.write_text("key: [unclosed\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(bad_file)


def test_config_attribute_access() -> None:
    config = Config({"a": {"b": 1}, "c": [1, 2, 3]})
    assert config.a.b == 1
    assert config["a"]["b"] == 1
    assert "c" in config
    assert config.get("missing") is None
    assert config.to_dict() == {"a": {"b": 1}, "c": [1, 2, 3]}
