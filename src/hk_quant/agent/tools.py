"""Strict, finite tools for a research agent (no arbitrary SQL, shell or orders)."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from hk_quant.agent.planner import plan_research

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}\Z")
_STOCK = re.compile(r"[A-Za-z0-9]{1,16}\Z")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
_FIELDS = {"open", "high", "low", "close", "volume", "amount", "turnover_rate"}
_CONFIG_KEYS = {
    "name", "variable", "forward_periods", "event_mode", "return", "date_range",
    "universe", "price", "exploratory",
}


def _stocks(value: Any, *, maximum: int = 20) -> list[str]:
    if not isinstance(value, list) or not 1 <= len(value) <= maximum or any(
        not isinstance(s, str) or not _STOCK.fullmatch(s) for s in value
    ):
        raise ToolFault("INVALID_INPUT", f"stock_ids must contain 1–{maximum} alphanumeric identifiers")
    if len(set(value)) != len(value):
        raise ToolFault("INVALID_INPUT", "duplicate stock_ids are not allowed")
    return value


def _strategy_key(data: dict[str, Any]) -> tuple[str, str]:
    strategy_id, version = data["strategy_id"], data["version"]
    if not isinstance(strategy_id, str) or not _ID.fullmatch(strategy_id):
        raise ToolFault("INVALID_INPUT", "invalid strategy_id")
    if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ToolFault("INVALID_INPUT", "version must use major.minor.patch")
    return strategy_id, version


def _as_of_adjustment_verified(repository: Any) -> bool:
    """Only the repository with a T-bound adjustment contract is accepted."""
    try:
        from hk_quant.data.repository import DataRepository

        return isinstance(repository, DataRepository)
    except ImportError:
        return False
_NESTED_KEYS = {
    "variable": {"name", "thresholds", "unit"},
    "return": {"entry", "exit", "type", "dividend"},
    "date_range": {"start", "end"},
    "universe": {"mode"},
    "price": {"adjusted"},
}


class ToolFault(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _keys(args: Any, allowed: set[str], *, required: set[str] = frozenset()) -> dict[str, Any]:
    if not isinstance(args, dict):
        raise ToolFault("INVALID_INPUT", "arguments must be an object")
    unknown = set(args) - allowed
    missing = required - set(args)
    if unknown or missing:
        raise ToolFault("INVALID_INPUT", f"unexpected keys {sorted(unknown)}; missing keys {sorted(missing)}")
    return args


def _iso(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _DATE.fullmatch(value):
        raise ToolFault("INVALID_INPUT", f"{field} must be YYYY-MM-DD")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ToolFault("INVALID_INPUT", f"{field} is not a calendar date") from exc
    return value


def _strict_config(raw: Any, *, max_combinations: int) -> dict[str, Any]:
    data = _keys(raw, _CONFIG_KEYS, required={"name", "variable", "forward_periods", "date_range"})
    if not isinstance(data["name"], str) or not _ID.fullmatch(data["name"]):
        raise ToolFault("INVALID_INPUT", "research.name must be 1–80 safe identifier characters")
    for key, allowed in _NESTED_KEYS.items():
        if key in data:
            _keys(data[key], allowed)

    variable = _keys(data["variable"], _NESTED_KEYS["variable"], required={"name", "thresholds"})
    name = variable["name"]
    if not isinstance(name, str) or name not in _FIELDS:
        raise ToolFault("INVALID_INPUT", f"variable.name must be one of {sorted(_FIELDS)}")
    if variable.get("unit", "ratio") != "ratio":
        raise ToolFault("INVALID_INPUT", "thresholds must use ratio units (10% = 0.10)")
    thresholds = variable["thresholds"]
    periods = data["forward_periods"]
    if not isinstance(thresholds, list) or not thresholds or any(
        isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n) or n <= 0 or n > 1e12
        for n in thresholds
    ):
        raise ToolFault("INVALID_INPUT", "thresholds must be finite positive numbers")
    if not isinstance(periods, list) or not periods or any(
        isinstance(n, bool) or not isinstance(n, int) or n < 1 or n > 180
        for n in periods
    ):
        raise ToolFault("INVALID_INPUT", "forward_periods must be integers from 1 to 180")
    if len(set(thresholds)) != len(thresholds) or len(set(periods)) != len(periods):
        raise ToolFault("INVALID_INPUT", "duplicate thresholds or forward_periods are not allowed")
    if len(thresholds) * len(periods) > max_combinations:
        raise ToolFault("BUDGET_EXCEEDED", f"maximum {max_combinations} threshold × period combinations per run")

    window = _keys(data["date_range"], {"start", "end"}, required={"start", "end"})
    start, end = _iso(window["start"], "date_range.start"), _iso(window["end"], "date_range.end")
    if start > end:
        raise ToolFault("INVALID_INPUT", "date_range.start must be on or before end")
    if (date.fromisoformat(end) - date.fromisoformat(start)).days > 3652:
        raise ToolFault("BUDGET_EXCEEDED", "research window cannot exceed ten years")
    if data.get("exploratory", True) is not True:
        raise ToolFault("INVALID_INPUT", "research with an observed universe must be marked exploratory")
    if data.get("universe", {}).get("mode", "observed_price_universe") != "observed_price_universe":
        raise ToolFault("DATA_UNAVAILABLE", "a verified historical universe is required for historical_universe")
    price = data.get("price", {"adjusted": False})
    if price.get("adjusted", False) is not False:
        raise ToolFault("INVALID_INPUT", "historical agent runs require raw prices until as-of adjustment is verified")
    # Keep a defensive copy, so a caller cannot change the config mid-run.
    return {**data, "price": {"adjusted": False}, "exploratory": True}


def _json_value(value: Any) -> Any:
    """Produce JSON-compatible values from pandas/numpy scalar fields."""
    if is_dataclass(value) and not isinstance(value, type):
        return _json_value(asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _json_value(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(v) for v in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "item"):
        return _json_value(value.item())
    if isinstance(value, float) and (value != value or abs(value) == float("inf")):
        return None
    return value


class ResearchTools:
    """Bounded adapter over DataRepository + ResearchEngine + ExperimentRegistry.

    Each call returns a stable envelope; a failing deterministic engine is never
    misreported as successful research. The registry is optional for read-only
    tools but mandatory for a new research run.
    """

    def __init__(
        self,
        repository: Any,
        research_root: str | Path,
        registry: Any | None = None,
        *,
        max_combinations: int = 40,
        strategies_root: str | Path = "strategies",
    ) -> None:
        self.repository = repository
        self.research_root = Path(research_root).resolve()
        self.registry = registry
        self.strategies_root = Path(strategies_root).resolve()
        if not isinstance(max_combinations, int) or max_combinations < 1 or max_combinations > 200:
            raise ValueError("max_combinations must be from 1 to 200")
        self.max_combinations = max_combinations

    def call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        handlers = {
            "get_data_coverage": self.get_data_coverage,
            "get_market_data": self.get_market_data,
            "plan_research": self.plan_research,
            "run_research": self.run_research,
            "get_research_result": self.get_research_result,
            "get_experiment": self.get_experiment,
            "compare_experiments": self.compare_experiments,
            "create_strategy": self.create_strategy,
            "validate_strategy": self.validate_strategy,
            "generate_signals": self.generate_signals,
            "run_backtest": self.run_backtest,
            "run_validation": self.run_validation,
            "run_risk_analysis": self.run_risk_analysis,
        }
        if tool not in handlers:
            return {"ok": False, "tool": tool, "error": {"code": "UNKNOWN_TOOL", "message": "unknown or disabled tool"}}
        try:
            result = handlers[tool](arguments)
            return {"ok": True, "tool": tool, "data": _json_value(result)}
        except ToolFault as exc:
            return {"ok": False, "tool": tool, "error": {"code": exc.code, "message": str(exc)}}
        except Exception as exc:
            # No stack traces, SQL, filesystem paths, broker responses or secrets
            # are exposed to the agent; detailed errors stay in trusted logs.
            import logging

            logging.getLogger(__name__).exception("research tool %s failed", tool)
            return {"ok": False, "tool": tool, "error": {"code": "ENGINE_FAILED", "message": "research engine failed; check local logs"}}

    def get_data_coverage(self, args: dict[str, Any]) -> dict[str, Any]:
        _keys(args, set())
        if not hasattr(self.repository, "get_data_coverage"):
            raise ToolFault("DATA_UNAVAILABLE", "data coverage report has not been configured")
        return self.repository.get_data_coverage()

    def get_market_data(self, args: dict[str, Any]) -> dict[str, Any]:
        data = _keys(args, {"stock_ids", "start_date", "end_date", "limit"}, required={"stock_ids", "start_date", "end_date"})
        stocks = _stocks(data["stock_ids"], maximum=10)
        start, end = _iso(data["start_date"], "start_date"), _iso(data["end_date"], "end_date")
        if start > end:
            raise ToolFault("INVALID_INPUT", "start_date must be on or before end_date")
        limit = data.get("limit", 200)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ToolFault("INVALID_INPUT", "limit must be an integer from 1 to 500")
        prices = self.repository.get_daily_prices(stock_ids=stocks, start_date=start, end_date=end)
        if len(prices) > limit:
            raise ToolFault("BUDGET_EXCEEDED", f"query returned {len(prices)} rows; narrow the date range or raise limit to at most 500")
        columns = [c for c in ("stock_id", "trade_date", "open", "high", "low", "close", "volume", "amount", "turnover_rate", "source") if c in prices]
        return {"count": len(prices), "rows": prices[columns].to_dict(orient="records"), "warnings": ["amount is trading value, not turnover_rate"]}

    def plan_research(self, args: dict[str, Any]) -> dict[str, Any]:
        data = _keys(args, {"question", "start_date", "end_date", "thresholds", "forward_periods"}, required={"question"})
        try:
            plan = plan_research(**data)
            if plan["status"] == "READY":
                _strict_config(plan["config"], max_combinations=self.max_combinations)
            return plan
        except ValueError as exc:
            raise ToolFault("INVALID_INPUT", str(exc)) from exc

    def run_research(self, args: dict[str, Any]) -> dict[str, Any]:
        data = _keys(args, {"config"}, required={"config"})
        config = _strict_config(data["config"], max_combinations=self.max_combinations)
        coverage = self.get_data_coverage({})
        prices = coverage.get("daily_prices", {})
        field = config["variable"]["name"]
        if field == "turnover_rate" and not prices.get("turnover_rate_nonnull", 0):
            raise ToolFault("DATA_UNAVAILABLE", "turnover_rate has no verified observations; amount is not a substitute")
        if not prices.get("row_count", 0):
            raise ToolFault("DATA_UNAVAILABLE", "no processed daily prices are available")
        if self.registry is None:
            raise ToolFault("REGISTRY_UNAVAILABLE", "experiment registry is required to persist a research run")

        # Import the deterministic engine only after input/coverage validation.
        from hk_quant.research.config import _build_definition
        from hk_quant.research.engine import ResearchDataError, run_research
        from hk_quant.research.results import build_summary

        definition = _build_definition(config)
        version = self.repository.get_data_version()
        try:
            result = run_research(definition, repository=self.repository, data_version=version)
        except ResearchDataError as exc:
            raise ToolFault("DATA_UNAVAILABLE", str(exc)) from exc
        record = self.registry.register_research_result(result)
        return {
            "experiment_id": record.experiment_id,
            "config_hash": record.config_hash,
            "summary": build_summary(result),
            "artifact": str(record.artifact_dir),
            "warnings": record.warnings,
        }

    def get_research_result(self, args: dict[str, Any]) -> dict[str, Any]:
        data = _keys(args, {"experiment_id"}, required={"experiment_id"})
        experiment_id = data["experiment_id"]
        if not isinstance(experiment_id, str) or not re.fullmatch(r"[a-f0-9]{32}", experiment_id):
            raise ToolFault("INVALID_INPUT", "experiment_id must be the issued 32-character hexadecimal ID")
        if self.registry is None:
            raise ToolFault("REGISTRY_UNAVAILABLE", "experiment registry is not configured")
        record = self.registry.get_experiment(experiment_id)
        if record.experiment_type != "research":
            raise ToolFault("INVALID_INPUT", "experiment is not a research run")
        if "summary.json" not in record.artifacts:
            raise ToolFault("NOT_FOUND", "research summary artifact is missing")
        path = record.artifact_dir / "summary.json"
        root = self.registry.artifacts_root.resolve()
        if not path.is_file() or not path.resolve().is_relative_to(root):
            raise ToolFault("NOT_FOUND", "research summary artifact is missing")
        if hashlib.sha256(path.read_bytes()).hexdigest() != record.artifacts["summary.json"]:
            raise ToolFault("ARTIFACT_CHANGED", "research summary checksum does not match registry")
        return {"experiment_id": experiment_id, "summary": json.loads(path.read_text(encoding="utf-8"))}

    def get_experiment(self, args: dict[str, Any]) -> dict[str, Any]:
        data = _keys(args, {"experiment_id"}, required={"experiment_id"})
        if self.registry is None:
            raise ToolFault("REGISTRY_UNAVAILABLE", "experiment registry is not configured")
        key = data["experiment_id"]
        if not isinstance(key, str) or not _ID.fullmatch(key):
            raise ToolFault("INVALID_INPUT", "invalid experiment_id")
        try:
            return self.registry.get_experiment(key)
        except KeyError as exc:
            raise ToolFault("NOT_FOUND", "experiment not found") from exc

    def compare_experiments(self, args: dict[str, Any]) -> dict[str, Any]:
        data = _keys(args, {"experiment_ids"}, required={"experiment_ids"})
        if self.registry is None:
            raise ToolFault("REGISTRY_UNAVAILABLE", "experiment registry is not configured")
        ids = data["experiment_ids"]
        if not isinstance(ids, list) or not 2 <= len(ids) <= 5 or any(
            not isinstance(key, str) or not _ID.fullmatch(key) for key in ids
        ):
            raise ToolFault("INVALID_INPUT", "experiment_ids must contain 2–5 safe IDs")
        return self.registry.compare_experiments(ids)

    def _load_strategy(self, strategy_id: str, version: str) -> Any:
        from hk_quant.strategy.storage import load_strategy

        # Safety does not depend on the storage module's own path checks.
        path = self.strategies_root / strategy_id / f"v{version}.yaml"
        if not path.is_file() or not path.resolve().is_relative_to(self.strategies_root):
            raise ToolFault("NOT_FOUND", "strategy version not found")
        return load_strategy(strategy_id, version, strategies_dir=self.strategies_root)

    def create_strategy(self, args: dict[str, Any]) -> dict[str, Any]:
        data = _keys(args, {"config"}, required={"config"})
        config = data["config"]
        if not isinstance(config, dict) or len(json.dumps(config, allow_nan=False)) > 16384:
            raise ToolFault("INVALID_INPUT", "strategy config must be an object of at most 16 KiB")
        _keys(config, set(config), required={"id", "version"})
        strategy_id, version = _strategy_key({"strategy_id": config["id"], "version": config["version"]})
        # A strategy's research linkage is metadata, never an untrusted path.
        research = config.get("research")
        if research and (not isinstance(research, dict) or research.get("research_result_path")):
            raise ToolFault("INVALID_INPUT", "research_result_path cannot be supplied through the agent")
        from hk_quant.strategy.builder import build_strategy_from_dict

        strategy = build_strategy_from_dict(config, repository=self.repository, strategies_dir=self.strategies_root)
        # Append only safe identifiers/hashes. Never log the raw strategy or keys.
        self.research_root.mkdir(parents=True, exist_ok=True)
        audit_path = self.research_root / "agent_audit.jsonl"
        if audit_path.is_symlink():
            raise ToolFault("INVALID_INPUT", "audit log cannot be a symlink")
        audit = {"at": datetime.now(timezone.utc).isoformat(), "action": "create_strategy", "strategy_id": strategy_id, "version": version, "hash": strategy.strategy_hash}
        with audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(audit, ensure_ascii=False) + "\n")
        return {"strategy_id": strategy_id, "version": version, "hash": strategy.strategy_hash, "status": strategy.status.value}

    def validate_strategy(self, args: dict[str, Any]) -> dict[str, Any]:
        data = _keys(args, {"strategy_id", "version"}, required={"strategy_id", "version"})
        strategy_id, version = _strategy_key(data)
        from hk_quant.strategy.validators import validate_strategy

        strategy = validate_strategy(self._load_strategy(strategy_id, version), repository=self.repository)
        return {"strategy_id": strategy_id, "version": version, "hash": strategy.strategy_hash, "status": strategy.status.value, "warnings": ["validation checks schema and available fields, not future profitability"]}

    def generate_signals(self, args: dict[str, Any]) -> dict[str, Any]:
        data = _keys(args, {"strategy_id", "version", "date", "stock_ids"}, required={"strategy_id", "version", "date", "stock_ids"})
        strategy_id, version = _strategy_key(data)
        signal_date = _iso(data["date"], "date")
        stock_ids = _stocks(data["stock_ids"])
        strategy = self._load_strategy(strategy_id, version)
        if strategy.price.adjusted and not _as_of_adjustment_verified(self.repository):
            raise ToolFault("DATA_UNAVAILABLE", "adjusted prices lack a verified as-of boundary for historical signals")
        from hk_quant.signal.engine import generate_signals

        signals = generate_signals(strategy, signal_date, universe=stock_ids, repository=self.repository, data_version=self.repository.get_data_version())
        return {"signals": [signal.to_dict() for signal in signals], "warnings": ["signals are evaluations, not orders"]}

    def run_backtest(self, args: dict[str, Any]) -> dict[str, Any]:
        data = _keys(args, {"strategy_id", "version", "start_date", "end_date", "stock_ids", "config"}, required={"strategy_id", "version", "start_date", "end_date", "stock_ids"})
        strategy_id, version = _strategy_key(data)
        start, end = _iso(data["start_date"], "start_date"), _iso(data["end_date"], "end_date")
        if start > end or (date.fromisoformat(end) - date.fromisoformat(start)).days > 1096:
            raise ToolFault("BUDGET_EXCEEDED", "backtest dates must be ordered and span at most three years")
        stocks = _stocks(data["stock_ids"])
        raw_config = _keys(data.get("config", {}), {"initial_capital", "commission_rate", "slippage_rate", "risk_free_rate", "annual_trading_days"})
        if self.registry is None:
            raise ToolFault("REGISTRY_UNAVAILABLE", "experiment registry is required to persist backtest results")
        strategy = self._load_strategy(strategy_id, version)
        if strategy.price.adjusted and not _as_of_adjustment_verified(self.repository):
            raise ToolFault("DATA_UNAVAILABLE", "historical backtest with adjusted prices requires verified as-of adjustments")
        from hk_quant.backtest import BacktestConfig, run_backtest

        config = BacktestConfig(**raw_config)
        result = run_backtest(strategy, start, end, self.repository, config, universe=stocks)
        record = self.registry.register_backtest_result(result)
        return {"experiment_id": record.experiment_id, "config_hash": record.config_hash, "metrics": result.metrics, "warnings": record.warnings, "metadata": result.metadata}

    def run_validation(self, args: dict[str, Any]) -> dict[str, Any]:
        data = _keys(args, {"strategy_id", "version", "start_date", "end_date", "stock_ids", "config"}, required={"strategy_id", "version", "start_date", "end_date", "stock_ids"})
        strategy_id, version = _strategy_key(data)
        start, end = _iso(data["start_date"], "start_date"), _iso(data["end_date"], "end_date")
        if start > end or (date.fromisoformat(end) - date.fromisoformat(start)).days > 1096:
            raise ToolFault("BUDGET_EXCEEDED", "validation dates must be ordered and span at most three years")
        stocks = _stocks(data["stock_ids"])
        allowed = {"train_fraction", "validation_fraction", "label_horizon_days", "embargo_days", "walk_min_train_days", "walk_evaluation_days", "walk_step_days", "cost_multiplier"}
        config_data = _keys(data.get("config", {}), allowed)
        if self.registry is None:
            raise ToolFault("REGISTRY_UNAVAILABLE", "experiment registry is required for validation")
        strategy = self._load_strategy(strategy_id, version)
        if strategy.price.adjusted and not _as_of_adjustment_verified(self.repository):
            raise ToolFault("DATA_UNAVAILABLE", "validation with adjusted prices requires verified as-of adjustments")
        from hk_quant.validation import ValidationConfig, run_validation

        config = ValidationConfig(**config_data, reveal_final_test=False)
        result = run_validation(strategy, start, end, self.repository, config=config, universe=stocks, registry=self.registry)
        return result.to_dict()

    def run_risk_analysis(self, args: dict[str, Any]) -> dict[str, Any]:
        data = _keys(args, {"stock_ids", "as_of_date", "window"}, required={"stock_ids", "as_of_date"})
        stocks = _stocks(data["stock_ids"], maximum=10)
        as_of = _iso(data["as_of_date"], "as_of_date")
        window = data.get("window", 252)
        if isinstance(window, bool) or not isinstance(window, int) or not 20 <= window <= 756:
            raise ToolFault("INVALID_INPUT", "window must be 20–756 trading days")
        if self.registry is None:
            raise ToolFault("REGISTRY_UNAVAILABLE", "experiment registry is required for risk analysis")
        from hk_quant.risk import analyze_risk, register_risk_result

        start = (date.fromisoformat(as_of) - timedelta(days=window * 3)).isoformat()
        prices = self.repository.get_daily_prices(stock_ids=stocks, start_date=start, end_date=as_of)
        if prices.empty:
            raise ToolFault("DATA_UNAVAILABLE", "no prices available for requested stocks/date")
        result = analyze_risk(prices, as_of_date=as_of, window=window, data_version=self.repository.get_data_version())
        record = register_risk_result(result, self.registry)
        return {"experiment_id": record.experiment_id, "summary": result.summary(), "warnings": record.warnings}
