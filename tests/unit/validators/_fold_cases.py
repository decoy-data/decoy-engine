"""One small failing fixture per validator, shared by the fold parity and invariance tests.

Each case builds ``(outputs, config, sources)`` for one ``validators:`` entry. Every case fails
on a few rows, so the findings, their indices and their wording are all in play.
"""

from __future__ import annotations

from typing import Any, NamedTuple

import pyarrow as pa


class Case(NamedTuple):
    outputs: dict[str, pa.Table]
    config: dict[str, Any]
    sources: dict[str, pa.Table]


def _rel(parent: str, pcols: list[str], child: str, ccols: list[str]) -> dict[str, Any]:
    return {
        "parent": {"table": parent, "columns": pcols},
        "children": [{"table": child, "columns": ccols}],
    }


def _single(entry: dict[str, Any], column: str, values: list[Any]) -> Case:
    return Case(
        {"t": pa.table({column: values})},
        {"validators": [entry], "tables": [], "relationships": []},
        {},
    )


def _fk_case(name: str) -> Case:
    parent = pa.table({"id": [1, 2, 3]})
    child = pa.table({"pid": [1, 9, None, 2, 7]})
    return Case(
        {"parent": parent, "child": child},
        {
            "validators": [{"name": name}],
            "tables": [],
            "relationships": [_rel("parent", ["id"], "child", ["pid"])],
        },
        {},
    )


def _leak_case() -> Case:
    out = pa.table(
        {
            "a": ["x1", "x2", "x3", "x4", "x5"],
            "b": ["b1", "zz", "b3", "yy", "ww"],
            "c": ["c1", "c2", "c3", "c4", "c5"],
            "d": ["d1", "d2", "d3", "d4", "d5"],
        }
    )
    src = pa.table(
        {
            "a": ["x1", "x2", "x3", "x4", "x5"],
            "b": ["b1", "b2", "b3", "b4", "b5"],
            "c": ["c1", "c2", "c3", "c4", "c5"],
            "d": ["d1", "d2", "d3", "d4", "d5"],
        }
    )
    tables = [
        {
            "name": "t",
            "columns": [
                {"name": "a", "strategy": "hash"},
                {"name": "b", "strategy": "redact"},
                {"name": "c", "strategy": "shuffle"},
                {"name": "d", "strategy": "passthrough"},
            ],
        }
    ]
    return Case(
        {"t": out},
        {"validators": [{"name": "leak_check"}], "tables": tables, "relationships": []},
        {"t": src},
    )


def _window_case() -> Case:
    parent = pa.table(
        {
            "id": [1, 2, 3],
            "start": ["2020-01-01", "2020-02-01", None],
            "end": ["2020-12-31", "2020-02-28", "2020-12-31"],
        }
    )
    child = pa.table(
        {
            "pid": [1, 1, 2, 2, 3, 9, None, 1, 2],
            "d": [
                "2020-06-01",
                "2021-01-01",
                "2020-02-10",
                "2020-03-01",
                "2020-05-05",
                "1999-01-01",
                "2020-01-01",
                "garbage",
                None,
            ],
        }
    )
    entry = {
        "name": "parent_window_respected",
        "params": {
            "child_table": "child",
            "child_column": "d",
            "parent_table": "parent",
            "window_start_column": "start",
            "window_end_column": "end",
        },
    }
    return Case(
        {"parent": parent, "child": child},
        {
            "validators": [entry],
            "tables": [],
            "relationships": [_rel("parent", ["id"], "child", ["pid"])],
        },
        {},
    )


def _reconcile_case() -> Case:
    parent = pa.table({"id": [1, 2, 3, 4], "total": [10.0, 5.0, 7.0, None]})
    child = pa.table({"pid": [1, 1, 2, 3, 4], "amt": ["4", "6", "4", "x", "1"]})
    entry = {
        "name": "reconciliation_holds",
        "params": {
            "parent_table": "parent",
            "parent_column": "total",
            "child_table": "child",
            "child_column": "amt",
        },
    }
    return Case(
        {"parent": parent, "child": child},
        {
            "validators": [entry],
            "tables": [],
            "relationships": [_rel("parent", ["id"], "child", ["pid"])],
        },
        {},
    )


def build_cases() -> dict[str, Case]:
    """Every registered validator name mapped to its failing fixture."""
    return {
        "luhn": _single(
            {"name": "luhn", "columns": {"t": ["cc"]}},
            "cc",
            ["4532015112830366", "4532015112830367", None, "x", "4111111111111111"],
        ),
        "npi": _single(
            {"name": "npi", "columns": {"t": ["cc"]}},
            "cc",
            ["1234567893", "1234567890", None, "12"],
        ),
        "iban": _single(
            {"name": "iban", "columns": {"t": ["cc"]}},
            "cc",
            ["GB82WEST12345698765432", "GB82WEST12345698765433", None],
        ),
        "vin": _single(
            {"name": "vin", "columns": {"t": ["cc"]}},
            "cc",
            ["1M8GDM9AXKP042788", "1M8GDM9A1KP042788", "short"],
        ),
        "regex_match": _single(
            {"name": "regex_match", "columns": {"t": ["cc"]}, "params": {"pattern": r"ab\d"}},
            "cc",
            ["ab1", "abx", "12", None, "ab9"],
        ),
        "column_in_set": _single(
            {
                "name": "column_in_set",
                "columns": {"t": ["cc"]},
                "params": {"allowed_values": ["a", "b"], "allow_null": False},
            },
            "cc",
            ["a", "b", "c", None, "z"],
        ),
        "fk_intact": _fk_case("fk_intact"),
        "no_orphan_children": _fk_case("no_orphan_children"),
        "leak_check": _leak_case(),
        "parent_window_respected": _window_case(),
        "reconciliation_holds": _reconcile_case(),
    }


def _blank_window_case() -> Case:
    """A leading blank string: pandas takes the date format from the first real value."""
    base = _window_case()
    parent = pa.table({"id": [1], "start": ["2024-01-01"], "end": ["2024-12-31"]})
    child = pa.table({"pid": [1, 1, 1], "d": ["", "2024-01-05", "01/05/2024"]})
    return Case({"parent": parent, "child": child}, base.config, {})


def _repeated_column_case() -> Case:
    """leak_check with one column listed twice is two checks, as it always was."""
    values = ["x1", "x2", "x3"]
    tables = [{"name": "t", "columns": [{"name": "a", "strategy": "hash"}]}]
    return Case(
        {"t": pa.table({"a": values})},
        {
            "validators": [{"name": "leak_check", "columns": {"t": ["a", "a"]}}],
            "tables": tables,
            "relationships": [],
        },
        {"t": pa.table({"a": values})},
    )


def _skipped_unpaired_case() -> Case:
    """Every column is skipped, so the source need not pair with the output."""
    tables = [{"name": "t", "columns": [{"name": "e", "strategy": "passthrough"}]}]
    return Case(
        {"t": pa.table({"e": ["a", "b"]})},
        {"validators": [{"name": "leak_check"}], "tables": tables, "relationships": []},
        {"t": pa.table({"e": ["a", "b", "c"]})},
    )


def build_extra_cases() -> dict[str, Case]:
    """Cases beyond one per validator; their expected findings were also captured at 311ec1418."""
    return {
        "parent_window_leading_blank": _blank_window_case(),
        "leak_check_repeated_column": _repeated_column_case(),
        "leak_check_skipped_columns_do_not_pair": _skipped_unpaired_case(),
    }
