"""The one resolved description of what dispatch does with each work node.

`resolve_operations` reads each node once, FK resolution first (an FK child resolves through its
parent map before any handler runs, so the handler it is configured with is bypassed), then the
handler's `column_access` declaration. Every consumer takes these records: the ordering edges, the
`when:` snapshot set, the gated stitch, the ranked commits and the carry-side untouched set. No
consumer asks `column_access` about a node's writes itself, so one answer reaches all of them.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from decoy_engine.execution._column_access import (
    OWN_TARGET_SOURCE,
    ColumnAccess,
    creates_own_target,
    declared_access,
)
from decoy_engine.execution._runner import node_entry, when_columns_of

if TYPE_CHECKING:
    from decoy_engine.execution._runner import WorkNode
    from decoy_engine.relationships import RelationshipEdge, RelationshipGraph

OpKind = Literal["fk", "scalar", "composite", "passthrough"]
NodeKey = tuple[str, tuple[str, ...]]


@dataclass(frozen=True)
class ResolvedOperation:
    """What dispatch does for one work node.

    `writes` are the columns the node may replace (rows chosen by its gate, if any). `wildcard`
    means the writes cannot be named: the node may replace any column of its table. `creates` is
    true for a scalar that writes its own target without reading it, so the target may be absent
    from the source until the node runs.

    Reads come in three phases, each declared by the handler's `column_access` row: `source_reads`
    are anchor columns taken from the pre-mask snapshot (`joint_mask` `key_by`, `date_shift`
    `group_by`), `masked_reads` are sibling columns read at their value when the node runs, and
    `reads_own_target` means the handler reads the prior version of its own target.
    `reads_unknown` means the declaration cannot name its reads, so every column of the table is
    read at its dispatch value. The `when:` predicate reads are separate: they come from the
    node's seed (`_runner.source_snapshot_columns`).
    """

    node: WorkNode
    kind: OpKind
    writes: frozenset[str]
    wildcard: bool
    creates: bool
    gated: bool
    source_reads: frozenset[str]
    masked_reads: frozenset[str]
    reads_own_target: bool
    reads_unknown: bool
    fk_edges: tuple[RelationshipEdge, ...] = ()

    @property
    def key(self) -> NodeKey:
        return self.node.key

    @property
    def table(self) -> str:
        return self.node.table

    @property
    def outputs(self) -> tuple[str, ...]:
        """The write set in a stable order, the node's own columns first."""
        own = [c for c in self.node.columns if c in self.writes]
        return (*own, *sorted(self.writes - set(own)))


def _declared(
    node: WorkNode, entry: Mapping[str, Any], access: ColumnAccess
) -> tuple[frozenset[str], frozenset[str], bool, bool]:
    """`(source reads, masked reads, reads own target, reads unknown)` from the declaration."""
    # A scalar's own column is not a sibling read. A deterministic bundle reads its first sorted
    # group column, which is one of its own outputs, so a composite keeps it.
    own_column = set(node.columns) if node.kind == "scalar" else set()
    # `ColumnAccess.reads` also holds the `when:` predicate's columns; those are gate reads.
    when_reads = when_columns_of([entry.get("when")])
    masked = access.reads - access.source_reads - when_reads - own_column
    own = node.kind == "scalar" and access.own_target == OWN_TARGET_SOURCE
    return access.source_reads, frozenset(masked), own, access.reads_unknown


def resolve_operation(node: WorkNode, graph: RelationshipGraph) -> ResolvedOperation:
    """Resolve one node. FK resolution is checked first, as dispatch does."""
    from decoy_engine.execution._chunked_carry import passthrough_leaves_input
    from decoy_engine.plan import ColumnSeed

    own = frozenset(node.columns)
    edges = graph.parents_of(node.table, node.columns)
    has_when = isinstance(node.plan_slice, ColumnSeed) and node.plan_slice.when is not None
    entry = node_entry(node)
    none = frozenset[str]()
    if edges:
        return ResolvedOperation(
            node, "fk", own, False, False, False, none, none, False, False, edges
        )
    if entry is None:  # a composite FK group with no edge: dispatch refuses it
        return ResolvedOperation(
            node, "composite", own, False, False, False, none, none, False, False
        )
    composite = node.kind == "composite"
    access = declared_access(entry, composite)
    source, masked, reads_own, unknown = _declared(node, entry, access)
    if composite:
        # A bundle writes exactly its provider's outputs; a `coherent_with` member outside them
        # is group identity, not a write.
        writes = access.writes if not access.writes_unknown else own
        return ResolvedOperation(
            node, "composite", writes, access.writes_unknown, False, False,
            source, masked, False, unknown,
        )  # fmt: skip
    if node.strategy == "passthrough" and passthrough_leaves_input():
        return ResolvedOperation(
            node, "passthrough", none, False, False, has_when, source, masked, False, unknown
        )
    return ResolvedOperation(
        node, "scalar", own | access.writes, access.writes_unknown, creates_own_target(entry),
        has_when, source, masked, reads_own, unknown,
    )  # fmt: skip


def resolve_operations(
    work: Iterable[WorkNode], graph: RelationshipGraph
) -> dict[NodeKey, ResolvedOperation]:
    """One record per work node, resolved once against the job's relationship graph."""
    return {n.key: resolve_operation(n, graph) for n in work}
