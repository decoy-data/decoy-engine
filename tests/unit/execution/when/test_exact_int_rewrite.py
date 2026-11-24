"""M2: deterministic Faker over a nullable integer column that an earlier gated joint mask rewrote.

The joint mask writes `n` as a secondary output. Faker must key from the written values, never
from the Arrow integers of the source. The job either gives exactly the Faker-only oracle on the
rewritten column or fails closed with a value-free error.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest

from tests.unit.execution.when import _write_support as ws

BIG = 2**60
SRC_N = [BIG, None, BIG + 1, 5]


def _faker() -> Any:
    return ws.seed(
        "faker",
        provider="person_email",
        backend_type="faker",
        cardinality_mode="reuse",
        deterministic=True,
        namespace="nm",
        provider_config=(("pool_size", 64),),
    )


def _table(n: list[int | None]) -> pa.Table:
    return pa.table(
        {
            "k": pa.array(["a", "b", "c", "d"]),
            "city": pa.array(["c0", "c1", "c2", "c3"]),
            "n": pa.array(n, type=pa.int64()),
        }
    )


@pytest.mark.parametrize("sequential", [False, True], ids=["full-frame", "sequential"])
def test_faker_keys_from_the_rewritten_integers_or_fails_closed(
    tmp_path: Path, sequential: bool
) -> None:
    ref = ws.reference(tmp_path / "r.parquet", city=["JC"], n=[7])
    joint = ws.joint(ref, ["city", "n"], when="k == 'a' or k == 'c'")
    run = ws.run_sequential if sequential else ws.run
    rewritten = [7, None, 7, 5]
    oracle = ws.run(ws.plan([("n", _faker())]), _table(rewritten), bound=(("n",),))
    try:
        out = run(ws.plan([("city", joint), ("n", _faker())]), _table(SRC_N), bound=(("n",),))
    except Exception as exc:
        assert getattr(exc, "code", None), type(exc).__name__
        assert str(BIG) not in str(exc) and str(BIG + 1) not in str(exc)
        return
    assert out.column("n").to_pylist() == oracle.column("n").to_pylist()
