# Data readiness before backtests

Run `DataRepository("data/processed").get_data_coverage()` after ingestion. The
returned dictionary records observed row counts, stocks, date ranges, whether
turnover rate and historical listing dates exist, availability of action
announcement dates, and whether the calendar is stored or derived from prices.
It also includes `data_version`, a SHA-256 fingerprint of every processed
Parquet file. Save the dictionary alongside every research or backtest run.

The report describes local files. It does **not** establish that a provider
returned all listed stocks, splits, holidays or trading sessions. AKShare's
current daily feed supplies `amount` (成交額), which is not turnover rate (換手率).
Its current stock list cannot substitute for a historical, delisting-aware
universe. If `turnover_rate_nonnull` and `listing_date_nonnull` are zero,
experiments requiring them must remain blocked. An observed price universe can
be used for exploratory price-only backtests, with survivorship bias disclosed.

`DataStorage` merges same-month daily-price batches by stock and trading day,
atomically replaces partition files, and creates a completion record only
after processed data is saved. Failed ingestions reuse already saved raw
responses when rerun. Storage assumes **one writer at a time**; don't run two
ingestion jobs against the same directory concurrently.

The `provenance/manifest.json` file records a **content fingerprint** of the
current data. Save its contents alongside an experiment if you need the file
hashes from that run. It is not a historical copy of the data: keep source
responses or an immutable processed snapshot to rerun an older experiment
with exactly the same bytes. `repository.get_data_version()` verifies all
current files, catching edits made outside `DataStorage`.

For price-based decisions on historical date T, query
`repository.get_prices(..., end_date=T, adjusted=True)` or pass
`as_of_date=T`. Only corporate actions announced and effective by T will be
used for that adjustment. A panel adjusted once as of its **last** date is
not a valid historical signal source for all earlier dates. Backtest fills
must use raw trading prices, such as T+1 `get_daily_prices()` Open, and account
for missing or untradeable bars separately. Missing corporate action feeds
mean adjusted history cannot be assumed complete.

Useful acceptance checks before accepting a strategy result:

1. For each source field, establish provenance, coverage and earliest
   knowable timestamp. Mark unavailable fields explicitly.
2. Backfill overlapping dates twice and confirm the processed stock-month
   contains the union with one row per `(stock_id, trade_date)`.
3. Fail ingestion after the raw save; rerun and confirm processed data and
   completion record are created without losing the raw response.
4. Insert a split with a future announcement or effective date and confirm
   an earlier T signal is unchanged.
5. Edit a processed value and confirm `get_data_version()` changes. Archive
   the exact processed data if you need to reproduce the older version.
