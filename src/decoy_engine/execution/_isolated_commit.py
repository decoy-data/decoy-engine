"""Parent-side publication and result-envelope IO for the isolated-run primitive.

Split out of `_isolated_run.py` (which owns spawn/classify orchestration) to stay under the
~600 LOC orchestration cap: filesystem and publication helpers with no subprocess lifecycle of
their own, shared by the isolated (subprocess) path and the `isolate=False` fallback so both
publish through F22's `publish_unit` with one discipline (plan 5.7).

The isolated parent opens a `publication` stage beside `output_dir` and hands its path to the
child, which stages plain Parquet files there and nothing else. The child is an untrusted
producer (class 6), so before anything is measured the parent establishes the staged set
itself: the envelope's table names must each be one path component, and the stage, listed
through the file-access policy without following links, must hold exactly those files, each a
regular file. Anything else (a child-written `_decoy_publication.json`, an extra file, a
directory, a link, a missing table) is refused with nothing bound. Each admitted entry is made
owner-only (0600, the stage 0700) before it is read, since the child's umask decided its mode
(V1-b). `publish_unit` then measures the bytes (size, SHA-256, footer rows) and writes the
descriptor; the child's word is never taken for any of them. Pattern: Git's receiving side
(`git index-pack --strict`) recomputes every object id from the received bytes and checks the
pack's contents rather than trusting the sender's claims.

The fallback stages its in-memory tables, each as `<table>.parquet`, into its own `publication`
stage and binds them with `publish_unit`: what `publish_tables` does, with the stage held here
so the cleanup of a refused stage is confirmed by looking (F29).
"""

from __future__ import annotations

import json
import signal
import sys
import uuid
from collections.abc import Callable, Mapping
from contextlib import ExitStack
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, TypeGuard

import pyarrow as pa

from decoy_engine import fileaccess
from decoy_engine.errors import DecoyError
from decoy_engine.execution._isolated_common import IsolatedRunResult, commit_error_text
from decoy_engine.execution._isolated_reason import (
    Attempt,
    commit_reason,
    envelope_failure,
    readback_memory_failure,
    readback_refused,
)
from decoy_engine.execution._row_errors import RowErrorRecord
from decoy_engine.execution._transactional_sink import _validate_table_name
from decoy_engine.execution.pipeline import (
    INSUFFICIENT,
    ResidentFit,
    TableBytesSpec,
    check_readback,
    kill_ceiling,
    lazy_spec,
    lower_bound_bytes,
    resident_spec,
)
from decoy_engine.fileaccess import (
    FileRequest,
    FileRole,
    OutputDir,
    OutputTxn,
    handed_stage_dir,
    is_memory_failure,
    is_valid_component,
    own_entry,
)
from decoy_engine.fileaccess.adapters import arrow as arrow_adapter
from decoy_engine.io.bounded_reader import UnsupportedColumnType
from decoy_engine.publication import (
    CommitReceipt,
    PublicationRequest,
    failed_receipt,
    publish_tables,
    publish_unit,
    raise_for_outcome,
)
from decoy_engine.reason_adapter import reason_from_exception
from decoy_engine.reasons import (
    CleanupState,
    Operation,
    Phase,
    PublicationState,
    ReasonContext,
)

__all__ = [
    "COMMITTED",
    "Collected",
    "CommitError",
    "Publication",
    "Readback",
    "ReadbackMemoryFailure",
    "ReadbackRefused",
    "begin_publication",
    "collect",
    "failed_publication",
    "publish_resident",
    "read_envelope",
    "result_from_envelope",
    "row_errors_of",
    "signal_name",
    "stage_sources",
]

COMMITTED = frozenset({"published", "already_committed"})
_FIELD_KEY = "output_dir"


class CommitError(DecoyError):
    """A staged isolated output that could not be committed (F29: `publication_failed`).

    Nothing in the route raises it since the route publishes through `publish_unit`, whose
    receipts carry the outcome; the class stays registered with the reason adapter."""


@dataclass(frozen=True)
class Publication:
    """The parent's publication of one isolated run: capability, open stage and request."""

    out: OutputDir
    txn: OutputTxn
    request: PublicationRequest
    stage: Path
    target: Path


@dataclass(frozen=True)
class Readback:
    """What the driver measured while reading the child's output back, as plain integers.

    `floor_bytes` is the strict lower bound over the footers of the staged outputs, `held_bytes`
    the measured buffer bytes of those already read, so a completed run shows the floor was not
    above reality. `sources_bytes` is the caller's resident sources, which the driver also holds.
    """

    kill_ceiling_bytes: int | None
    sources_bytes: int
    floor_bytes: int
    held_bytes: int
    tables_read: int
    tables_staged: int


@dataclass(frozen=True)
class Collected:
    """The staged tables read back, and the publication receipt when there was an `output_dir`."""

    outputs: dict[str, pa.Table]
    receipt: CommitReceipt | None
    extra: dict[str, Any]


@dataclass(frozen=True)
class ReadbackRefused:
    """The strict floor of the readback was over the kill ceiling; nothing more was read and the
    stage is aborted. `receipt` is the failed receipt when there was an `output_dir`."""

    fit: ResidentFit
    receipt: CommitReceipt | None
    extra: dict[str, Any]


@dataclass(frozen=True)
class ReadbackMemoryFailure:
    """A memory failure while the driver read the output back. It carries no exception: the
    exception's text can name sizes and values."""

    receipt: CommitReceipt | None
    extra: dict[str, Any]


def _request(request: PublicationRequest | None) -> PublicationRequest:
    return request if request is not None else PublicationRequest(uuid.uuid4().hex)


def _output(output_dir: Path) -> OutputDir:
    req = FileRequest(FileRole.TARGET_OUTPUT, "write", str(output_dir), _FIELD_KEY)
    return fileaccess.capture().output_dir(req)


def begin_publication(
    output_dir: Path, request: PublicationRequest | None
) -> Publication | CommitReceipt:
    """Open the `publication` stage beside `output_dir` that the child stages into."""
    request = _request(request)
    out = _output(output_dir)
    try:
        txn = out.begin("dir", "exclusive", label="publication")
    except OSError as exc:  # errno only: a parent that cannot be made or opened
        return failed_receipt(request, os_errno=exc.errno)
    return Publication(out, txn, request, Path(txn.local_stage_path()), output_dir)


def publish_resident(
    output_dir: Path, outputs: dict[str, pa.Table], request: PublicationRequest | None
) -> tuple[CommitReceipt, Path | None]:
    """The fallback's publication: `publish_tables` into a `publication` stage beside
    `output_dir`, each table as `<table>.parquet`. Returns the receipt and the stage path, so a
    refusal's cleanup is confirmed by looking (the stage is already discarded unless bound)."""
    if not _names_ok(list(outputs)):  # the isolated route's refusal, so both modes agree
        return failed_receipt(_request(request)), None
    stages: list[str] = []
    receipt = publish_tables(
        _output(output_dir), outputs, _request(request), suffix=".parquet", on_stage=stages.append
    )
    return receipt, Path(stages[0]) if stages else None


def _names_ok(names: object) -> TypeGuard[list[str]]:
    """The child's envelope names, which are its word only: a list of table names that are each
    one path component and map to distinct valid stage components."""
    if type(names) is not list or any(type(n) is not str for n in names):
        return False
    try:
        for name in names:
            _validate_table_name(name)
    except ValueError:
        return False
    components = [f"{name}.parquet" for name in names]
    return len(set(components)) == len(components) and all(map(is_valid_component, components))


def stage_sources(
    work_root: Path, sources: dict[str, pa.Table], source_rollback: ExitStack | None = None
) -> dict[str, dict[str, str]]:
    """Stage each table under an opaque name in the private work root.

    Raises `UnsupportedColumnType` for a dictionary whose values are a dictionary or an extension
    type: Arrow IPC cannot read those back, and Parquet takes no dictionary."""
    for table in sources.values():
        for field in table.schema:
            kind = arrow_adapter.ipc_refusal(field.type)
            if kind is not None:
                raise UnsupportedColumnType(column=field.name, kind=kind)
    stage = handed_stage_dir(work_root, "isolated.sources")
    manifest = {}
    for index, (name, table) in enumerate(sources.items()):
        if all(arrow_adapter.parquet_holds_type(field.type) for field in table.schema):
            fmt = "parquet"
            component = f"s{index:04d}.parquet"
            # Preserve list child names in the private handoff.
            arrow_adapter.write_table(table, stage, component, use_compliant_nested_type=False)
        else:
            fmt = "ipc"
            component = f"s{index:04d}.arrow"
            # The stream format carries each chunk's own dictionary; the file format allows one.
            with arrow_adapter.ipc_new_stream(stage, component, table.schema) as writer:
                arrow_adapter.ipc_write_exact(writer, table)
        if source_rollback is not None:
            source_rollback.callback(stage.remove, component)
        manifest[name] = {"path": str(work_root / component), "format": fmt}
    return manifest


def _admit(stage: Path, names: list[str]) -> bool:
    """True when the stage holds exactly `<name>.parquet` for each name (its reserved marker aside), each a regular file,
    made owner-only (the stage 0700, each file 0600) before anything reads it: the child's
    umask decided its modes. A link or a directory under a table's name raises."""
    posix = sys.platform != "win32"
    if posix:
        own_entry(stage, 0o700, directory=True)
    listing = FileRequest(FileRole.TARGET_OUTPUT, "read_dir", str(stage), _FIELD_KEY)
    with fileaccess.capture().open_dir(listing) as handle:
        found = fileaccess.stage_entries(handle)
    expected = sorted(f"{name}.parquet" for name in names)
    if found != expected:
        return False
    for component in expected if posix else ():
        own_entry(stage / component, 0o600)
    return True


def collect(
    envelope: dict[str, Any],
    staging: Path,
    pub: Publication | None,
    attempt: Attempt,
    sources: Mapping[str, pa.Table] | None = None,
) -> Collected | ReadbackRefused | ReadbackMemoryFailure | CommitReceipt:
    """Admit and read back the child's staged tables, then publish them when there is an
    `output_dir`. `sources` are the caller's resident tables, which the driver also holds.

    Returns the tables; a refusal (the strict floor of the readback is over the kill ceiling); a
    memory failure; or the receipt of a refused stage, a failed read or a publication that did not
    commit. Each of the last three aborts the transaction first; a refused stage is already
    discarded. A refusal and a memory failure drop the tables read so far."""
    request = _request(pub.request if pub is not None else None)
    names = envelope.get("staged_tables")
    reader = _Readback(staging, sources, attempt.extra)
    admitted = False
    memory = False
    code: int | None = None
    try:
        if _names_ok(names) and _admit(staging, names):
            admitted = True
            reader.run(names)
    except MemoryError:
        raise  # to memory_boundary: the window decides what the caller is told
    except (OSError, pa.ArrowException, KeyboardInterrupt) as exc:
        memory = is_memory_failure(exc)
        if isinstance(exc, KeyboardInterrupt) and not memory:
            raise  # a real interrupt; Arrow reports exhaustion at a cap as one with a memory cause
        code = exc.errno if isinstance(exc, OSError) else None
        admitted = False
    if admitted and reader.refusal is None:
        return _publish(reader, pub, request, attempt)
    reader.outputs.clear()
    if pub is not None:
        pub.txn.abort()
    failed = failed_receipt(request, os_errno=code)
    shown = failed if pub is not None else None
    if reader.refusal is not None:
        return ReadbackRefused(reader.refusal, shown, reader.extra)
    return ReadbackMemoryFailure(shown, reader.extra) if memory else failed


def _publish(
    reader: _Readback, pub: Publication | None, request: PublicationRequest, attempt: Attempt
) -> Collected | CommitReceipt:
    """Bind the read-back tables when there is an `output_dir`; the refusals are all before this."""
    outputs = reader.outputs
    if pub is None:
        return Collected(outputs, None, reader.extra)
    components = [f"{name}.parquet" for name in outputs]
    attempt.enter_publishing()  # from here the target may exist: a memory failure is UNKNOWN
    receipt = publish_unit(pub.out, pub.txn, request, tables=components)
    return Collected(outputs, receipt, reader.extra) if receipt.outcome in COMMITTED else receipt


def _priced(table: pa.Table) -> TableBytesSpec:
    """`table` measured for the bound: its Arrow buffers only. A metadata-free view shares the
    buffers and skips the pandas metadata, which the driver never reads."""
    return resident_spec(table.replace_schema_metadata(None), charge_pandas=False)


class _Readback:
    """The driver's readback of one admitted stage, table by table in envelope order.

    Before each decode the strict lower bound over everything the driver would then hold is
    compared with the kill ceiling (`check_readback`): the caller's resident sources and the
    tables read so far at their measured bytes, and this table and the rest at their footer
    floor. Only a bound over the ceiling refuses; an undetectable ceiling checks nothing."""

    def __init__(
        self, staging: Path, sources: Mapping[str, pa.Table] | None, extra: dict[str, Any]
    ) -> None:
        self.outputs: dict[str, pa.Table] = {}
        self.refusal: ResidentFit | None = None
        self._staging = staging
        self._sources = sources or {}
        self._ceiling: int | None = None
        self._held: list[TableBytesSpec] = []
        self._read: list[TableBytesSpec] = []
        self._footers: list[TableBytesSpec] = []
        self._staged = 0
        self.extra = extra

    def run(self, names: list[str]) -> None:
        self._staged = len(names)
        self._held = [_priced(table) for table in self._sources.values()]
        self._ceiling = kill_ceiling()
        self._footers = [self._footer(name) for name in names]
        self._measure()
        for index, name in enumerate(names):
            fit = check_readback(
                [*self._held, *self._read],
                self._footers[index:],
                kill_ceiling_bytes=self._ceiling,
            )
            if fit is not None and fit.verdict == INSUFFICIENT:
                self.refusal = fit
                return
            table = _read_staged(self._staging, name)
            self.outputs[name] = table
            self._read.append(_priced(table))
            self._measure()

    def _measure(self) -> None:
        """Take the figures after each step, inside the guarded readback, so the result that
        reports them allocates nothing after a failure or a publication."""
        figures = Readback(
            kill_ceiling_bytes=self._ceiling,
            sources_bytes=lower_bound_bytes(self._held),
            floor_bytes=lower_bound_bytes(self._footers),
            held_bytes=lower_bound_bytes(self._read),
            tables_read=len(self._read),
            tables_staged=self._staged,
        )
        self.extra["readback"] = asdict(figures)

    def _footer(self, name: str) -> TableBytesSpec:
        """The rows and Arrow schema from the footer alone; nothing is decoded and the file is
        closed again before the table is read."""
        request = _staged_request(self._staging, name)
        with (
            fileaccess.capture().open_read(request) as handle,
            arrow_adapter.parquet_file(handle) as parquet_file,
        ):
            return lazy_spec(
                parquet_file.metadata.num_rows, parquet_file.schema_arrow, charge_pandas=False
            )


def _staged_request(staging: Path, name: str) -> FileRequest:
    return FileRequest(FileRole.TARGET_OUTPUT, "read", str(staging / f"{name}.parquet"), _FIELD_KEY)


def _read_staged(staging: Path, name: str) -> pa.Table:
    """One admitted staged table, read through the file-access choke point."""
    with fileaccess.capture().open_read(_staged_request(staging, name)) as handle:
        return arrow_adapter.read_table(handle)


def result_from_envelope(
    envelope: dict[str, Any],
    pub: Publication | None,
    pid: int,
    staging_output_dir: Path,
    attempt: Attempt,
    discard_scratch_stage: Callable[[], None],
    sources: Mapping[str, pa.Table] | None = None,
) -> IsolatedRunResult:
    """The result of a child that reported an outcome: its failure, or its staged tables read
    back and published. A readback the driver would not survive is a `crashed` result.

    A completed report opens the pre-call window first (`Attempt.enter_readback`); the memory
    boundary around the attempt returns a reserved result if memory runs out before it is built."""
    outcome = envelope["outcome"]
    peak = envelope.get("peak_rss_mb")
    if outcome != "completed":
        return envelope_failure(envelope, pid=pid)

    attempt.enter_readback(pid, peak)
    attempt.extra["readback"] = asdict(Readback(None, 0, 0, 0, 0, 0))
    committed = None if pub is None else str(pub.target)
    row_errors = row_errors_of(envelope)
    collected = collect(envelope, staging_output_dir, pub, attempt, sources)
    # Cleanup evidence below must observe the stage after its owner's removal attempt.
    discard_scratch_stage()
    if isinstance(collected, CommitReceipt):
        # MED-1: a refused stage or a publication that did not commit is a classified result.
        fields = {"peak_rss_mb": peak, "returncode": 0, "isolated": True, "pid": pid}
        return failed_publication(collected, staging_output_dir, **fields)
    if isinstance(collected, ReadbackRefused):
        return readback_refused(
            collected.fit,
            staging=staging_output_dir,
            receipt=collected.receipt,
            extra=collected.extra,
            peak=peak,
            pid=pid,
        )
    if isinstance(collected, ReadbackMemoryFailure):
        return readback_memory_failure(
            staging=staging_output_dir,
            receipt=collected.receipt,
            extra=collected.extra,
            peak=peak,
            pid=pid,
        )
    return IsolatedRunResult(
        outcome="completed",
        peak_rss_mb=peak,
        outputs=collected.outputs,
        quality_metrics=envelope.get("quality_metrics") or {},
        table_kinds=envelope.get("table_kinds") or {},
        returncode=0,
        signal_number=None,
        error=None,
        isolated=True,
        pid=pid,
        committed_output_dir=committed,
        row_errors=row_errors,
        extra=collected.extra,
        publication_receipt=collected.receipt,
    )


def _typed_error(receipt: CommitReceipt) -> BaseException:
    """The typed error a caller raises for this receipt's outcome (`raise_for_outcome`)."""
    try:
        raise_for_outcome(receipt)
    except MemoryError:
        raise
    except Exception as exc:
        return exc
    raise ValueError("a committed receipt is not a failure")


def failed_publication(
    receipt: CommitReceipt, staging: Path | None, **fields: Any
) -> IsolatedRunResult:
    """A classified `crashed` result for a publication that did not commit: safe text, the F29
    reason and the receipt. `staging` is the stage to look at for cleanup evidence, if any."""
    error = _typed_error(receipt)
    if receipt.visible or staging is None:
        state = PublicationState.UNKNOWN if receipt.visible else PublicationState.NOT_PUBLISHED
        cleanup = CleanupState.NOT_NEEDED if receipt.visible else CleanupState.ATTEMPTED
        context = ReasonContext.build(
            operation=Operation.COMMIT,
            storage_ref="output",
            publication_state=state,
            cleanup_state=cleanup,
        )
        reason = reason_from_exception(error, phase=Phase.PUBLISH, context=context)
    else:
        reason = commit_reason(error, staging)
    return IsolatedRunResult(
        outcome="crashed",
        outputs=None,
        quality_metrics={},
        table_kinds={},
        signal_number=None,
        error=commit_error_text(receipt),
        reason=reason,
        publication_receipt=receipt,
        **fields,
    )


def row_errors_of(envelope: dict[str, Any]) -> tuple[RowErrorRecord, ...]:
    """The row errors the worker carried in its envelope (dennis review MED-4).

    Absent (the common case: no row errors this run) or malformed both degrade to an empty
    tuple rather than failing the run: row_errors is additive telemetry, not load-bearing."""
    try:
        return tuple(RowErrorRecord(**item) for item in envelope.get("row_errors") or ())
    except TypeError:
        return ()


def read_envelope(result_path: Path) -> dict[str, Any] | None:
    """Read the worker's result envelope from `result_path` (dennis review HIGH-1).

    Missing (the child died before writing it -- a harder rlimit trip, an
    external SIGKILL) or corrupt (a partial write raced with a kill) both
    return `None` rather than raising, so the caller falls through to
    `classify_abnormal_exit`'s outside classification exactly as it did for
    the old "no parseable last stdout line" case (MED-5's missing/corrupt
    envelope coverage).
    """
    try:
        text = result_path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        envelope = json.loads(text)
    except json.JSONDecodeError:
        return None
    return envelope if isinstance(envelope, dict) else None


def signal_name(signal_number: int | None) -> str | None:
    """`signal.Signals(n).name`, guarded (dennis review LOW-3).

    Real-time signal NUMBERS (e.g. SIGRTMIN+5) are valid `os.kill` targets
    but most have no individual `signal.Signals` enum member -- the
    constructor raises `ValueError` for them. That must not turn a clean
    abnormal-exit classification into an unhandled driver exception; fall
    back to a bare numeric label instead.
    """
    if not signal_number:
        return None
    try:
        return signal.Signals(signal_number).name
    except ValueError:
        return f"signal {signal_number}"
