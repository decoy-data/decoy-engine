"""The F31 canary harness catches a planted marker on every surface it claims to cover.

A corpus cell is only as good as the harness behind it. Each case here plants `CANARY` in one
place a constructor or a log call can put a value, and expects the named surface to carry it. A
harness that stopped looking at instance attributes, `records` or the context chain would go red
here, not stay green in the corpus.
"""

from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from tests.security._f31_canary import CANARY, assert_no_canary, canary_surfaces, observe
from tests.security._surfaces import exception_chain, rendered, rendered_surfaces


@dataclass(frozen=True)
class _Record:
    reason: str


class _AttributeError(Exception):
    def __init__(self, text: str, payload: Any) -> None:
        super().__init__(text)
        self.payload = payload


class _RecordsError(Exception):
    def __init__(self, records: tuple[_Record, ...]) -> None:
        super().__init__("row errors")
        self.records = records


def _raised(factory: Any) -> BaseException:
    try:
        factory()
    except BaseException as exc:
        return exc
    raise AssertionError("the factory did not raise")


def _in_message() -> None:
    raise ValueError(f"bad {CANARY}")


def _in_attribute() -> None:
    raise _AttributeError("fixed", {"value": CANARY})


def _in_records() -> None:
    raise _RecordsError((_Record(reason=CANARY),))


def _in_cause() -> None:
    try:
        raise KeyError(CANARY)
    except KeyError as inner:
        raise ValueError("fixed") from inner


def _in_context() -> None:
    try:
        raise KeyError(CANARY)
    except KeyError:
        raise ValueError("fixed") from None


def _in_context_of_cause() -> None:
    try:
        try:
            raise KeyError(CANARY)
        except KeyError:
            raise RuntimeError("middle") from None
    except RuntimeError as middle:
        raise ValueError("fixed") from middle


def _in_cause_attribute() -> None:
    try:
        raise _AttributeError("fixed", CANARY)
    except _AttributeError as inner:
        raise ValueError("fixed") from inner


def _in_args() -> None:
    raise ValueError("fixed", CANARY.encode())


@pytest.mark.parametrize(
    ("factory", "surface"),
    [
        (_in_message, "exc.str"),
        (_in_attribute, "exc.attrs"),
        (_in_records, "exc.records"),
        (_in_records, "exc.attrs"),
        (_in_cause, "exc.chain"),
        (_in_context, "exc.chain"),
        (_in_context_of_cause, "exc.chain"),
        (_in_cause_attribute, "exc.attrs"),
        (_in_args, "exc.args"),
    ],
    ids=lambda v: getattr(v, "__name__", v),
)
def test_planted_marker_reaches_its_surface(factory: Any, surface: str) -> None:
    surfaces = rendered_surfaces(_raised(factory))
    assert surface in canary_surfaces(surfaces)
    with pytest.raises(AssertionError):
        assert_no_canary(surfaces)


def test_a_clean_exception_has_no_marker() -> None:
    assert_no_canary(rendered_surfaces(ValueError("fixed")))
    assert not any(CANARY in text for text in rendered(ValueError("fixed")))


def test_the_chain_follows_cause_and_context_and_stops_on_a_cycle() -> None:
    cause, context, top = KeyError("c"), KeyError("x"), ValueError("t")
    top.__cause__, top.__context__ = cause, context
    cause.__context__ = top
    assert exception_chain(top) == [top, cause, context]


def test_a_marker_in_a_log_record_a_warning_and_a_progress_event_is_seen(tmp_path: Path) -> None:
    def noisy(**_: Any) -> None:
        logging.getLogger("decoy_engine").debug("value %s", CANARY)
        warnings.warn(CANARY, stacklevel=1)

    seen = observe(noisy, tmp_path, with_progress=True)
    assert {"log.stream", "log.file", "warnings"} <= set(seen.surfaces_with_canary())


def test_a_marker_in_a_row_error_reason_is_seen_through_the_raised_error(tmp_path: Path) -> None:
    def failing() -> None:
        raise _RecordsError((_Record(reason=f"cannot parse {CANARY}"),))

    seen = observe(failing, tmp_path)
    assert "exc.records" in seen.surfaces_with_canary()
