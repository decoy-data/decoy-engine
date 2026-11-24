"""Every operation declares its reads by phase, and the record carries them (plan revision 2.6,
I4 and D2).

Reads have three phases: `source_reads` (the pre-mask snapshot: `joint_mask` `key_by`,
`date_shift` `group_by`), `masked_reads` (a sibling at its value when the node runs) and
`reads_own_target`. Each scalar and composite key of `SURFACE_DECLARATIONS` has a representative
entry that names a sentinel column in every sibling field the declaration reads; the declaration
and the resolved record must carry each sentinel in its expected phase. A key with no row fails.
In S2a `source_reads` decides what is snapshotted, and the `when:` reads of every gated node must
be in the snapshot set whenever some operation of its table writes them.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from decoy_engine.execution._column_access import (
    OWN_TARGET_SOURCE,
    SURFACE_DECLARATIONS,
    creates_own_target,
    declared_access,
)
from decoy_engine.execution._runner import build_work_list, source_snapshot_columns
from decoy_engine.execution.work_order import ResolvedOperation, compile_work_order
from tests.unit.execution.when import _write_support as ws

SIBLINGS = (
    ("group_by", "s_gb"),
    ("order_by", "s_ob"),
    ("anchor", "s_an"),
    ("reference_column", "s_rc"),
)
MASKED_SIBLINGS = frozenset({"s_co", "s_gb", "s_ob", "s_an", "s_rc"})
_COMPOSITES = (
    "composite_name_email",
    "composite_city_state_zip",
    "composite_person",
    "composite_address",
    "composite_provider",
    "composite_custom",
)


def _scalar(key: str) -> tuple[Any, frozenset[str], frozenset[str]]:
    """(seed, expected source reads, expected masked reads) for the scalar declaration `key`."""
    cfg: tuple[tuple[str, Any], ...] = SIBLINGS
    source: frozenset[str] = frozenset()
    masked = MASKED_SIBLINGS
    if key == "date_shift":
        source, masked = frozenset({"s_gb"}), MASKED_SIBLINGS - {"s_gb"}
    elif key == "joint_mask":
        cfg = (
            *SIBLINGS,
            ("columns", ["t_col", "s_out"]),
            ("reference", "customer:/none"),
            ("key_by", "s_key"),
        )
        source = frozenset({"s_key"})
    elif key == "derived":
        cfg = (*SIBLINGS, ("expression", "concat(s_e1, s_e2)"))
        masked = MASKED_SIBLINGS | {"s_e1", "s_e2"}
    elif key == "derived_aggregate":
        cfg = (*SIBLINGS, ("column", "s_agg"))
        masked = MASKED_SIBLINGS | {"s_agg"}
    return ws.seed(key, provider_config=cfg, coherent_with=("s_co",)), source, masked


def _composite(key: str) -> tuple[Any, frozenset[str], frozenset[str]]:
    seed = ws.seed(
        "faker",
        provider=key,
        namespace="nm",
        backend_type="composite",
        coherent_with=("a_co",),
        provider_config=(("bundle", [{"column": "t_col", "provider": "first_name"}]),)
        if key == "composite_custom"
        else (),
    )
    # The deterministic key is the first sorted column of the group ({t_col, a_co}).
    return seed, frozenset(), frozenset({"a_co"})


def _rows() -> dict[str, tuple[Any, frozenset[str], frozenset[str]]]:
    rows = {k: _scalar(k.split(":", 1)[1]) for k in SURFACE_DECLARATIONS if k.startswith("scalar:")}
    rows.update(
        {
            k: _composite(k.split(":", 1)[1])
            for k in SURFACE_DECLARATIONS
            if k.startswith("composite:")
        }
    )
    return rows


def _resolve(seed: Any) -> ResolvedOperation:
    plan = ws.plan([("t_col", seed)])
    order = compile_work_order(build_work_list(plan, ws.REG), ws.NO_GRAPH)
    (op,) = order.ops.values()
    return op


def test_every_scalar_and_composite_key_has_a_representative_row() -> None:
    keys = {k for k in SURFACE_DECLARATIONS if k.startswith(("scalar:", "composite:"))}
    assert keys == set(_rows())
    assert {f"composite:{c}" for c in _COMPOSITES} <= keys


@pytest.mark.parametrize("key", sorted(_rows()))
def test_the_declaration_and_the_record_carry_each_sentinel_in_its_phase(key: str) -> None:
    seed, source, masked = _rows()[key]
    op = _resolve(seed)
    assert not op.reads_unknown
    assert op.source_reads == source, key
    assert op.masked_reads == masked, key
    # The record is the declaration, unchanged.
    entry = {
        "name": "t_col",
        "strategy": seed.strategy,
        "provider": seed.provider,
        "provider_config": dict(seed.provider_config),
        "coherent_with": list(seed.coherent_with),
        "when": None,
    }
    access = declared_access(entry, key.startswith("composite:"))
    assert op.source_reads == access.source_reads
    assert access.source_reads <= access.reads
    own = {"t_col"} if op.kind == "scalar" else set()
    assert (access.reads - access.source_reads - own) == op.masked_reads
    if key.startswith("scalar:") and op.kind == "scalar":
        assert op.creates == creates_own_target(entry), key
        assert op.reads_own_target == (access.own_target == OWN_TARGET_SOURCE), key


def test_the_read_fields_have_no_defaults() -> None:
    """A record built without stating its reads is a construction error, not "reads nothing"."""
    fields = {f.name: f for f in dataclasses.fields(ResolvedOperation)}
    for name in ("source_reads", "masked_reads", "reads_own_target", "reads_unknown"):
        assert fields[name].default is dataclasses.MISSING, name
        assert fields[name].default_factory is dataclasses.MISSING, name  # type: ignore[misc]


def test_a_declaration_that_cannot_name_its_reads_is_marked_unknown() -> None:
    seed = ws.derived("concat(a, ")  # unparsable expression
    assert _resolve(seed).reads_unknown


def test_a_gated_nodes_when_reads_are_snapshotted_once_a_node_writes_them() -> None:
    plan = ws.plan(
        [
            ("status", ws.seed("redact")),
            ("z_gated", ws.seed("redact", when="status == 'a' and other == 1")),
        ]
    )
    order = compile_work_order(build_work_list(plan, ws.REG), ws.NO_GRAPH)
    assert source_snapshot_columns(order)["t"] == {"status"}  # `other` is written by no node
