"""TargetDescriptor: discriminated union over output-target variants.

S15-CLOUD-TGT-S3GCS (2026-05-30): structural mirror of SourceDescriptor.
Adds `S3Target` and `GCSTarget` alongside the existing `FileTarget`.
The discriminator is the literal `type` field.

Credentials handling mirrors S14 sources: `credentials_ref` is OPAQUE to
the engine; the platform layer resolves it against its credentials store
before the SDK call. The engine layer is not a secrets boundary
(ISO/IEC 27002 §8.24 / §5.17).

Write semantics (S15): cloud targets write to a temporary key
`<key>.<job_id>.tmp`, head-object verify, then server-side copy_object to
the canonical key and delete the tmp. A partial-write never leaves a
half-written canonical object (Q12 pattern carry from QA review of the
V1 DB connector's no-transaction to_sql). Verification is at the
platform layer (`api/jobs/v2_runner.py:_materialize_output`); this module
is the schema only.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from pathlib import PurePath
from typing import Annotated, ClassVar, Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

from decoy_engine.config._fixed_width import FixedWidthLayout
from decoy_engine.errors import ConfigRuleError


class FileTarget(BaseModel):
    """A local-filesystem CSV, Parquet, or fixed-width target.

    Mirrors `FileSource` on the output side: `layout` carries the column-spec
    for `format=="fixed_width"` (see `FixedWidthLayout`); it is required for
    that format and forbidden for `csv` / `parquet`. Fixed-width output is
    materialized by `write_fixed_width`, which inverts `read_fixed_width` over
    the same `FixedWidthLayout` contract.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["file"]
    # The field a duplicate-destination problem points at.
    destination_field: ClassVar[str] = "path"
    format: Literal["csv", "parquet", "fixed_width"]
    path: str
    layout: FixedWidthLayout | None = Field(
        default=None,
        description=(
            "Column-spec for format=='fixed_width'; required for that "
            "format, forbidden (must be omitted/None) for csv/parquet."
        ),
    )

    @model_validator(mode="after")
    def _validate_layout_matches_format(self) -> FileTarget:
        if self.format == "fixed_width" and self.layout is None:
            raise ConfigRuleError(
                "FileTarget: format='fixed_width' requires a `layout` column-spec"
            )
        if self.format != "fixed_width" and self.layout is not None:
            raise ConfigRuleError(
                "FileTarget: `layout` is only valid when format='fixed_width' "
                f"(got format={self.format!r})"
            )
        return self


class S3Target(BaseModel):
    """An S3 (or S3-compatible) CSV / Parquet target.

    Symmetric with `S3Source`. The platform writes via the atomic-move
    pattern (Q12 carry): upload to `<key>.<job_id>.tmp`, server-side
    `copy_object` to the canonical key on verify, then delete the tmp.
    A mid-upload failure leaves the canonical key untouched.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["s3"]
    # The field a duplicate-destination problem points at.
    destination_field: ClassVar[str] = "key"
    format: Literal["csv", "parquet"]
    bucket: str = Field(..., min_length=1, max_length=255)
    key: str = Field(..., min_length=1)
    region: str | None = None
    endpoint_url: str | None = Field(
        default=None,
        description=(
            "Override the AWS endpoint (e.g. http://localhost:9000 for MinIO, "
            "https://<account>.r2.cloudflarestorage.com for Cloudflare R2). "
            "Leave None for real AWS S3."
        ),
    )
    credentials_ref: str | None = Field(
        default=None,
        description=(
            "Opaque credentials identifier the platform resolves at run time. "
            "The engine never sees raw secrets; when None the SDK walks its "
            "default credential chain (env vars / instance profile / etc.)."
        ),
    )


class GCSTarget(BaseModel):
    """A Google Cloud Storage CSV / Parquet target.

    Symmetric with `GCSSource`. Atomic-move pattern at the platform layer
    mirrors `S3Target`.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["gcs"]
    # The field a duplicate-destination problem points at.
    destination_field: ClassVar[str] = "object"
    format: Literal["csv", "parquet"]
    bucket: str = Field(..., min_length=1, max_length=255)
    object: str = Field(..., min_length=1)
    credentials_ref: str | None = Field(
        default=None,
        description=(
            "Opaque credentials identifier the platform resolves at run time. "
            "The engine never sees raw secrets; when None the SDK uses GCP "
            "ADC (Application Default Credentials)."
        ),
    )


TargetDescriptor = Annotated[
    FileTarget | S3Target | GCSTarget,
    Field(discriminator="type"),
]


def _target_identity(target: FileTarget | S3Target | GCSTarget) -> tuple[str, ...]:
    """The one definition of "same destination" for a validated output target.

    S3 compares by endpoint, bucket and key, GCS by bucket and object. A file path with no `..`
    component is normalized so `out/a.csv` and `out/./a.csv` are one destination. A path with `..`
    keeps its text because the OS resolves `..` after a symlink from the link target, so
    normalizing could merge two files. Filesystem aliasing is the writer's concern.
    """
    if isinstance(target, FileTarget):
        if os.pardir in PurePath(target.path).parts:
            return ("file", target.path)
        return ("file", os.path.normpath(target.path))
    if isinstance(target, S3Target):
        # The endpoint names the store (AWS, MinIO, R2...); "" is the AWS default.
        return ("s3", _endpoint_identity(target.endpoint_url), target.bucket, target.key)
    if isinstance(target, GCSTarget):
        return ("gcs", target.bucket, target.object)
    raise TypeError("unsupported target type has no destination identity")


def duplicate_target_groups(
    targets: Mapping[str, FileTarget | S3Target | GCSTarget], active_names: Iterable[str]
) -> list[list[str]]:
    """Table names that share one destination, each group of 2+ in mapping order.

    Only keys in `active_names` take part; a key that names no table is refused on its own by
    `unknown_target_names`, so it never reaches a writer.
    """
    active = set(active_names)
    by_identity: dict[tuple[str, ...], list[str]] = {}
    for name, target in targets.items():
        if name in active:
            by_identity.setdefault(_target_identity(target), []).append(name)
    return [names for names in by_identity.values() if len(names) > 1]


def unknown_target_names(targets: Iterable[str], table_names: Iterable[str]) -> list[str]:
    """Target keys that name no configured table, in mapping order.

    A key is a table name, compared exactly. A source name alone is not a target key, so a typo
    in a key is refused here instead of being skipped by the writers.
    """
    tables = set(table_names)
    return [name for name in targets if name not in tables]


def _endpoint_identity(url: str | None) -> str:
    # Only the scheme and host are case-insensitive (RFC 3986 section 6.2.2.1); a path
    # or user-info may name a different tenant by case alone.
    if not url:
        return ""
    parts = urlsplit(url)
    userinfo, at, hostport = parts.netloc.rpartition("@")
    netloc = f"{userinfo}{at}{hostport.lower()}"
    path = parts.path.removesuffix("/")
    return urlunsplit((parts.scheme.lower(), netloc, path, parts.query, parts.fragment))
