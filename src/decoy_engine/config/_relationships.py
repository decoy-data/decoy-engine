"""RelationshipConfig: FK relationships at the pipeline-config layer.

Mirrors the S2 spec §3 relationship shape (resolution of S2 B2:
composite via `columns: tuple[str, ...]`). `orphan_policy` is the
closed Literal from S2 TODO 4 (no default; explicit required).

This is the INPUT-side relationship type. The OUTPUT-side
`PlanRelationship` (in `decoy_engine.plan._types`) is the post-compile
type with `orphan_policy` always set + `namespace` resolved by the
build_namespace_registry step. They share field names by design;
PlanRelationship adds invariants (composite_columns_length_match
__post_init__).
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from decoy_engine import reasons
from decoy_engine.config._namespaces import refuse_namespace_placeholder

OrphanPolicyLiteral = Literal["preserve", "remap", "warn", "fail"]


class RelationshipEnd(BaseModel):
    """One side of a relationship (parent or child).

    `columns` is a list (length 1 for single-column FKs; length >1 for
    composite-key FKs). Mirrors the S2 B2 resolution exactly.
    """

    model_config = ConfigDict(extra="forbid")

    table: str
    columns: list[str] = Field(min_length=1)


class RelationshipConfig(BaseModel):
    """One FK relationship: parent + one or more children + policy + namespace.

    `orphan_policy` is required (S2 TODO 4: no default). The four valid
    values are documented in S2 spec §3.
    """

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    parent: RelationshipEnd
    children: list[RelationshipEnd] = Field(min_length=1)
    orphan_policy: OrphanPolicyLiteral
    namespace: str | None = None

    @field_validator("namespace")
    @classmethod
    def _namespace_not_a_placeholder(cls, value: str | None) -> str | None:
        return refuse_namespace_placeholder(value)


def relationship_shape_error(
    rel: Mapping[str, Any],
    columns_by_table: Mapping[str, Collection[str]] | None = None,
) -> tuple[str, str] | None:
    """The first shape fault of one declared relationship as `(code, path)`, or None.

    The one authority for the shape rules both the plan arity check and the starter builder
    apply. Checked in order: an unknown parent or child table, a parent/child column-count
    mismatch, a key column missing from a table whose columns are known. With
    `columns_by_table=None` only the count rule runs. The path names tables and columns, never
    a value.
    """
    parent = rel["parent"]
    here = f"relationships[{parent['table']}]"
    ends = [(parent, "parent"), *((child, "children") for child in rel["children"])]
    if columns_by_table is not None:
        for end, side in ends:
            if end["table"] not in columns_by_table:
                return str(reasons.config.FK_UNKNOWN_NODE), f"{here}.{side}.{end['table']}"
    for child in rel["children"]:
        if len(parent["columns"]) != len(child["columns"]):
            return (
                str(reasons.plan.COMPOSITE_COLUMNS_LENGTH_MISMATCH),
                f"{here}.children.{child['table']}",
            )
    if columns_by_table is not None:
        for end, side in ends:
            known = columns_by_table[end["table"]]
            for column in end["columns"]:
                if column not in known:
                    return (
                        str(reasons.config.FK_UNKNOWN_COLUMN),
                        f"{here}.{side}.{end['table']}.{column}",
                    )
    return None
