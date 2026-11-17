Status: plan

# F24 engine half: full-lifecycle estimate including the ingestion peak (roadmap row 84)

Owner: Cam. Author: Opus plan agent. Date: 2026-11-17. Revision 1 (not yet reviewed).
Scope: engine slices 84-E1 and 84-E2. Advisory only. No CLI or platform change in this row.

Rules consulted: `dev-rules/README.md` (routing), `00-universal.md`, `risk-and-exceptions.md` (R1
and R2 tiers), `development-loop.md` (PLAN: guarantee, size, design notes, choke point, Placement,
Established solutions, Proportion), `feature-dev.md`, `performance.md` (measurement and variance),
`testing.md` (Test depth, full-suite triggers), `api-and-compatibility.md` (additive fields on a
public result), `architecture.md` (Layout), `reuse-first.md`, `scope-discipline.md`,
`proportionality.md`, `security.md` (value-free output), `documentation.md`,
`workspace-and-vcs.md` (Commit messages), `catalogs/recurring-defects.md` (classes 1 to 11); engine
`CLAUDE.md`, `CODEMAP.md` "Where Things Go" (`CODEMAP.md:252`, the "Pipeline spine and routes"
row), `docs/frozen-surfaces.md` (Execution public names row), `docs/compatibility-contract.md`;
the V1 bar (only a function break, data loss, a non-admin value leak or cascading design blocks
V1); the V1 threat model (accidental leaks only); the section CAP lock (capacity is advisory, warn,
never gate); owner rules: CLI V1 first, platform parked, no new features beyond the row.

Base: engine `origin/main` `3bddfc9ff` (#610). CLI `origin/main` `f7deac1` (#300), read only for
the ingestion facts in section 1. Line numbers below are from those heads.

## 1. Source and what is already done

Source spec, found in this order:

1. Roadmap row 84 (CLI repo `docs/ROADMAP.md`, section 5.3 group H): "F24 engine half:
   full-lifecycle estimate including the ingestion peak; advisory only", engine, After: estimator
   (engine #328). Row detail (`docs/roadmap/row-detail.md`): "Advisory per section CAP; enforced
   admission is V2."
2. MASTER F24 "Full-lifecycle capacity estimation and admission" (vault,
   `10_Projects/decoy/business/market-expansion-specs/MASTER - Decoy Feature Specification.md`).
   The 2026-10-27 audit gap: "it explicitly excludes the ingestion peak (transform buffers /
   generation pools / resident maps / staging / spill simultaneous lifetimes are not modeled)".
   How it works: "Estimates include simultaneous lifetimes rather than assuming all phases are
   separate." Example 1: "Preflight identifies ingestion as the limiting phase."
3. COMPANION V1/V2 scope: V1 is "advisory estimates with uncertainty"; V2 is "full-lifecycle
   prediction, accurate time estimates, and multi-job reservations"; "This does not make the
   existing advisory estimator an automatic refusal policy."
4. Vault memory `decoy-job-time-estimator-idea` (the website estimator idea) and the engine plans
   `docs/plans/2026-10-22-job-time-estimator.md` and
   `docs/plans/2026-10-28-b10-job-time-estimator-completion-remote.md` (the #328 build).

What is built (do not rebuild):

| Piece | Where | What it does today |
|---|---|---|
| `estimate_job`, `JobEstimate` (public) | `src/decoy_engine/execution/_job_estimate.py:82` | Route (row-count only), `peak_bytes` for the execute phase of a mask job, a runtime band. Never raises, never gates, never changes routing |
| Peak model | `src/decoy_engine/execution/_mem_estimate.py:447` | `intercept + basis * slope` per route; TB-4 measured slopes (`_mem_estimate.py:326`) and intercepts (`_mem_estimate.py:310`) |
| Size specs | `src/decoy_engine/execution/_mem_estimate_schema.py:107`, `:250` | Profile and generate-table adapters; strings priced only from a sample or a declared width, else unpriceable |
| Sample-to-spec adapter | `src/decoy_engine/execution/_pipeline_routing_samples.py:22` | `_mask_specs(mask_tables, caller_sources)`: Arrow types and widths from resident tables |
| Runtime band | `src/decoy_engine/execution/_throughput_calibration.py` | Byte or row throughput anchors, wide band |
| Generation floor | `src/decoy_engine/generation/_bounds.py:345` | A lower bound on resident generated Arrow buffers (no string payload) |
| OOC capacity check (public) | `src/decoy_engine/execution/capacity.py:7` | Out-of-core-FK only; its docstring states it "excludes that ingestion peak entirely" |

The gaps this row closes, each checked in code:

- G1. No ingestion term. The CLI reads every file source whole before the engine runs
  (`decoy/cli/run/_prepare.py:553` calls `_load_sources_from_config`,
  `decoy/cli/run/_execute.py:261`). A CSV source is read through the engine reader
  `read_csv_source(dtype=str)` (`src/decoy_engine/profile/_csv_reader.py:514`) into a pandas
  object frame, then copied to Arrow (`decoy/cli/_sources.py:389`). Every earlier table stays
  resident while the next one is read. Nothing prices this.
- G2. Inputs stay resident for the whole run in the CLI. The CLI keeps `ctx.sources` and hands
  `run_pipeline` resident Arrow tables, so the sequential and out-of-core routes do not get their
  bounded-memory benefit for inputs. TB-4 measured those two routes with lazy inputs
  (`scripts/tb4_calibration.py`, through `run_pipeline_isolated`), so their slopes exclude it.
- G3. No write term. Outputs come back resident; a CSV target converts each output to a pandas
  frame before `to_csv` (`decoy/cli/io/_targets.py:359`, `:405`).
- G4. Every string column is unpriceable in `estimate_job`, because it passes no sample
  (`_job_estimate.py:189`, `_mask_specs(mask_tables, {})`). A CSV source is all strings, so every
  CSV job is unpriceable today.
- G5. Generate-only jobs return `peak_bytes=None` and mixed jobs return no price at all
  (`_job_estimate.py:169`).
- G6. No limiting phase is reported.

## 2. Guarantee and non-goals

### The guarantee (pinned)

`estimate_job` reports, next to its existing fields, a lifecycle peak: the largest of three phase
peaks (ingest, execute, write), where each phase peak is the sum of the memory that is live at
the same time in that phase for a caller that reads every file source whole through the engine's
readers and holds inputs and outputs until it has written the last target. It names the phase
that sets the peak. On the measured fixtures in section 8 (run on test VMs), the lifecycle peak
is never below the measured peak RSS, and where the realized route equals the predicted route and
the job has at least 1,000,000 rows it is at most 1.5 times the measured peak (OQ-4). It stays
advisory: it never raises, never refuses a job, never changes a route, and its output holds byte
counts, phase tokens, table and column names only, never a cell value, a path or exception text.

### Non-goals

- Enforced admission, reservations or a refusal from the estimate (V2, row detail).
- Runtime: the existing runtime band is unchanged (OQ-1). Phase wall times are recorded in the
  calibration record only.
- Disk and scratch (spill, staging) sizing (OQ-2; F25 owns scratch).
- The `--chunked` CLI path and lazy (platform) handoff: the estimate assumes whole-file resident
  handoff, which over-predicts both (the safe direction). Stated in the docstring and the docs.
- Subset jobs (still "not applicable: subset").
- Per-strategy output widths (a hash output is wider than its input). Outputs are priced with the
  input widths; recorded as V2-LOG.
- Changing `estimate_job_capacity`, routing, or `_mem_estimate` constants.
- A CLI surface. OQ-3 recommends a separate CLI row.

## 3. Established solutions

Searches run 2026-11-17: web search "Spark CBO sizeInBytes estimate rowCount avgLen column
statistics", "polars DataFrame estimated_size pandas memory_usage deep pyarrow Table nbytes",
"XLA HeapSimulator peak memory live buffers buffer assignment"; qmd and grep in the vault for "F24
estimate" and "ingestion peak"; the codebase for `estimate_job`, `estimate_peak_bytes`,
`ingestion`, `read_source`, `generation_floor_bytes`, `wait4`.

| Problem | Established answer | Followed here |
|---|---|---|
| Size of a table before reading it | Spark CBO: `sizeInBytes` and `rowCount` from `ANALYZE TABLE`, with per-column `avgLen` and `maxLen` for strings; size = rows times average row width | Yes. Rows from the profile (Parquet footer exact, CSV estimate); average UTF-8 width per string column from a bounded sample of at most 10,000 rows |
| Bytes of a columnar table | Apache Arrow columnar format: validity bitmap, int32 offsets plus data for variable-width, `bit_width` for fixed-width; `pyarrow.Table.nbytes`; Polars `estimated_size()` sums the same buffers | Yes, the Arrow term (`_arrow_column_floor` already follows it, `generation/_bounds.py:306`) |
| Bytes of a pandas object frame | `DataFrame.memory_usage(deep=True)`: pointer plus each Python object; CPython PEP 393 compact str is 49 bytes plus length | Yes, the existing `raw_data_bytes` per-cell cost (57 plus width) |
| Peak over a program with overlapping lifetimes | Liveness-based peak: XLA buffer assignment and its heap simulator take the peak as the largest sum of live buffers over program points | Yes, three program points (ingest of table k, execute, write of table k); peak is the maximum of the live sums |
| Route working memory | Engine's own measured TB-4 model (two-point fit under process isolation) | Reused unchanged |
| Measure the real peak | Linux `getrusage`/`wait4` `ru_maxrss` from outside the worker (the engine's `scripts/fk-scale/_supervisor.py` pattern); DuckDB reports memory by tag but enforces `memory_limit` rather than predicting, so it gives no predictor to copy | Yes, the existing supervisor |

Custom code that remains: the three-phase live-set sums and the sample read for widths. Both are
small and specific to how Decoy hands data to the engine.

## 4. Behavior

### 4.1 Inputs (84-E1)

For each mask source, in config `sources` order (the CLI reads in that order):

- Rows: `TableProfile.row_count` and `row_count_exact` from the profile `estimate_job` already
  builds.
- Widths: a bounded sample of at most 10,000 rows, read the way the CLI reads the file:
  CSV through `read_csv_source(..., dtype=str, nrows=10_000)` then `pa.Table.from_pandas`;
  Parquet through `build_lazy_source` first batch; fixed_width through `build_profile_source`
  `sample_frame(10_000)` then Arrow. The sample tables go to the existing `_mask_specs` as its
  `caller_sources` argument, which already derives Arrow types and mean widths from resident
  tables. The sample is dropped after the specs are built.
- A source whose sample cannot be read leaves the lifecycle unpriced with a note naming the table
  and the exception type only.

### 4.2 Phase model (84-E1)

Terms per table `t`: `arrow(t)` is the Arrow bytes (fixed width times rows; for strings
`rows * (4 + width)`; one validity bit per row for a column with nulls); `frame(t)` is
`raw_data_bytes` of the table (the pandas object cost already in `_mem_estimate`); `I` is the
in-core intercept `route_intercept_bytes("full_frame")`.

- Ingest: for each source k in order, `I + sum(arrow(j) for j before k) + transient(k)`, where
  `transient(k)` is `frame(k) + arrow(k)` for CSV and fixed_width (both live during
  `from_pandas`), and `arrow(k)` plus the largest row group's `total_byte_size` from the footer
  for Parquet. The ingest peak is the largest of these.
- Execute: the existing `estimate_peak_bytes(specs, route)`. For `sequential` and `out_of_core`,
  plus `sum(arrow(all inputs))`, because the CLI keeps inputs resident and TB-4 measured those
  routes with lazy inputs (G2). For `full_frame` nothing is added: TB-4 measured it with inputs
  materialized, so its slope already holds them.
- Write: `I + sum(arrow(inputs)) + sum(arrow(outputs)) + transient_out(t*)`, where outputs are
  priced with the input specs and `t*` is the output with the largest transient; a CSV or
  fixed_width target's transient is `frame(t)`, a Parquet target's is 0.
- Lifecycle peak is the largest phase peak; the limiting phase is its token. Ties go to the
  earlier phase.

### 4.3 Generate and mixed jobs (84-E2)

- Generate tables: rows from `row_count`; widths from `table_size_spec_from_generate_table`
  (`_mem_estimate_schema.py:250`), and from `faker_payload_bound` (`generation/_bounds.py:104`)
  where that function gives a bound and the width table does not. A column with neither keeps the
  lifecycle unpriced with a note (no guess, matching section 3.5 of the OOM design).
- Execute for a generate-only job: `I + sum(arrow(generated tables)) + largest unique working set`
  (`table_unique_peak`, `generation/_bounds.py:271`); the resident run holds every generated table
  (`generation_floor_bytes` docstring). No ingest phase (no sources): its token is reported with
  0 bytes.
- Mixed job: execute is the mask route's execute term plus `sum(arrow(generated tables))`; ingest
  covers the mask sources; write covers every output.
- The existing fields keep their values: generate-only `peak_bytes` stays `None`; a mixed job stays
  `priceable=False` with its note. Only the new fields are filled.

### 4.4 Result fields (84-E1)

`JobEstimate` gains three fields, all with defaults, appended after `notes`:

- `lifecycle_peak_bytes: int | None = None`
- `limiting_phase: Literal["ingest", "execute", "write"] | None = None`
- `phase_bytes: tuple[tuple[str, int], ...] = ()`, in the fixed order ingest, execute, write.

When any table is unpriceable the three stay at their defaults and `notes` says why. When any
profiled row count is an estimate (CSV), `notes` gains "row counts estimated from file size".

`peak_bytes` keeps its meaning (the execute phase). With the sampled widths, string mask jobs now
get a `peak_bytes` too (OQ-5); the merged cell that pinned the old "unpriceable" answer changes as
listed in AT-E1-9.

## 5. Failure modes

| Id | Failure | Handling |
|---|---|---|
| FM-1 | Sample read fails (corrupt file, permission) | Lifecycle unpriced; note names the table and `type(exc).__name__`; the outer `estimate_job` try still holds |
| FM-2 | Exception text carries a cell value or a path | Never formatted; only the type name (the existing `_job_estimate.py:95` rule) |
| FM-3 | Column type with no size model (dictionary, list, struct) | Lifecycle unpriced; note names `table.column` |
| FM-4 | CSV row count is an estimate | Priced; note says so; the accuracy cells include a CSV fixture so the estimate error is measured |
| FM-5 | Non-ASCII strings: CPython holds them as UCS-2 or UCS-4, wider than UTF-8 bytes | Known under-price for wide-character text; one accuracy cell uses Latin-1 text; recorded in docs; V2-LOG for a width per encoding kind |
| FM-6 | Realized route differs from the coarse predicted route (native auto-chunk) | Lower bound asserted only; the cell records both routes |
| FM-7 | A sample shows no nulls but the file has them | The validity bit is missed (at most 1 bit per row); within tolerance; documented |
| FM-8 | Very wide config (thousands of columns) | Sample read is bounded in rows, not columns; same cost class as the existing profile read |
| FM-9 | A builder tunes a constant to make a cell green | Forbidden: no new constant without a measured record; a cell outside tolerance stops the slice and goes back to the plan |

## 6. Design notes and choke points

- New structure: one pure module for the phase sums and one input module that reads samples. No
  new public type: three fields on the existing public `JobEstimate`. The root facade
  (`src/decoy_engine/__init__.py`, 599 lines) is not touched.
- Principle: single responsibility. The arithmetic stays I/O-free (like `_mem_estimate`), so the
  unit cells run without files; the input module is the only one that opens a file.
- One place per fact: Arrow bytes per column in one function (reusing `_arrow_column_floor`'s
  rule through a shared helper, not a copy); pandas cost stays `raw_data_bytes`; the intercept
  stays `route_intercept_bytes`; widths come only from `_mask_specs` or the generate adapters.
- House style: a frozen `PhaseInputs` context object passed to the phase function, no flag
  arguments, comments that say why.
- Choke point: N/A as a cross-cutting rule. The row adds no rule other call sites must follow;
  `estimate_job` is the one entry and the only caller of the new modules.

## 7. Value-free rules

- Never in any field or note: a cell value, a sampled value, a file path, exception text.
- Allowed: table and column names from the config, byte counts, row counts, phase tokens, route
  tokens, exception type names.
- No log line is added.

## 8. Acceptance tests (red first)

Each test is written first and must fail on the base head for the reason given. Each names the
mutation that must turn it red. A builder may add tests; none of these may be weakened. Unit cells
run in the default loop through `vm-run` or the Mac, never on the devbox. Accuracy cells are
`benchmark`-marked and run on a test VM through `~/bin/vm-run`.

### 84-E1, unit (`tests/unit/execution/pipeline/test_lifecycle.py`, `tests/unit/execution/test_job_estimate.py`)

| Id | Test | Fails before | Named mutation |
|---|---|---|---|
| AT-E1-1 | Two CSV specs A then B: ingest peak equals `I + arrow(A) + frame(B) + arrow(B)` when B is larger, and `I + frame(A) + arrow(A)` when A is larger | module does not exist | drop the earlier tables' `arrow` from the live sum |
| AT-E1-2 | Parquet spec: ingest transient is `arrow + largest row group bytes`, not `frame + arrow` | module does not exist | price Parquet like CSV |
| AT-E1-3 | Sequential and out_of_core execute add `sum(arrow(inputs))`; full_frame execute equals `estimate_peak_bytes` exactly | module does not exist | add the input term on full_frame too |
| AT-E1-4 | Write: CSV target adds `frame` of the largest output; Parquet target adds 0 | module does not exist | use the smallest output |
| AT-E1-5 | `lifecycle_peak_bytes == max(phase_bytes)` and `limiting_phase` names it; ties pick the earlier phase | module does not exist | return the last phase on a tie |
| AT-E1-6 | A CSV mask job over real files: `lifecycle_peak_bytes` set, `phase_bytes` in order ingest, execute, write, note "row counts estimated" present | field does not exist | omit the estimated-rows note |
| AT-E1-7 | A Parquet source with a `list<int64>` column: lifecycle fields at defaults, note names `t.col`, no raise (the builder first confirms `classify_column` returns `Unpriceable` for it) | field does not exist | price an unpriceable column at 0 |
| AT-E1-8 | Sample bounded: a 30,000-row CSV and Parquet source; patched readers record `nrows <= 10_000` and the Parquet batch size; `to_frame` never called | sample read does not exist | read the whole file for the sample |
| AT-E1-9 | Edit list for merged cells in `tests/unit/execution/test_job_estimate.py`: `test_string_without_sample_is_unpriceable_not_a_raise` (`:55`) becomes "a string mask job is priced from a bounded sample" (priceable True, `peak_bytes` set); its honesty half moves to AT-E1-7. No other merged cell is edited | merged cell asserts the old answer | keep `_mask_specs(mask_tables, {})` |
| AT-E1-10 | Value-free: a CSV whose cells hold a seeded marker and a source path holding a second marker; a reader patched to raise `ValueError(marker)`; neither marker appears in `repr(est)` or any note; the raise case gives a note with `ValueError` only | sample read does not exist | format `str(exc)` into the note |
| AT-E1-11 | Never raises: every new-module function patched in turn to raise `RuntimeError`; `estimate_job` returns a `JobEstimate` | fields do not exist | let a lifecycle error escape the outer try |
| AT-E1-12 | No route change: for the merged fixtures, `est.route` and `est.runtime` equal their values with the lifecycle code patched out | fields do not exist | pass sampled widths into `decide_execution_route` |
| AT-E1-13 | Sentries pass with no raised cap: fan-out (`execution/` stays 103, `execution/pipeline/` under 25), module size, import layers with no new ignore line, physical-seam permit list naming the two new modules | guard | add an ignore line |

### 84-E1, accuracy (`tests/perf/test_f24_lifecycle_accuracy.py`, `benchmark` marker, test VM only)

The worker (`scripts/fk-scale/bench_worker_lifecycle.py`) does in one child process what the CLI
does: read every source through the engine readers in config order, hold them, call
`run_pipeline` with the resident tables, write every target (CSV through
`generated_table_to_pandas` then `to_csv`, Parquet through `pq.write_table`), and record the realized
route. The supervisor (`scripts/fk-scale/_supervisor.py:65`) reads `ru_maxrss` from outside.
Each cell asserts `measured <= predicted`, and `predicted <= 1.5 * measured` when the realized route
equals the predicted route and rows are at least 1,000,000.

| Id | Fixture (1M and 3M rows) | Expected limiting phase | Named mutation |
|---|---|---|---|
| AT-E1-14 | CSV, one table, 6 unique ASCII string columns, `redact` (stays on the pandas route) | ingest or execute, recorded | drop `frame` from the CSV transient |
| AT-E1-15 | CSV, three tables, FK chain, sequential route | ingest | drop the resident-input term on sequential |
| AT-E1-16 | Parquet, numeric FK, out_of_core route, CSV targets | write | price the CSV target transient as 0 |
| AT-E1-17 | CSV with Latin-1 text (FM-5) | recorded | none: records the wide-character error; lower bound only if outside |
| AT-E1-18 | CSV, single table, `hash` (native auto-chunk eligible, FM-6) | recorded | lower bound only |

### 84-E2 (`tests/unit/execution/pipeline/test_lifecycle_generate.py`, accuracy cells in the same perf file)

| Id | Test | Fails before | Named mutation |
|---|---|---|---|
| AT-E2-1 | Generate-only, `sequence` plus `faker` email: execute equals `I + sum(arrow) + unique peak`; ingest phase 0; `peak_bytes` still `None` | generate lifecycle does not exist | sum unique working sets across columns |
| AT-E2-2 | A generate column with no width source (`formula`): lifecycle unpriced, note names it | as above | price it at 0 |
| AT-E2-3 | Mixed job: execute is the mask execute term plus generated Arrow; `priceable` stays False and its "mixed" note stays | as above | drop the generated term |
| AT-E2-4 | Accuracy (VM): generate-only 3M rows to CSV; mixed 1M mask plus 1M generate to Parquet; same bounds as above | as above | drop the write transient for generated CSV |
| AT-E2-5 | Docs: `docs/execution-backends.md` estimate section names the three phases and the resident-handoff assumption; frozen-surface row text matches | doc missing | omit the assumption sentence |

## 9. Goldens, pins and sentries that move

- One merged test cell changes, listed in AT-E1-9; it follows the new contract and its honesty
  check moves to AT-E1-7 without loss.
- `tests/sentry/test_physical_seam_disconnection.py` `permitted_non_physical` gains the two new
  `execution/pipeline/` modules (E1) and the third (E2), each with a one-line why. This is a
  per-file permit list that the sentry requires for every changed execution module (vault memory
  `physical-seam-sentry-allowlist`); the guarded property (no `execution.physical` import) stays
  checked by the import sweeps. `_job_estimate.py` is already listed.
- No cap, ceiling, ratchet, fan-out pin, sentry baseline, determinism golden or `_mem_estimate`
  constant is raised or changed. `execution/` stays at 103 direct modules; the new files go in the
  named `execution/pipeline/` sub-package.
- The accuracy tolerance (1.5) is a test constant pinned by this plan (OQ-4), never widened in a
  build.

## 10. Placement (checked against `CODEMAP.md:252`, "Pipeline spine and routes")

| Item | Goes in | Map line and neighbor |
|---|---|---|
| Phase arithmetic | `src/decoy_engine/execution/pipeline/_lifecycle.py` (new) | "new route clusters in ... `execution/pipeline/`"; beside `_host.py` and `_routing_facts.py`; not `execution/` (frozen at 103) |
| Sample reads and spec building | `src/decoy_engine/execution/pipeline/_lifecycle_inputs.py` (new) | same row; beside `_lifecycle.py` |
| Generate and mixed terms (E2) | `src/decoy_engine/execution/pipeline/_lifecycle_generate.py` (new) | same row; keeps `_lifecycle.py` I/O-free and under 400 lines |
| Result fields and wiring | `src/decoy_engine/execution/_job_estimate.py` | existing module (214 lines, ends near 300) |
| Unit tests | `tests/unit/execution/pipeline/` (new folder) | "Unit tests" row: mirror `src/` |
| Accuracy worker | `scripts/fk-scale/bench_worker_lifecycle.py` (new) | "Dev tooling" row, topic folder `scripts/fk-scale/` (9 modules), beside `bench_worker_gen.py` |
| Accuracy cells | `tests/perf/test_f24_lifecycle_accuracy.py` (new) | existing perf suite, `benchmark` marker, beside `test_fr0_bounded_generation_rss.py` |
| CODEMAP rows | `CODEMAP.md` file rows for the three modules | beside the `pipeline/_host.py` row (`CODEMAP.md:104`) |
| Docs | `docs/execution-backends.md` new section "Advisory job estimate and lifecycle peak" | existing routing doc |
| Calibration record | `docs/records/2026-11-xx-f24-lifecycle-calibration.md` | "Plans, decisions, records" row |
| Changelog | `changelog.d/f24-lifecycle-e1.md`, `changelog.d/f24-lifecycle-e2.md` | fragment rules |

## 11. Reuse inventory

| Need | Reused | Where |
|---|---|---|
| Entry point, never-raise wrapper | `estimate_job`, `JobEstimate` | `src/decoy_engine/execution/_job_estimate.py:82` |
| Route and execute peak | `estimate_peak_bytes`, `route_intercept_bytes` | `src/decoy_engine/execution/_mem_estimate.py:447`, `:348` |
| Pandas frame bytes | `raw_data_bytes` | `src/decoy_engine/execution/_mem_estimate.py:205` |
| Specs from samples | `_mask_specs` | `src/decoy_engine/execution/_pipeline_routing_samples.py:22` |
| String width | `sample_average_string_bytes` | `src/decoy_engine/execution/_mem_estimate_schema.py:50` |
| Arrow column bytes | the rule of `_arrow_column_floor` | `src/decoy_engine/generation/_bounds.py:306` |
| Generate widths and unique sets | `table_size_spec_from_generate_table`, `faker_payload_bound`, `table_unique_peak` | `src/decoy_engine/execution/_mem_estimate_schema.py:250`, `src/decoy_engine/generation/_bounds.py:104`, `:271` |
| CSV read as the CLI reads | `read_csv_source` | `src/decoy_engine/profile/_csv_reader.py:514` |
| Parquet and fixed_width readers | `build_lazy_source`, `build_profile_source` | `src/decoy_engine/profile/_lazy_build.py:131`, `src/decoy_engine/profile/_readers.py:493` |
| Peak measurement | `run_worker` supervisor | `scripts/fk-scale/_supervisor.py:65` |

## 12. Frozen contracts touched

All additive.

- `JobEstimate` (Execution row of `docs/frozen-surfaces.md`, contract 3.4) gains three defaulted
  fields. The row pins the name, not the fields; the frozen-surface page gets one sentence naming
  the fields.
- `JobEstimate.peak_bytes` is now set for string mask jobs that were unpriceable (G4). Semantics
  unchanged (execute phase); a consumer sees a number where it saw `None`. Pre-GA, and the only
  consumers are the parked platform B-10 work and no CLI caller (checked: CLI `origin/main` has no
  `estimate_job` call). Named in the changelog fragment.
- No new public name, reason code, format tag, schema, exit code or config key. No reason code is
  added, so nothing needs since=UNRELEASED; if a build finds it needs one, it is registered with
  since=UNRELEASED and the plan is amended first.

## 13. Class table

| # | Class | Closing structure | Sentry or property test | Mutation |
|---|---|---|---|---|
| 1 | Value-bearing output | Notes carry names, counts and exception type names only; sample frames dropped after spec build | AT-E1-10 | format `str(exc)` into a note |
| 2 | Cleanup missing on an exit path | Sample reads go through the file-access handles' context managers; no temp files are created | AT-E1-8, AT-E1-11 | open a Parquet file without closing it on the error path |
| 3 | State and concurrency | Pure functions over frozen specs; no cache or module global | AT-E1-1 to AT-E1-5 run twice in one process with equal results | memoize specs in a module global |
| 4 | Route parity and silent fallback | The route comes from the unchanged router call; the lifecycle never feeds routing; native realized routes are asserted lower-bound only, never silently passed | AT-E1-12, AT-E1-18 | pass sampled widths into `decide_execution_route` |
| 5 | Referential integrity | N/A: the estimate reads samples and writes nothing; FK shape only selects the route term | N/A, covered by AT-E1-15 for the sequential term | N/A |
| 6 | Untrusted producer | Source files are user data: bounded sample, typed classifier, unpriceable on any unknown type, never raises | AT-E1-7, AT-E1-8, AT-E1-11 | price an unknown type at 0 |
| 7 | Check then use on a path (TOCTOU) | The estimate is advisory and reads each file once for its sample; a file that changes before the run only makes the estimate stale, which the docs state | AT-E1-8 | re-open the file after the stat for the sample |
| 8 | Weak tests and overclaimed evidence | Red-first cells with named mutations; accuracy cells on VMs with a pinned tolerance; realized route recorded so a native run cannot pass the upper bound by accident | AT-E1-14 to AT-E1-18, AT-E2-4 | widen the tolerance to 3.0 |
| 9 | Behavior-preserving refactor drift | N/A: no refactor; one merged cell edit listed in AT-E1-9, its check kept in AT-E1-7 | AT-E1-9, AT-E1-12 | edit a merged cell beyond the list |
| 10 | Frozen contract drift | Additive defaulted fields; frozen-surface sentence; changelog names the `peak_bytes` change | `tests/sentry/release/test_frozen_surface_map.py`, `tests/unit/test_public_api.py` | rename `peak_bytes` |

Class 11 (no raised caps): nothing in this plan raises a cap, ceiling, pin, baseline or allowlist
count; the physical-seam permit entries are per-file rationale lines the sentry requires (section 9).

## 14. Enumerations

### Exit paths

- `estimate_job` returns a `JobEstimate` on every path; any exception becomes
  `route="unknown"` with a type-name note (`src/decoy_engine/execution/_job_estimate.py:95`).
- Subset: early return, lifecycle fields at defaults (`src/decoy_engine/execution/_job_estimate.py:104`).
- Mixed: returns `priceable=False` with lifecycle fields filled from E2 (`src/decoy_engine/execution/_job_estimate.py:169`).
- Unpriceable column or failed sample read: lifecycle fields at defaults plus a note.

### Routes

- `full_frame`: execute term is the TB-4 model unchanged (`src/decoy_engine/execution/_mem_estimate.py:447`).
- `sequential`, `out_of_core`: TB-4 model plus resident inputs (G2; `src/decoy_engine/execution/_pipeline_sources.py:127`).
- Any other route token (`mixed`, `unknown`): priced as `full_frame`, the existing rule and note (`src/decoy_engine/execution/_job_estimate.py:205`).
- Native auto-chunk and the CLI `--chunked` path: not predicted; over-predicted by design.

### FK shapes

- No FK: single or multiple independent tables, any route.
- FK chain and fan-in: they only change the route and therefore the execute term; the ingest and
  write sums are per table and do not depend on edges. AT-E1-15 and AT-E1-16 cover a chain on
  sequential and out_of_core.

### Fields

- `JobEstimate.lifecycle_peak_bytes`: `int | None`, at least 0.
- `JobEstimate.limiting_phase`: `"ingest" | "execute" | "write" | None`.
- `JobEstimate.phase_bytes`: three `(token, bytes)` pairs in fixed order, or empty.
- Existing `route`, `priceable`, `peak_bytes`, `runtime`, `notes`: unchanged meanings.

### Output surfaces

- The returned `JobEstimate` only: fields and `notes`.
- No log line, no file written, no event emitted, no exception text.

## 15. Slices, gates and risk

| Slice | Repo | Production files | Count | Lines | Depends on | Risk |
|---|---|---|---|---|---|---|
| 84-E1 | engine | `execution/pipeline/_lifecycle.py` (new), `execution/pipeline/_lifecycle_inputs.py` (new), `execution/_job_estimate.py`; plus the worker, unit and perf tests, permit entries, CODEMAP rows, frozen-surface sentence, calibration record, changelog fragment | 3 | about 550 production | #328 (merged) | R2 (reads source values for widths, a value-leak surface; changes a public result) |
| 84-E2 | engine | `execution/pipeline/_lifecycle_generate.py` (new), `execution/_job_estimate.py`, `execution/pipeline/_lifecycle.py`; plus tests, docs section, changelog fragment | 3 | about 300 production | 84-E1 merged | R1 (no source values, no new public field) |

Gates: R2 is Dennis then Codex on the exact head; R1 is Codex only. Tests: T0 per edit, T1 per
commit, T2 at the gate, on the Mac or a VM through `~/bin/vm-run`, never the devbox; accuracy
cells once per slice on a test VM, their numbers in the calibration record with the head they ran
on. Full-suite trigger: none expected (no shared fixtures, schema, lock or frozen format); E1
changes a public result's values, which the gate judges against the serialization trigger, and
if it applies, one full suite on the merge head against the saved main baseline. Commit rules:
Conventional Commits subject, no body unless it says why, final line `cam`.

## 16. Dependencies and release

1. 84-E1 builds now; #328 is merged.
2. 84-E2 builds on E1's merge.
3. The next daily engine release carries them (row 77 cadence). No CLI repin is needed for this
   row, because no CLI code calls `estimate_job` today.

## 17. Owner questions

- **OQ-1. Lifecycle covers memory only; the runtime band stays as it is?** Recommended: yes.
  COMPANION puts accurate time estimates in V2, and ingest and write throughput have no measured
  anchor. The accuracy worker records phase wall times in the calibration record, so a later row
  has data.
- **OQ-2. Disk and scratch (spill, staging) stay out of this row?** Recommended: yes. F25 owns
  scratch; `predict_ooc_disk_bytes` exists for a later row. V2-LOG.
- **OQ-3. Add a CLI row so `decoy validate preflight` prints the lifecycle line (advisory,
  value-free)?** Recommended: yes, as a new small CLI row after the engine release. Without it the
  estimate reaches no user, against the standing "express every capability" rule.
- **OQ-4. Accuracy bar: never below the measured peak; at most 1.5 times it when the route matches
  and rows are at least 1M?** Recommended: yes. Under-prediction is the unsafe direction; 1.5
  leaves room for the TB-4 slope margin (up to +22 percent) plus CSV row-count error.
- **OQ-5. Price string mask columns from the bounded sample in `peak_bytes` too, not only in the
  lifecycle fields?** Recommended: yes. Every CSV job is unpriceable today; one merged cell
  changes (AT-E1-9). The other option (lifecycle only) leaves `priceable=False` beside a priced
  lifecycle, which reads as a contradiction.

## 18. Pre-mortem

Assume it is 2026-12-05 and row 84 is not closed. Likely reasons, with the guard for each:

- An accuracy cell came in under the measured peak because the execute term for `full_frame`
  misses a copy the CLI makes (declared-type casting of CSV inputs). Guard: the cell fails red;
  the slice stops and the plan is amended with a measured term (FM-9), not a tuned constant.
- The upper bound failed on a cell that went native. Guard: realized route recorded; FM-6.
- The sample read leaked a cell value through a reader error. Guard: AT-E1-10.
- Accuracy cells were run on the devbox and stalled it. Guard: `benchmark` marker excluded by
  default; the brief names `vm-run`.
- Review went three rounds over whether `peak_bytes` may change. Guard: OQ-5 asked up front.
- The physical-seam sentry failed CI on the new modules. Guard: section 9 lists the entries.

## 19. Follow-ups (recorded, not in this row)

- V2-LOG: per-strategy output widths for the write phase.
- V2-LOG: string width per CPython encoding kind (FM-5).
- V2-LOG: lazy and chunked handoff models (platform, `--chunked`).
- V2-LOG: move `_mem_estimate*`, `_job_estimate.py` and `_throughput_calibration.py` into one
  estimate sub-package when one of them next changes.
- V2: reservation model and enforced admission (platform, parked).
- CLI roadmap row 84: point at this plan.
