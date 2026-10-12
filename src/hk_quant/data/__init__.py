"""Market data layer for the HK Quant Research Platform."""

from hk_quant.data.models import (
    ACTION_BONUS,
    ACTION_DIVIDEND,
    ACTION_RIGHTS,
    ACTION_SPLIT,
    CALENDAR_COLUMNS,
    CORPORATE_ACTION_COLUMNS,
    CORPORATE_ACTION_TYPES,
    DAILY_PRICE_COLUMNS,
    FUNDAMENTAL_COLUMNS,
    SOURCE_AKSHARE,
    STOCK_MASTER_COLUMNS,
)
from hk_quant.data.normalization import normalize_stock_id
from hk_quant.data.calendar import TradingCalendar
from hk_quant.data.corporate_actions import (
    canonicalize_corporate_actions,
    empty_corporate_actions,
)
from hk_quant.data.adjustments import adjust_prices
from hk_quant.data.point_in_time import get_available_as_of, get_fundamentals_as_of
from hk_quant.data.universe import UniverseDataUnavailableError, get_universe
from hk_quant.data.provenance import (
    DataProvenance,
    build_data_manifest,
    build_provenance,
    get_data_version,
    make_data_version,
    read_data_manifest,
    read_provenance,
    update_data_manifest,
    write_data_manifest,
    write_provenance,
)
from hk_quant.data.coverage import report_data_coverage, write_coverage_report
from hk_quant.data.storage import DataStorage
from hk_quant.data.repository import DataRepository

__all__ = [
    "ACTION_BONUS",
    "ACTION_DIVIDEND",
    "ACTION_RIGHTS",
    "ACTION_SPLIT",
    "CALENDAR_COLUMNS",
    "CORPORATE_ACTION_COLUMNS",
    "CORPORATE_ACTION_TYPES",
    "DAILY_PRICE_COLUMNS",
    "FUNDAMENTAL_COLUMNS",
    "SOURCE_AKSHARE",
    "STOCK_MASTER_COLUMNS",
    "DataProvenance",
    "DataRepository",
    "DataStorage",
    "TradingCalendar",
    "UniverseDataUnavailableError",
    "adjust_prices",
    "build_data_manifest",
    "build_provenance",
    "canonicalize_corporate_actions",
    "empty_corporate_actions",
    "get_available_as_of",
    "get_data_version",
    "get_fundamentals_as_of",
    "get_universe",
    "make_data_version",
    "normalize_stock_id",
    "read_data_manifest",
    "read_provenance",
    "report_data_coverage",
    "update_data_manifest",
    "write_coverage_report",
    "write_data_manifest",
    "write_provenance",
]
