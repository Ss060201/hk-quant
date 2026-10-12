"""Purged, forward-only evaluation of conditional adverse-outcome scores."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from hk_quant.ml.models import ConditionalDataset, ConditionalModelResult


@dataclass(frozen=True)
class PurgedFold:
    train_indices: tuple[int, ...]
    test_indices: tuple[int, ...]
    first_test_date: str
    last_test_date: str
    purged_train_samples: int


def walk_forward_splits(
    samples: pd.DataFrame,
    *,
    initial_train_dates: int = 60,
    test_dates: int = 20,
    embargo_calendar_days: int = 0,
) -> Iterator[PurgedFold]:
    """Expanding chronological folds; train labels must end BEFORE test start.

    `embargo_calendar_days` adds a calendar-day gap between label end and the
    first test signal. Sample rows from the same date stay in the same fold.
    A dropped/missing label cannot be used in either training or testing.
    """
    if initial_train_dates < 2 or test_dates < 1 or embargo_calendar_days < 0:
        raise ValueError("invalid train/test/embargo size")
    needed = {"signal_date", "label_period_end", "label"}
    if not needed.issubset(samples.columns):
        raise ValueError(f"samples missing {needed.difference(samples.columns)}")
    dates = pd.to_datetime(samples.signal_date, errors="raise").dt.normalize()
    ends = pd.to_datetime(samples.label_period_end, errors="raise").dt.normalize()
    if dates.isna().any() or ends.isna().any() or (ends <= dates).any():
        raise ValueError("samples require valid forward label dates")
    if samples.label.isna().any():
        raise ValueError("unlabelled rows must be excluded before splitting")
    distinct_dates = sorted(dates.unique())
    for offset in range(initial_train_dates, len(distinct_dates), test_dates):
        chunk = distinct_dates[offset:offset + test_dates]
        first_test = chunk[0]
        cutoff = first_test - pd.Timedelta(days=embargo_calendar_days)
        before_test = dates < first_test
        # Last allowed training outcome must be *strictly before* the first
        # test signal, even when an event spans an otherwise valid boundary.
        training = before_test & (ends < cutoff)
        testing = dates.isin(chunk)
        yield PurgedFold(
            train_indices=tuple(np.flatnonzero(training)),
            test_indices=tuple(np.flatnonzero(testing)),
            first_test_date=first_test.date().isoformat(),
            last_test_date=chunk[-1].date().isoformat(),
            purged_train_samples=int((before_test & ~training).sum()),
        )


def _classification_metrics(y: np.ndarray, score: np.ndarray,
                            threshold: float) -> dict[str, Any]:
    from sklearn.metrics import (average_precision_score, brier_score_loss,
                                 precision_score, recall_score, roc_auc_score)

    positives = int(y.sum())
    bins = np.minimum((score * 5).astype(int), 4)
    reliability = [
        {"score_range": [i / 5, (i + 1) / 5], "count": int((bins == i).sum()),
         "mean_score": float(score[bins == i].mean()) if (bins == i).any() else None,
         "observed_event_rate": float(y[bins == i].mean()) if (bins == i).any() else None}
        for i in range(5)
    ]
    return {
        "count": len(y), "positives": positives, "event_fraction": positives / len(y),
        "pr_auc": float(average_precision_score(y, score)) if positives else None,
        "roc_auc": float(roc_auc_score(y, score)) if 0 < positives < len(y) else None,
        "brier": float(brier_score_loss(y, score)),
        "precision": float(precision_score(y, score >= threshold, zero_division=0)),
        "recall": float(recall_score(y, score >= threshold, zero_division=0)),
        "reliability_bins": reliability,
    }


def evaluate_conditional_model(
    dataset: ConditionalDataset,
    *,
    initial_train_dates: int = 60,
    test_dates: int = 20,
    embargo_calendar_days: int = 0,
    min_train_samples: int = 30,
    seed: int = 42,
    compare_strategy: Callable[[pd.DataFrame], dict[str, Any]] | None = None,
) -> ConditionalModelResult:
    """Compare train-fold prevalence baseline with logistic regression OOS.

    Fit imputation, scaling and logistic regression *inside each training
    fold*, with no future label end crossing the fold boundary. No parameter
    tuning or probability calibration is done; Brier and reliability bins
    measure calibration quality, and raw scores are not certified posterior
    probabilities. A separate backtest callback is required to claim net
    strategy/strategy+ML performance. It receives only OOS identifiers,
    model score and the fixed threshold; never future labels or returns.
    """
    if min_train_samples < 2:
        raise ValueError("min_train_samples must be >= 2")
    model_config = {"estimator": "logistic_regression", "class_weight": None,
                    "preprocessing": "train_fold_median_imputation_and_standard_scaling",
                    "decision_threshold": 0.5, "threshold_selection": "fixed_before_OOS",
                    "calibration": "unfitted_diagnostics_only", "seed": seed}
    split_config = {"initial_train_dates": initial_train_dates, "test_dates": test_dates,
                    "embargo_calendar_days": embargo_calendar_days,
                    "min_train_samples": min_train_samples,
                    "purge": "train.label_period_end < first_test_date - embargo_calendar_days"}
    warnings = list(dataset.warnings)
    if dataset.samples.empty:
        return ConditionalModelResult("BLOCKED", dataset.strategy_id, dataset.strategy_version,
                                      dataset.data_version, dataset.feature_columns, None,
                                      model_config, dataset.label_definition, split_config,
                                      [], pd.DataFrame(), None, warnings + ["No labelled BUY signals."])
    try:
        import sklearn
        from sklearn.impute import SimpleImputer
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
    except ImportError:
        return ConditionalModelResult("BLOCKED", dataset.strategy_id, dataset.strategy_version,
                                      dataset.data_version, dataset.feature_columns, None,
                                      model_config, dataset.label_definition, split_config,
                                      [], pd.DataFrame(), None,
                                      warnings + ["Optional scikit-learn dependency missing; ML evaluation BLOCKED."])
    rows = dataset.samples.reset_index(drop=True)
    if not rows.label.isin([0, 1]).all():
        raise ValueError("binary labels must be 0 or 1")
    for feature in dataset.feature_columns:
        if feature not in rows:
            raise ValueError(f"missing model feature {feature}")
    fold_metrics: list[dict] = []
    predictions: list[dict] = []
    for fold_idx, fold in enumerate(walk_forward_splits(
        rows, initial_train_dates=initial_train_dates, test_dates=test_dates,
        embargo_calendar_days=embargo_calendar_days,
    )):
        train = rows.iloc[list(fold.train_indices)]
        test = rows.iloc[list(fold.test_indices)]
        if len(train) < min_train_samples or train.label.nunique() < 2:
            warnings.append(f"Fold {fold_idx}: too few purged training samples or only one class; skipped.")
            continue
        if train[list(dataset.feature_columns)].isna().all().any():
            warnings.append(f"Fold {fold_idx}: a feature has no observed training values; skipped.")
            continue
        pipeline = make_pipeline(
            SimpleImputer(strategy="median", add_indicator=True, keep_empty_features=True),
            StandardScaler(), LogisticRegression(max_iter=1000, random_state=seed),
        )
        train_x = train.loc[:, list(dataset.feature_columns)]
        test_x = test.loc[:, list(dataset.feature_columns)]
        pipeline.fit(train_x, train.label)
        score = pipeline.predict_proba(test_x)[:, 1]
        base_score = np.full(len(test), float(train.label.mean()))
        y = test.label.to_numpy(dtype=int)
        fold_metrics.append({
            "fold": fold_idx, "train_samples": len(train), "test_samples": len(test),
            "train_positive_fraction": float(train.label.mean()),
            "first_test_date": fold.first_test_date, "last_test_date": fold.last_test_date,
            "purged_train_samples": fold.purged_train_samples,
            "model": _classification_metrics(y, score, 0.5),
            "prevalence_baseline": _classification_metrics(y, base_score, 0.5),
        })
        if len(set(y)) < 2:
            warnings.append(f"Fold {fold_idx}: single-class test set; ROC-AUC unavailable.")
        for (_, row), value, baseline in zip(test.iterrows(), score, base_score):
            predictions.append({"fold": fold_idx, "stock_id": row.stock_id,
                                "signal_date": pd.Timestamp(row.signal_date).date().isoformat(),
                                "label": int(row.label), "model_score": float(value),
                                "baseline_score": float(baseline)})
    prediction_frame = pd.DataFrame.from_records(predictions)
    comparison = None
    if compare_strategy is not None and not prediction_frame.empty:
        # Only identifiers and prespecified model decisions reach the portfolio
        # evaluator; labels and future outcomes are never exposed to it.
        compare_input = prediction_frame[["stock_id", "signal_date", "model_score"]].copy()
        compare_input["skip_buy_when_score_at_least"] = 0.5
        comparison = compare_strategy(compare_input)
        needed = {"strategy_net_return", "strategy_plus_ml_net_return", "cost_config"}
        if not isinstance(comparison, dict) or not needed.issubset(comparison):
            raise ValueError(f"comparison callback must return {sorted(needed)}")
    else:
        warnings.append("Strategy vs Strategy+ML OOS net comparison BLOCKED: no independent cost-aware backtest callback or no OOS predictions.")
    if prediction_frame.empty:
        warnings.append("Insufficient class-balanced training history after purge; model evaluation BLOCKED.")
    else:
        warnings.append("Raw model scores have not been probability-calibrated; inspect Brier and reliability bins.")
    return ConditionalModelResult(
        "EVALUATED" if not prediction_frame.empty else "BLOCKED",
        dataset.strategy_id, dataset.strategy_version, dataset.data_version,
        dataset.feature_columns, f"sklearn-{sklearn.__version__}-logistic-regression",
        model_config, dataset.label_definition, split_config, fold_metrics,
        prediction_frame, comparison, warnings,
    )
