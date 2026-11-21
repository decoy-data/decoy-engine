"""The ``decoy-publication/v1`` descriptor: one field declaration, its writer and its strict reader.

Pattern: Git content addressing plus RFC 8785 canonical JSON (Git object model, GPL-2.0 docs; RFC 8785, IETF). Keys and paths sort in Unicode code point order. See: https://www.rfc-editor.org/rfc/rfc8785.

Every published unit carries ``_decoy_publication.json``. Its bytes are the engine's one canonical
JSON form, ``decoy_engine._canonical.canonical_json_bytes`` (keys sorted in Unicode code point order, fixed separators, UTF-8
text as-is, no NaN), so equal content has equal bytes and
``descriptor_digest`` is a plain SHA-256 of them. ``result_id`` names the output content alone,
as Git names an object by its bytes: a domain-separated SHA-256 of the canonical artifact list.
It leaves out ``operation_id`` (the retry handle, Delta Lake's transaction identifier) and the
vault, which is judged by its rows, never by a digest of them.

One declaration (``DESCRIPTOR_FIELDS`` and the two nested ones, built from the shared specs in
``decoy_engine._canonical``) drives both directions, so the writer cannot emit what
the reader refuses. The reader is the persisted-reader contract: exact
version tag, every field present, no unknown field, exact built-in JSON types (``bool`` is never
an ``int``), bounded counts, closed tokens, ``re.fullmatch`` shapes, relative paths through the
engine's one component validator, no duplicate key, no non-finite number, canonical bytes, a
``result_id`` that recomputes, and at most 1 MiB. A refusal raises ``ValueError`` whose text is
``descriptor_refused:<check>`` with a closed check token and nothing from the bytes, raised
outside any parse handler so no exception context carries them.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import pairwise
from typing import Any, Final, Literal, NoReturn, cast

from decoy_engine._canonical import (
    CanonicalJsonError,
    CountSpec,
    ExactSpec,
    ListSpec,
    NullableSpec,
    ObjectSpec,
    OneOfSpec,
    RelPathSpec,
    ShapedSpec,
    Spec,
    attempt,
    canonical_json_bytes,
    parse_or_token,
)
from decoy_engine.fileaccess import DESCRIPTOR_NAME, is_valid_component
from decoy_engine.publication._types import (
    MAX_COUNT,
    OPERATION_ID_PATTERN,
    ROLES,
    UNIT_IMMUTABLE_DIRECTORY,
    UNITS,
    ArtifactSummary,
    Role,
    Unit,
    is_hex64,
    is_operation_id,
)
from decoy_engine.release import __version__

__all__ = [
    "ARTIFACT_FIELDS",
    "DESCRIPTOR_FIELDS",
    "DESCRIPTOR_NAME",
    "MAX_DESCRIPTOR_BYTES",
    "REFUSAL_PREFIX",
    "RESULT_DOMAIN",
    "SCHEMA",
    "VAULT_FIELDS",
    "Artifact",
    "Check",
    "Descriptor",
    "DescriptorVault",
    "build_descriptor",
    "compute_result_id",
    "decode_descriptor",
    "describe_declaration",
    "descriptor_digest",
    "encode_descriptor",
]

SCHEMA: Final = "decoy-publication/v1"
MAX_DESCRIPTOR_BYTES: Final = 1 << 20
RESULT_DOMAIN: Final = b"decoy-publication-result/v1\x00"
REFUSAL_PREFIX: Final = "descriptor_refused:"

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
    "artifacts_order",
    "result_id_mismatch",
    "not_canonical",
]

_VERSION_PATTERN: Final = r"[0-9][0-9A-Za-z.+!_-]{0,63}"
_VERSION = re.compile(_VERSION_PATTERN)
_HEX_PATTERN: Final = r"[0-9a-f]{64}"
# A JSON integer longer than this cannot be a count; refusing it before int() keeps a hostile
# digit run from costing quadratic time.
_MAX_INT_DIGITS: Final = 20


def _refuse(check: Check) -> NoReturn:
    raise ValueError(REFUSAL_PREFIX + check)


@dataclass(frozen=True)
class Artifact:
    """One measured file of the unit. ``path`` is relative to the unit root."""

    path: str
    role: Role
    rows: int
    sha256: str
    size: int

    def summary(self) -> ArtifactSummary:
        return ArtifactSummary(role=self.role, size=self.size, rows=self.rows, sha256=self.sha256)


@dataclass(frozen=True)
class DescriptorVault:
    """The vault a unit was bound with: its digest, byte size and entry count."""

    sha256: str
    size: int
    entry_count: int


@dataclass(frozen=True)
class Descriptor:
    """The typed descriptor; the same model is written and read."""

    schema: str
    unit: Unit
    operation_id: str
    result_id: str
    artifacts: tuple[Artifact, ...]
    vault: DescriptorVault | None
    engine_version: str


def _load(spec: Spec, raw: Any) -> Any:
    """``spec.load``; a spec's closed token becomes the descriptor refusal outside the handler."""
    value, refused = attempt(spec.load, raw)
    if refused is not None:
        _refuse(refused)
    return value


def _dump(spec: Spec, value: Any) -> Any:
    """``spec.dump``, refused the same way as :func:`_load`."""
    raw, refused = attempt(spec.dump, value)
    if refused is not None:
        _refuse(refused)
    return raw


_HEX = ShapedSpec(_HEX_PATTERN, is_hex64)
_COUNT = CountSpec(MAX_COUNT)
_SCHEMA_TAG = ExactSpec(SCHEMA)

ARTIFACT_FIELDS: Final[tuple[tuple[str, Spec], ...]] = (
    ("path", RelPathSpec(is_valid_component, DESCRIPTOR_NAME)),
    ("role", OneOfSpec(ROLES)),
    ("rows", _COUNT),
    ("sha256", _HEX),
    ("size", _COUNT),
)
VAULT_FIELDS: Final[tuple[tuple[str, Spec], ...]] = (
    ("sha256", _HEX),
    ("size", _COUNT),
    ("entry_count", _COUNT),
)
_ARTIFACT = ObjectSpec(Artifact, ARTIFACT_FIELDS)
DESCRIPTOR_FIELDS: Final[tuple[tuple[str, Spec], ...]] = (
    ("schema", _SCHEMA_TAG),
    ("unit", OneOfSpec(UNITS)),
    ("operation_id", ShapedSpec(OPERATION_ID_PATTERN, is_operation_id)),
    ("result_id", _HEX),
    ("artifacts", ListSpec(_ARTIFACT)),
    ("vault", NullableSpec(ObjectSpec(DescriptorVault, VAULT_FIELDS))),
    ("engine_version", ShapedSpec(_VERSION_PATTERN, lambda v: _VERSION.fullmatch(v) is not None)),
)
_DOCUMENT = ObjectSpec(Descriptor, DESCRIPTOR_FIELDS)


def describe_declaration() -> tuple[tuple[str, str], ...]:
    """The wire shape as text, for the declaration pin test."""
    return tuple((name, spec.describe()) for name, spec in DESCRIPTOR_FIELDS)


def _canonical_or_refuse(obj: Any) -> bytes:
    """``canonical_json_bytes``; a value with no canonical form (an unpaired surrogate, as an
    undecodable filename gives) is refused with the closed token, outside the handler."""
    data = b""
    try:
        data = canonical_json_bytes(obj)
    except CanonicalJsonError:
        pass
    if not data:
        _refuse("not_canonical")
    return data


def _ordered(artifacts: Iterable[Artifact]) -> tuple[Artifact, ...]:
    return tuple(sorted(artifacts, key=lambda a: a.path))


def compute_result_id(artifacts: Iterable[Artifact]) -> str:
    """The content identity of a unit: its artifacts in path order, nothing else."""
    listed = [_dump(_ARTIFACT, a) for a in _ordered(artifacts)]
    return hashlib.sha256(RESULT_DOMAIN + _canonical_or_refuse(listed)).hexdigest()


def descriptor_digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _check_document(raw: Any) -> Descriptor:
    """The declaration plus the document rules; the writer and the reader both end here."""
    descriptor: Descriptor = _load(_DOCUMENT, raw)
    paths = [a.path for a in descriptor.artifacts]
    if any(a >= b for a, b in pairwise(paths)):
        _refuse("artifacts_order")
    if compute_result_id(descriptor.artifacts) != descriptor.result_id:
        _refuse("result_id_mismatch")
    return descriptor


def build_descriptor(
    *,
    operation_id: str,
    artifacts: Iterable[Artifact],
    vault: DescriptorVault | None,
    unit: Unit = UNIT_IMMUTABLE_DIRECTORY,
    engine_version: str = __version__,
) -> Descriptor:
    """A checked descriptor for measured ``artifacts``, sorted, with its ``result_id``."""
    listed = list(artifacts)
    for artifact in listed:
        _load(_ARTIFACT, _dump(_ARTIFACT, artifact))
    ordered = _ordered(listed)
    descriptor = Descriptor(
        schema=SCHEMA,
        unit=unit,
        operation_id=operation_id,
        result_id=compute_result_id(ordered),
        artifacts=ordered,
        vault=vault,
        engine_version=engine_version,
    )
    return _check_document(_dump(_DOCUMENT, descriptor))


def encode_descriptor(descriptor: Descriptor) -> bytes:
    """The canonical bytes of ``descriptor``, refused on the same rules the reader applies."""
    document = _dump(_DOCUMENT, descriptor)
    _check_document(document)
    data = _canonical_or_refuse(document)
    if len(data) > MAX_DESCRIPTOR_BYTES:
        _refuse("oversize")
    return data


def _parse(data: bytes) -> Any:
    """Strict JSON; the shared decoder's closed token is the refusal check."""
    parsed, token = parse_or_token(data, _MAX_INT_DIGITS)
    if token is not None:
        _refuse(cast(Check, token))
    return parsed


def decode_descriptor(data: bytes) -> Descriptor:
    """Read a stored descriptor, refusing any malformed record (see the module docstring)."""
    if type(data) is not bytes:
        _refuse("wrong_type")
    if len(data) > MAX_DESCRIPTOR_BYTES:
        _refuse("oversize")
    raw = _parse(data)
    if type(raw) is not dict:
        _refuse("not_object")
    if "schema" not in raw:
        _refuse("schema_missing")
    _load(_SCHEMA_TAG, raw["schema"])
    descriptor = _check_document(raw)
    if _canonical_or_refuse(_dump(_DOCUMENT, descriptor)) != data:
        _refuse("not_canonical")
    return descriptor
