"""Full-lifecycle memory estimate: the ingest, execute and write phase peaks (F24, row 84).

Pure arithmetic over frozen inputs, no I/O and no module state, so unit cells run without
files. `_lifecycle_inputs.py` reads the bounded samples that fill `PhaseInputs`.

The estimate is the largest of three phase peaks. Each phase peak is the sum of what is live at
once for a caller that reads every file source whole through the engine's readers and holds
inputs and outputs until the last target is written. The live-set sums follow the liveness
rule of buffer-assignment heap simulators (XLA): the peak is the largest sum of live buffers
over the program points. Arrow sizes follow the columnar format (`arrow_column_bytes`); pandas
frames use the engine's existing per-cell model (`raw_data_bytes`); the execute term is the
measured TB-4 model (`estimate_peak_bytes`), unchanged.

Notes are value-free: table and column names, byte counts and exception type names only.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Literal

import pyarrow as pa

from decoy_engine._arrow_types import arrow_column_bytes
from decoy_engine.execution._mem_estimate import (
    ColumnSizeSpec,
    ExecutionPath,
    TableSizeSpec,
    estimate_peak_bytes,
    raw_data_bytes,
    route_intercept_bytes,
)

Phase = Literal["ingest", "execute", "write"]
PHASES: tuple[Phase, ...] = ("ingest", "execute", "write")

# Read once from the running interpreter, never pinned.
_INT_OBJECT = sys.getsizeof(1 << 20)
_FLOAT_OBJECT = sys.getsizeof(1.5)
_SLOT = 8
# An `Int64` value plus its mask byte (`_FIXED_WIDTH_DTYPE_BYTES["Int64"]`).
_INT64_CELL = 9

# --- Notes: the only texts the lifecycle adds -------------------------------------------

NOTE_ROWS_ESTIMATED = "row counts estimated from file size"
NOTE_SAMPLE_UNREADABLE = "lifecycle not priced: sample of table {table} not readable ({error})"
NOTE_SOURCE_NOT_LOCAL = "lifecycle not priced: source {table} is not a local file"
NOTE_SOURCE_FORMAT = "lifecycle not priced: source {table} has a format with no rule"
NOTE_TARGET_FORMAT = "lifecycle not priced: target {table} has a format with no rule"
NOTE_LAYOUT = "lifecycle not priced: layout of target {table} not readable"
NOTE_OUTPUT_WIDTH = (
    "lifecycle not priced: column {column} has an output width its strategy does not declare"
)
NOTE_GENERATE_WIDTH = "lifecycle not priced: generated column {column} has no width source"
NOTE_FAILED = "lifecycle not priced ({error})"

NOTE_SHAPES = frozenset(
    {
        NOTE_ROWS_ESTIMATED,
        NOTE_SAMPLE_UNREADABLE,
        NOTE_SOURCE_NOT_LOCAL,
        NOTE_SOURCE_FORMAT,
        NOTE_TARGET_FORMAT,
        NOTE_LAYOUT,
        NOTE_OUTPUT_WIDTH,
        NOTE_GENERATE_WIDTH,
        NOTE_FAILED,
    }
)


def _shape_pattern(shape: str) -> re.Pattern[str]:
    parts = re.split(r"\{(?:table|error|column)\}", shape)
    return re.compile(".+".join(re.escape(p) for p in parts))


_SHAPE_PATTERNS = tuple(_shape_pattern(s) for s in sorted(NOTE_SHAPES))


def note_matches_shape(note: str) -> bool:
    """Whether `note` is one of the constants above with its placeholders filled."""
    return any(p.fullmatch(note) for p in _SHAPE_PATTERNS)


# --- Inputs -----------------------------------------------------------------------------


@dataclass(frozen=True)
class ColumnInputs:
    """One column as the phases price it: Arrow type and null flag for the Arrow table, the
    size spec (pandas cell cost, string width) for frames and Python objects."""

    name: str
    arrow_type: pa.DataType
    has_nulls: bool
    spec: ColumnSizeSpec
    # What the column holds after its strategy ran; None means the input form (a strategy that
    # keeps the type, or a table built before output specs are attached).
    output_spec: ColumnSizeSpec | None = None
    output_arrow_type: pa.DataType | None = None


@dataclass(frozen=True)
class TargetInputs:
    """A table's target format and, for fixed_width, the columns its layout types `int`."""

    format: str
    int_columns: frozenset[str] = frozenset()


@dataclass(frozen=True)
class TableInputs:
    name: str
    rows: int
    columns: tuple[ColumnInputs, ...]
    source_format: str
    target: TargetInputs = field(default_factory=lambda: TargetInputs("parquet"))
    # Parquet only: the footer's largest row group `total_byte_size`.
    row_group_bytes: int = 0
    rows_exact: bool = True
    has_transforms: bool = False


@dataclass(frozen=True)
class GeneratedInputs:
    """The generate tables of a job. `tables` are the outputs as written (target attached);
    `resident_bytes` is what the run holds for them while it executes and `unique_peak_bytes`
    the largest unique-draw working set (both from `decoy_engine.generation`)."""

    tables: tuple[TableInputs, ...]
    resident_bytes: int
    unique_peak_bytes: int


@dataclass(frozen=True)
class PhaseInputs:
    """`path` is the priced route (one of the three models), `tables` are the mask tables in
    config order. `generated` is set for a generate-only or mixed job."""

    path: ExecutionPath
    tables: tuple[TableInputs, ...]
    generated: GeneratedInputs | None = None


@dataclass(frozen=True)
class Lifecycle:
    phase_bytes: tuple[tuple[Phase, int], ...]
    peak_bytes: int
    limiting_phase: Phase


# --- Per-table terms --------------------------------------------------------------------


def table_spec(t: TableInputs) -> TableSizeSpec:
    return TableSizeSpec(name=t.name, row_count=t.rows, columns=tuple(c.spec for c in t.columns))


def _cell_bytes(spec: ColumnSizeSpec) -> float:
    return _priced(TableSizeSpec("c", 1000, (spec,))) / 1000


def working_spec(c: ColumnInputs) -> ColumnSizeSpec:
    """The larger of a column's input and output cell: the route holds whichever is bigger."""
    out = c.output_spec
    if out is None or _cell_bytes(out) <= _cell_bytes(c.spec):
        return c.spec
    return out


def working_table_spec(t: TableInputs) -> TableSizeSpec:
    return TableSizeSpec(t.name, t.rows, tuple(working_spec(c) for c in t.columns))


def output_table(t: TableInputs) -> TableInputs:
    """The table as written: each column in its output form."""
    columns = tuple(
        replace(
            c,
            spec=c.output_spec if c.output_spec is not None else c.spec,
            arrow_type=c.output_arrow_type if c.output_arrow_type is not None else c.arrow_type,
            output_spec=None,
            output_arrow_type=None,
        )
        for c in t.columns
    )
    return replace(t, columns=columns)


def _is_string(spec: ColumnSizeSpec) -> bool:
    return spec.string_width_bytes is not None


def _is_integer(spec: ColumnSizeSpec) -> bool:
    return spec.dtype.lower().startswith(("int", "uint"))


def _priced(spec: TableSizeSpec) -> int:
    result = raw_data_bytes((spec,))
    if not result.is_priceable:
        raise ValueError("lifecycle needs every column priced")
    return result.priceable_bytes


def _column_frame(c: ColumnInputs, rows: int) -> int:
    return _priced(TableSizeSpec("c", rows, (c.spec,)))


def arrow_bytes(t: TableInputs) -> int:
    """The table as Arrow: data buffers plus a validity bitmap for a column with nulls."""
    total = 0
    for c in t.columns:
        total += arrow_column_bytes(c.arrow_type, t.rows, c.spec.string_width_bytes or 0.0)
        if c.has_nulls:
            total += (t.rows + 7) // 8
    return total


def frame_bytes(t: TableInputs) -> int:
    """The table as a pandas object frame (`raw_data_bytes`)."""
    return _priced(table_spec(t))


def _refs_cell(spec: ColumnSizeSpec) -> int:
    """A pandas cell that points at a Python object that already exists: a pointer for a string
    or an object-held value, the dtype item size for a numeric column."""
    if _is_string(spec) or spec.dtype.startswith("pyobject["):
        return _SLOT
    return _priced(TableSizeSpec("c", 1, (spec,)))


def _number_object(spec: ColumnSizeSpec) -> int:
    return _INT_OBJECT if _is_integer(spec) else _FLOAT_OBJECT


def refs_bytes(t: TableInputs) -> int:
    return sum(t.rows * _refs_cell(c.spec) for c in t.columns)


def int_columns(t: TableInputs) -> tuple[ColumnInputs, ...]:
    """Columns the fixed_width layout types `int` that the writer's coercion step converts:
    an integer-typed column is left as it is and is covered by `refs`."""
    if t.target.format != "fixed_width":
        return ()
    return tuple(c for c in t.columns if c.name in t.target.int_columns and not _is_integer(c.spec))


def lists_bytes(t: TableInputs) -> int:
    """The `.tolist()` lists: a slot per cell, plus a new number object per numeric cell.
    A string cell reuses the frame's str object."""
    coerced = {c.name for c in int_columns(t)}
    total = 0
    for c in t.columns:
        total += t.rows * _SLOT
        if c.name in coerced:
            total += t.rows * _INT_OBJECT
        elif not _is_string(c.spec):
            total += t.rows * _number_object(c.spec)
    return total


def records_bytes(t: TableInputs) -> int:
    """The fixed_width reader's list of row dicts: one dict and one list slot per row, plus the
    Python object of every cell."""
    per_row_dict = sys.getsizeof(dict.fromkeys(range(len(t.columns)))) + _SLOT
    total = t.rows * per_row_dict
    for c in t.columns:
        if _is_string(c.spec):
            total += _column_frame(c, t.rows)
        else:
            total += t.rows * _number_object(c.spec)
    return total


def converted_bytes(t: TableInputs) -> int:
    """Each coerced column stays in the copy as `Int64` (9 bytes a row) while later columns
    are coerced, and `refs` still prices it at its original cell cost."""
    return sum(t.rows * max(0, _INT64_CELL - _refs_cell(c.spec)) for c in int_columns(t))


def _coerce_bytes(t: TableInputs) -> int:
    """One column's coercion: a list slot, one int object and the `Int64` value plus mask."""
    return t.rows * (_SLOT + _INT_OBJECT + _INT64_CELL)


def coerce_moment(t: TableInputs) -> int:
    """Inside `_coerce_int_columns`: the original frame, the copy's pointers, the columns
    already converted and the one column being coerced (one at a time, so one term)."""
    one_column = _coerce_bytes(t) if int_columns(t) else 0
    return frame_bytes(t) + refs_bytes(t) + converted_bytes(t) + one_column


def list_moment(t: TableInputs) -> int:
    """Inside the writer's `.tolist()`: the copy (a full frame) and the lists."""
    return frame_bytes(t) + lists_bytes(t)


# --- Format rules (keys equal `FILE_FORMATS`; a guard test pins it) ----------------------


def _csv_ingest(t: TableInputs) -> int:
    return frame_bytes(t) + arrow_bytes(t)


def _parquet_ingest(t: TableInputs) -> int:
    return arrow_bytes(t) + t.row_group_bytes


def _fixed_width_ingest(t: TableInputs) -> int:
    # The row dicts and the new frame are live together inside `DataFrame.from_records`; the
    # dicts are freed before `from_pandas` builds the Arrow table.
    return max(records_bytes(t) + refs_bytes(t), frame_bytes(t) + arrow_bytes(t))


def _no_write_transient(t: TableInputs) -> int:
    return 0


def _fixed_width_write(t: TableInputs) -> int:
    return max(coerce_moment(t), list_moment(t))


INGEST_TRANSIENT: dict[str, Callable[[TableInputs], int]] = {
    "csv": _csv_ingest,
    "parquet": _parquet_ingest,
    "fixed_width": _fixed_width_ingest,
}

WRITE_TRANSIENT: dict[str, Callable[[TableInputs], int]] = {
    "csv": frame_bytes,
    "parquet": _no_write_transient,
    "fixed_width": _fixed_width_write,
}


# --- Phases -----------------------------------------------------------------------------


def _ingest(inputs: PhaseInputs, intercept: int) -> int:
    held = 0
    peak = 0
    for t in inputs.tables:
        peak = max(peak, intercept + held + INGEST_TRANSIENT[t.source_format](t))
        held += arrow_bytes(t)
    return peak


def _execute(inputs: PhaseInputs, intercept: int) -> int:
    generated = inputs.generated
    held = 0 if generated is None else generated.resident_bytes
    if not inputs.tables:
        return intercept + held + (0 if generated is None else generated.unique_peak_bytes)
    base = estimate_peak_bytes(tuple(working_table_spec(t) for t in inputs.tables), inputs.path)
    if base.estimated_bytes is None:
        raise ValueError("lifecycle needs every column priced")
    arrows = [arrow_bytes(t) for t in inputs.tables]
    extra = 0
    if inputs.path == "sequential":
        extra = sum(arrows) - max(arrows)
    elif inputs.path == "out_of_core":
        extra = sum(arrows)
    # A declared transform builds a new table beside the resident one.
    extra += sum(a for a, t in zip(arrows, inputs.tables, strict=True) if t.has_transforms)
    return base.estimated_bytes + extra + held


def _write(inputs: PhaseInputs, intercept: int) -> int:
    outputs = [output_table(t) for t in inputs.tables]
    if inputs.generated is not None:
        outputs += inputs.generated.tables
    resident = sum(arrow_bytes(t) for t in inputs.tables) + sum(arrow_bytes(o) for o in outputs)
    transient = max(WRITE_TRANSIENT[o.target.format](o) for o in outputs)
    return intercept + resident + transient


def limiting_phase(phase_bytes: tuple[tuple[Phase, int], ...]) -> Phase:
    """The phase with the largest bytes; a tie goes to the earlier phase."""
    best = phase_bytes[0]
    for item in phase_bytes[1:]:
        if item[1] > best[1]:
            best = item
    return best[0]


def lifecycle_peak(inputs: PhaseInputs) -> Lifecycle:
    """The three phase peaks, the largest of them and the phase that sets it."""
    if not inputs.tables and inputs.generated is None:
        raise ValueError("lifecycle needs at least one table")
    intercept = route_intercept_bytes("full_frame")
    phases: tuple[tuple[Phase, int], ...] = (
        ("ingest", _ingest(inputs, intercept)),
        ("execute", _execute(inputs, intercept)),
        ("write", _write(inputs, intercept)),
    )
    return Lifecycle(
        phase_bytes=phases,
        peak_bytes=max(b for _, b in phases),
        limiting_phase=limiting_phase(phases),
    )
