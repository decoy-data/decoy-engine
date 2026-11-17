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
from decoy_engine.profiling._starter_inference import StarterDecision, infer_starter_strategy
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
_CHECK_NAMESPACE = "starter-check"
_TARGETS: TypeAdapter[dict[str, TargetDescriptor]] = TypeAdapter(dict[str, TargetDescriptor])
_UNSAFE_NAME = re.compile(r"[^A-Za-z0-9._-]")

_KEY_NOTE = (
    "Key column of a declared relationship. hash with one namespace keeps the join after "
    "masking; the scan suggested {suggested}."
)
_PLACEHOLDER_NOTE = (
    "Set the same namespace on the relationship and on every key column of it before "
    "running; `decoy validate` refuses the placeholder."
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
    built, and `live` says it was written into the config. Only a regex suggestion is live.
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

    def __post_init__(self) -> None:
        # `strategy`, `namespace` and `entry` describe one choice; a confirm matches on one and
        # applies another, so they must agree. Only a regex suggestion is written into the config.
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
    targets: Mapping[str, dict[str, Any]] | None = None,
    seed: int = 42,
    relationships: Sequence[Mapping[str, Any]] = (),
) -> StarterConfig:
    """Build a starter pipeline config for the tables of `scan`.

    `relationships` are the user's declared `RelationshipConfig` dicts, copied unchanged; the
    scan does not carry them. `targets` maps a table to a full target descriptor that replaces
    the default. A placeholder namespace is written where a declared relationship names none.
    """
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
            suggestion = _suggestion(table.name, stats.name, decision, key)
            suggestions.append(suggestion)
            columns.append(dict(suggestion.entry))
            notes[(table.name, stats.name)] = _note(table, stats.name, decision, key)
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


def _suggestion(
    table: str, column: str, decision: StarterDecision, key: tuple[str, bool] | None
) -> ColumnSuggestion:
    if key is not None:
        bare = ColumnSuggestion(table, column, _KEY_STRATEGY, namespace=key[0], is_key=True)
        return dataclasses.replace(bare, entry=MappingProxyType(_entry(bare)))
    bare = ColumnSuggestion(
        table,
        column,
        decision.strategy,
        provider=decision.provider,
        provider_config=decision.provider_config,
        deterministic=decision.deterministic,
        detector_id=decision.detector_id,
        confidence_bucket=decision.confidence_bucket,
    )
    named = dataclasses.replace(bare, namespace=column) if _needs_namespace(bare) else bare
    return dataclasses.replace(named, entry=MappingProxyType(_entry(named)))


def detector_entry(detector_id: str, column: str) -> dict[str, Any] | None:
    """The column entry the starter writes for a column `detector_id` flagged, or None.

    None when the detector has no starter choice. The namespace follows the same registry rule
    as `starter_config`, so a review that takes a detector's default writes what a scan would.
    """
    choice = recommendations.starter_choice(detector_id)
    if choice is None:
        return None
    bare = ColumnSuggestion(
        "",
        column,
        choice.strategy,
        provider=choice.provider,
        provider_config=choice.provider_config,
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
    column: str,
    decision: StarterDecision,
    key: tuple[str, bool] | None,
) -> str:
    if key is None:
        parts = [decision.review]
    else:
        parts = [_KEY_NOTE.format(suggested=decision.strategy)]
        if key[1]:
            parts.append(_PLACEHOLDER_NOTE)
    zeros = table.leading_zero_counts.get(column)
    if zeros:
        parts.append(_LEADING_ZERO_NOTE.format(count=zeros))
    return " ".join(p for p in parts if p)


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
