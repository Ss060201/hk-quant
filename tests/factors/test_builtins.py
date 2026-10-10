"""Built-in factor calculation tests."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from hk_quant.factors.registry import DEFAULT_REGISTRY


def test_momentum_20_hand_calculation() -> None:
    calc = DEFAULT_REGISTRY.get_calculator("momentum_20")
    close = pd.Series([100.0 + i for i in range(21)])  # 100 .. 120
    assert calc(close) == pytest.approx(120.0 / 100.0 - 1.0)


def test_momentum_insufficient_history_is_nan() -> None:
    calc = DEFAULT_REGISTRY.get_calculator("momentum_20")
    close = pd.Series([100.0] * 10)
    assert math.isnan(calc(close))


def test_volatility_20_is_daily_scale_not_annualized() -> None:
    calc = DEFAULT_REGISTRY.get_calculator("volatility_20")
    close = pd.Series([100.0, 102.0] * 11)  # 22 closes, alternating +-2%
    value = calc(close)
    assert not math.isnan(value)
    assert 0.0 < value < 0.1  # daily scale, far below an annualized ~0.3


def test_volatility_insufficient_history_is_nan() -> None:
    calc = DEFAULT_REGISTRY.get_calculator("volatility_20")
    close = pd.Series([100.0, 101.0])
    assert math.isnan(calc(close))
