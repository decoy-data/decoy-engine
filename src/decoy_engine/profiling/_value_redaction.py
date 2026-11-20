"""The one place that decides which profile fields hold cell values, and removes them.

`ColumnProfile.to_dict()` stays the raw form (the platform persists and rebuilds it).
Anything that writes a profile for a person to read or commit goes through
`profile_document`, and anything that reads a saved profile back for display goes through
`redact_profile_dict` (both in `_profile_document.py`). Both are driven by `VALUE_FIELDS`; every other field reachable from
`ColumnProfile` is listed in `VALUE_FREE_FIELDS`, and the type walk refuses a field that is
in neither, so a new value-bearing field cannot ship unclassified.

Pattern: classification registry plus default-deny serializer (Google Cloud DLP
`include_quote`, ydata-profiling `sensitive=True`, Microsoft Presidio `replace` operator).
See: https://cloud.google.com/sensitive-data-protection/docs/reference/rest/v2/InspectConfig.
Findings omit the quote unless asked (DLP); counts and shape survive while values go
(ydata); a redacted entry keeps its position as a fixed placeholder (Presidio).

The distribution snapshot `decoy fit` writes is classified here too (`SNAPSHOT_VALUE_STATS`),
so one file answers which fields of a Decoy artifact are cell values. Numeric and datetime
coarsening follows statistical disclosure control global recoding and top/bottom coding
(Hundepool et al., Statistical Disclosure Control, Wiley 2012, sections 3.4.2 to 3.4.3; R
sdcMicro `globalRecode`), and datetimes keep only years as in HIPAA Safe Harbor,
45 CFR 164.514(b)(2)(i)(C). The data-dependent rules live in `_snapshot_values.py`.
"""

from __future__ import annotations

import dataclasses
import enum
import functools
import math
import numbers
import types
from collections.abc import Callable, Iterator, Mapping
from typing import Any, Final, TypeGuard, Union, get_args, get_origin, get_type_hints

from decoy_engine.profiling.types import ColumnProfile


class Rule(enum.Enum):
    NULL = "null"
    EMPTY_LIST = "empty_list"
    PLACEHOLDER = "placeholder"
    PLACEHOLDER_EACH = "placeholder_each"
    COARSE_RANGE = "coarse_range"  # re-derived from the series on a coarse grid
    EMPTY_MAP = "empty_map"
    PREVIOUS_YEAR_START = "previous_year_start"  # re-derived from the year bins
    NEXT_YEAR_END = "next_year_end"
    # The floor rules for a column the profiler did not flag (`SNAPSHOT_FLOOR_STATS`).
    TOP_CODED_RANGE = "top_coded_range"  # bounds and bins from the K-th smallest and largest cell
    K_TAIL_QUANTILES = "k_tail_quantiles"  # kept only when K rows lie on each side
    FOLD_YEARS_UNDER_K = "fold_years_under_k"  # adjacent years merged until a range holds K rows
    KEPT_YEAR_START = "kept_year_start"  # first instant of the first folded range
    KEPT_YEAR_END = "kept_year_end"  # last instant of the last folded range
    FOLD_UNDER_K = "fold_under_k"  # labels and cells under K rows move into other_count
    # The floor rules for a column the profiler did not flag, in a plain profile document
    # (`PROFILE_FLOOR_FIELDS`). Each needs counts from the same document.
    HELD_BY_K = "held_by_k"  # kept when the top values prove K rows hold the text
    UNDER_K_PLACEHOLDER = "under_k_placeholder"  # a text no count proves K rows hold
    AGGREGATE_2K = "aggregate_2k"  # kept when the column has 2K non-null cells
    FOLD_DECADES = "fold_decades"  # decade buckets coded at the K-th row, then merged to K rows
    DECADE_START = "decade_start"  # first day of the first folded decade
    DECADE_END = "decade_end"  # last day of the last folded decade
    SENTINEL_TABLE = "sentinel_table"  # kept only when it is the fixed table text


REDACTED: Final = "[redacted]"
VALUE_POLICY_KEY: Final = "value_policy"
REDACTED_COLUMNS_KEY: Final = "redacted_columns"
# v2: every column the profiler did not flag is floored at MIN_RELEASE_COUNT as well.
POLICY_REDACTED: Final = "flagged-redacted/v2"
POLICY_REDACTED_V1: Final = "flagged-redacted/v1"
# Every reader that asks "is this a redacted document" tests membership, never equality.
REDACTED_POLICIES: Final = frozenset({POLICY_REDACTED_V1, POLICY_REDACTED})
POLICY_RAW: Final = "raw"
PII_CANDIDATE_THRESHOLD: Final = 0.6
# Minimum source rows behind a released numeric interval, tail or exact value. Agencies use
# minimum-frequency thresholds of 3 to 11 (Hundepool et al., Statistical Disclosure Control,
# Wiley 2012, section 4.2; the CMS cell-size policy suppresses cells under 11).
MIN_RELEASE_COUNT: Final = 10

VALUE_FIELDS: Final[Mapping[tuple[str, str], Rule]] = types.MappingProxyType(
    {
        ("FieldStats", "min_value"): Rule.NULL,
        ("FieldStats", "max_value"): Rule.NULL,
        ("FieldStats", "date_min"): Rule.NULL,
        ("FieldStats", "date_max"): Rule.NULL,
        ("FieldStats", "mode_value"): Rule.NULL,
        # One non-null value, or a constant column, makes the mean the cell itself.
        ("FieldStats", "mean_value"): Rule.NULL,
        ("FieldStats", "sample_invalid"): Rule.EMPTY_LIST,
        ("TopValue", "value"): Rule.PLACEHOLDER,
        ("DetectorMatch", "sample_misses"): Rule.EMPTY_LIST,
        # Categorical labels are cells and numeric bin edges come from the real min and max.
        ("Distribution", "labels"): Rule.PLACEHOLDER_EACH,
        ("Distribution", "min"): Rule.NULL,
        ("Distribution", "max"): Rule.NULL,
        ("Distribution", "mean"): Rule.NULL,
        # The note repeats the literal for known dates and interpolates string sentinels.
        ("SentinelFlag", "value"): Rule.PLACEHOLDER,
        ("SentinelFlag", "note"): Rule.PLACEHOLDER,
    }
)


def _free(type_name: str, *names: str) -> set[tuple[str, str]]:
    return {(type_name, n) for n in names}


VALUE_FREE_FIELDS: Final[frozenset[tuple[str, str]]] = frozenset(
    _free(
        "ColumnProfile",
        "source_label", "row_count", "sample_strategy", "sample_row_cap", "fields",
        "reid_risk_columns", "reid_risk_score", "quasi_identifier_groups", "k_anonymity",
        "engine_version", "generated_at",
    )
    | _free(
        "FieldStats",
        "name", "inferred_type", "dtype_raw", "row_count", "null_count", "null_rate",
        "distinct_count", "unique_rate", "is_likely_unique", "min_length",
        "max_length", "avg_length", "date_format", "invalid_count", "casing_pattern",
        "format_pattern", "format_pattern_complete", "alphabet", "value_set_size_class", "numeric_range_class",
        "mode_freq", "top_values", "detector_matches", "sentinels", "pii_score",
        "distribution", "detection_trail", "domain",
    )
    | _free("TopValue", "count", "pct")
    | _free(
        "DetectorMatch",
        "detector_id", "match_rate", "format_pattern", "format_pattern_complete", "confidence",
        "domain",
    )
    | _free("Distribution", "kind", "data")
    | _free("SentinelFlag", "kind", "count")
    # Signal text holds detector ids and header names, not cells.
    | _free("DetectionSignal", "signal", "confidence", "winner", "ml", "skipped")
)  # fmt: skip

SNAPSHOT_VALUE_STATS: Final[Mapping[tuple[str, str], Rule]] = types.MappingProxyType(
    {
        ("numeric", "min"): Rule.COARSE_RANGE,
        ("numeric", "max"): Rule.COARSE_RANGE,
        ("numeric", "bin_edges"): Rule.COARSE_RANGE,
        ("numeric", "bin_counts"): Rule.COARSE_RANGE,
        ("numeric", "mean"): Rule.NULL,
        # With the mean, the std fixes both cells of a two-row column.
        ("numeric", "std"): Rule.NULL,
        ("numeric", "quantiles"): Rule.EMPTY_MAP,
        ("numeric", "quantile_grid"): Rule.NULL,
        ("numeric", "exact_values"): Rule.NULL,
        # Any string placeholder here could equal a real category, so the container empties.
        ("categorical", "top_values"): Rule.EMPTY_LIST,
        ("datetime", "min"): Rule.PREVIOUS_YEAR_START,
        ("datetime", "max"): Rule.NEXT_YEAR_END,
        ("joint", "cells"): Rule.EMPTY_LIST,
    }
)
SNAPSHOT_VALUE_FREE_STATS: Final[frozenset[tuple[str, str]]] = frozenset(
    _free(
        "document",
        "schema_version",
        "row_count",
        "columns",
        "joints",
        "value_policy",
        "redacted_columns",
    )
    | _free(
        "column",
        "dtype",
        "kind",
        "null_count",
        "non_null_count",
        "distinct_count",
        "stats",
        "fanout",
        "cell_format",
    )
    # Degree histogram: integer counts only, never a key value.
    | _free("fanout", "rows", "keys", "degrees")
    | _free("categorical", "other_count", "high_cardinality")
    | _free("datetime", "year_bins")
    | _free("year_bin", "year", "start_year", "end_year", "count")
    | _free("freetext", "length", "length_bin_edges", "length_bin_counts")
    | _free("length", "min", "max", "mean", "std")
    | _free("joint", "columns", "cell_count", "other_count")
)
# Rules for a column the profiler did not flag, in a plain snapshot. The flagged table above
# withholds a key; this one keeps it at or above MIN_RELEASE_COUNT rows (Hundepool et al.,
# Statistical Disclosure Control, Wiley 2012, sections 3.4 and 4.2: top and bottom coding, global
# recoding, a minimum frequency rule). `("datetime", "year_bins")` is value-free for a flagged
# column and still folded, so it sits in both registries.
SNAPSHOT_FLOOR_STATS: Final[Mapping[tuple[str, str], Rule]] = types.MappingProxyType(
    {
        ("numeric", "min"): Rule.TOP_CODED_RANGE,
        ("numeric", "max"): Rule.TOP_CODED_RANGE,
        ("numeric", "bin_edges"): Rule.TOP_CODED_RANGE,
        ("numeric", "bin_counts"): Rule.TOP_CODED_RANGE,
        ("numeric", "quantiles"): Rule.K_TAIL_QUANTILES,
        ("categorical", "top_values"): Rule.FOLD_UNDER_K,
        ("datetime", "year_bins"): Rule.FOLD_YEARS_UNDER_K,
        ("datetime", "min"): Rule.KEPT_YEAR_START,
        ("datetime", "max"): Rule.KEPT_YEAR_END,
        ("joint", "cells"): Rule.FOLD_UNDER_K,
    }
)
# Flagged-table keys the floor keeps as they are: aggregates of at least 2K cells, and blocks the
# numeric shape fit already floors at K.
SNAPSHOT_FLOOR_KEPT_STATS: Final[frozenset[tuple[str, str]]] = frozenset(
    _free("numeric", "mean", "std", "quantile_grid", "exact_values")
)
SNAPSHOT_KINDS: Final = frozenset({"numeric", "categorical", "datetime", "freetext", "empty"})
# Rules that need the data; `_apply` performs every other rule.
DATA_RULES: Final = frozenset(
    {
        Rule.COARSE_RANGE,
        Rule.PREVIOUS_YEAR_START,
        Rule.NEXT_YEAR_END,
        Rule.TOP_CODED_RANGE,
        Rule.K_TAIL_QUANTILES,
        Rule.FOLD_YEARS_UNDER_K,
        Rule.KEPT_YEAR_START,
        Rule.KEPT_YEAR_END,
        Rule.FOLD_UNDER_K,
        Rule.HELD_BY_K,
        Rule.UNDER_K_PLACEHOLDER,
        Rule.AGGREGATE_2K,
        Rule.FOLD_DECADES,
        Rule.DECADE_START,
        Rule.DECADE_END,
        Rule.SENTINEL_TABLE,
    }
)
# Rules for a column the profiler did not flag, in a plain profile document. The flagged table
# withholds a slot; this one keeps it only when a count in the same document proves K rows
# behind it (Hundepool et al., Statistical Disclosure Control, Wiley 2012, sections 3.4 and 4.2).
# A distribution is keyed `Distribution.<kind>`; an unknown kind gets the flagged rules.
PROFILE_DISTRIBUTION_KINDS: Final = frozenset(
    {"numeric", "date", "categorical", "pattern", "freetext"}
)


def _floor(scope: str, **rules: Rule) -> dict[tuple[str, str], Rule]:
    return {(scope, name): rule for name, rule in rules.items()}


_NULLS: Final = {"min": Rule.NULL, "max": Rule.NULL, "mean": Rule.NULL}
PROFILE_FLOOR_FIELDS: Final[Mapping[tuple[str, str], Rule]] = types.MappingProxyType(
    {
        **_floor(
            "FieldStats",
            min_value=Rule.HELD_BY_K,
            max_value=Rule.HELD_BY_K,
            mode_value=Rule.HELD_BY_K,
            mean_value=Rule.AGGREGATE_2K,
            date_min=Rule.DECADE_START,
            date_max=Rule.DECADE_END,
            sample_invalid=Rule.EMPTY_LIST,
        ),
        **_floor("DetectorMatch", sample_misses=Rule.EMPTY_LIST),
        **_floor("TopValue", value=Rule.UNDER_K_PLACEHOLDER),
        **_floor("Distribution.categorical", labels=Rule.UNDER_K_PLACEHOLDER, **_NULLS),
        **_floor(
            "Distribution.numeric",
            labels=Rule.PLACEHOLDER_EACH,
            **{**_NULLS, "mean": Rule.AGGREGATE_2K},
        ),
        **_floor(
            "Distribution.date",
            labels=Rule.FOLD_DECADES,
            min=Rule.DECADE_START,
            max=Rule.DECADE_END,
            mean=Rule.NULL,
        ),
        **_floor("Distribution.pattern", labels=Rule.PLACEHOLDER_EACH, **_NULLS),
        **_floor("SentinelFlag", value=Rule.SENTINEL_TABLE, note=Rule.SENTINEL_TABLE),
    }
)
# Slots an unflagged column keeps as they are: free-text length buckets and length statistics.
PROFILE_FLOOR_KEEP: Final = frozenset(
    ("Distribution.freetext", name) for name in ("labels", "min", "max", "mean")
)


def profile_floor_slots(type_name: str, kind: Any = None) -> tuple[dict[str, Rule], frozenset[str]]:
    """(rule by slot, slots kept as they are) for one value-bearing type of an unflagged column."""
    scope = type_name
    if isinstance(kind, str) and kind in PROFILE_DISTRIBUTION_KINDS:
        scope = f"Distribution.{kind}"
    names = [name for t, name in VALUE_FIELDS if t == type_name]
    kept = frozenset(name for name in names if (scope, name) in PROFILE_FLOOR_KEEP)
    rules = {
        name: PROFILE_FLOOR_FIELDS.get((scope, name), VALUE_FIELDS[(type_name, name)])
        for name in names
        if name not in kept
    }
    return rules, kept


def snapshot_rules(scope: str) -> Mapping[str, Rule]:
    """Every value rule the snapshot registry holds for a scope (a column kind, `joint`)."""
    return types.MappingProxyType(
        {k: r for (s, k), r in SNAPSHOT_VALUE_STATS.items() if s == scope}
    )


def snapshot_floor_rules(scope: str) -> Mapping[str, Rule]:
    """Every floor rule the registry holds for a scope (a column kind, `joint`)."""
    return types.MappingProxyType(
        {k: r for (s, k), r in SNAPSHOT_FLOOR_STATS.items() if s == scope}
    )


def snapshot_keeper(scope: str) -> Callable[[str, Any], bool]:
    """Keep test for `_apply`: a key the registry classifies for `scope` survives, any other is denied."""
    known = {k for (s, k) in SNAPSHOT_VALUE_FREE_STATS if s == scope} | snapshot_rules(scope).keys()
    return lambda name, _value: name in known


_ITEM: Final = "*"
_Steps = tuple[str, ...]


def _unwrap(hint: Any) -> tuple[Any, _Steps]:
    """Strip `X | None` and `list[...]` layers, returning the inner type and its item steps."""
    steps: _Steps = ()
    while True:
        origin = get_origin(hint)
        if origin in (Union, types.UnionType):
            args = [a for a in get_args(hint) if a is not type(None)]
            if len(args) != 1:
                return hint, steps
            hint = args[0]
        elif origin is list:
            hint, steps = get_args(hint)[0], (*steps, _ITEM)
        else:
            return hint, steps


def _nests_dataclass(hint: Any) -> bool:
    return any(
        (dataclasses.is_dataclass(a) and isinstance(a, type)) or _nests_dataclass(a)
        for a in get_args(hint)
    )


_SCALARS: Final[Mapping[Any, tuple[type, ...]]] = types.MappingProxyType(
    {bool: (bool,), int: (numbers.Integral,), float: (numbers.Real,), str: (str,)}
)


def _checkable(hint: Any) -> bool:
    """True when `_conforms` can verify a value against `hint` (scalars, `list`, `Optional`)."""
    origin = get_origin(hint)
    if origin in (Union, types.UnionType, list):
        return all(_checkable(a) for a in get_args(hint))
    return hint is type(None) or hint in _SCALARS or dataclasses.is_dataclass(hint)


def _conforms(value: Any, hint: Any) -> bool:
    """Does a loaded JSON value have the declared type? Nested dataclasses are checked as containers."""
    origin = get_origin(hint)
    if origin in (Union, types.UnionType):
        return any(_conforms(value, a) for a in get_args(hint))
    if origin is list:
        (item,) = get_args(hint)
        return type(value) is list and all(_conforms(v, item) for v in value)
    if dataclasses.is_dataclass(hint):
        return True
    if hint is type(None):
        return value is None
    if isinstance(value, bool):
        return hint is bool  # a bool is not a count or a score
    if hint is float:
        # The profiler writes finite floats here; an integer or a NaN came from another writer and may be a cell.
        return (
            isinstance(value, numbers.Real)
            and not isinstance(value, numbers.Integral)
            and math.isfinite(value)
        )
    # numbers ABCs, so a NumPy count or score from the profiler still conforms.
    return isinstance(value, _SCALARS.get(hint, ()))


def _has_value_rules(cls: type) -> bool:
    return any(t == cls.__name__ for t, _ in VALUE_FIELDS)


def _walk(root: type) -> tuple[dict[_Steps, type], list[str]]:
    """Dict path of every dataclass reachable from `root`, plus every reason the walk is unsafe.

    The redactor only knows `list` and `Optional` nesting, value types under `fields[*]`, and
    one class per name, so anything else is reported instead of silently skipped.
    """
    found: dict[_Steps, type] = {}
    by_name: dict[str, type] = {}
    errors: list[str] = []

    def visit(cls: type, path: _Steps) -> None:
        found[path] = cls
        if by_name.setdefault(cls.__name__, cls) is not cls:
            errors.append(f"two classes named {cls.__name__}")
        if _has_value_rules(cls) and path[:2] != ("fields", _ITEM):
            errors.append(f"value type {cls.__name__} at {'.'.join(path) or 'root'}")
        hints = get_type_hints(cls)
        for f in dataclasses.fields(cls):
            pair = (cls.__name__, f.name)
            if (pair in VALUE_FIELDS) == (pair in VALUE_FREE_FIELDS):
                errors.append(f"unclassified {cls.__name__}.{f.name}")
            elif pair in VALUE_FREE_FIELDS and not _checkable(hints[f.name]):
                errors.append(f"unchecked shape {cls.__name__}.{f.name}")
            inner, steps = _unwrap(hints[f.name])
            if dataclasses.is_dataclass(inner) and isinstance(inner, type):
                visit(inner, (*path, f.name, *steps))
            elif _nests_dataclass(inner):
                errors.append(f"unsupported container {cls.__name__}.{f.name}")

    visit(root, ())
    return found, errors


@functools.cache
def profile_types() -> Mapping[_Steps, type]:
    """Dict path (`("fields", "*", "top_values", "*")`) to dataclass, from `ColumnProfile`."""
    found, errors = _walk(ColumnProfile)
    if errors:
        # Names only, never values: this fails an engine change in CI, not a user run.
        raise TypeError(f"profile types the redactor cannot cover: {errors}")
    return types.MappingProxyType(found)


def _is_score(value: Any) -> TypeGuard[float]:
    return type(value) is float and math.isfinite(value) and 0.0 <= value <= 1.0


def is_value_sensitive(field: Mapping[str, Any]) -> bool:
    """True when a profiled column's values must not leave the process by default.

    Any detector hit, a PII score at the candidate threshold, or a near-unique column. A
    missing or ill-typed input counts as sensitive, so a hand-edited file fails closed.
    """
    if not isinstance(field, Mapping):
        return True
    matches = field.get("detector_matches")
    score = field.get("pii_score")
    unique = field.get("is_likely_unique")
    if type(matches) is not list or not _is_score(score) or type(unique) is not bool:
        return True
    return bool(matches) or score >= PII_CANDIDATE_THRESHOLD or unique


def _sensitive_entries(fields: Any) -> list[tuple[int | None, str]]:
    """(index, name) of each value-sensitive entry of a profile's `fields`; index None is a non-list `fields`."""
    if isinstance(fields, list):
        return [
            (
                i,
                f["name"]
                if isinstance(f, Mapping) and isinstance(f.get("name"), str)
                else REDACTED,
            )
            for i, f in enumerate(fields)
            if is_value_sensitive(f)
        ]
    return [] if fields is None else [(None, REDACTED)]


def value_sensitive_names(fields: Any) -> list[str]:
    """Names of the value-sensitive columns in the JSON form of a profile's `fields` list.

    Takes `profile.to_dict()["fields"]`, not the dataclasses: those are not mappings, so the
    fail-closed predicate would flag every column.
    """
    return [name for _, name in _sensitive_entries(fields)]


def stamp_value_policy(
    doc: dict[str, Any], names: list[str], *, include_values: bool
) -> dict[str, Any]:
    """Write the policy marker and the sensitive names onto `doc`, which the caller owns."""
    if include_values:
        doc.setdefault(VALUE_POLICY_KEY, POLICY_RAW)
    else:
        doc[VALUE_POLICY_KEY] = POLICY_REDACTED
    doc[REDACTED_COLUMNS_KEY] = names
    return doc


def _containers(node: Any, steps: _Steps, parent: Any, key: Any) -> Iterator[dict[str, Any]]:
    """Yield the dicts at `steps` below `node`, replacing an off-shape location in `parent`."""
    if node is None:
        return
    if not steps:
        if isinstance(node, dict):
            yield node
        else:
            parent[key] = REDACTED
        return
    step, rest = steps[0], steps[1:]
    if step == _ITEM:
        if not isinstance(node, list):
            parent[key] = REDACTED
            return
        for i, item in enumerate(node):
            yield from _containers(item, rest, node, i)
    elif not isinstance(node, dict):
        parent[key] = REDACTED
    elif step in node:
        yield from _containers(node[step], rest, node, step)


@dataclasses.dataclass(frozen=True)
class PlaceholderAt:
    """Replace only these entries of a list slot, so a floor keeps the labels K rows hold."""

    indexes: frozenset[int]


def _apply(
    container: dict[str, Any],
    rules: Mapping[str, Rule | PlaceholderAt],
    keep: Callable[[str, Any], bool],
    *,
    denied_value: Any = REDACTED,
) -> None:
    # Default-deny: a key `keep` does not vouch for (a newer writer, a hand edit) may hold a cell.
    for name in container.keys() - rules.keys():
        if not keep(name, container[name]):
            container[name] = denied_value
    for name, rule in rules.items():
        if name not in container or container[name] is None:
            continue
        current = container[name]
        if isinstance(rule, PlaceholderAt):
            if isinstance(current, list):
                container[name] = [
                    REDACTED if i in rule.indexes else v for i, v in enumerate(current)
                ]
            else:
                container[name] = REDACTED
        elif rule is Rule.NULL:
            container[name] = None
        elif rule is Rule.EMPTY_LIST:
            container[name] = []
        elif rule is Rule.EMPTY_MAP:
            container[name] = {}
        elif rule is Rule.PLACEHOLDER_EACH and isinstance(current, list):
            container[name] = [REDACTED] * len(current)
        else:
            container[name] = REDACTED


def _shape_keep(shapes: Mapping[str, Any]) -> Callable[[str, Any], bool]:
    """A value-free slot survives only while it still has its declared type (a string score is a cell)."""
    return lambda name, value: name in shapes and _conforms(value, shapes[name])


def _shapes(cls: type) -> Mapping[str, Any]:
    """Declared type of each value-free field of `cls`, by key."""
    hints = get_type_hints(cls)
    return types.MappingProxyType(
        {
            f.name: hints[f.name]
            for f in dataclasses.fields(cls)
            if (cls.__name__, f.name) in VALUE_FREE_FIELDS
        }
    )


@functools.cache
def _field_plan() -> tuple[tuple[_Steps, Mapping[str, Rule], Mapping[str, Any]], ...]:
    """(steps below one `fields[*]` entry, rules, value-free shapes) for every type under a field."""
    plan = []
    for path, cls in profile_types().items():
        if path[:2] == ("fields", _ITEM):
            rules = {f: r for (t, f), r in VALUE_FIELDS.items() if t == cls.__name__}
            plan.append((path[2:], types.MappingProxyType(rules), _shapes(cls)))
    return tuple(plan)


def _redact_field(fields: list[Any], index: int) -> None:
    for steps, rules, shapes in _field_plan():
        for container in _containers(fields[index], steps, fields, index):
            _apply(container, rules, _shape_keep(shapes))
