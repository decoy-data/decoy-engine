"""What pyarrow writes into the pandas blob, per Arrow type, at the pinned pyarrow and pandas.

A pair is `(pandas_type, numpy_type)` as it appears in one `columns` entry. `PLAIN_PAIRS` holds
the thirteen plain numpy pairs native admission accepts. `pairs_for` lists every pair pyarrow
writes for a type, the plain pair first; a library bump that writes a new pair turns
`tests/unit/pandas_meta/test_descriptors.py` red. `column_metadata` derives a column's
`metadata` member from the Arrow type alone: a count of source categories is not derivable from
a schema, so it is never produced.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, Final

import pyarrow as pa

Pair = tuple[str, str]

# The one `column_indexes` entry pyarrow writes for a frame whose index it stores.
COLUMN_INDEX_ENTRY: Final[Mapping[str, Any]] = MappingProxyType(
    {
        "name": None,
        "field_name": None,
        "pandas_type": "unicode",
        "numpy_type": "object",
        "metadata": MappingProxyType({"encoding": "UTF-8"}),
    }
)

PLAIN_PAIRS: Final[Mapping[pa.DataType, Pair]] = MappingProxyType(
    {
        pa.bool_(): ("bool", "bool"),
        pa.int8(): ("int8", "int8"),
        pa.int16(): ("int16", "int16"),
        pa.int32(): ("int32", "int32"),
        pa.int64(): ("int64", "int64"),
        pa.uint8(): ("uint8", "uint8"),
        pa.uint16(): ("uint16", "uint16"),
        pa.uint32(): ("uint32", "uint32"),
        pa.uint64(): ("uint64", "uint64"),
        pa.float32(): ("float32", "float32"),
        pa.float64(): ("float64", "float64"),
        pa.string(): ("unicode", "object"),
        pa.large_string(): ("unicode", "object"),
    }
)

# pandas' masked extension dtypes name the same data with a capitalised numpy_type.
_MASKED: Final = {"bool": "boolean", "float32": "Float32", "float64": "Float64"}
_STRING_PAIRS: Final = (("unicode", "string"), ("object", "string"), ("object", "object"))


def _plain(t: pa.DataType) -> Pair | None:
    """The plain pair pyarrow writes for `t`, or `None` for a type outside the registry."""
    if (pair := PLAIN_PAIRS.get(t)) is not None:
        return pair
    types = pa.types
    if isinstance(t, pa.BaseExtensionType):
        # pandas' own extension types: the numpy_type names the validated parameters.
        name = t.extension_name
        if name == "pandas.period":
            return ("object", f"period[{t.freq}]")
        if name == "pandas.interval":
            return ("object", f"interval[{t.subtype}, {t.closed}]")
        return None
    if types.is_float16(t):
        return ("float16", "float16")
    if types.is_binary(t) or types.is_large_binary(t) or types.is_fixed_size_binary(t):
        return ("bytes", "object")
    if types.is_date(t):
        return ("date", "object")
    if types.is_time(t):
        return ("time", "object")
    if types.is_decimal(t):
        return ("decimal", "object")
    if types.is_timestamp(t):
        return ("datetimetz" if t.tz else "datetime", f"datetime64[{t.unit}]")
    if types.is_duration(t):
        return ("object", f"timedelta64[{t.unit}]")
    if types.is_dictionary(t):
        return ("categorical", str(t.index_type))
    if types.is_null(t):
        return ("empty", "object")
    return None


def pairs_for(t: pa.DataType) -> tuple[Pair, ...]:
    """Every pair pyarrow writes for `t`, plain pair first; empty for a type outside the registry."""
    plain = _plain(t)
    if plain is None:
        return ()
    kind, numpy = plain
    out = [plain]
    if t in PLAIN_PAIRS or (pa.types.is_timestamp(t) and not t.tz):
        out.append((kind, f"{t}[pyarrow]"))  # pandas ArrowDtype
    if pa.types.is_integer(t):
        out.append((kind, "UInt" + numpy[4:] if numpy.startswith("uint") else numpy.capitalize()))
    elif numpy in _MASKED:
        out.append((kind, _MASKED[numpy]))
    elif pa.types.is_string(t) or pa.types.is_large_string(t):
        out.extend(_STRING_PAIRS)
    return tuple(out)


def column_metadata(t: pa.DataType) -> dict[str, Any] | None:
    """The `metadata` member of a `columns` entry, derived from the Arrow type only."""
    if pa.types.is_timestamp(t) and t.tz:
        return {"timezone": t.tz}
    if pa.types.is_decimal(t):
        return {"precision": t.precision, "scale": t.scale}
    if pa.types.is_dictionary(t):
        return {"ordered": t.ordered}
    return None
