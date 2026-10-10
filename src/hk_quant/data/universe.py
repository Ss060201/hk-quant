"""Historical universe construction.

Answers: *which stocks were in the universe on a given historical date?*

This is separate from point-in-time filtering and from corporate actions.

Important limitation: the current provider (AKShare) does not reliably supply
``listing_date`` / ``delisting_date``. When those fields are unavailable the
universe layer raises :class:`UniverseDataUnavailableError` instead of
silently substituting today's stock list.
"""

from __future__ import annotations

import pandas as pd


class UniverseDataUnavailableError(Exception):
    """Raised when listing/delisting data is unavailable to build a universe."""


def _as_of_timestamp(as_of_date: object) -> pd.Timestamp:
    ts = pd.Timestamp(as_of_date)
    if ts is pd.NaT:
        raise ValueError(f"invalid as_of_date: {as_of_date!r}")
    return ts


def get_universe(master: pd.DataFrame, as_of_date: object) -> pd.DataFrame:
    """Return the stock universe as of ``as_of_date``.

    Inclusion rule::

        listing_date <= as_of_date
        AND (delisting_date is null OR delisting_date >= as_of_date)

    A stock with a null ``listing_date`` cannot be proven to have been listed
    before ``as_of_date``, so it is excluded. If *no* stock has a listing
    date at all, the data source is treated as unavailable and an error is
    raised rather than silently returning the current universe.
    """
    required = ["stock_id", "listing_date", "delisting_date"]
    missing = [c for c in required if c not in master.columns]
    if missing:
        raise UniverseDataUnavailableError(
            f"stock master is missing universe columns: {missing}"
        )

    listing = pd.to_datetime(master["listing_date"], errors="coerce")
    if listing.isna().all():
        raise UniverseDataUnavailableError(
            "listing_date is unavailable (all null); cannot reconstruct a "
            "historical universe from this data source"
        )

    as_of = _as_of_timestamp(as_of_date)
    delisting = pd.to_datetime(master["delisting_date"], errors="coerce")

    included = (
        listing.notna()
        & (listing <= as_of)
        & (delisting.isna() | (delisting >= as_of))
    )
    return master[included].reset_index(drop=True)
