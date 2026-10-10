"""Relationship analysis tests."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from hk_quant.research.relationships import (
    classify_pattern,
    spearman_rank_correlation,
)


def test_spearman_perfect_increasing() -> None:
    rho, p_value = spearman_rank_correlation(
        pd.Series([1, 2, 3, 4, 5]), pd.Series([10, 20, 30, 40, 50])
    )
    assert rho == pytest.approx(1.0)
    assert p_value < 0.05


def test_spearman_perfect_decreasing() -> None:
    rho, _ = spearman_rank_correlation(
        pd.Series([1, 2, 3, 4, 5]), pd.Series([50, 40, 30, 20, 10])
    )
    assert rho == pytest.approx(-1.0)


def test_spearman_ignores_nan() -> None:
    rho, p_value = spearman_rank_correlation(
        pd.Series([1.0, 2.0, 3.0, float("nan"), 5.0]),
        pd.Series([10.0, 20.0, 30.0, 40.0, 50.0]),
    )
    assert not math.isnan(rho)


def test_classify_increasing() -> None:
    assert classify_pattern([0.2, 0.7, 1.4, 2.1, 2.8]) == "increasing"


def test_classify_decreasing() -> None:
    assert classify_pattern([2.8, 2.1, 1.4, 0.7, 0.2]) == "decreasing"


def test_classify_non_monotonic_peak() -> None:
    # rises then falls: must NOT be called "increasing"
    assert classify_pattern([0.2, 0.7, 1.4, 2.1, 1.9, 1.2]) == "non_monotonic"


def test_classify_no_clear_pattern() -> None:
    assert classify_pattern([0.5]) == "no_clear_pattern"
    assert classify_pattern([0.1, -0.1, 0.05, 0.2, -0.15, 0.3]) == "no_clear_pattern"
