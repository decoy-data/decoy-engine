"""Round-1 review cells for the non-FK masked-type admission (NONFK-OOM S3).

Kept apart from `test_nonfk_dtype_matrix.py` so that module stays under the size goal.
"""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pytest

from decoy_engine.execution import _chunked_input as ci
from decoy_engine.execution.chunked._source_dtype_gate import admitted_masked_columns
from decoy_engine.providers_v2 import get_default_registry
from tests.parity._nonfk_dtype_cases import ROWS, source_table
from tests.parity.test_nonfk_dtype_matrix import _cfg, _masked_entry, _oracle, _run
from tests.unit.execution import _auto_chunk_support as support

# The ligature U+FB01 NFKC-normalises to "fi", so a `when:` on `file` reads it.
LIGATURE = "ﬁle"


def test_m1_a_non_nfkc_column_read_by_a_sibling_is_not_admitted() -> None:
    table = source_table("int64_nulls", "later_mixed", column=LIGATURE)
    facts = ci.facts_for(None, table, "t")
    registry = get_default_registry()
    plain = [support.redact_col("s"), support.hash_col(LIGATURE)]
    gated = [{**support.redact_col("s"), "when": "file > 3"}, support.hash_col(LIGATURE)]
    assert admitted_masked_columns(facts, plain, registry) == {LIGATURE}
    assert admitted_masked_columns(facts, gated, registry) == frozenset()


@pytest.mark.parametrize("redact_with", [0, None, ["x"], 1.5])
def test_at_b2_a_non_string_redact_with_stays_full_frame(
    tmp_path: Path, redact_with: object
) -> None:
    table = source_table("int64_nulls", "later_mixed")
    entry = {**support.redact_col("p"), "provider_config": {"redact_with": redact_with}}
    block = _run(table, _cfg(tmp_path, table, entry)).quality_metrics["auto_chunk"]
    assert block["mode"] == "full_frame"
    assert "p (integer with nulls)" in block["reason"]


def _all_null(type_class: str) -> pa.Table:
    arrow = {
        "int64_nulls": pa.int64(),
        "decimal128": pa.decimal128(10, 2),
        "binary": pa.binary(),
    }[type_class]
    return pa.table(
        {
            "s": pa.array([f"name{i}" for i in range(ROWS)], pa.string()),
            "p": pa.array([None] * ROWS, arrow),
        }
    )


@pytest.mark.parametrize("strategy", ["hash", "redact"])
@pytest.mark.parametrize("type_class", ["int64_nulls", "decimal128", "binary"])
def test_m3_an_all_null_column_equals_values_and_pins_the_type_split(
    tmp_path: Path, strategy: str, type_class: str
) -> None:
    """Values equal the oracle. The type differs and is pinned: a change shows up here.

    Known split (V2-LOG): chunked gives `string`, full-frame gives `null`."""
    table = _all_null(type_class)
    cfg = _cfg(tmp_path, table, _masked_entry(strategy))
    got = _run(table, cfg)
    block = got.quality_metrics["auto_chunk"]
    out = got.outputs[support.TABLE]
    base = _oracle(table, cfg).outputs[support.TABLE]
    assert block["mode"] == "chunked", block["reason"]
    assert out.column("p").to_pylist() == base.column("p").to_pylist()
    assert out.schema.field("p").type == pa.string()
    assert base.schema.field("p").type == pa.null()
