"""F07 E4a: `path_relations` and `path_key_batches`, defined but not yet read by any scan or gate.

One relation per `references` rule, in config order. The key extractor yields a key column of the
parent's Arrow type: a missing path or JSON null is a null key, and a cell that cannot be read or
a leaf of the wrong kind is counted and never loaded.
"""

from __future__ import annotations

import json
from typing import Any

import pyarrow as pa
import pytest

from decoy_engine._nested_json import PathRelation, path_relations
from decoy_engine._nested_json._paths import (
    UnsupportedKeyTypeError,
    path_key_batches,
    singular_path,
)


def _config(*columns: dict[str, Any]) -> dict[str, Any]:
    return {"tables": [{"name": "events", "columns": list(columns)}]}


def _nested(name: str, *rules: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": name,
        "strategy": "nested",
        "namespace": "ns",
        "provider_config": {"rules": list(rules)},
    }


def _ref(target: str, table: str = "customers", column: str = "id") -> dict[str, Any]:
    return {
        "target": target,
        "strategy": "hash",
        "namespace": "customer",
        "references": {"table": table, "column": column},
    }


def test_one_relation_per_references_rule_in_config_order() -> None:
    config = _config(
        _nested("payload", {"target": "$.x", "strategy": "redact"}, _ref("$.customer_id")),
        _nested("meta", _ref("$.ref.owner", "owners", "key")),
    )
    assert path_relations(config) == (
        PathRelation("customers", "id", "events", "payload", "$.customer_id"),
        PathRelation("owners", "key", "events", "meta", "$.ref.owner"),
    )


def test_no_reference_gives_no_relation() -> None:
    config = _config(
        _nested("payload", {"target": "$.x", "strategy": "redact"}),
        {"name": "plain", "strategy": "redact"},
        {"name": "single", "strategy": "nested", "provider_config": {"target": "$.a"}},
    )
    assert path_relations(config) == ()
    assert path_relations({}) == ()


def _keys(cells: list[Any], path: str, parent_type: pa.DataType) -> tuple[list[Any], int]:
    batches = list(path_key_batches([pa.array(cells, pa.string())], path, parent_type))
    keys = [v for b in batches for v in b.keys.to_pylist()]
    assert all(b.keys.type == parent_type for b in batches)
    return keys, sum(b.unreadable_rows for b in batches)


def test_integer_parent_reads_integer_leaves_and_counts_the_rest() -> None:
    cells = [
        json.dumps({"customer_id": 42}),
        json.dumps({"customer_id": None}),
        json.dumps({"other": 1}),
        None,
        "not json",
        json.dumps({"customer_id": "42"}),
        json.dumps({"customer_id": {"a": 1}}),
        json.dumps({"customer_id": True}),
        json.dumps({"customer_id": 4.0}),
        json.dumps({"customer_id": 7}),
    ]
    keys, unreadable = _keys(cells, "$.customer_id", pa.int64())
    assert keys == [42, None, None, None, 7]
    assert unreadable == 5


def test_string_parent_reads_string_leaves() -> None:
    cells = [
        json.dumps({"ref": {"id": "c-1"}}),
        json.dumps({"ref": {"id": 5}}),
        json.dumps({"ref": {}}),
        json.dumps({"ref": "c-2"}),
    ]
    keys, unreadable = _keys(cells, "$.ref.id", pa.string())
    assert keys == ["c-1", None, None]
    assert unreadable == 1


def test_an_integer_outside_the_parent_type_is_unreadable() -> None:
    keys, unreadable = _keys([json.dumps({"k": 300}), json.dumps({"k": 7})], "$.k", pa.int8())
    assert keys == [7]
    assert unreadable == 1


def test_a_parent_of_another_type_is_refused_without_reading() -> None:
    with pytest.raises(UnsupportedKeyTypeError):
        list(path_key_batches([pa.array(["{}"])], "$.k", pa.float64()))


@pytest.mark.parametrize("path", ["$.items[*].id", "$..id", "$.a[0]", "customer_id", "$", "$.a b"])
def test_a_path_that_is_not_singular_names_is_refused(path: str) -> None:
    assert singular_path(path) is None
    with pytest.raises(ValueError, match="singular"):
        list(path_key_batches([pa.array(["{}"])], path, pa.int64()))


def test_singular_path_gives_the_name_segments() -> None:
    assert singular_path("$.a.b_c") == ("a", "b_c")
