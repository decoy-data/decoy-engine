"""The two persisted records of a resume store: ``decoy-resume-run/v1`` and ``decoy-resume-table/v1``.

Pattern: RFC 8785 canonical JSON written through the engine's one canonical form, read back with
the strict persisted-reader rules F22 uses for ``decoy-publication/v1`` (``publication/_descriptor.py``).

``RunRecord`` is written once, first: the run and invocation ids, the F22 operation id, the
route, the ``RunFingerprint`` and the chunked tables in order. ``TableRecord`` is written last,
once per table, after its staged file is placed: the table's index and digests, the F22
``Artifact`` the file was measured as, the source digest taken before the table's chunk loop and
the fingerprint digest of the run. Every field is a digest, a count, a token or a path relative
to the run folder; no value, table name or key byte is stored.

One declaration per record drives both directions, built from ``decoy_engine._canonical._strict_spec``, so
the writer cannot emit what the reader refuses. The reader is the persisted-reader contract:
exact version tag, every field, no unknown field, exact built-in JSON types, ``re.fullmatch``
shapes (so ``"sha256:<hex>\\n"`` fails), relative paths through the engine's one component
validator, no duplicate key, no non-finite number, canonical bytes, and at most 64 KiB. A refusal
raises ``ValueError`` whose text is ``resume_record_refused:<check>`` with a closed check token
and nothing from the bytes, raised outside any parse handler so no exception context carries
them. The caller treats a record that raises as absent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from itertools import pairwise
from typing import Any, Final, Literal, NoReturn, cast

from decoy_engine._canonical import StrictJsonError, strict_json_loads
from decoy_engine._canonical._strict_spec import (
    CountSpec,
    ExactSpec,
    ListSpec,
    ObjectSpec,
    OneOfSpec,
    ShapedSpec,
    Spec,
    SpecCheck,
    SpecRefusedError,
)
from decoy_engine.delivery.resume._fingerprint import RunFingerprint
from decoy_engine.publication._descriptor import ARTIFACT_FIELDS, Artifact
from decoy_engine.publication._types import (
    MAX_COUNT,
    OPERATION_ID_PATTERN,
    is_hex64,
    is_operation_id,
)
from decoy_engine.records import canonical_bytes

__all__ = [
    "MAX_RECORD_BYTES",
    "REFUSAL_PREFIX",
    "ROUTE_CHUNKED",
    "RUN_SCHEMA",
    "TABLE_SCHEMA",
    "RunRecord",
    "TableEntry",
    "TableRecord",
    "decode_run_record",
    "decode_table_record",
    "encode_run_record",
    "encode_table_record",
]

RUN_SCHEMA: Final = "decoy-resume-run/v1"
TABLE_SCHEMA: Final = "decoy-resume-table/v1"
ROUTE_CHUNKED: Final = "chunked"
MAX_RECORD_BYTES: Final = 64 * 1024
REFUSAL_PREFIX: Final = "resume_record_refused:"

Check = Literal[
    "oversize",
    "not_json",
    "duplicate_key",
    "non_finite",
    "not_object",
    "schema_missing",
    "schema_unknown",
    "missing_field",
    "unknown_field",
    "wrong_type",
    "out_of_range",
    "bad_token",
    "bad_path",
    "components_invalid",
    "tables_order",
    "not_canonical",
]

# A JSON integer longer than this cannot be a count; refusing it before int() keeps a hostile
# digit run from costing quadratic time.
_MAX_INT_DIGITS: Final = 20

_RUN_ID_PATTERN: Final = r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}"
_INVOCATION_ID_PATTERN: Final = (
    r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
)
_LABEL_PATTERN: Final = r"[A-Za-z0-9][A-Za-z0-9._:+!-]{0,63}"
_KEY_CHECK_PATTERN: Final = r"[0-9a-f]{16}"
_TAGGED_PATTERN: Final = r"sha256:[0-9a-f]{64}"
_RUN_ID = re.compile(_RUN_ID_PATTERN)
_INVOCATION_ID = re.compile(_INVOCATION_ID_PATTERN)
_LABEL = re.compile(_LABEL_PATTERN)
_KEY_CHECK = re.compile(_KEY_CHECK_PATTERN)
_TAGGED = re.compile(_TAGGED_PATTERN)


def _fullmatch(pattern: re.Pattern[str]) -> Any:
    # fullmatch, not a `$` anchor: `$` also matches before a trailing newline.
    return lambda value: pattern.fullmatch(value) is not None


@dataclass(frozen=True)
class TableEntry:
    """One chunked table of the run: its position and two digests, never its name."""

    index: int
    name_digest: str
    binding_digest: str


@dataclass(frozen=True)
class RunRecord:
    """``RUN.json``: what the run is, written once before any table."""

    run_id: str
    invocation_id: str
    operation_id: str
    route: str
    fingerprint: RunFingerprint
    tables: tuple[TableEntry, ...]
    schema: str = RUN_SCHEMA


@dataclass(frozen=True)
class TableRecord:
    """One table's checkpoint, written after its staged file is placed and fsynced."""

    index: int
    name_digest: str
    binding_digest: str
    artifact: Artifact
    source_sha256: str
    fingerprint_digest: str
    schema: str = TABLE_SCHEMA


_TAGGED_DIGEST = ShapedSpec(_TAGGED_PATTERN, _fullmatch(_TAGGED))
_LABEL_SPEC = ShapedSpec(_LABEL_PATTERN, _fullmatch(_LABEL))
_COUNT = CountSpec(MAX_COUNT)

_FINGERPRINT_FIELDS: Final[tuple[tuple[str, Spec], ...]] = (
    ("config_hash", ShapedSpec(r"[0-9a-f]{64}", is_hex64)),
    ("components", ListSpec(ListSpec(_LABEL_SPEC))),
    ("key_check", ShapedSpec(_KEY_CHECK_PATTERN, _fullmatch(_KEY_CHECK))),
    ("key_version", _LABEL_SPEC),
    ("chunk_size", _COUNT),
)
_ENTRY_FIELDS: Final[tuple[tuple[str, Spec], ...]] = (
    ("index", _COUNT),
    ("name_digest", _TAGGED_DIGEST),
    ("binding_digest", _TAGGED_DIGEST),
)
RUN_FIELDS: Final[tuple[tuple[str, Spec], ...]] = (
    ("schema", ExactSpec(RUN_SCHEMA)),
    ("run_id", ShapedSpec(_RUN_ID_PATTERN, _fullmatch(_RUN_ID))),
    ("invocation_id", ShapedSpec(_INVOCATION_ID_PATTERN, _fullmatch(_INVOCATION_ID))),
    ("operation_id", ShapedSpec(OPERATION_ID_PATTERN, is_operation_id)),
    ("route", OneOfSpec((ROUTE_CHUNKED,))),
    ("fingerprint", ObjectSpec(RunFingerprint, _FINGERPRINT_FIELDS)),
    ("tables", ListSpec(ObjectSpec(TableEntry, _ENTRY_FIELDS))),
)
TABLE_FIELDS: Final[tuple[tuple[str, Spec], ...]] = (
    ("schema", ExactSpec(TABLE_SCHEMA)),
    ("index", _COUNT),
    ("name_digest", _TAGGED_DIGEST),
    ("binding_digest", _TAGGED_DIGEST),
    ("artifact", ObjectSpec(Artifact, ARTIFACT_FIELDS)),
    ("source_sha256", _TAGGED_DIGEST),
    ("fingerprint_digest", _TAGGED_DIGEST),
)
_RUN = ObjectSpec(RunRecord, RUN_FIELDS)
_TABLE = ObjectSpec(TableRecord, TABLE_FIELDS)
_SCHEMA_RUN_TAG = ExactSpec(RUN_SCHEMA)
_SCHEMA_TABLE_TAG = ExactSpec(TABLE_SCHEMA)


def _refuse(check: Check) -> NoReturn:
    raise ValueError(REFUSAL_PREFIX + check)


def _load(spec: Spec, raw: Any) -> Any:
    """``spec.load``; the spec's closed token becomes the record refusal outside the handler."""
    refused: SpecCheck | None = None
    value: Any = None
    try:
        value = spec.load(raw)
    except SpecRefusedError as error:
        refused = error.check
    if refused is not None:
        _refuse(refused)
    return value


def _dump(spec: Spec, value: Any) -> Any:
    refused: SpecCheck | None = None
    raw: Any = None
    try:
        raw = spec.dump(value)
    except SpecRefusedError as error:
        refused = error.check
    if refused is not None:
        _refuse(refused)
    return raw


def _check_run(record: RunRecord) -> RunRecord:
    """The document rules the field declaration cannot say."""
    fingerprint = record.fingerprint
    pairs = fingerprint.components
    if not pairs or any(len(pair) != 2 for pair in pairs):
        _refuse("components_invalid")
    if any(a > b for a, b in pairwise(pairs)):
        _refuse("components_invalid")
    if fingerprint.chunk_size < 1:
        _refuse("out_of_range")
    if any(a.index >= b.index for a, b in pairwise(record.tables)):
        _refuse("tables_order")
    return record


def _parse(data: bytes) -> Any:
    """Strict JSON; the shared decoder's closed token is the refusal check."""
    parsed: Any = None
    refused: Check | None = None
    try:
        parsed = strict_json_loads(data, max_int_digits=_MAX_INT_DIGITS)
    except StrictJsonError as error:
        refused = cast(Check, error.token)
    if refused is not None:
        _refuse(refused)
    return parsed


def _encode(document: Any) -> bytes:
    # Only a document the reader's own rules accepted gets here, so it has a canonical form.
    data = canonical_bytes(document)
    if len(data) > MAX_RECORD_BYTES:
        _refuse("oversize")
    return data


def _read(data: bytes, tag: ExactSpec) -> Any:
    """The parsed JSON object of a stored record whose ``schema`` is ``tag``."""
    if type(data) is not bytes:
        _refuse("wrong_type")
    if len(data) > MAX_RECORD_BYTES:
        _refuse("oversize")
    raw = _parse(data)
    if type(raw) is not dict:
        _refuse("not_object")
    if "schema" not in raw:
        _refuse("schema_missing")
    _load(tag, raw["schema"])
    return raw


def encode_run_record(record: RunRecord) -> bytes:
    """The canonical bytes of ``record``, refused on the same rules the reader applies."""
    document = _dump(_RUN, record)
    _check_run(_load(_RUN, document))
    return _encode(document)


def decode_run_record(data: bytes) -> RunRecord:
    """Read a stored ``RUN.json``, refusing any malformed record (see the module docstring)."""
    raw = _read(data, _SCHEMA_RUN_TAG)
    record = _check_run(_load(_RUN, raw))
    if canonical_bytes(_dump(_RUN, record)) != data:
        _refuse("not_canonical")
    return record


def encode_table_record(record: TableRecord) -> bytes:
    """The canonical bytes of ``record``, refused on the same rules the reader applies."""
    document = _dump(_TABLE, record)
    _load(_TABLE, document)
    return _encode(document)


def decode_table_record(data: bytes) -> TableRecord:
    """Read a stored table record, refusing any malformed record (see the module docstring)."""
    raw = _read(data, _SCHEMA_TABLE_TAG)
    record: TableRecord = _load(_TABLE, raw)
    if canonical_bytes(_dump(_TABLE, record)) != data:
        _refuse("not_canonical")
    return record
