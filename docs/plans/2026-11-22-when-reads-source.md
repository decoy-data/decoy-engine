Status: plan (revision 1, 2026-11-22; not yet reviewed)

# WHEN-READS-SOURCE: a `when:` condition reads the original value on every route

Owner: Cam. Author: Opus (plan author). Date: 2026-11-22. Roadmap row: WHEN-READS-SOURCE (new, V1, owner decision 2026-11-22). One engine slice, plus doc lines in the CLI repo carried by the next CLI docs PR.

Anchors: a path with no prefix is in this repository (decoy-engine) under `src/decoy_engine/`; `tests/` and `docs/` are repository paths; `CLI:` is the decoy CLI repo. Read at engine `origin/main` `70881ad79` (0.28.3). Line numbers are at that head.

Rules consulted: dev-rules `README.md`, `00-universal.md`, `development-loop.md` (PLAN, Proportion), `risk-and-exceptions.md`, `bugfix.md`, `feature-dev.md`, `architecture.md`, `cross-cutting-concerns.md`, `reuse-first.md`, `scope-discipline.md`, `proportionality.md`, `testing.md` (Test depth), `catalogs/recurring-defects.md`, `api-and-compatibility.md`, `security.md` (value-free errors), `documentation.md`, `workspace-and-vcs.md`; engine `CLAUDE.md` and `CODEMAP.md` ("Where Things Go").

Risk: R2. It changes masked output on the pandas routes for configs where a `when:` names a column that another column masks earlier, and it removes one native decline. Plan review: Dennis, then Codex. Code gate: Codex and Dennis (`/code-review high`: masking lane). T3 full suite at the merge head (golden outputs change), mutations on the changed units.

## 1. Frame

**The contract (owner, 2026-11-22).** `when:` means "mask when the original value = xyz". The condition selects rows by the values the source had, before any column of the job was masked.

**The defect.** The pandas oracle breaks that contract. `run_with_when_gate` (`execution/_when_gate.py:434`) evaluates the predicate on `df` (`:477`), the live frame that earlier nodes have already masked. So the rows a `when:` selects depend on column order:

```yaml
columns:
  - name: status          # sorts before zz_email, so it is masked first
    strategy: hash
  - name: zz_email
    strategy: faker
    when: "status == 'active'"   # oracle compares the HASH of status to 'active': matches nothing
```

Rename `zz_email` to `aa_email` and the predicate sees the original `status`, so the active rows are masked. The same config means two different things depending on a column name. In the first form the `email` values that should be masked are written out unmasked. That is a data leak, not a cosmetic difference.

The native lanes already read the original values: the chunked native leg evaluates on the raw chunk (`execution/native/_when_mask.py:52-60`) and the unified slice on `candidate.source_frame` (`execution/_unified_slice_when.py:73-90`). To keep them equal to the defective oracle, native admission declines any `when:` that reads a column masked earlier (`execution/native/_when_admission.py:169-175`, code `when_predicate_reads_masked_column`). That decline is a guard around the defect, not a rule of the contract.

**Out of scope.** A created column that reads masked siblings (`scalar_creating_reads`, `execution/_column_access.py:391`: `formula`, `derived` and the other creating strategies) keeps reading the masked value. That is its documented contract ("a created column runs after every column its value reads"). Only the `when:` gate changes.

## 2. Established solutions

Search run: how SQL engines and dataframe libraries evaluate a condition inside a multi-column update; how this codebase already reads a pre-mask value.

- **SQL `UPDATE ... SET a = f(a), b = CASE WHEN a = 'x' THEN g(b) ELSE b END`.** Every expression on the right side reads the row as it was before the statement (SQL standard; PostgreSQL, SQL Server and DuckDB all behave this way). The order of the `SET` list does not matter. `when:` with this plan behaves like a SQL `CASE WHEN` inside one `UPDATE`.
- **Polars `with_columns`.** All expressions in one call read the input frame, never each other's output.
- **pandas `DataFrame.assign`** with several keyword arguments evaluates callables in order against the updated frame. That is today's oracle behavior, and the reason the defect exists.
- **In this codebase:** `joint_mask` `key_by` and `date_shift` `group_by` already read a pre-mask value through `ctx.group_anchor_snapshots`, built from `source_anchor_columns` (`execution/_runner.py:265-279`) before the node loop (`execution/_pandas_adapter.py:199`, `:209-214`; `execution/_sequential.py:329`). `joint_mask` fails closed when its snapshot is missing (`execution/_strategies/_joint_mask.py:79-90`, `JOINT_MASK_KEY_BY_SNAPSHOT_MISSING`). This plan reuses that mechanism. It adds no second snapshot.

### Reuse inventory

- `execution/_runner.py:265` `source_anchor_columns` and the pre-mask `ctx.group_anchor_snapshots` built from it (`execution/_pandas_adapter.py:209-214`, `execution/_sequential.py:329`): the snapshot.
- `expressions/_when_parser.py:294` `when_column_refs`: the names a predicate reads.
- `execution/_when_gate.py:328` `_eval_predicate`: the one evaluator, unchanged.
- `reasons/route/_retired.py`: the tombstone pattern for shipped codes.

## 3. Guarantee and non-goals

After this plan:

1. On every route (full-frame oracle, sequential FK route, chunked oracle, out-of-core route, chunked native leg, unified slice) a `when:` predicate is evaluated on the original values of the columns it names. The original value is the value the masking stage received, after declared casts and `transforms`/`derive`, before any column is masked.
2. **One snapshot set.** `when_read_columns(plan)` (new, `execution/_runner.py`, beside `joint_mask_key_by_columns`) returns, per table, the columns any `ColumnSeed.when` names (`when_column_refs`). `source_anchor_columns` (`:265`) unions it in. So the pandas routes snapshot these columns pre-mask in the same dict, at the same place, with the same lossless integer conversion, as the `key_by` and `group_by` anchors. `_fk_keys._when_read_columns` (`execution/_fk_keys.py:315-333`) is deleted: the lossless set already includes `source_anchor_columns` (`:390`), so it reads the same set from one place.
3. **One evaluation input.** `run_with_when_gate` evaluates the predicate on `when_source_frame(df, ctx, refs)` (new, `execution/_when_gate.py`): a frame with `df`'s index whose columns are the snapshots of the referenced columns, aligned by index label (`snapshot.loc[df.index]`). A name the snapshot dict does not hold for this table is left out of the frame, so pandas raises the same coded `when_expression_error` for an undefined name that it raises today. If the table has a `when:` and the snapshot dict was never built for it (a wiring defect), the gate raises `when_source_snapshot_missing` (new runtime code), like `joint_mask`.
4. The native lanes keep evaluating on the raw source (`_when_mask.py:52-60`, `_unified_slice_when.py:73-90`). Those frames are the snapshot by construction: nothing writes to them. No code change there.
5. **Decline removed.** `when_native_rejection` no longer calls `_earlier_writes`; `_earlier_writes`, `READS_MASKED_CODE` and the `READS_MASKED_CODE` entry of `_WHEN_DECLINE_CODES` (`_when_admission.py:43`, `:85-115`, `:169-175`, `:194`, `:299`) are deleted. `RouteDeclineCode.WHEN_READS_MASKED_COLUMN` (`native/_route_decline_codes.py:51`) is deleted. The registry codes `route.when_reads_masked_column` (`reasons/route/_part1.py:146`) and `runtime.when_predicate_reads_masked_column` (`reasons/runtime/_part3.py:380`) shipped in tagged releases, so they move to tombstones with `deprecated_in` set to the release that carries this slice (`reasons/route/_retired.py` pattern, `:14-19`; a runtime tombstone sits in the runtime catalog the same way). A config that declined natively for this reason now runs natively.
6. Determinism: unchanged rules. The same config, seed and namespace give the same bytes on rerun. Output values no longer depend on column names or on chunk size.
7. Created columns (`scalar_creating_reads`) are unchanged and still read masked drivers in work order. The ordering edges (`column_dependency_edges`, `execution/_runner.py:354`) are unchanged; `when:` still adds no edge.

Non-goals: any change to `formula`, `derived` or other created-column reads; a `when:` that names a created column (still refused, `created_columns` at `_column_access.py:432`); new `when:` grammar; native admission of `when:` cases declined for other reasons (`when_predicate_not_native`, `when_outside_subset`); performance work on the gate.

## 4. Enumerations

### Exit paths

- Unknown column in a predicate: `when_expression_error`, as today (the name is left out of the eval frame).
- Snapshot dict missing for a table that has a `when:`: `when_source_snapshot_missing` (new), value-free, exit 3. Not reachable in production; a guard for a future route that forgets the snapshot.
- Every other `when:` error: unchanged codes (`when_outside_closed_grammar`, `numexpr_required`, `when_expression_not_boolean`).

### Routes

- Full-frame oracle: `PandasExecutionAdapter.run`, the one caller of `run_with_when_gate` (`execution/_pandas_adapter.py:423`). Snapshot built at `:209-214`.
- Sequential FK route: snapshot built from `source_anchor_columns` at `execution/_sequential.py:329`; dispatch goes through the same gate. `_sequential.py` (679 of ceiling 680) gets no edit.
- Chunked oracle: runs `PandasExecutionAdapter.run` per chunk (`execution/_chunked_oracle.py:450`), so the snapshot is per chunk. A `when:` is row-local, so per-chunk snapshots give the same rows as one full snapshot.
- Out-of-core route: reaches the gate only through the adapter; the builder confirms at DEVELOP with `grep run_with_when_gate` (one call site today).
- Chunked native leg and unified slice: read the raw source today; unchanged, now also admitted for the former `reads_masked` cases.

### FK shapes

- A `when:` that reads an FK key column: the key is snapshotted pre-mask with the lossless conversion (already in the lossless set). Covered by `tests/unit/execution/test_o1_when_eval_frame.py:139` (`test_fk_key_read_by_when_stays_exact`), which must still pass.
- An FK child column with a `when:` on the sequential route: same snapshot rule per table.

### Fields

- New runtime reason `when_source_snapshot_missing`.
- Tombstoned: `route.when_reads_masked_column`, `runtime.when_predicate_reads_masked_column`.
- Removed enum member: `RouteDeclineCode.WHEN_READS_MASKED_COLUMN`.

### Output surfaces

- Masked output of any table where a `when:` names a column masked earlier in work order (section 10).
- `chunked_route` and unified-slice evidence: such tables now admit natively, so `reroute_reason` and `decline_records` lose the `when_predicate_reads_masked_column` entry.

## 5. Slices and size

One slice.

| File | Lines now | Change | Expected after |
|---|---|---|---|
| `execution/_when_gate.py` | 541 | `when_source_frame`; `run_with_when_gate` passes it to `_eval_predicate` | about 570 |
| `execution/_runner.py` | 496 | `when_read_columns`; `source_anchor_columns` unions it; docstring states the `when:` contract | about 520 |
| `execution/_fk_keys.py` | 575 | delete `_when_read_columns` and its call | about 555 |
| `execution/native/_when_admission.py` | 307 | delete `_earlier_writes`, `READS_MASKED_CODE` and their uses | about 260 |
| `execution/native/_route_decline_codes.py` | 124 | delete one member | 123 |
| `reasons/route/_part1.py`, `reasons/route/_retired.py` | 303, 19 | move `WHEN_READS_MASKED_COLUMN` to a tombstone | -3, +6 |
| `reasons/runtime/_part3.py` | n/a | tombstone `WHEN_PREDICATE_READS_MASKED_COLUMN`; add `WHEN_SOURCE_SNAPSHOT_MISSING` | +8 |
| docs (section 9) and `changelog.d/when-reads-source.md` | | contract text; `Breaking:` line | about 60 |

Tests changed because they assert the removed decline (each rewritten to assert the native route now admits the table and its output equals the oracle):

- `tests/native/test_chunked_entry_evidence.py:249`
- `tests/native/test_c8_i_when_declines.py:230`, `:238`, `:295`, `:306`
- `tests/native/test_obs2_decline_records.py:130`, `:283-299`
- `tests/native/test_c8_i_when_auto_route.py:178`
- `tests/native/test_chunked_date_shift_admission.py:497`
- the F29 producer inventory baseline `tests/sentry/baselines/f29-producer-inventory.json` (the two codes leave the live producer set)

Size target: about 120 source lines added, about 90 removed, about 400 test lines. Well under the 600-line single-slice limit.

## 6. Placement

| New item | File | CODEMAP row | Sits beside |
|---|---|---|---|
| `when_read_columns` | `execution/_runner.py` (existing) | work list and source-read sets live in `_runner.py` | `joint_mask_key_by_columns`, `source_anchor_columns` |
| `when_source_frame` | `execution/_when_gate.py` (existing) | the `when:` gate | `run_with_when_gate`, `when_eval_frame` |
| `WHEN_SOURCE_SNAPSHOT_MISSING` | `reasons/runtime/_part3.py` | "Reason codes": one catalog package per namespace | `WHEN_*` runtime codes |
| `test_when_reads_source.py` | `tests/unit/execution/` | engine execution tests | `test_o1_when_routes.py`, `test_when_predicate.py` |
| `test_when_reads_source_property.py` | `tests/property/` | Hypothesis property tests | existing property suites |
| `test_when_single_reader.py` | `tests/sentry/defects/` | "Sentry test": recurring-defect class rules | `test_group_by_single_reader.py` |

No new module. `execution/` stays at 103 direct modules. No module crosses 600 lines.

## 7. Design notes

- **Principles.** One place per fact: the set of source-read columns is `source_anchor_columns` for every pandas route, and `when:` joins it instead of growing a third list. The deletion of `_fk_keys._when_read_columns` removes an existing duplicate.
- **Pattern.** SQL `UPDATE` semantics: every right-side expression reads the pre-statement row (section 2). In-codebase precedent: the `joint_mask` `key_by` pre-mask snapshot.
- **Choke point.** `_eval_predicate` has three callers: `run_with_when_gate` (oracle), `native/_when_mask.when_mask` (chunked native, raw chunk) and `compute_when_masks` (unified slice, source frame). The guard `tests/sentry/defects/test_when_single_reader.py` checks by AST that each call's frame argument comes from an allowed source: `when_source_frame(...)` in `_when_gate.py`, a `raw_chunk` selection in `_when_mask.py`, `candidate.source_frame` in the unified slice. A new caller fails the sentry until it is added with its reason. Mutation: pass `df` again in `run_with_when_gate` (sentry red, and W1 red).
- **House style.** `when_source_frame` takes the context, not loose dicts; no flag argument chooses live or source.

## 8. Class table

| # | Class | Where it applies | Structure that closes it | Proof | Mutation that must turn it red |
|---|---|---|---|---|---|
| 1 | Value-bearing output | the new snapshot-missing error | message names table and column only | W8 | add the expression text to the message (W8 red) |
| 2 | Cleanup missing on an exit path | none | N/A: the gate holds no resources | n/a | n/a |
| 3 | State and concurrency | snapshot dict shared across nodes | built once before the node loop; series are copies; never written | W2 | write the masked value into the snapshot (W2 red) |
| 4 | Route parity and silent fallback | oracle against native lanes | all routes read the original; the decline that hid the difference is gone | W3, W4 | read the live frame in the oracle (W1, W3 red) |
| 5 | Referential integrity | `when:` reading an FK key | key snapshotted with the lossless conversion | existing `test_fk_key_read_by_when_stays_exact` | n/a |
| 6 | Untrusted producer | none | N/A: inputs are compiled config | n/a | n/a |
| 7 | Check then use | snapshot built before the loop, read in the gate | the dict is built from the same compiled plan the gate runs | W6 | build the snapshot after the first node (W2 red) |
| 8 | Weak tests | ordering tests on one config | Hypothesis over column names and orders, and a direct "earlier node masks the read column" case | W1, W2 | n/a |
| 9 | Refactor drift | `_when_read_columns` removed | lossless set reads `source_anchor_columns` | existing `tests/sentry/defects/test_lossless_int_columns.py` | drop `when_read_columns` from `source_anchor_columns` (lossless sentry red) |
| 10 | Frozen contract drift | golden outputs, reason codes | goldens regenerated with a reason each (section 10); codes tombstoned, not deleted | W9, registry sentry | delete the tombstone (registry sentry red) |
| 11 | Determinism | column-name and chunk-size independence | evaluation input no longer depends on order | W1, W5 | n/a |

## 9. Acceptance tests

Each fails before the change unless marked control.

- **W1 order pairs (Hypothesis).** Random single-table configs: a `when:` column and the columns its predicate names, each named so that it sorts either before or after the gated column (`aa_`/`zz_` prefixes), with strategies `hash`, `redact`, `categorical`, `faker`. For each config, the pair of runs that differ only in names gives identical output after renaming back. Fail-before: the `zz_` form selects different rows.
- **W2 earlier node masks the read column.** `status: hash in ns` and `zz_email: faker(person_email)` with `when: "status == 'active'"`, 2,000 rows, 600 active: exactly the 600 active rows have a masked `zz_email`, the other 1,400 keep their source value, and `status` is masked on all rows. Fail-before: zero rows selected and 600 active emails written unmasked.
- **W3 native equals oracle.** The W2 table, and a W1 sample, on the chunked native leg (120,000 rows), the unified slice (2,000 rows) and the oracle (`--no-native`): output equal on every route. The native lanes now admit the table (evidence: no `when_*` decline). Fail-before: native declines with `when_predicate_reads_masked_column`.
- **W4 chunk-size invariance.** The W2 shape at 120,000 rows on the chunked oracle and the chunked native leg, chunk size 7,000 and 40,000: equal output.
- **W5 sequential route.** A two-table FK job where the child has `zz_note: redact` with `when: "kind == 'x'"` and `kind: hash`: rows selected by the original `kind`. Fail-before: no rows selected.
- **W6 snapshot missing.** A test double that runs the gate with an empty snapshot dict for a table with a `when:`: raises `when_source_snapshot_missing`.
- **W7 created columns unchanged (control).** `tests/unit/execution/test_cross_column_ordering.py:88`, `:122`, `:144` and `tests/unit/execution/test_cross_column_joint_mask_remediation.py:120` pass unchanged: a created column still reads the masked driver.
- **W8 value-free.** W6's message and every evidence entry hold no seeded sentinel value and no expression text.
- **W9 goldens.** The golden and snapshot suites (`tests/snapshots/`, `tests/parity/`, `tests/vectors/`, `tests/acceptance/`) run at the merge head. Every changed golden is regenerated in the PR and listed in the PR body with the reason "a `when:` read a column masked earlier in work order; it now reads the original value (WHEN-READS-SOURCE)". A golden that changes for any other reason blocks the merge. The builder finds the affected goldens with a temporary probe on the base head: in `run_with_when_gate`, compare the mask from the live frame with the mask from the snapshot and record the config when they differ. The probe is not committed.
- **W10 control: existing `when:` suites.** `test_o1_when_routes.py`, `test_o1_when_eval_frame.py`, `test_when_predicate.py`, `test_when_gate_mutation_kills.py`, `test_multi_table_when.py` pass unchanged, except where a case asserted the order-dependent result; each such case is rewritten and listed in the PR body.

Mutations (core units, final head): pass the live `df` to `_eval_predicate` (W1, W2, sentry red); build the snapshot after the node loop starts (W2 red); drop `when_read_columns` from `source_anchor_columns` (W6 path and lossless sentry red); restore the `reads_masked` decline (W3 red).

Test scope: T0 per edit; T1 impact selection plus the named tests and the sentry; T3 full suite at the merge head (goldens change), diffed against the saved main baseline.

## 10. Frozen contracts, goldens and docs

**Output change.** `Breaking: a when: condition now reads the original value of every column it names, as documented. Before, on the pandas routes, it read a value that a column earlier in work order had already masked, so the rows it selected depended on column names.` This is a correctness fix to the documented contract; no config key, public name or exit code changes.

**Evidence change.** `Breaking: the native lanes no longer decline a when: that names a column masked earlier; reason codes when_reads_masked_column and when_predicate_reads_masked_column are deprecated.`

**Goldens that change.** Only goldens whose config has a `when:` naming a column masked earlier in work order. Each is listed in the PR body with the reason in W9. No other golden may change.

**Docs to update (the contract in the owner's words: "mask when the original value = xyz").**

- `docs/strategies.md:1352-1361` "Conditional masking (when:)": add "A `when:` condition tests the original value of each column it names, before any column is masked. Column order and names do not change which rows it selects." Add the `status`/`email` example.
- `docs/determinism.md`: one line, output does not depend on column order for `when:`.
- `docs/qa/10-expressions-and-when.md`: the QA checklist row for an order pair and for a `when:` reading a masked column.
- `docs/compatibility-contract.md`: the deprecated codes.
- `docs/execution-backends.md`: remove `when_reads_masked_column` from the native decline list.
- CLI: `decoy explain` has no `when:` text today (topics in `CLI:src/decoy/cli/explain.py`, `yaml` at `:140`); add the contract sentence to the `yaml` topic. Also the `.decoy` language reference for `when` (AST field `CLI:src/decoy/lang/_ast.py:73`) and `CLI:docs/roadmap/groups/mask.md` if it describes `when:` reads. These go in the CLI docs PR that bumps the engine pin.
- Public docs site (`decoy-web-docs`, vendored engine docs): regenerated from the engine docs at its next sync. The site is paused until CLI V1, so this is a note in its resume list, not work now.

## 11. Pre-mortem

- **A user relied on the order-dependent reading** (a gate on a column that another column masks, written to match masked values). That config matched nothing before, or matched by accident, so it was already leaking. The changelog line and the docs example name the change.
- **A route builds no snapshot.** Today every pandas route goes through `PandasExecutionAdapter` or the sequential runner, and both build it from `source_anchor_columns`. W5 covers sequential, W4 the chunked oracle, and `when_source_snapshot_missing` fails closed for a future route.
- **Index alignment inside a gated sub-frame.** `when:` is evaluated on the frame the gate receives. `snapshot.loc[df.index]` aligns by label, and the snapshots share the adapter frames' `RangeIndex`. W2 checks positions; a nested handler that calls the gate on a reindexed frame would fail `.loc` loudly, not silently.
- **Memory.** One copy per `when:`-referenced column per table, the same cost the `key_by` and `group_by` anchors already pay. Usually a few string columns.
- **PER-COLUMN-ROUTING depends on this.** That plan now relies on guarantee 1 for its Python half (sub-table of original values). Merge this first.

## 12. Open questions for the owner

None. The contract and the out-of-scope line for created columns are the owner's decisions of 2026-11-22.
