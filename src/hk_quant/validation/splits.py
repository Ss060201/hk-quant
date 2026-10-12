"""Deterministic trading-session splits and point-in-time label purging."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable

import pandas as pd


@dataclass(frozen=True)
class DateWindow:
    start: date
    end: date

    def to_dict(self) -> dict[str, str]:
        return {"start": self.start.isoformat(), "end": self.end.isoformat()}


@dataclass(frozen=True)
class TemporalSplit:
    train: DateWindow
    validation: DateWindow
    test: DateWindow
    label_horizon_days: int
    embargo_days: int
    train_validation_gap: tuple[date, ...]
    validation_test_gap: tuple[date, ...]

    def to_dict(self) -> dict:
        return {
            "train": self.train.to_dict(),
            "validation": self.validation.to_dict(),
            "test": self.test.to_dict(),
            "label_horizon_days": self.label_horizon_days,
            "embargo_days": self.embargo_days,
            "train_validation_gap": [d.isoformat() for d in self.train_validation_gap],
            "validation_test_gap": [d.isoformat() for d in self.validation_test_gap],
        }


@dataclass(frozen=True)
class WalkForwardFold:
    train: DateWindow
    evaluation: DateWindow
    gap: tuple[date, ...]

    def to_dict(self) -> dict:
        return {
            "train": self.train.to_dict(),
            "evaluation": self.evaluation.to_dict(),
            "gap": [d.isoformat() for d in self.gap],
        }


def _sessions(dates: Iterable[object]) -> list[date]:
    parsed = pd.to_datetime(list(dates), errors="raise")
    if pd.isna(parsed).any():
        raise ValueError("calendar dates must be valid")
    result = sorted({d.date() for d in parsed})
    if not result:
        raise ValueError("calendar has no trading sessions")
    return result


def temporal_split(
    trading_days: Iterable[object],
    *,
    train_fraction: float = 0.6,
    validation_fraction: float = 0.2,
    label_horizon_days: int = 0,
    embargo_days: int = 0,
) -> TemporalSplit:
    """Reserve a final test chronologically; purge earlier boundary labels.

    A training label may use observations at most ``label_horizon_days``
    sessions after its event. The combined horizon and embargo is removed
    *before* each following window. All counts use observed trading days.
    """
    days = _sessions(trading_days)
    if not 0 < train_fraction < 1 or not 0 < validation_fraction < 1:
        raise ValueError("split fractions must be strictly between zero and one")
    if train_fraction + validation_fraction >= 1:
        raise ValueError("reserve a nonempty test interval")
    if label_horizon_days < 0 or embargo_days < 0:
        raise ValueError("label horizon and embargo must be nonnegative")
    first = int(len(days) * train_fraction)
    second = int(len(days) * (train_fraction + validation_fraction))
    gap = label_horizon_days + embargo_days
    if first - gap < 1 or second - first - gap < 1 or second >= len(days):
        raise ValueError("not enough trading sessions for three purged windows")
    return TemporalSplit(
        train=DateWindow(days[0], days[first-gap-1]),
        validation=DateWindow(days[first], days[second-gap-1]),
        test=DateWindow(days[second], days[-1]),
        label_horizon_days=label_horizon_days,
        embargo_days=embargo_days,
        train_validation_gap=tuple(days[first-gap:first]),
        validation_test_gap=tuple(days[second-gap:second]),
    )


def walk_forward_folds(
    trading_days: Iterable[object],
    *,
    min_train_days: int,
    evaluation_days: int,
    step_days: int | None = None,
    label_horizon_days: int = 0,
    embargo_days: int = 0,
    expanding: bool = True,
) -> list[WalkForwardFold]:
    """Produce strictly ordered, nonoverlapping OOS windows.

    ``step_days`` defaults to the test window size; overlapping evaluation
    windows are rejected to avoid double-counting reported OOS performance.
    """
    days = _sessions(trading_days)
    step = evaluation_days if step_days is None else step_days
    if min_train_days < 1 or evaluation_days < 1 or step < evaluation_days:
        raise ValueError("require positive windows and step >= evaluation_days")
    if label_horizon_days < 0 or embargo_days < 0:
        raise ValueError("label horizon and embargo must be nonnegative")
    gap = label_horizon_days + embargo_days
    folds: list[WalkForwardFold] = []
    start = min_train_days + gap
    while start + evaluation_days <= len(days):
        train_end = start - gap - 1
        train_start = 0 if expanding else train_end - min_train_days + 1
        folds.append(WalkForwardFold(
            train=DateWindow(days[train_start], days[train_end]),
            evaluation=DateWindow(days[start], days[start + evaluation_days - 1]),
            gap=tuple(days[train_end + 1:start]),
        ))
        start += step
    if not folds:
        raise ValueError("not enough trading sessions for one walk-forward fold")
    return folds


def purge_overlapping_labels(
    samples: pd.DataFrame,
    train: DateWindow,
    evaluation: DateWindow,
    *,
    event_column: str = "event_date",
    label_end_column: str = "exit_date",
    embargo_days: int = 0,
    trading_days: Iterable[object] | None = None,
) -> pd.DataFrame:
    """Keep only training events whose actual label ends before evaluation.

    The end date must be present, not inferred from a calendar-day offset.
    Null label ends are excluded. A positive embargo requires an explicit
    trading calendar, and additionally removes recent pre-evaluation events.
    """
    if embargo_days < 0:
        raise ValueError("embargo_days must be nonnegative")
    if event_column not in samples or label_end_column not in samples:
        raise ValueError("event and label end columns are required")
    if train.end >= evaluation.start:
        raise ValueError("training window must precede evaluation")
    cutoff = pd.Timestamp(evaluation.start)
    if embargo_days:
        if trading_days is None:
            raise ValueError("trading_days required for an embargo")
        earlier = [d for d in _sessions(trading_days) if d < evaluation.start]
        if len(earlier) < embargo_days:
            raise ValueError("insufficient trading sessions for embargo")
        cutoff = pd.Timestamp(earlier[-embargo_days])
    events = pd.to_datetime(samples[event_column], errors="coerce")
    ends = pd.to_datetime(samples[label_end_column], errors="coerce")
    mask = (
        events.between(pd.Timestamp(train.start), pd.Timestamp(train.end))
        & ends.notna()
        & (ends < cutoff)
    )
    return samples.loc[mask].copy()
