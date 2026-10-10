"""Basic import smoke tests for the hk_quant package."""

from __future__ import annotations


def test_import_package() -> None:
    import hk_quant

    assert hk_quant.__version__ == "0.1.0"


def test_get_logger_available() -> None:
    from hk_quant import get_logger

    logger = get_logger("test_import")
    assert logger.name == "hk_quant.test_import"
