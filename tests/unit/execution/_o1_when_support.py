"""Builders and the reference evaluator for the O1 `when:` acceptance tests.

The reference evaluator reads the parsed predicate and compares Python integers, with a blank
treated as NaN: a blank row is selected by `!=`, `not in` and a `not` around a comparison that is
false for it, and by nothing else. Every route and column class must equal it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pyarrow as pa

from decoy_engine.expressions._when_parser import BoolOp, Compare, InList, Not, parse_when

BIG = 2**53
L = BIG + 1
VALUES: list[int | None] = [BIG, BIG + 1, None, 5, 2**63 - 1, -(2**63) + 1]
OPS = [
    f"v == {L}",
    f"v != {L}",
    f"v < {L}",
    f"v <= {L}",
    f"v > {L}",
    f"v >= {L}",
    f"v in [{L}, 5]",
    f"v not in [{L}, 5]",
    f"not (v == {L})",
    f"not (v < {L})",
    f"v == {L} and v != 5",
    f"v == {L} or v == 5",
]
FLOAT_OPS = [f"v == {float(BIG)}", f"v != {float(BIG)}", f"v < {float(BIG)}", "v >= 5.5"]
CLASSES = ["plain", "fk", "declared", "anchor", "top_code", "group_key"]
_CMP = {
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
}


def reference(expression: str, values: list[Any], name: str = "v") -> list[bool]:
    """The rows `expression` selects over `values`, by Python integer comparison and NaN-style blanks."""
    ast = parse_when(expression)

    def ev(node: Any, x: Any) -> bool:
        if isinstance(node, Compare):
            if x is None:
                return node.op == "!="
            a, b = (node.value, x) if node.literal_first else (x, node.value)
            return bool(_CMP[node.op](a, b))
        if isinstance(node, InList):
            hit = x is not None and x in node.values
            return (not hit) if node.negated else hit
        if isinstance(node, Not):
            return not ev(node.operand, x)
        assert isinstance(node, BoolOp)
        parts = [ev(o, x) for o in node.operands]
        return all(parts) if node.op == "and" else any(parts)

    return [ev(ast, x) for x in values]


def selected_rows(out: pa.Table, source_m: list[str]) -> list[bool]:
    """Rows of the gated column `m` the run redacted."""
    return [a != b for a, b in zip(out.column("m").to_pylist(), source_m, strict=True)]


M_SOURCE = ["a", "b", "c", "d", "e", "f"]
ID_SOURCE = list(range(1, 7))


def _csv_stub(tmp: Path, name: str, header: list[str]) -> str:
    path = tmp / f"{name}.csv"
    path.write_text(",".join(header) + "\n" + ",".join("x" for _ in header) + "\n")
    return str(path)


def _col(name: str, strategy: str = "passthrough", **fields: Any) -> dict[str, Any]:
    return {"name": name, "strategy": strategy, **fields}


def build_case(
    cls: str, tmp: Path, expression: str, gated: dict[str, Any] | None = None
) -> tuple[dict[str, Any], dict[str, pa.Table]]:
    """A one- or two-table job whose gated column `m` carries `expression` over the integer
    column `v`, with `v` in the pipeline role named by `cls`.

    plain: nothing else. fk: `v` is a child key whose parent holds the same integers. declared: `v`
    is a declared integer read from text. anchor: `v` is a `date_shift` `group_by`. top_code: `v`
    is `top_code`d with a threshold above every value. group_key: `v` is a `group_by` sibling.
    """
    from decoy_engine.config import PipelineConfig
    from tests._declared_schema import declare_rest

    ints = pa.array(VALUES, pa.int64())
    base: dict[str, pa.Array] = {"id": pa.array(ID_SOURCE, pa.int64()), "v": ints}
    cols: list[dict[str, Any]] = [
        _col("id"),
        _col("v"),
        {**(gated or _col("m", "redact")), "name": "m", "when": expression},
    ]
    tables: dict[str, pa.Table] = {}
    relationships: list[dict[str, Any]] = []
    extra: list[dict[str, Any]] = []
    if cls == "declared":
        base["v"] = pa.array([None if x is None else str(x) for x in VALUES], pa.string())
        cols[1] = _col(
            "v",
            logical_type="integer",
            parse_format={"id": "integer/ascii/v1", "signed": True, "bit_width": 64},
        )
    elif cls == "anchor":
        base["d"] = pa.array(["2020-01-01"] * 6, pa.string())
        cols.append(
            _col(
                "d",
                "date_shift",
                provider_config={"max_shift_days": 3, "group_by": "v"},
                deterministic=True,
                namespace="ns_d",
            )
        )
    elif cls == "top_code":
        cols[1] = _col("v", "top_code", provider_config={"cap": 2**53 - 1, "over_label": "OVER"})
    elif cls == "group_key":
        base["k"] = pa.array(["x"] * 6, pa.string())
        cols.append(_col("k", "group_key", provider_config={"group_by": "v"}))
    base["m"] = pa.array(M_SOURCE, pa.string())
    if cls == "fk":
        tables["parent"] = pa.table(
            {"pid": pa.array([x for x in VALUES if x is not None], pa.int64())}
        )
        extra.append({"name": "parent", "columns": [_col("pid")]})
        relationships.append(
            {
                "parent": {"table": "parent", "columns": ["pid"]},
                "children": [{"table": "t", "columns": ["v"]}],
                "orphan_policy": "remap",
                "namespace": "ns_fk",
            }
        )
    tables["t"] = pa.table(base)
    raw: dict[str, Any] = {
        "version": 2,
        "global_settings": {"seed": 7},
        "sources": {
            n: {
                "type": "file",
                "format": "csv",
                "has_header": True,
                "path": _csv_stub(tmp, n, t.column_names),
            }
            for n, t in tables.items()
        },
        "tables": [{"name": "t", "columns": cols}, *extra],
        "targets": {
            n: {"type": "file", "format": "csv", "path": str(tmp / f"{n}.out")} for n in tables
        },
        "relationships": relationships,
        "namespaces": {},
    }
    return PipelineConfig.model_validate(declare_rest(raw, tables)).model_dump(), tables
