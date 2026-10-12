"""Point-in-time descriptive risk analysis. Never generates trading instructions."""

from hk_quant.risk.engine import analyze_risk
from hk_quant.risk.integrations import analyze_backtest_risk, register_risk_result
from hk_quant.risk.models import RiskResult

__all__ = ["RiskResult", "analyze_risk", "analyze_backtest_risk", "register_risk_result"]
