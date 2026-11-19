"""Pre-scan review of a starter config: one column-entry writer and one fold of the verdicts.

`starter_config` writes a config and one suggestion per column. A front end (the `decoy init`
wizard) shows each suggestion and collects a verdict per column; `apply_review` folds those
verdicts into a new `StarterConfig`. Every entry the user types goes through `column_entry`,
which checks it against the strategy catalog (`strategy_catalog`), so a front end keeps no table
of strategies, options, types or namespaces. The starter's own entries come from the detector
descriptors and go through `profiling.build_entry`, the same shape writer without the catalog
check: they carry settings (`validate_luhn`) the wizard does not offer.

This module sits at the `execution` tier because it reads the catalog, and `profiling` is below
that tier. `plan` is below it too, so `apply_review` runs the profile-free plan checks
(`run_config_only_checks`). The full `compile_plan` needs a profile, which reads the data, so that
step stays with the caller. Every refusal is a `ReviewInputError` that names a table, a column or an
option key, never a value. It is raised after the `except` block that caught the cause has
closed, so neither `__cause__` nor `__context__` holds a value.
"""

from __future__ import annotations

import copy
import dataclasses
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, NoReturn

from decoy_engine import reasons
from decoy_engine.config import PipelineConfigError
from decoy_engine.contracts.strategy_requirements import lookup_path, requirement_applies
from decoy_engine.detection.types import DetectorSource, ModelRef
from decoy_engine.errors import DecoyError
from decoy_engine.execution import StrategyInfo, StrategyOption, strategy_catalog
from decoy_engine.fileaccess import FileAccess, entry_point
from decoy_engine.plan import PlanCompileError, run_config_only_checks
from decoy_engine.profiling import (
    StarterConfig,
    build_entry,
    check_starter_config,
    declared_key_namespaces,
    swap_placeholder_namespaces,
)
from decoy_engine.reasons import ReasonCode

__all__ = [
    "ReviewDecision",
    "ReviewDuplicateError",
    "ReviewEmptyTableError",
    "ReviewEntryError",
    "ReviewInputError",
    "ReviewKeyColumnError",
    "ReviewStaleError",
    "ReviewUnknownColumnError",
    "ReviewVerdict",
    "SuggestionRef",
    "apply_review",
    "column_entry",
]

_REDACT = "redact"
_NER_PREFIX = "ner_"
_MAX_PROBLEMS_SHOWN = 5


class ReviewInputError(DecoyError):
    """A review decision or column entry the starter config cannot take.

    Each subclass names one registered reason in its class attribute `code`. `table`, `column`
    and `option` name where, and none of them is a data value. The message is fixed text plus
    those names.
    """

    if TYPE_CHECKING:
        code: ReasonCode

    def __init__(
        self,
        text: str,
        *,
        table: str | None = None,
        column: str | None = None,
        option: str | None = None,
    ) -> None:
        if type(self) is ReviewInputError:
            raise TypeError("ReviewInputError is a base class; raise one of its subclasses")
        self.text = text
        self.table = table
        self.column = column
        self.option = option
        names = (("table", table), ("column", column), ("option", option))
        where = ", ".join(f"{label} {name!r}" for label, name in names if name is not None)
        super().__init__(f"{self.identity}: {text}" + (f" ({where})" if where else ""))

    @property
    def identity(self) -> str:
        """The registry identity, `<namespace>.<code>`."""
        return f"{self.code.namespace}.{self.code}"


class ReviewEntryError(ReviewInputError):
    """A column entry names an unknown strategy or option, or gives a bad value."""

    code = reasons.config.ENTRY_INVALID


class ReviewKeyColumnError(ReviewInputError):
    """A relationship key column was dropped or given a strategy that is not join-safe."""

    code = reasons.config.KEY_COLUMN_NOT_JOIN_SAFE


class ReviewUnknownColumnError(ReviewInputError):
    """A decision names a table or column the starter config does not have."""

    code = reasons.pre_scan.REVIEW_UNKNOWN_COLUMN


class ReviewDuplicateError(ReviewInputError):
    """Two decisions name the same column."""

    code = reasons.pre_scan.REVIEW_DUPLICATE


class ReviewStaleError(ReviewInputError):
    """A confirmed suggestion is not the one the starter holds."""

    code = reasons.pre_scan.REVIEW_STALE


class ReviewEmptyTableError(ReviewInputError):
    """The decisions drop every column of a table."""

    code = reasons.pre_scan.REVIEW_EMPTY_TABLE


class ReviewVerdict(str, Enum):
    """What the user decided about one column. One vocabulary for columns and findings."""

    CONFIRM = "confirm"
    REJECT = "reject"
    EDIT = "edit"
    SKIP = "skip"
    DROP = "drop"


@dataclass(frozen=True)
class SuggestionRef:
    """What the user saw and confirmed: a suggestion's identity, its model and its strategy."""

    source: DetectorSource
    detector_id: str
    model: ModelRef | None
    strategy: str


@dataclass(frozen=True)
class ReviewDecision:
    """One column's verdict. `confirmed` is for `CONFIRM`, `entry` for `EDIT` (a strategy and
    its options)."""

    table: str
    column: str
    verdict: ReviewVerdict
    confirmed: SuggestionRef | None = None
    entry: Mapping[str, Any] | None = None


def column_entry(
    strategy: str,
    column: str,
    *,
    options: Mapping[str, Any] | None = None,
    namespace: str | None = None,
) -> dict[str, Any]:
    """Build the column entry for `strategy`, refusing anything the catalog does not allow.

    Refuses an unknown or non-offered strategy, an option the strategy does not declare, a wrong
    exact type (a bool is not an int), a value outside `choices`, and a missing required option
    or setting. The namespace is `namespace`, or the column name when the catalog says the
    strategy needs one. Each option's catalog `location` decides whether it sits on the entry or
    under `provider_config`.
    """
    info = _catalog().get(strategy) if isinstance(strategy, str) else None
    if info is None or not info.offer_in_wizard:
        raise _invalid(column, "the strategy is unknown or not offered for review")
    if namespace is not None and _blank(namespace):
        raise _invalid(column, "the namespace must be a non-empty string", option="namespace")
    fields: dict[str, Any] = {}
    provider_config: dict[str, Any] = {}
    declared = {o.name: o for o in info.options}
    given = dict(options or {})
    for name, value in given.items():
        option = declared.get(name)
        if option is None:
            raise _invalid(column, "the strategy has no such option", option=str(name))
        _check_value(column, option, value)
        _place(option, value, fields, provider_config)
    for option in info.options:
        if option.required and option.name not in given:
            raise _invalid(column, "a required option is missing", option=option.name)
    chosen = namespace if namespace is not None else (column if info.namespace_required else None)
    entry = build_entry(
        strategy, column, column_fields=fields, provider_config=provider_config, namespace=chosen
    )
    for req in info.requirements:
        if requirement_applies(req, entry) and _blank(lookup_path(entry, req.path)):
            raise _invalid(column, "a setting the strategy needs is missing", option=req.path[-1])
    return entry


@entry_point
def apply_review(
    starter: StarterConfig,
    decisions: Sequence[ReviewDecision],
    *,
    file_access: FileAccess | None = None,
    base_dir: str | Path | None = None,
) -> StarterConfig:
    """Fold one verdict per column into a new `StarterConfig`.

    The result does not depend on the order of `decisions`. `CONFIRM` takes the suggestion the
    user saw, `REJECT` writes `redact` with a note, `EDIT` writes a catalog-checked entry, `SKIP`
    keeps the starter's entry and note, `DROP` removes the column and lists it in the table's one
    `drop_column` transform. A column of a declared relationship keeps that relationship's
    namespace, takes only a join-safe strategy and cannot be dropped; `REJECT` leaves its key
    entry as it is. The result passes the config validation and the profile-free plan checks
    (`run_config_only_checks`), so every entry that needs a namespace has one. The full
    `compile_plan` needs a profile, which reads the data, so that step is the caller's.

    `file_access` and `base_dir` go to `run_config_only_checks`, which reads the snapshot
    artifacts a config names.
    """
    config = copy.deepcopy(starter.config)
    notes: dict[tuple[str, str], str] = dict(starter.notes)
    tables = {t["name"]: t for t in config["tables"]}
    keys = declared_key_namespaces(config.get("relationships") or ())
    catalog = _catalog()
    seen: set[tuple[str, str]] = set()
    dropped: dict[str, set[str]] = {}
    for decision in decisions:
        slot = (decision.table, decision.column)
        table = tables.get(decision.table)
        index = _index_of(table, decision.column)
        if table is None or index is None:
            raise ReviewUnknownColumnError(
                "the decision names a column that is not in the starter config",
                table=decision.table,
                column=decision.column,
            )
        if slot in seen:
            raise ReviewDuplicateError(
                "two decisions name the same column",
                table=decision.table,
                column=decision.column,
            )
        seen.add(slot)
        verdict = decision.verdict
        if not isinstance(verdict, ReviewVerdict):
            raise _invalid(decision.column, "the verdict is not a review verdict", decision.table)
        columns = table["columns"]
        key = keys.get(slot)
        if verdict is ReviewVerdict.SKIP:
            continue
        if verdict is ReviewVerdict.DROP:
            if key is not None:
                raise _not_join_safe(decision, "a relationship key cannot be dropped")
            dropped.setdefault(decision.table, set()).add(decision.column)
            notes.pop(slot, None)
            continue
        if verdict is ReviewVerdict.REJECT:
            if key is None:
                notes[slot] = f"rejected (suggested {columns[index]['strategy']})"
                columns[index] = column_entry(_REDACT, decision.column)
            continue
        if verdict is ReviewVerdict.CONFIRM:
            entry = _confirmed_entry(starter, decision)
        else:
            entry = _edited_entry(decision, None if key is None else key[0])
        if key is not None:
            info = catalog.get(entry.get("strategy", ""))
            if info is None or not info.join_safe:
                raise _not_join_safe(decision, "a relationship key needs a join-safe strategy")
            entry = {**entry, "namespace": key[0]}
        columns[index] = entry
        notes.pop(slot, None)
    for table_name in sorted(dropped):
        _drop(tables[table_name], dropped[table_name])
    problems = _validation_problems(config, file_access, base_dir)
    if problems:
        raise ReviewEntryError(f"the reviewed config fails validation ({problems})")
    return dataclasses.replace(starter, config=config, notes=MappingProxyType(notes))


def _blank(value: object) -> bool:
    """The plan check's test for a missing name: anything but a non-blank string."""
    return not isinstance(value, str) or not value.strip()


def _unreachable(value: NoReturn) -> NoReturn:
    raise AssertionError("an option kind the catalog does not define")


def _catalog() -> dict[str, StrategyInfo]:
    return {info.name: info for info in strategy_catalog()}


def _invalid(
    column: str, text: str, table: str | None = None, *, option: str | None = None
) -> ReviewInputError:
    return ReviewEntryError(text, table=table, column=column, option=option)


def _not_join_safe(decision: ReviewDecision, text: str) -> ReviewInputError:
    return ReviewKeyColumnError(text, table=decision.table, column=decision.column)


def _index_of(table: Mapping[str, Any] | None, column: str) -> int | None:
    if table is None:
        return None
    for position, entry in enumerate(table["columns"]):
        if entry.get("name") == column:
            return position
    return None


def _check_value(column: str, option: StrategyOption, value: Any) -> None:
    wire = option.wire_type
    if wire == "str":
        ok = type(value) is str
    elif wire == "int":
        ok = type(value) is int
    elif wire == "float":
        ok = type(value) in (int, float)
    elif wire == "bool":
        ok = type(value) is bool
    elif wire == "str_list":
        ok = isinstance(value, (list, tuple)) and all(type(v) is str for v in value)
    elif wire == "float_list":
        ok = isinstance(value, (list, tuple)) and all(type(v) in (int, float) for v in value)
    else:
        _unreachable(wire)
    if not ok:
        raise _invalid(column, "the option has the wrong type", option=option.name)
    if option.choices is not None:
        chosen = value if isinstance(value, (list, tuple)) else (value,)
        if any(v not in option.choices for v in chosen):
            raise _invalid(column, "the option value is not one of its choices", option=option.name)


def _place(
    option: StrategyOption, value: Any, fields: dict[str, Any], provider_config: dict[str, Any]
) -> None:
    stored = list(value) if isinstance(value, (list, tuple)) else value
    if option.location == "column":
        fields[option.name] = stored
    elif option.location == "provider_config":
        provider_config[option.name] = stored
    elif option.location == "provider_config.ner":
        provider_config.setdefault("ner", {})[option.name.removeprefix(_NER_PREFIX)] = stored
    else:
        _unreachable(option.location)


def _confirmed_entry(starter: StarterConfig, decision: ReviewDecision) -> dict[str, Any]:
    ref = decision.confirmed
    if ref is None:
        raise _stale(decision, "confirmed suggestion")
    column = [
        s for s in starter.suggestions if (s.table, s.column) == (decision.table, decision.column)
    ]
    found = [s for s in column if (s.source, s.detector_id) == (ref.source, ref.detector_id)]
    if not found:
        raise _stale(decision, "detector")
    found = [s for s in found if s.model == ref.model]
    if not found:
        raise _stale(decision, "model")
    found = [s for s in found if s.strategy == ref.strategy]
    if not found:
        raise _stale(decision, "strategy")
    return copy.deepcopy(dict(found[0].entry))


def _stale(decision: ReviewDecision, differing: str) -> ReviewInputError:
    return ReviewStaleError(
        f"the confirmed suggestion does not match the starter's ({differing} differs)",
        table=decision.table,
        column=decision.column,
    )


def _edited_entry(decision: ReviewDecision, key_namespace: str | None) -> dict[str, Any]:
    given = decision.entry
    if not isinstance(given, Mapping) or "strategy" not in given:
        raise _invalid(decision.column, "an edit needs an entry with a strategy", decision.table)
    options = {k: v for k, v in given.items() if k not in ("strategy", "namespace")}
    namespace = given.get("namespace") if key_namespace is None else key_namespace
    refused: ReviewInputError | None = None
    try:
        return column_entry(
            given["strategy"], decision.column, options=options, namespace=namespace
        )
    except ReviewInputError as err:
        refused = type(err)(
            err.text,
            table=decision.table,
            column=err.column,
            option=err.option,
        )
    raise refused


def _drop(table: dict[str, Any], names: set[str]) -> None:
    kept = [c for c in table["columns"] if c.get("name") not in names]
    if not kept:
        raise ReviewEmptyTableError(
            "the review drops every column of the table",
            table=table["name"],
        )
    in_source_order = [c["name"] for c in table["columns"] if c.get("name") in names]
    table["columns"] = kept
    ops = table.setdefault("transforms", [])
    existing = next((op for op in ops if op.get("op") == "drop_column"), None)
    if existing is None:
        ops.append({"op": "drop_column", "columns": in_source_order})
    else:
        have = existing["columns"]
        existing["columns"] = [*have, *(n for n in in_source_order if n not in have)]


def _validation_problems(
    config: dict[str, Any], file_access: FileAccess | None, base_dir: str | Path | None
) -> str:
    """The value-free summary of why `config` fails, or an empty string when it validates."""
    summary = ""
    try:
        check_starter_config(copy.deepcopy(config))
        run_config_only_checks(
            swap_placeholder_namespaces(config)[0], file_access=file_access, base_dir=base_dir
        )
    except PipelineConfigError as err:
        shown = [
            f"{p.code} at {p.location or '(root)'}" for p in err.problems[:_MAX_PROBLEMS_SHOWN]
        ]
        summary = "; ".join(shown) or "no detail"
    except PlanCompileError as err:
        summary = f"{err.code} at {err.path or '(root)'}"
    return summary
