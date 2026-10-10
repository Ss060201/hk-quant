"""Logging setup for ``hk_quant``.

Provides a single entry point, :func:`get_logger`, which configures one
console handler once and returns namespaced loggers such as ``hk_quant``,
``hk_quant.data`` or ``hk_quant.research``.
"""

from __future__ import annotations

import logging
import sys

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_configured = False


def setup_logging(level: int = logging.INFO) -> None:
    """Configure the ``hk_quant`` root logger once.

    Args:
        level: Logging level for the ``hk_quant`` namespace.
    """
    global _configured
    if _configured:
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))

    logger = logging.getLogger("hk_quant")
    logger.setLevel(level)
    logger.addHandler(handler)
    logger.propagate = False

    _configured = True


def get_logger(name: str = "hk_quant") -> logging.Logger:
    """Return a logger under the ``hk_quant`` namespace.

    Args:
        name: Logger name. If it does not start with ``hk_quant``, the
            prefix is added automatically.

    Returns:
        A configured :class:`logging.Logger`.
    """
    setup_logging()
    if not name.startswith("hk_quant"):
        name = f"hk_quant.{name}"
    return logging.getLogger(name)
