"""Loader for reference tables (SP-06 / P5.INFRA.3).

Pattern: pyarrow Parquet I/O (apache/arrow, Apache-2.0).
See: https://arrow.apache.org/docs/python/parquet.html

Loads shipped tables from the ``data/`` sub-directory or a customer-
provided path. Version mismatch between the expected shipped version and
the file's metadata is logged as a WARNING and the table is still used
(graceful degradation -- the swap-in hook allows custom tables that may
not carry engine version metadata).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pyarrow as pa

from decoy_engine import fileaccess
from decoy_engine._arrow_types import is_text
from decoy_engine._config_text import (
    Expected,
    Kind,
    Problem,
    Refusal,
    config_position,
    config_refusal,
    read_config,
)
from decoy_engine._error_base import raise_bare
from decoy_engine.fileaccess import (
    FileAccess,
    FileAccessDenied,
    FileAccessReadError,
    FileHandle,
    FileRequest,
    FileRole,
)
from decoy_engine.fileaccess.adapters import arrow as arrow_adapter
from decoy_engine.reference_tables._registry import SHIPPED_TABLES, shipped_path
from decoy_engine.reference_tables._types import ReferenceTable

_LOG = logging.getLogger(__name__)

# Expected version for each shipped table, from the one shipped-table registry. Files that
# carry a ``decoy_table_version`` metadata key are checked against this map.
_SHIPPED_VERSIONS: dict[str, str] = {t.name: t.version for t in SHIPPED_TABLES.values()}


_CUSTOMER_PREFIX = "customer:"


@fileaccess.entry_point
def load_table(
    name: str, path: Path | None = None, *, file_access: FileAccess | None = None
) -> ReferenceTable:
    """Load a reference table by name.

    When ``path`` is omitted, loads the shipped table of that name; a bare name that is not
    in the shipped-table registry is refused without any file access (it is a lookup key,
    never a path). When ``path`` is provided, loads that file instead (customer-provided
    swap-in hook -- the file must follow the same schema convention: an ``id``
    column plus domain columns), through the file-access policy.

    Customer-provided tables can also be specified by prefixing the ``name``
    with ``"customer:"`` (e.g. ``"customer:/path/to/my_table.parquet"``). This
    is the canonical customer-provided reference table pathway (SP-08b). The
    file path follows the prefix directly without a separator.

    Args:
        name: Table identifier (e.g. ``"us_zip5_city_state"``) or a
            ``"customer:/path/to/file.parquet"`` reference (SP-08b).
        path: Optional override path to a Parquet file. Takes precedence over
            any ``"customer:"`` prefix in ``name``.
        file_access: The policy that decides which files may be read (default: ambient CLI).

    Returns:
        A :class:`~decoy_engine.reference_tables._types.ReferenceTable`.

    Raises:
        FileNotFoundError: No shipped table for ``name`` and no ``path``.
        ValueError: File is not readable as Parquet, or lacks the ``id``
            column.
    """
    # Resolve customer: prefix -> explicit path.
    if path is None and name.startswith(_CUSTOMER_PREFIX):
        customer_path_str = name[len(_CUSTOMER_PREFIX) :]
        path = Path(customer_path_str)
        # Use the basename (without extension) as the logical name for version checking.
        name = path.stem

    handle: FileHandle
    if path is None:
        if name not in SHIPPED_TABLES:
            # A rejected name may be a path or URL a caller handed in as the lookup key, so the
            # message names nothing under any policy (X4). Membership is checked before any file
            # access, so this is a lookup miss, never an existence oracle.
            raise FileNotFoundError(
                "no shipped reference table of that name. Provide a path= override or a "
                "'customer:' reference."
            )
        handle = fileaccess.engine_handle(shipped_path(name))
    else:
        handle = fileaccess.current().open_read(
            FileRequest(
                FileRole.REFERENCE,
                "read",
                str(path),
                fileaccess.position_key("joint_mask.reference"),
            )
        )

    try:
        # The route's own typed file-access errors pass unchanged under either policy.
        arrow_table = read_config(
            lambda: arrow_adapter.read_table(handle),
            config_position("reference_table"),
            _refusal,
            passes=(FileAccessDenied, FileAccessReadError),
        )
    finally:
        handle.close()

    at_id = config_position("reference_table", "id")
    if "id" not in arrow_table.schema.names:
        raise_bare(
            _refusal(
                config_refusal(
                    at_id,
                    Problem.MISSING,
                    expected=Expected.INT64,
                    hint="All reference tables must have a stable int64 'id' column",
                )
            )
        )

    id_type = arrow_table.schema.field("id").type
    if id_type != pa.int64():
        # The kind only: a rendered Arrow type carries file-authored text (a timestamp zone,
        # struct field names), so it never reaches the message.
        raise_bare(
            _refusal(
                config_refusal(
                    at_id,
                    Problem.WRONG_TYPE,
                    expected=Expected.INT64,
                    got_kind=_type_kind(id_type),
                    hint=(
                        "All reference tables must have a stable int64 'id' column "
                        "(schema convention -- see reference_tables/__init__.py)"
                    ),
                )
            )
        )

    _check_version(name, arrow_table)
    return ReferenceTable(arrow_table, name=name)


# Checked in order; the first predicate that holds names the kind. Engine literals only.
_TYPE_KINDS: tuple[tuple[Kind, Any], ...] = (
    (Kind.INTEGER, pa.types.is_integer),
    (Kind.FLOATING_POINT, pa.types.is_floating),
    (Kind.DECIMAL, pa.types.is_decimal),
    (Kind.BOOLEAN, pa.types.is_boolean),
    (Kind.STRING, is_text),
    (Kind.BINARY, lambda t: pa.types.is_binary(t) or pa.types.is_large_binary(t)),
    (Kind.TIMESTAMP, pa.types.is_timestamp),
    (Kind.DATE, pa.types.is_date),
    (Kind.TIME, pa.types.is_time),
    (Kind.DURATION, pa.types.is_duration),
    (Kind.DICTIONARY, pa.types.is_dictionary),
    (Kind.NESTED, pa.types.is_nested),
)


def _type_kind(arrow_type: pa.DataType) -> Kind:
    """A value-free closed kind for an Arrow type."""
    return next((kind for kind, test in _TYPE_KINDS if test(arrow_type)), Kind.OTHER)


def _refusal(refusal: Refusal) -> ValueError:
    return ValueError(refusal.text)


def _check_version(name: str, table: Any) -> None:
    """Emit a WARNING when file version metadata does not match expected.

    The diagnostics name the table, never its location."""
    expected = _SHIPPED_VERSIONS.get(name)
    if expected is None:
        return  # Unknown table name: no version expectation, skip check.

    schema_meta = table.schema.metadata or {}
    actual_bytes = schema_meta.get(b"decoy_table_version")
    if actual_bytes is None:
        _LOG.debug(
            "reference table %r has no decoy_table_version metadata "
            "(expected %r). Continuing with loaded data.",
            name,
            expected,
        )
        return

    actual = actual_bytes.decode("utf-8", errors="replace")
    if actual != expected:
        _LOG.warning(
            "reference table %r version mismatch: engine "
            "expects %r. Using the available version. If this "
            "is a customer-provided table, update the table or adjust "
            "_SHIPPED_VERSIONS in _loader.py.",
            name,
            expected,
        )
