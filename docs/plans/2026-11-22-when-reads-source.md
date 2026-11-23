Status: plan (revision 2.1, 2026-11-23; amendment A1 from the S1 build: one reader for the chunk read set, the rev9 backtick tests; revision 2, 2026-11-22: Dennis R1 items closed, owner grammar seam added)

# WHEN-READS-SOURCE: a `when:` condition reads the original value on every route

Owner: Cam. Author: Opus (plan author). Date: 2026-11-22. Roadmap row: WHEN-READS-SOURCE (new, V1, owner decision 2026-11-22). Two engine slices (S1 grammar seam, S2 source reads), plus doc lines in the CLI repo carried by the next CLI docs PR.

Anchors: a path with no prefix is in this repository (decoy-engine) under `src/decoy_engine/`; `tests/` and `docs/` are repository paths; `CLI:` is the decoy CLI repo. Read at engine `origin/main` `70881ad79` (0.28.3). Line numbers are at that head.

Rules consulted: dev-rules `README.md`, `00-universal.md`, `development-loop.md` (PLAN, Proportion), `risk-and-exceptions.md`, `bugfix.md`, `feature-dev.md`, `architecture.md`, `cross-cutting-concerns.md`, `reuse-first.md`, `scope-discipline.md`, `proportionality.md`, `testing.md` (Test depth), `catalogs/recurring-defects.md`, `api-and-compatibility.md`, `security.md` (value-free errors), `documentation.md`, `workspace-and-vcs.md`; engine `CLAUDE.md` and `CODEMAP.md` ("Where Things Go").

Risk: R2. S1 widens a frozen surface (the `when:` grammar, contract 3.4) in an additive way. S2 changes masked output on the pandas routes for configs where a `when:` names a column that another column masks, and removes one native decline. Plan review: Dennis, then Codex. Code gate per slice: Codex and Dennis (`/code-review high`: masking lane). T3 full suite at the S2 merge head (golden outputs change); S1 runs T3 too, because it touches a frozen contract. Mutations on the changed units.

Revision 2 closes Dennis R1: the `LosslessInts` split stays and calls one new reader; one snapshot helper serves both snapshot sites and snapshots only columns some node writes; the native tests use admitted strategies; W1 no longer depends on a column-keyed seed; the route list drops out-of-core; the F29 fixtures, baselines and contract text are listed. It also adds the owner's grammar seam (section 3, guarantees 8 to 10).

## 1. Frame

**The contract (owner, 2026-11-22).** "`when:` picks rows by the row's ORIGINAL values, from any column. Mask `email` only on rows where the original `country` = 'US'." The condition selects rows by the values the source had, before any column of the job was masked.

**The defect.** The pandas oracle breaks that contract. `run_with_when_gate` (`execution/_when_gate.py:434`) evaluates the predicate on `df` (`:477`), the live frame that earlier nodes have already masked. So the rows a `when:` selects depend on column order:

```yaml
columns:
  - name: status          # sorts before zz_email, so it is masked first
    strategy: hash
    namespace: ns
  - name: zz_email
    strategy: redact
    when: "status == 'active'"   # oracle compares the HASH of status to 'active': matches nothing
```

Rename `zz_email` to `aa_email` and the predicate sees the original `status`, so the active rows are masked. The same config means two different things depending on a column name. In the first form the `email` values that should be masked are written out unmasked. That is a data leak.

The native lanes already read the original values: the chunked native leg evaluates on the raw chunk (`execution/native/_when_mask.py:52-60`) and the unified slice on `candidate.source_frame` (`execution/_unified_slice_when.py:73-90`). To keep them equal to the defective oracle, native admission declines any `when:` that reads a column masked earlier (`execution/native/_when_admission.py:169-175`, code `when_predicate_reads_masked_column`). That decline is a guard around the defect, not a rule of the contract.

**Out of scope.** A created column keeps reading the masked value of its drivers. The creating strategies are the ones whose declaration is `OWN_TARGET_CREATES`: `derived`, `derived_aggregate`, `grouped_series`, `windowed_date` and `group_key` (`execution/_column_access.py:329-335`; `scalar_creating_reads` at `:391`). `formula` is not one of them: it rewrites its own column and has no ordering edge. Only the `when:` gate changes.

## 2. Established solutions

Search run: how SQL engines and dataframe libraries evaluate a condition inside a multi-column update; how they name a column that holds a dot; how this codebase already reads a pre-mask value.

- **SQL `UPDATE ... SET a = f(a), b = CASE WHEN a = 'x' THEN g(b) ELSE b END`.** Every expression on the right side reads the row as it was before the statement (SQL standard; PostgreSQL, SQL Server and DuckDB all behave this way). The order of the `SET` list does not matter. With this plan, `when:` behaves like a SQL `CASE WHEN` inside one `UPDATE`.
- **SQL trigger `OLD.col` / `NEW.col`.** PostgreSQL and MySQL triggers name the before and after value of a row with a prefix. The `source.` and `masked.` prefixes follow that model: one name, two phases, the prefix says which.
- **Polars `with_columns`.** All expressions in one call read the input frame, never each other's output.
- **pandas `DataFrame.assign`** with several keyword arguments evaluates callables in order against the updated frame. That is today's oracle behavior, and the reason the defect exists.
- **Quoted names.** pandas `eval`/`query`, Spark SQL and MySQL quote a column name that is not a plain identifier with backticks. Double quotes are already string literals in the `when:` grammar, so backticks are the only free choice.
- **In this codebase:** `joint_mask` `key_by` and `date_shift` `group_by` already read a pre-mask value through `ctx.group_anchor_snapshots`, built from `source_anchor_columns` (`execution/_runner.py:265-279`) before the node loop (`execution/_pandas_adapter.py:199`, `:209-214`; `execution/_sequential.py:329`, `:452-454`). `joint_mask` fails closed when its snapshot is missing (`execution/_strategies/_joint_mask.py:79-90`, `JOINT_MASK_KEY_BY_SNAPSHOT_MISSING`). This plan reuses that mechanism. It adds no second snapshot dict.

### Reuse inventory

- `execution/_runner.py:265` `source_anchor_columns`, the pre-mask `ctx.group_anchor_snapshots` and its two build sites (`execution/_pandas_adapter.py:209-214`, `execution/_sequential.py:452-454`): the snapshot.
- `execution/_runner.py:301` `_writer_node_map` over `build_work_list` (`:101`), with `_writer_output_columns` (`:281-298`): which columns some node writes.
- `execution/_fk_keys.py:336-360` `LosslessInts` and its `exact` / `when_read` split: unchanged; only its `when_read` source moves.
- `expressions/_when_parser.py:294` `when_column_refs`: the one reader of the names a predicate reads, now typed.
- `execution/_when_gate.py:328` `_eval_predicate`: the one evaluator.
- `reasons/route/_retired.py:14-19`: the tombstone pattern for shipped codes. `replaced_by` is optional: `reasons/_types.py:98` defaults it to `None`, and the registry check (`reasons/_registry.py:202-205`) only tests a `replaced_by` that is set.

## 3. Guarantee and non-goals

After this plan:

1. On every route that evaluates `when:` (full-frame oracle, sequential FK route, chunked oracle, chunked native leg, unified slice), a predicate is evaluated on the original values of the columns it names. The original value is the value the masking stage received, after declared casts and `transforms`/`derive`, before any column is masked. Out-of-core refuses `when:` today (`execution/out_of_core/_compat.py:255-258`, `out_of_core_when_predicate_unsupported`) and still does.
2. **One reader of `when:` columns.** `when_read_columns(plan) -> dict[str, frozenset[str]]` (new, `execution/_runner.py`, beside `joint_mask_key_by_columns`) returns, per table, the columns any `ColumnSeed.when` reads, from `when_column_refs` (guarantee 9). `_fk_keys.lossless_int_columns` keeps the `LosslessInts` `exact` / `when_read` split exactly as it is (`execution/_fk_keys.py:336-360`, `:399`) and fills `when_read` from `_runner.when_read_columns`. The private duplicate `_fk_keys._when_read_columns` (`:315-333`) is deleted. `source_anchor_columns` is unchanged, so a `when:` column never joins the `exact` set.
3. **One snapshot helper.** `source_snapshot_columns(plan, registry) -> dict[str, frozenset[str]]` (new, `execution/_runner.py`) returns `source_anchor_columns ∪ written_when_reads`, where `written_when_reads` is each `when_read_columns` entry that `_writer_node_map(build_work_list(plan, registry))` holds as `(table, column)`. Both snapshot sites call it in place of `source_anchor_columns`: `_pandas_adapter.py:199` and `_sequential.py:329` (the set that `:452-454` snapshots per table). Each swap is one call for another, so `_sequential.py` stays at 679 of its 680 ceiling before the context line in guarantee 4.
4. **One evaluation input.** `StrategyContext` (`execution/_adapter.py:146`) gains `source_snapshot_columns: Mapping[str, frozenset[str]] | None = None`, set by both sites to the helper's result. `run_with_when_gate` evaluates the predicate on `when_source_frame(df, ctx, table, reads)` (new, `execution/_when_gate.py`):
   - `ctx.source_snapshot_columns is None` for a node with a `when:`: raise `when_source_snapshot_missing` (new runtime code, value-free). A route that forgot the snapshot fails closed.
   - a read in `ctx.source_snapshot_columns[table]`: the snapshot, aligned by label (`snapshot.loc[df.index]`); a missing snapshot key raises the same code;
   - any other read: `df[column]`. No node writes that column, so the live value is the original value.
   - a read the frame does not hold: `when_expression_error`, as today.
5. **Memory cost.** One `Series.copy()` per `(table, column)` that a `when:` reads and some node writes, held for the table's node loop (the sequential route evicts it at `_sequential.py:579-580`). For object or nullable integer columns the copy is the value array: about 8 to 9 MB per million rows per column; the string objects are shared, not copied. On the chunked oracle the copy is per chunk. A column that a `when:` reads but no node writes costs nothing. This is the cost the `key_by` and `group_by` anchors already pay.
6. **Decline removed.** `when_native_rejection` no longer calls `_earlier_writes`. `_earlier_writes`, `READS_MASKED_CODE` and its `_WHEN_DECLINE_CODES` entry (`_when_admission.py:43`, `:85-115`, `:169-175`, `:194`, `:299`) are deleted, and so is `RouteDeclineCode.WHEN_READS_MASKED_COLUMN` (`native/_route_decline_codes.py:51`). The registry codes `route.when_reads_masked_column` (`reasons/route/_part1.py:106`, `:146`) and `runtime.when_predicate_reads_masked_column` (`reasons/runtime/_part3.py:106`, `:380`) shipped in tagged releases, so they become tombstones with `deprecated_in` set to the release that carries S2 and no `replaced_by` (the `_retired.py:14-19` pattern; a runtime `_retired.py` beside it if the runtime catalog has none). A config that declined natively for this reason now runs natively when its strategy and target type are admitted (`ADMITTED_WHEN_STRATEGIES`, `_when_admission.py:45-47`, with a `string` target).
7. Created columns are unchanged and still read masked drivers in work order. The ordering edges (`column_dependency_edges`, `execution/_runner.py:354`) are unchanged; `when:` still adds no edge. The `scalar_creating_reads` docstring (`_column_access.py:396-399`, "the gate reads the frame as it stands when the entry runs") is corrected to "the gate reads original values".

**The grammar seam (S1, owner 2026-11-22).** The aim is that 1.x can add masked reads with no refactor.

8. **Reserved reference prefixes.** A column reference in `when:` is one of:
   - `<col>`: a bare name. It means `source.<col>`.
   - `source.<col>`: the original value.
   - `masked.<col>`: the value after masking. In V1 the parser refuses it with the new code `when_masked_reference_unsupported` (registered, value-free; message "a `masked.` reference in `when:` is planned for 1.x; V1 reads original values only").
   - `` `<name>` `` or `` source.`<name>` ``: a backtick-quoted name, for a column whose name holds a dot or another character outside `[A-Za-z0-9_]`. A quoted name holds no backtick, backslash or control character.
   - an unquoted dotted name whose prefix is not `source` or `masked` (`a.b == 1`) is refused with `when_outside_closed_grammar` and the reason "only `source.` or `masked.` may prefix a column; quote a column name that holds a dot with backticks".
   `source` and `masked` are not keywords. A column named `source` still works bare (`source == 'web'`); the prefix is recognized only before a dot. The reserved-name checks (`_name`, `_when_parser.py:120-128`) apply to the column part, quoted or not, so quoting does not bypass the frozen `RESERVED_NAMES`.
9. **Typed reads.** `WhenRead(column: str, phase: Literal["source", "masked"])` (new frozen dataclass, `expressions/_when_parser.py`). `Compare` and `InList` gain `phase` (default `"source"`). `when_column_refs(ast) -> tuple[WhenRead, ...]`, sorted and de-duplicated. Every consumer takes this one type: native admission (`_when_admission.py:160`, `:287`), the native row mask (`native/_when_mask.py:44`), the unified slice (`_unified_slice_when.py:68`), the chunk guard (`_chunked_when_guard.py:120`), the gate (`_when_gate.py:290`, `:370`), and `when_read_columns` (so the snapshot helper and `LosslessInts`). In V1 every read in a parsed AST has phase `source`.
10. **One rendering for evaluation.** pandas `eval` cannot read `source.status` or a backtick name with a dot the way the grammar means them. `_eval_predicate` therefore evaluates an aliased form: it maps each read column to a positional alias (`_w0`, `_w1`, ...), builds the evaluation frame from those columns under the aliases, and renders the text with `render_when(ast)` (new, `expressions/_when_parser.py`, the same leaf rendering `_leaf_text` does today at `_when_gate.py:320-325`). The exact-integer path and `when_eval_frame` run on the aliased frame and AST unchanged. A predicate with no prefix and no quote gives the same mask as before.

Non-goals: any change to created-column reads; a `when:` that names a created column (still refused, `created_columns` at `_column_access.py:432`); evaluating `masked.` reads (1.x); new comparison operators; native admission of `when:` cases declined for other reasons (`when_predicate_not_native`, `when_predicate_outside_native_subset`); out-of-core `when:` support; performance work on the gate.

## 4. Enumerations

### Exit paths

- Unknown column in a predicate: `when_expression_error`, as today (raised before eval when the frame lacks a read).
- Snapshot set or snapshot missing for a read some node writes: `when_source_snapshot_missing` (new), value-free, exit 3. Not reachable in production; a guard for a route that forgets the snapshot.
- `masked.` reference: `when_masked_reference_unsupported` (new) at config load (`config/_tables.py:214-221`, which today raises only `WHEN_OUTSIDE_GRAMMAR_CODE` and now passes `exc.code` through), at plan check (`plan/_checks_when.py:82-100`, mapped to the plan-namespace code) and in `validate_envelope_when` (`_when_parser.py:242`).
- Dotted name without quotes or with an unknown prefix: `when_outside_closed_grammar`, as any other grammar refusal.
- Every other `when:` error: unchanged codes (`when_outside_closed_grammar`, `numexpr_required`, `when_expression_not_boolean`).

### Routes

- Full-frame oracle: `PandasExecutionAdapter.run`, the one caller of `run_with_when_gate` (`execution/_pandas_adapter.py:423`). Snapshot built at `:209-214` from `source_snapshot_columns`.
- Sequential FK route: snapshot built per table at `execution/_sequential.py:452-454` from the set computed at `:329`; dispatch goes through the same gate.
- Chunked oracle: runs `PandasExecutionAdapter.run` per chunk (`execution/_chunked_oracle.py:450`), so the snapshot is per chunk. A `when:` is row-local, so per-chunk snapshots give the same rows as one full snapshot.
- Chunked native leg and unified slice: read the raw source today; unchanged except for the typed reads; now also admitted for the former `reads_masked` cases.
- Out-of-core: refuses any node with a `when:` (`out_of_core/_compat.py:255-258`); unchanged.

### FK shapes

- A `when:` that reads an FK key column: the key is in the `exact` set and is snapshotted with the lossless conversion when a node writes it. Covered by `tests/unit/execution/test_o1_when_eval_frame.py:139` (`test_fk_key_read_by_when_stays_exact`), which must still pass.
- An FK child column with a `when:` on the sequential route: same snapshot rule per table (W5).

### Fields

- New: `WhenRead`; `Compare.phase`, `InList.phase`; `StrategyContext.source_snapshot_columns`.
- New reason codes: `when_masked_reference_unsupported` (config, plan and runtime namespaces, beside each `WHEN_OUTSIDE_CLOSED_GRAMMAR`: `reasons/config/_part1.py:198`, `reasons/plan/_part2.py:302`, `reasons/runtime/_part3.py:224`); `when_source_snapshot_missing` (runtime).
- Tombstoned: `route.when_reads_masked_column`, `runtime.when_predicate_reads_masked_column`.
- Removed enum member: `RouteDeclineCode.WHEN_READS_MASKED_COLUMN`.

### Output surfaces

- Masked output of any table where a `when:` names a column that some node masks earlier in work order (section 10).
- `chunked_route` and unified-slice evidence: such tables now admit natively, so `reroute_reason` and `decline_records` lose the `when_predicate_reads_masked_column` entry, and `executed_backend` becomes the native backend.
- Output type of a newly native-admitted chunked `when:` column: pinned to `string` on both chunked legs, as the contract already states for native-admitted `when:` columns (`docs/compatibility-contract.md:1045-1056`).

## 5. Slices and size

### Slice S1: grammar seam (no output change)

| File | Lines now | Change | Expected after |
|---|---|---|---|
| `expressions/when_grammar.lark` | 50 | `ref` rule (bare, quoted, prefixed), `QUOTED_NAME` terminal; comment block | about 62 |
| `expressions/_when_parser.py` | 340 | `WhenRead`; `phase` on `Compare`/`InList`; `bare_ref`/`phase_ref` transforms; masked refusal; `when_column_refs` typed; `render_when`, `alias_reads` | about 410 |
| `execution/_when_gate.py` | 541 | `_eval_predicate` evaluates the aliased frame and `render_when` text; `_leaf_text` reuses the renderer | about 555 |
| `execution/native/_when_admission.py`, `native/_when_mask.py`, `_unified_slice_when.py`, `_chunked_when_guard.py`, `_fk_keys.py` | 307, 101, 98, 132, 575 | read `.column` from typed reads | +1 to +3 each |
| `config/_tables.py`, `plan/_checks_when.py` | n/a | pass the parser's code through | +3 |
| `reasons/config/_part1.py`, `reasons/plan/_part2.py`, `reasons/runtime/_part3.py` | n/a | `WHEN_MASKED_REFERENCE_UNSUPPORTED` | +3 each |
| `tests/fixtures/f29/reason-manifest-v1.34-when-reads-source.json`, `reason-registry-release.json` | new, n/a | the new codes (`since` = the release that carries S1) | per regenerate script |
| `tests/sentry/defects/test_when_reserved_names.py` | n/a | AT-S5a regex-terminal pin gains `QUOTED_NAME`; new AT-S5d pins the prefix set `{"source", "masked"}` | +20 |
| `docs/frozen-surfaces.md:138`, `docs/compatibility-contract.md` | | the reference prefixes and quoting join the reserved-names row and contract 3.4 | +6 |

Size: about 130 source lines, about 250 test lines.

### Slice S2: `when:` reads the original value

| File | Lines now | Change | Expected after |
|---|---|---|---|
| `execution/_runner.py` | 496 | `when_read_columns`, `source_snapshot_columns`; docstrings state the `when:` contract | about 535 |
| `execution/_fk_keys.py` | about 577 | delete `_when_read_columns` (`:315-333`); `when_read` from `_runner.when_read_columns` | about 560 |
| `execution/_adapter.py` | 536 | `StrategyContext.source_snapshot_columns` | about 540 |
| `execution/_pandas_adapter.py` | 665 (ceiling 700) | `:199` calls `source_snapshot_columns`; context field set at `:224` | 666 |
| `execution/_sequential.py` | 679 (ceiling 680) | `:329` calls `source_snapshot_columns` (net 0); context field set where the context is built (+1) | 680 |
| `execution/_when_gate.py` | about 555 | `when_source_frame`; `run_with_when_gate` passes it | about 590 |
| `execution/_column_access.py` | n/a | `scalar_creating_reads` docstring | 0 |
| `execution/native/_when_admission.py` | about 309 | delete `_earlier_writes`, `READS_MASKED_CODE` and their uses | about 260 |
| `execution/native/_route_decline_codes.py` | 124 | delete one member | 123 |
| `reasons/route/_part1.py`, `reasons/route/_retired.py`, runtime catalog | 303, 19, n/a | tombstone the two codes; add `WHEN_SOURCE_SNAPSHOT_MISSING` | about +15 |
| F29 fixtures and baselines | | see below | |
| docs (section 10) and `changelog.d/when-reads-source.md` | | contract text; `Breaking:` lines | about 60 |

If `_sequential.py` would cross 680, the builder folds the five-line comment at `:324-328` to four lines; the ceiling is not raised.

F29 fixtures and baselines that S2 edits (regenerated by the scripts the sentries name, never by hand):

- `tests/fixtures/f29/producer-inventory.json:370` and `:386`: the two producers leave the live inventory.
- `tests/fixtures/f29/reason-baseline.json:524` and `:801`: the two codes leave the producer-sourced baseline.
- `tests/fixtures/f29/reason-registry-release.json:16549` and `:22380`: `deprecated_in` set on both; the new runtime code added.
- `tests/fixtures/f29/reason-manifest-v1.34-when-reads-source.json`: the S2 additions and deprecations (or the next free version).
- `tests/sentry/baselines/f29-producer-inventory.json:1049` and `:1064`, `tests/sentry/baselines/f29-reason-baseline.json:1562` and `:2393`: the two entries removed (the baselines may only shrink).
- `tests/sentry/baselines/f29-consumer-inventory.json`: rechecked; edited only if a consumer entry named the two codes.

Tests changed because they assert the removed decline (each rewritten to assert the native route now admits the table and its output equals the oracle):

- `tests/native/test_chunked_entry_evidence.py:249`
- `tests/native/test_c8_i_when_declines.py:230`, `:238`, `:295`, `:306`
- `tests/native/test_obs2_decline_records.py:130`, `:283-299`
- `tests/native/test_c8_i_when_auto_route.py:178`
- `tests/native/test_chunked_date_shift_admission.py:497`

Size: about 120 source lines added, about 90 removed, about 400 test lines. Each slice is under the 600-line limit.

## 6. Placement

| New item | File | CODEMAP row | Sits beside |
|---|---|---|---|
| `WhenRead`, `render_when`, `alias_reads` | `expressions/_when_parser.py` (existing) | the `when:` grammar | `when_column_refs`, `when_literals_by_ref` |
| `when_read_columns`, `source_snapshot_columns` | `execution/_runner.py` (existing) | work list and source-read sets live in `_runner.py` | `joint_mask_key_by_columns`, `source_anchor_columns` |
| `StrategyContext.source_snapshot_columns` | `execution/_adapter.py` (existing) | the strategy context | `group_anchor_snapshots` |
| `when_source_frame` | `execution/_when_gate.py` (existing) | the `when:` gate | `run_with_when_gate`, `when_eval_frame` |
| `WHEN_MASKED_REFERENCE_UNSUPPORTED` | `reasons/config/_part1.py`, `reasons/plan/_part2.py`, `reasons/runtime/_part3.py` | "Reason codes": one catalog package per namespace | `WHEN_OUTSIDE_CLOSED_GRAMMAR` in each |
| `WHEN_SOURCE_SNAPSHOT_MISSING` | `reasons/runtime/_part3.py` | "Reason codes" | `WHEN_*` runtime codes |
| `test_when_reference_prefixes.py` | `tests/unit/` | engine unit tests | `test_c8_i_when_grammar.py` |
| `test_when_reads_source.py` | `tests/unit/execution/` | engine execution tests | `test_o1_when_routes.py`, `test_when_predicate.py` |
| `test_when_reads_source_property.py` | `tests/property/` | Hypothesis property tests | existing property suites |
| `test_when_single_reader.py` | `tests/sentry/defects/` | "Sentry test": recurring-defect class rules | `test_group_by_single_reader.py` |

No new module in `src/`. `execution/` stays at 103 direct modules; `expressions/` gains none. No module crosses 600 lines except the dense entries already listed, which stay at or under their ceilings.

## 7. Design notes

- **Principles.** One place per fact. The columns a `when:` reads: `when_column_refs`, typed. The per-table `when:` read set: `when_read_columns`, read by `LosslessInts` and the snapshot helper. The snapshot set: `source_snapshot_columns`, read by both snapshot sites and by the gate through the context. The deletion of `_fk_keys._when_read_columns` removes an existing duplicate.
- **Pattern.** SQL `UPDATE` semantics: every right-side expression reads the pre-statement row. SQL trigger `OLD`/`NEW` for the phase prefix. In-codebase precedent: the `joint_mask` `key_by` pre-mask snapshot.
- **Choke points.** (a) `_eval_predicate` has three callers: `run_with_when_gate` (oracle), `native/_when_mask.when_mask` (chunked native, raw chunk) and `compute_when_masks` (unified slice, source frame). `tests/sentry/defects/test_when_single_reader.py` checks by AST that each call's frame argument comes from an allowed source: `when_source_frame(...)` in `_when_gate.py`, a `raw_chunk` selection in `_when_mask.py`, `candidate.source_frame` in the unified slice. A new caller fails the sentry until it is added with its reason. (b) `when_column_refs` is the only producer of `WhenRead`; the sentry also checks that no module outside `expressions/` reads `.ref` of a `Compare` or `InList`.
- **1.x: masked reads (design note, not built).** A `masked.<col>` read becomes an ordering edge in the existing `column_dependency_edges` (`execution/_runner.py:354`): the `when:` node runs after the node that writes `<col>`, exactly as a created column runs after its drivers through `_masked_driver_columns`. The gate then reads `df[col]` for a `masked` read and the snapshot for a `source` read; `when_source_frame` already dispatches on the read, so only that branch and the edge are new. Native admission gets the same edge through the same function. There is no second scheduler and no second read path. The V1 refusal is one check in `parse_when`; 1.x deletes it and tombstones `when_masked_reference_unsupported`.
- **House style.** `when_source_frame` takes the context, not loose dicts; no flag argument chooses live or source; the phase is data on the read, not a parameter.

## 8. Class table

| # | Class | Where it applies | Structure that closes it | Proof | Mutation that must turn it red |
|---|---|---|---|---|---|
| 1 | Value-bearing output | the two new errors | messages name table, column and position only | W8, T-S5 | add the expression text to the snapshot-missing message (W8 red) |
| 2 | Cleanup missing on an exit path | none | N/A: the gate holds no resources | n/a | n/a |
| 3 | State and concurrency | snapshot dict shared across nodes | built once before the node loop; series are copies; never written | W2 | write the masked value into the snapshot (W2 red) |
| 4 | Route parity and silent fallback | oracle against native lanes; typed reads at every consumer | all routes read the original; the decline that hid the difference is gone; one read type | W3, T-S1 | read the live frame in the oracle (W1, W3 red); compare `WhenRead` objects with column names in `_unified_slice_when.py:68` (W3 unified case red) |
| 5 | Referential integrity | `when:` reading an FK key | key in the `exact` set, snapshotted with the lossless conversion | existing `test_fk_key_read_by_when_stays_exact` | n/a |
| 6 | Untrusted producer | backtick-quoted names | the quoted form excludes backtick, backslash and control characters; reserved-name checks apply | T-S3, AT-S5a | allow a backtick inside a quoted name (T-S3 red) |
| 7 | Check then use | snapshot set built before the loop, read in the gate | the set and the snapshots come from one helper over the same compiled plan; the gate fails closed on a missing set | W6 | build the snapshot after the first node (W2 red) |
| 8 | Weak tests | ordering tests on one config | Hypothesis over names and orders, selected row sets compared, plus a direct "earlier node masks the read column" case | W1, W2 | n/a |
| 9 | Refactor drift | `_fk_keys._when_read_columns` removed; snapshot set moved to one helper | `LosslessInts.when_read` and the snapshot helper both read `_runner.when_read_columns` | W2, existing `tests/sentry/defects/test_lossless_int_columns.py` | drop `when_read_columns` from `source_snapshot_columns` (W2 red: the gate reads the live masked column); feed `LosslessInts.when_read` an empty map (`test_fk_key_read_by_when_stays_exact` red) |
| 10 | Frozen contract drift | grammar surface, golden outputs, reason codes | prefix set and terminals pinned; goldens regenerated with a reason each; codes tombstoned, not deleted | AT-S5a, AT-S5d, W9, registry sentry | add a third prefix (AT-S5d red); delete a tombstone (registry sentry red) |
| 11 | Determinism | column-name and chunk-size independence | evaluation input no longer depends on order | W1, W4 | n/a |

## 9. Acceptance tests

Each fails before the change unless marked control.

S1 (grammar seam):

- **T-S1 bare equals `source.`** For a sample of predicates over every grammar shape, `parse_when("status == 'a'")` and `parse_when("source.status == 'a'")` give equal ASTs, and `when_column_refs` returns `(WhenRead("status", "source"),)` for both. Both evaluate to the same mask on the oracle and the native mask. Mutation: make `bare_ref` build `phase="masked"` (T-S1 red, and every existing `when:` suite red through the refusal).
- **T-S2 `masked.` refused.** `masked.status == 'a'` raises `ValidationError` with code `when_masked_reference_unsupported` from `parse_when`, a config load error at `tables.<i>.columns.<j>.when` with that type, and a `PlanCompileError` with the plan code from a raw dict. Fail-before: `when_outside_closed_grammar`.
- **T-S3 quoted dotted name.** A table with a column `a.b`: `` `a.b` == 'x' `` and `` source.`a.b` == 'x' `` select the rows where the original `a.b` is `'x'`, on the oracle, the chunked native leg and the unified slice. `a.b == 'x'` unquoted is refused with `when_outside_closed_grammar`. A quoted name holding a backtick or a control character is refused.
- **T-S4 `source` as a column name (control).** `source == 'web'` still parses as the column `source`.
- **T-S5 value-free.** The messages of T-S2 and T-S3 refusals hold no literal from the predicate.
- **T-S6 rendering (control).** For every predicate in `tests/unit/test_c8_i_when_grammar.py` and `test_when_predicate.py`, the mask from the aliased rendering equals the mask from today's raw-text evaluation.
- AT-S5a and AT-S5d in `tests/sentry/defects/test_when_reserved_names.py` (section 5).

S2 (source reads):

- **W1 order pairs (Hypothesis).** Random single-table configs: a gated column and the columns its predicate names, each named so that it sorts either before or after the gated column (`aa_`/`zz_` prefixes). Read columns use `hash` with an explicit shared `namespace: ns` (`_strategies/_hash.py:66-98` derives from `plan.namespace`, never from the column name) or `redact`. The gated column uses `redact` or `hash` in `ns`. For each pair of runs that differ only in names: the set of selected row positions is equal (a row is selected when the gated column differs from its source value), and the output is equal after renaming back. Fail-before: the `zz_` form selects a different row set.
- **W2 earlier node masks the read column.** `status: hash` in `ns` and `zz_email: redact` with `when: "status == 'active'"`, 2,000 rows, 600 active: exactly the 600 active rows have a redacted `zz_email`, the other 1,400 keep their source value, and `status` is hashed on all rows. Fail-before: zero rows selected and 600 active emails written unmasked.
- **W3 native equals oracle.** The W2 table with `zz_email` a `string` column and strategies `redact`, `hash` in `ns` and `truncate` in turn (all in `ADMITTED_WHEN_STRATEGIES`), on the chunked native leg (120,000 rows), the unified slice (2,000 rows) and the oracle (`--no-native`): output equal on every route. The native lanes admit the table (evidence: no `when_*` decline). Fail-before: native declines with `when_predicate_reads_masked_column`.
- **W4 chunk-size invariance (control).** The W2 shape at 120,000 rows on the chunked oracle and the chunked native leg, chunk size 7,000 and 40,000: equal output. A `when:` is row-local, so this passes before the change too; it pins that per-chunk snapshots keep it so.
- **W5 sequential route.** A two-table FK job where the child has `zz_note: redact` with `when: "kind == 'x'"` and `kind: hash` in `ns`: rows selected by the original `kind`. Fail-before: no rows selected.
- **W6 snapshot missing.** The gate run with `ctx.source_snapshot_columns = None` for a node with a `when:`, and again with the set naming a column that has no snapshot: both raise `when_source_snapshot_missing`.
- **W7 created columns unchanged (control).** `tests/unit/execution/test_cross_column_ordering.py:88`, `:122`, `:144` and `tests/unit/execution/test_cross_column_joint_mask_remediation.py:120` pass unchanged: a created column still reads the masked driver.
- **W8 value-free.** W6's message and every evidence entry hold no seeded sentinel value and no expression text.
- **W9 goldens.** The golden and snapshot suites (`tests/snapshots/`, `tests/parity/`, `tests/vectors/`, `tests/acceptance/`) run at the merge head. The builder finds the affected goldens with a temporary probe on the base head, not committed:
  - in `run_with_when_gate`, compare the mask from the live frame with the mask from the source values and record the config when they differ;
  - in `when_native_rejection`, record every config that declines with `READS_MASKED_CODE`.
  Every changed golden is regenerated in the PR and listed in the PR body with one of three reasons: (R1) "a `when:` read a column masked earlier in work order; it now reads the original value"; (R2) "the table now runs natively: the `when_predicate_reads_masked_column` decline is gone from the evidence and `executed_backend` is native"; (R3) "the native-admitted chunked `when:` column is pinned to `string`, as contract 3.4 states". A golden that changes for any other reason blocks the merge.
- **W10 control: existing `when:` suites.** `test_o1_when_routes.py`, `test_o1_when_eval_frame.py`, `test_when_predicate.py`, `test_when_gate_mutation_kills.py`, `test_multi_table_when.py` pass unchanged, except where a case asserted the order-dependent result; each such case is rewritten and listed in the PR body.

Mutations (core units, final head of each slice): S1: `bare_ref` builds `masked` (T-S1 red); drop the masked refusal (T-S2 red); skip `_name` on quoted names (AT-S5b red). S2: pass the live `df` to `_eval_predicate` (W1, W2, sentry red); build the snapshot after the node loop starts (W2 red); drop `when_read_columns` from `source_snapshot_columns` (W2 red); restore the `reads_masked` decline (W3 red); skip the `None` check in `when_source_frame` (W6 red).

Test scope: T0 per edit; T1 impact selection plus the named tests and the sentries; T3 full suite at each merge head (S1 frozen contract, S2 goldens), diffed against the saved main baseline.

## 10. Frozen contracts, goldens and docs

**Grammar (S1, additive).** Contract 3.4 and the `frozen-surfaces.md:138` row ("`when:` reserved column names") gain the reference prefixes `source.` and `masked.`, the backtick quoting rule and the V1 refusal of `masked.`. Every predicate that parsed before parses to the same AST with phase `source` and evaluates to the same mask (T-S1, T-S6). The sentry `test_when_reserved_names.py` pins the new terminal and the prefix set. No `Breaking:` line for S1: no accepted predicate changes meaning.

**Output change (S2).** `Breaking: a when: condition now reads the original value of every column it names, as documented. Before, on the pandas routes, it read a value that a column earlier in work order had already masked, so the rows it selected depended on column names.` This is a correctness fix to the documented contract; no config key, public name or exit code changes.

**Evidence change (S2).** `Breaking: the native lanes no longer decline a when: that names a column masked earlier; reason codes when_reads_masked_column and when_predicate_reads_masked_column are deprecated.`

**Goldens that change.** Only goldens found by the W9 probe, each with reason R1, R2 or R3. No other golden may change.

**Docs to update.** The contract text in every place is the owner's: "`when:` picks rows by the row's ORIGINAL values, from any column. Mask `email` only on rows where the original `country` = 'US'."

- `docs/compatibility-contract.md:1045-1056` (the C8-i `when:` entry): rewrite. Remove "A predicate that reads a column an earlier work node (column-name order) masks ... keep the oracle leg" and the `when_predicate_reads_masked_column` code from the decline list; state that every route reads original values; state the prefixes and quoting (S1) and the deprecated codes (S2); correct "The unified full-frame route and out-of-core still decline `when:`" to "Out-of-core still refuses `when:`" (the unified slice evaluates `when:` through `compute_when_masks`).
- `docs/frozen-surfaces.md:138`: the row text (S1).
- `docs/strategies.md:1352-1361` "Conditional masking (when:)": the contract sentence and its example; the prefixes, with `masked.` "planned for 1.x"; backtick quoting with an `a.b` example; "Column order and names do not change which rows it selects."
- `docs/determinism.md`: one line, output does not depend on column order for `when:`.
- `docs/qa/10-expressions-and-when.md`: QA rows for an order pair, a `when:` reading a masked column, `source.`/`masked.` and a quoted dotted name.
- `docs/execution-backends.md`: remove `when_reads_masked_column` from the native decline list.
- CLI: `decoy explain` has no `when:` text today (topics in `CLI:src/decoy/cli/explain.py`, `yaml` at `:140`); add the contract sentence to the `yaml` topic. Also the `.decoy` language reference for `when` (AST field `CLI:src/decoy/lang/_ast.py:73`; the builder checks that the `.decoy` lexer passes backticks and dots inside the string through unchanged) and `CLI:docs/roadmap/groups/mask.md` if it describes `when:` reads. These go in the CLI docs PR that bumps the engine pin.
- Public docs site (`decoy-web-docs`, vendored engine docs): regenerated from the engine docs at its next sync. The site is paused until CLI V1, so this is a note in its resume list, not work now.

## 11. Pre-mortem

- **A user relied on the order-dependent reading** (a gate on a column that another column masks, written to match masked values). That config matched nothing before, or matched by accident, so it was already leaking. The changelog line and the docs example name the change.
- **A route builds no snapshot.** Today every pandas route goes through `PandasExecutionAdapter` or the sequential runner, and both build it from `source_snapshot_columns`. A route that skips it leaves `ctx.source_snapshot_columns` at `None` and the gate fails closed (W6). W5 covers sequential, W4 the chunked oracle.
- **A consumer compares typed reads with names.** `set(when_column_refs(ast)) <= set(names)` would be always false and decline silently. Every consumer is listed in guarantee 9 and changed in S1; mypy types the sets; W3 runs the unified slice and fails on such a decline.
- **The aliased rendering differs from the raw text.** `render_when` reuses the leaf rendering the exact-integer path already uses. T-S6 compares masks over every existing grammar test predicate.
- **Index alignment inside a gated sub-frame.** `snapshot.loc[df.index]` aligns by label, and the snapshots share the adapter frames' index. W2 checks positions; a handler that calls the gate on a reindexed frame would fail `.loc` loudly.
- **Memory.** Section 3, guarantee 5: only columns some node writes are copied.
- **PER-COLUMN-ROUTING depends on this.** That plan relies on guarantee 1 for its Python half and on the typed reads for its read set. Merge S1 and S2 first.

## 12. Open questions for the owner

None. The contract, the prefixes, the V1 refusal of `masked.` and the out-of-scope line for created columns are the owner's decisions of 2026-11-22. The 1.x design for masked reads is a note (section 7), not a decision taken here.

## Amendment A1 (2026-11-23, from the S1 build, engine #769)

The S1 builder found two gaps. Both are fixed here, and S1 carries them.

**A1.1 One reader for the chunk read set.** `execution/_column_access.predicate_names` (`:100`) is a second reader of `when:` columns. It runs pandas' tokenizer and NFKC-normalizes every name, including backtick-quoted ones. After S1 the evaluator reads exactly the columns `when_column_refs` returns (item 10, the alias map). For a quoted fullwidth name the two disagree: the evaluator reads the exact column and the read set collects the normalized name. A read set that misses a column the predicate reads hands it a placeholder, so rows can be selected wrongly and a column left unmasked (the failure the `predicate_names` docstring itself names). Fix at the source: `predicate_names` stops tokenizing. It calls `when_column_refs` and returns `{read.column for read in refs}`, or None when the predicate does not parse (callers keep treating every passthrough column as read). There is then one producer of `when:` reads. Name normalization lives only in the grammar's name rule: an unquoted name is NFKC-normalized there, which keeps today's behavior (pandas resolves a fullwidth bare `x` and a ligature `file` to `x` and `file`); a quoted name is exact and is not normalized. If keeping bare-name NFKC is not possible in the grammar, stop and report; do not change bare-name behavior silently.

**A1.2 Acceptance and mutation.**
- **AT-S1e read set equals evaluator reads.** For a predicate corpus (bare, fullwidth bare, ligature bare, quoted dotted, quoted fullwidth, `source.` with each form, a string literal holding a name, an unparsable predicate), the chunk read set equals the set of columns the evaluator reads (spy on the alias map), and the unparsable case returns None. Runs in `tests/sentry/defects/` beside the reserved-name sentry.
- **Mutation A1-M1:** normalize quoted names in the grammar's name rule (AT-S1e red on the quoted fullwidth case). **A1-M2:** restore the tokenizer inside `predicate_names` (AT-S1e red on the quoted fullwidth case). **A1-M3:** drop the None return for an unparsable predicate (AT-S1e red).

**A1.3 Tests that change.** Backtick quoting is valid from S1 (item 9), so these cases now assert the opposite of what they assert on main. Change them in a separate commit whose message cites A1.3; every changed case asserts the masked output equals the oracle and the read set holds the exact quoted column:
- `tests/native/test_chunked_entry_rev9_read.py::test_backtick_predicate_is_rejected_at_compile` (4 cases): rename to `test_backtick_predicate_is_accepted` and assert acceptance plus oracle equality.
- `tests/native/test_chunked_entry_rev9_nfkc.py::test_nfkc_spelled_predicate_is_rejected_at_compile` (the 4 backtick cases): a quoted NFKC-spelled name reads the exact column; if no such column exists, it is refused with the grammar's unknown-column code at compile, not with the old backtick refusal. The bare NFKC cases keep their current outcome unchanged.
- `tests/unit/execution/test_c8_iii_c_boundaries.py`: the two `WhenSpec(...)` constructions pass `WhenRead("x")` for the typed field; no assertion changes.

**A1.4 Size.** `_column_access.py` shrinks (the tokenizer loop goes). No ceiling rises.
