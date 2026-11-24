Status: plan (revision 2.3, 2026-11-24, revised after PR #783 review at `0fdf6d5a9`).

# WHEN-READS-SOURCE: a `when:` condition reads the original value on every route

**Invariant.** Dispatch resolves each node once, every write consumer uses that operation’s outputs, and each reader sees its required column version assembled from the rows selected by those writers in commit order.

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
- `execution/_runner.py:301` `_writer_node_map` over `build_work_list` (`:101`), with `_writer_output_columns` (`:281-298`): reuse the writer index with resolved operations as its only inputs.
- `execution/_fk_keys.py:336-360` `LosslessInts` and its `exact` / `when_read` split: unchanged; only its `when_read` source moves.
- `expressions/_when_parser.py:294` `when_column_refs`: the one reader of the names a predicate reads, now typed.
- `execution/_when_gate.py:328` `_eval_predicate`: the one evaluator.
- `reasons/route/_retired.py:14-19`: the tombstone pattern for shipped codes. `replaced_by` is optional: `reasons/_types.py:98` defaults it to `None`, and the registry check (`reasons/_registry.py:202-205`) only tests a `replaced_by` that is set.

## 3. Guarantee and non-goals

After this plan:

1. On every route that evaluates `when:` (full-frame oracle, sequential FK route, chunked oracle, chunked native leg, unified slice), a predicate is evaluated on the original values of the columns it names. The original value is the value the masking stage received, after declared casts and `transforms`/`derive`, before any column is masked. Out-of-core refuses `when:` today (`execution/out_of_core/_compat.py:255-258`, `out_of_core_when_predicate_unsupported`) and still does.
2. **One reader of `when:` columns.** `when_read_columns(plan) -> dict[str, frozenset[str]]` (new, `execution/_runner.py`, beside `joint_mask_key_by_columns`) returns, per table, the columns any `ColumnSeed.when` reads, from `when_column_refs` (guarantee 9). `_fk_keys.lossless_int_columns` keeps the `LosslessInts` `exact` / `when_read` split exactly as it is (`execution/_fk_keys.py:336-360`, `:399`) and fills `when_read` from `_runner.when_read_columns`. The private duplicate `_fk_keys._when_read_columns` (`:315-333`) is deleted. `source_anchor_columns` is unchanged, so a `when:` column never joins the `exact` set.
3. **One snapshot helper.** `source_snapshot_columns` takes the compiled operations and anchor/read sets. For each table it returns source anchors plus predicate inputs that intersect a resolved output or table wildcard. Both snapshot sites use it before creator allocation and before the first writer. In particular, a child FK configured with a bundle writes its child key.
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
- `tests/fixtures/f29/reason-baseline.json:524` and `:801`: retain both identities in the frozen historical baseline.
- `tests/fixtures/f29/reason-registry-release.json:16549` and `:22380`: `deprecated_in` set on both; the new runtime code added.
- `tests/fixtures/f29/reason-manifest-v1.34-when-reads-source.json`: the S2 additions and deprecations (or the next free version).
- `tests/sentry/baselines/f29-producer-inventory.json:1049` and `:1064`: remove the two obsolete live producers. Preserve the historical sentry reason baseline.
- `tests/sentry/baselines/f29-consumer-inventory.json`: rechecked; edited only if a consumer entry named the two codes.

Tests changed because they assert the removed decline (each rewritten to assert the native route now admits the table and its output equals the oracle):

- `tests/native/test_chunked_entry_evidence.py:249`
- `tests/native/test_c8_i_when_declines.py:230`, `:238`, `:295`, `:306`
- `tests/native/test_obs2_decline_records.py:130`, `:283-299`
- `tests/native/test_c8_i_when_auto_route.py:178`
- `tests/native/test_chunked_date_shift_admission.py:497`

Build the PR #783 repair as one S2 slice: resolve operations and land the seeded authority guard first, then wire the shared ordering decision, version commits and route tests in the same change. Move the existing resolver inputs, sort, allocation and commit code before wiring callers; use the per-file ceilings in Placement and removal.

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

New execution modules belong under `execution/work_order/` (placement below). The direct execution module count stays fixed; `expressions/` gains none. No module crosses 600 lines except the dense entries already listed, which stay at or under their ceilings.

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

In `changelog.d/when-reads-source.md`, name the new runtime reason exactly as `runtime/when_source_snapshot_missing` for release-manifest validation.

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

## Amendment A1 (revision 2.2, 2026-11-23, from the S1 build, engine #769)

The S1 build exposed a read-set mismatch. The Codex NO-GO review then found that revision 2.1 fixed it at the wrong boundary. This revision fixes the mismatch without changing the two broad pandas-expression consumers.

**A1.1 Separate choke points for separate expression languages.** `execution/_column_access.py` serves two expression contracts:

- `_when` (`:196`) reads the closed `when:` language. Change only this declaration to call `parse_when` and `when_column_refs`, returning `ColumnAccess(reads=frozenset(read.column for read in refs))`. A parse refusal returns `_READS_UNKNOWN`, preserving the fail-closed chunk behavior. This makes `when_column_refs` the one producer of `when:` reads for the evaluator, native admission, chunk carry, unified slice, snapshot helper and `LosslessInts` consumers named in guarantee 9.
- `_transforms` (`:222`, expression read at `:230`) and `_derive_created` (`:448`, expression read at `:467`) read the broader pandas-derived-expression language. Both continue to call `predicate_names` unchanged. `predicate_names` remains the separately named generic scanner at `:100`, including arithmetic such as `g + o * 2`, pandas expression shapes outside the closed `when:` grammar, NFKC normalization as pandas applies it, and the conservative `None` result for f-strings, bytes literals, unknown token kinds and unreadable expressions. A `None` result continues to mean every passthrough column is read or the derived target is not creatable.

These are intentionally two choke points because they model different languages. Do not route `_transforms` or `_derive_created` through `parse_when`, and do not replace or narrow `predicate_names`. The three existing sites are `_when`, `_transforms` and `_derive_created`; after A1, only `_when` uses the closed grammar.

**A1.2 Bare and quoted name contract.** Keep the `IDENT` terminal ASCII-only. An unquoted fullwidth name such as `ｘ` and an unquoted ligature spelling such as `ﬁle`, with or without the `source.` prefix, remain refused with `when_outside_closed_grammar`, exactly as on `origin/main`. Do not NFKC-normalize an unquoted token before `_name` validation and do not widen `IDENT` to other Unicode identifiers. Quoted text is exact: `` `ｘ` `` reads the literal column `ｘ`, `` `ﬁle` `` reads the literal column `ﬁle`, and neither resolves to `x` or `file`. The reserved-name check still applies to the exact quoted column text. `predicate_names` keeps its existing pandas-oriented normalization because it belongs to the separate generic expression language.

**A1.3 Acceptance and mutation.**

- **AT-S1e `when:` read set equals evaluator reads.** In `tests/sentry/defects/test_when_single_reader.py`, compare `_when`'s declared reads with the evaluator alias-map columns for valid closed-grammar predicates: one bare ASCII name, a two-column Boolean predicate (`left > 0 and right == 'go'`), quoted dotted and quoted fullwidth names, `source.` with bare and quoted names, and a string literal that holds a column name. Assert separately that bare fullwidth, bare ligature and an unparsable predicate are refused by `parse_when` and make `_when` return `_READS_UNKNOWN`. The end-to-end two-column case leaves both predicate columns unconfigured, runs through chunk carry, asserts both are carried, and asserts chunked output equals the oracle. This is the direct proof that one missed legitimate read cannot receive a placeholder and change the mask.
- **AT-S1f generic scanner remains broad and conservative.** Existing `tests/native/test_chunked_entry_rev9_read.py::test_predicate_names_declines_every_non_plain_string_shape` and `::test_predicate_names_fails_closed_on_a_token_kind_it_does_not_know` keep the generic scanner's conservative `None` contract. Add `tests/unit/execution/test_created_derive_chain.py::test_transform_expression_readers_keep_the_generic_scanner`: call `SURFACE_DECLARATIONS["surface:transforms"]` to prove `_transforms` reads both `g` and `o` from `g + o * 2`, and call `created_columns` to prove `_derive_created` makes the same target creatable. In the same test, f-string, bytes, unknown-token and unreadable-expression cases make the surface declaration `reads_unknown` and do not make the target creatable. This directly pins both `predicate_names` callers. These are controls and do not change their product expectations.
- **Mutation A1-M1:** normalize a quoted name before `_name` validation. AT-S1e is red on the quoted fullwidth case.
- **Mutation A1-M2:** make `_when` call `predicate_names` again. AT-S1e is red on the quoted fullwidth case.
- **Mutation A1-M3:** make `_when` return an empty read set after a parse refusal. AT-S1e is red on the invalid bare and unparsable cases.
- **Mutation A1-M4:** drop `right` from `when_column_refs` for `left > 0 and right == 'go'`. AT-S1e is red because the declared read set and alias map differ, and the end-to-end chunk carry assertion is red because `right` receives a placeholder and the masking output differs from the oracle.
- **Mutation A1-M5:** route `_transforms` through `parse_when`. AT-S1f is red because `g + o * 2` no longer declares both reads.
- **Mutation A1-M6:** route `_derive_created` through `parse_when`. AT-S1f is red because the arithmetic target is no longer creatable. The unreadable-expression cells also pin the conservative fallback at both sites.

**A1.4 Exact test IDs that change.** Backtick quoting is valid from S1, while bare fullwidth and ligature names remain invalid. Change only the following existing IDs, plus the new AT-S1e and AT-S1f coverage above. Every accepted quoted case asserts the masked output equals the oracle and the chunk read set holds the exact quoted column.

- Rename these exact `tests/native/test_chunked_entry_rev9_read.py` IDs: `test_backtick_predicate_is_rejected_at_compile[backtick]` to `test_backtick_predicate_is_accepted[backtick]`; `test_backtick_predicate_is_rejected_at_compile[backtick_configured]` to `test_backtick_predicate_is_accepted[backtick_configured]`; `test_backtick_predicate_is_rejected_at_compile[needs_backticks]` to `test_backtick_predicate_is_accepted[needs_backticks]`; and `test_backtick_predicate_is_rejected_at_compile[needs_backticks_configured]` to `test_backtick_predicate_is_accepted[needs_backticks_configured]`.
- Replace `tests/native/test_chunked_entry_rev9_nfkc.py::test_nfkc_spelled_predicate_resolves_to_the_real_column_name` with these exact helper-level IDs: `test_generic_expression_scanner_nfkc_normalizes_name[fullwidth]`, `test_generic_expression_scanner_nfkc_normalizes_name[ligature]`, `test_generic_expression_scanner_nfkc_normalizes_name[fullwidth_backtick]`, `test_generic_expression_scanner_nfkc_normalizes_name[ligature_backtick]`, `test_generic_expression_scanner_nfkc_normalizes_name[ligature_notnull]`, `test_when_invalid_nfkc_bare_name_reads_every_passthrough[fullwidth]`, `test_when_invalid_nfkc_bare_name_reads_every_passthrough[ligature]`, `test_when_invalid_nfkc_bare_name_reads_every_passthrough[ligature_notnull]`, `test_when_quoted_nfkc_name_is_exact[fullwidth_backtick]` and `test_when_quoted_nfkc_name_is_exact[ligature_backtick]`. The first group is a control for retained `predicate_names`; the second pins fail-closed `_when` behavior for grammar refusals; the third uses literal `ｘ` and `ﬁle` source columns and pins exact quoted reads.
- Replace only these four quoted IDs in `tests/native/test_chunked_entry_rev9_nfkc.py`: `test_nfkc_spelled_predicate_is_rejected_at_compile[fullwidth_backtick-unconfigured]`, `test_nfkc_spelled_predicate_is_rejected_at_compile[fullwidth_backtick-configured]`, `test_nfkc_spelled_predicate_is_rejected_at_compile[ligature_backtick-unconfigured]` and `test_nfkc_spelled_predicate_is_rejected_at_compile[ligature_backtick-configured]`. Their replacement IDs are `test_nfkc_quoted_predicate_reads_exact_column[fullwidth_backtick-unconfigured]`, `test_nfkc_quoted_predicate_reads_exact_column[fullwidth_backtick-configured]`, `test_nfkc_quoted_predicate_reads_exact_column[ligature_backtick-unconfigured]` and `test_nfkc_quoted_predicate_reads_exact_column[ligature_backtick-configured]`. Keep these six existing IDs and their `when_outside_closed_grammar` outcome unchanged: `test_nfkc_spelled_predicate_is_rejected_at_compile[fullwidth-unconfigured]`, `test_nfkc_spelled_predicate_is_rejected_at_compile[fullwidth-configured]`, `test_nfkc_spelled_predicate_is_rejected_at_compile[ligature-unconfigured]`, `test_nfkc_spelled_predicate_is_rejected_at_compile[ligature-configured]`, `test_nfkc_spelled_predicate_is_rejected_at_compile[ligature_notnull-unconfigured]` and `test_nfkc_spelled_predicate_is_rejected_at_compile[ligature_notnull-configured]`.
- Split the four invalid closed-grammar rows out of `tests/native/test_chunked_entry_rev9_read.py::test_read_set_scans_predicates` as these exact IDs: `test_invalid_when_expression_reads_every_passthrough[unicode-cafe]`, `test_invalid_when_expression_reads_every_passthrough[unicode-delta]`, `test_invalid_when_expression_reads_every_passthrough[unicode-cjk]` and `test_invalid_when_expression_reads_every_passthrough[method-call]`. Each now expects every supplied passthrough column because `_when` fails closed. The valid ASCII, quoted, literal and blank rows keep their current expectations.
- In `tests/unit/execution/test_c8_iii_c_boundaries.py`, update `test_native_mask_raises_the_grammar_code[non_empty]`, `test_native_mask_raises_the_grammar_code[zero_rows]` and `test_no_raising_boundary_renders_the_predicate[native_mask]` only to pass `WhenRead("x")` in the two `WhenSpec(...)` construction sites. Their assertions do not change.

The tokenizer-specific `tests/native/test_chunked_entry_rev9_read.py::test_predicate_names_fails_closed_on_a_token_kind_it_does_not_know` remains valid and unchanged because `predicate_names` remains the generic scanner. The derived-expression and transform controls in AT-S1f remain broad; no broader expression test is rewritten to the closed `when:` grammar.

**A1.5 Placement and size.** The existing Placement row for `test_when_single_reader.py` covers AT-S1e. AT-S1f extends existing native and execution test modules and adds no file. `_column_access.py` changes only `_when`; the tokenizer loop remains. No ceiling rises.

## Write and ordering model

**Ordering compatibility.** Preserve the dispatch order and intermediate reads of every successful baseline sort, subject to the specified source-predicate and exact-integer corrections. Use fallback ranks only for a cyclic baseline sort.

This model governs the remaining S2 ordering work. The baseline is engine `42436c973`.
Execution paths below are relative to `src/decoy_engine/execution/`.

### One dispatch contract

Build one immutable `ResolvedOperation` per work node in
`execution/work_order/operations.py`, exported by `execution.work_order`. Resolve the
work list with its actual relationship graph before planning snapshots or carry. Each
record holds the node/key and table, dispatch kind and selected FK edges or handler,
declared outputs (including a table wildcard), creatable targets, gate, masked and source
inputs. Dispatch executes that selection. Only the resolver asks for matching child
edges and interprets write declarations. For handler operations it uses the existing
column-access registry, including the single joint-mask output declaration. Consumers
take the records or an index over those records. Config remains available for schema
policy and expression reads. Neither a consumer nor a handler output hook resolves
the operation again. A standalone entry point compiles its own invocation once and
passes that decision down. A chunk reuses the structural decision with fresh buffers.

A write means a column whose cells dispatch may replace, including writes limited to selected rows.

| Selected operation | Writes and reads |
| --- | --- |
| FK resolution, checked first | Resolve one child tuple per row against the existing parent maps. Apply the shared orphan policy on a miss. Write exactly the child tuple. The child input rule below covers cycles. Discard the bypassed handler's reads, outputs, gate and creator flag. A composite FK group requires an edge. See `_pandas_adapter.py:375` and `:533–566`. |
| Scalar | Writes its target. A nested handler writes back its outer column. A multi-column `joint_mask` writes exactly its configured outputs. Its mask key reads source. A scalar `date_shift` with `group_by` needs the original group key in its table. Supply the aligned snapshot at `_strategies/_date_shift.py:190`. See `_column_access.py:347` and `_strategies/_joint_mask.py:119`. |
| Creating scalar | Writes its target and can introduce it. Take masked drivers from the strategy declaration. This covers `derived`, `derived_aggregate`, `grouped_series`, `windowed_date` and `group_key`. See `_column_access.py:339` and `_column_access.py:409`. |
| Composite | Writes exactly the fixed provider outputs or the columns in the custom bundle. Check all generated keys against that set before assignment. A `coherent_with` member outside the bundle contributes zero writes. Keep group identity. A deterministic bundle reads the first sorted group column at its dispatch rank. See `_column_access.py:266`, `_runner.py:113–115` (grouping), `_runner.py:127–136` (construction) and `_strategies/_composite.py:130`. |
| Passthrough | Writes nothing. A gate may still read its predicate. See `_strategies/_passthrough.py:24`. |
| Unknown writer | May write any column of its own table. Use one table-scoped wildcard. An unsupported handler still raises its existing error. See `_column_access.py:385` for the declaration, `_runner.py:411` for wildcard lookup and `_pandas_adapter.py:410–415` for the error. |

### Final values and dependencies

Give every work node one dispatch rank. For a plan that orders today, use its position
in today's `order_work(build_work_list(...), graph)`. Keep the existing FK, driver and
creator-before-bundle constraints for this rank. The heap takes the smallest ready
`(table, columns)` after each placement. A global name sort would miss dependencies.
`run_single` calls `run`, which walks that order serially (`_pandas_adapter.py:157`,
`:242`, `:281`). Each ungated joint handler replaces all configured columns
(`_when_gate.py:528`, `transforms/joint_mask.py:324` under `src/decoy_engine/`).
Thus independent `city` runs before `zip` even when declared second.

Commit all writes to each column in increasing dispatch rank. The last matching writer
wins each row. Use the same ranks for every output of a node, including FK, bundle and
wildcard outputs. Keep the input version that a successful overlap consumed. This
preserves intermediate reads as well as the final winner. Seed position adds no override.
If the old constraints contain a cycle, today's sort raises and supplies no ranks.
For that case alone, rank by resolved operation class, then by node key. Commit
wildcards first, then known non-bundle handlers, then bundles, then FK resolutions.
Within each class the larger key writes last. Use these ranks for commits only.
The required input checks below still reject a real value cycle. Never run handlers to
choose ranks. Keep one ordering decision behind the public work-order API.

Evaluate each handler once when its input versions are ready. Collect its output values and
selected row positions in isolation. The gate reads its predicate from the source. Preserve preflight, validation, warnings and row errors.
Use a separate commit step for each output column. Start with the source column or its admitted
empty target. Each partial commit overlays its selected rows on the preceding version.
An unconditional replacement supplies a whole version without waiting for the preceding commit.
Record the actual gate positions once, using the same positions for stitching and capture.
A whole replacement selects every position, including equal cells and null-to-null writes.
Use the existing gate position selector once for a gated replacement, and an all-rows
marker for an unconditional replacement. Preserve the positional mapping to the table index.
A zero-match gate selects none. Capture typed values at those positions for each output.
Remove the before/after equality scan and delta-count shortcut in `FallbackCommits`.

Represent assembly as a dependency: writer evaluations supply selected positions and values
to the commit for the required version, and a reader depends on that commit. Publish the
assembled version to the reader before dispatch. This permits a bundle surname to unlock
summary while email still awaits the derived writer. A final-email reader waits for both
email writers and their ranked overlay. Table emission consumes the same final version.
Keep intermediate versions until their last rank-specific consumer.

A masked sibling read uses the final driver under its dependency edge. Preserve the
existing exception for a creator ordered before the bundle that overwrites it. On a
working overlap it reads the driver version available at its dispatch rank. A handler that transforms its
own target waits for the version just before its write. For example, a later unconditional
`truncate(last_name)` reads the bundle's generated surname (`_strategies/_truncate.py:115–121`).
A replacement that never reads its target can skip an unused prior version. Its earlier handler
still runs.

On a successful sort, dispatch FKs in today's order against the same visible writes.
The first child to request a parent map builds it from the source snapshots and the parent frame
visible at that point. Keep the existing cache key `(parent_table, parent_columns)`.
Later children reuse that first map even if another writer has since changed a parent column
(`_pandas_adapter.py:620`). Keep the existing FK ordering edges. Add no wait for final parent writers.
This also preserves self-FKs, mutual composite FKs and bundles keyed by a resolved child.

On a successful sort, the FK reads every earlier write to its child tuple.
Only when the old sort raises a cycle, assemble the child tuple from source and earlier
child writes in fallback rank order. Keep each write's selected rows. Skip a child write
if its node also supplies a parent key component for this lookup. Apply that choice
once across all declared parents. The skip affects only the child input. The writer
still commits its parent output. Build the map at the FK's turn in the fallback order.

In test 3 the bundle supplies the parent first_name. Skip its email write when assembling
the child key. The original email then resolves to the bundle's masked first_name.
In test 17 the earlier city writer supplies no parent key. Keep its email write and
skip the bundle's. The passthrough variant sorts today, so it reads the bundle email.
Test 16 also sorts today. Its child sees the joint writer's PA and preserves it on a miss.

Merge maps in graph order. The graph builder sorts by parent table and parent columns,
then by child table and child columns (`relationships/_graph.py:250` under `src/decoy_engine/`).
The adapter keeps the first match with `setdefault` (`_pandas_adapter.py:529`).
Look up the same assembled child tuple for every parent.

An unwritten input uses the source version. Source reads add no writer edges. Supply required
anchor snapshots before evaluation, including the original group key for `date_shift`.

For a gated derived `state` followed by a gated joint write to `city` and `state`, evaluate
the joint handler from its source key. Commit its selected cities over the source cities.
Evaluate the derived handler using that final city column. The existing city driver edge ranks joint before derived.
Commit joint states first. Overlay derived states on the rows its gate selected. Ordering the two state commits
adds no dependency between the handler evaluations.

Bind exact integer keys to the input version selected for deterministic Faker or ungated
hash. Today registration records `node.columns` and sampling looks up only table and column
(`_exact_int_sources.py:56–72`, `:160`). A joint mask can replace a secondary output
without changing its null positions. That lookup can return stale Arrow integers.
Attach the exact Arrow data to the source version at full-frame and sequential registration
(`_pandas_adapter.py:245`, `_sequential.py:426`). A whole replacement supplies its own
values. Start a partial commit from the preceding exact version. Replace only the
selected rows with the writer's typed values. Apply Faker's gate positions to that assembled
input. Preserve nulls and integer width without a float round trip.

Use one `compile_work_order` decision in `execution.work_order` for `classify_job`,
`run_sequential` and the pandas adapter. It holds resolved records, ordered nodes,
version dependencies, commit ranks and per-table creator targets. Only this function
tries the compatibility sort and retries its specific `cyclic_work_ordering` result
with the fallback value graph. Other errors propagate. Preserve `order_work` as the
ordered-WorkNode projection for compatibility and out-of-core preflight. The planner
uses that same decision for admission and carry. Both execution loops consume the
decision's evaluation/commit steps and call the same per-table creator preparation
after snapshots, before the first dispatch. Planning records the preparation without
allocating a frame. Sequential execution prepares each table as it loads and
materializes its final versions before writing the table or evicting its buffers.
The chunked oracle
calls the adapter for each chunk (`_chunked_oracle.py:448`). Keep saved outputs, row positions
and exact input versions local to that call. Release each after its last consumer and
release all remaining temporaries before returning the chunk.

Use the same version dependencies at compile time and execution. Include table wildcards in
writer lookup. The sorted ready queue at `_runner.py:550` may order independent steps.
Reject a cycle of required inputs at compile time with `cyclic_work_ordering`. Two live
derived outputs that each need the other's final value still form such a cycle.

Separate column existence from value order. After source snapshots and before dispatch,
allocate each admitted missing creator target as an index-aligned, typed nullable column.
Keep existing columns intact. The gate still runs preflight and evaluates the original predicate.
Zero matches leave that column null. Partial matches fill only selected rows.
The bundle can now fill an admitted target even if the creator matched nothing.
Keep the missing-output error for undeclared targets. See `_when_gate.py:541` and
`_strategies/_composite.py:135`.

### Red-first acceptance through the affected entry points

Use the real adapter and the fixture at `tests/unit/execution/when/test_reads_source.py:572`.
Run each case before the fix and record its failing assertion. For an already-green behavior,
first kill the specified mutation, then restore it. Run the same tests green on the final head.

1. **V1** `test_coherent_member_reads_generated_email`. Put summary in first_name's
   coherent group. Derive summary from email plus "!". Every summary must equal the output
   email plus "!" and differ from the source email plus "!".
2. **V1** Characterize the existing surname fixture in `test_write_order.py`.
   The queue runs derived last_name, then a_ref, then the bundle. Pin a_ref to
   `[O2?, O0?, O3?, O1?]`. Pin last_name to the fixed-seed bundle oracle.
   Remapping a_ref to the bundle surnames must fail this test.
3. **V1** `test_fk_child_bypasses_derived_creator`. Resolve email from first_name while
   its configured derived expression names an unrelated column. Keep the cycle fixture.
   Source email holds the original first_name keys in row order. The bundle writes
   first_name, last_name and email. Assert email equals masked first_name on every row.
   Assert last_name matches the fixed-seed bundle oracle. Looking up the generated
   email would preserve an orphan. The FK bypasses the derived expression.
4. **V1** `test_indirect_creator_reads_after_bundle`. Supply all columns. Derive email
   from summary and summary from last_name. Assert success, summary equal to generated
   last_name plus "!", and email equal to the fixed-seed bundle oracle.
   Run two additional variants independently:
   - Initialize email to the oracle email on every row. Make each derived email distinct
     from its oracle cell. Every final email must still equal the bundle oracle.
   - Initialize email to distinct source values and add `z_view = concat(email, "!")`.
     Expect every z_view to equal its oracle email plus "!", including rows on which
     evaluation ran the derived email writer last.

   Exercise the indirect cycle through `classify_job` on the pandas substrate as well as
   `run_single` and an actual `run_sequential` sink. Expect the bundle fixture to classify
   as `pandas_fallback` and the sequential sink to contain the same oracle email and
   summary columns. Keep a mutually dependent derived pair as a negative control:
   all three entry points must raise `cyclic_work_ordering`.
5. **V1** `test_zero_match_creator_supplies_missing_target`. Omit email. Match no rows.
   Run once without the bundle and assert email exists with all nulls. With the bundle,
   assert every email equals the generated oracle. Exercise both variants through
   the sequential sink as well as the adapter and assert the same column presence,
   row count and values. Keep both existing overlap cases at
   `tests/unit/execution/when/test_reads_source.py:636`.
6. **V2-LOG** `test_unknown_writer_is_table_scoped`. Register z_stub with unknown outputs.
   Have it replace an otherwise unwritten driver. Assert a_derived reads its replacement.
   Capture the real dependency map during the run. Include a second table's reader in the
   planning probe and assert it has no edge from z_stub. Make the two assertions fail by
   removing wildcard lookup and by pooling wildcards across tables, respectively.
7. **V1** Run test 2 with a_ref and z_ref. Hold the seed and namespace fixed.
   Pin a_ref to the list in test 2. The queue runs z_ref after the bundle.
   Expect z_ref to contain bundle surnames from rows 2, 0, 3 and 1, in that order.
   Compare every other output column across the two runs.

8. **V1** `test_overlapping_derived_and_joint_gates`. Declare derived `state = concat(city, "!")`
   first. Then declare a joint mask on `city` that writes both city and state. Use two source
   flags and four rows. Use a single-row reference with a distinct joint city and state.
   Assert success. On the derived-only row, expect source city plus "!" as state.
   On the joint-only row, expect joint state. On the overlap row, expect joint city plus "!".
   On the fourth row, expect source state. Expect joint city exactly where the joint gate matched.
   Reversing the two state commits must fail the overlap assertion.
9. **V1** `test_truncate_reads_generated_surname`. Run the bundle alone for a fixed-seed
   oracle. Then declare the same bundle first and unconditional head truncate on last_name
   second, with length three. Use source surnames whose first three characters differ from
   the oracle prefixes on every row. Assert each output surname equals the generated prefix.
   Dropping the bundle's surname before truncate reads it exposes the source prefix.
10. **V1** `test_equal_priority_writer_spelling_swap`. Declare ungated z_first before
    a_second. Give each a distinct one-row reference for its own column and a shared
    column. Expect the first reference on every shared cell. Swap the dispatch names
    throughout the fixture while keeping declaration order and reference values fixed.
    Now expect the second reference. In both runs the larger ready key writes last.
11. **V1** `test_date_shift_uses_original_group_key`. Use an ungated grouped date_shift.
    Get expected dates with the group key untouched. Mask that key to one value and run
    again with the same seed. Use source groups with distinct oracle shifts. Assert the
    masked key is constant and all dates match the oracle. Dropping the group snapshot
    fails the run. Using the masked key gives the wrong dates.
12. **V1** `test_zip_city_state_matches_current_output`. Run two ungated joint masks
    through `run_single`. Declare zip before city. Both read k and write state. Use source
    rows (a, x, m, s) and (b, y, n, t) in column order k, zip, city, state. The one-row
    references supply (ZIP, zip-state) and (CITY, city-state). Pin the complete output
    observed at `d74afd71c`: (a, ZIP, CITY, zip-state) and (b, ZIP, CITY, zip-state).
    Compare the new run with that fixed table, including schema and row order.
13. **DESIGN** `test_three_writers_share_one_order`. Declare the first_name bundle,
    a city joint mask, then a derived last_name. Supply all columns. Use independent
    source keys and a separate driver for derived. Give all three distinct surnames.
    City is ready first. The creator must precede the bundle. Assert the joint city
    is present and every last_name equals the fixed-seed bundle oracle. Repeat with
    zip as the joint dispatch key. Now the creator unlocks the bundle before zip runs.
    Expect the joint surname. A fixed bundle priority fails the second run.
14. **V1** `test_faker_uses_committed_nullable_integer`. Give deterministic Faker a
    nullable Arrow int64 target with adjacent source keys above 2**53. Before Faker,
    run two gated joint masks that write the target as a secondary output. Give each
    mask a distinct integer and a disjoint set of non-null rows. Build the Faker-only
    oracle on an exact Arrow array. It holds the first integer on the first mask's rows
    and the second integer on the second mask's rows. Leave a large source key and a
    null untouched. Compare every Faker output with the oracle at the same seed and
    namespace. Choose keys that give distinct outputs for each replacement, the stale
    source and the rounded source. Repeat with Faker gated to all non-null positions.
    Put the null between two selected rows.
15. **V1** `test_chunk_releases_saved_outputs`. Public chunk preflight rejects joint
    masks and composites. Supply the multi-output fixture after preflight, directly to
    `_chunked_oracle._oracle_masked`. Use two chunks with different keys and gate
    matches. Force the handler to save a column
    until its last commit. Observe the actual saved buffers with weak references.
    Keep both returned chunks alive. Check the first chunk's temporary buffers are
    collectible before supplying chunk two. Check the second chunk's after it returns.
    Compare both outputs with their separate full-frame oracles. Retaining the buffers
    on the shared adapter must fail the lifetime check.
16. **V1** `test_fk_preserves_state_written_by_joint_mask`. Start the child FK
    `state` at `original`. Have an earlier joint mask write `PA` to `state`.
    Use a parent key distinct from both values and set the orphan policy to `PRESERVE`.
    Assert that `run_single` returns `PA` in the child's `state` at `d74afd71c`.
    The city writer leaves the parent key alone. Dropping its write would return `original`.
17. **V1** `test_fk_child_distinguishes_parent_and_joint_writes`. Extend test 3.
    Give each row a distinct original first_name and copy it to source email.
    Run a city joint mask before the bundle. Its one-row reference writes the
    second row's original first_name to every email. Choose distinct masked first names.
    Assert every FK email equals the second row's masked first_name. A source read
    would return different names across rows. A bundle read would preserve orphan emails.
    Repeat with passthrough in place of derived on email. This plan orders today.
    Assert every email matches the bundle-only email oracle under orphan preservation.

18. **V1** `test_self_fk_reads_shared_tenant_before_commit`. In table t, resolve (tenant, manager)
    against (tenant, id). Use tenants [A, A, B, B], ids [1, 2, 1, 2] as strings,
    and managers [2, 1, 2, 1] as strings. Derive id as label plus "!".
    Use labels [a1, a2, b1, b2]. Pin the successful output at `42436c973`.
    Tenant and label keep their input values. Id is [a1!, a2!, b1!, b2!].
    Manager is [a2!, a1!, b2!, b1!]. The map sees tenant before the FK writes it.
19. **V1** `test_bundle_keys_on_resolved_fk_child`. Repeat test 2 with
    `coherent_with=("a_ref",)`. Bind the sorted bundle group to the same namespace.
    At `42436c973`, a_ref is [O2?, O0?, O3?, O1?]. Assert that exact list.
    Compare first_name, last_name and email with the fixed-seed bundle oracle keyed by that list.
    Assert the child values are absent from final last_name. The bundle runs after the FK.
    Reading source a_ref instead changes all three generated columns.
20. **V1** `test_multi_parent_fk_uses_one_child_tuple`. Extend the cycle in test 3.
    Use source first_name [F0, F1, F2, F3], email [F0, S, miss, F3] and second [F0, S, Q, R].
    Derive second from [O0, O1, O2, O3] plus "!". Declare first_name and second as parents of email.
    Only the bundle writes both a parent key and email. Use PRESERVE.
    Let G0 and G3 be the generated first names for F0 and F3 from the bundle oracle.
    Build the graph from each declaration order. In both runs, first_name sorts before second.
    Assert email is `[G0, O1!, miss, G3]` in both. F0 matches both maps and first_name wins.
    S matches only second. The old sort raises `cyclic_work_ordering` for this fixture.

21. **V1** `test_fk_composite_provider_snapshots_child_ref`. Give a single-column
    child FK `ref` the provider `composite_name_email`. Use source child keys
    [A, B] and parents masked to [P, Q]. Order a later `z_secret` redaction
    gated on `ref == 'A'` after FK resolution. With source secrets [one, two]
    and replacement REDACTED, expect ref [P, Q] and z_secret [REDACTED, two].
    Run through the full-frame and sequential snapshot sites. Resolving the
    provider’s outputs before checking the FK must expose the first cell and fail.

For case 14 require both Faker variants on the final head. Replacing the version lookup
with registration by `node.columns` must fail the secondary-output assertions. For case
15 capture only weak references to temporary saved buffers at the commit boundary.
Drop observer locals and collect garbage at each stated boundary. Assert each reference
returns `None` while returned outputs remain readable. A seeded strong reference on the
reused adapter must fail before chunk two starts.

### Placement and removal

**V1 known defect.** The a_ref values in tests 2 and 7 can be absent from the final
last_name column. Preserve this output in S2. The orchestrator files the separate
row `FK-FINAL-PARENT-READ` as a 1.x candidate.

Move existing code before adding logic. Current sizes and ceilings are
`_runner.py` 598/600, `_when_gate.py` 600/600, `_pandas_adapter.py` 669/700
and `_sequential.py` 677/680. Put the shared code in a named execution subpackage.
Keep operation resolution, ordering and version assembly together in `work_order`.
Keep FK map construction, merging and cache ownership in the current FK path.
Expose shared entry points through `execution/work_order/__init__.py`.

| Location | Builder change |
| --- | --- |
| `execution/work_order/operations.py` | Own `ResolvedOperation` and FK-first resolution. Keep `_column_access.py` as the resolver’s handler-declaration source. Reuse canonical or configured bundle outputs and exclude extra coherent members. |
| `execution/work_order/__init__.py` | Export the record and shared compile/preparation API. Work-order modules import `RelationshipGraph` from `decoy_engine.relationships` (public export at `relationships/__init__.py:43`). |
| `_planner.py:238`, `_sequential.py:316`, `_pandas_adapter.py:250` (PR head) | Replace all three sort choices with the shared decision. Move creator allocation out of the adapter-only path. |
| `_exact_int_sources.py:72` (PR head) | Bind exact-int registration and sampling to resolved output versions, including secondary outputs. |
| `execution/work_order/ranks.py` | Move the current rank sort out of `_runner.py`. Use it inside the shared decision. |
| `execution/work_order/versions.py` | Build the shared evaluation and commit dependencies from resolved operations. Use them for compile checks and execution. |
| `execution/work_order/commits.py` | Move selected-row output stitching out of `_when_gate.py`. Move shared per-table commit work out of the adapter and sequential loops. Keep saved versions local to each run. |
| `_runner.py:356`, `_runner.py:382`, `_runner.py:449`, `_runner.py:470`, `_runner.py:527` | Keep the current WorkNode ordering constraints for compatibility ranks. Use the extracted rank sort. Retain compatibility precedence as ordering constraints. Query output membership only through resolved records. |
| `_pandas_adapter.py:375`, `_when_gate.py:582`, `_strategies/_joint_mask.py:47` | Dispatch the resolved operation. Use its outputs for write-back and gated stitching. Remove the separate gated-output hook. |
| `_runner.py:329`, `_chunked_carry.py:202` | Use resolved writes for predicate snapshots and for full-frame and sequential type preservation. A wildcard covers every predicate input in its table. |
| `_chunked_carry.py:176`, `_column_access.py:527` | Feed the same write declaration into `passthrough_columns`. Replace the entry-based write union in `handler_written_columns`. Pass resolved writes to both `carried_columns` and `plan_carry` through this path. A wildcard disables carry for its table. |
| `_chunked_carry.py:228–245` (chunk-carry guard) | Exercise the planner and stock chunk lane with an unconfigured source field. Have the shared declaration report it as a bundle output. Assert both carry decisions exclude it and the chunk output keeps its generated value. Assert an unread, untouched control is carried. Inject the extra output into the compiled record before either carry caller runs, leaving the raw config untouched. Bypassing the shared declaration at line 176 must turn the guard red. |
| `tests/unit/execution/when/test_reads_source.py:572` | Use the S2 fixtures in `tests/unit/execution/when/_write_support.py`. Put the FK cases in the existing `test_write_order.py` beside it. Guard the commit boundary with a generated bundle containing an undeclared key. Removing the key check must turn the guard red. |
| `tests/sentry/defects/test_resolved_operation_writes.py` | Guard the execution write authority and both carry callers as specified below. |
| `tests/sentry/defects/test_when_single_reader.py:122` (PR head) | Normalize predicate call targets before checking caller and frame provenance. |

**DESIGN — write-authority sentry.** At PR head the competing sources are
`_runner.py:377` (ordering), `_runner.py:329,372` (snapshots),
`_chunked_carry.py:176,202` (carry and untouched columns), `_column_access.py:175`
and `_strategies/_joint_mask.py:47` (joint outputs), `_when_gate.py:563` (stitching),
`_exact_int_sources.py:72` (registration) and `work_order/commits.py:103` (capture).
Delete the duplicate write helpers and the joint handler output hook. Test the wiring
with a resolver fixture that returns a secondary output absent from the config,
node columns and ordinary handler declaration. Inject it at resolution and count one
selection per node per compilation. Assert the secondary output creates an ordering
edge, enters a predicate snapshot, leaves both carry sets and the untouched set,
receives the gated stitch, advances the exact-int version and receives a ranked
fallback commit. Exercise planner carry and stock chunk carry independently. Inspect
the resulting records/outputs at each consumer. A resolver call count alone can pass
even when its answer is discarded. Seed a bypass at each consumer in turn, including
each carry caller, and require its own assertion to fail. Restrict raw output-declaration
lookups to the resolver and its checked registry helpers with an import-normalized AST
guard. Pin helper identity by path and symbol and check its callers. On final head run
the guards and behavior mutations after the last refactor.

**V2-LOG — predicate sentry.** Resolve absolute and relative imports, direct imports
with an alias, module imports with and without an alias, qualified calls and simple
local aliases to the evaluator’s defining symbol. Pin the allowed (path, function)
and source-frame provenance for each call. Seed each spelling in an unauthorized
caller and with a live frame in an authorized caller. Each fixture must be rejected.
Keep a valid source-frame call as a passing control.
