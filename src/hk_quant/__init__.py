"""HK Quant Research Platform.

An AI-native Hong Kong stock quantitative research platform.
Phase 1: project foundation (package structure, configuration, logging,
CLI entry point and tests). No research functionality is implemented yet.
"""

from hk_quant.logging_config import get_logger

__version__ = "0.1.0"

__all__ = ["__version__", "get_logger"]
