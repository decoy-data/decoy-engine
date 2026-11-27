"""`starter_config`: one scan over many tables becomes one starter pipeline config.

Modeled on the CLI's `decoy init` scaffold (scan, suggest per column, leave each judgment
to a REVIEW note) generalized to many tables. Foreign keys are never inferred. A declared
relationship's key columns all hash under one shared namespace, the keyed-pseudonym join rule
of SDV's HMA1 (same key in, same token out across tables) and of the namespace registry's
same-FK same-mask check. The per-column decision is `_starter_inference`'s; this module reads
the descriptors and holds no detector table.

The builder validates the config it returns (`PipelineConfig`) and the shape of each declared
relationship. It does not run `compile_plan`: `plan` sits above `profiling` in the import layers,
so the compile check lives in the tests and in the CLI. Which strategies need a namespace comes
from the shared requirement registry, never a list kept here. Output carries detector ids, strategy names, counts and fixed copy, never a cell value.
"""

from __future__ import annotations

import copy
import dataclasses
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

from pydantic import TypeAdapter, ValidationError

from decoy_engine import reasons
from decoy_engine.config import (
    NAMESPACE_PLACEHOLDER_PREFIX,
    PipelineConfig,
    PipelineConfigError,
    TargetDescriptor,
    duplicate_target_groups,
    parse_pipeline_config,
    relationship_shape_error,
)
from decoy_engine.contracts.strategy_requirements import requirement_applies, requirements_for
from decoy_engine.detection.types import DetectorSource, ModelRef
from decoy_engine.profiling import recommendations
from decoy_engine.profiling._model_pass import ModelHit
from decoy_engine.profiling._starter_inference import (
    StarterDecision,
    confident_matches,
    detected_date_config,
    infer_starter_strategy,
)
from decoy_engine.profiling.scan_set import SCAN_SET_SCHEMA, ScanSet, TableScan
from decoy_engine.safe_output import ConfigProblem

__all__ = [
    "ColumnSuggestion",
    "StarterConfig",
    "build_entry",
    "check_starter_config",
    "declared_key_namespaces",
    "detector_entry",
    "starter_config",
    "swap_placeholder_namespaces",
]

_KEY_STRATEGY = "hash"
_DATE_FALLBACK_STRATEGY = "redact"
_CHECK_NAMESPACE = "starter-check"
_TARGETS: TypeAdapter[dict[str, TargetDescriptor]] = TypeAdapter(dict[str, TargetDescriptor])
_UNSAFE_NAME = re.compile(r"[^A-Za-z0-9._-]")
# A note is one line: model and detector ids come from a pack file, so any control character in
# one is folded to a space before it can reach a YAML comment or a `.decoy` note.
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")

_KEY_NOTE = (
    "Key column of a declared relationship. hash with one namespace keeps the join after "
    "masking; the scan suggested {suggested}."
)
_PLACEHOLDER_NOTE = (
    "Set the same namespace on the relationship and on every key column of it before "
    "running; `decoy validate` refuses the placeholder."
)
_DATE_NO_FORMAT_NOTE = (
    "A model read this column as a date, but the scan found no single complete date format, so "
    "it stays redact until you choose one."
)
_LEADING_ZERO_NOTE = (
    "{count} sampled values in this column start with 0. The scan read it as a number, but "
    "`decoy run` reads CSV as text, so check that the strategy keeps leading zeros."
)
_CLOUD_NOTE = (
    "`decoy run` does not read or write S3 or GCS until the CLI-CLOUD row lands. The target "
    "is a local masked/ directory next to this file."
)


def _empty_entry() -> Mapping[str, Any]:
    return MappingProxyType({})


@dataclass(frozen=True)
class ColumnSuggestion:
    """What the starter writes for one column, before it becomes a config entry.

    Identity is `(table, column, source, detector_id)`; `detector_id` is empty when no detector
    decided (the fallback, or the integer-key rule). `model` and `band` are for a classifier
    suggestion and stay `None` for a regex one. `entry` is the column entry `starter_config`
    built; every entry is written to the config. `live` says a deterministic rule decided it
    (regex, declared key, integer-unique hash, fallback), and is false when a model chose the
    entry. Only a suggestion with `source == "regex"` is live, which every deterministic rule
    uses. `decided_by` names the rule.
    """

    table: str
    column: str
    strategy: str
    provider: str | None = None
    provider_config: Mapping[str, Any] = field(default_factory=_empty_entry)
    namespace: str | None = None
    deterministic: bool = False
    is_key: bool = False
    source: DetectorSource = "regex"
    detector_id: str = ""
    model: ModelRef | None = None
    band: Literal["high", "review"] | None = None
    confidence_bucket: str | None = None
    entry: Mapping[str, Any] = field(default_factory=_empty_entry)
    live: bool = True

    @property
    def decided_by(
        self,
    ) -> Literal["declared_key", "regex", "classifier", "integer_key", "fallback"]:
        if self.is_key:
            return "declared_key"
        if self.source == "classifier":
            return "classifier"
        if self.detector_id:
            return "regex"
        return "integer_key" if self.strategy == _KEY_STRATEGY else "fallback"

    def __post_init__(self) -> None:
        # `strategy`, `namespace` and `entry` describe one choice; a confirm matches on one and
        # applies another, so they must agree. Regex and classifier suggestions are both written.
        if self.live and self.source != "regex":
            raise ValueError("only a regex suggestion can be live")
        if self.entry and (
            self.entry.get("name") != self.column
            or self.entry.get("strategy") != self.strategy
            or self.entry.get("namespace") != self.namespace
        ):
            raise ValueError(
                "the suggestion's entry disagrees with its column, strategy or namespace"
            )


@dataclass(frozen=True)
class StarterConfig:
    """The starter pipeline and the copy that explains it.

    `notes` maps `(table, column)` to REVIEW text. The key `(table, "")` holds a note about the
    table's source and target (the cloud note).
    """

    config: dict[str, Any]
    notes: Mapping[tuple[str, str], str]
    suggestions: tuple[ColumnSuggestion, ...]
    relationship_template: tuple[str, ...]


def starter_config(
    scan: ScanSet,
    *,
    baseline_path: str | None = None,
    baseline_sha256: str | None = None,
    targets: Mapping[str, dict[str, Any]] | None = None,
    seed: int = 42,
    relationships: Sequence[Mapping[str, Any]] = (),
) -> StarterConfig:
    """Build a starter pipeline config for the tables of `scan`.

    `relationships` are the user's declared `RelationshipConfig` dicts, copied unchanged; the
    scan does not carry them. `targets` maps a table to a full target descriptor that replaces
    the default. A placeholder namespace is written where a declared relationship names none.
    """
    if baseline_sha256 is not None and baseline_path is None:
        raise ValueError("baseline_sha256 needs baseline_path")
    _refuse_header_suspect(scan)
    _check_relationship_shapes(scan, relationships)
    keys = declared_key_namespaces(relationships)
    allocated = _allocate_targets(scan, targets or {})
    suggestions: list[ColumnSuggestion] = []
    notes: dict[tuple[str, str], str] = {}
    sources: dict[str, Any] = {}
    tables: list[dict[str, Any]] = []
    for table in scan.tables:
        sources[table.name] = copy.deepcopy(table.descriptor)
        if table.descriptor["type"] != "file":
            notes[(table.name, "")] = _CLOUD_NOTE
        columns = []
        for stats in table.profile.fields:
            decision = infer_starter_strategy(stats)
            key = keys.get((table.name, stats.name))
            hits = table.model_hits.get(stats.name, ())
            suggestion, lead = _decide(table.name, stats, decision, key, hits)
            suggestions.append(suggestion)
            columns.append(dict(suggestion.entry))
            notes[(table.name, stats.name)] = _note(table, stats, lead, key, hits)
        tables.append({"name": table.name, "columns": columns})

    config: dict[str, Any] = {
        "version": 2,
        "global_settings": {"seed": seed},
        "sources": sources,
        "tables": tables,
        "relationships": copy.deepcopy([dict(r) for r in relationships]),
        "targets": allocated,
    }
    if baseline_path is not None:
        config["scan_baseline"] = {"path": baseline_path, "schema": SCAN_SET_SCHEMA}
        if baseline_sha256 is not None:
            config["scan_baseline"]["sha256"] = baseline_sha256
    _refuse_shared_destinations(allocated, [t["name"] for t in tables])
    check_starter_config(config)
    return StarterConfig(
        config=config,
        notes=MappingProxyType(notes),
        suggestions=tuple(suggestions),
        relationship_template=tuple(t.name for t in scan.tables),
    )


def declared_key_namespaces(
    relationships: Sequence[Mapping[str, Any]],
) -> dict[tuple[str, str], tuple[str, bool]]:
    """(table, column) -> (namespace, is_placeholder) for every declared key column."""
    found: dict[tuple[str, str], tuple[str, bool]] = {}
    for position, rel in enumerate(relationships, start=1):
        declared = rel.get("namespace")
        placeholder = declared is None
        namespace = f"{NAMESPACE_PLACEHOLDER_PREFIX}{position}" if placeholder else str(declared)
        ends = [rel["parent"], *rel["children"]]
        for end in ends:
            for column in end["columns"]:
                slot = (end["table"], column)
                if slot in found and found[slot][0] != namespace:
                    raise PipelineConfigError.from_problems(
                        [
                            ConfigProblem(
                                str(reasons.config.NAMESPACE_AMBIGUITY),
                                f"relationships[{position - 1}]",
                                "A key column is named by two relationships with different "
                                "namespaces.",
                            )
                        ],
                        prefix="starter config input is invalid",
                    )
                found[slot] = (namespace, placeholder)
    return found


def _refuse_header_suspect(scan: ScanSet) -> None:
    """Refuse a scan whose first row the scan guard read as data: its column names may be values.

    The message names no table, column or path; the location is the table's position.
    """
    flagged = reasons.warning.SCAN_HEADER_SUSPECT.spec.ref
    problems = [
        ConfigProblem(
            str(reasons.config.STARTER_HEADER_SUSPECT),
            f"tables[{position}]",
            reasons.config.STARTER_HEADER_SUSPECT.spec.summary,
        )
        for position, table in enumerate(scan.tables)
        if flagged in table.warnings
    ]
    if problems:
        raise PipelineConfigError.from_problems(problems, prefix="starter config input is invalid")


def _decide(
    table: str,
    stats: Any,
    decision: StarterDecision,
    key: tuple[str, bool] | None,
    hits: Sequence[ModelHit],
) -> tuple[ColumnSuggestion, str]:
    """The suggestion for one column and the lead sentence of its note.

    Order: a declared key, then a confident regex match, then the first high-band classifier hit
    whose detector has a starter entry, then the regex fallback. NER hits and review-band hits
    add evidence to the note only.
    """
    if key is not None:
        bare = ColumnSuggestion(table, stats.name, _KEY_STRATEGY, namespace=key[0], is_key=True)
        lead = _KEY_NOTE.format(suggested=decision.strategy)
        return dataclasses.replace(bare, entry=MappingProxyType(_entry(bare))), lead
    if not confident_matches(stats):
        for hit in hits:
            chosen = _classifier_suggestion(table, stats, hit)
            if chosen is not None:
                return chosen
    bare = ColumnSuggestion(
        table,
        stats.name,
        decision.strategy,
        provider=decision.provider,
        provider_config=decision.provider_config,
        deterministic=decision.deterministic,
        detector_id=decision.detector_id,
        confidence_bucket=decision.confidence_bucket,
    )
    named = dataclasses.replace(bare, namespace=stats.name) if _needs_namespace(bare) else bare
    return dataclasses.replace(named, entry=MappingProxyType(_entry(named))), decision.review


def _classifier_suggestion(
    table: str, stats: Any, hit: ModelHit
) -> tuple[ColumnSuggestion, str] | None:
    """The suggestion a high-band classifier hit writes, or None when it writes nothing.

    `hit.detector_id` is already the detector the label maps to (`_model_pass`), so it is used as
    it is. A date detector needs a complete format from a regex match of the same detector, so
    a column the scan could not read as one format stays `redact`.
    """
    if hit.source != "classifier" or hit.band != "high":
        return None
    choice = recommendations.starter_choice(hit.detector_id)
    if choice is None:
        return None
    date_format = _complete_date_format(stats, hit.detector_id, choice)
    if choice.detected_date_format and date_format is None:
        # The hit says date but the scan read no complete format. Falling through would let the
        # inferred strategy decide, and a likely-unique integer column would become `hash`.
        entry: dict[str, Any] | None = build_entry(_DATE_FALLBACK_STRATEGY, stats.name)
        note = _DATE_NO_FORMAT_NOTE
    else:
        entry = detector_entry(hit.detector_id, stats.name, date_format=date_format)
        note = choice.review
    if entry is None:
        return None
    suggestion = ColumnSuggestion(
        table,
        stats.name,
        entry["strategy"],
        provider=entry.get("provider"),
        provider_config=MappingProxyType(entry.get("provider_config", {})),
        namespace=entry.get("namespace"),
        source="classifier",
        detector_id=hit.detector_id,
        model=hit.model,
        band="high",
        entry=MappingProxyType(entry),
        live=False,
    )
    return suggestion, note


def _complete_date_format(
    stats: Any, detector_id: str, choice: recommendations.StarterChoice
) -> str | None:
    """The date format a regex match of `detector_id` read completely, or None."""
    if not choice.detected_date_format:
        return None
    for match in getattr(stats, "detector_matches", None) or []:
        if getattr(match, "detector_id", "") != detector_id:
            continue
        config = detected_date_config(choice, match)
        if config is not None:
            return str(config["date_format"])
    return None


def detector_entry(
    detector_id: str, column: str, *, date_format: str | None = None
) -> dict[str, Any] | None:
    """The column entry the starter writes for a column `detector_id` flagged, or None.

    None when the detector has no starter choice, or when its choice needs the detected date
    format and `date_format` is not given: the descriptor holds no format, so it never builds a
    `date_shift` the plan would refuse. The namespace follows the same registry rule as
    `starter_config`, so a review that takes a detector's default writes what a scan would.
    """
    choice = recommendations.starter_choice(detector_id)
    if choice is None:
        return None
    provider_config: Mapping[str, Any] = choice.provider_config
    if choice.detected_date_format:
        if not isinstance(date_format, str) or not date_format.strip():
            return None
        provider_config = {**provider_config, "date_format": date_format}
    bare = ColumnSuggestion(
        "",
        column,
        choice.strategy,
        provider=choice.provider,
        provider_config=provider_config,
    )
    return _entry(dataclasses.replace(bare, namespace=column) if _needs_namespace(bare) else bare)


def _needs_namespace(s: ColumnSuggestion) -> bool:
    """Whether the registry requires a namespace on the entry this suggestion becomes."""
    entry = _entry(s)
    return any(
        req.path == ("namespace",) and requirement_applies(req, entry)
        for req in requirements_for(s.strategy)
    )


def build_entry(
    strategy: str,
    column: str,
    *,
    column_fields: Mapping[str, Any] | None = None,
    provider_config: Mapping[str, Any] | None = None,
    namespace: str | None = None,
) -> dict[str, Any]:
    """The one writer of a column entry's shape and key order.

    `column_fields` are the top-level `ColumnConfig` members (`provider`, `deterministic`),
    `provider_config` the free-form mapping. It checks nothing about the strategy: the starter
    passes the settings a detector descriptor chose, and `column_entry` (the review's entry
    point) checks the settings an operator typed against the strategy catalog before calling it.
    """
    fields = dict(column_fields or {})
    entry: dict[str, Any] = {"name": column, "strategy": strategy}
    if fields.get("provider"):
        entry["provider"] = fields.pop("provider")
    else:
        fields.pop("provider", None)
    if namespace is not None:
        entry["namespace"] = namespace
    if provider_config:
        entry["provider_config"] = copy.deepcopy(dict(provider_config))
    for name, value in fields.items():
        entry[name] = value
    return entry


def _entry(s: ColumnSuggestion) -> dict[str, Any]:
    return build_entry(
        s.strategy,
        s.column,
        column_fields={
            "provider": s.provider,
            **({"deterministic": True} if s.deterministic else {}),
        },
        provider_config=s.provider_config,
        namespace=s.namespace,
    )


def _note(
    table: TableScan,
    stats: Any,
    lead: str,
    key: tuple[str, bool] | None,
    hits: Sequence[ModelHit],
) -> str:
    parts = [lead]
    evidence = _evidence(stats, hits, declared_key=key is not None)
    if evidence:
        parts.append(f"Model evidence: {evidence}.")
    if key is not None and key[1]:
        parts.append(_PLACEHOLDER_NOTE)
    zeros = table.leading_zero_counts.get(stats.name)
    if zeros:
        parts.append(_LEADING_ZERO_NOTE.format(count=zeros))
    return " ".join(p for p in parts if p)


def _evidence(stats: Any, hits: Sequence[ModelHit], *, declared_key: bool = False) -> str:
    """One line naming each model hit: ids, versions, bands and buckets, never a value.

    A hit that names a detector other than the confident regex match says the regex was kept,
    except on a declared key, where the declaration decided and the line only lists both views.
    """
    confident = confident_matches(stats)
    regex_id = getattr(confident[0], "detector_id", "") if confident else ""
    parts = []
    for hit in hits:
        qualifier = f"band {hit.band}" if hit.source == "classifier" else f"rate {hit.rate_bucket}"
        model = f"{hit.source} {hit.model.id} {hit.model.version}"
        if regex_id and hit.detector_id != regex_id and declared_key:
            parts.append(f"{model} says {hit.detector_id} ({qualifier}), regex says {regex_id}")
        elif regex_id and hit.detector_id != regex_id:
            parts.append(
                f"{model} says {hit.detector_id} ({qualifier}), regex says {regex_id}; regex kept"
            )
        else:
            parts.append(f"{model}: {hit.detector_id} ({qualifier})")
    return " ".join(_CONTROL.sub(" ", "; ".join(parts)).split())


def _check_relationship_shapes(scan: ScanSet, relationships: Sequence[Mapping[str, Any]]) -> None:
    columns = {t.name: [f.name for f in t.profile.fields] for t in scan.tables}
    for position, rel in enumerate(relationships):
        found = relationship_shape_error(rel, columns)
        if found is not None:
            code, path = found
            raise PipelineConfigError.from_problems(
                [
                    ConfigProblem(
                        code,
                        f"relationships[{position}]",
                        f"A declared relationship does not fit the scanned tables ({path}).",
                    )
                ],
                prefix="starter config input is invalid",
            )


def _allocate_targets(scan: ScanSet, given: Mapping[str, Any]) -> dict[str, Any]:
    """The one place a target path is made. Raises ValueError (names only) on a bad input."""
    readers: dict[str, int] = {}
    for table in scan.tables:
        if table.descriptor["type"] == "file":
            readers[table.descriptor["path"]] = readers.get(table.descriptor["path"], 0) + 1
    out: dict[str, Any] = {}
    used_dirs: set[str] = set()
    for table in scan.tables:
        name = table.name
        if name in given:
            explicit = given[name]
            if not isinstance(explicit, Mapping) or not explicit:
                raise ValueError(f"the target given for table {name!r} is empty or not a mapping")
            out[name] = copy.deepcopy(dict(explicit))
        else:
            shared = table.descriptor["type"] == "file" and readers[table.descriptor["path"]] > 1
            out[name] = _default_target(table, used_dirs, shared)
    return out


def _default_target(table: TableScan, used_dirs: set[str], shared: bool) -> dict[str, Any]:
    descriptor = table.descriptor
    target: dict[str, Any] = {"type": "file", "format": descriptor["format"]}
    if descriptor["type"] == "file":
        path = Path(descriptor["path"])
        middle = f".{_UNSAFE_NAME.sub('_', table.name)}" if shared else ""
        target["path"] = str(path.with_name(f"{path.stem}{middle}.masked{path.suffix}"))
        if descriptor.get("layout"):
            target["layout"] = copy.deepcopy(descriptor["layout"])
    else:
        # Cloud inputs are written to a local folder; two table names must not share a file.
        base = _UNSAFE_NAME.sub("_", table.name)
        name, n = base, 1
        while name in used_dirs:
            n += 1
            name = f"{base}-{n}"
        used_dirs.add(name)
        target["path"] = f"masked/{name}.{descriptor['format']}"
    return target


def _problems_of(raw: dict[str, Any]) -> tuple[ConfigProblem, ...] | None:
    """The value-free problems `raw` fails with, or None when it validates."""
    try:
        parse_pipeline_config(raw)
    except PipelineConfigError as err:
        return err.problems
    return None


def _refuse_shared_destinations(targets: Mapping[str, Any], table_names: Sequence[str]) -> None:
    """Refuse two tables writing one destination before the full validation reports it generically."""
    try:
        validated = _TARGETS.validate_python(dict(targets))
    except ValidationError:
        return  # a malformed target is reported by `_check`
    groups = duplicate_target_groups(validated, table_names)
    if groups:
        first, second = groups[0][:2]
        raise ValueError(f"tables {first!r} and {second!r} share one target destination")


def swap_placeholder_namespaces(config: dict[str, Any]) -> tuple[dict[str, Any], int]:
    """A copy of `config` with every placeholder namespace set to a real one, and how many."""
    swapped = copy.deepcopy(config)
    placeholders = 0
    for table in swapped["tables"]:
        for column in table["columns"]:
            if str(column.get("namespace", "")).startswith(NAMESPACE_PLACEHOLDER_PREFIX):
                column["namespace"] = _CHECK_NAMESPACE
                placeholders += 1
    return swapped, placeholders


def check_starter_config(config: dict[str, Any]) -> PipelineConfig:
    """Validate the config; a placeholder must be the only thing that fails it.

    A failure here is a builder bug, so the error names codes and locations, never values.
    """
    expected = str(reasons.config.NAMESPACE_PLACEHOLDER_UNSET)
    swapped, placeholders = swap_placeholder_namespaces(config)
    failed = _problems_of(swapped)
    if failed is not None:
        raise PipelineConfigError.from_problems(failed, prefix="starter config failed validation")
    validated = parse_pipeline_config(swapped)
    if not placeholders:
        return validated
    problems = _problems_of(config)
    if problems is None:
        raise PipelineConfigError("starter config accepted a placeholder namespace")
    if problems and all(p.code == expected for p in problems):
        return validated
    raise PipelineConfigError.from_problems(problems, prefix="starter config failed validation")
