"""Shared builders for the bounded Parquet profile tests (PREFLIGHT-ARROW-PROFILE S1b).

One table is offered to the readers the bounded profile meets (local Parquet, S3, GCS, a supplied
`pa.Table`) through the one choke point `_profile_one_source`. The reference is the merge base's own output, pinned in `pins/base_profiles.json` and
recorded by a separate interpreter running the base checkout. Its inputs are rebuilt here from
pyarrow and pandas alone, so no code under test computes an expected value.
"""

from __future__ import annotations

import atexit
import hashlib
import io
import json
import os
import pickle
import random
import subprocess
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from decoy_engine.contracts.column_shape import ColumnShape
from decoy_engine.profile._readers import ProfileSource, build_profile_source
from decoy_engine.profile._readers_resident import ResidentTableSource
from decoy_engine.profile._source import _profile_one_source
from decoy_engine.profile._types import ColumnProfile, PIIClass, TableProfile
from tests.unit.profile.test_duplicate_header_readers import _stub_cloud

READER_KINDS = ("local", "s3", "gcs", "resident")
PARQUET_KINDS = ("local", "s3", "gcs")
FILE_FORMAT = {"local": "parquet", "s3": "parquet", "gcs": "parquet", "resident": "table"}
SAFE_FAILURE = r"^bounded source profile failed \(\w+\)$"


def parquet_bytes(table: pa.Table, *, row_group_size: int | None = None) -> bytes:
    buf = io.BytesIO()
    pq.write_table(table, buf, row_group_size=row_group_size)
    return buf.getvalue()


def make_reader(
    kind: str,
    table: pa.Table,
    data: bytes,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> ProfileSource:
    """`kind` reader over `data` (a Parquet file) or, for `resident`, over `table`."""
    if kind == "resident":
        return ResidentTableSource(table)
    if kind == "local":
        path = tmp_path / "t.parquet"
        path.write_bytes(data)
        return build_profile_source({"type": "file", "format": "parquet", "path": str(path)})
    _stub_cloud(monkeypatch, data, kind)
    descriptor: dict[str, Any] = {"type": kind, "format": "parquet", "bucket": "b"}
    descriptor["key" if kind == "s3" else "object"] = "t.parquet"
    return build_profile_source(descriptor)


def bounded_profile(
    reader: ProfileSource,
    kind: str,
    *,
    sample_rows: int = 10_000,
    declared_pk: frozenset[str] = frozenset(),
    fk_specs: dict[str, tuple[str, str]] | None = None,
    rng: random.Random | None = None,
) -> TableProfile:
    return _profile_one_source(
        reader,
        table_name="t",
        declared_pk_cols=declared_pk,
        fk_specs=fk_specs or {},
        sample_rows=sample_rows,
        residency="bounded",
        rng=rng or random.Random(0),
        source_format=FILE_FORMAT[kind],
    )


class BaseRaisedError(Exception):
    """The merge base raised on this case (its text is not pinned)."""


PINS = Path(__file__).parent / "pins" / "base_profiles.json"
_RECORD_ENV = "DECOY_RECORD_BASE_SRC"
_pins: dict[str, Any] | None = None
_server: subprocess.Popen[bytes] | None = None
_flushed = False


_PANDAS_OPTIONS = ("mode.use_inf_as_na", "future.infer_string")


def _pandas_options() -> dict[str, Any]:
    """The pandas options that change a profile; part of the case, so each setting is pinned."""
    found: dict[str, Any] = {}
    for name in _PANDAS_OPTIONS:
        try:
            found[name] = pd.get_option(name)
        except (KeyError, ValueError, pd.errors.OptionError):
            continue
    return found


def _case_key(kind: str, table: pa.Table, meta: dict[str, Any]) -> str:
    """Names the case from its inputs alone: the format, the table and the walk arguments.

    The table, not the Parquet bytes it was written to: a Parquet writer may order the
    dictionary of a repeated-value column differently from run to run, so the bytes would name
    one case by several keys (`data` is always `parquet_bytes(table)` here)."""
    digest = hashlib.sha256(kind.encode())
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, table.schema) as writer:
        writer.write_table(table)
    digest.update(sink.getvalue().to_pybytes())
    digest.update(
        repr(sorted((k, sorted(v) if k == "declared_pk" else v) for k, v in meta.items())).encode()
    )
    return digest.hexdigest()


def _load_pins() -> dict[str, Any]:
    global _pins
    if _pins is None:
        _pins = json.loads(PINS.read_text()) if PINS.exists() else {}
    return _pins


def _record_case(
    kind: str, table: pa.Table, data: bytes, meta: dict[str, Any], base_src: str
) -> dict[str, Any]:
    """The pin for one case, recorded only when re-recording. The merge base's own reader and walk
    both run in the child interpreter, so a reader failure is pinned like a walk failure and no
    code of the current checkout decides an outcome."""
    atexit.register(_flush_pins)  # idempotent: the pins are written once, at exit
    request = {
        **meta,
        "kind": kind,
        "table": table,
        "data": data,
        "source_format": FILE_FORMAT[kind],
    }
    return _record(request, base_src)


def _record(request: dict[str, Any], base_src: str) -> dict[str, Any]:
    """Ask a separate interpreter running the merge base's walk; used only to re-record pins."""
    global _server
    if _server is None:
        env = {**os.environ, "PYTHONPATH": base_src}
        script = Path(__file__).with_name("base_walk_server.py")
        _server = subprocess.Popen(  # noqa: S603  (fixed script, recording only)
            [sys.executable, str(script)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=env
        )
    assert _server.stdin is not None and _server.stdout is not None
    pickle.dump(request, _server.stdin)
    _server.stdin.flush()
    return pickle.load(_server.stdout)  # noqa: S301  (our own child process)


def _flush_pins() -> None:
    global _flushed
    if _flushed:
        return
    _flushed = True
    if _server is not None and _server.stdin is not None:
        _server.stdin.close()
    if _pins is not None and os.environ.get(_RECORD_ENV):
        PINS.parent.mkdir(exist_ok=True)
        PINS.write_text(json.dumps(_pins, sort_keys=True, separators=(",", ":")) + "\n")


def _profile_from_json(raw: dict[str, Any]) -> TableProfile:
    columns = tuple(
        ColumnProfile(
            **{
                **c,
                "shape": ColumnShape(c["shape"]),
                "pii_class": None if c["pii_class"] is None else PIIClass(c["pii_class"]),
                "fk_target": None if c["fk_target"] is None else tuple(c["fk_target"]),
            }
        )
        for c in raw["columns"]
    )
    return TableProfile(
        name=raw["name"],
        row_count=raw["row_count"],
        columns=columns,
        row_count_exact=raw["row_count_exact"],
    )


def base_profile(
    kind: str,
    table: pa.Table,
    data: bytes,
    *,
    sample_rows: int = 10_000,
    declared_pk: frozenset[str] = frozenset(),
    fk_specs: dict[str, tuple[str, str]] | None = None,
) -> TableProfile:
    """What the bounded profile gave at the merge base, from a pinned file; raises `BaseRaisedError`
    where base raised.

    The pins were recorded by running the base checkout's own walk in another interpreter (set
    `DECOY_RECORD_BASE_SRC` to that checkout's `src` to re-record), so no code under test
    computes an expected value."""
    meta: dict[str, Any] = {
        "sample_rows": sample_rows,
        "declared_pk": declared_pk,
        "fk_specs": fk_specs or {},
        "options": _pandas_options(),
    }
    # The key names the case from its inputs alone, so a case whose base reader refused the table
    # is looked up in the pins like any other and never answered by the current environment.
    key = _case_key(kind, table, meta)
    pins = _load_pins()
    base_src = os.environ.get(_RECORD_ENV)
    if base_src and key not in pins:
        pins[key] = _record_case(kind, table, data, meta, base_src)
    if key not in pins:
        pytest.fail(f"no pinned base profile for case {key[:12]}; re-record with {_RECORD_ENV}")
    pinned = pins[key]
    if "raises" in pinned:
        raise BaseRaisedError(pinned["raises"])
    return _profile_from_json(pinned["profile"])


def _flat_temporal_schema(schema: pa.Schema) -> bool:
    """The spec of the one place a base failure may become a success: unique names, no pandas
    footer, only dates, nanosecond times, text and integers, and at least one date or time."""
    if b"pandas" in (schema.metadata or {}) or len(set(schema.names)) != len(schema.names):
        return False
    types = [f.type for f in schema]
    temporal = [pa.types.is_date32(t) or (pa.types.is_time64(t) and t.unit == "ns") for t in types]
    return any(temporal) and all(
        is_t or pa.types.is_string(t) or pa.types.is_integer(t)
        for t, is_t in zip(types, temporal, strict=True)
    )


def assert_same_profile(ours: TableProfile, oracle: TableProfile, label: str) -> None:
    """Field by field, so a failure names the column and the field."""
    assert [c.name for c in ours.columns] == [c.name for c in oracle.columns], label
    for a, b in zip(ours.columns, oracle.columns, strict=True):
        assert a == b, (
            label,
            a.name,
            [f for f in a.__dataclass_fields__ if getattr(a, f) != getattr(b, f)],
        )
    assert ours == oracle, label


def assert_matches_base(
    table: pa.Table,
    kind: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    **kw: Any,
) -> bool:
    """The bounded profile equals base where base succeeds; where base raises, the bounded
    profile raises the value-free error. Returns whether base succeeded."""
    try:
        data = parquet_bytes(table) if kind != "resident" else b""
    except (pa.ArrowNotImplementedError, pa.ArrowInvalid, pa.ArrowTypeError):
        pytest.skip("parquet does not store this type")
    reader = make_reader(kind, table, data, tmp_path, monkeypatch)
    try:
        oracle = base_profile(kind, table, data, **kw)
    except BaseRaisedError:
        read_back = pq.ParquetFile(io.BytesIO(data)).schema_arrow if data else table.schema
        if data and _flat_temporal_schema(read_back):
            # The one place a base failure may become a success: a flat date/time schema.
            assert any(c.dtype == "object" for c in bounded_profile(reader, kind, **kw).columns)
        else:
            with pytest.raises(ValueError, match=SAFE_FAILURE):
                bounded_profile(reader, kind, **kw)
        return False
    assert_same_profile(bounded_profile(reader, kind, **kw), oracle, kind)
    return True
