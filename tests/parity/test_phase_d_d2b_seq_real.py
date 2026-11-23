"""Phase D / D2b: the REAL compiled companion across the SEQ FK shapes.

Needs the abi-3 companion; skipped (not weakened) on a box without it, where the stand-in suite
(`test_phase_d_d2b_seq_shapes.py`) covers the same routing. These tests run the real kernel and
check what only it can show: native SEQ output equals the SEQ Python path and the full-frame
oracle on every strict dimension for each shape, equals frozen literals captured from the
Python hash, and is the kernel's own result rather than a recomputation.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Callable
from typing import Any

import pyarrow as pa
import pytest

from decoy_engine.execution.native._crypto_ext import (
    CryptoExtensionUnavailableError,
    load_compiled_crypto_kernel,
)
from decoy_engine.relationships._graph import OrphanPolicy
from tests.parity import _d2b_shapes as s
from tests.parity import _strict_compare as sc
from tests.parity._d2a_seq_data import table_digest
from tests.parity._seq_witness import hide_companion, install, spy_python_hash
from tests.parity.test_phase_d_d2b_seq_shapes import _CASES, _IDS


def _companion_loads() -> bool:
    try:
        load_compiled_crypto_kernel()
    except CryptoExtensionUnavailableError:
        return False
    return True


pytestmark = pytest.mark.skipif(
    not _companion_loads(),
    reason="decoy-engine-native abi-3 companion not loadable; the companion-present job covers this",
)

_ALL_TRUE = dict.fromkeys(sc.DIMENSIONS, True)
_SENSITIVE = "a̖ࢗ"
_ORDERED = "a\u0316\u0897"

# Frozen from the pure-Python hash (SEQ run without the companion, equal to the oracle). Re-frozen
# after F13 (#339) moved keyed derivation from the job seed to the admitted secret, which changed
# every token; native, Python SEQ and the full-frame oracle all give these values.
_CHAIN_A = "f386170d7979fe129e3749ddec1c483088ed7a4d408193157703a5e9b86fa6d9"
_CHAIN_B_ORPHAN = "7862bfdf8bcacf27f076a5b2014b38eed3e2017f4a6e57c129c92e45c101a27f"
_CHAIN_C_ORPHAN = "a25dc20aaee57543e954177d53978602630238942c262d52e587756e7d350d72"
_SHARED_UNDER_P1 = "18189237cc6a556bd5cd02df6520f27fb598c480714c70c8eb4eb2c8128b28bd"
_SHARED_UNDER_P2 = "2fe9cba5be5f5d85ac3f6126450ec303c14acd2e1a1e4f76a847103fb4a5dfd1"


class RecordingRealKernel:
    """Delegates to the real compiled kernel and records each array it returned."""

    def __init__(self) -> None:
        self._real = load_compiled_crypto_kernel()
        self.results: list[pa.Array] = []

    def derive_batch(self, values: Any, **kwargs: Any) -> pa.Array:
        out = self._real.derive_batch(values, **kwargs)
        self.results.append(out)
        return out


@pytest.mark.parametrize(("name", "build", "rows"), _CASES, ids=_IDS)
def test_native_seq_agrees_with_the_oracle_on_every_strict_dimension(
    name: str, build: Callable[[], s.Shape], rows: list[int], monkeypatch: pytest.MonkeyPatch
) -> None:
    shape = build()
    full = s.run_full(shape).outputs
    python_rows = spy_python_hash(monkeypatch)
    seq = s.run_seq(shape).outputs
    assert python_rows == [], name
    for table in full:
        assert sc.compare_strict(full[table], seq[table]) == _ALL_TRUE, (name, table)


@pytest.mark.parametrize(("name", "build", "rows"), _CASES, ids=_IDS)
def test_native_and_python_seq_are_byte_identical_per_shape(
    name: str, build: Callable[[], s.Shape], rows: list[int], monkeypatch: pytest.MonkeyPatch
) -> None:
    native = s.run_seq(build())
    with monkeypatch.context() as m:
        hide_companion(m)
        python = s.run_seq(build())
    assert set(native.outputs) == set(python.outputs)
    for table in python.outputs:
        assert table_digest(native.outputs[table]) == table_digest(python.outputs[table]), (
            name,
            table,
        )
    backends = {
        e["executed_backend"]
        for e in native.quality_metrics["sequential_hash"]
        if e["path"] == "scalar"
    }
    assert backends == {"rust_companion"}


def test_chain_tokens_match_the_frozen_python_literals_hop_by_hop() -> None:
    out = s.run_seq(s.chain_shape(OrphanPolicy.REMAP)).outputs
    assert out["A"].column("k").to_pylist() == [_CHAIN_A]
    assert out["B"].column("k").to_pylist() == [_CHAIN_A, _CHAIN_B_ORPHAN]
    assert out["C"].column("k").to_pylist() == [_CHAIN_A, _CHAIN_B_ORPHAN, _CHAIN_C_ORPHAN]


def test_chain_orphans_are_the_kernels_own_results(monkeypatch: pytest.MonkeyPatch) -> None:
    kernel = install(monkeypatch, RecordingRealKernel())
    python_rows = spy_python_hash(monkeypatch)
    out = s.run_seq(s.chain_shape(OrphanPolicy.REMAP)).outputs
    returned = sorted(r.to_pylist()[0] for r in kernel.results)
    assert returned == sorted([_CHAIN_A, _CHAIN_B_ORPHAN, _CHAIN_C_ORPHAN])
    assert out["C"].column("k").to_pylist()[2] in returned
    assert python_rows == []


def test_multi_parent_shared_key_resolves_to_the_first_declared_parent() -> None:
    out = s.run_seq(s.multi_parent_shape(OrphanPolicy.PRESERVE)).outputs
    assert out["P1"].column("k").to_pylist()[1] == _SHARED_UNDER_P1
    assert out["P2"].column("k").to_pylist()[1] == _SHARED_UNDER_P2
    assert out["X"].column("ref").to_pylist()[2] == _SHARED_UNDER_P1


def test_composite_child_tuple_is_the_parents_native_tuple() -> None:
    out = s.run_seq(s.composite_shape(OrphanPolicy.REMAP)).outputs
    p, c = out["P"].to_pydict(), out["C"].to_pydict()
    assert (c["k"][0], c["j"][0]) == (p["k"][0], p["j"][0])
    assert (c["k"][1], c["j"][1]) == (p["k"][1], p["j"][1])


def test_mixed_type_composite_matches_the_oracle(monkeypatch: pytest.MonkeyPatch) -> None:
    shape = s.mixed_composite_shape(OrphanPolicy.REMAP)
    full = s.run_full(shape).outputs
    python_rows = spy_python_hash(monkeypatch)
    seq = s.run_seq(shape).outputs
    assert python_rows == [3, 1]  # the declined member, parent then orphan
    for table in full:
        assert sc.compare_strict(full[table], seq[table]) == _ALL_TRUE, table


def test_mixed_type_chain_matches_the_oracle(monkeypatch: pytest.MonkeyPatch) -> None:
    shape = s.mixed_type_chain_shape(OrphanPolicy.REMAP)
    full = s.run_full(shape).outputs
    seq = s.run_seq(shape).outputs
    for table in full:
        assert sc.compare_strict(full[table], seq[table]) == _ALL_TRUE, table


# The one accepted divergence: the same kernel as D1a, so the same Unicode-table behavior.


def test_post_python_version_sequence_is_native_normalized_through_a_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def chain(key: str) -> dict[str, pa.Table]:
        shape = s.chain_shape(OrphanPolicy.PRESERVE, a=[key], b=[key], c=[key])
        return s.run_seq(shape).outputs

    sensitive, ordered = chain(_SENSITIVE), chain(_ORDERED)
    # Native NFC maps both spellings to one token, and the whole chain carries it.
    tokens = {t.column("k").to_pylist()[0] for out in (sensitive, ordered) for t in out.values()}
    assert len(tokens) == 1
    assert tuple(int(p) for p in unicodedata.unidata_version.split(".")) < (16, 0, 0)
    with monkeypatch.context() as m:
        hide_companion(m)
        python = (
            chain(_SENSITIVE)["A"].column("k").to_pylist()[0],
            chain(_ORDERED)["A"].column("k").to_pylist()[0],
        )
    # The Python path keeps the older normalization, so the two spellings differ there.
    assert python[0] != python[1] or unicodedata.unidata_version != "14.0.0"
    assert tokens != {python[0]}


# The D0 goldens' data, with the FK key columns hashed.


def _golden_shapes() -> dict[str, s.Shape]:
    emp = s.golden_sources("self_fk")["employees"]
    self_ref = s.Shape(
        s.make_plan(
            {
                "employees": s.table_seed(
                    {"id": s.hashed("ns_emp"), "manager_id": s.hashed("ns_emp")}
                )
            }
        ),
        s.graph(s.edge("employees", "id", "employees", "manager_id", "ns_emp", OrphanPolicy.REMAP)),
        {"employees": emp},
    )
    composite_src = s.golden_sources(
        "composite_key",
        enrollments=("member_id", "plan_id", "effective_date"),
        claims=("member_id", "plan_id", "effective_date"),
    )
    cols = ("member_id", "plan_id", "effective_date")
    composite = s.Shape(
        s.make_plan(
            {
                "enrollments": s.table_seed({c: s.hashed(f"ns_{c}") for c in cols}),
                "claims": s.table_seed({}, {cols: "ns_enrollment"}),
            }
        ),
        s.graph(
            s.edge("enrollments", cols, "claims", cols, "ns_enrollment", OrphanPolicy.PRESERVE)
        ),
        composite_src,
    )
    nullable_src = s.golden_sources("nullable_fk")
    nullable = s.Shape(
        s.make_plan(
            {
                "employees": s.table_seed({"employee_id": s.hashed("ns_emp")}),
                "reviews": s.table_seed(
                    {"employee_id": s.hashed("ns_emp"), "reviewer_id": s.hashed("ns_emp")}
                ),
            }
        ),
        s.graph(
            s.edge("employees", "employee_id", "reviews", "employee_id", "ns_emp"),
            s.edge("employees", "employee_id", "reviews", "reviewer_id", "ns_emp"),
        ),
        nullable_src,
    )
    return {"self_fk": self_ref, "composite_key": composite, "nullable_fk": nullable}


@pytest.mark.parametrize("fixture", ["self_fk", "composite_key", "nullable_fk"])
def test_golden_data_hashes_natively_and_matches_the_oracle_and_the_python_route(
    fixture: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    shape = _golden_shapes()[fixture]
    full = s.run_full(shape).outputs
    native = s.run_seq(shape)
    for table in full:
        assert sc.compare_strict(full[table], native.outputs[table]) == _ALL_TRUE, table
    with monkeypatch.context() as m:
        hide_companion(m)
        python = s.run_seq(shape).outputs
    for table in python:
        assert table_digest(python[table]) == table_digest(native.outputs[table]), table
    assert any(
        e["executed_backend"] == "rust_companion" for e in native.quality_metrics["sequential_hash"]
    )
