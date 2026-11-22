"""The resident-fit decision for a job with no foreign keys: bytes a full-frame run holds.

`lower_bound_bytes` is the strict lower bound on those bytes; `resident_fit_verdict` turns facts
about one job into a `ResidentFit`; `store_resident_fit` is the single place that gathers the
facts, refuses, and stamps the verdict on the `RouteDecision`.

`lower_bound_bytes` is pure: it reads the facts a caller supplies (an in-memory table, or a row
count and a schema from a Parquet footer) and nothing else. It opens no file, reads no lazy source,
detects no host memory and runs no probe. Every width below is a floor, so the sum is a bound the
real peak cannot undercut; a width that turned out too high would make the bound wrong, so the
S1 baseline measures peak against it on every workload.

Method follows the Arrow columnar layout (fixed-width values, 4 or 8 offset bytes per
variable-width row) and the pandas block layout (numpy width per cell, one object pointer per
string-like cell).
"""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

import pyarrow as pa

from decoy_engine import fileaccess, reasons
from decoy_engine.profile._readers import BOUNDED_FALLBACK_ROWS, LazySource

if TYPE_CHECKING:
    from decoy_engine.execution._pipeline_context import PipelineRunContext, RouteDecision

_logger = logging.getLogger(__name__)

# The kill ceiling `H` is the host or cgroup limit. `A = H * fraction` is the admission ceiling:
# it can prove a fit, never a refusal (a job between `A` and `H` runs today and still runs).
RESIDENT_ADMISSION_FRACTION: Final = 0.85

FIT: Final = "FIT"
INSUFFICIENT: Final = "INSUFFICIENT"
UNKNOWN: Final = "UNKNOWN"

_OBJECT_POINTER_BYTES = 8
_DICTIONARY_CODE_BYTES = 1  # pandas narrows categorical codes; one byte is the floor


@dataclass(frozen=True)
class TableBytesSpec:
    """One table's size facts.

    `resident_input_bytes` is set for a table already in memory and is `None` for a lazy table,
    which is priced from rows and schema alone. `charge_pandas` is false for a table the run holds
    but never converts to pandas (a generated table in a mixed job).
    """

    rows: int
    schema: pa.Schema
    resident_input_bytes: int | None = None
    charge_pandas: bool = True


def resident_spec(table: pa.Table, *, charge_pandas: bool = True) -> TableBytesSpec:
    return TableBytesSpec(
        rows=table.num_rows,
        schema=table.schema,
        resident_input_bytes=resident_table_bytes(table),
        charge_pandas=charge_pandas,
    )


def lazy_spec(rows: int, schema: pa.Schema, *, charge_pandas: bool = True) -> TableBytesSpec:
    return TableBytesSpec(rows=rows, schema=schema, charge_pandas=charge_pandas)


def resident_table_bytes(table: pa.Table) -> int:
    """The bytes the table's distinct physical buffers hold.

    Arrow counts each buffer once however many arrays, columns, dictionaries or slices point at
    it (`Table.get_total_buffer_size`, present since pyarrow 14), and a sliced array counts its
    whole backing buffer, which the process does hold. So the figure never exceeds what the
    table occupies.
    """
    return int(table.get_total_buffer_size())


def input_bytes(specs: Iterable[TableBytesSpec]) -> int:
    return sum(
        s.resident_input_bytes
        if s.resident_input_bytes is not None
        else _lazy_input_bytes(s.rows, s.schema)
        for s in specs
    )


def pandas_bytes(specs: Iterable[TableBytesSpec]) -> int:
    return sum(
        s.rows * sum(_pandas_cell_bytes(f.type) for f in s.schema) for s in specs if s.charge_pandas
    )


def lower_bound_bytes(specs: Iterable[TableBytesSpec]) -> int:
    """`input_bytes + pandas_bytes` over `specs`. The one formula; callers do not re-derive it."""
    materialized = tuple(specs)
    return input_bytes(materialized) + pandas_bytes(materialized)


def _lazy_input_bytes(rows: int, schema: pa.Schema) -> int:
    return sum(_lazy_column_bytes(rows, f.type) for f in schema)


def _lazy_column_bytes(rows: int, arrow_type: pa.DataType) -> int:
    """Fixed-width part only, plus the offsets of variable-width types; no validity bitmap."""
    t = arrow_type
    if pa.types.is_null(t):
        return 0
    if pa.types.is_boolean(t):
        return -(-rows // 8)
    if pa.types.is_dictionary(t):
        return rows * t.index_type.bit_width // 8
    if pa.types.is_struct(t):
        return sum(_lazy_column_bytes(rows, t.field(i).type) for i in range(t.num_fields))
    if pa.types.is_fixed_size_list(t):
        return 0  # the child length is not in the schema; zero keeps the bound a floor
    if pa.types.is_large_string(t) or pa.types.is_large_binary(t) or pa.types.is_large_list(t):
        return rows * 8
    if pa.types.is_string(t) or pa.types.is_binary(t) or pa.types.is_list(t) or pa.types.is_map(t):
        return rows * 4
    if pa.types.is_fixed_size_binary(t):
        return rows * t.byte_width
    return rows * t.bit_width // 8 if _has_bit_width(t) else 0


def _has_bit_width(t: pa.DataType) -> bool:
    try:
        return t.bit_width > 0
    except ValueError:
        return False


def _pandas_cell_bytes(arrow_type: pa.DataType) -> int:
    t = arrow_type
    if pa.types.is_dictionary(t):
        return _DICTIONARY_CODE_BYTES
    if pa.types.is_boolean(t):
        return 1
    if (
        pa.types.is_integer(t)
        or pa.types.is_floating(t)
        or pa.types.is_timestamp(t)
        or pa.types.is_duration(t)
    ):
        # An int with nulls widens to float64 (8); the int's own width is the floor.
        return t.bit_width // 8
    return _OBJECT_POINTER_BYTES


@dataclass(frozen=True)
class ResidentFit:
    """The verdict on one job, stored on `RouteDecision.resident_fit`.

    `verdict` is `FIT`, `INSUFFICIENT` or `UNKNOWN` (the `CapacityVerdict` vocabulary, in capitals);
    `code` is the registered route or runtime code that says why. `estimated_bytes` is the figure
    the verdict rested on: the probe's measured peak, the static estimate, or the lower bound on a
    lower-bound refusal; 0 when nothing was priced. Numbers and tokens only, so it can go into
    `quality_metrics` and an error message as is.
    """

    verdict: str
    code: str
    table_count: int
    estimated_bytes: int
    lower_bound_bytes: int
    admission_ceiling_bytes: int
    kill_ceiling_bytes: int


@dataclass(frozen=True)
class ProbeFacts:
    """What a two-point probe measured: `None` when it could not give a number."""

    estimated_bytes: int | None
    uniqueness_risk: bool = False


@dataclass(frozen=True)
class ResidentFitFacts:
    """Every number `resident_fit_verdict` reads. Gatherers build this; they never compare.

    `complete` is false when a table in the resident set could not be priced (a loader table has
    a schema and no row count), so `lower_bound_bytes` is a floor over the priced tables only:
    enough to refuse, never enough to prove a fit.
    """

    table_count: int
    lower_bound_bytes: int
    static_estimate_bytes: int | None
    risk_columns: bool
    kill_ceiling_bytes: int
    complete: bool = True
    probe_applicable: bool = False
    probe: ProbeFacts | None = None


def admission_ceiling_bytes(kill_ceiling_bytes: int) -> int:
    return int(kill_ceiling_bytes * RESIDENT_ADMISSION_FRACTION)


def resident_fit_verdict(facts: ResidentFitFacts) -> ResidentFit:
    """The one place the ceilings are compared. First match wins:

    1. `LB < A`, the static estimate with its calibration band under `A`, no risk column: fits.
    2. `LB > H`: refused; the input and one pandas copy alone cannot fit.
    3. A measured probe: fits when `LB < A` and its upper edge is under `A` with no risk column;
       refused when its estimate clears `H` by the whole calibration band.
    4. Anything else is unverified and runs as before.

    The static estimate alone never refuses (it over-prices pooled strings by up to 3x).
    """
    from decoy_engine.execution._mem_estimate import K_CALIBRATION_ERROR_BAND

    band = K_CALIBRATION_ERROR_BAND
    kill = facts.kill_ceiling_bytes
    admit = admission_ceiling_bytes(kill)
    lb = facts.lower_bound_bytes
    static = facts.static_estimate_bytes

    def verdict(kind: str, code: str, estimated: int) -> ResidentFit:
        return ResidentFit(kind, code, facts.table_count, estimated, lb, admit, kill)

    if (
        facts.complete
        and not facts.risk_columns
        and lb < admit
        and static is not None
        and static * (1 + band) < admit
    ):
        return verdict(FIT, reasons.route.NONFK_FULL_FRAME_FITS, static)
    if lb > kill:
        return verdict(INSUFFICIENT, reasons.runtime.NONFK_FULL_FRAME_CAPACITY_EXCEEDED, lb)
    measured = facts.probe.estimated_bytes if facts.probe is not None else None
    if facts.probe is not None and measured is not None:
        if measured > kill * (1 + band):
            return verdict(
                INSUFFICIENT, reasons.runtime.NONFK_FULL_FRAME_CAPACITY_EXCEEDED, measured
            )
        if (
            facts.complete
            and not facts.probe.uniqueness_risk
            and not facts.risk_columns
            and lb < admit
            and measured * (1 + band) < admit
        ):
            return verdict(FIT, reasons.route.NONFK_FULL_FRAME_PROBE_FITS, measured)
    return verdict(UNKNOWN, reasons.route.NONFK_FULL_FRAME_UNVERIFIED, measured or static or 0)


def require_resident_fit(fit: ResidentFit) -> None:
    """Raise the shared capacity refusal when `fit` refuses; return otherwise."""
    if fit.verdict == INSUFFICIENT:
        from decoy_engine.execution._errors import nonfk_full_frame_capacity_error

        raise nonfk_full_frame_capacity_error(
            needed_bytes=fit.estimated_bytes, kill_ceiling_bytes=fit.kill_ceiling_bytes
        )


def resident_fit_metrics(fit: ResidentFit) -> dict[str, Any]:
    """The verdict as plain tokens, counts and bytes, the shape its `quality_metrics` block will take."""
    return dataclasses.asdict(fit)


def resident_names(ctx: PipelineRunContext, decision: RouteDecision) -> tuple[str, ...]:
    """The mask tables the full-frame executor will hold whole, in config order.

    A chunked route holds none; a multi-table split sends its dispatched tables to the lanes.
    """
    if decision.route_chunked:
        return ()
    dispatched = frozenset(decision.split.dispatched) if decision.split is not None else frozenset()
    return tuple(n for n, kind in ctx.table_kinds.items() if kind == "mask" and n not in dispatched)


def _in_scope(ctx: PipelineRunContext, decision: RouteDecision) -> bool:
    """Every condition for pricing a job lives here, so no caller copies one."""
    return (
        ctx.execution_mode == "auto"
        and ctx.has_mask_table
        and not ctx.graph.edges
        and decision.route == "full_frame"
        and bool(resident_names(ctx, decision))
    )


def store_resident_fit(
    ctx: PipelineRunContext,
    decision: RouteDecision,
    additional_resident: Iterable[pa.Table] = (),
) -> RouteDecision:
    """`decision` with its resident-fit verdict, or `decision` unchanged when out of scope.

    Raises the capacity refusal here, before the route opens an output, a cast run or a spool.
    """
    if not _in_scope(ctx, decision):
        return decision
    fit = gather_resident_fit(ctx, decision, additional_resident)
    require_resident_fit(fit)
    if fit.verdict == UNKNOWN:
        _logger.info("resident fit unverified: %s", fit.code)
    return dataclasses.replace(decision, resident_fit=fit)


def gather_resident_fit(
    ctx: PipelineRunContext,
    decision: RouteDecision,
    additional_resident: Iterable[pa.Table] = (),
) -> ResidentFit:
    """Read the job's sizes and the host ceiling; run a probe only when the ladder needs one.

    Gathers numbers and calls `resident_fit_verdict`; it compares nothing itself.
    """
    from decoy_engine.execution import out_of_core
    from decoy_engine.execution._errors import ExecutionError

    names = resident_names(ctx, decision)
    try:
        kill = out_of_core.detect_effective_memory_bytes()
    except ExecutionError as exc:
        if exc.code != reasons.runtime.OUT_OF_CORE_MEMORY_DETECTION_FAILED:
            raise
        # No ceiling to compare with: the job runs as it did before this check existed.
        return ResidentFit(
            UNKNOWN, reasons.route.NONFK_FULL_FRAME_UNVERIFIED, len(names), 0, 0, 0, 0
        )
    tables = _priced_tables(ctx, names)
    specs = [*tables.specs, *(resident_spec(t, charge_pandas=False) for t in additional_resident)]
    facts = ResidentFitFacts(
        table_count=len(names),
        lower_bound_bytes=lower_bound_bytes(specs),
        static_estimate_bytes=_static_estimate(ctx, names),
        risk_columns=bool(_risk_columns(ctx, names)),
        kill_ceiling_bytes=kill,
        complete=tables.complete,
        probe_applicable=_probe_applicable(ctx, names),
    )
    verdict = resident_fit_verdict(facts)
    if verdict.verdict == UNKNOWN and facts.probe_applicable:
        facts = dataclasses.replace(facts, probe=_run_probe(ctx, names, kill))
        verdict = resident_fit_verdict(facts)
    return verdict


@dataclass(frozen=True)
class _PricedTables:
    specs: tuple[TableBytesSpec, ...]
    complete: bool


def _priced_tables(ctx: PipelineRunContext, names: tuple[str, ...]) -> _PricedTables:
    """A size spec per table the run holds whole; a table with no readable size marks the set
    incomplete. A lazy table is priced from its footer: nothing is read."""
    specs: list[TableBytesSpec] = []
    complete = True
    for name in names:
        source = ctx.caller_sources.get(name)
        if isinstance(source, pa.Table):
            specs.append(resident_spec(source))
        elif isinstance(source, LazySource):
            footer = _footer_or_none(source)
            if footer is None:
                complete = False
            else:
                specs.append(lazy_spec(footer[0], footer[1]))
        else:
            complete = False
    return _PricedTables(tuple(specs), complete)


def _footer_or_none(source: LazySource) -> tuple[int, pa.Schema] | None:
    # A footer that cannot be read leaves the table unpriced; the whole read later raises its
    # own coded error, so nothing is hidden by declining to price it here.
    try:
        facts = source.footer_facts()
    except Exception:
        return None
    return facts.num_rows, facts.schema


def _profile_tables(ctx: PipelineRunContext, names: tuple[str, ...]) -> list[Any]:
    from decoy_engine.execution._transforms_admission import routing_profile

    profile = routing_profile(ctx.profile, ctx.caller_sources, ctx.prepared.prepared)
    return [t for t in profile.tables if t.name in names]


def _static_estimate(ctx: PipelineRunContext, names: tuple[str, ...]) -> int | None:
    from decoy_engine.execution._mem_estimate import estimate_peak_bytes
    from decoy_engine.execution._pipeline_routing_samples import _mask_specs

    specs = _mask_specs(_profile_tables(ctx, names), ctx.caller_sources)
    return estimate_peak_bytes(specs, "full_frame").estimated_bytes


def _risk_columns(ctx: PipelineRunContext, names: tuple[str, ...]) -> tuple[tuple[str, str], ...]:
    """Columns near their cardinality ceiling, judged on the sample the profile read."""
    from decoy_engine.execution._probe import sampled_uniqueness_risk

    tables = _profile_tables(ctx, names)
    rows = {t.name: t.row_count for t in tables}
    distinct: dict[tuple[str, str], int] = {}
    non_null: dict[tuple[str, str], int] = {}
    for t in tables:
        sample = min(t.row_count, BOUNDED_FALLBACK_ROWS)
        for c in t.columns:
            if c.distinct_count is not None:
                distinct[(t.name, c.name)] = c.distinct_count
                non_null[(t.name, c.name)] = max(sample - c.null_count, 0)
    return sampled_uniqueness_risk(rows, distinct, non_null)


def _probe_applicable(ctx: PipelineRunContext, names: tuple[str, ...]) -> bool:
    """A probe measures the whole forced full-frame job in a child process, so it needs resident
    tables, ambient file access and a resident set that is every mask table."""
    mask_tables = [n for n, kind in ctx.table_kinds.items() if kind == "mask"]
    return (
        len(_profile_tables(ctx, names)) == len(names)
        and fileaccess.is_ambient()
        and ctx.config.get("subset") is None
        and set(names) == set(mask_tables)
        and all(isinstance(ctx.caller_sources.get(n), pa.Table) for n in names)
    )


def _run_probe(ctx: PipelineRunContext, names: tuple[str, ...], kill: int) -> ProbeFacts:
    from decoy_engine.execution import _probe
    from decoy_engine.execution._mem_estimate import raw_data_bytes
    from decoy_engine.execution._pipeline_routing_samples import _mask_specs

    tables = _profile_tables(ctx, names)
    raw = raw_data_bytes(_mask_specs(tables, ctx.caller_sources))
    largest = max(tables, key=lambda t: t.row_count)
    try:
        result = _probe.probe_peak_bytes(
            ctx.config,
            dict(ctx.caller_sources),
            reference_table=largest.name,
            target_rows=largest.row_count,
            uniqueness_risk_columns=_risk_columns(ctx, names),
            raw_floor_bytes=raw.priceable_bytes if raw.is_priceable else None,
            mem_cap_bytes=kill,
            timeout_s=_probe.DEFAULT_PROBE_TIMEOUT_S,
            engine_version=ctx.engine_version,
            risk_policy="measure",
        )
    except Exception as exc:
        # The probe only adds evidence. A job it cannot run (a prepared transform changed the
        # schema, a child failed to start) stays unverified and runs as it did before.
        _logger.info("resident fit probe unavailable: %s", type(exc).__name__)
        return ProbeFacts(None)
    return ProbeFacts(result.estimated_peak_bytes, result.uniqueness_risk)
