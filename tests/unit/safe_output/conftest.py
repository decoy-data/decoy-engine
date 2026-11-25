"""Fixtures for the `SafeRecordFilter` tests."""

from __future__ import annotations

import logging

import pytest


@pytest.fixture
def isolated_logger():  # type: ignore[no-untyped-def]
    """Builds a logger that prints only through `handler` and restores it afterwards."""
    saved: list[tuple[logging.Logger, list[logging.Handler], bool, int]] = []

    def make(name: str, handler: logging.Handler, level: int = logging.NOTSET) -> logging.Logger:
        logger = logging.getLogger(name)
        saved.append((logger, list(logger.handlers), logger.propagate, logger.level))
        logger.handlers = [handler]
        logger.propagate = False
        logger.setLevel(level)
        return logger

    yield make
    for logger, handlers, propagate, level in saved:
        logger.handlers = handlers
        logger.propagate = propagate
        logger.setLevel(level)
