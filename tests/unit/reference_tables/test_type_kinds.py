"""The reference loader's Arrow classifier returns closed `Kind` members, never text."""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pytest

from decoy_engine import _arrow_types
from decoy_engine._config_text import Kind
from decoy_engine.reference_tables import _loader


def test_reference_type_kinds_use_is_text() -> None:
    by_kind = {kind: test for kind, test in _loader._TYPE_KINDS}
    assert by_kind[Kind.STRING] is _arrow_types.is_text


def test_every_type_kind_row_is_a_kind_member() -> None:
    assert all(isinstance(kind, Kind) for kind, _ in _loader._TYPE_KINDS)
    assert _loader._type_kind(pa.timestamp("ns", tz="PRIVATE_ZONE")) is Kind.TIMESTAMP
    assert _loader._type_kind(pa.large_string()) is Kind.STRING
    assert _loader._type_kind(pa.null()) is Kind.OTHER


def test_timestamp_renders_without_the_zone() -> None:
    from decoy_engine._config_text import Problem, config_position, config_refusal

    kind = _loader._type_kind(pa.timestamp("ns", tz="PRIVATE_ZONE"))
    refusal = config_refusal(config_position("id"), Problem.WRONG_TYPE, got_kind=kind)
    assert "timestamp" in refusal.text
    assert "PRIVATE_ZONE" not in refusal.text


def test_loader_names_the_kind_of_a_bad_id_column(tmp_path: Path) -> None:
    import pyarrow.parquet as pq

    bad = tmp_path / "id32.parquet"
    pq.write_table(pa.table({"id": pa.array([1], pa.int32())}), bad)
    with pytest.raises(ValueError) as raised:
        _loader.load_table(f"customer:{bad}")
    assert "reference_table.id: wrong type; expected int64, got integer" in str(raised.value)
