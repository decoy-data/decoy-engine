"""Inherited-column invariant (check_inherited_columns) for the test-flight suite.

An `inherit` generate column copies one column of the parent row its foreign key names. The
harness checks that end to end from the output tables alone: it builds the parent's
key-to-value map and compares every child row against it, without the engine's lookup code, so
a lookup that drew the wrong row, read a same-named child column or kept a value beside a null
key fails here even when the engine agrees with itself.
"""

from __future__ import annotations

from typing import Any


def check_inherited_columns(job_name: str, spec: list[Any], result: Any) -> str:
    """Assert each inherited column equals its parent row's value through the foreign key.

    For each InheritedColumnSpec: the parent key is unique in the parent output; a child row
    with a null key holds null; a child row with a key holds exactly the parent row's value
    (type included) and its key exists in the parent. ``min_null_keys`` and
    ``min_distinct_values`` keep the check from passing on data that cannot show a fault.

    Returns:
        Short evidence string naming each verified column with its row counts.

    Raises:
        AssertionError: on any mismatch, a missing table or column, or a vacuous fixture.
    """
    checked: list[str] = []
    for ic in spec:
        where = f"[{job_name}] inherited_columns: {ic.table}.{ic.column}"
        child = result.outputs.get(ic.table)
        parent = result.outputs.get(ic.parent_table)
        assert child is not None, f"{where}: table '{ic.table}' not in result.outputs."
        assert parent is not None, f"{where}: table '{ic.parent_table}' not in result.outputs."
        for tbl, name, col in (
            (child, ic.table, ic.column),
            (child, ic.table, ic.via),
            (parent, ic.parent_table, ic.parent_key),
            (parent, ic.parent_table, ic.parent_column),
        ):
            assert col in tbl.column_names, f"{where}: column '{col}' not in '{name}'."
        keys = parent.column(ic.parent_key).to_pylist()
        values = parent.column(ic.parent_column).to_pylist()
        row_of: dict[Any, Any] = {}
        for k, v in zip(keys, values, strict=True):
            assert k is not None, f"{where}: parent key '{ic.parent_key}' holds a null."
            assert k not in row_of, f"{where}: parent key '{ic.parent_key}' is not unique."
            row_of[k] = v
        fks = child.column(ic.via).to_pylist()
        copies = child.column(ic.column).to_pylist()
        bad: list[str] = []
        null_keys = 0
        for i, (fk, got) in enumerate(zip(fks, copies, strict=True)):
            if fk is None:
                null_keys += 1
                if got is not None:
                    bad.append(f"row {i}: null key but value {got!r}")
            elif fk not in row_of:
                bad.append(f"row {i}: key {fk!r} has no parent row")
            elif got != row_of[fk] or type(got) is not type(row_of[fk]):
                bad.append(f"row {i}: key {fk!r} holds {got!r}, parent holds {row_of[fk]!r}")
        assert not bad, (
            f"{where}: {len(bad)} row(s) differ from the parent row (first 3): "
            + "; ".join(bad[:3])
        )
        assert null_keys >= ic.min_null_keys, (
            f"{where}: {null_keys} null-key row(s), fewer than the {ic.min_null_keys} the "
            "manifest requires, so the null-key rule went unchecked."
        )
        distinct = {v for fk, v in zip(fks, copies, strict=True) if fk is not None}
        assert len(distinct) >= ic.min_distinct_values, (
            f"{where}: {len(distinct)} distinct inherited value(s), fewer than "
            f"{ic.min_distinct_values}, so a copy from the wrong parent row could pass."
        )
        checked.append(
            f"{ic.table}.{ic.column}(rows={len(fks)}, null_keys={null_keys}, "
            f"distinct={len(distinct)})"
        )
    return "inherited_columns verified: " + ", ".join(checked)
