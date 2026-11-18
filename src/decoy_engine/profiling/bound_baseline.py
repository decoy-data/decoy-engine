"""The bound scan baseline and the drift verdict computed from it.

`scan_baseline.sha256` pins the baseline file's bytes. `bind_baseline` is the one function that
turns those bytes into a `BoundBaseline`: it hashes them, compares the digest with the config,
and only then parses them, so a replaced or reformatted file is refused before any parser sees
it, and the digest and the parse cover the same bytes. `evaluate_drift` takes only a
`BoundBaseline`, so a verdict is never computed from unchecked bytes.

Both refusals (`baseline_digest_mismatch`, `baseline_unreadable`) carry fixed text that names a
config key, never the file path, the bytes, a digest or a parser message, and are raised after
their `except` block closes so nothing chains. The parse is `strict_json_loads`, the engine's one
strict parser, so a duplicate key, a non-finite number or an overflowed literal makes the
baseline unreadable.

A verdict holds table and column names and drift kinds only; no cell value reaches it.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final, Literal

from decoy_engine import reasons
from decoy_engine._canonical import StrictJsonError, strict_json_loads
from decoy_engine.config import OnDrift, PipelineConfigError, ScanBaselineConfig
from decoy_engine.errors import DecoyError
from decoy_engine.profiling.scan_diff import ScanSetDiff, diff_scan_documents
from decoy_engine.profiling.scan_set_read import ScanSetReadError, read_scan_set
from decoy_engine.safe_output import ConfigProblem

__all__ = [
    "BaselineBindingError",
    "BoundBaseline",
    "DriftFinding",
    "DriftVerdict",
    "bind_baseline",
    "evaluate_drift",
]

_TOKEN: Final = object()
_Kind = Literal["digest_mismatch", "unreadable"]
_Status = Literal["passed", "warned", "failed"]

_TEXT: Final[dict[str, str]] = {
    "digest_mismatch": "the scan baseline file does not match scan_baseline.sha256",
    "unreadable": "scan_baseline.path is not a readable scan-set/v1 scan",
}


class BaselineBindingError(DecoyError, ValueError):
    """The baseline file is not the one the config pins, or is not a readable scan.

    `code` is the reason code (`pre_scan.baseline_digest_mismatch` or
    `pre_scan.baseline_unreadable`). The text is fixed.
    """

    def __init__(self, kind: _Kind) -> None:
        super().__init__(_TEXT[kind])
        self.kind: _Kind = kind
        self.code: str = str(
            reasons.pre_scan.BASELINE_DIGEST_MISMATCH
            if kind == "digest_mismatch"
            else reasons.pre_scan.BASELINE_UNREADABLE
        )

    def __reduce__(self) -> tuple[type[BaselineBindingError], tuple[_Kind]]:
        return (type(self), (self.kind,))


@dataclass(frozen=True)
class BoundBaseline:
    """A parsed baseline whose bytes were checked. Only `bind_baseline` builds one.

    `bound` is true when the config pinned a digest and the bytes matched it; an unpinned
    baseline (allowed under `on_drift: warn`) still carries the digest of the bytes read.
    """

    sha256: str
    bound: bool
    on_drift: OnDrift | None
    scan: Mapping[str, Any]
    _token: object

    def __post_init__(self) -> None:
        if self._token is not _TOKEN:
            raise TypeError("BoundBaseline is built by bind_baseline")


def bind_baseline(raw: bytes, block: ScanBaselineConfig) -> BoundBaseline:
    """Hash `raw`, check it against `block.sha256`, then parse it as a `scan-set/v1` core.

    The digest is checked before any parse. A block that asks for `on_drift: fail` without a
    digest (one built past the config validator) is refused first with the config's
    `config/scan_baseline_unbound`. Raises `BaselineBindingError` or `PipelineConfigError`.
    """
    if block.on_drift == "fail" and block.sha256 is None:
        raise PipelineConfigError.from_problems(
            [
                ConfigProblem(
                    str(reasons.config.SCAN_BASELINE_UNBOUND),
                    "scan_baseline.sha256",
                    "scan_baseline.on_drift: fail needs scan_baseline.sha256.",
                )
            ],
            prefix="scan baseline is not bound",
        )
    digest = hashlib.sha256(raw).hexdigest()
    if block.sha256 is not None and digest != block.sha256:
        raise BaselineBindingError("digest_mismatch")
    scan: dict[str, Any] | None = None
    try:
        scan = read_scan_set(strict_json_loads(raw))
    except (StrictJsonError, ScanSetReadError):
        scan = None
    if scan is None:
        raise BaselineBindingError("unreadable")
    return BoundBaseline(
        sha256=digest,
        bound=block.sha256 is not None,
        on_drift=block.on_drift,
        scan=MappingProxyType(scan),
        _token=_TOKEN,
    )


@dataclass(frozen=True)
class DriftFinding:
    """One drifted item. `table` is `None` only for `no_common_table`; `column` is `None` for a
    table-level kind (`table_added`, `new_quasi_identifier_group`)."""

    table: str | None
    column: str | None
    kind: str


@dataclass(frozen=True)
class DriftVerdict:
    """The outcome of comparing a bound baseline with a fresh scan.

    `passed`: no drift. `warned`: drift under `warn` (code `pre_scan.drift_detected`).
    `failed`: drift under `fail` (code `pre_scan.drift_blocked`). `findings` is sorted by
    (table, column, kind); `drifted_tables` groups the findings that name a table.
    """

    status: _Status
    findings: tuple[DriftFinding, ...]
    drifted_tables: Mapping[str, tuple[DriftFinding, ...]]
    diff: ScanSetDiff
    baseline_sha256: str
    bound: bool

    @property
    def code(self) -> str | None:
        """The reason code of a drifted verdict, derived from `status` so the two cannot differ."""
        if self.status == "failed":
            return str(reasons.pre_scan.DRIFT_BLOCKED)
        if self.status == "warned":
            return str(reasons.pre_scan.DRIFT_DETECTED)
        return None


def _sort_key(finding: DriftFinding) -> tuple[str, str, str]:
    return (finding.table or "", finding.column or "", finding.kind)


def _findings(diff: ScanSetDiff) -> tuple[DriftFinding, ...]:
    found: list[DriftFinding] = []
    if diff.no_common_table:
        found.append(DriftFinding(None, None, "no_common_table"))
    found.extend(DriftFinding(name, None, "table_added") for name in diff.tables_added)
    for table in diff.tables:
        found.extend(
            DriftFinding(table.table, row.name, "pii_bucket_increased")
            for row in table.pii_increased
        )
        found.extend(
            DriftFinding(table.table, row.name, "new_high_pii_field") for row in table.new_high_pii
        )
        found.extend(
            DriftFinding(table.table, None, "new_quasi_identifier_group") for _ in table.qi_added
        )
    return tuple(sorted(found, key=_sort_key))


def evaluate_drift(bound: BoundBaseline, current: Mapping[str, Any]) -> DriftVerdict:
    """Compare the bound baseline with `current` (a `scan-set/v1` core) and decide.

    A baseline with no `on_drift` set is reported (`warned`), never refused.
    """
    diff = diff_scan_documents(bound.scan, current)
    findings = _findings(diff)
    grouped: dict[str, list[DriftFinding]] = {}
    for finding in findings:
        if finding.table is not None:
            grouped.setdefault(finding.table, []).append(finding)
    status: _Status
    if not diff.drift:
        status = "passed"
    elif bound.on_drift == "fail":
        status = "failed"
    else:
        status = "warned"
    return DriftVerdict(
        status=status,
        findings=findings,
        drifted_tables=MappingProxyType({t: tuple(f) for t, f in grouped.items()}),
        diff=diff,
        baseline_sha256=bound.sha256,
        bound=bound.bound,
    )
