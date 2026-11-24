"""One transform-lineage rule: admission and execution agree on drop, rename, derive."""

from __future__ import annotations

import pyarrow as pa
import pytest

from decoy_engine.execution import _transforms_table


class TestAdmissionAgreesWithExecutionLineage:
    """One lineage rule: admission's derived set is the executed output's derived bindings."""

    @pytest.mark.parametrize(
        "ops",
        [
            [
                {"op": "drop_column", "columns": ["n"]},
                {"op": "derive", "column": "m", "expression": "k * 2"},
                {"op": "derive", "column": "n", "expression": "m + 1"},
            ],
            [
                {"op": "derive", "column": "m", "expression": "n * 1"},
                {"op": "drop_column", "columns": ["n"]},
                {"op": "derive", "column": "n", "expression": "m + 0"},
            ],
            [
                {"op": "derive", "column": "d", "expression": "n * 2"},
                {"op": "drop_column", "columns": ["d"]},
            ],
        ],
    )
    def test_drop_rename_derive_same_name(self, ops):
        from decoy_engine.config import DERIVED_ORIGIN, final_bindings, parse_ops
        from decoy_engine.execution._transforms_admission import _derived_names

        table = pa.table({"n": [1, 2, 3], "k": [4, 5, 6]})
        cfg = {"tables": [{"name": "t", "transforms": ops}]}
        out = _transforms_table._apply_ops(table, parse_ops(ops))
        executed = {
            c for c, o in final_bindings(table.column_names, parse_ops(ops)) if o == DERIVED_ORIGIN
        }
        assert _derived_names(cfg, "t") == executed
        assert set(out.column_names) >= executed
