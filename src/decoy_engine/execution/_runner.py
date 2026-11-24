"""Work-list construction + execution ordering for the pandas adapter (S9).

The load-bearing core (S9 spec §6; the BLOCKER Dennis caught at spec review):

- `build_work_list` enumerates the columns to mask from
  `plan.seed_envelope.per_table`, NOT from `plan.ordering`. `plan.ordering`
  is built from FK edges only and is EMPTY for a no-FK single-table job, so
  iterating it as the work list would silently leave non-FK columns unmasked.
  The seed envelope is the authoritative set of maskable columns.
- `order_work` computes an execution order over the FULL work list: FK parents
  before children (from `relationship_graph.edges`), and each composite node
  before any FK child that reads one of its output columns (R17). Independent
  nodes fall in deterministic (table, columns) sorted order via a Kahn topo
  sort with a sorted tie-break (byte-stable across runs).

These are pure functions (no pandas, no pyarrow); the concrete
PandasExecutionAdapter (later slice) consumes them.
"""

from __future__ import annotations

import heapq
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, TypeVar

from decoy_engine import reasons
from decoy_engine.execution._errors import ExecutionError
from decoy_engine.plan._types import ColumnSeed, GroupSeed

if TYPE_CHECKING:
    from decoy_engine.execution.native._requirements import NodeRequirements
    from decoy_engine.plan._types import Plan
    from decoy_engine.providers_v2 import ProviderRegistry
    from decoy_engine.relationships import RelationshipGraph

_NodeKey = tuple[str, tuple[str, ...]]


class _HasColumns(Protocol):
    @property
    def columns(self) -> tuple[str, ...]: ...


_N = TypeVar("_N", bound=_HasColumns)


def work_order_key(table: str, columns: tuple[str, ...]) -> _NodeKey:
    """The identity AND sort key of a work node. `order_work`'s tie-break
    (`_kahn_sorted`) takes the smallest of these, so any route that must visit
    nodes in the oracle's order sorts by this one key instead of restating it."""
    return (table, columns)


def in_work_order(table: str, nodes: Iterable[_N]) -> list[_N]:
    """`nodes` of one table in `order_work` order, for a route with no FK or
    composite dependency edges (the unified slice), where that order is exactly
    key order. Visit order is observable: a provider with state, or two columns
    that both fail, behave differently under plan (config) order."""
    return sorted(nodes, key=lambda n: work_order_key(table, n.columns))


@dataclass(frozen=True)
class WorkNode:
    """One unit of masking work: a scalar column, a collapsed composite bundle,
    or a composite-FK group (one node, not per-column)."""

    table: str
    columns: tuple[str, ...]
    kind: str  # "scalar" | "composite" | "composite_fk_group"
    strategy: str
    provider: str | None  # None for scalar transforms (hash/redact/...); see ColumnSeed
    plan_slice: ColumnSeed | GroupSeed
    # Native planning boundary (Task 0.2b): the resolved native execution
    # requirements for this node, attached inertly at native-plan compile time.
    # None on every existing execution path (build_work_list never sets it), so
    # this is pure addition: no route reads it, and byte output is unchanged.
    requirements: NodeRequirements | None = None

    @property
    def key(self) -> _NodeKey:
        return work_order_key(self.table, self.columns)


def provider_is_composite(provider: str | None, registry: ProviderRegistry) -> bool:
    """Whether a column's provider fans out to a multi-column composite node.

    The single source of the provider-composite predicate: a registry-bound
    provider whose capability ``backend_type == "composite"``. ``build_work_list``
    uses it to set ``WorkNode.kind == "composite"``, and the native planning
    boundary reads the same helper so ``native_route_eligibility`` and
    ``compile_native_plan`` never disagree on whether a column is composite.
    Null-guarded before ``registry.has``, which expects a provider string.
    """
    if not provider or not registry.has(provider):
        return False
    return registry.get_capabilities(provider).backend_type == "composite"


def build_work_list(plan: Plan, registry: ProviderRegistry) -> list[WorkNode]:
    """Enumerate every maskable unit from the seed envelope (S9 spec §6.1).

    Covers single-table no-FK jobs (which `plan.ordering` does not). Composite
    output columns collapse into one bundle node keyed on the sorted union of
    (column + its coherent_with); a composite is recognized by
    `provider_is_composite` (registry `backend_type == "composite"`).
    """
    work: list[WorkNode] = []
    for table, table_seed in plan.seed_envelope.per_table:
        composite_groups: dict[_NodeKey, list[ColumnSeed]] = {}
        for col_name, col_seed in table_seed.per_column:
            if provider_is_composite(col_seed.provider, registry):
                group_cols = tuple(sorted({col_name, *col_seed.coherent_with}))
                composite_groups.setdefault((table, group_cols), []).append(col_seed)
            else:
                work.append(
                    WorkNode(
                        table=table,
                        columns=(col_name,),
                        kind="scalar",
                        strategy=col_seed.strategy,
                        provider=col_seed.provider,
                        plan_slice=col_seed,
                    )
                )
        for (group_table, group_cols), seeds in composite_groups.items():
            head = seeds[0]  # all members share the composite provider
            work.append(
                WorkNode(
                    table=group_table,
                    columns=group_cols,
                    kind="composite",
                    strategy="<composite>",
                    provider=head.provider,
                    plan_slice=head,
                )
            )
        for _canonical_key, group_seed in table_seed.per_group:
            work.append(
                WorkNode(
                    table=table,
                    columns=group_seed.coherent_columns,
                    kind="composite_fk_group",
                    strategy="<group>",
                    provider="<group>",
                    plan_slice=group_seed,
                )
            )
    return work


def date_shift_group_columns(plan: Plan, registry: ProviderRegistry) -> dict[str, set[str]]:
    """Per-table set of sibling columns named by a `date_shift` `group_by` (HC-3a).

    A `group_by` anchor column has the same two requirements as an FK-parent
    key column: it must be read PRE-MASK (so every row of one entity anchors on
    the identical source value regardless of masking order / when-gates) and
    converted LOSSLESSLY (an int+null anchor must not widen to float64, which
    would make `_canonicalize_source` reject a valid id). Both the pandas
    adapter and the sequential runner union this set into
    `fk_columns_for_table(...)` (lossless ingestion) and snapshot these columns
    pre-mask into `StrategyContext.group_anchor_snapshots`. Empty when no
    `date_shift` column configures a `group_by`. Only a non-empty STRING
    `group_by` is collected; a malformed ref is rejected at plan-compile
    (`check_date_shift_group_by_refs`), so this walker never has to guess.
    """
    from decoy_engine.execution._adapter import provider_config_to_dict

    out: dict[str, set[str]] = {}
    for node in build_work_list(plan, registry):
        if node.kind != "scalar" or node.strategy != "date_shift":
            continue
        if not isinstance(node.plan_slice, ColumnSeed):
            continue
        group_by = group_by_sibling(provider_config_to_dict(node.plan_slice.provider_config))
        if group_by is not None:
            out.setdefault(node.table, set()).add(group_by)
    return out


def top_code_columns(plan: Plan, registry: ProviderRegistry) -> dict[str, set[str]]:
    """Per-table set of columns masked by `top_code` (HC-3b).

    A top_code column must ingest LOSSLESSLY (nullable Int64), never via a bare
    `to_pandas()` that widens an int+null column to float64. Widening rounds any
    integer with magnitude >= 2**53, and -- because whether a chunk widens
    depends on whether THAT chunk carries a null -- makes the masked output
    depend on the chunk boundary, breaking the CHUNK_SAFE byte-identity contract
    (Codex R2 HIGH). The pandas adapter and the sequential runner union this set
    into `fk_columns_for_table(...)` so the handler compares and renders exact
    integer values on every route. Genuine float columns are unaffected (they are
    float64 on every route already, so no chunk-dependent widening arises).
    """
    out: dict[str, set[str]] = {}
    for node in build_work_list(plan, registry):
        if node.kind != "scalar" or node.strategy != "top_code":
            continue
        for col in node.columns:
            out.setdefault(node.table, set()).add(col)
    return out


def group_by_sibling(provider_config: Mapping[str, Any] | None) -> str | None:
    """The `group_by` sibling a `group_key` column names, or None. The one reading of that key:
    an empty or non-string value is never a real column (the plan walker and unified admission
    both go through here)."""
    group_by = (provider_config or {}).get("group_by")
    return group_by if isinstance(group_by, str) and group_by else None


def group_key_group_by_columns(plan: Plan, registry: ProviderRegistry) -> dict[str, set[str]]:
    """Per-table set of sibling columns named by a `group_key` `group_by` (Trap B).

    A group_by column needs the same lossless-ingest treatment as an FK
    parent key or a `date_shift`/`top_code` column: `apply_group_key` calls
    `str(raw_val)` on the group_by cell, so an int+null column that widens
    to float64 on a null-bearing chunk but stays int64 on a null-free one
    stringifies "5" vs "5.0" for the SAME value depending purely on which
    OTHER rows share its chunk -- a chunk-boundary-dependent key, breaking
    the sibling-keyed byte-identity contract. Both the pandas adapter and
    the sequential runner union this set into `fk_columns_for_table(...)`
    (lossless ingestion only -- NOT a pre-mask snapshot: unlike date_shift's
    group anchors, group_key reads the group_by column at its own position
    in the work order on every route, so a masked group_by column is read
    post-mask consistently everywhere).
    """
    from decoy_engine.execution._adapter import provider_config_to_dict

    out: dict[str, set[str]] = {}
    for node in build_work_list(plan, registry):
        if node.kind != "scalar" or node.strategy != "group_key":
            continue
        if not isinstance(node.plan_slice, ColumnSeed):
            continue
        group_by = group_by_sibling(provider_config_to_dict(node.plan_slice.provider_config))
        if group_by is not None:
            out.setdefault(node.table, set()).add(group_by)
    return out


def joint_mask_key_by_columns(plan: Plan, registry: ProviderRegistry) -> dict[str, set[str]]:
    """Per-table set of `joint_mask` `key_by` SOURCE-key columns (cross-column V1).

    `key_by` selects the reference tuple off the SOURCE key value (its docstring:
    "key_by: Source column"; the FK-key identity analogy -- same source entity ->
    same reference row), so it must read a PRE-MASK snapshot, never the mutable
    frame. This set is unioned into the group-anchor snapshot build + the
    lossless-ingest column set on the full-frame and sequential routes, EXACTLY
    as `date_shift` `group_by` is (`source_anchor_columns`): the reused precedent,
    not a new snapshot stage. Empty when no `joint_mask` column configures
    `key_by`.
    """
    from decoy_engine.execution._adapter import provider_config_to_dict

    out: dict[str, set[str]] = {}
    for node in build_work_list(plan, registry):
        if node.strategy != "joint_mask" or not isinstance(node.plan_slice, ColumnSeed):
            continue
        key_by = provider_config_to_dict(node.plan_slice.provider_config).get("key_by")
        if isinstance(key_by, str) and key_by:
            out.setdefault(node.table, set()).add(key_by)
    return out


def source_anchor_columns(plan: Plan, registry: ProviderRegistry) -> dict[str, set[str]]:
    """All columns a strategy reads at their immutable SOURCE value through the
    pre-mask `ctx.group_anchor_snapshots`: `date_shift` `group_by` anchors plus
    `joint_mask` `key_by` source keys. Both read a sibling's source value via the
    same pre-mask snapshot machinery, so they share one build set (the
    `date_shift` precedent reused for `joint_mask`; see the plan's §5 no-fork
    checklist). `group_key`'s `group_by` is NOT here: it reads the MASKED value
    under an ordering edge, not a source snapshot.
    """
    out = date_shift_group_columns(plan, registry)
    for table, cols in joint_mask_key_by_columns(plan, registry).items():
        out.setdefault(table, set()).update(cols)
    return out


def when_columns_of(whens: Iterable[object]) -> frozenset[str]:
    """The columns the given `when:` predicates read, from `when_column_refs` (the one producer
    of `when:` reads). A non-string or an unparsable predicate reads nothing here: the evaluator
    raises its coded error for it, so there is nothing to snapshot or ingest exactly."""
    from decoy_engine.errors import ValidationError
    from decoy_engine.expressions._when_parser import parse_when_cached, when_column_refs

    cols: set[str] = set()
    for when in whens:
        if not isinstance(when, str):
            continue
        try:
            cols.update(read.column for read in when_column_refs(parse_when_cached(when)))
        except ValidationError:
            continue
    return frozenset(cols)


def when_read_columns(plan: Plan) -> dict[str, frozenset[str]]:
    """Per table, the columns any column's `when:` reads.

    A `when:` selects rows by the ORIGINAL values of these columns, so this one set feeds both
    the lossless integer ingest (`LosslessInts.when_read`) and the pre-mask snapshot
    (`source_snapshot_columns`).
    """
    out: dict[str, frozenset[str]] = {}
    for table, table_seed in plan.seed_envelope.per_table:
        cols = when_columns_of(seed.when for _name, seed in table_seed.per_column)
        if cols:
            out[table] = out.get(table, frozenset()) | cols
    return out


def source_snapshot_columns(plan: Plan, registry: ProviderRegistry) -> dict[str, frozenset[str]]:
    """Every column snapshotted pre-mask: `source_anchor_columns` plus each `when:`-read column
    that some node writes. A `when:` column no node writes keeps its original value in the live
    frame, so it costs no copy. Both snapshot sites call this in place of `source_anchor_columns`.

    What a node writes comes from `column_access`, the one handler-write declaration (a composite
    also writes its provider's own output columns, which no config entry names). A node whose
    writes cannot be named snapshots every column its table's `when:` reads.
    """
    out = {t: frozenset(c) for t, c in source_anchor_columns(plan, registry).items()}
    reads = when_read_columns(plan)
    written: dict[str, set[str]] = defaultdict(set)
    for node in build_work_list(plan, registry):
        if node.table not in reads:
            continue
        names, unknown = node_written_columns(node)
        written[node.table] |= reads[node.table] if unknown else names
    for table, cols in reads.items():
        hit = cols & written[table]
        if hit:
            out[table] = out.get(table, frozenset()) | hit
    return out


def node_entry(node: WorkNode) -> dict[str, Any] | None:
    """The config-entry view of a `ColumnSeed` node (None for a composite FK group), the shape
    the `column_access` declarations read."""
    from decoy_engine.execution._adapter import provider_config_to_dict

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


def node_written_columns(node: WorkNode) -> tuple[frozenset[str], bool]:
    """The ONE write declaration of a work node: `(columns, unknown)`.

    The node's own columns plus what its `column_access` declaration writes (a composite's
    canonical outputs, every column a `joint_mask` config lists). `unknown` means the
    declaration cannot name the writes. This is the conservative view: the `when:` snapshot set
    and the carry's untouched set read it as is and treat `unknown` as "every column". The
    ordering edges read the dispatch view built on it, `dispatch_writes`.
    """
    from decoy_engine.execution._column_access import declared_access

    names = frozenset(node.columns)
    entry = node_entry(node)
    if entry is None:
        return names, False
    access = declared_access(entry, node.kind == "composite")
    if node.kind == "composite" and not access.writes_unknown:
        names = frozenset()  # a group member the provider does not output is read, not written
    return names | access.writes, access.writes_unknown


def dispatch_writes(node: WorkNode, graph: RelationshipGraph) -> tuple[frozenset[str], bool]:
    """`(columns, unknown)` that `_dispatch_mask_node` really writes for `node`, for the
    ordering edges. An extra edge can form a false cycle, so this view is exact where dispatch
    is known: an FK child resolves through its parent's key map before any handler runs, so it
    writes its own columns only, even when its plan slice is a composite."""
    if graph.parents_of(node.table, node.columns):
        return frozenset(node.columns), False
    return node_written_columns(node)


def node_creates_own_target(node: WorkNode) -> bool:
    """Whether `node` is a scalar that writes its own column without reading it, so the column
    may be absent from the source until the node runs."""
    from decoy_engine.execution._column_access import creates_own_target

    entry = node_entry(node) if node.kind == "scalar" else None
    return entry is not None and creates_own_target(entry)


def writer_node_map(
    work: list[WorkNode], graph: RelationshipGraph
) -> dict[tuple[str, str | None], set[_NodeKey]]:
    """Each written (table, column) -> the keys of ALL nodes that write it (`dispatch_writes`),
    so a dependent waits on every writer and reads the final value (a joint_mask group is one
    node per output, each writing every output). `(table, None)` holds the nodes whose writes
    cannot be named: they may write any column, so `writers_of` returns them for every one."""
    writer: dict[tuple[str, str | None], set[_NodeKey]] = defaultdict(set)
    for node in work:
        names, unknown = dispatch_writes(node, graph)
        if unknown:
            writer[(node.table, None)].add(node.key)
        for col in names:
            writer[(node.table, col)].add(node.key)
    return writer


def writers_of(
    writer: Mapping[tuple[str, str | None], set[_NodeKey]], table: str, column: str
) -> set[_NodeKey]:
    return writer.get((table, column), set()) | writer.get((table, None), set())


def masked_driver_columns(node: WorkNode) -> frozenset[str]:
    """The same-table sibling columns `node` reads for their MASKED value, so it
    must be ordered AFTER them (the cross-column V1 ordering edge).

    Only a scalar node whose strategy creates its own target from other columns has
    such drivers. Their names come from `scalar_creating_reads`, the same declaration
    `created_columns` admits a created column by, so a column accepted as created is
    ordered after every column it reads, for every creating strategy. Every other node
    (including `joint_mask`, whose `key_by` is a SOURCE read via snapshot) imposes no
    ordering edge.
    """
    plan_slice = node.plan_slice
    if node.kind != "scalar" or not isinstance(plan_slice, ColumnSeed):
        return frozenset()
    from decoy_engine.execution._column_access import scalar_creating_reads

    return scalar_creating_reads(node_entry(node) or {})


def composite_overwrites(
    work: list[WorkNode], writer: Mapping[tuple[str, str | None], set[_NodeKey]]
) -> dict[_NodeKey, set[_NodeKey]]:
    """Composite node -> the creating nodes whose column it also writes. The handler writes
    every bundle output and refuses one not yet on the frame, so the composite runs after the
    creator and overwrites the created value with the coherent bundle's."""
    by_key = {n.key: n for n in work}
    out: dict[_NodeKey, set[_NodeKey]] = defaultdict(set)
    for (_table, col), keys in writer.items():
        if col is None:
            continue
        composites = {k for k in keys if by_key[k].kind == "composite"}
        for k in keys - composites:
            if node_creates_own_target(by_key[k]):
                for c in composites:
                    out[c].add(k)
    return out


def column_dependency_edges(
    work: list[WorkNode], graph: RelationshipGraph
) -> dict[_NodeKey, set[_NodeKey]]:
    """The cross-column ordering channel for `order_work`: dependent-node key ->
    the keys of the nodes that write its MASKED driver columns.

    A driver resolves to its writers through `writer_node_map`; a column no node writes adds
    no edge, nor does a self-ref. SOURCE-read drivers (`joint_mask` `key_by`) read a snapshot.
    A creator a composite overwrites (`composite_overwrites`) runs first and gets no edge onto
    that composite: what it read never reaches the output, and the edge could only form a
    cycle. Cycles fall to `order_work`'s topo sort and `check_derived_column_refs`.
    """
    writer = writer_node_map(work, graph)
    overwrites = composite_overwrites(work, writer)
    deps: dict[_NodeKey, set[_NodeKey]] = defaultdict(set)
    for composite, creators in overwrites.items():
        deps[composite] |= creators
    for node in work:
        for col in masked_driver_columns(node):
            for writer_key in writers_of(writer, node.table, col):
                if writer_key != node.key and node.key not in overwrites.get(writer_key, ()):
                    deps[node.key].add(writer_key)
    return deps


def order_work(
    work: list[WorkNode],
    relationship_graph: RelationshipGraph,
    column_deps: Mapping[_NodeKey, set[_NodeKey]] | None = None,
) -> list[WorkNode]:
    """Order the work list (S9 spec §6.2).

    Dependency edges come from `relationship_graph.edges` (FK parent -> child),
    plus a composite-node -> FK-child edge whenever the composite's output
    columns are a superset of an FK's parent_columns (R17: the composite writes
    the whole bundle before any child reads a masked parent column). Topo-sorted
    with a sorted tie-break for byte-stable ordering.

    `column_deps` is the cross-column V1 channel: dependent-node key -> the keys
    of the nodes writing its MASKED driver columns (`derived` expression refs,
    `group_key` `group_by`, and the reads of every other creating strategy), so a dependent reads its drivers' masked values
    under an explicit edge instead of by lexicographic-sort accident. None means
    derive them from `work` via `column_dependency_edges` (so every route gets
    the fix); a caller/test may pass an explicit map. These edges only ADD
    constraints, so FK ordering stays dominant; a cross-column edge that
    contradicts an FK edge is a genuine cycle and raises `cyclic_work_ordering`.
    """
    by_key: dict[_NodeKey, WorkNode] = {w.key: w for w in work}
    deps: dict[_NodeKey, set[_NodeKey]] = defaultdict(set)

    for edge in relationship_graph.edges:
        parent_k = (edge.parent_table, edge.parent_columns)
        child_k = (edge.child_table, edge.child_columns)
        if child_k not in by_key:
            continue
        if parent_k in by_key:
            deps[child_k].add(parent_k)
        else:
            # Composite-key FK: the parent tuple is not a single work node; its
            # columns mask as individual scalar nodes. The composite-FK child
            # node waits on each parent column node so the parent key mapping is
            # fully masked before the child resolves against it.
            for pcol in edge.parent_columns:
                pcol_k = (edge.parent_table, (pcol,))
                if pcol_k in by_key:
                    deps[child_k].add(pcol_k)

    # R17: a composite output column that is also a FK parent. The FK child waits
    # on the whole composite bundle node, not a per-column node.
    for node in work:
        if node.kind != "composite":
            continue
        node_cols = set(node.columns)
        for edge in relationship_graph.edges:
            if edge.parent_table == node.table and set(edge.parent_columns).issubset(node_cols):
                child_k = (edge.child_table, edge.child_columns)
                if child_k in by_key:
                    deps[child_k].add(node.key)

    # Cross-column V1: a dependent waits on the node(s) writing its MASKED
    # drivers, so the read is intentional (not lexicographic luck). FK edges
    # above stay dominant: these only add constraints.
    col_deps = (
        column_dependency_edges(work, relationship_graph) if column_deps is None else column_deps
    )
    for dependent, drivers in col_deps.items():
        if dependent not in by_key:
            continue
        for driver in drivers:
            if driver in by_key:
                deps[dependent].add(driver)

    return _kahn_sorted(by_key, deps)


def _kahn_sorted(
    by_key: dict[_NodeKey, WorkNode], deps: dict[_NodeKey, set[_NodeKey]]
) -> list[WorkNode]:
    """Deterministic topological sort: at each step take the sorted-smallest node
    whose dependencies are all placed. Total order, byte-stable across runs.

    QA-10 F9 (2026-06-01): heapq-based Kahn replaces the prior O(n^2)
    "scan all keys + sort the ready set" loop. Pre-fix every
    topological step did a full `sorted(k for k in keys if ...)`,
    yielding O(n^2 log n) total work. Post-fix maintains a min-heap
    of ready nodes + an indegree counter; each node is pushed/popped
    once for O((n+e) log n) total. Output is byte-identical to the
    prior implementation (both yield the lexicographically smallest
    topological order). Same fix shape as QA-8 F1 closure on the
    relationship-graph builder.
    """
    keys = set(by_key)
    if not keys:
        return []
    # Build reverse adjacency + indegree counter so each placement
    # only revisits the children of the just-placed node, not the
    # full key set.
    rev: dict[_NodeKey, set[_NodeKey]] = defaultdict(set)
    indegree: dict[_NodeKey, int] = {k: 0 for k in keys}
    for child, parents in deps.items():
        if child not in keys:
            continue
        for parent in parents:
            if parent not in keys:
                continue
            rev[parent].add(child)
            indegree[child] += 1
    ready_heap: list[_NodeKey] = [k for k in keys if indegree[k] == 0]
    heapq.heapify(ready_heap)
    placed: list[_NodeKey] = []
    while ready_heap:
        nxt = heapq.heappop(ready_heap)
        placed.append(nxt)
        for child in sorted(rev[nxt]):
            indegree[child] -= 1
            if indegree[child] == 0:
                heapq.heappush(ready_heap, child)
    if len(placed) < len(keys):
        unplaced = sorted(k for k in keys if indegree[k] > 0)
        raise ExecutionError(
            code=reasons.runtime.CYCLIC_WORK_ORDERING,
            message=f"cycle in work-node dependencies; unresolved: {unplaced!r}",
        )
    return [by_key[k] for k in placed]
