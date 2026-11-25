"""The one place a config loader turns file content into Python values.

`read_config` runs a loader's read AND its materialization (`.as_py()`, `to_pylist`, `json.loads`,
`yaml.safe_load`) as one protected operation. A failure inside it is classified without
reading its text: the loader gets a value-free refusal, never PyYAML's snippet, a JSON decoder
message, a library exception string or a time-zone name from a Parquet column.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, TypeVar

import yaml

from decoy_engine import fileaccess
from decoy_engine._config_text._refusal import ConfigPosition, Problem, Refusal, config_refusal
from decoy_engine._error_base import raise_bare

T = TypeVar("T")


def _yaml_mark(marked: Any) -> tuple[int | None, int | None]:
    """Line and column of a `MarkedYAMLError`; only the integer fields of its mark are read."""
    return _mark_ints(marked.problem_mark or marked.context_mark)


def _mark_ints(mark: yaml.Mark | None) -> tuple[int | None, int | None]:
    if mark is not None and type(mark.line) is int and type(mark.column) is int:
        return mark.line + 1, mark.column + 1
    return None, None


def _mark(exc: BaseException) -> tuple[int | None, int | None]:
    """The integer line and column of a parse failure, 1-indexed, or (None, None).

    Only ints are read: the YAML mark (the `yaml_error_text` rule) or `json.JSONDecodeError`'s
    `lineno` and `colno`. An error with no position, such as the `ValueError` a `!!int`
    constructor raises, gives none."""
    if isinstance(exc, yaml.MarkedYAMLError):
        return _yaml_mark(exc)
    if isinstance(exc, json.JSONDecodeError):
        return exc.lineno, exc.colno
    return None, None


def read_config(
    read: Callable[[], T],
    position: ConfigPosition,
    refuse: Callable[[Refusal], BaseException],
    *,
    passes: tuple[type[BaseException], ...] = (),
) -> T:
    """Run `read`, turning any failure into `refuse(refusal)`.

    - `passes` are the route's own typed errors and propagate unchanged under either policy.
    - Under a strict file-access policy a recognised memory or disk-resource failure keeps its
      class and gets the file-access replacement (fixed text, no filename), and the policy's own
      typed errors propagate. Under the ambient policy a builtin `MemoryError` passes, and a disk
      error becomes a refusal.
    - Every other failure becomes a refusal that holds the position, a closed problem and, for a
      parse failure, only the integer line and column. The refusal is raised after the handler
      closes, with no cause or context.
    """
    refusal: Refusal | None = None
    fresh: BaseException | None = None
    try:
        return read()
    except passes:
        raise
    except Exception as exc:
        if fileaccess.is_ambient():
            if isinstance(exc, MemoryError):
                raise
        else:
            classified = fileaccess.classified_failure(exc)
            if classified is not None:
                fresh = classified.fresh
                if fresh is None and classified.kind != "resource":
                    fresh = MemoryError(fileaccess.MEMORY_TEXT)
            elif fileaccess.keeps_class(exc):
                raise
        if fresh is None:
            line, column = _mark(exc)
            problem = Problem.UNREADABLE if isinstance(exc, OSError) else Problem.UNPARSEABLE
            refusal = config_refusal(position, problem, line=line, column=column)
    if fresh is not None:
        raise_bare(fresh)
    assert refusal is not None  # noqa: S101 - the handler set one of the two
    raise_bare(refuse(refusal))
