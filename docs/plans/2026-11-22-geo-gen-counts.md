Status: plan (revision 1, 2026-11-22)

# GEO-GEN-COUNTS: mark geo_generalize whole-column, guard the flag, decide once per distinct ZIP

Owner: Cam. Author: Opus (plan author). Date: 2026-11-22. Roadmap row: GEO-GEN-COUNTS (V1 engine, approved 2026-11-22), from the fast-path exceptions study (vault `10_Projects/decoy/fastpath-exceptions-study-2026-11-22.md`, section 3) and the V1 fast-path audit (vault `10_Projects/decoy/v1-fast-path-audit-2026-11-22.md`).

Anchors: paths are in this repository (decoy-engine), read at `origin/main` `70881ad79`. Line numbers are at that head.

Rules consulted: dev-rules `README.md`, `00-universal.md`, `risk-and-exceptions.md`, `development-loop.md` (PLAN, choke point, placement), `profiles/local-operations.md`, `feature-dev.md`, `performance.md`, `cross-cutting-concerns.md`, `reuse-first.md`, `scope-discipline.md`, `proportionality.md`, `testing.md`, `architecture.md`, `security.md`, `catalogs/recurring-defects.md`; engine `CLAUDE.md` and `CODEMAP.md` ("Where Things Go"); PER-COLUMN-ROUTING plan (`origin/plan/per-column-routing` `8b74b74d9`, section 5).

Risk: R2. It touches an anonymisation strategy (HIPAA Safe Harbor ZIP cascade) and a security-relevant routing table. Output bytes do not change. Plan review: Dennis, then Codex. Code gate: Codex and Dennis.

## 1. Frame

### The leak question (answered first, sent to the orchestrator on 2026-11-22)

**No route runs `geo_generalize` per chunk at `70881ad79`. There is no leak today.** Each route that splits a table refuses the strategy by name:

| Route | Gate | Result for `geo_generalize` |
|---|---|---|
| chunked (`run_mask_pipeline_chunked`, CLI `--chunked`, native `run_mask_chunked`) | `_chunked.py:204` `_CHUNK_ADMITTED_STRATEGIES` = `CHUNK_SAFE_STRATEGIES` (`_chunked_fk_vocab.py:44-59`) plus the DGRN and sibling-keyed sets; checked at `:341` | `strategy_not_chunk_safe` |
| auto-chunk in `run_pipeline` | `_pipeline_chunk_route.py:44` calls `_planner.classify_job`, which reruns `check_chunked_compatibility` (`_planner.py:357`) | stays full frame |
| mixed generate-plus-mask | `_mixed_static.py:168` `chunk_unstable_warning_column` (`geo_generalize_cascade` is in `CHUNK_VARIANT_WARNING_CODES`, `_mixed_admission.py:92`), then `classify_job` | `mask_strategy_warnings_not_chunk_stable` |
| out-of-core | `out_of_core/_compat.py:105-110` `_DEFERRED_GROUP_C` | `out_of_core_whole_column_aggregation_unsupported` |
| native and unified slice | no kernel in `OPERATORS`, so `fallback_policy` is `python_only` (`native/_requirements.py:580-588`) | oracle on the full frame |
| PER-COLUMN-ROUTING (planned) | its chunked P half runs only when `_oracle_preflight` accepts the trimmed plan (its section 5) | stays full frame |

Even if a route did chunk it, the result would be over-generalization, not a leak. A chunk's count for a ZIP5, ZIP3 or state is never higher than the whole-column count. So any level that passes `k_threshold` inside a chunk also passes over the whole column, and every output group still has at least `k` rows. The ZIP3 floor (`max(20000, count)`, `transforms/geo_generalize.py:399`) and the restricted-prefix skip do not depend on counts. The defect is a route-dependent output (determinism and utility), never a privacy loss.

### The latent defect

The capability table says the opposite of the code. `native/_capabilities.py:265-272` marks `geo_generalize` as `_Ortho(True, False, False, False, True)`: row-local, not global. `cascade_zip_column` (`transforms/geo_generalize.py:294-375`) and `cascade_latlng_column` (`:466-560`) count values over the whole frame the handler receives. Three readers trust the wrong row:

- `native/_plan.py:398-403` `_native_rejection` passes it (it fails later, only on the missing kernel).
- `native/_requirements.py:397` `_required_prepasses` does not ask for `whole_column_pass`.
- `native/_requirements.py:580-588` `_fallback_policy` would return `native` the day a kernel lands.

Today only the missing kernel and hand-written name lists keep the strategy whole-frame. A future kernel, or a new chunk gate that reads `is_row_local` (the study's WHOLE-COLUMN-PREPASS), would chunk it with no warning. No test checks that "row-local" means "the same output on any split".

### The speed

`cascade_zip_column` runs Python per row four times: `_extract_zip5`, `_zip5_to_zip3`, the count-dict loops, and `_cascade_one_row`. `_build_state_map` (`:271-287`) rebuilds a 42k-entry dict from the reference table row by row on every call. The study measured 3.32 s at 1M rows on the Dell node, and 0.93 s for a build that decides once per distinct ZIP and maps back, with identical output. A ZIP column has at most about 42,000 distinct ZIP5 values, so per-distinct work is small.

## 2. Established solutions

- **Factorize, decide per distinct, gather back.** The dictionary-encode pattern: `pandas.factorize` (or Arrow `dictionary_encode`) gives integer codes and the distinct values. A per-distinct result array indexed by the codes is the output (`numpy` fancy indexing). This is how Arrow `DictionaryArray` decodes, and it is the study's `index_in` plus `take` probe.
- **Group sizes from codes.** `numpy.bincount(codes)` counts each distinct value in one pass.
- **Property-based differential test.** Hypothesis against a frozen copy of the old function, as the engine's parity suites do (`tests/parity/`).
- **A capability claim proved by behaviour.** The engine's capability totality test (`tests/native/test_capabilities.py`) checks that the table covers every handler. This row adds the matching behaviour check: a row marked row-local must give the same output on any split.

### Reuse inventory

- `transforms/geo_generalize.py`: `_extract_zip5`, `_zip5_to_zip3`, `_cascade_one_row`, `_cascade_one_latlng_row`, `_load_restricted_zip3`, `_build_state_map`, `CascadeEvidence`. All kept; the loops move from per row to per distinct.
- `execution/_strategies/_geo_generalize.py:84-123` handler: unchanged (section 5 names the one condition for a change).
- `native/_capabilities.py` `_MASK` table and `capabilities_for`: the one place the flag lives.
- `tests/native/test_column_access_surfaces.py:384` `_corpus()` and `tests/unit/execution/_auto_chunk_strategies.py` `STRATEGY_FIXTURES`: per-strategy configs and sources that the split sentry reuses.
- `_chunked.py` `_CHUNK_ADMITTED_STRATEGIES` and `CHUNK_CONDITIONAL_STRATEGIES`; `out_of_core/_compat.py` `_SUPPORTED_WORK_STRATEGIES`: admission sets that the consistency sentry reads (read only).

## 3. Guarantee and non-goals

After this row:

1. `capabilities_for("geo_generalize")` has `is_row_local=False` and `is_global=True`. `requirements_for` lists `whole_column_pass` for it, and every capability reader treats it as whole-column.
2. A sentry fails when a strategy marked row-local gives a different output on a split frame than on the whole frame.
3. A sentry fails when a chunk or out-of-core admission set contains a strategy whose capability row says `is_global=True`.
4. `geo_generalize` output (values, dtype, warning detail) is byte identical to `70881ad79` for every input, for both `zip` and `lat_lng`.
5. The ZIP path decides once per distinct raw value and is at least 3 times faster at 1M rows with 40,000 distinct ZIPs (study: 3.6 times).

Non-goals: chunking `geo_generalize` (needs WHOLE-COLUMN-PREPASS, 1.0.x); a native kernel; changing the cascade, the 20,000 floor, the suppress value or the `when:` semantics. With `when:`, counts are over the matched rows, as today; that is more conservative and is not changed here. The H3 library calls themselves are not changed.

## 4. Enumerations

### Exit paths

All unchanged; no new reason code.

- Plan codes `geo_generalize_unsupported_type`, `geo_generalize_invalid_cascade`, `geo_generalize_missing_suppress`, `geo_generalize_invalid_cascade_level` (`reasons/plan/_part2.py:194-203`), raised before any row is read.
- The h3 `ImportError` for `type: lat_lng` without the `geo` extra (`reasons/platform/_part1.py:393`).
- A state-map load failure: logs and continues with no states (state level never passes), retried on the next call after S2.
- Normal exit with warning `geo_generalize_cascade` when any row left the top level.

### Routes and codes

- chunked, auto-chunk, mixed, out-of-core: unchanged declines (section 1 table).
- full frame (oracle): unchanged; the only route that runs the strategy.
- `native_route_eligibility` (`native/_plan.py`, internal, not on the run card): `no_native_kernel:<col>:geo_generalize` becomes `requires_global_execution:<col>:geo_generalize`.
- native dispatch: keeps `fallback_policy_not_native` (`native/_dispatch.py:330-332`), so ROUTE-LABEL-TRUTH sees no change.

### FK shapes

N/A: `geo_generalize` has `join_safe = False` (`execution/_strategies/_geo_generalize.py:64`) and is never an FK key or FK child on any route.

### Fields

- `StrategyCapabilities` for `geo_generalize`: `is_row_local` True to False, `is_global` False to True, `notes` rewritten.
- `NodeRequirements.required_prepasses` for a geo node: `()` to `("whole_column_pass",)`.
- Config fields (`type`, `cascade`, `k_threshold`): unchanged.

### Output surfaces

- Masked column values and dtype: unchanged.
- `geo_generalize_cascade` warning detail (`rows_generalized`, `rows_<decision>`): unchanged.
- Debug log "a zip3 prefix is HHS-restricted" (`transforms/geo_generalize.py:385-389`): once per distinct ZIP, not once per row. It carries no value.
- Byte changes: none.

## 5. Design notes

No new source module and no new abstraction. Principles: one place per fact (the capability row), and a property checked by behaviour, not by a name list.

**S1: the flag and two sentries.**

- `_capabilities.py:265-272` becomes `_Ortho(False, False, True, False, True, warning_codes=("geo_generalize_cascade",), notes=...)`. The note says why: `k_threshold` reads whole-column counts (ZIP5, ZIP3 and state, or H3 cells); per-chunk counts would over-generalize and make output depend on the route; chunking needs WHOLE-COLUMN-PREPASS. The output type stays static (string).
- `tests/native/test_capabilities.py`: pin the new row, beside `test_shuffle_is_global_and_order_sensitive` (`:39`).
- **Split sentry**, new file `tests/sentry/defects/test_row_local_split_invariance.py`. For every mask capability row with `is_row_local=True`, run the full-frame pipeline (`run_pipeline(..., execution_mode="full_frame")`) on a 12-row source and on each 6-row half. Assert that the halves' outputs, concatenated, equal the whole output (values and Arrow type). Cases come from `_corpus()` and `STRATEGY_FIXTURES`. A row-local name with no case fails the test, so a new strategy must bring one. Exemptions are a named list, each with its reason in the test: `tokenize` (needs a platform vault callback), and any configuration that is position-keyed by design (non-deterministic `faker` reuse, covered by the chunked parity suites with a row offset). The geo case uses `k_threshold: 4` and one ZIP that appears four times, two in each half: the whole-column count passes and each half's count fails.
- **Admission consistency sentry**, same file: every name in `_CHUNK_ADMITTED_STRATEGIES`, `CHUNK_CONDITIONAL_STRATEGIES` and `out_of_core._compat._SUPPORTED_WORK_STRATEGIES` has `is_global=False`. If a current member fails, the builder stops and reports a finding; it does not edit a capability row to make the test pass.

Choke point: the capability row is the one fact. The split sentry is the guard that fails when the row is wrong. The mutation that must turn it red is setting `geo_generalize` back to `is_row_local=True`.

**S2: decide once per distinct value.** Inside `cascade_zip_column`, keep `raw_col = df[column].astype(str)`, so nulls stay `"None"` and `"nan"` as today:

1. `codes, uniques = pd.factorize(raw_col, sort=False)`; `weights = np.bincount(codes, minlength=len(uniques))`.
2. For each distinct raw value: `z5`, `z3` and `state` from the existing helpers.
3. Build the count maps by weighted sums over the distinct values (`zip5_counts[z5] += w`). They equal the per-row dicts. `state_counts` skips `""` as today.
4. Call `_cascade_one_row` once per distinct raw value, into object arrays `out_u` and `label_u`.
5. `result_df[column] = out_u[codes]` (object dtype, the same as assigning a list of `str`); `CascadeEvidence(decisions=tuple(label_u[codes]))`.

`_build_state_map` gets a module-level cache that stores only a successful build. A load failure still logs and returns `{}`, and the next call tries again, so a transient failure cannot pin "no states" for the whole process. `cascade_latlng_column` takes the same factorize step: parse and call `h3.latlng_to_cell` once per distinct raw value per resolution, and cascade once per distinct value. The handler stays as it is. If the S2 profile shows the handler's `Counter` over the 1M-entry tuple above 10 % of the run, `CascadeEvidence` gains an optional `counts` mapping and the handler reads it; otherwise nothing changes there.

**Placement:** no new source file. S1 adds one sentry test file.

| New file | Directory | CODEMAP row | Sits beside |
|---|---|---|---|
| `test_row_local_split_invariance.py` | `tests/sentry/defects/` | "Sentry test": recurring-defect class rules in `tests/sentry/defects/` | `test_canonical_json_choke_point.py` |

**Size:** S1 about 120 lines (one capability row, two test files). S2 about 80 source lines in `transforms/geo_generalize.py` and 150 test lines. No public name is added.

## 6. Defect classes

### Plan-contract catalog (docs/handoffs/DEFECT-CATALOG.md)

| # | Class | Where it could appear | Closing structure | Test | Mutation |
|---|---|---|---|---|---|
| 1 | Value-bearing output | the restricted-prefix debug log, the cascade warning | log text stays value-free; warning detail stays counts only | existing `tests/sentry/test_log_interpolation.py` | put `z3` in the debug log (sentry red) |
| 2 | Cleanup missing on an exit path | none: the handler holds no resource | N/A: no file, lock or staging is opened | none needed | N/A: nothing to release |
| 3 | State and concurrency | the new state-map cache | module-level cache holds only a successful, immutable build | A9 | cache a failed load (A9 red, M6) |
| 4 | Route parity and silent fallback | capability row says row-local; routes treat it as whole-column | the capability row is the one fact, proved by the split sentry and the admission sentry | A1, A2, A4 | M1 (A2 red) |
| 5 | Referential integrity | none: no key or FK column | N/A: geo_generalize is never a join key (`join_safe = False`) | none needed | N/A: no key path |
| 6 | Untrusted producer | source ZIP strings | unchanged: values are only digit-filtered and looked up, never parsed as code | A5 (letters, hyphens) | N/A: no new parser |
| 7 | Check then use | count maps then decision | counts and decisions come from the same factorized codes in one call | A5 | M4 (A5 red) |
| 8 | Weak tests | a differential on tiny or all-distinct inputs | Hypothesis with repeats, nulls, restricted prefixes and every cascade order; 1M bench | A5, A8 | M3 (A5 red) |
| 9 | Behavior-preserving refactor drift | S2 rewrite of the cascade loops | frozen copy of the old function as the oracle; Parquet bytes on the disguise | A5, A6, A7 | M5, M7 (A5 red) |
| 10 | Frozen contract drift | output values, warning detail keys | none changes; no `Breaking:` line | A7 | N/A: no contract surface touched |

### Recurring defect classes (dev-rules catalog)

| # | Class | Applies | How |
|---|---|---|---|
| 1 | Anchored validation | no | no new validation |
| 2 | Strict wire types | no | no persisted model |
| 3 | No exception context | no | no new error |
| 4 | Versioned read models | no | none |
| 5 | Normalized guard scanners | partly | the sentries read live registries (sets and the capability table), not source text, so there is no spelling to normalize |
| 6 | No private reaching | yes | the sentry imports `_chunked` and `_capabilities` from the engine's own tests, which is allowed inside one package |
| 7 | No hidden CI failures | yes | no `skip` or `xfail`; exemptions are a named list with reasons |
| 8 | One trust class per entry point | no | none |
| 9 | Mutations on final head | yes | S1 and S2 mutations rerun on each slice's final head; the head is recorded |
| 10 | Allowlisted helpers checked | yes | the exemption list holds exact strategy names, each with a reason; a new entry needs review |
| 11 | No raised caps | yes | no cap or allowlist grows, apart from the exemption list's first entries |

## 7. Acceptance tests (each with its fail-before)

- **A1** `capabilities_for("geo_generalize")`: `is_row_local is False` and `is_global is True`; `requirements_for` on a geo node lists `whole_column_pass`. Fails before: both flags are the opposite and the prepass list is empty.
- **A2** Split sentry, geo case (k 4, one ZIP split two and two): the whole output keeps the ZIP5 for those rows and the halves give the ZIP3. Fails before: red at `70881ad79`, where the row is marked row-local.
- **A3** The split sentry passes for every other row-local strategy at `70881ad79` plus S1, which shows the sentry is not geo-only. If another strategy fails, stop and report it as a new finding.
- **A4** The admission consistency sentry passes. Seeded self-test: adding `"geo_generalize"` to a copy of `CHUNK_SAFE_STRATEGIES` inside the test fails it.
- **A5** S2 differential (Hypothesis, 300 examples): lists of ZIP-like values (5-digit, ZIP+4 with a hyphen, short digit strings, letters, `None`, `float("nan")`, restricted prefixes from `us_zip3_population`, unknown ZIPs), `k` from 1 to 6, and every valid cascade order. The new `cascade_zip_column` equals a frozen test copy of the `70881ad79` function on values, dtype and `decisions`. The fail-before is the mutation set in section 8 (this is an identity change).
- **A6** The same differential for `cascade_latlng_column`. It is skipped only when h3 is absent, with the reason "h3 extra not installed"; the CI lane with extras runs it.
- **A7** Pipeline parity: `run_pipeline` output Parquet bytes for the `hipaa.yaml` disguise on a 10,000-row fixture are equal before and after S2.
- **A8** Speed, on the Dell node through `vm-run`, recorded in the PR (not a CI test): 1M rows, 40,000 distinct ZIPs, `k_threshold` 20000, three runs after one warmup, median and spread reported. Target: at least 3 times faster than `70881ad79`. Peak memory is reported beside it.
- **A9** `_build_state_map` cache: a first call whose load fails returns `{}`, and a second call whose load succeeds returns the full map.

## 8. Named mutations

- M1 `_capabilities.py`: `geo_generalize` back to `is_row_local=True` -> A1 and A2 red.
- M2 sentry: drop the "row-local name with no case fails" check -> the self-test with a seeded strategy that has no case goes red.
- M3 S2: build the count maps without weights (`+= 1` per distinct) -> A5 red.
- M4 S2: map the per-distinct results back by position, not by codes -> A5 red.
- M5 S2: let `state_counts` include `""` -> A5 red on unknown ZIPs.
- M6 S2: cache a failed state-map load -> A9 red.
- M7 S2: factorize `df[column]` instead of the `astype(str)` series, so nulls change -> A5 red on `None` and `nan`.

## 9. Slices

| Slice | Content | Size | Risk |
|---|---|---|---|
| S1 | capability row, A1 pin, split sentry, admission sentry | 0.3 | R2 (routing table) |
| S2 | per-distinct ZIP and lat/lng, state-map cache, A5 to A9 | 0.7 | R2 (anonymisation output, identity) |

S1 merges first and does not need S2. Each slice adds a `changelog.d/` fragment (S1: geo_generalize is classified as whole-column; S2: the ZIP cascade decides once per distinct value, with the same output). Test depth: T0 per edit and T1 impact-selected per commit. No escalation trigger applies (no shared fixture, test config or schema), so no full suite before merge.

## 10. Frozen contracts

None touched. Masked output bytes, the warning shape and every route code stay as they are, so there is no `Breaking:` line. `StrategyCapabilities` is internal (`execution.native`), not a frozen surface.

## 11. Pre-mortem

- **The split sentry finds a second mislabeled strategy.** Likely candidates: a handler that reads a frame-level fact (format detection, a frame-local row index in evidence). Response: stop, report it as a finding with its own row; do not widen the exemption list to make S1 green.
- **The sentry is flaky or slow.** It runs 12-row frames through `run_pipeline`; about 30 strategies at roughly 50 ms each. If it passes 10 s, run the handler through the adapter directly instead of the full pipeline.
- **factorize changes dtype.** Assigning an object ndarray must give the same `object` column as a list of `str`; A5 compares dtype, and A7 compares Parquet bytes.
- **Debug log volume was someone's signal.** It was per row; nobody reads per-row debug lines in production, and the line carries no value. Accept.
- **h3 differences.** Calling `latlng_to_cell` once per distinct string gives the same cell as once per row (pure function). A6 checks it on the extras lane.

## 12. Follow-ups (not this row)

- WHOLE-COLUMN-PREPASS (1.0.x): one count pass, then a row-pure chunked pass. `geo_generalize` becomes a consumer. The `whole_column_pass` requirement from S1 is what that seam reads.
- DERIVED-ARROW (1.0.x) is unrelated; the study lists it.
