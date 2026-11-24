"""PM-1a: one classifier says what each transform op writes, and the writer query and the
`surface:transforms` declaration both answer from it. An op it does not know, or a malformed op,
is an unknown writer for its own table only."""

from __future__ import annotations

import typing

import pytest

from decoy_engine.config import TransformOp
from decoy_engine.plan.column_access import (
    SURFACE_DECLARATIONS,
    KnownEmpty,
    KnownSet,
    Unknown,
    transform_op_writes,
    written_columns_by_table,
)
from decoy_engine.providers_v2 import get_default_registry


def _op_names() -> set[str]:
    (union, *_) = typing.get_args(TransformOp)
    return {
        name
        for cls in typing.get_args(union)
        for name in typing.get_args(cls.model_fields["op"].annotation)
    }


@pytest.mark.parametrize("name", sorted(_op_names()))
def test_every_transform_op_is_classified(name):
    """A new op stays red here until the classifier says what it writes."""
    assert transform_op_writes({"op": name, "column": "c", "expression": "x"}) is not None


# (ops, the writer query's answer for the table, the declaration's writes or None for unknown)
_CASES = {
    "non-writing ops": (
        [{"op": "filter", "expr": "x > 1"}, {"op": "drop_column", "columns": ["y"]}],
        KnownEmpty(),
        frozenset(),
    ),
    "derive": (
        [{"op": "derive", "column": "z", "expression": "x"}],
        KnownSet(frozenset({"z"})),
        frozenset({"z"}),
    ),
    "unknown op": ([{"op": "pivot"}], Unknown(), None),
    "op name not a string": ([{"op": []}], Unknown(), None),
    "op not a mapping": ([{"op": "filter"}, "derive"], Unknown(), None),
    "derive target not a string": (
        [{"op": "derive", "column": 3, "expression": "x"}],
        Unknown(),
        None,
    ),
}


@pytest.mark.parametrize("case", list(_CASES))
def test_both_consumers_answer_from_the_one_classifier(case):
    ops, query, declared = _CASES[case]
    config = {"version": 2, "tables": [{"name": "t", "columns": [], "transforms": ops}]}
    written = written_columns_by_table(
        config, schemas={"t": ["x"]}, edges=(), registry=get_default_registry()
    )
    assert written == {"t": query}
    access = SURFACE_DECLARATIONS["surface:transforms"]({"name": "t", "transforms": ops})
    assert access.writes_unknown is (declared is None)
    if declared is not None:
        assert access.writes == declared
