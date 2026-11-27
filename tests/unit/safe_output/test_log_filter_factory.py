"""A host record factory must not widen the set of fields the filter leaves alone (F31 AE3)."""

from __future__ import annotations

import importlib.util
import io
import json
import logging
import sys
import types
from collections.abc import Iterator
from contextlib import contextmanager

import pytest

from decoy_engine.safe_output import _log_filter
from tests.unit.safe_output.log_filter_support import _CANARY, _JsonFormatter


def _fresh_filter_module() -> types.ModuleType:
    """Runs the filter module's import-time code again, without touching `sys.modules`."""
    spec = importlib.util.spec_from_file_location("_f31_ae3_fresh_log_filter", _log_filter.__file__)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@contextmanager
def _factory_adding_error() -> Iterator[None]:
    """A host record factory that adds an `error` field holding a live exception."""
    previous = logging.getLogRecordFactory()

    def factory(*args: object, **kwargs: object) -> logging.LogRecord:
        record = previous(*args, **kwargs)
        record.error = ValueError(_CANARY)
        return record

    logging.setLogRecordFactory(factory)
    try:
        yield
    finally:
        logging.setLogRecordFactory(previous)


def _failure_json(module: types.ModuleType) -> str:
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(_JsonFormatter())
    handler.addFilter(module.SafeRecordFilter())
    try:
        raise ValueError(_CANARY)
    except ValueError:
        exc_info = sys.exc_info()
    record = logging.getLogger("f31_ae3_t_factory").makeRecord(
        "f31_ae3_t_factory", logging.ERROR, __file__, 1, "step failed", (), exc_info
    )
    handler.handle(record)
    return buf.getvalue()


def _break_scrub(module: types.ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(value: object, depth: int) -> object:
        raise RuntimeError(_CANARY)

    monkeypatch.setattr(module, "_safe_value", broken)


@pytest.mark.parametrize("path", ["normal", "fallback"])
@pytest.mark.parametrize("order", ["factory_before_import", "factory_after_import"])
def test_host_factory_field_is_scrubbed(
    order: str, path: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    if order == "factory_before_import":
        with _factory_adding_error():
            module = _fresh_filter_module()
            if path == "fallback":
                _break_scrub(module, monkeypatch)
            out = _failure_json(module)
    else:
        module = _fresh_filter_module()
        if path == "fallback":
            _break_scrub(module, monkeypatch)
        with _factory_adding_error():
            out = _failure_json(module)
    assert "error" in json.loads(out)  # positive control: the factory field reached the record
    assert _CANARY not in out


def test_standard_field_set_ignores_the_active_factory() -> None:
    with _factory_adding_error():
        module = _fresh_filter_module()
    assert "error" not in module._STANDARD_FIELDS
    assert module._STANDARD_FIELDS == _log_filter._STANDARD_FIELDS
