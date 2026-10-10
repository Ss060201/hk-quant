"""Corporate actions: canonical schema and helpers.

Corporate actions describe *how historical prices should be represented*
(splits, bonus issues, dividends, rights). They are kept separate from
point-in-time logic, which describes *what the market knew on a given day*.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

import pandas as pd

from hk_quant.data import models
from hk_quant.data.normalization import normalize_stock_id

#: Cash dividend pattern, e.g. "每股派港币5.3元" -> 5.3
_CASH_DIVIDEND_RE = re.compile(r"每股派[^0-9]*([0-9]+(?:\.[0-9]+)?)\s*元")

#: Stock distribution pattern, e.g. "每10股分派1股..." -> 1 new per 10 held
_BONUS_SHARE_RE = re.compile(r"每\s*([0-9]+(?:\.[0-9]+)?)\s*股[^0-9]*?分?派\s*([0-9]+(?:\.[0-9]+)?)\s*股")


def _utc_now() -> pd.Timestamp:
    return pd.Timestamp(datetime.now(timezone.utc))


def parse_dividend_scheme(scheme: object) -> tuple[str, float | None, float | None]:
    """Parse a HK dividend scheme string.

    Returns ``(action_type, cash_amount, factor)`` where:

    * plain cash dividend ("每股派港币5.3元") -> ``("dividend", 5.3, None)``
    * stock distribution ("每10股分派1股...") -> ``("bonus", None, 1.1)``
    * unparseable scheme -> ``("dividend", None, None)`` (never guessed)

    ``factor`` is the multiplicative effect on share count.
    """
    text = str(scheme).strip()

    bonus = _BONUS_SHARE_RE.search(text)
    if bonus:
        base = float(bonus.group(1))
        issued = float(bonus.group(2))
        if base > 0:
            return (models.ACTION_BONUS, None, 1.0 + issued / base)

    cash = _CASH_DIVIDEND_RE.search(text)
    if cash:
        return (models.ACTION_DIVIDEND, float(cash.group(1)), None)

    return (models.ACTION_DIVIDEND, None, None)


def canonicalize_corporate_actions(df: pd.DataFrame, source: str) -> pd.DataFrame:
    """Convert a column-renamed DataFrame into the canonical action schema."""
    result = df.copy()
    if "stock_id" not in result.columns:
        raise ValueError("corporate actions must contain a 'stock_id' column")

    result["stock_id"] = result["stock_id"].map(normalize_stock_id)
    for col in ("event_date", "announcement_date"):
        if col in result.columns:
            result[col] = pd.to_datetime(result[col], errors="coerce")
    for col in ("factor", "cash_amount"):
        if col in result.columns:
            result[col] = pd.to_numeric(result[col], errors="coerce")
    result["source"] = source
    result["ingested_at"] = _utc_now()
    result = result[list(models.CORPORATE_ACTION_COLUMNS)]
    return result.sort_values(["stock_id", "event_date"]).reset_index(drop=True)


def empty_corporate_actions() -> pd.DataFrame:
    """Return an empty canonical corporate actions DataFrame."""
    return pd.DataFrame(columns=list(models.CORPORATE_ACTION_COLUMNS))
