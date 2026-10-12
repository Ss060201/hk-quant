"""Bounded research tools and a deterministic natural-language research planner.

This package never submits an order or computes quantitative statistics itself.
"""

from hk_quant.agent.planner import plan_research
from hk_quant.agent.tools import ResearchTools

__all__ = ["ResearchTools", "plan_research"]
