"""External PAPER account adapters and read-only monitoring."""

from hk_quant.paper.futu_adapter import FutuPaperBroker, PaperOrderError
from hk_quant.paper.monitor import PaperMonitor, StrategyLifecycle
from hk_quant.paper.policy import PaperProposal, propose_paper_order

__all__ = ["FutuPaperBroker", "PaperOrderError", "PaperMonitor", "StrategyLifecycle",
           "PaperProposal", "propose_paper_order"]
