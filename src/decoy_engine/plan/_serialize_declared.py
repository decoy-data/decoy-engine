"""YAML (de)serialization of the Plan's optional blocks: `declared_casting` (F06, plan_version 3)
and `column_shapes` (plan_version 5), and the `plan_version` check that runs before either.

A stored plan is untrusted input: loading re-validates every contract through the catalog, so a
plan that names an unknown format, catalog version or column shape never reaches a run.
"""

from __future__ import annotations

from typing import Any

from decoy_engine import reasons
from decoy_engine.contracts.column_shape import ColumnShape
from decoy_engine.plan._errors import PlanCompileError
from decoy_engine.plan._types import (
    PLAN_VERSION,
    DeclaredCastingPlan,
    PlanColumnShape,
    PlanDeclaredColumn,
    freeze_json,
    unfreeze_json,
)


def declared_casting_to_dict(block: DeclaredCastingPlan) -> dict[str, Any]:
    out: dict[str, Any] = {
        "catalog_version": block.catalog_version,
        "columns": [
            {
                "table": c.table,
                "column": c.column,
                "strategy": c.strategy,
                "contract": unfreeze_json(c.contract),
            }
            for c in block.columns
        ],
    }
    if block.quarantine is not None:
        out["quarantine"] = unfreeze_json(block.quarantine)
    return out


def declared_casting_from_dict(data: dict[str, Any]) -> DeclaredCastingPlan:
    """Load and re-validate a stored block: a stored plan is untrusted input, and a plan that
    names an unknown format or catalog version must never reach a run."""
    from decoy_engine.contracts.declared_casting import (
        CATALOG_VERSION,
        DeclaredCastContractError,
        build_contract,
    )

    if data.get("catalog_version") != CATALOG_VERSION:
        raise PlanCompileError(
            code=reasons.plan.DECLARED_CAST_FORMAT_UNKNOWN,
            path="<declared_casting.catalog_version>",
            message="The stored declared-casting catalog version is not supported by this engine.",
        )
    columns: list[PlanDeclaredColumn] = []
    for raw in data.get("columns") or ():
        path = f"<declared_casting {raw.get('table')!s}.{raw.get('column')!s}>"
        try:
            contract = build_contract(dict(raw["contract"]))
        except DeclaredCastContractError as exc:
            raise PlanCompileError(code=exc.code, path=path, message=exc.message) from None
        columns.append(
            PlanDeclaredColumn(
                table=raw["table"],
                column=raw["column"],
                strategy=raw["strategy"],
                contract=freeze_json(contract.to_payload()),
            )
        )
    quarantine = data.get("quarantine")
    return DeclaredCastingPlan(
        catalog_version=data["catalog_version"],
        columns=tuple(columns),
        quarantine=freeze_json(quarantine) if quarantine is not None else None,
    )


_SHAPES_BY_TOKEN = {s.value: s for s in ColumnShape}


def column_shapes_to_list(shapes: tuple[PlanColumnShape, ...]) -> list[dict[str, str]]:
    return [{"table": c.table, "column": c.column, "shape": c.shape.value} for c in shapes]


def column_shapes_from_list(raw: Any) -> tuple[PlanColumnShape, ...]:
    """Load the stored shapes. A token this engine does not know is refused, never read as
    `other`; the message names the table and column and holds no stored value."""
    out: list[PlanColumnShape] = []
    for entry in raw or ():
        table, column = entry.get("table"), entry.get("column")
        token = entry.get("shape")
        shape = _SHAPES_BY_TOKEN.get(token) if isinstance(token, str) else None
        if shape is None:
            raise PlanCompileError(
                code=reasons.plan.STORED_SHAPE_UNKNOWN,
                path="<column_shapes>",
                message=(
                    f"column {column!s} in table {table!s} has a stored shape this engine "
                    "does not know; compile the plan again."
                ),
            )
        out.append(PlanColumnShape(table=table, column=column, shape=shape))
    return tuple(out)


def check_plan_version(data: dict[str, Any]) -> None:
    """Refuse a stored plan this engine cannot run as written, before any other field is read.

    A missing, non-`int` or newer version would have fields dropped or misread; an older one has
    no `column_shapes`, and reading it as "no shapes" would refuse plans that are valid today.
    No stored value reaches the message, `__cause__` or `__context__`.
    """
    version = data.get("plan_version")
    if type(version) is not int:
        raise PlanCompileError(
            code=reasons.plan.PLAN_VERSION_UNSUPPORTED,
            path="<plan_version>",
            message="this plan has no valid plan_version; compile the plan again.",
        )
    if version > PLAN_VERSION:
        raise PlanCompileError(
            code=reasons.plan.PLAN_VERSION_UNSUPPORTED,
            path="<plan_version>",
            message=(
                f"this plan was written by a newer engine (plan_version {version}); "
                "upgrade decoy-engine or compile the plan again."
            ),
        )
    if version < PLAN_VERSION:
        raise PlanCompileError(
            code=reasons.plan.PLAN_RECOMPILE_REQUIRED,
            path="<plan_version>",
            message=(
                f"this plan was written by an older engine (plan_version {version}); "
                "compile it again from its config."
            ),
        )
