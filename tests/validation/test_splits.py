"""Session-based splits and actual label-end purging."""

from datetime import timedelta

import pandas as pd
import pytest

from hk_quant.validation.splits import (
    DateWindow, purge_overlapping_labels, temporal_split, walk_forward_folds,
)


def test_split_purges_labels_using_observed_sessions() -> None:
    dates = pd.bdate_range("2026-01-01", periods=30).date
    split = temporal_split(dates, label_horizon_days=2, embargo_days=1)
    assert len(split.train_validation_gap) == 3
    assert len(split.validation_test_gap) == 3
    assert split.train.end < split.validation.start < split.validation.end < split.test.start
    assert dates[18] == split.validation.start
    assert dates[24] == split.test.start


def test_walk_forward_has_no_overlapping_test_folds_and_purged_training() -> None:
    dates = pd.bdate_range("2026-01-01", periods=30).date
    folds = walk_forward_folds(
        dates, min_train_days=8, evaluation_days=4, label_horizon_days=2,
        embargo_days=1,
    )
    assert len(folds) >= 2
    assert all(len(fold.gap) == 3 for fold in folds)
    assert all(left.evaluation.end < right.evaluation.start
               for left, right in zip(folds, folds[1:]))


def test_purge_uses_actual_label_end_not_calendar_date_or_event_end() -> None:
    dates = pd.bdate_range("2026-01-01", periods=12).date
    samples = pd.DataFrame({
        "event_date": dates[:5],
        "exit_date": [dates[1], dates[8], dates[3], None, dates[6]],
        "id": [1, 2, 3, 4, 5],
    })
    kept = purge_overlapping_labels(
        samples, DateWindow(dates[0], dates[4]),
        DateWindow(dates[7], dates[10]),
        trading_days=dates, embargo_days=2,
    )
    assert kept["id"].tolist() == [1, 3]


def test_reject_overlapping_or_tiny_splits() -> None:
    dates = pd.bdate_range("2026-01-01", periods=8).date
    with pytest.raises(ValueError, match="not enough"):
        temporal_split(dates, label_horizon_days=3, embargo_days=3)
    with pytest.raises(ValueError, match="step"):
        walk_forward_folds(dates, min_train_days=3, evaluation_days=3, step_days=1)
