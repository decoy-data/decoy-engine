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
    OWN_TARGET_CREATES,
    SURFACE_DECLARATIONS,
    column_access,
    declared_access,
    scalar_creating_reads,
)

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
    from the source until the node runs. `masked_reads` are sibling columns read at their masked
    value (the ordering edge); `source_reads` are the columns its `when:` reads at the original.
    """

    node: WorkNode
    kind: OpKind
    writes: frozenset[str]
    wildcard: bool
    creates: bool
    gated: bool
    masked_reads: frozenset[str]
    fk_edges: tuple[RelationshipEdge, ...] = ()
    # The creator flag and masked reads of the handler the node is CONFIGURED with, kept for the
    # compatibility sort: a plan that orders today keeps its order, so an FK child's configured
    # creator still adds its edges there. Value dependencies (`creates`, `masked_reads`) discard
    # a bypassed handler's reads and flag.
    order_creates: bool = False
    order_reads: frozenset[str] = frozenset()

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


def _entry(node: WorkNode) -> dict[str, object] | None:
    from decoy_engine.execution._adapter import provider_config_to_dict
    from decoy_engine.plan._types import ColumnSeed

    seed = node.plan_slice
    if not isinstance(seed, ColumnSeed):
        return None
    return {
        "name": node.columns[0] if node.columns else None,
        "strategy": seed.strategy,
        "provider": seed.provider,
        "provider_config": provider_config_to_dict(seed.provider_config),
        "coherent_with": list(seed.coherent_with),
        "when": seed.when,
    }


def _configured_order(
    node: WorkNode, entry: dict[str, object] | None
) -> tuple[bool, frozenset[str]]:
    """`(creates, masked reads)` of the scalar handler a node is configured with."""
    if entry is None or node.kind != "scalar":
        return False, frozenset()
    declare = SURFACE_DECLARATIONS.get(f"scalar:{node.strategy}")
    creates = declare is not None and declare(entry).own_target == OWN_TARGET_CREATES
    return creates, scalar_creating_reads(entry)


def resolve_operation(node: WorkNode, graph: RelationshipGraph) -> ResolvedOperation:
    """Resolve one node. FK resolution is checked first, as dispatch does."""
    from decoy_engine.execution._chunked_carry import passthrough_leaves_input
    from decoy_engine.plan._types import ColumnSeed

    own = frozenset(node.columns)
    edges = graph.parents_of(node.table, node.columns)
    gated = isinstance(node.plan_slice, ColumnSeed) and node.plan_slice.when is not None
    entry = _entry(node)
    if edges:
        creates, reads = _configured_order(node, entry)
        return ResolvedOperation(
            node, "fk", own, False, False, False, frozenset(), edges, creates, reads
        )
    if entry is None:  # a composite FK group with no edge: dispatch refuses it
        return ResolvedOperation(node, "composite", own, False, False, False, frozenset())
    composite = node.kind == "composite"
    access = declared_access(entry, composite)
    if composite:
        # A bundle writes exactly its provider's outputs; a `coherent_with` member outside them
        # is group identity, not a write.
        writes = access.writes if not access.writes_unknown else own
        return ResolvedOperation(
            node, "composite", writes, access.writes_unknown, False, gated, frozenset()
        )
    if node.strategy == "passthrough" and passthrough_leaves_input():
        return ResolvedOperation(node, "passthrough", frozenset(), False, False, gated, frozenset())
    declare = SURFACE_DECLARATIONS.get(f"scalar:{node.strategy}")
    creates = declare is not None and declare(entry).own_target == OWN_TARGET_CREATES
    reads = scalar_creating_reads(entry)
    return ResolvedOperation(
        node,
        "scalar",
        own | access.writes,
        access.writes_unknown,
        creates,
        gated,
        reads,
        (),
        creates,
        reads,
    )


def resolve_operations(
    work: Iterable[WorkNode], graph: RelationshipGraph
) -> dict[NodeKey, ResolvedOperation]:
    """One record per work node, resolved once against the job's relationship graph."""
    return {n.key: resolve_operation(n, graph) for n in work}


def entries_written(entries: Iterable[Mapping[str, Any]], registry: Any) -> frozenset[str] | None:
    """Columns some handler writes across config `entries`, or None when a declaration cannot
    name its writes (every source field is then potentially written). The carry side, which holds
    the table config and no work list, reads the same declaration the resolver does."""
    written: set[str] = set()
    for entry in entries:
        access = column_access(entry, registry)
        if access.writes_unknown:
            return None
        written |= access.writes
    return frozenset(written)
