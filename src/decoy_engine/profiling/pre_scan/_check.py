"""The pre-scan coverage verdict: which flagged source columns does the pipeline leave unmasked.

`evaluate_pre_scan` takes a validated config dict and a `scan-set/v1` core (value-free) and
decides one thing. A source column is flagged when its `pii_candidate` is set, or when a model
detector named in `pre_scan.detectors` gave it a `high` band hit (`review` hits are not flagged).
A flagged column is covered when its column rule has a strategy other than `passthrough` and no
`when:` gate. Rows where `when` is false pass through unchanged, so a gated rule is partial
coverage and the column is a finding with `partial` set. A mask table the core does not hold is a
`not_scanned` finding (fail closed). Generate tables have no source and are not scanned.

A verdict, its `Check` and the two errors hold table names, column names and detector source
names only. No cell value reaches them: the core carries none, and nothing here copies a field
sample.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, Literal, NamedTuple

from decoy_engine import reasons
from decoy_engine.config import PreScanConfig, classify_table_kinds, final_bindings, parse_ops
from decoy_engine.errors import DecoyError
from decoy_engine.run_result import Check, CheckCounts

__all__ = [
    "PreScanBlockedError",
    "PreScanFailedError",
    "PreScanFinding",
    "PreScanVerdict",
    "PreScanWarning",
    "evaluate_pre_scan",
]

PreScanStatus = Literal["passed", "warned", "failed"]

# The catalog name of the unmasked strategy (`support._shape.StrategyKind.PASSTHROUGH`). `support`
# sits above `profiling` in the import layers, so the name is held here and a test pins it to the
# catalog value.
_PASSTHROUGH: Final = "passthrough"
_NOT_SCANNED: Final = "not_scanned"
_HIGH: Final = "high"


class PreScanFinding(NamedTuple):
    """One uncovered column. `column` is empty and `sources` is `("not_scanned",)` for a mask
    table the core does not hold. `partial` is set when a `when:` gate covers only some rows."""

    table: str
    column: str
    sources: tuple[str, ...]
    partial: bool


@dataclass(frozen=True)
class PreScanVerdict:
    """The outcome of the coverage rule. `findings` is sorted by (table, column).

    `detectors` is the effective detector set (sorted, `regex` always present) and
    `tables_scanned` the sorted mask tables the core held, both set on every verdict.
    `covered` counts flagged columns the pipeline masks.
    """

    status: PreScanStatus
    findings: tuple[PreScanFinding, ...]
    covered: int
    detectors: tuple[str, ...]
    tables_scanned: tuple[str, ...]

    @property
    def code(self) -> str | None:
        """The reason code, derived from `status` so the two cannot differ."""
        if self.status == "failed":
            return str(reasons.pre_scan.UNCOVERED_PII_BLOCKED)
        if self.status == "warned":
            return str(reasons.pre_scan.UNCOVERED_PII)
        return None

    @property
    def blocking(self) -> bool:
        return self.status == "failed"

    @property
    def counts(self) -> CheckCounts:
        uncovered = len(self.findings)
        return CheckCounts(
            **{
                "pass": self.covered,
                "warning": uncovered if self.status == "warned" else 0,
                "fail": uncovered if self.status == "failed" else 0,
                "error": 0,
            }
        )

    def to_check(self) -> Check:
        """The run result check `pre_scan`: status, counts and the code, no names."""
        code = self.code
        return Check(
            id="pre_scan",
            status=self.status,
            blocking=self.blocking,
            counts=self.counts,
            codes=() if code is None else (code,),
        )


class PreScanWarning(DecoyError, UserWarning):  # noqa: N818 - the plan names it a warning
    """The pre-scan flagged unmasked columns under `on_findings: warn`.

    A `DecoyError` too, because the exception-taxonomy sentry bars an engine exception class
    outside that base; callers filter it as a `UserWarning`. `code` is `pre_scan.uncovered_pii`."""

    def __init__(self, *args: object) -> None:
        super().__init__(*args)
        self.code: str = str(reasons.pre_scan.UNCOVERED_PII)


class PreScanBlockedError(DecoyError, ValueError):
    """The pre-scan flagged unmasked columns under `on_findings: fail`, so the run stopped.

    Carries the verdict (names only). `code` is `pre_scan.uncovered_pii_blocked`; the text is
    fixed.
    """

    def __init__(self, verdict: PreScanVerdict) -> None:
        super().__init__("the pre-scan flagged source columns that the pipeline leaves unmasked")
        self.verdict = verdict
        self.code: str = str(reasons.pre_scan.UNCOVERED_PII_BLOCKED)

    def __reduce__(self) -> tuple[type[PreScanBlockedError], tuple[PreScanVerdict]]:
        return (type(self), (self.verdict,))


class PreScanFailedError(DecoyError, RuntimeError):
    """The run-start scan raised before it produced a core. `code` is `pre_scan.profile_failed`;
    the text is fixed and the cause is not chained."""

    def __init__(self) -> None:
        super().__init__("the pre-scan did not complete")
        self.code: str = str(reasons.pre_scan.PROFILE_FAILED)

    def __reduce__(self) -> tuple[type[PreScanFailedError], tuple[()]]:
        return (type(self), ())


def _effective_detectors(policy: Mapping[str, Any]) -> tuple[str, ...]:
    # The config model owns "regex is always on"; the sort keeps `PreScanVerdict.detectors` sorted.
    return tuple(sorted(PreScanConfig(detectors=tuple(policy.get("detectors") or ())).detectors))


def _gated(rule: Mapping[str, Any]) -> bool:
    when = rule.get("when")
    return isinstance(when, str) and when.strip() != ""


def _output_names(table: Mapping[str, Any], scan: Mapping[str, Any]) -> frozenset[str]:
    """Column names in the table output: the scanned source names after the ordered transforms."""
    ops = parse_ops(table.get("transforms") or [])
    source = [f["name"] for f in scan.get("fields") or ()]
    return frozenset(name for name, _ in final_bindings(source, ops))


def _flag_sources(field: Mapping[str, Any], detectors: tuple[str, ...]) -> tuple[str, ...]:
    found: set[str] = set()
    if field.get("pii_candidate") is True:
        found.add("regex")
    for hit in field.get("model_hits") or ():
        source = hit.get("source")
        if hit.get("band") == _HIGH and source in detectors:
            found.add(str(source))
    return tuple(sorted(found))


def evaluate_pre_scan(config: Mapping[str, Any], core: Mapping[str, Any]) -> PreScanVerdict:
    """Apply the coverage rule to `config` against the scan `core` and decide.

    `pre_scan.on_findings` picks the status of an uncovered result: `warn` (the default) gives
    `warned`, `fail` gives `failed`. Nothing uncovered gives `passed`.
    """
    policy = config.get("pre_scan", {})
    if not isinstance(policy, Mapping):
        # A policy read as empty would turn `fail` into `warn`, so a bad shape is refused.
        raise TypeError("pre_scan must be a mapping")
    detectors = _effective_detectors(policy)
    core_tables = {t["name"]: t for t in core.get("tables") or ()}
    findings: list[PreScanFinding] = []
    covered = 0
    scanned: list[str] = []
    kinds = classify_table_kinds(dict(config))
    for table in config.get("tables") or ():
        if kinds.get(table["name"]) != "mask":
            continue
        name = table["name"]
        scan = core_tables.get(name)
        if scan is None:
            findings.append(PreScanFinding(name, "", (_NOT_SCANNED,), False))
            continue
        scanned.append(name)
        rules = {c["name"]: c for c in table.get("columns") or ()}
        output = _output_names(table, scan)
        for field in scan.get("fields") or ():
            sources = _flag_sources(field, detectors)
            if not sources or field["name"] not in output:
                continue
            rule = rules.get(field["name"])
            if rule is None or rule.get("strategy") == _PASSTHROUGH:
                findings.append(PreScanFinding(name, field["name"], sources, False))
            elif _gated(rule):
                findings.append(PreScanFinding(name, field["name"], sources, True))
            else:
                covered += 1
    status: PreScanStatus = "passed"
    if findings:
        status = "failed" if policy.get("on_findings") == "fail" else "warned"
    return PreScanVerdict(
        status=status,
        findings=tuple(sorted(findings, key=lambda f: (f.table, f.column))),
        covered=covered,
        detectors=detectors,
        tables_scanned=tuple(sorted(scanned)),
    )
