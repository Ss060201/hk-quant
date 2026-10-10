"""Simple YAML configuration loader for ``hk_quant``.

The loader returns a small :class:`Config` object that exposes nested YAML
mappings through attribute access. It is intentionally minimal and can be
reused by future Data / Research / Backtest modules.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping, Union

import yaml

PathLike = Union[str, os.PathLike[str]]


class ConfigError(Exception):
    """Raised when a configuration file cannot be loaded."""


class Config:
    """A read-only, attribute-accessible wrapper around a nested mapping."""

    def __init__(self, data: Mapping[str, Any]) -> None:
        object.__setattr__(self, "_data", dict(data))

    def __getattr__(self, key: str) -> Any:
        try:
            value = self._data[key]
        except KeyError as exc:
            raise AttributeError(f"Config has no key: {key!r}") from exc
        return _wrap(value)

    def __getitem__(self, key: str) -> Any:
        return _wrap(self._data[key])

    def __contains__(self, key: str) -> bool:
        return key in self._data

    def get(self, key: str, default: Any = None) -> Any:
        return _wrap(self._data.get(key, default))

    def to_dict(self) -> dict[str, Any]:
        """Return the underlying data as a plain dictionary."""
        return self._data

    def __repr__(self) -> str:
        return f"Config({self._data!r})"


def _wrap(value: Any) -> Any:
    """Wrap nested mappings into Config objects (recursively)."""
    if isinstance(value, Mapping):
        return Config(value)
    if isinstance(value, list):
        return [_wrap(item) for item in value]
    return value


def load_config(path: PathLike) -> Config:
    """Load a YAML config file and return it as a :class:`Config`.

    Args:
        path: Path to the YAML configuration file.

    Returns:
        A Config object representing the loaded configuration.

    Raises:
        ConfigError: If the path is missing, is not a file, contains
            invalid YAML, or cannot be read.
    """
    config_path = Path(path)

    if not config_path.exists():
        raise ConfigError(f"Config file not found: {config_path}")
    if not config_path.is_file():
        raise ConfigError(f"Config path is not a file: {config_path}")

    try:
        with config_path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        raise ConfigError(
            f"Invalid YAML in config file {config_path}: {exc}"
        ) from exc
    except OSError as exc:
        raise ConfigError(
            f"Could not read config file {config_path}: {exc}"
        ) from exc

    if data is None:
        return Config({})
    if not isinstance(data, Mapping):
        raise ConfigError(
            f"Config file {config_path} must contain a mapping, "
            f"got {type(data).__name__}"
        )
    return Config(data)
