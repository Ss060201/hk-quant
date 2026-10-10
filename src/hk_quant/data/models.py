"""Canonical data schemas for the HK Quant Research Platform.

These schemas define the single source of truth for how market data is
represented inside the system, independent of any external provider.
"""

from __future__ import annotations

#: Canonical column order for the daily price table.
#: ``stock_id``  str, normalized internal id (e.g. "0700")
#: ``trade_date`` datetime.date
#: ``open/high/low/close`` float
#: ``volume`` float, provider raw volume (shares, unadjusted)
#: ``amount`` float, provider raw trading amount (成交額, unadjusted)
#: ``turnover_rate`` float or None, 換手率 as a ratio (0.10 = 10%).
#:     NOT available from the current provider; kept nullable and never
#:     substituted with ``amount``.
#: ``source`` str, provider name (e.g. "akshare")
#: ``ingested_at`` timestamp (UTC), when data entered the system
DAILY_PRICE_COLUMNS: tuple[str, ...] = (
    "stock_id",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "turnover_rate",
    "source",
    "ingested_at",
)

#: Canonical column order for the stock master table.
#: ``stock_id`` str, normalized internal id (e.g. "0700")
#: ``symbol`` str, provider symbol (e.g. "00700")
#: ``name`` str, security name
#: ``listing_date`` datetime.date or None
#: ``delisting_date`` datetime.date or None
#: ``status`` str or None
#: ``source`` str, provider name
#: ``ingested_at`` timestamp (UTC)
STOCK_MASTER_COLUMNS: tuple[str, ...] = (
    "stock_id",
    "symbol",
    "name",
    "listing_date",
    "delisting_date",
    "status",
    "source",
    "ingested_at",
)

#: Provider name used by the AKShare adapter.
SOURCE_AKSHARE: str = "akshare"

#: Canonical column order for the point-in-time fundamental table.
#: ``stock_id`` str
#: ``period_end`` datetime.date, the period the fact describes
#: ``announcement_date`` datetime.date or None, when the market learned it
#: ``effective_date`` datetime.date or None, when it takes effect
#: ``metric`` str, e.g. "revenue"
#: ``value`` float
#: ``source`` str
#: ``ingested_at`` timestamp (UTC)
FUNDAMENTAL_COLUMNS: tuple[str, ...] = (
    "stock_id",
    "period_end",
    "announcement_date",
    "effective_date",
    "metric",
    "value",
    "source",
    "ingested_at",
)

#: Canonical column order for the corporate actions table.
#: ``stock_id`` str
#: ``event_date`` datetime.date, when the action takes effect on prices
#: ``announcement_date`` datetime.date or None, when it became known
#: ``action_type`` str, one of ``CORPORATE_ACTION_TYPES``
#: ``factor`` float or None, multiplicative effect on share count
#: ``cash_amount`` float or None, cash per share for dividends
#: ``source`` str
#: ``ingested_at`` timestamp (UTC)
CORPORATE_ACTION_COLUMNS: tuple[str, ...] = (
    "stock_id",
    "event_date",
    "announcement_date",
    "action_type",
    "factor",
    "cash_amount",
    "source",
    "ingested_at",
)

#: Canonical column order for the trading calendar table.
CALENDAR_COLUMNS: tuple[str, ...] = ("trade_date",)

#: Corporate action types (designed; only implemented where a provider
#: actually supplies them).
ACTION_SPLIT: str = "split"
ACTION_BONUS: str = "bonus"
ACTION_DIVIDEND: str = "dividend"
ACTION_RIGHTS: str = "rights"

CORPORATE_ACTION_TYPES: tuple[str, ...] = (
    ACTION_SPLIT,
    ACTION_BONUS,
    ACTION_DIVIDEND,
    ACTION_RIGHTS,
)
