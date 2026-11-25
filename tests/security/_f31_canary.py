"""Shared harness for the F31 engine canary corpus (AE6).

`observe(call)` runs one failure shape and returns every surface the engine can write text to:
the exception (str, repr, args, formatted traceback with its cause and context chain), every
log record on the `decoy_engine` logger through a stock formatter on a stream handler and on a
DEBUG file handler, every `warnings.warn`, and the progress events. A cell asserts that its
failure path ran (type and reason code) before it asserts the marker is absent, so a cell whose
path never triggered cannot pass for free.

Helper errors here carry no data or config values: only surface names and the cell id.
"""

from __future__ import annotations

import importlib
import io
import logging
import traceback
import warnings
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CANARY = "DECOY_CANARY_F31_7Q4Z"

_LOGGER_NAME = "decoy_engine"
_STOCK_FORMAT = "%(levelname)s %(name)s %(message)s"


@dataclass
class Observed:
    """What one failure shape wrote, by surface."""

    exc: BaseException | None = None
    result: Any = None
    surfaces: dict[str, str] = field(default_factory=dict)

    @property
    def code(self) -> str | None:
        return getattr(self.exc, "code", None)

    def surfaces_with_canary(self) -> list[str]:
        return sorted(name for name, text in self.surfaces.items() if CANARY in text)


def exception_surfaces(exc: BaseException) -> dict[str, str]:
    """Every text form of one exception, including the cause and context chain."""
    chain: list[BaseException] = []
    seen: set[int] = set()
    cursor: BaseException | None = exc
    while cursor is not None and id(cursor) not in seen:
        seen.add(id(cursor))
        chain.append(cursor)
        cursor = cursor.__cause__ or cursor.__context__
    return {
        "exc.str": str(exc),
        "exc.repr": repr(exc),
        "exc.args": repr(exc.args),
        "exc.traceback": "".join(traceback.format_exception(exc)),
        "exc.chain": "\n".join(f"{type(e).__name__}: {e!s}" for e in chain),
    }


def render_failure_surface(exc: BaseException) -> str | None:
    """`render_failure(exc)` once the safe-output slice has landed, else None."""
    try:
        module = importlib.import_module("decoy_engine.safe_output")
    except ImportError:
        return None
    render = getattr(module, "render_failure", None)
    if render is None:
        return None
    return str(render(exc))


def observe(
    call: Callable[..., Any], tmp_path: Path, *, with_progress: bool = False, **kwargs: Any
) -> Observed:
    """Run `call` under log, warning and progress capture and return every surface."""
    stream = io.StringIO()
    stream_handler = logging.StreamHandler(stream)
    file_path = tmp_path / "f31-canary-debug.log"
    file_handler = logging.FileHandler(file_path, encoding="utf-8")
    for handler in (stream_handler, file_handler):
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(logging.Formatter(_STOCK_FORMAT))
    logger = logging.getLogger(_LOGGER_NAME)
    saved_level = logger.level
    logger.setLevel(logging.DEBUG)
    logger.addHandler(stream_handler)
    logger.addHandler(file_handler)

    events: list[Any] = []
    if with_progress:
        from decoy_engine.progress import CallbackSink

        kwargs["progress"] = CallbackSink(events.append)

    out = Observed()
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            try:
                out.result = call(**kwargs)
            except BaseException as exc:
                out.exc = exc
    finally:
        logger.removeHandler(stream_handler)
        logger.removeHandler(file_handler)
        logger.setLevel(saved_level)
        stream_handler.flush()
        file_handler.close()

    if out.exc is not None:
        out.surfaces.update(exception_surfaces(out.exc))
        rendered = render_failure_surface(out.exc)
        if rendered is not None:
            out.surfaces["render_failure"] = rendered
    out.surfaces["log.stream"] = stream.getvalue()
    out.surfaces["log.file"] = file_path.read_text(encoding="utf-8")
    out.surfaces["warnings"] = "\n".join(f"{w.category.__name__}: {w.message}" for w in caught)
    out.surfaces["progress"] = "\n".join(repr(e) for e in events)
    if out.exc is None and out.result is not None:
        out.surfaces["result.quality"] = _quality_text(out.result)
    return out


def _quality_text(result: Any) -> str:
    """Warnings, row errors and quality metrics of a run result, never the output tables."""
    parts: list[str] = []
    for name in ("quality_warnings", "warnings", "row_errors", "quality_metrics", "evidence"):
        value = getattr(result, name, None)
        if value:
            parts.append(f"{name}={value!r}")
    return "\n".join(parts)
