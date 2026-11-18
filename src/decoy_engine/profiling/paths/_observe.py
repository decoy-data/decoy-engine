"""Observe the paths of the JSON columns of one scanned frame.

A column qualifies when at least half of its first `SCAN_MAX_CELLS` non-null values are a JSON
object or array: a `dict` or `list`, or a string that parses to one. Pass 1 parses each cell once
(never keeping the tree), decides which keys are names and tells whether the column qualifies.
Pass 2 parses each cell again and counts the paths, so memory holds one cell at a time. Only counts,
closed kind tokens, detector ids and key names that passed the key rule leave this module: no leaf
value, no key that failed a rule and no `sample_misses`.
"""

from __future__ import annotations

import re
from typing import Any, cast

import numpy as np
import pandas as pd

from decoy_engine._canonical import (
    SCAN_CELL_BYTES,
    SCAN_MAX_CELLS,
    StrictJsonError,
    strict_json_read,
)
from decoy_engine.detection.detectors import run_all_detectors
from decoy_engine.profiling._scan_core import NestedCore, PathKind, PathObservationCore
from decoy_engine.profiling.paths import _walk

# A string that can be a JSON object or array. Anything else is a scalar and is not parsed.
_OPENS = re.compile(r"\s*[\[{]")

_MALFORMED = "malformed"
_OVERSIZED = "oversized"
_SCALAR = "scalar"


def _read(cell: Any) -> tuple[Any, str | None]:
    """The tree of one cell and no fault, or no tree and the fault: malformed, oversized, scalar."""
    if isinstance(cell, (dict, list, tuple)) or (isinstance(cell, np.ndarray) and cell.ndim == 1):
        return cell, None
    if not isinstance(cell, str) or not _OPENS.match(cell):
        return None, _SCALAR
    fault: str | None = None
    try:
        return (
            strict_json_read(
                cell,
                max_bytes=SCAN_CELL_BYTES,
                max_depth=None,
                non_finite="keep",
                keep_lexemes=False,
                max_int_digits=None,
            ),
            None,
        )
    except StrictJsonError as exc:
        refused = exc.token
        fault = _OVERSIZED if refused == "oversized" else _MALFORMED
    return None, fault


def _noop(pattern: _walk.Pattern, value: Any) -> bool:
    return True


def _cells(series: pd.Series) -> list[Any]:
    """The first `SCAN_MAX_CELLS` non-null values, also when the scan read every row."""
    return series.dropna().head(SCAN_MAX_CELLS).tolist()


def observe_column(series: pd.Series) -> NestedCore | None:
    """The path observation of one column, or `None` when fewer than half of its cells are JSON
    objects or arrays."""
    cells = _cells(series)
    total = len(cells)
    if total == 0:
        return None
    levels = _walk.Levels()
    faults = {_MALFORMED: 0, _OVERSIZED: 0, _SCALAR: 0}
    parsed = 0
    for index, cell in enumerate(cells):
        tree, fault = _read(cell)
        if fault is not None:
            faults[fault] += 1
            if sum(faults.values()) * 2 > total:  # the column cannot qualify any more
                return None
            continue
        parsed += 1
        levels.cell = index
        _walk.walk(tree, levels.scout, _noop)
    if parsed == 0:
        return None
    levels.finalize()
    return _pass_two(cells, levels, faults, parsed)


def _pass_two(
    cells: list[Any], levels: _walk.Levels, faults: dict[str, int], parsed: int
) -> NestedCore:
    tally = _walk.Tally()
    too_deep = 0
    long_arrays = 0
    for index, cell in enumerate(cells):
        tree, fault = _read(cell)
        if fault is not None:
            continue
        tally.cell = index
        levels.cell = index
        deep, arrays = _walk.walk(tree, levels.settle, tally.record)
        too_deep += deep
        long_arrays += arrays
    rows = sorted((_walk.path_text(p), p, row) for p, row in tally.rows.items())
    return NestedCore(
        cells_sampled=len(cells),
        cells_parsed=parsed,
        cells_malformed=faults[_MALFORMED],
        cells_oversized=faults[_OVERSIZED],
        cells_scalar=faults[_SCALAR],
        depth_truncated_cells=too_deep,
        arrays_truncated=long_arrays,
        key_suspect_collapsed=levels.suspect,
        map_collapsed=levels.map_collapsed,
        paths_truncated=levels.truncated or tally.truncated,
        paths=[
            PathObservationCore(
                path=text,
                present_count=row.present,
                null_count=row.null,
                kinds=cast(list[PathKind], sorted(row.kinds)),
                detector_hits=_detector_hits(pattern, row.leaves),
            )
            for text, pattern, row in rows
        ],
    )


def _detector_hits(pattern: _walk.Pattern, leaves: list[str]) -> list[str]:
    """Detector ids over the first leaves of a path. Only the id crosses: the match rate and the
    `sample_misses` values stay here."""
    if not leaves:
        return []
    matches = run_all_detectors(pd.Series(leaves, dtype=object), _walk.name_hint(pattern))
    return sorted({m.detector_id for m in matches})


def observe_frame(frame: pd.DataFrame) -> dict[str, NestedCore]:
    """The observation of every JSON column of `frame`, by column name. A column that is not
    JSON has no entry."""
    found: dict[str, NestedCore] = {}
    for name in frame.columns:
        series = frame[name]
        if not (
            pd.api.types.is_object_dtype(series.dtype) or pd.api.types.is_string_dtype(series.dtype)
        ):
            continue
        observed = observe_column(series)
        if observed is not None:
            found[str(name)] = observed
    return found
