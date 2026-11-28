"""Plan-compile checks: the foundational validation set.

Each check is a pure function taking `(config, profile)` (and sometimes
additional precomputed state) and either returning silently on pass or
raising `PlanCompileError` on fail. The full check map lives in the
compile-check ownership table (S1 spec §plan-yaml-shape).

S2 relocated two relationship-related checks into
`decoy_engine.relationships`: `namespace_ambiguity` (now performed by
`build_namespace_registry`) and `fk_plan_ordering` (now performed by
`build_relationship_graph`). The check names still appear in
`PlanCompileResult.checks_passed` to preserve the S1 -> S2 regression
contract (per S2 spec B1: `checks_passed` equals S1's list plus exactly
one new entry, `orphan_fk_policy_completeness`).

`orphan_fk_policy_completeness` (new in S2, row 6) lives in
`decoy_engine.relationships._graph.check_orphan_fk_policy_completeness`
alongside the graph builder that consumes its lookup output.
"""

from __future__ import annotations

import re
from typing import Any

from decoy_engine import reasons
from decoy_engine._error_base import raise_bare
from decoy_engine.config import relationship_shape_error
from decoy_engine.generation.pool import unique_capacity_ok
from decoy_engine.plan._errors import PlanCompileError, refusal_error
from decoy_engine.plan._pool_size import resolve_pool_size
from decoy_engine.profile._types import Profile

# Strategies under which a null-bearing integer source column is ambiguous: an
# arrow-backed int+null column widens to float64 under `to_pandas()`, which the
# deterministic remap then either reshapes or hard-errors on. B1, PO-settled
# 2026-05-28: reject at validation.
_INT_NULL_REJECTED_STRATEGIES = frozenset({"truncate", "categorical"})


def _is_integer_dtype(dtype: str) -> bool:
    """True for pandas/numpy/arrow/DB integer dtype strings.

    `ColumnProfile.dtype` is `str(series.dtype)`, so it can be `int64`,
    `int64[pyarrow]`, `Int64` (nullable), `uint32`, or a DB-source label like
    `integer` / `bigint` / `smallint`. Floats, object, datetime, interval, and
    boolean are excluded.
    """
    base = dtype.lower().split("[", 1)[0].strip()
    if base in {"integer", "bigint", "smallint", "tinyint", "int", "intp", "uintp"}:
        return True
    return bool(re.fullmatch(r"u?int(8|16|32|64)?", base))


def check_unknown_provider(config: dict[str, Any]) -> None:
    """Reject configs that reference a provider not in the registry.

    Compile-check ownership table row #2. S1 shipped this against
    `S1_STUB_REGISTRY`; S4 swapped to `get_default_registry().known_providers()`
    (the real registry from `decoy_engine.providers_v2`). Behavior contract is
    preserved: same configs accepted, same configs rejected against the
    registered set; the test signature shape changed (per S4 spec §9 + cold-
    read M4).

    The registry import is deferred inside the function. The real motivation
    is import-cycle prevention: `decoy_engine.providers_v2` and the planner
    sit on the same dependency tier, and a module-level import here can
    surface a cycle as the package grows. Faker eagerness is not the issue
    (faker is already loaded by other engine modules at package import time);
    cycle prevention is. Dennis Session 22 L1.
    """
    from decoy_engine.providers_v2 import get_default_registry

    known = get_default_registry().known_providers()
    tables = config.get("tables", []) if isinstance(config.get("tables"), list) else []
    for table_entry in tables:
        if not isinstance(table_entry, dict):
            continue
        table_name = table_entry.get("name", "?")
        for col_entry in table_entry.get("columns", []) or []:
            if not isinstance(col_entry, dict):
                continue
            provider = col_entry.get("provider")
            if provider is None:
                continue
            if provider not in known:
                col_name = col_entry.get("name", "?")
                raise PlanCompileError(
                    code=reasons.plan.UNKNOWN_PROVIDER,
                    path=f"tables.{table_name}.columns.{col_name}.provider",
                    message=(
                        f"Provider {provider!r} is not in the default registry. "
                        f"Known providers: {sorted(known)!r}. Custom providers "
                        "land via `register_faker_provider_v2` (V2) or "
                        "`register_faker_provider` (V1; until S9)."
                    ),
                )


def check_non_poolable_provider_with_pool_backend(config: dict[str, Any]) -> None:
    """Reject pool-routed columns whose provider declares poolable=False.

    Compile-check ownership table row #11 (audit H5, 2026-06-12). Pool
    routing is structural: `strategy: faker` ALWAYS builds a pool
    (FakerStrategyHandler -> PoolBuilder), and PoolBuilder.build raises
    PoolCapacityError[provider_not_poolable] at runtime for any provider
    with `poolable: False` -- so a faker column on uuid/lorem-style
    providers is guaranteed dead at `run` while passing schema
    validation. This check moves that failure to compile time. The
    capacity pre-flight (row 7) deliberately SKIPS non-poolable
    providers, so nothing else catches the combination.

    Config + registry only (no profile): safe to run in --no-profile
    mode and in config-only validation paths.
    """
    from decoy_engine.providers_v2 import get_default_registry

    registry = get_default_registry()
    known = registry.known_providers()
    tables = config.get("tables", []) if isinstance(config.get("tables"), list) else []
    for table_entry in tables:
        if not isinstance(table_entry, dict):
            continue
        table_name = table_entry.get("name", "?")
        for col_entry in table_entry.get("columns", []) or []:
            if not isinstance(col_entry, dict):
                continue
            if col_entry.get("strategy") != "faker":
                continue
            provider = col_entry.get("provider")
            if provider is None or provider not in known:
                continue  # unknown_provider (row 2) owns missing/unknown
            caps = registry.get_capabilities(provider)
            # A computed draw builds no pool; `check_computed_draws` owns its refusals.
            if not caps.poolable and caps.draw != "computed":
                col_name = col_entry.get("name", "?")
                raise PlanCompileError(
                    code=reasons.plan.NON_POOLABLE_PROVIDER_WITH_POOL_BACKEND,
                    path=f"tables.{table_name}.columns.{col_name}.provider",
                    message=(
                        f"Provider {provider!r} declares poolable=False but column "
                        f"{table_name}.{col_name} uses strategy 'faker', which always "
                        "routes through the pool backend and fails at runtime with "
                        "provider_not_poolable. Use a poolable provider, a keyed "
                        "strategy (hash / fpe) for deterministic identifiers, or "
                        "redact."
                    ),
                )


def check_basic_uniqueness_pre_flight(config: dict[str, Any], profile: Profile) -> None:
    """Reject pool-backed `unique` configs whose non-null output-row count
    exceeds the pool capacity hint. If no pool_size is declared the check
    passes and the runtime discovers any failure later.

    DE-11: UNIQUE capacity is the non-null output-row count (row_count -
    null_count), shared with the runtime sampler via `unique_capacity_ok`;
    pool_size is resolved from both declaration sites via `resolve_pool_size`.
    Compile-check ownership table row #4.
    """
    nonnull_lookup: dict[tuple[str, str], int] = {}
    for table in profile.tables:
        for col in table.columns:
            nonnull_lookup[(table.name, col.name)] = col.row_count - col.null_count

    tables = config.get("tables", []) if isinstance(config.get("tables"), list) else []
    for table_entry in tables:
        if not isinstance(table_entry, dict):
            continue
        table_name = table_entry.get("name", "?")
        for col_entry in table_entry.get("columns", []) or []:
            if not isinstance(col_entry, dict):
                continue
            if col_entry.get("cardinality_mode") != "unique":
                continue
            if col_entry.get("backend_type") != "pool":
                continue
            col_name = col_entry.get("name", "?")
            # Resolve from both sites so a provider_config-only pool_size is
            # checked here, not silently deferred to a late runtime failure.
            pool_size = resolve_pool_size(col_entry, table_name=table_name, col_name=col_name)
            if pool_size is None:
                continue
            nonnull_rows = nonnull_lookup.get((table_name, col_name))
            if nonnull_rows is None:
                continue
            if not unique_capacity_ok(pool_size, nonnull_rows):
                raise PlanCompileError(
                    code=reasons.plan.POOL_CAPACITY_PRE_FLIGHT_UNIQUE,
                    path=f"tables.{table_name}.columns.{col_name}",
                    message=(
                        f"Column {table_name}.{col_name} uses cardinality_mode=unique "
                        f"with pool_size={pool_size}, but the pool must supply one unique "
                        f"value per non-null output row ({nonnull_rows}). The pool "
                        "cannot supply enough unique values; raise pool_size or pick "
                        "a different cardinality_mode."
                    ),
                )


def check_null_bearing_int_unsupported(config: dict[str, Any], profile: Profile) -> None:
    """Reject integer + null-bearing source columns under truncate/categorical.

    Compile-check ownership table row #10 (B1, S13). PO-settled 2026-05-28: a
    column that is integer-typed AND null-bearing is REJECTED at plan-compile when
    masked under truncate / categorical, because its masked value is
    ambiguous: `to_pandas()` widens an arrow-backed int+null source to float64
    before the deterministic remap sees it. This is the same class of
    "ambiguous numeric source" the S5 float-canonicalization hard error already
    rejects. Remediation: stringify or bin the column upstream.

    Profile-dependent (reads `dtype` + `null_count`), so under `no_profile=True`
    it lands in `checks_skipped`; the execution-time guard
    (`decoy_engine.execution` `reject_null_bearing_int`) is the backstop there.
    """
    null_int_lookup: dict[tuple[str, str], bool] = {}
    for table in profile.tables:
        for col in table.columns:
            null_int_lookup[(table.name, col.name)] = (
                _is_integer_dtype(col.dtype) and col.null_count > 0
            )

    # FK-child columns are EXEMPT: they are resolved through the relationship edge
    # (not masked by the strategy), and an FK job runs via the pandas oracle on
    # both substrates, so the int+null divergence cannot arise for them. Matches
    # the execution-time guard's FK exemption.
    fk_child_columns: set[tuple[str, str]] = {
        (rel.child_table, child_col)
        for rel in profile.relationships
        for child_col in rel.child_columns
    }

    tables = config.get("tables", []) if isinstance(config.get("tables"), list) else []
    for table_entry in tables:
        if not isinstance(table_entry, dict):
            continue
        table_name = table_entry.get("name", "?")
        for col_entry in table_entry.get("columns", []) or []:
            if not isinstance(col_entry, dict):
                continue
            if col_entry.get("strategy") not in _INT_NULL_REJECTED_STRATEGIES:
                continue
            col_name = col_entry.get("name", "?")
            if (table_name, col_name) in fk_child_columns:
                continue
            if not null_int_lookup.get((table_name, col_name), False):
                continue
            raise PlanCompileError(
                code=reasons.plan.NULL_BEARING_INT_UNSUPPORTED,
                path=f"tables.{table_name}.columns.{col_name}",
                message=(
                    f"Column {table_name}.{col_name} is an integer column with nulls "
                    f"masked under {col_entry.get('strategy')!r}. Integer-with-null is "
                    "not supported under truncate/categorical: the masked value is "
                    "ambiguous across execution substrates (int widens to float on one "
                    "path, stays integer on the other). Stringify or bin this column "
                    "upstream. This mirrors the float-canonicalization hard error."
                ),
            )


def check_composite_columns_length_match(profile: Profile) -> None:
    """Every relationship's parent.columns and each child.columns must
    have the same length.

    `Relationship.__post_init__` enforces this at construction; this check also
    catches a Profile deserialized without it. The rule is `relationship_shape_error`.

    Compile-check ownership table row #5.
    """
    for rel in profile.relationships:
        pair = {"table": rel.parent_table, "columns": rel.parent_columns}
        kid = {"table": rel.child_table, "columns": rel.child_columns}
        if relationship_shape_error({"parent": pair, "children": [kid]}) is not None:
            raise PlanCompileError(
                code=reasons.plan.COMPOSITE_COLUMNS_LENGTH_MISMATCH,
                path=(
                    f"relationships[{rel.parent_table}.{rel.parent_columns}->"
                    f"{rel.child_table}.{rel.child_columns}]"
                ),
                message=(
                    f"Relationship {rel.parent_table}.{rel.parent_columns} -> "
                    f"{rel.child_table}.{rel.child_columns}: parent columns length "
                    f"{len(rel.parent_columns)} != child columns length {len(rel.child_columns)}."
                ),
            )


def check_statistical_columns(
    config: dict[str, Any],
    pinned: dict[str, Any] | None = None,
    dp_verified_columns: frozenset[tuple[str, str]] = frozenset(),
    failures: dict[str, Any] | None = None,
) -> list[tuple[str, str, str, dict[str, Any]]]:
    """Validate `type: statistical` generate columns against their snapshots.

    Compile-check ownership table row #12 (capability-gaps WS3,
    2026-06-12). A statistical column is guaranteed dead at run when its
    snapshot_file is unreadable, the source column is absent from the
    artifact, the snapshot kind has no sampler (an all-null "empty"
    column; freetext is admitted since deferred follow-up 4), a
    categorical column lacks the `allow_real_categories: true`
    disclosure opt-in (unless the compiler has DP-verified it, guide
    section 5), or `condition_on` names a pair the snapshot has no joint
    table for. `generation/statistical.load_spec` owns those verdicts
    (one set of error codes for compile time and generation time); this
    check adds the declared-order rule load_spec cannot see: the
    condition_on column must be generated BEFORE its dependent in the same table.

    `pinned` is the compiler's `{path: ReadSnapshot}` read-once map
    (`plan._generation.read_and_pin_snapshots`). `failures` is that same
    read-once pass's `{path: StatisticalSpecError}` classification of
    every path it could not open or parse (C-M1, round-3 remediation): a
    path absent from `pinned` raises the CLASSIFIED failure from
    `failures` rather than reopening it, so a compile that ran the read-
    once pass never calls `open()` a second time for any path. `failures
    =None` means no read-once pass ran at all (a direct/legacy caller,
    e.g. a test building a spec by hand); only then does this function
    fall back to a direct read via `plan._generation.resolve_pinned_
    snapshot`. `dp_verified_columns` is the `(table, column)` set
    `plan._checks_dp.verify_dp_snapshots` certified as an OpenDP release.
    Returns `(table_name, column_name,
    snapshot_path, spec_dict)` per validated statistical column, in
    declared order, fed to `plan._generation.build_generation_plan`.

    Config + snapshot artifact only (no profile, no source data): the
    snapshot is a config-referenced fitted-model file, so config-only
    callers (decoy validate) catch a bad artifact before a long run.

    HC-5: `high_cardinality` (full-vocabulary retention opt-in) is meaningful
    only for `type: statistical` columns; `load_spec` validates its
    dependency on `allow_real_categories` and its snapshot-kind requirement,
    but it never sees non-statistical columns, so the "wrong type entirely"
    case (a `faker`/`sequence`/... column carrying a stray `high_cardinality`
    key) is caught here instead.
    """
    from decoy_engine.generation.statistical import check_degenerate, load_spec, spec_to_dict
    from decoy_engine.generation.statistical._spec import StatisticalSpecError
    from decoy_engine.plan._generation import resolve_pinned_snapshot, statistical_refusal

    pinned = pinned or {}
    column_specs: list[tuple[str, str, str, dict[str, Any]]] = []
    tables = config.get("tables", []) if isinstance(config.get("tables"), list) else []
    for table_entry in tables:
        if not isinstance(table_entry, dict):
            continue
        table_name = table_entry.get("name", "?")
        for col_entry in table_entry.get("generate_columns", []) or []:
            if not isinstance(col_entry, dict):
                continue
            col_name = col_entry.get("name", "?")
            col_type = col_entry.get("type")
            if col_type != "statistical" and "high_cardinality" in col_entry:
                raise PlanCompileError(
                    code=reasons.plan.STATISTICAL_HIGH_CARDINALITY_WRONG_TYPE,
                    path=f"tables.{table_name}.generate_columns.{col_name}.high_cardinality",
                    message=(
                        f"generate column {col_name!r}: high_cardinality is only valid "
                        f"for `type: statistical` columns (got type {col_type!r})."
                    ),
                )
            if col_type == "statistical":
                snapshot_file = col_entry.get("snapshot_file")
                if not snapshot_file:
                    raise PlanCompileError(
                        code=reasons.plan.STATISTICAL_SNAPSHOT_FILE_REQUIRED,
                        path=f"tables.{table_name}.generate_columns.{col_name}",
                        message=f"statistical column {col_name!r} requires `snapshot_file`.",
                    )
                snapshot_file = str(snapshot_file)
                read = pinned.get(snapshot_file)
                failure: PlanCompileError | None = None
                try:
                    snap = resolve_pinned_snapshot(snapshot_file, pinned, failures)
                    dp_verified = (table_name, col_name) in dp_verified_columns
                    # Thread the read-once pass's own digest onto the spec
                    # (guide section 4.7/4.8, defect F4) so generation-time
                    # seed derivation reuses it instead of reopening
                    # snapshot_file to rehash it later.
                    spec = load_spec(
                        col_entry,
                        snapshot=snap,
                        dp_verified=dp_verified,
                        snapshot_digest=read.sha256 if read is not None else None,
                    )
                    check_degenerate(spec)
                except StatisticalSpecError as exc:
                    refusal = statistical_refusal(exc.code, snapshot_file, table_name, col_name)
                    failure = refusal_error(exc.code, refusal)
                if failure is not None:
                    raise_bare(failure)
                # condition_on ordering is checked by plan/checks/_generate_columns.py.
                column_specs.append((table_name, col_name, snapshot_file, spec_to_dict(spec)))
    return column_specs


def _check_ner_available_for_strategy(config: dict[str, Any], strategy: str) -> None:
    """Shared body of rows #13 and #30: reject `strategy` columns whose `ner` cannot run here.

    A column that opts in while spaCy or its model is missing is dead at run. Config and
    installed packages only (no model load, no profile): safe for `decoy validate`.
    """
    from decoy_engine.detection import ner  # module import keeps the legacy-file LOC flat

    tables = config.get("tables", []) if isinstance(config.get("tables"), list) else []
    for table_entry in tables:
        if not isinstance(table_entry, dict):
            continue
        table_name = table_entry.get("name", "?")
        for col_entry in table_entry.get("columns", []) or []:
            if not isinstance(col_entry, dict):
                continue
            if col_entry.get("strategy") != strategy:
                continue
            provider_config = col_entry.get("provider_config") or {}
            ner_cfg = provider_config.get("ner") if isinstance(provider_config, dict) else None
            if not ner_cfg:
                continue
            col_name = col_entry.get("name", "?")
            refusal = None
            try:
                model = str(ner.resolve_column_ner(ner_cfg)[0])
                ner.ensure_ner_available(model, ner.NerSurface(strategy))
            except ner.NerUnavailableError as exc:
                refusal = exc
            if refusal is not None:  # raised outside the handler: no cause, no context
                raise PlanCompileError(
                    code=refusal.code,
                    path=f"tables.{table_name}.columns.{col_name}.provider_config.ner",
                    message=refusal.message,
                )


def check_text_redact_ner_available(config: dict[str, Any]) -> None:
    """Reject `text_redact` columns whose `ner` config cannot run here.

    Compile-check ownership table row #13 (capability-gaps WS2,
    2026-06-12). NER is an optional capability (the `ner` extra plus a
    separately-downloaded spaCy model); a column that opts in while
    either piece is missing is guaranteed dead at run. Config + installed
    packages only (no model load, no profile): safe for config-only
    callers (decoy validate).
    """
    _check_ner_available_for_strategy(config, "text_redact")


def check_text_mask_ner_available(config: dict[str, Any]) -> None:
    """Reject `text_mask` columns whose `ner` config cannot run here (TX-2).

    Compile-check ownership table row #30 (TX-2, 2026-07-20): the text_mask
    analog of row #13 above, now that text_mask has its own `ner` opt-in
    (`_strategies/_text_mask.py`). Same optional-dependency reasoning, same
    fail mode (dead at run without this check).
    """
    _check_ner_available_for_strategy(config, "text_mask")


def check_derived_column_refs(config: dict[str, Any]) -> None:
    """Reject derived columns whose expression refs are missing or cyclic.

    Compile-check ownership table row #16 (SP-10 / P5.S.derived, 2026-06-28).
    Two failure modes caught here (plan-compile time, before any execution):

    1. Missing column ref: an expression references a column name that is not
       present in the same table's ``columns`` or ``generate_columns``. A
       missing ref is guaranteed to raise KeyError at row-evaluation time;
       rejecting it here surfaces the error with a clear message and the exact
       missing name.

    2. Cyclic reference: a derived column's expression depends (directly or
       transitively) on itself. Direct self-reference (``b: expression: b + 1``)
       and transitive cycles (``a -> b -> a``) are both detected via DFS over
       the dependency graph of derived columns in the same table.

    Validation never mutates (per engine rule). Config-only (no profile, no
    source data), so it runs in both compile branches and in
    ``run_config_only_checks``.

    Args:
        config: Raw pipeline config dict.

    Raises:
        PlanCompileError: A missing column ref or cyclic dependency is found.
    """
    from decoy_engine.expressions import column_refs, compile_expr

    tables = config.get("tables", []) if isinstance(config.get("tables"), list) else []
    for table_entry in tables:
        if not isinstance(table_entry, dict):
            continue
        table_name = table_entry.get("name", "?")

        # Build the full set of column names known in this table.
        all_col_names: set[str] = set()
        for col_entry in table_entry.get("columns", []) or []:
            if isinstance(col_entry, dict) and col_entry.get("name"):
                all_col_names.add(str(col_entry["name"]))
        for col_entry in table_entry.get("generate_columns", []) or []:
            if isinstance(col_entry, dict) and col_entry.get("name"):
                all_col_names.add(str(col_entry["name"]))

        # Collect derived column definitions: {col_name -> frozenset of refs}.
        # Scans both mask-kind columns (strategy: derived, provider_config.expression)
        # and generate-kind columns (type: derived, flat expression key). The
        # generate_columns union in all_col_names is LIVE once derived works in
        # generate tables.
        derived_refs: dict[str, frozenset[str]] = {}

        def _derived_col_entries(t: dict[str, Any]) -> Any:
            """Yield (col_name, expr, col_kind) per derived column. t passed
            explicitly to avoid capturing the loop variable (ruff B023)."""
            for e in t.get("columns") or []:
                if isinstance(e, dict) and e.get("strategy") == "derived":
                    yield (
                        e.get("name", "?"),
                        (e.get("provider_config") or {}).get("expression"),
                        "columns",
                    )
            for e in t.get("generate_columns") or []:
                if isinstance(e, dict) and e.get("type") == "derived":
                    yield e.get("name", "?"), e.get("expression"), "generate_columns"

        for col_name, expr, col_kind in _derived_col_entries(table_entry):
            if not expr:
                continue  # missing expression: DerivedConfig.from_dict catches at execution time
            try:
                compiled = compile_expr(str(expr))
            except Exception:
                continue  # invalid syntax: ValidationError at execution time; skip double-report
            refs = column_refs(compiled)
            missing = refs - all_col_names
            if missing:
                raise PlanCompileError(
                    code=reasons.plan.DERIVED_MISSING_COLUMN_REF,
                    path=f"tables.{table_name}.{col_kind}.{col_name}.expression",
                    message=(
                        f"derived column {col_name!r} in table {table_name!r} "
                        f"references column(s) {sorted(missing)!r} that are not "
                        f"defined in the same table. Available columns: "
                        f"{sorted(all_col_names)!r}. "
                        f"Column references must be bare identifiers matching a "
                        f"column name in the same table."
                    ),
                )

            derived_refs[str(col_name)] = refs

        # Check 2: cyclic dependencies among derived columns.
        # DFS from each derived column; detect back-edges.
        # all_derived is passed explicitly so the function does not capture
        # a loop-scoped variable (avoids ruff B023).
        def _has_cycle(
            start: str,
            visited: set[str],
            path: set[str],
            all_derived: dict[str, frozenset[str]],
        ) -> bool:
            if start in path:
                return True
            if start in visited:
                return False
            if start not in all_derived:
                return False
            visited.add(start)
            path.add(start)
            for dep in all_derived[start]:
                if dep in all_derived and _has_cycle(dep, visited, path, all_derived):
                    return True
            path.discard(start)
            return False

        visited: set[str] = set()
        for col_name in derived_refs:
            path: set[str] = {col_name}
            for dep in derived_refs[col_name]:
                if dep in derived_refs and _has_cycle(dep, visited, path, derived_refs):
                    raise PlanCompileError(
                        code=reasons.plan.DERIVED_CYCLIC_REFERENCE,
                        path=f"tables.{table_name}.columns.{col_name}.provider_config.expression",
                        message=(
                            f"derived column {col_name!r} in table {table_name!r} "
                            f"has a cyclic dependency: the expression dependency graph "
                            f"contains a cycle involving {col_name!r}. "
                            f"Cyclic derived columns cannot be evaluated. "
                            f"Refactor to remove the cycle."
                        ),
                    )
            visited.add(col_name)
