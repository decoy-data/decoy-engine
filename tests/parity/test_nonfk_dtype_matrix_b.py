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
from tests.parity._nonfk_dtype_cases import LAYOUTS, ROWS, null_at, source_table
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


# -- every nullable integer width and the allow_collisions faker alias (Codex final on #735) ----

_WIDTHS = {
    "int8": (pa.int8(), 100),
    "int16": (pa.int16(), 30000),
    "int32": (pa.int32(), 2_000_000_000),
    "uint8": (pa.uint8(), 200),
    "uint16": (pa.uint16(), 60000),
    "uint32": (pa.uint32(), 4_000_000_000),
}


def _width_table(width: str, layout: str) -> pa.Table:
    arrow, top = _WIDTHS[width]
    values = [
        None if null_at(layout, i) else (top - i if layout == "wide_value" else i % 100)
        for i in range(ROWS)
    ]
    return pa.table(
        {
            "s": pa.array([f"name{i}" for i in range(ROWS)], pa.string()),
            "p": pa.array(values, arrow),
        }
    )


def _assert_chunked_and_equal(tmp_path: Path, table: pa.Table, entry: dict[str, object]) -> None:
    cfg = _cfg(tmp_path, table, entry)
    got = _run(table, cfg)
    block = got.quality_metrics["auto_chunk"]
    assert block["mode"] == "chunked", block["reason"]
    out = got.outputs[support.TABLE]
    base = _oracle(table, cfg).outputs[support.TABLE]
    assert out.schema.field("p").type == base.schema.field("p").type
    assert out.column("p").to_pylist() == base.column("p").to_pylist()


@pytest.mark.parametrize("layout", LAYOUTS)
@pytest.mark.parametrize("strategy", ["hash", "redact"])
@pytest.mark.parametrize("width", list(_WIDTHS))
def test_every_nullable_integer_width_is_chunked_and_equals_the_oracle(
    tmp_path: Path, width: str, strategy: str, layout: str
) -> None:
    _assert_chunked_and_equal(tmp_path, _width_table(width, layout), _masked_entry(strategy))


@pytest.mark.parametrize("layout", LAYOUTS)
def test_a_faker_with_the_allow_collisions_alias_matches_the_oracle(
    tmp_path: Path, layout: str
) -> None:
    """The shared predicate admits the alias at the dtype gate, but the chunked strategy rule
    still requires `deterministic: true`, so the table runs full-frame. Pinned: output equals
    the oracle either way, and a change of route shows up here."""
    table = source_table("int64_nulls", layout)
    entry = {**support.faker_col("p"), "allow_collisions": True}
    del entry["deterministic"]
    cfg = _cfg(tmp_path, table, entry)
    got = _run(table, cfg)
    assert got.quality_metrics["auto_chunk"]["mode"] == "full_frame"
    base = _oracle(table, cfg).outputs[support.TABLE]
    out = got.outputs[support.TABLE]
    assert out.schema.field("p").type == base.schema.field("p").type
    assert out.column("p").to_pylist() == base.column("p").to_pylist()
