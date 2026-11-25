"""The post-scan gate: one check of a run's outputs before they become visible (plan 4.5).

Declared keys are measured over Arrow batches by `check_keys`. The column suite runs through
`run_post_mask` only when `post_scan.integrity` asks for it, so a run that only declares
relationships is never scanned for findings it did not opt in to. `post_scan_verdict` decides and a
block raises `PostScanBlockedError` after every `except` block has closed, so its chain is empty.
A coded engine error from a part propagates unchanged; any other keeps only its class name,
because a reader or DuckDB message can quote key values.

`execute_route` binds one gate per run (`bind_gate`); a route that holds its outputs resident
runs it before it commits, and `observed_commit` refuses a commit while a required gate has not
run. `settle` runs it over the returned outputs when no route did, and stamps its report on the
result.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Collection, Iterator, Mapping
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import pyarrow as pa

from decoy_engine import fileaccess, reasons
from decoy_engine.config import (
    RelationshipConfig,
    parse_relationship_config,
    post_scan_gate_applies,
    post_scan_integrity_requested,
    post_scan_ner_findings,
    post_scan_output_readable,
    post_scan_sink_kind,
)
from decoy_engine.execution._chunked_input import SourceFacts, capture_source_facts, check_opened
from decoy_engine.execution._pipeline_sources import materialize_source
from decoy_engine.execution._transforms_gate import transform_bearing_mask_tables
from decoy_engine.execution.out_of_core import MaskedKeyStager, resolve_ooc_memory_limit
from decoy_engine.execution.pipeline._post_scan_distribution import (
    DistributionState,
    refuse_transformed_integrity,
    refuse_unchecked_distribution,
)
from decoy_engine.execution.pipeline._post_scan_suite import exact_frames, suite_tables
from decoy_engine.generation.pool._events import QualityWarning
from decoy_engine.internal.memory_limit import require_megabytes
from decoy_engine.profile import LazySource
from decoy_engine.profiling import MEMORY_LIMIT, passes_through
from decoy_engine.progress import safe_error_class
from decoy_engine.reasons import reason_ref_payload
from decoy_engine.verification.postmask import (
    SCHEMA_VERSION,
    KeyResult,
    PostScanVerdict,
    blocked_error,
    check_keys,
    from_lazy,
    from_staged,
    from_table,
    key_columns,
    keys_report,
    post_scan_verdict,
    raise_if_ner_blocked,
    run_post_mask,
    run_post_mask_tables,
    with_cast,
)

if TYPE_CHECKING:
    from decoy_engine.execution._adapter import ExecutionResult
    from decoy_engine.execution._pipeline_context import PipelineRunContext
    from decoy_engine.plan.column_access import TableWrites
    from decoy_engine.profiling.model_pack import DetectorSet
    from decoy_engine.verification.postmask import TableBatches
    from decoy_engine.verification.postmask.distribution import DistributionInput

__all__ = [
    "PostScanGate",
    "active_gate",
    "attach_cast_run",
    "bind_gate",
    "note_quarantined",
    "settle",
    "tee_reader",
]

# `pass_failed_with` when the commit is reached and a required gate never ran.
_NOT_RUN: Final = "PostScanGateNotRun"


# Below this cap DuckDB's hash join fails to pin a block even at 100k keys.
_FLOOR_MB: Final = 128


class PostScanGate:
    """One run's gate. `ran` is set once a check completes; every later call is a no-op. After a
    run, `report` is the value-free report and `verdict` the decision on it."""

    def __init__(
        self,
        config: Mapping[str, Any],
        *,
        budget_bytes: int | None = None,
        source_facts: Mapping[str, SourceFacts] | None = None,
        deferred: bool = False,
        sources: Mapping[str, pa.Table | LazySource] | None = None,
        detectors: DetectorSet | None = None,
        writes: Mapping[str, TableWrites] | None = None,
    ) -> None:
        self.required = post_scan_gate_applies(config)
        # Post-scan models loaded strictly at run start; they read resident outputs only.
        self._detectors = detectors
        self._writes = writes  # the run's writer query; None makes the runner compute it
        # True on a route whose inputs or output the gate cannot read back yet: the run is then
        # checked report-only, as before the gate, and says so on its result.
        self.deferred = deferred and self.required
        # A commit to a sink the gate cannot read back: delivered unchecked, deferred, said so.
        self.output_unreadable = False
        self.ran = False
        self.report: dict[str, Any] | None = None
        self.verdict: PostScanVerdict | None = None
        self._config = config
        self._budget_bytes = budget_bytes
        # Key columns of parent rows quarantine removed, in memory only: such a child is no orphan.
        self._quarantined: dict[tuple[str, tuple[str, ...]], list[pa.Table]] = {}
        # Footer facts of each lazy input before any read: a re-read refuses a changed file.
        self._source_facts = source_facts or {}
        # The caller's inputs, re-read (with declared casting) by a commit with no resident output.
        self._sources = sources or {}
        self._cast_run: Any = None
        # Writes that carry row values (the quarantine file), held until the verdict passes.
        self._held: list[Callable[[], None]] = []
        # Key and cast columns of each table only the route reads, copied once to scratch Parquet.
        self._teed: dict[str, LazySource] = {}
        self._scratch = ExitStack()
        self._scratch_root: Path | None = None
        self._distribution = DistributionState.for_run(config)

    @property
    def enforces_ner(self) -> bool:
        """A deferred gate whose report-only check still blocks on NER (`ner_findings: fail`)."""
        return (
            self.deferred
            and post_scan_integrity_requested(self._config)
            and post_scan_ner_findings(self._config) == "fail"
        )

    @property
    def memory_limit(self) -> str:
        """The key scan's DuckDB cap: its own fixed cap or the run's budget share, whichever is
        less, never below the working floor. The scan spills to its scratch directory past it."""
        budget = resolve_ooc_memory_limit(self._budget_bytes).memory_limit
        capped = min(MEMORY_LIMIT, budget, key=require_megabytes)
        return f"{max(_FLOOR_MB, require_megabytes(capped))}MB"

    def run_resident(
        self,
        outputs: Mapping[str, pa.Table],
        sources: Mapping[str, pa.Table | LazySource],
        table_kinds: Mapping[str, str],
        *,
        raw_sources: bool = False,
    ) -> None:
        """Check resident outputs against their sources (resident or lazy, re-read in batches);
        raise if the verdict blocks. `raw_sources` says the sources are the caller's own, before
        any declared cast, so the re-read casts them as the route did."""
        if self.ran or not self.required:
            return
        if self.deferred:
            self._report_only(outputs, sources, table_kinds)
            return
        if not all(name in outputs for name in table_kinds):
            return  # the route wrote to a sink as it went; the commit reads the staged files
        suite = None
        if post_scan_integrity_requested(self._config):

            def suite(keys: tuple[KeyResult, ...]) -> dict[str, Any]:
                return self._column_suite(outputs, sources, table_kinds, keys, raw_sources)

        views = {name: from_table(name, table) for name, table in outputs.items()}
        self._decide(views, sources, raw_sources, suite)

    def _decide(
        self,
        outputs: Mapping[str, TableBatches],
        sources: Mapping[str, pa.Table | LazySource],
        raw_sources: bool,
        suite: Callable[[tuple[KeyResult, ...]], dict[str, Any]] | None,
    ) -> None:
        failed: str | None = None
        keys: tuple[KeyResult, ...] = ()
        try:
            keys = self._keys(outputs, sources, raw_sources)
        except Exception as exc:
            if passes_through(exc):
                raise
            failed = safe_error_class(type(exc).__name__)
        report: dict[str, Any] = {"schema_version": SCHEMA_VERSION}
        if suite is not None:
            try:
                report = suite(keys)
            except Exception as exc:
                if passes_through(exc):
                    raise
                failed = failed or safe_error_class(type(exc).__name__)
        report["keys"] = keys_report(keys)
        if failed:
            report["pass_failed_with"] = failed
        verdict = post_scan_verdict(report, ner_findings=post_scan_ner_findings(self._config))
        report["verdict"] = verdict.as_dict()
        self.report, self.verdict, self.ran = report, verdict, True
        error = blocked_error(report, verdict)
        if error is not None:
            raise error

    def tee_reader(self) -> Callable[[str, pa.Table], None] | None:
        """The callback the route's loader resolution tells each read it takes from a loader or
        through transforms. It copies the key and cast columns of each declared key table, as
        the route read them, into scratch, so the gate's baseline is what the route masked and
        no read is repeated. `None` when no check will use it."""
        if not self.required or self.deferred:
            return None
        wanted = key_columns(self._relationships())

        def tee(name: str, table: pa.Table) -> None:
            if name in wanted and name not in self._teed:
                self._tee(name, table, wanted[name])

        return tee

    def _tee(self, name: str, table: pa.Table, columns: tuple[str, ...]) -> None:
        cast = self._cast_run
        if cast is not None and name in cast.tables():
            columns = (*columns, *cast.declared_columns(name))
        kept = table.select([c for c in dict.fromkeys(columns) if c in table.column_names])
        if self._scratch_root is None:
            self._scratch_root = self._scratch.enter_context(
                fileaccess.protected_scratch_dir(prefix="decoy-post-scan-tee-")
            )
        path = self._scratch_root / f"t{len(self._teed):04d}.parquet"
        # The out-of-core key stager is the engine's one narrow-column scratch writer: 0600 files
        # under the engine-issued scratch root, read back through its own scratch reader.
        stager = MaskedKeyStager(path, columns=tuple(kept.column_names), fixed_schema=kept.schema)
        try:
            for batch in kept.to_batches():
                stager.add(batch, batch)
        finally:
            stager.close()
        self._teed[name] = stager.source()

    def close(self) -> None:
        """Remove the tee's scratch files."""
        self._scratch.close()

    def attach_cast_run(self, cast_run: Any) -> None:
        """The run's declared casting, so a re-read of the raw inputs types them as the route did."""
        self._cast_run = cast_run

    def _report_only(
        self,
        outputs: Mapping[str, pa.Table],
        sources: Mapping[str, pa.Table | LazySource],
        table_kinds: Mapping[str, str],
    ) -> None:
        """The check a deferred route gets: the column suite over the mask tables the run still
        holds, reported and blocking only through the NER predicate (`ner_findings: fail`, which
        is never report-only). Declared keys alone get no check yet. A suite that cannot run is
        reported by class name with a blocking verdict, never as a clean pass."""
        wanted = post_scan_integrity_requested(self._config)
        masked = suite_tables(outputs, sources, table_kinds) if wanted else []
        if not masked:
            self.ran = True
            return
        try:
            report = run_post_mask(
                exact_frames({n: materialize_source(sources[n]) for n in masked}),
                exact_frames({n: outputs[n] for n in masked}),
                config=dict(self._config),
                detectors=self._detectors,
                writes=self._writes,
            )
        except Exception as exc:
            if passes_through(exc):
                raise
            failed = safe_error_class(type(exc).__name__)
            report = {"schema_version": SCHEMA_VERSION, "pass_failed_with": failed}
        ner_findings = post_scan_ner_findings(self._config)
        verdict = post_scan_verdict(report, ner_findings=ner_findings)
        report["verdict"] = verdict.as_dict()
        self.report, self.verdict, self.ran = report, verdict, True
        raise_if_ner_blocked(report, ner_findings=ner_findings)

    def note_quarantined(self, table: str, rows: pa.Table, removed: Collection[int]) -> None:
        """Record the declared parent keys of `rows` (a table before quarantine filtered it) at
        the `removed` row indices."""
        if self._distribution is not None and not self.deferred:
            self._distribution.note_quarantined(table, removed)
        if not self.required or self.deferred or not removed:
            return
        for rel in self._relationships():
            columns = tuple(rel.parent.columns)
            if rel.parent.table == table and set(columns) <= set(rows.column_names):
                taken = rows.select(list(columns)).take(sorted(removed))
                self._quarantined.setdefault((table, columns), []).append(taken)

    def _relationships(self) -> list[RelationshipConfig]:
        return [
            parse_relationship_config(raw, prefix=f"relationship {n} is invalid")
            for n, raw in enumerate(self._config.get("relationships") or ())
        ]

    def before_commit(self, sink: Any) -> None:
        """A required gate that has not run when a sink commits reads the sink's staged files
        back and judges them before anything is published. A sink it cannot read (a foreign
        class, never trusted) is deferred: the run delivers through it and the result says the
        output went unchecked. With no sink (the post-condition after the route) a gate that never
        ran is a wiring fault and refuses."""
        if self.ran or not self.required:
            return
        if sink is not None and not post_scan_output_readable(post_scan_sink_kind(sink)):
            # Flagged even when the route already deferred the gate, so the warning is not lost.
            self.output_unreadable = True
            self.ran = not self.deferred  # a deferred gate still owes its report-only check
            return
        if self.deferred:
            return
        openers = _staged_openers(sink)
        if openers is not None:
            if post_scan_integrity_requested(self._config) and transform_bearing_mask_tables(
                self._config
            ):
                # The suite compares output with the raw source, and a transformed table's rows
                # no longer line up with it. Refused before the commit, so nothing is published.
                refuse_transformed_integrity()
            staged = {name: from_staged(name, opener) for name, opener in openers.items()}
            suite = (
                self._staged_suite(staged) if post_scan_integrity_requested(self._config) else None
            )
            self._decide(staged, self._sources, True, suite)
            return
        report = {"schema_version": SCHEMA_VERSION, "pass_failed_with": _NOT_RUN}
        error = blocked_error(report, post_scan_verdict(report))
        if error is not None:
            raise error

    def _staged_suite(
        self, staged: Mapping[str, TableBatches]
    ) -> Callable[[tuple[KeyResult, ...]], dict[str, Any]]:
        """The column suite over staged output, in batches. A table the route transformed has no
        raw baseline to compare against, so `before_commit` refuses that case before it gets here."""
        masked = suite_tables(staged, self._sources)

        def suite(keys: tuple[KeyResult, ...]) -> dict[str, Any]:
            with fileaccess.protected_scratch_dir(prefix="decoy-post-scan-columns-") as scratch:
                return run_post_mask_tables(
                    {n: self._source(n, self._sources[n], True) for n in masked},
                    {n: staged[n] for n in masked},
                    config=self._config,
                    keys=keys,
                    scratch=scratch,
                    memory_limit=self.memory_limit,
                    distribution=self._distribution_input(masked, self._sources, True),
                    writes=self._writes,
                )

        return suite

    def _source(self, name: str, source: pa.Table | LazySource, raw: bool) -> TableBatches:
        if not isinstance(source, LazySource):
            base = from_table(name, source)
        else:
            # A teed file is the engine's own copy of the route's read, not the caller's input.
            expected = None if self._teed.get(name) is source else self._source_facts.get(name)
            if expected is None:
                base = from_lazy(name, source)
            else:
                base = from_lazy(
                    name, source, on_open=lambda opened: check_opened(opened, expected, table=name)
                )
        cast = self._cast_run
        if not raw or cast is None or name not in cast.tables():
            return base
        typed = cast.cast_batch(name, base.schema.empty_table(), record=False).table.schema
        # `record=False`: the route already counted this pass; the re-read must not count again.
        return with_cast(
            base,
            needs=cast.declared_columns(name),
            schema=typed,
            drops_rows=name in cast.quarantine_tables(),
            cast=lambda table, offset: (
                cast.cast_batch(name, table, offset=offset, record=False).table
            ),
        )

    def _keys(
        self,
        outputs: Mapping[str, TableBatches],
        sources: Mapping[str, pa.Table | LazySource],
        raw_sources: bool,
    ) -> tuple[KeyResult, ...]:
        rels = self._relationships()
        if not rels:
            return ()
        # The gate's connections go through the run's own recorder and thread cap, which
        # `execute_route` binds around the route and this check alike.
        with fileaccess.protected_scratch_dir(prefix="decoy-post-scan-gate-") as scratch:
            return check_keys(
                rels,
                {
                    name: self._source(name, src, raw_sources)
                    for name, src in {**sources, **self._teed}.items()
                },
                dict(outputs),
                scratch=scratch,
                memory_limit=self.memory_limit,
                quarantined=self._quarantined,
            )

    def _column_suite(
        self,
        outputs: Mapping[str, pa.Table],
        sources: Mapping[str, pa.Table | LazySource],
        table_kinds: Mapping[str, str],
        keys: tuple[KeyResult, ...],
        raw_sources: bool,
    ) -> dict[str, Any]:
        # Generated tables have no source to compare against, as in the report-only suite.
        masked = suite_tables(outputs, sources, table_kinds)
        return run_post_mask(
            exact_frames({n: materialize_source(sources[n]) for n in masked}),
            exact_frames({n: outputs[n] for n in masked}),
            config=dict(self._config),
            detectors=self._detectors,
            keys=keys,
            distribution=self._distribution_input(masked, sources, raw_sources),
            writes=self._writes,
        )

    def _distribution_input(
        self, tables: list[str], sources: Mapping[str, pa.Table | LazySource], raw: bool
    ) -> DistributionInput | None:
        """The distribution check's input, its source side read through `_source` like every
        other source side of the gate; `None` when the run did not ask for the check."""
        if self._distribution is None:
            return None
        return self._distribution.build(
            self._config,
            tables,
            lambda n: self._source(n, sources[n], raw),
            cast_run=self._cast_run,
        )


_ACTIVE: ContextVar[PostScanGate | None] = ContextVar("decoy_post_scan_gate", default=None)


def active_gate() -> PostScanGate | None:
    """The gate bound to this run, or `None` outside `bind_gate`."""
    return _ACTIVE.get()


def _staged_openers(sink: Any) -> Mapping[str, Callable[[], int]] | None:
    """The staged files of a sink the gate may read back, or `None` for no sink or a sink class
    it does not trust (a foreign producer's files are never read)."""
    if sink is None or not post_scan_output_readable(post_scan_sink_kind(sink)):
        return None
    staged = getattr(sink, "staged_tables", None)
    return staged() if callable(staged) else None


def tee_supported() -> bool:
    """Whether the scratch writer the tee uses can run here: it opens files and directories with
    POSIX descriptor flags. Where it cannot, a loader or transformed run stays deferred. The one
    place that decides, for `_deferred` (and so `tee_reader`, which returns nothing when deferred)."""
    return all(hasattr(os, flag) for flag in ("O_NOFOLLOW", "O_CLOEXEC", "O_DIRECTORY"))


def _deferred(ctx: PipelineRunContext, route: str | None = None) -> bool:
    """Whether this run's inputs cannot be read back by the gate before the route runs: a loader
    supplies tables nothing can re-read, and a lazy table that declares transforms is
    transformed inside the route. The sequential route loads each such table once through a
    loader resolution the gate tees (`tee_reader`), so it is the one route that is not deferred,
    and only where `tee_supported` says the scratch writer can run.
    Outputs that are not resident are read at commit."""
    lazy_transformed = any(
        isinstance(ctx.caller_sources.get(name), LazySource)
        for name in transform_bearing_mask_tables(ctx.config)
    )
    teed = route == "sequential" and tee_supported()
    return (ctx.source_loader is not None or lazy_transformed) and not teed


@contextmanager
def bind_gate(ctx: PipelineRunContext, route: str | None = None) -> Iterator[PostScanGate]:
    """Bind one gate for the run. Its lazy-input snapshot is taken here, before any route reads."""
    deferred = _deferred(ctx, route)
    refuse_unchecked_distribution(ctx, deferred=deferred)
    facts = (
        capture_source_facts(ctx.caller_sources, ctx.table_kinds)
        if post_scan_gate_applies(ctx.config) and not deferred
        else {}
    )
    gate = PostScanGate(
        ctx.config,
        budget_bytes=ctx.out_of_core_budget_bytes,
        source_facts=facts,
        deferred=deferred,
        sources=ctx.caller_sources,
        detectors=ctx.post_scan_detectors,
        writes=ctx.writes,
    )
    token = _ACTIVE.set(gate)
    try:
        yield gate
    finally:
        _ACTIVE.reset(token)
        gate.close()


def tee_reader() -> Callable[[str, pa.Table], None] | None:
    """The run's gate baseline tee, for the route's loader resolution. Outside `bind_gate` there
    is no gate and nothing to tee."""
    gate = active_gate()
    return None if gate is None else gate.tee_reader()


def attach_cast_run(cast_run: Any) -> None:
    """Tell the run's gate about the declared casting a route opened. Outside `bind_gate`, or
    with no cast run, there is nothing to attach."""
    if cast_run is not None and (gate := active_gate()) is not None:
        gate.attach_cast_run(cast_run)


def note_quarantined(
    tables: Mapping[str, pa.Table], removed: Mapping[str, Collection[int]]
) -> None:
    """Tell the run's gate which rows quarantine is about to remove from `tables` (still
    unfiltered). Outside `bind_gate` there is no gate and nothing to tell."""
    if (gate := active_gate()) is None:
        return
    for name, rows in removed.items():
        if name in tables:
            gate.note_quarantined(name, tables[name], rows)


def publish_after_gate(write: Callable[[], None]) -> None:
    """Run `write`, a publish that carries row values, once nothing can block the run: now when
    no gate will judge it, else in `settle` after the verdict passes. A blocked run drops it."""
    gate = active_gate()
    # A deferred gate judges nothing, except the NER block its report-only check still enforces.
    if gate is None or not gate.required or gate.ran or (gate.deferred and not gate.enforces_ner):
        write()
    else:
        gate._held.append(write)


def settle(gate: PostScanGate, ctx: PipelineRunContext, result: ExecutionResult) -> ExecutionResult:
    """After a route returns: run the gate over the outputs when no route did, refuse a required
    gate that still has not run, publish what waited on the verdict, and stamp the report."""
    if not gate.ran:
        gate.run_resident(result.outputs, ctx.caller_sources, ctx.table_kinds, raw_sources=True)
    if gate.required and not gate.ran:
        gate.before_commit(None)
    held, gate._held = gate._held, []
    for write in held:
        write()
    if gate.report is not None:
        result.quality_metrics["post_scan_integrity"] = gate.report
    if gate.deferred or gate.output_unreadable:
        result.quality_metrics["post_scan_gate_deferred"] = reason_ref_payload(
            reasons.post_scan.GATE_DEFERRED_ROUTE.spec.ref
        )
    if gate.output_unreadable:
        return replace(
            result,
            warnings=(
                *result.warnings,
                QualityWarning(
                    code=reasons.warning.POST_SCAN_OUTPUT_UNREADABLE, provider="post_scan"
                ),
            ),
        )
    return result
