"""The one place a config loader turns file content into Python values.

`read_config` runs a loader's read AND its materialization (`.as_py()`, `to_pylist`, `json.loads`,
`yaml.safe_load`) as one protected operation. A failure inside it is classified without
reading its text: the loader gets a value-free refusal, never PyYAML's snippet, a JSON decoder
message, a library exception string or a time-zone name from a Parquet column.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import TypeVar

import yaml

from decoy_engine import fileaccess
from decoy_engine._config_text._refusal import ConfigPosition, Problem, Refusal, config_refusal
from decoy_engine._error_base import raise_bare

T = TypeVar("T")


def _mark_ints(mark: object) -> tuple[int | None, int | None]:
    line, column = getattr(mark, "line", None), getattr(mark, "column", None)
    if type(line) is int and type(column) is int:
        # PyYAML marks are 0-indexed; editors count from 1.
        return line + 1, column + 1
    return None, None


def _yaml_mark(exc: object) -> tuple[int | None, int | None]:
    """Line and column of a YAML error; only the integer fields of its mark are read."""
    return _mark_ints(getattr(exc, "problem_mark", None) or getattr(exc, "context_mark", None))


def yaml_error_text(exc: Exception) -> str:
    """A leak-safe one-line description of a YAML parse failure.

    PyYAML's message and snippet echo the offending source line, which can hold a password or
    PII. Only the integer line and column of the error mark are read. Accepts any exception so a
    broad ``except`` cannot pass a non-YAML error's text through.
    """
    line, column = _yaml_mark(exc)
    if line is not None and column is not None:
        return f"could not parse YAML: invalid syntax at line {line}, column {column}"
    return "could not parse YAML: the file is not valid YAML"


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


def passthrough(exc: Exception) -> BaseException | None:
    """How a failure that is not an ordinary read or parse error leaves a loader, or None.

    One rule for every route that reads a pinned or configured file, so no route rebuilds it:

    - Under the ambient policy a builtin `MemoryError` is returned as is (re-raise it).
    - Under a strict policy a recognised memory or disk-resource failure keeps its class and gets
      the file-access replacement (fixed text, no filename): the fresh error is returned, to be
      raised bare. The policy's own typed errors are returned as is.
    - Anything else gives None: the caller turns it into its own value-free outcome.

    A caller re-raises with `raise` when the result `is exc`, and with `raise_bare` otherwise.
    """
    if fileaccess.is_ambient():
        return exc if isinstance(exc, MemoryError) else None
    classified = fileaccess.classified_failure(exc)
    if classified is not None:
        if classified.fresh is not None:
            return classified.fresh
        return None if classified.kind == "resource" else MemoryError(fileaccess.MEMORY_TEXT)
    return exc if fileaccess.keeps_class(exc) else None


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
        outcome = passthrough(exc)
        if outcome is exc:
            raise
        fresh = outcome
        if fresh is None:
            line, column = _mark(exc)
            problem = Problem.UNREADABLE if isinstance(exc, OSError) else Problem.UNPARSEABLE
            refusal = config_refusal(position, problem, line=line, column=column)
    if fresh is not None:
        raise_bare(fresh)
    assert refusal is not None  # noqa: S101 - the handler set one of the two
    raise_bare(refuse(refusal))
