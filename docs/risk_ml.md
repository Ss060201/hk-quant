# Historical risk and conditional failure model

## Risk report (Phase 12)

`hk_quant.risk.analyze_risk(stock_prices, *, as_of_date, data_version, ...)`
accepts a canonical `stock_id, trade_date, close` price table; optional `open`
and `amount` support worst overnight gap and median **traded amount**. Amount
is a liquidity proxy, never turnover rate. The function also accepts a dated
portfolio equity/turnover series, daily position snapshots with fractional
weights, and dated sector/factor metadata with an explicit source. Inputs after
`as_of_date` are excluded. There is no provider or broker call.

For an existing backtest, use
`analyze_backtest_risk(backtest_result, stock_prices, as_of_date=...)`. The
adapter derives position weights from market value / same-day equity and
propagates the backtest's limitations. Pass prices from the same data version;
that match is the caller's responsibility. A `RiskResult` can be stored via
`register_risk_result(report, ExperimentRegistry(root))`.

| Metric | Formula / convention | Missing rule |
| --- | --- | --- |
| Historical volatility | Sample standard deviation of daily simple close returns (`ddof=1`) × `sqrt(annualization)`, default 252. Last `window` observed returns. | Fewer than two returns → `null`. |
| Downside volatility | `sqrt(mean(min(daily_return, 0)^2) × annualization)` using zero target and **all** valid daily returns. | No return → `null`. |
| Worst overnight gap | Minimum of zero and `open_t / close_(t-1) - 1`. | Missing valid adjacent Open/Close → `null`. |
| Liquidity proxy | Median daily `amount` in input provider units. | Missing `amount` → `null`; currency/lot conversion is not invented. |
| Equity max drawdown | `min(equity / cumulative_peak - 1)`; the supplied initial capital is included as the initial peak. | Missing/nonpositive equity → `null`/error. |
| Correlation | Pairwise Pearson on aligned dated close returns, with at least 2 joint days and nonzero variance in both. | Too few paired dates or zero variance → `null`. |
| Concentration | Sum of squared **current dated** position weights, cash excluded. | No dated weights → `null`. |
| Sector/factor exposure | Sum of current position weights per dated sector / sum of weight × supplied dated numeric `factor_*` value (cash contributes zero). | No source, classification or complete factor coverage → `null`, with warning. |
| Cost sensitivity | Multiply `(1 + observed portfolio daily return - traded_notional/equity × extra_bps/10000)` across daily observations; assumes the input backtest already included its original costs. | Missing or invalid turnover → `null`. |

These are historical descriptions. Regime sensitivity and accurate drawdown
contribution need dated regimes and **daily pre-return** holding weights;
they are reported unavailable. No VaR, prediction, sizing, signal or order
generation is performed. Corporate actions and stale marks remain subject to
the underlying price/backtest provenance.

## Fixed conditional outcome (Phase 13)

`build_conditional_dataset(signals, features, raw_prices, *, strategy_id,
strategy_version, data_version, feature_source, feature_columns)` selects
only valid BUY signals from one fixed strategy version. Its **single** label is
`1` when the stock's raw close return from the signal date to **20 observed
trading days later** is below `-5%`; otherwise `0`. No missing end price is
filled, and rows with an incomplete horizon are counted as discarded. The
observed input calendar is not an official HKEX calendar; raw returns omit
dividends and may be distorted by corporate actions. The caller must certify
that input raw prices really are raw and that each input feature was derived
only from data known at its `available_at` timestamp. The builder joins the
latest feature row with `available_at <= signal_date`, and the outcome fields
are not selectable features.

`evaluate_conditional_model(dataset, ...)` uses expanding, date-grouped,
walk-forward folds. Training rows whose label ends on/after the first test
date are purged; an optional calendar-day embargo lengthens that gap. Median
imputation, scaling and logistic regression are fitted **only** within each
training fold. The reference score is the training fold's event frequency;
the decision threshold of `0.5` is fixed in advance. Each held-out fold
reports event prevalence, PR-AUC (when positives exist), ROC-AUC (when both
classes exist), Brier, 5-bin reliability table, precision and recall. Scores
are **not probability-calibrated**; no model is promoted to a strategy.

If data or the optional `scikit-learn` dependency are absent, result status is
`BLOCKED`; no fake real-data model score is produced. `Strategy vs Strategy+ML`
net performance remains `BLOCKED` unless the caller supplies an independent
cost-aware out-of-sample backtest callback; no trade-level outcome averages
are presented as portfolio returns. The callback sees only dated OOS signal
identifiers and scores, never labels. To snapshot the full labeled sample,
predictions and metrics in the experiment registry, call
`register_conditional_result(result, dataset, registry)`.

`python -m unittest discover -s tests/risk` and
`python -m unittest discover -s tests/ml` run the isolated synthetic checks
with `PYTHONPATH=src`. Full repository tests require its normal dependencies.
