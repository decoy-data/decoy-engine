"""The one rule for the key/value metadata of a published Parquet file.

A masked output must not carry text from the source file that masking never looked at. The rule
is a rebuild, not a scan: `output_schema` builds a metadata-free schema (every field at every
nesting depth) and attaches only the keys of `_ALLOWED_SCHEMA_KEYS`. The registry holds one key,
`b"pandas"`, and its value is rebuilt, never copied. Every member comes from the output schema,
the running pyarrow and pandas versions or the descriptor registry; the source blob only helps
choose among registry pairs that are all correct for the output Arrow type, so it cannot carry
free text or a number into the output. A blob that is not a JSON object is dropped.

`output_table` applies the rule to a table and `attach_output_metadata` to a schema that is built
elsewhere; the output writers of `fileaccess/adapters/arrow.py` call them, so a published file is
written from the sanitized schema whatever the batches carry.
"""

from __future__ import annotations

import importlib.metadata
import json
import re
import warnings
from collections.abc import Callable, Collection, Mapping
from functools import lru_cache
from typing import Any, Final

import pyarrow as pa
import pyarrow.compute as pc

from decoy_engine._canonical import StrictJsonError, strict_json_loads
from decoy_engine._pandas_meta import COLUMN_INDEX_ENTRY, column_metadata, pairs_for
from decoy_engine.safe_output._date_buffers import own_date_columns

__all__ = [
    "HANDLED_PREDICATES",
    "attach_output_metadata",
    "output_schema",
    "output_table",
    "sanitized_schema_metadata",
]

_PANDAS: Final = b"pandas"
_GENERATED_INDEX: Final = re.compile(r"__index_level_\d+__")


# -- fields and types ----------------------------------------------------------------------------


def _field(field: pa.Field) -> pa.Field:
    return pa.field(field.name, _type(field.type), nullable=field.nullable)


def _children(t: pa.DataType) -> list[pa.Field]:
    return [_field(t.field(i)) for i in range(t.num_fields)]


_RULES: Final[tuple[tuple[str, Callable[[Any], pa.DataType]], ...]] = (
    ("is_struct", lambda t: pa.struct(_children(t))),
    ("is_list", lambda t: pa.list_(_field(t.value_field))),
    ("is_large_list", lambda t: pa.large_list(_field(t.value_field))),
    ("is_fixed_size_list", lambda t: pa.list_(_field(t.value_field), t.list_size)),
    ("is_list_view", lambda t: pa.list_view(_field(t.value_field))),
    ("is_large_list_view", lambda t: pa.large_list_view(_field(t.value_field))),
    (
        "is_map",
        lambda t: pa.map_(_field(t.key_field), _field(t.item_field), keys_sorted=t.keys_sorted),
    ),
    ("is_union", lambda t: pa.union(_children(t), t.mode, list(t.type_codes))),
    ("is_dictionary", lambda t: pa.dictionary(t.index_type, _type(t.value_type), t.ordered)),
    ("is_run_end_encoded", lambda t: pa.run_end_encoded(t.run_end_type, _type(t.value_type))),
)
# List views arrived in pyarrow 16; the declared floor is 14. A row whose predicate does not exist
# in the installed pyarrow has no such type to rebuild, so it is left out. Every other row
# resolves its predicate normally, so a rename in a new pyarrow still fails at import.
_OPTIONAL: Final = frozenset({"is_list_view", "is_large_list_view"})
_ACTIVE: Final = tuple(
    (name, rebuild) for name, rebuild in _RULES if name not in _OPTIONAL or hasattr(pa.types, name)
)
_REBUILDERS: tuple[tuple[Callable[[pa.DataType], bool], Callable[[Any], pa.DataType]], ...] = tuple(
    (getattr(pa.types, name), rebuild) for name, rebuild in _ACTIVE
)

# The predicates `_REBUILDERS` handles; `tests/unit/safe_output/test_file_metadata.py` checks them
# against every `pa.types.is_*` predicate at the pin, so a new nested type turns it red.
HANDLED_PREDICATES: Final = frozenset(name for name, _ in _ACTIVE)


# Extension types with no free-text parameter. Anything else (opaque, tensors, a type a Python
# program registered) is written as its storage type, so a source-supplied name, vendor, dimension
# name or serialized parameter never reaches the output.
_PLAIN_EXTENSIONS: Final = frozenset(
    {"arrow.uuid", "arrow.bool8", "arrow.json", "pandas.period", "pandas.interval"}
)
_PERIOD_FREQ: Final = re.compile(r"[A-Za-z0-9\-]{1,12}")
_INTERVAL_CLOSED: Final = frozenset({"left", "right", "both", "neither"})


def _params_ok(t: pa.BaseExtensionType) -> bool:
    """The pandas types carry one short parameter each; keep the type only if it is a pandas
    frequency string (parsed by pandas, not free text), or one of the four interval closures with a
    subtype that is its own sanitized form."""
    if t.extension_name == "pandas.period":
        freq = getattr(t, "freq", None)
        if not (isinstance(freq, str) and _PERIOD_FREQ.fullmatch(freq)):
            return False
        from pandas.tseries.frequencies import to_offset  # pandas is only needed for this type

        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", FutureWarning)  # a deprecated alias still parses
                to_offset(freq)
        except (ValueError, TypeError):
            return False
        return True
    if t.extension_name == "pandas.interval":
        subtype = getattr(t, "subtype", None)
        return (
            getattr(t, "closed", None) in _INTERVAL_CLOSED
            and isinstance(subtype, pa.DataType)
            and _type(subtype).equals(subtype, check_metadata=True)
        )
    return True


_TZ_SHAPE: Final = re.compile(r"[A-Za-z0-9_+\-/:]{1,64}")


@lru_cache(maxsize=256)
def _tz_known(tz: str) -> bool:
    """True for a timezone name pyarrow resolves (an IANA name or a UTC offset), the closed set
    a timezone parameter may take. Any other text, a URL or a secret included, is not one."""
    if not _TZ_SHAPE.fullmatch(tz):
        return False
    try:
        pc.assume_timezone(pa.array([0], pa.timestamp("s")), tz)  # type: ignore[attr-defined]  # missing from the stubs
    except (pa.ArrowInvalid, pa.ArrowNotImplementedError):
        return False
    return True


def _timestamp(t: pa.TimestampType) -> pa.DataType:
    """A timestamp keeps its zone only when the zone is a known name; otherwise it is the naive
    type of the same unit, with the same stored integers."""
    return t if t.tz is None or _tz_known(t.tz) else pa.timestamp(t.unit)


def _extension(t: pa.BaseExtensionType) -> pa.DataType:
    storage = _type(t.storage_type)
    keep = t.extension_name in _PLAIN_EXTENSIONS and _params_ok(t)
    return t if keep and storage.equals(t.storage_type, check_metadata=True) else storage


def _type(t: pa.DataType) -> pa.DataType:
    if isinstance(t, pa.BaseExtensionType):
        return _extension(t)
    if pa.types.is_timestamp(t):
        return _timestamp(t)
    for matches, rebuild in _REBUILDERS:
        if matches(t):
            return rebuild(t)
    if pa.types.is_nested(t):
        # A code defect, not a data condition: a new nested type must be handled, never skipped.
        raise TypeError(f"output metadata: unhandled nested Arrow type {type(t).__name__}")
    return t


# -- the pandas blob -----------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _pandas_version() -> str | None:
    try:
        return importlib.metadata.version("pandas")
    except importlib.metadata.PackageNotFoundError:
        return None


def _source_entries(columns: object) -> dict[str, dict[str, Any]]:
    """The source `columns` entry per field name, first one wins."""
    out: dict[str, dict[str, Any]] = {}
    if isinstance(columns, list):
        for entry in columns:
            if isinstance(entry, dict) and isinstance(entry.get("field_name"), str):
                out.setdefault(entry["field_name"], entry)
    return out


def _source_pairs(source: dict[str, Any]) -> dict[str, tuple[str, str]]:
    """The `(pandas_type, numpy_type)` the source names per field; a choice among registry pairs."""
    chosen: dict[str, tuple[str, str]] = {}
    for name, entry in _source_entries(source.get("columns")).items():
        kind, numpy = entry.get("pandas_type"), entry.get("numpy_type")
        if isinstance(kind, str) and isinstance(numpy, str):
            chosen[name] = (kind, numpy)
    return chosen


def _column_name(field: str, is_index: bool, source: dict[str, Any], names: set[str]) -> str | None:
    """The `name` member: the field name, except a generated index field, which pyarrow names
    `None`, or by an index name that equals another output field's name (the real name)."""
    if not (is_index and _GENERATED_INDEX.fullmatch(field)):
        return field
    real = _source_entries(source.get("columns")).get(field, {}).get("name")
    return real if isinstance(real, str) and real in names and real != field else None


def _column_index_entry() -> dict[str, Any]:
    return {**COLUMN_INDEX_ENTRY, "metadata": dict(COLUMN_INDEX_ENTRY["metadata"])}


def _sanitize_pandas_blob(raw: bytes, for_schema: pa.Schema) -> bytes | None:
    try:
        source = strict_json_loads(raw, max_int_digits=None)
    except (StrictJsonError, RecursionError):
        return None
    version = _pandas_version()
    if not isinstance(source, dict) or version is None:
        return None
    names = set(for_schema.names)
    stored = source.get("index_columns")
    stored_names = {c for c in stored if isinstance(c, str)} if isinstance(stored, list) else set()
    chosen = _source_pairs(source)
    columns: list[dict[str, Any]] = []
    for field in for_schema:
        pairs = pairs_for(field.type)
        if not pairs:
            continue
        pair = chosen.get(field.name)
        kind, numpy = pair if pair in pairs else pairs[0]
        columns.append(
            {
                "name": _column_name(field.name, field.name in stored_names, source, names),
                "field_name": field.name,
                "pandas_type": kind,
                "numpy_type": numpy,
                "metadata": column_metadata(field.type),
            }
        )
    # An index entry is kept only for a field that got a column entry, once, in source order.
    entries = {c["field_name"] for c in columns}
    index_columns = (
        [c for c in dict.fromkeys(c for c in stored if isinstance(c, str)) if c in entries]
        if isinstance(stored, list)
        else []
    )
    blob = {
        "index_columns": index_columns,
        "column_indexes": [_column_index_entry()] if index_columns else [],
        "columns": columns,
        "attributes": {},
        "creator": {"library": "pyarrow", "version": pa.__version__},
        "pandas_version": version,
    }
    return json.dumps(blob).encode()


# -- the rule ------------------------------------------------------------------------------------

# The one registry of schema-level keys an output file may carry. F38 (opt-in metadata preserve)
# adds a policy argument to `output_schema` and `output_table`; nothing else changes here.
_ALLOWED_SCHEMA_KEYS: Final[Mapping[bytes, Callable[[bytes, pa.Schema], bytes | None]]] = {
    _PANDAS: _sanitize_pandas_blob,
}


def sanitized_schema_metadata(
    meta: Mapping[bytes, bytes] | None, *, for_schema: pa.Schema
) -> dict[bytes, bytes] | None:
    """The schema metadata an output file may carry, or `None` when nothing remains.

    `for_schema` is the final output schema: a sanitizer reads field names and Arrow types from
    it, never from `meta`. Call only through `output_schema` and `attach_output_metadata`.
    """
    kept: dict[bytes, bytes] = {}
    for key, sanitize in _ALLOWED_SCHEMA_KEYS.items():
        raw = (meta or {}).get(key)
        cleaned = sanitize(raw, for_schema) if raw is not None else None
        if cleaned is not None:
            kept[key] = cleaned
    return kept or None


def _with_carried_entries(
    meta: Mapping[bytes, bytes] | None,
    carried_meta: Mapping[bytes, bytes] | None,
    carried: Collection[str],
) -> Mapping[bytes, bytes] | None:
    """`meta` with the source's pandas `columns` entry for each carried column added, so a carried
    column keeps the dtype hint (`Int64`, `string`) its source gave it. Only entries for names in
    `carried` move, and the sanitizer still rebuilds every entry from the output schema."""
    source_raw = (carried_meta or {}).get(_PANDAS)
    if source_raw is None or not carried:
        return meta
    try:
        source = strict_json_loads(source_raw, max_int_digits=None)
        raw = (meta or {}).get(_PANDAS)
        built = strict_json_loads(raw, max_int_digits=None) if raw is not None else {}
    except (StrictJsonError, RecursionError):
        return meta
    if not isinstance(source, dict) or not isinstance(built, dict):
        return meta
    have = _source_entries(built.get("columns"))
    extra = [
        e
        for n, e in _source_entries(source.get("columns")).items()
        if n in carried and n not in have
    ]
    columns = built.get("columns")
    merged = {**built, "columns": [*(columns if isinstance(columns, list) else []), *extra]}
    return {**(meta or {}), _PANDAS: json.dumps(merged).encode()}


def attach_output_metadata(
    schema: pa.Schema,
    meta: Mapping[bytes, bytes] | None,
    *,
    carried: Collection[str],
    carried_meta: Mapping[bytes, bytes] | None = None,
) -> pa.Schema:
    """`schema` with its schema metadata replaced by the sanitized form of `meta`.

    `carried` names the columns that are the untouched source field (a passthrough column is the
    source field by contract, so its field metadata stays). Every other column is rebuilt with no
    field metadata at any depth: a masked or generated column's source metadata can describe the
    values it replaced. Callers name the carried set from the plan, never from values. The writers
    strip field metadata again; this is the in-memory entry.

    `carried_meta` is the source's schema metadata: its pandas entry for a carried column rides
    into the blob so that column reads back with the dtype the source named."""
    keep = frozenset(carried)
    fields = [f if f.name in keep else _field(f) for f in schema]
    meta = _with_carried_entries(meta, carried_meta, keep)
    source_items = tuple(meta.items()) if meta else ()
    kept = _kept_metadata(source_items, tuple((f.name, f.type) for f in fields))
    out = pa.schema(fields)
    return out.with_metadata(dict(kept)) if kept else out.remove_metadata()


@lru_cache(maxsize=256)
def _kept_metadata(
    source_items: tuple[tuple[bytes, bytes], ...], columns: tuple[tuple[str, pa.DataType], ...]
) -> tuple[tuple[bytes, bytes], ...]:
    """The sanitized schema metadata for one (source metadata, output schema) pair, computed once.

    The out-of-core builders call `attach_output_metadata` for every batch; the blob only changes
    with the source metadata or the output schema, so a table pays the JSON rebuild once."""
    bare = pa.schema([pa.field(name, typ) for name, typ in columns])
    kept = sanitized_schema_metadata(dict(source_items), for_schema=bare)
    return tuple(kept.items()) if kept else ()


def output_schema(schema: pa.Schema) -> pa.Schema:
    """`schema` with no field metadata at any depth and only the allowed schema keys."""
    return attach_output_metadata(schema, schema.metadata, carried=())


def output_table(table: pa.Table) -> pa.Table:
    """`table` under `output_schema`, with each date column over buffers it owns. The types are
    equal, so the cast copies no buffers; a table with no date column that already conforms is
    returned as is."""
    target = output_schema(table.schema)
    conformed = table if table.schema.equals(target, check_metadata=True) else table.cast(target)
    return own_date_columns(conformed)
