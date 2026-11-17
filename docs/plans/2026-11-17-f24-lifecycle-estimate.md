Status: plan

# F24 engine half: full-lifecycle estimate including the ingestion peak (roadmap row 84)

Owner: Cam. Author: Opus plan agent. Date: 2026-11-17. Revision 5 (Dennis round 1 on
`f7c5065f4` applied in revision 2; Codex round 1 on `1181509d7` applied in revision 3; Codex
round 2 on `d03677750` applied in revision 4; revision 5 is the orchestrator amendment after the
84-E1 build stopped on four accuracy cells (FM-12): output specs in the execute and write terms,
section 4.2a; the review record is in section 20).
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

Base: engine `origin/main` `3bddfc9ff` (#610). CLI `origin/main` `b6f8558d`, read only for the
ingestion facts in section 1. Line numbers below are from those heads.

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
5. The TB-4 calibration record `docs/plans/2026-07-13-tb4-calibration-results.md` (measured peaks
   per shape and route; used for the expected ratios in section 8.3).

What is built (do not rebuild):

| Piece | Where | What it does today |
|---|---|---|
| `estimate_job`, `JobEstimate` (public) | `src/decoy_engine/execution/_job_estimate.py:82` | Route (row-count only), `peak_bytes` for the execute phase of a mask job, a runtime band. Never raises, never gates, never changes routing |
| Peak model | `src/decoy_engine/execution/_mem_estimate.py:447` | `intercept + basis * slope` per route; TB-4 measured slopes (`_mem_estimate.py:326`) and intercepts (`_mem_estimate.py:310`) |
| Size specs | `src/decoy_engine/execution/_mem_estimate_schema.py:107`, `:250` | Profile and generate-table adapters; strings priced only from a sample or a declared width, else unpriceable |
| Arrow type per column | `src/decoy_engine/execution/_mem_estimate_arrow.py:254` | `column_arrow_types(resident, profile_table)`: Arrow type and exact null flag per column |
| Sample-to-spec adapter | `src/decoy_engine/execution/_pipeline_routing_samples.py:22` | `_mask_specs(mask_tables, caller_sources)`: specs from resident tables |
| Runtime band | `src/decoy_engine/execution/_throughput_calibration.py` | Byte or row throughput anchors, wide band |
| Generation floor | `src/decoy_engine/generation/_bounds.py:345` | A lower bound on resident generated Arrow buffers (no string payload), from `classify_plan` (`generation/_admission.py:169`) |
| OOC capacity check (public) | `src/decoy_engine/execution/capacity.py:7` | Out-of-core-FK only; its docstring states it "excludes that ingestion peak entirely" |

The gaps this row closes, each checked in code:

- G1. No ingestion term. The CLI reads every file source whole before the engine runs
  (`decoy/cli/run/_prepare.py:553` calls `_load_sources_from_config`,
  `decoy/cli/run/_execute.py:261`). A CSV source is read all-text into a pandas object frame,
  then copied to Arrow (`decoy/cli/_sources.py:418-419`); fixed_width goes through
  `read_fixed_width`, which parses each line into a dict of typed Python values and builds one
  DataFrame from the list (`src/decoy_engine/profile/_fixed_width_reader.py:343`, `:384`), then
  Arrow (`decoy/cli/_sources.py:423-424`). Every earlier table stays resident while the next one is read.
- G2. Inputs stay resident for the whole run in the CLI. TB-4 ran through `run_pipeline_isolated`
  with `LazySource` inputs that `run_pipeline` resolves at the point of use
  (`src/decoy_engine/execution/_isolated_worker.py:76`). Full_frame resolved all of them and held
  them, so its slope already holds the inputs. Sequential read one table at a time through its
  loader and dropped it after use (`src/decoy_engine/execution/_sequential.py:443`, `del src`).
  Out_of_core scanned the lazy sources and never held them. The CLI instead holds every input as
  Arrow from start to end.
- G3. No write term. Outputs come back resident; a CSV target converts each output to a pandas
  frame before `to_csv` (`decoy/cli/io/_targets.py:359`, `:405`). A fixed_width target is
  heavier. `_write_fixed_width` (`decoy/cli/io/_targets.py:372`) runs
  `_coerce_int_columns(table.to_pandas(), layout)` (`decoy/cli/io/_targets.py:324`), which copies
  the frame (`out = frame.copy()`) and returns the copy, then passes the copy to the engine
  writer, which turns every column into a Python list with `.tolist()`
  (`src/decoy_engine/profile/_fixed_width_writer.py:310`). The live set has two moments, checked
  against those lines:
  - During coercion: the Arrow output, the `to_pandas` frame and its copy.
  - During the list conversion: the Arrow output, the copy and the lists. The `to_pandas` frame
    has no reference left once coercion returns, so its numeric arrays are freed; its str objects
    stay alive because the copy points at them, so the copy then costs a full `frame`.
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
is never below the measured peak RSS. It is at most 1.5 times the measured peak for the cells
section 8.3 marks "bounded": type-preserving numeric-led cells (every masked column keeps its
input type, so its output spec equals its input spec, section 4.2a), and cells whose predicted
limiting phase is ingest or write, where the realized route equals the predicted route and the
job has at least 1,000,000 rows (OQ-4). Cells whose execute phase is priced on string cells
(string inputs, or numeric inputs that a strategy turns into strings, such as `hash` and
`redact`) carry the TB-4 string slope margin and the native-route gap (section 4.2a), measured
or expected at 1.1 to 5.9 times (section 8.3), and are checked against the lower bound only. It
stays advisory: it
never raises, never refuses a job, never changes a route, and its output holds byte counts, phase
tokens, table and column names only, never a cell value, a path or exception text.

### Non-goals

- Enforced admission, reservations or a refusal from the estimate (V2, row detail).
- Runtime: the existing runtime band is unchanged (OQ-1). Phase wall times are recorded in the
  calibration record only.
- Disk and scratch (spill, staging) sizing (OQ-2; F25 owns scratch).
- The `--chunked` CLI path and lazy (platform) handoff: the estimate assumes whole-file resident
  handoff, which over-predicts both (the safe direction). Stated in the docstring and the docs.
- Subset jobs (still "not applicable: subset").
- Output widths for strategies other than `passthrough`, `hash` and `redact` (section 4.2a prices
  those three). A string column under another strategy is priced at its input width; a
  non-string column under another strategy leaves the lifecycle unpriced with a note (FM-13).
  V2-LOG: an output spec per strategy, each with a measured cell.
- A native-aware execute term. The estimate prices the pandas form of a string output even when
  the native unified slice keeps it in Arrow at run time (FM-14). V2-LOG.
- Vault maps, the post-scan baseline tables (`tee` in `_pipeline_sources.py:127`) and quarantine
  frames. They are live at the same time as the route's working set on jobs that use them, and
  none has a measured size model. V2-LOG; the docs name them as unpriced.
- A tighter upper bound for string execute cells. It needs new string-shape slopes, which is a
  `_mem_estimate` change. V2-LOG.
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
| Bytes of a columnar table | Apache Arrow columnar format: validity bitmap, int32 offsets plus data for variable-width, `bit_width` for fixed-width; `pyarrow.Table.nbytes`; Polars `estimated_size()` sums the same buffers | Yes, one helper `arrow_column_bytes` (section 6) that the generation floor also uses |
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
- Sample: at most 10,000 rows, read the way the CLI reads the file. CSV through
  `read_csv_source(..., dtype=str, nrows=10_000)` then `pa.Table.from_pandas`; Parquet through
  `build_lazy_source` first batch; fixed_width through `build_profile_source`
  `sample_frame(10_000)` then Arrow. The Parquet sample is bounded in rows, not bytes: a file with
  very wide values reads 10,000 of them (the same bound the profile read already has).
- Per column: the Arrow type and null flag come from `column_arrow_types(sample, profile_table)`
  (`_mem_estimate_arrow.py:254`), and the mean width from the existing `_mask_specs` with the
  sample as `caller_sources`. Each `PhaseInputs` column carries `(arrow_type, has_nulls, width)`;
  there is no table that maps a pandas label to an Arrow type. Each column also carries its
  output spec (section 4.2a).
- A string column whose sample holds no non-null value is unpriced with a note naming it (it is
  not priced as `Declared(0.0)`).
- The sample is dropped after the inputs are built.
- The reader and transient rule is keyed on the format name. The rule table's keys must equal the
  keys of `FILE_FORMATS` (`src/decoy_engine/profile/_lazy_build.py:118`); a guard test checks this
  (AT-E1-20). A format with no rule leaves the lifecycle unpriced with a note.
- A source whose sample cannot be read leaves the lifecycle unpriced with a note naming the table
  and the exception type only.

### 4.2 Phase model (84-E1)

Terms per table `t`: `arrow(t)` is the sum of `arrow_column_bytes(type, rows, width)` over its
columns; `frame(t)` is `raw_data_bytes` of the table (the pandas object cost already in
`_mem_estimate`); `I` is the in-core intercept `route_intercept_bytes("full_frame")`. Three
Python-object terms price the fixed-width paths:

- `refs(t)`: a pandas array that points at Python objects that already exist. 8 bytes per cell
  for a string (object) column, the dtype item size (plus 1 for a nullable extension dtype) for
  a numeric column. A pandas deep copy of an object column copies the pointer array, not the
  str objects, so `frame.copy()` costs `refs(t)` while the original frame is alive.
- `lists(t)`: the `.tolist()` lists. An 8-byte list slot per cell; a numeric cell also gets a new
  Python int or float object (its `sys.getsizeof`, read once at import, not a pinned number); a
  string cell reuses the frame's str object.
- `records(t)`: the reader's list of row dicts. Per row, `sys.getsizeof` of a dict with the
  table's column count (read once at import) plus 8 for the list slot; per cell, the Python
  object (57 plus width for a string, the int or float object size otherwise).

- Ingest: for each source k in order, `I + sum(arrow(j) for j before k) + transient(k)`.
  - CSV: `transient(k) = frame(k) + arrow(k)` (both live during `from_pandas`).
  - fixed_width: `max(records(k) + refs(k), frame(k) + arrow(k))`. The records and the new
    frame are live together inside `pd.DataFrame.from_records`, and the frame's string columns
    point at the records' str objects; the records are freed when the reader returns, before
    `from_pandas` builds the Arrow table.
  - Parquet: `arrow(k)` plus the largest row group's `total_byte_size` from the footer.
  - The ingest peak is the largest of these.
- Execute: the existing `estimate_peak_bytes(working_specs, route)`, where each column's working
  spec is the larger of its input spec and its output spec (section 4.2a), plus a resident-input
  term that does not repeat what TB-4 already measured (G2):
  - `full_frame`: nothing added; TB-4 held every input.
  - `sequential`: `sum(arrow(inputs)) - max(arrow(inputs))`. TB-4 held one input at a time, so the
    measured peak already holds the largest input's Arrow table (the two largest tables in the
    sequential basis are their pandas working set, a different copy). The rest are the extra
    tables the CLI holds.
  - `out_of_core`: `sum(arrow(inputs))`; TB-4 held none.
  - A mask table that declares transforms adds one `arrow(t)`: `transform_resolved_source`
    builds a new table beside the resident one.
- Write: `I + sum(arrow(inputs)) + sum(arrow(outputs)) + transient_out(t*)`, where outputs are
  priced with the output specs (section 4.2a) and `t*` is the output with the largest transient;
  `frame`, `refs`, `lists` and `int_cols` of an output read its output specs:
  - CSV target: `frame(t)`.
  - fixed_width target: `max(coerce_moment(t), list_moment(t))`, the larger of the two moments in
    G3 (the Arrow output is already in the sum).
    - `coerce_moment(t) = frame(t) + refs(t) + converted(t) + max over c in int_cols(t) of coerce(c)`,
      where `converted(t) = sum over c in int_cols(t) of rows * max(0, 9 - refs_cell(c))`. Each
      column already coerced stays in the copy as `Int64` (9 bytes a row, `_targets.py:355`)
      while later columns are coerced, and `refs` still prices it at its original cell cost, so
      the positive difference is added for every int column (the column being coerced is counted
      too, which only over-prices). During
      `_coerce_int_columns` (CLI `_targets.py:316-355`) the original frame costs `frame`, the
      copy `refs`, and the column being coerced builds a Python list of ints and then an `Int64`
      series from it (`_targets.py:273-293`, `:316-321`), both live while the series is built:
      `coerce(c) = rows * (8 + int_object + 9)` (a list slot, one int object sized with
      `sys.getsizeof` at import, and the `Int64` value plus its mask byte). Coercion is one
      column at a time, so only the largest such column is added. `int_cols(t)` is the set of
      columns the target layout types `int` whose priced type is not already an integer type
      (`_coerce_int_columns` enters coercion only for float and object dtypes; an integer column
      is left as it is and is covered by `refs`). A float column takes `astype("Int64")`, which
      the generic `coerce(c)` term over-prices; that is accepted as the conservative side.
    - `list_moment(t) = frame(t) + lists(t)`, where `lists` prices every column in `int_cols(t)`
      as a list slot plus an int object, whatever its input spec, because the engine writer's
      `.tolist()` (`_fixed_width_writer.py:310`) turns the `Int64` column into Python ints. The
      other columns keep the cell costs above. `frame(t)` still prices those columns with the
      input spec; that over-prices a coerced string column (its strings are freed with the
      original frame) and is accepted as the conservative side.
    - The int-column set comes from the fixed_width target layout in the pipeline config, read by
      the same loader the CLI uses; a layout that cannot be read leaves the write term unpriced
      with a note (one of the constant note texts, AT-E1-21).
  - Parquet target: 0.
- Lifecycle peak is the largest phase peak; the limiting phase is its token. Ties go to the
  earlier phase.

### 4.2a Output specs and the execute term (revision 5, after the 84-E1 calibration)

What the build measured (`docs/records/2026-11-17-f24-lifecycle-calibration.md`, head
`b1213e83a`): AT-E1-19 came in at 0.46 (1M) and 0.32 (3M) and AT-E1-23 at 0.96 and 0.95. No
constant was tuned (FM-12). Both fixtures mask int64 columns with strategies that write strings:
AT-E1-19 hashes the int64 keys (`hash`) and redacts the int64 payload (`redact`); AT-E1-23 redacts
six int64 columns. The TB-4 shapes the slopes come from masked their numeric columns with
`passthrough` (`scripts/tb4_calibration.py:196-202`, `:234`), so in TB-4 an output cell has the
input cell's type and cost. The revision 4 basis priced every column at its input spec, which is
right only under that condition.

What the sequential route holds (AT-E1-19, three tables P 0.2N, C 0.4N, G 0.4N rows, read from
`execution/_sequential.py:225-580` and `execution/_pandas_adapter.py:355-666`):

- The frame is pandas. `hash` writes one 64-character hex token per cell, `derive(...).hex()`
  (`kernel/_scalar.py:57`; the native sequential hash returns the same tokens as a Python list,
  `_sequential_native.py:302`), so a masked key cell is a pointer plus a Python str: 8 + 49 + 64
  bytes, the `raw_data_bytes` cost `57 + 64`. `redact` takes `redact_array(...).to_pylist()`
  (`_strategies/_redact.py:46-47`), one new Python str per cell: `57 + 8` bytes.
- The parent key map (`_parent_map`, `_pandas_adapter.py:596`) maps a 1-tuple of the source key
  to a 1-tuple of the masked token, and is kept until the last child that references it is done
  (`_sequential.py:580-589`). After the parent frame is evicted the map holds the only reference
  to the tokens.
- With no sink, every masked table is kept as Arrow in `outputs` (`_sequential.py:564`): 68 bytes
  a token cell (64 data plus a 4-byte offset), 12 bytes a redacted cell.

At N = 1M the largest live set is when the grandchild table is converted to Arrow: caller-held
inputs 22.4 MB, outputs P and C 75.2 MB, the C key map about 123 MB (400k keys: a dict slot near
52 bytes, two 48-byte tuples, a 32-byte int, a 128-byte token after pymalloc rounding), the G
frame about 86 MB (tokens, pointers into the map's tokens, redacted strs) and the G output 59.2
MB: about 372 MB a million rows. The measured slope is (1435 - 625) / 2 = 405 MiB, about 425 MB a
million rows. The rest is transients freed before that moment but still held by the allocators
(the FK resolve lists of 40 to 56 bytes a row, the hash and redact intermediates), which a bare
liveness sum cannot see. That is why the term keeps the measured TB-4 slope and corrects its
basis, instead of replacing the slope with a liveness sum. The revision 4 basis was the two
largest tables at input width, 19.2 MB a million rows; it does not contain the token and str
cells at all, which is the whole of the miss.

What the full_frame cell shows (AT-E1-23): the measured slope is 198 MiB a million rows, about
208 bytes a row for six cells. The pandas path would hold at least 6 x 65 = 390 bytes a row of
redacted strs, so this run kept the outputs in Arrow (12 bytes a cell): the native unified slice
(`execution/_pipeline_full_frame.py`, `maybe_run_unified_slice`). The revision 4 term priced 4.0
x 48 = 192 bytes a row on the inputs alone; the 72 bytes a row of new Arrow strings were not in
it. The estimate cannot know before the run whether the unified slice admits the plan, and when
it declines, the pandas route holds the str cells; so the estimate prices the pandas form, the
same over-predict-by-design rule as FM-6 (FM-14).

The rule:

- The output cell is a fact of the strategy handler, so the handler declares it (one place, owned
  by the code that writes the cell). Two optional members on a scalar handler, read by the
  lifecycle through `SCALAR_HANDLERS[strategy]` (`execution/_strategies/__init__.py:48`) with
  `getattr` defaults, so a handler that declares nothing is "unknown":
  - `output_is_input: bool` (default False). True on `PassthroughHandler` only: its `run`
    returns the frame unchanged (`_strategies/_passthrough.py:31`).
  - `output_string_width(provider_config) -> int | None`: the UTF-8 width of every non-null cell
    the handler writes, or None when the config makes it unknown (a `redact_with` that is not a
    str), which the lifecycle treats as a handler that declares nothing. `HashStrategyHandler`: the hex length of the HMAC-SHA256 digest `derive` returns
    (64), capped at `truncate` when it is a positive int (the kernel slices the token). `RedactHandler`: the UTF-8 length of
    `redact_with`, default `_DEFAULT_REDACT_WITH`. Each handler moves its config parsing (the
    `truncate` test at `_strategies/_hash.py:56-57`, the `redact_with` lookup at
    `_strategies/_redact.py:43`) into one module function that both `run` and
    `output_string_width` call, so the declaration and the behavior read the same value.
  - A guard test (AT-E1-30) runs each declaring handler on a small int64 frame and asserts every
    non-null output cell has the declared width, so the declaration cannot drift from `run`.
  - The lifecycle holds no strategy names or widths of its own; AT-E1-30 also checks that
    `_lifecycle_inputs.py` and `_lifecycle.py` contain no strategy-name literal.
- Each mask column gets an output spec from its compiled plan seed (`ColumnSeed.strategy` and
  `provider_config` through `provider_config_to_dict`, the values the handlers read):
  - A handler with `output_is_input`, and a column the plan leaves unconfigured: the input spec.
  - A handler with `output_string_width`: a string of that width.
  - An FK child column (an edge in the relationship graph names it): the output spec of the parent
    key column, because `_resolve_fk_node` writes the parent's masked values into the child.
  - A handler that declares neither: a string input keeps its input spec (the revision 4 rule, V2-LOG); a
    non-string input leaves the lifecycle unpriced with `NOTE_OUTPUT_WIDTH` naming `table.column`
    (FM-13). Never a guessed width.
  - The output keeps the input's null flag (`hash` and `redact` keep nulls).
- The working spec of a column is whichever of its input and output specs has the larger
  `raw_data_bytes` per cell.
- Execute: `estimate_peak_bytes(working_specs, route)` with the TB-4 slopes and intercepts
  unchanged. On sequential the two-largest-tables basis is taken over the working specs, so the
  key-map tokens and str cells the route holds are in the basis. The resident-input term and the
  transform copy keep the input specs (they are the caller's input tables).
- Write: outputs are priced with their output specs (section 4.2).
- Ingest keeps the input specs. `peak_bytes` and the route keep the input specs: `peak_bytes` is
  the router's own model (section 4.5), and the router must not see sampled or output widths
  (AT-E1-12).

Checked against the calibration (arithmetic from the record's row counts; MiB as the record
prints them):

| Cell | Rows | Revision 4 predicted | Revision 5 predicted | Measured | Revision 5 ratio |
|---|---|---|---|---|---|
| AT-E1-19 | 1M | 285 | 1149 | 625 | 1.84 |
| AT-E1-19 | 3M | 456 | 3047 | 1435 | 2.12 |
| AT-E1-23 | 1M | 383 | 1688 | 397 | 4.25 |
| AT-E1-23 | 3M | 749 | 4663 | 793 | 5.88 |

The revision 4 column reproduces the record's predictions exactly, so the arithmetic matches the
build. On AT-E1-19 the corrected data term is 4.0 x 245.6 MB = 982 MB a million rows, against the
372 MB liveness tally and the 425 MB measured slope. Every other cell's basis can only grow (a
working spec is never smaller than the input spec), so no cell that passed its lower bound can
fail it; AT-E1-27 masks with `passthrough` only and is unchanged (1.13 and 1.24). AT-E1-19 and
AT-E1-23 are string-output cells and move to the lower bound only (section 8.3). Why this is the
right term and not a fit: no constant changes; the slope stays the TB-4 measured value; the only
change is that the basis prices the cells the route holds after the strategy runs, read from the
strategy code, which is the condition under which TB-4 measured the slope.

### 4.3 Generate and mixed jobs (84-E2)

- E2 calls `classify_plan` (`generation/_admission.py:169`) once and prices the generated tables
  with a payload-aware form of `_floor_by_table` (`generation/_bounds.py:315`): the same loop,
  given a width per column, so the floor and the lifecycle share one walk over the plan.
  - An eligible column is priced as `arrow_column_bytes(arrow_type, rows, width)`. The width comes
    from `table_size_spec_from_generate_table` (`_mem_estimate_schema.py:250`) or from
    `faker_payload_bound` (`generation/_bounds.py:104`).
  - When the plan runs the legacy whole-table path (any declined column), each cell is priced as a
    Python object: a list slot plus the object (57 plus width for a string, the CPython size of
    an int or float otherwise).
  - A column with no width source keeps the lifecycle unpriced with a note.
- The function is exported through `decoy_engine.generation` (lazy import, like
  `resident_floor_shortfall` at `generation/__init__.py:29`); execution code never imports
  `generation._bounds` directly.
- Execute for a generate-only job: `I + sum(resident generated bytes) + largest unique working
  set` (`table_unique_peak`, `generation/_bounds.py:271`). No ingest phase: its token is
  reported with 0 bytes.
- Mixed job: execute is the mask route's execute term plus the generated bytes; ingest covers the
  mask sources; write covers every output.
- The existing fields keep their values: generate-only `peak_bytes` stays `None`; a mixed job stays
  `priceable=False` with its note. Only the new fields are filled.

### 4.4 Result fields (84-E1)

`JobEstimate` gains three fields, all with defaults, appended after `notes`:

- `lifecycle_peak_bytes: int | None = None`
- `limiting_phase: Literal["ingest", "execute", "write"] | None = None`
- `phase_bytes: tuple[tuple[str, int], ...] = ()`, in the fixed order ingest, execute, write.

When any table is unpriceable the three stay at their defaults and `notes` says why. When any
profiled row count is an estimate (CSV), `notes` gains "row counts estimated from file size".

Every note text the lifecycle adds is a constant in one block in `_lifecycle.py`, with a
placeholder only for a table or column name or an exception type name. A shape test pins the set
(AT-E1-21). Revision 5 adds one constant, `NOTE_OUTPUT_WIDTH` ("lifecycle not priced: output
width of column {table} unknown", filled with `table.column`, FM-13).

### 4.5 Value changes on existing fields (84-E1)

With sampled widths (OQ-5), a mask job with string columns that was unpriceable now gets:

- `priceable`: `False` becomes `True`.
- `peak_bytes`: `None` becomes a number (meaning unchanged: the execute phase).
- `runtime`: `None` becomes a band, because the runtime band is computed for priceable jobs.

All three are named in section 12 and in the changelog fragment. The merged cell that pinned the
old answer changes as listed in AT-E1-9.

`peak_bytes` stays the router's TB-4 model on input specs; output specs (section 4.2a) feed only
the lifecycle phases. A job whose strategies turn numbers into strings therefore has a lifecycle
execute phase above `peak_bytes`; the docstring and the docs section say which number is which.

## 5. Failure modes

| Id | Failure | Handling |
|---|---|---|
| FM-1 | Sample read fails (corrupt file, permission) | Lifecycle unpriced; note names the table and `type(exc).__name__`; the outer `estimate_job` try still holds |
| FM-2 | Exception text carries a cell value or a path | Never formatted; only the type name (the existing `_job_estimate.py:95` rule) |
| FM-3 | Column type with no size model (dictionary, list, struct) | Lifecycle unpriced; note names `table.column` |
| FM-4 | CSV row count is an estimate | Priced; note says so; the accuracy cells include CSV fixtures so the error is measured |
| FM-5 | Non-ASCII strings: CPython holds them as 1, 2 or 4 bytes per character with a larger header, which can differ from the UTF-8 width | Known error for wide-character text; one accuracy cell uses Latin-1 text and asserts the lower bound; documented; V2-LOG for a width per encoding kind |
| FM-6 | Realized route differs from the predicted route (native auto-chunk) | Lower bound asserted only; the cell records both routes |
| FM-7 | A sample shows no nulls but the file has them | Parquet: the null flag comes from the footer through `column_arrow_types`, so this cannot happen. CSV: the validity bit is missed (at most 1 bit per row); documented |
| FM-8 | Head-of-file sample bias: the first 10,000 rows are narrower than the rest (a file sorted by a width-related key, or a header block of short rows) | Under-price possible. Documented in the docstring and docs; the lower-bound cells use files whose widths are uniform, so this is not measured; V2-LOG for a spread sample (Parquet row groups across the file) |
| FM-9 | A string column is all null in the sample | Unpriced with a note naming it; never priced as width 0 |
| FM-10 | Very wide config (thousands of columns) | Sample read is bounded in rows, not columns or bytes; same cost class as the existing profile read |
| FM-11 | A format added to `FILE_FORMATS` without a lifecycle rule | Guard test fails (AT-E1-20); at run time the lifecycle is unpriced with a note |
| FM-12 | A builder tunes a constant to make a cell green | Forbidden: no new constant without a measured record; a cell outside its bound stops the slice and goes back to the plan (this happened on 84-E1; revision 5 is the plan answer) |
| FM-13 | A strategy other than `passthrough`, `hash` or `redact` masks a non-string column, so its output width is unknown | Lifecycle unpriced; `NOTE_OUTPUT_WIDTH` names `table.column`; never priced at the input width. A string column under such a strategy keeps its input width (documented; V2-LOG per-strategy output specs) |
| FM-14 | The native unified slice keeps string outputs in Arrow, so the run holds less than the pandas form the estimate prices | Over-prediction by design (as FM-6); string-output cells assert the lower bound only; AT-E1-23 records the gap (about 4 to 6 times); V2-LOG native-aware term |

## 6. Design notes and choke points

- New structure: two modules in E1 and one in E2, all in `execution/pipeline/`, plus one shared
  helper in the bottom-tier `_arrow_types.py`. No new public type: three fields on the existing
  public `JobEstimate`. The root facade (`src/decoy_engine/__init__.py`, 599 lines) is not
  touched.
- Principle: single responsibility. The arithmetic stays I/O-free (like `_mem_estimate`), so the
  unit cells run without files; the input module is the only one that opens a file.
- One place per fact:
  - Arrow bytes per column: `arrow_column_bytes(arrow_type, rows, width)` in
    `src/decoy_engine/_arrow_types.py` (49 lines, imports only pyarrow). `_arrow_column_floor`
    in `generation/_bounds.py:306` becomes a call to it with width 0. Behavior is unchanged
    there, and a snapshot cell pins it (AT-E1-22).
  - Arrow type and null flag per column: `column_arrow_types`.
  - Pandas cost: `raw_data_bytes`. Intercept: `route_intercept_bytes`.
  - Widths: `_mask_specs` or the generate adapters.
  - Format names: `FILE_FORMATS` keys.
  - Note texts: one constants block.
  - Output cells (section 4.2a): declared by the strategy handler that writes them
    (`output_is_input`, `output_string_width`), checked against `run` by AT-E1-30. The lifecycle
    only reads the declaration; it holds no strategy name or width.
- No private reach across packages: execution code imports generation only through
  `decoy_engine.generation` (catalog class 6). The guard test may read `FILE_FORMATS` from its
  private module; production code keys on the literal format names, and the guard pins them equal.
- House style: a frozen `PhaseInputs` context object passed to the phase function, no flag
  arguments, comments that say why.
- Placement call (Dennis L3): the new modules go in the existing `execution/pipeline/`
  sub-package, not a new `execution/estimate/`. A new package now would hold only the new files
  while `_mem_estimate*`, `_job_estimate.py` and `_throughput_calibration.py` stay flat, so the
  estimate code would sit in three places until a move that touches every importer. That move is
  V2-LOG, and it takes the new modules with it.
- Choke point: N/A as a cross-cutting rule. The row adds no rule other call sites must follow;
  `estimate_job` is the one entry and the only caller of the new modules. The format rule table is
  a one-site registry with a completeness guard (AT-E1-20).

## 7. Value-free rules

- Never in any field or note: a cell value, a sampled value, a file path, exception text.
- Allowed: table and column names from the config, byte counts, row counts, phase tokens, route
  tokens, exception type names.
- No log line is added.

## 8. Acceptance tests (red first)

Each test is written first and must fail on the base head for the reason given. Named mutations
belong to unit cells; accuracy cells assert bounds only. A builder may add tests; none of these
may be weakened. Unit cells run in the default loop through `vm-run` or the Mac, never on the
devbox. Accuracy cells are `benchmark`-marked and run on a test VM through `~/bin/vm-run`.

### 8.1 84-E1, unit (`tests/unit/execution/pipeline/test_lifecycle.py`, `tests/unit/execution/test_job_estimate.py`, `tests/unit/test_arrow_types.py`)

| Id | Test | Fails before | Named mutation |
|---|---|---|---|
| AT-E1-1 | Two CSV specs A then B: ingest peak equals `I + arrow(A) + frame(B) + arrow(B)` when B is larger, and `I + frame(A) + arrow(A)` when A is larger | module does not exist | drop the earlier tables' `arrow` from the live sum |
| AT-E1-2 | Parquet spec: ingest transient is `arrow + largest row group bytes`, not `frame + arrow`; fixed_width transient is `max(records + refs, frame + arrow)` | module does not exist | price Parquet like CSV |
| AT-E1-3 | Execute input term: full_frame adds 0 (equals `estimate_peak_bytes` on the working specs exactly); sequential adds `sum - max` of input Arrow; out_of_core adds the sum; with only `passthrough` columns the working specs equal the input specs | module does not exist | add the full sum on sequential |
| AT-E1-4 | Write: CSV target adds `frame` of the largest output; Parquet target adds 0 | module does not exist | use the smallest output |
| AT-E1-5 | `lifecycle_peak_bytes == max(phase_bytes)` and `limiting_phase` names it; ties pick the earlier phase | module does not exist | return the last phase on a tie |
| AT-E1-6 | A CSV mask job over real files: `lifecycle_peak_bytes` set, `phase_bytes` in order ingest, execute, write, note "row counts estimated" present | field does not exist | omit the estimated-rows note |
| AT-E1-7 | A Parquet source with a dictionary-encoded column: lifecycle fields at defaults, note names `t.col`, no raise (`classify_column` returns `Unpriceable` for it, `_mem_estimate_arrow.py:184`). A `list<int64>` column never reaches pricing: the profiler raises first and `estimate_job` reports route "unknown"; a separate cell asserts that it does not raise (revision 5, accepted builder divergence) | field does not exist | price an unpriceable column at 0 |
| AT-E1-8 | Sample bounded: a 30,000-row CSV and Parquet source; patched readers record `nrows <= 10_000` and the Parquet batch size; `to_frame` never called | sample read does not exist | read the whole file for the sample |
| AT-E1-9 | Edit list for merged cells in `tests/unit/execution/test_job_estimate.py`: `test_string_without_sample_is_unpriceable_not_a_raise` (`:55`) becomes "a string mask job is priced from a bounded sample" (priceable True, `peak_bytes` set, `runtime` set); its unpriceable check moves to AT-E1-7. No other merged cell is edited | merged cell asserts the old answer | keep `_mask_specs(mask_tables, {})` |
| AT-E1-10 | Value-free: a CSV whose cells hold a seeded marker and a source path holding a second marker; a reader patched to raise `ValueError(marker)`; neither marker appears in `repr(est)` or any note; the raise case gives a note with `ValueError` only | sample read does not exist | format `str(exc)` into the note |
| AT-E1-11 | Never raises: every new-module function patched in turn to raise `RuntimeError`; `estimate_job` returns a `JobEstimate` whose `route`, `priceable`, `peak_bytes` and `runtime` equal the result with the lifecycle code patched out, lifecycle fields at defaults, and a note holding `RuntimeError` only | fields do not exist | let a lifecycle error escape the outer try |
| AT-E1-12 | No route change: for the merged fixtures, `est.route` equals its value with the lifecycle code patched out | fields do not exist | take the route from the lifecycle stage instead of the router (revision 5: the builder's mutation; sampled widths never reach `decide_execution_route` because the route is decided before the sample is read) |
| AT-E1-13 | Sentries pass with no raised cap: fan-out (`execution/` stays at the sentry's 103, `execution/pipeline/` under 25), module size, import layers with no new ignore line, the physical-seam permit set and the declaration-gate `READERS` holding exactly the rows in section 9 | guard | add an ignore line |
| AT-E1-14 | All-null sample column: a CSV string column empty in its first 10,000 rows gives lifecycle defaults and a note naming it | sample read does not exist | price the column at width 0 |
| AT-E1-15 | Column types come from the sample schema: a Parquet `int32` column with nulls is priced at its Arrow width plus validity, not as a pandas float | sample read does not exist | price every non-string column at 8 bytes |
| AT-E1-16 | Transforms: a mask table with a declared transform adds one `arrow(t)` to execute | module does not exist | drop the transform copy |
| AT-E1-20 | Format registry: the lifecycle rule table's keys equal `FILE_FORMATS` keys; a descriptor with an unknown format gives lifecycle defaults and a note | rule table does not exist | remove `fixed_width` from the rule table |
| AT-E1-21 | Note shapes: every lifecycle note matches one of the constants in the notes block after its placeholder is filled; the set of constants is pinned (it includes `NOTE_OUTPUT_WIDTH`) | notes block does not exist | build a note with an inline f-string |
| AT-E1-29 | Output specs (section 4.2a): an int64 column under `hash` is priced in execute and write as a string of width 64, and of width `truncate` when set; under `redact` as a string of `len(redact_with)` (default from `_DEFAULT_REDACT_WITH`); under `passthrough` with its input spec; an FK child column takes its parent key column's output spec; an int64 column under a strategy whose handler declares neither member (`bucketize`) leaves the lifecycle at defaults with `NOTE_OUTPUT_WIDTH`; on sequential the basis is the two largest tables over working specs; `peak_bytes` and `route` equal their values with output specs off | output specs do not exist | (a) price execute with the input specs; (b) ignore `truncate`; (c) price an unknown-strategy int64 column at its input spec; (d) feed output specs into `peak_bytes` |
| AT-E1-30 | Handler output declarations: `HashStrategyHandler` (default, `truncate=12`, `truncate=100`) and `RedactHandler` (default, `redact_with="XX"`, `redact_with="é"`) run on a small int64 frame with a null; every non-null output cell's UTF-8 length equals `output_string_width(provider_config)`; `PassthroughHandler` returns the frame unchanged and declares `output_is_input`; no other handler in `SCALAR_HANDLERS` declares either member without a parity case here; `_lifecycle.py` and `_lifecycle_inputs.py` hold no string literal equal to a `SCALAR_HANDLERS` key (AST scan) | members do not exist | (a) return 64 from the hash declaration whatever `truncate` is; (b) count characters, not UTF-8 bytes, in the redact declaration; (c) put a `"hash"` literal back in `_lifecycle_inputs.py` |
| AT-E1-26 | Fixed-width write: a fixed_width target with one string and one int column (the int column already integer-typed) adds exactly `max(coerce_moment, list_moment)` as section 4.2 defines it (not the summed form, not `frame` alone); `lists` gives the int column an int object per cell and the string column a slot only; a CSV target of the same table adds `frame` only | module does not exist | sum the two moments instead of taking the larger |
| AT-E1-28 | Fixed-width integer coercion: a CSV-sourced string column the target layout types `int` adds `coerce(c) = rows * (8 + int_object + 9)` to the coerce moment for the largest such column only, and `lists` prices it as an int object per cell, not as its input string spec; an integer-typed column adds no coerce term; with two int-declared string columns the coerce moment adds `converted` for both (the first column stays resident as `Int64` while the second is coerced); an unreadable layout leaves the write term unpriced with the constant note | module does not exist | (a) drop the `coerce(c)` term; (b) price `int_cols` lists with the input spec; (c) add `coerce` for every int column instead of the largest; (d) drop `converted` |
| AT-E1-22 | Helper parity: `arrow_column_bytes(t, rows, 0)` equals the base head's `_arrow_column_floor(t, rows)` for a matrix of types (bool, int8 to int64, float32/64, string, large_string, timestamp, date32); `generation_floor_bytes` is unchanged on the merged generation fixtures | helper does not exist | drop the ceil division for bool |

### 8.2 84-E1, accuracy (`tests/perf/test_f24_lifecycle_accuracy.py`, `benchmark` marker, test VM only)

The worker (`scripts/fk-scale/bench_worker_lifecycle.py`) does in one child process what the CLI
does: read every source through the engine readers in config order, hold them, call
`run_pipeline` with the resident tables, write every target (CSV through
`generated_table_to_pandas` then `to_csv`, Parquet through `pq.write_table`), and record the
realized route. It passes `run_pipeline` the same keyword set the CLI passes at
`decoy/cli/run/_execute.py:354` that changes memory: resource limits (as the CLI's `_resources`
helper builds them, with defaults) and the native gate result. It does not pass the vault writer,
quarantine path or report flags (out of scope, section 2), and the record says so. The supervisor
(`scripts/fk-scale/_supervisor.py:65`) reads `ru_maxrss` from outside. The fixture files are
written by a separate process before the measured child starts (accepted builder divergence,
revision 5), so fixture construction never reaches the measured peak.

Open on the 84-E1 rerun: the calibration record says the worker passes neither the resource
limits nor the native gate result. The paragraph above requires both. The rerun passes them, or
the orchestrator records the divergence and its reason before the gate.

Every cell asserts `measured <= predicted`. A cell marked "bounded" in 8.3 also asserts
`predicted <= 1.5 * measured` when the realized route equals the predicted route and rows are at
least 1,000,000. Accuracy cells carry no named mutation; the arithmetic they rest on is pinned by
the unit cells above.

| Id | Fixture (1M and 3M rows) | Class | Bound |
|---|---|---|---|
| AT-E1-17 | CSV, one table, 6 unique ASCII string columns, `redact` (pandas route) | string, execute | lower |
| AT-E1-18 | CSV, three tables, FK chain, string keys and attributes, sequential route | string, execute | lower |
| AT-E1-19 | Parquet, numeric FK chain of three tables (P 0.2N, C 0.4N, G 0.4N rows), int64 keys under `hash`, int64 payload under `redact`; the router picks sequential at 1M and 3M (revision 4 assumed out_of_core); CSV targets | string output (numbers turned into strings), execute | lower |
| AT-E1-23 | Parquet, one table of 6 int64 columns under `redact`, full_frame, Parquet target | string output, execute (native slice at run time, FM-14) | lower |
| AT-E1-24 | CSV with Latin-1 text (FM-5) | string, execute | lower |
| AT-E1-25 | CSV, single table, `hash` (native auto-chunk eligible, FM-6) | realized route may differ | lower |
| AT-E1-27 | Parquet, one table of 4 int and 2 short string columns, all `passthrough`, full_frame, fixed_width target | type-preserving numeric-led; execute-limited as measured | bounded (bound check only; it does not separate the old and new write formulas, AT-E1-26 does) |

### 8.3 Expected ratios from TB-4 (execute term; predicted over measured)

Predicted is `I + basis * slope` with the pinned slopes (4.0 in-core, 1.5 out_of_core); measured
is the TB-4 peak for the nearest shape. Values at 3M are extrapolated with the measured two-point
slope.

| Fixture | Nearest TB-4 shape and route | Rows | Expected ratio | Bound set |
|---|---|---|---|---|
| AT-E1-17, AT-E1-24 | unique_single, full_frame (slope 2.43) | 1M / 2M / 3M | 1.36 / 1.45 / about 1.50 | lower only |
| AT-E1-18 | pooled_fk, sequential (slope 1.65) | 400k / 800k | 2.00 / 2.17 | lower only |
| (pooled string on full_frame, for reference) | pooled_fk, full_frame (slope 2.11) | 800k | 1.79 | lower only |
| AT-E1-19 | none: TB-4 has no string-output numeric shape; sequential, working-spec basis (section 4.2a) | 1M / 3M | 1.84 / 2.12 (computed from the calibration record) | lower only |
| AT-E1-23 | none: string output on the native slice (FM-14); full_frame, working-spec basis | 1M / 3M | 4.25 / 5.88 (computed from the calibration record) | lower only |
| AT-E1-25 | native route, not in TB-4 | any | unknown | lower only |
| AT-E1-27 | numeric_single, full_frame, plus the fixed-width write term `max(coerce_moment, list_moment)` (section 4.2) | 1M / 3M | measured 1.13 / 1.24, execute-limited (unchanged by revision 5: `passthrough` only) | 1.5 (type-preserving numeric-led) |

The ingest and write terms are direct sums with no slope, so a cell whose predicted limiting phase
is ingest or write also takes the 1.5 bound. The cell asserts its bound from the phase the model
predicts at run time, and all cells record the predicted and measured phase peaks.

Revision 5 corrections from the 84-E1 calibration record (head `b1213e83a`):

- Revision 4 expected AT-E1-27 to be write-limited. It was not: the execute term prices the two
  string columns at `4.0 * (57 + width)` a cell, which outweighs the int cells' write cost; the
  model put execute at 794 and 1983 MiB against write at 596 and 1388. The measured peak (701 and
  1605) lies between the two, and `ru_maxrss` is one number for the whole process, so the cell
  cannot show which phase set it; it checks the lifecycle peak only. The fixed-width write formula
  stays pinned by the unit cells AT-E1-26 and AT-E1-28.
- AT-E1-19 runs on sequential, not out_of_core, so no accuracy cell checks the out_of_core
  resident-input term with a matching route (AT-E1-18 realized out_of_core against a predicted
  sequential, FM-6). AT-E1-3 pins that term's arithmetic.
- Measured ratios of the string cells before revision 5: AT-E1-17 2.99 / 3.76, AT-E1-24 1.78 /
  1.95, AT-E1-18 1.50 / 1.97, AT-E1-25 1.09 / 1.26. Revision 5 leaves AT-E1-17 and AT-E1-24 as
  they are (redact width 8 is not above their input width) and raises AT-E1-18 and AT-E1-25 (hash
  width 64). The rerun records the new values.

### 8.4 84-E2 (`tests/unit/execution/pipeline/test_lifecycle_generate.py`, accuracy cells in the same perf file)

| Id | Test | Fails before | Named mutation |
|---|---|---|---|
| AT-E2-1 | Generate-only, `sequence` plus `faker` email: execute equals `I + resident generated bytes + unique peak`; ingest phase 0; `peak_bytes` still `None` | generate lifecycle does not exist | sum unique working sets across columns |
| AT-E2-2 | A generate column with no width source (`formula`): lifecycle unpriced, note names it | as above | price it at 0 |
| AT-E2-3 | Mixed job: execute is the mask execute term plus generated bytes; `priceable` stays False and its "mixed" note stays | as above | drop the generated term |
| AT-E2-4 | Legacy path: a plan with a declined column prices every cell as an object (slot plus object), not as Arrow | as above | price the legacy path as Arrow |
| AT-E2-5 | Floor unchanged: `generation_floor_bytes` on the merged fixtures equals the base head after the payload-aware refactor | refactor does not exist | add the payload to the floor |
| AT-E2-6 | Accuracy (VM, lower bound only; no TB-4 anchor for generation): generate-only 3M rows to CSV; mixed 1M mask plus 1M generate to Parquet; the measured ratio goes in the record | as above | none (bounds only) |
| AT-E2-7 | Docs: `docs/execution-backends.md` estimate section names the three phases, the resident-handoff assumption, the unpriced items in section 2 and the sample bias; frozen-surface sentence matches | doc missing | omit the assumption sentence |

## 9. Goldens, pins and sentries that move

- One merged test cell changes, listed in AT-E1-9; it follows the new contract and its unpriceable
  check moves to AT-E1-7.
- Sentry registrations. Each row below is the registration the sentry is built to receive: the
  sentry fails on every new site until the site is listed with its reason. Adding a row is not
  raising a cap; each row names one file or one call site.

| Sentry and list | Row added | Reason recorded beside it |
|---|---|---|
| `tests/sentry/test_physical_seam_disconnection.py`, the inline set in `permitted_non_physical` (beside `_job_estimate.py`) | `src/decoy_engine/execution/pipeline/_lifecycle.py` (E1) | lifecycle phase arithmetic for `estimate_job`; imports `_mem_estimate` and `_arrow_types` only, nothing under `execution.physical` |
| same | `src/decoy_engine/execution/pipeline/_lifecycle_inputs.py` (E1) | bounded sample reads and phase inputs for `estimate_job`; imports profile readers and `_mem_estimate*` only, nothing under `execution.physical` |
| same | `src/decoy_engine/execution/pipeline/_lifecycle_generate.py` (E2) | generate and mixed lifecycle terms; imports `decoy_engine.generation` and `_lifecycle` only, nothing under `execution.physical` |
| same | `src/decoy_engine/execution/_strategies/_hash.py` (E1, changed) | declares its output cell (`output_string_width`) and shares its `truncate` parsing with `run`; no physical import (the list already carries other `_strategies/` handlers, such as `_truncate.py`) |
| same | `src/decoy_engine/execution/_strategies/_redact.py` (E1, changed) | declares its output cell and shares its `redact_with` lookup with `run`; no physical import |
| same | `src/decoy_engine/execution/_strategies/_passthrough.py` (E1, changed) | declares `output_is_input`; no physical import |
| `tests/sentry/source_config/test_declaration_gate.py`, `READERS` | `("execution/pipeline/_lifecycle_inputs.py", "_read_csv", "resolve_csv_dialect")` | the estimate's bounded sample read; `estimate_job._estimate` runs `prepare_declared_execution_sources` and `profile_source` (the gate) before `_sample_stage` reaches it |
| same | `("execution/pipeline/_lifecycle_inputs.py", "_read_csv", "read_csv_source")` | same: a sample of at most 10,000 rows, after the gate in `_estimate` |
| same | `("execution/pipeline/_lifecycle_inputs.py", "_read_parquet", "build_lazy_source")` | same: first batch only, after the gate in `_estimate` |
| same | `("execution/pipeline/_lifecycle_inputs.py", "_read_fixed_width", "build_profile_source")` | same: `sample_frame(10_000)`, after the gate in `_estimate` |

  The four `READERS` rows are the reader calls in the 84-E1 diff (`git diff origin/main...HEAD` on
  `feat/f24-84-e1`, `_lifecycle_inputs.py:60-89`); revision 4 missed them. The guarded property of
  each sentry stays checked: the import sweeps still prove no `execution.physical` import, and the
  gate walk still sees every reader. A builder who adds another reader call adds its row the same
  way, or the plan is amended first.
- `src/decoy_engine/profile/_readers.py` `FooterFacts` gains `max_row_group_bytes: int = 0`, a
  defaulted field filled by `footer_facts_of` from the footer's row groups (accepted builder
  divergence, revision 5). `FooterFacts` is not a public or frozen name; existing callers are
  unchanged.
- No cap, ceiling, ratchet, fan-out pin, sentry baseline, determinism golden or `_mem_estimate`
  constant is raised or changed. `execution/` stays at 103 direct modules, the sentry's max in
  `tests/sentry/baselines/package-fanout.json` (the CODEMAP row's "104" is the count when the
  freeze was set); the new files go in the named `execution/pipeline/` sub-package.
- The accuracy tolerance (1.5) and the per-class bound choice are test constants pinned by this
  plan (OQ-4), never widened in a build.

## 10. Placement (checked against `CODEMAP.md:252`, "Pipeline spine and routes")

| Item | Goes in | Map line and neighbor |
|---|---|---|
| Phase arithmetic and notes block | `src/decoy_engine/execution/pipeline/_lifecycle.py` (new) | "new route clusters in ... `execution/pipeline/`"; beside `_host.py` and `_routing_facts.py`; not `execution/` (frozen at 103) |
| Sample reads, format rule table, phase inputs | `src/decoy_engine/execution/pipeline/_lifecycle_inputs.py` (new) | same row; beside `_lifecycle.py` |
| Generate and mixed terms (E2) | `src/decoy_engine/execution/pipeline/_lifecycle_generate.py` (new) | same row; keeps `_lifecycle.py` I/O-free and under 400 lines |
| `arrow_column_bytes` | `src/decoy_engine/_arrow_types.py` (existing, 49 lines) | bottom leaf "shared across layers"; imports only pyarrow |
| Payload-aware generation bytes and export | `src/decoy_engine/generation/_bounds.py`, `src/decoy_engine/generation/__init__.py` | existing generation modules; export follows `resident_floor_shortfall` |
| Result fields and wiring | `src/decoy_engine/execution/_job_estimate.py` | existing module (214 lines, ends near 300) |
| Output specs (revision 5) | `src/decoy_engine/execution/pipeline/_lifecycle_inputs.py` (new in E1) reads them; the declarations sit on the handlers in `src/decoy_engine/execution/_strategies/_hash.py`, `_redact.py`, `_passthrough.py` (existing) | the handler owns the cell it writes; the lifecycle only reads it |
| Largest row group bytes | `src/decoy_engine/profile/_readers.py` `FooterFacts` (existing) | the footer facts owner; one defaulted field |
| Sentry registrations | `tests/sentry/test_physical_seam_disconnection.py`, `tests/sentry/source_config/test_declaration_gate.py` (existing) | the rows in section 9, one per new module or reader site |
| Unit tests | `tests/unit/execution/pipeline/` (new folder), `tests/unit/test_arrow_types.py` | "Unit tests" row: mirror `src/` |
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
| Arrow type and null flag per column | `column_arrow_types` | `src/decoy_engine/execution/_mem_estimate_arrow.py:254` |
| Specs and widths from samples | `_mask_specs`, `sample_average_string_bytes` | `src/decoy_engine/execution/_pipeline_routing_samples.py:22`, `src/decoy_engine/execution/_mem_estimate_schema.py:50` |
| Arrow column bytes | the rule of `_arrow_column_floor`, moved to one helper | `src/decoy_engine/generation/_bounds.py:306` |
| Format names | `FILE_FORMATS` keys | `src/decoy_engine/profile/_lazy_build.py:118` |
| Generate plan, widths and unique sets | `classify_plan`, `_floor_by_table`, `table_size_spec_from_generate_table`, `faker_payload_bound`, `table_unique_peak` | `src/decoy_engine/generation/_admission.py:169`, `src/decoy_engine/generation/_bounds.py:315`, `src/decoy_engine/execution/_mem_estimate_schema.py:250`, `src/decoy_engine/generation/_bounds.py:104`, `:271` |
| CSV read as the CLI reads | `read_csv_source` | `src/decoy_engine/profile/_csv_reader.py:514` |
| Parquet and fixed_width readers | `build_lazy_source`, `build_profile_source` | `src/decoy_engine/profile/_lazy_build.py:131`, `src/decoy_engine/profile/_readers.py:493` |
| Peak measurement | `run_worker` supervisor | `scripts/fk-scale/_supervisor.py:65` |

## 12. Frozen contracts touched

All additive.

- `JobEstimate` (Execution row of `docs/frozen-surfaces.md`, contract 3.4) gains three defaulted
  fields. The row pins the name, not the fields; the frozen-surface page gets one sentence naming
  the fields.
- Value changes for a mask job with string columns that was unpriceable (G4, section 4.5):
  `priceable` False to True, `peak_bytes` None to a number, `runtime` None to a band. Meanings are
  unchanged. Pre-GA. No CLI caller (checked: CLI `origin/main` has no `estimate_job` call). All
  three are named in the changelog fragment.
- Platform follow-up (platform parked): the platform's B-10 code keeps a `_KNOWN_NOTE_SHAPES` set
  for `JobEstimate.notes`. At its next engine repin it must add the lifecycle note shapes from the
  notes block, or it will treat them as unknown. Recorded in the platform follow-up list and in the
  changelog fragment.
- No new public name other than the generation export in E2 (a function name added to
  `decoy_engine.generation`, recorded as "Pre-GA additive" in `docs/compatibility-contract.md`).
  No reason code, format tag, schema, exit code or config key. No reason code is added, so nothing
  needs since=UNRELEASED; if a build finds it needs one, it is registered with since=UNRELEASED
  and the plan is amended first.

## 13. Class table

| # | Class | Closing structure | Sentry or property test | Mutation |
|---|---|---|---|---|
| 1 | Value-bearing output | Notes carry names, counts and exception type names only, from one constants block; sample frames dropped after inputs are built | AT-E1-10, AT-E1-21 | format `str(exc)` into a note |
| 2 | Cleanup missing on an exit path | Sample reads go through the file-access handles' context managers; no temp files are created | AT-E1-8, AT-E1-11 | open a Parquet file without closing it on the error path |
| 3 | State and concurrency | Pure functions over frozen inputs; no cache or module global | AT-E1-1 to AT-E1-5 run twice in one process with equal results | memoize inputs in a module global |
| 4 | Route parity and silent fallback | The route comes from the unchanged router call; the lifecycle never feeds routing; native realized routes are asserted lower-bound only, never silently passed | AT-E1-12, AT-E1-25, AT-E1-29 | take the route from the lifecycle stage instead of the router |
| 5 | Referential integrity | N/A: the estimate reads samples and writes nothing; FK shape only selects the route term | N/A, covered by AT-E1-3 for the sequential term | N/A |
| 6 | Untrusted producer | Source files are user data: bounded sample, typed classifier, unpriced on any unknown type or format, never raises | AT-E1-7, AT-E1-8, AT-E1-11, AT-E1-20 | price an unknown type at 0 |
| 7 | Check then use on a path (TOCTOU) | The estimate is advisory and reads each file once for its sample; a file that changes before the run only makes the estimate stale, which the docs state | AT-E1-8 | re-open the file after the stat for the sample |
| 8 | Weak tests and overclaimed evidence | Red-first unit cells with named mutations; accuracy cells on VMs with a bound chosen per class from TB-4 (8.3), so no cell is set up to fail or to pass by slack; realized route recorded | AT-E1-17 to AT-E1-25, AT-E2-6 | widen the tolerance to 3.0 |
| 9 | Behavior-preserving refactor drift | `_arrow_column_floor` becomes a call to the shared helper and `_floor_by_table` gains a width input; both pinned to base-head values; one merged cell edit listed in AT-E1-9 | AT-E1-22, AT-E2-5, AT-E1-9 | drop the ceil division for bool |
| 10 | Frozen contract drift | Additive defaulted fields; frozen-surface sentence; changelog names the three value changes | `tests/sentry/release/test_frozen_surface_map.py`, `tests/unit/test_public_api.py` | rename `peak_bytes` |

Recurring-defects catalog classes, as they apply to this plan:

1. Anchored validation: N/A, no pattern validation is added.
2. Strict wire and stored types: N/A, `JobEstimate` is an in-process frozen dataclass, not
   persisted or sent by the engine.
3. No exception context: no exception is raised out of the estimate; notes carry the type name
   only (AT-E1-10, AT-E1-11).
4. Versioned read models: N/A, nothing persisted is read.
5. Normalized guard scanners: the format-registry guard compares key sets, not text (AT-E1-20).
6. No reaching into private modules: execution imports generation only through
   `decoy_engine.generation`; the import-layer sentry stays without a new ignore line (AT-E1-13).
7. No hidden CI failures: accuracy cells are `benchmark`-marked and run on a VM by the gate,
   which records their result; they are not skipped silently in the default loop, they are
   excluded by the marker, and the gate record names the run.
8. One input, one trust class per entry point: `estimate_job` takes one config and one base
   directory; sources are user data throughout (class 6 row).
9. Mutations on the final head: the gate reruns every named mutation in 8.1 and 8.4 on the final
   head and records that head next to each result in the gate ledger.
10. Allowlisted helpers are still checked: the new physical-seam permit entries are still covered
    by the import sweeps (section 9).
11. No raised caps: nothing in this plan raises a cap, ceiling, pin, baseline or allowlist count;
    the physical-seam permit entries and the declaration-gate `READERS` rows are per-file and
    per-site rationale lines the two sentries require (section 9).

## 14. Enumerations

### Exit paths

- `estimate_job` returns a `JobEstimate` on every path; any exception becomes
  `route="unknown"` with a type-name note (`src/decoy_engine/execution/_job_estimate.py:95`).
- Subset: early return, lifecycle fields at defaults (`src/decoy_engine/execution/_job_estimate.py:104`).
- Mixed: returns `priceable=False` with lifecycle fields filled from E2 (`src/decoy_engine/execution/_job_estimate.py:169`).
- A lifecycle error inside the new code: caught at the lifecycle call, existing fields as without
  it, lifecycle fields at defaults, type-name note (AT-E1-11).
- Unpriceable column, all-null sample column, unknown format or failed sample read: lifecycle
  fields at defaults plus a note.

### Routes

- `full_frame`: execute term is the TB-4 model unchanged (`src/decoy_engine/execution/_mem_estimate.py:447`).
- `sequential`: TB-4 model plus all inputs but the largest (`src/decoy_engine/execution/_sequential.py:443`).
- `out_of_core`: TB-4 model plus all inputs (`src/decoy_engine/execution/_isolated_worker.py:76`).
- Any other route token (`mixed`, `unknown`): priced as `full_frame`, the existing rule and note (`src/decoy_engine/execution/_job_estimate.py:205`).
- Native auto-chunk and the CLI `--chunked` path: not predicted; over-predicted by design.

### FK shapes

- No FK: single or multiple independent tables, any route.
- FK chain and fan-in: they only change the route and therefore the execute term; the ingest and
  write sums are per table and do not depend on edges. AT-E1-18 and AT-E1-19 cover a chain. The
  router put AT-E1-19 on sequential, and AT-E1-18 was predicted sequential and realized
  out_of_core, so no accuracy cell checks out_of_core with a matching route; AT-E1-3 pins the
  out_of_core term (section 8.3).

### Fields

- `JobEstimate.lifecycle_peak_bytes`: `int | None`, at least 0.
- `JobEstimate.limiting_phase`: `"ingest" | "execute" | "write" | None`.
- `JobEstimate.phase_bytes`: three `(token, bytes)` pairs in fixed order, or empty.
- Existing `route`, `notes`: unchanged meanings and values. `priceable`, `peak_bytes`, `runtime`:
  unchanged meanings; values change for string mask jobs (section 4.5).

### Output surfaces

- The returned `JobEstimate` only: fields and `notes`.
- No log line, no file written, no event emitted, no exception text.

## 15. Slices, gates and risk

| Slice | Repo | Production files | Count | Lines | Depends on | Risk |
|---|---|---|---|---|---|---|
| 84-E1 | engine | `execution/pipeline/_lifecycle.py` (new), `execution/pipeline/_lifecycle_inputs.py` (new), `execution/_job_estimate.py`, `_arrow_types.py`, `generation/_bounds.py` (helper call only), `profile/_readers.py` (one defaulted `FooterFacts` field), `execution/_strategies/_hash.py`, `_redact.py`, `_passthrough.py` (output declarations); plus the worker, unit and perf tests, the section 9 sentry rows, CODEMAP rows, frozen-surface sentence, calibration record, changelog fragment | 9 | about 680 production (revision 5 adds the output specs and declarations, about 80) | #328 (merged) | R2 (reads source values for widths, a value-leak surface; changes values on a public result) |
| 84-E2 | engine | `execution/pipeline/_lifecycle_generate.py` (new), `execution/_job_estimate.py`, `execution/pipeline/_lifecycle.py`, `generation/_bounds.py`, `generation/__init__.py`; plus tests, docs section, compatibility entry, changelog fragment | 5 | about 350 production | 84-E1 merged | R1 (no source values; one additive export) |

Gates: R2 is Dennis then Codex on the exact head; R1 is Codex only. Tests: T0 per edit, T1 per
commit, T2 at the gate, on the Mac or a VM through `~/bin/vm-run`, never the devbox; accuracy
cells once per slice on a test VM, their numbers in the calibration record with the head they ran
on. Full-suite trigger: none expected (no shared fixtures, schema, lock or frozen format); E1
changes values on a public result, which the gate judges against the serialization trigger, and
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
- **OQ-4. Accuracy bar: the estimate is never below the measured peak on any cell; numeric cells
  and cells limited by ingest or write are also at most 1.5 times the measured peak when the route
  matches and rows are at least 1M; string cells limited by execute are checked against the lower
  bound only?** Recommended: yes. Under-prediction is the unsafe direction. The TB-4 records put
  the string execute ratio at 1.36 to 2.17 with the pinned slopes (section 8.3), so a 1.5 cap there
  would fail on the existing model, not on this row's code. Tightening it needs string-shape
  slopes (V2-LOG). Revision 5: a cell whose strategies turn numbers into strings (`hash`,
  `redact`) is a string-output cell and takes the lower bound only (section 4.2a); the
  recommendation stands, since the 1.5 cap still applies to every cell whose basis is the one
  TB-4 measured.
- **OQ-5. Price string mask columns from the bounded sample in `peak_bytes` too, not only in the
  lifecycle fields?** Recommended: yes. Every CSV job is unpriceable today; one merged cell
  changes (AT-E1-9) and `priceable`, `peak_bytes` and `runtime` change values (section 4.5). The
  other option (lifecycle only) leaves `priceable=False` beside a priced lifecycle, which reads as
  a contradiction.

## 18. Pre-mortem

Assume it is 2026-12-05 and row 84 is not closed. Likely reasons, with the guard for each:

- An accuracy cell came in under the measured peak because the execute term for `full_frame`
  misses a copy the CLI makes (declared-type casting of CSV inputs). Guard: the cell fails red;
  the slice stops and the plan is amended with a measured term (FM-12), not a tuned constant.
- It happened (84-E1, revision 5): AT-E1-19 and AT-E1-23 came in under because their strategies
  turn int64 columns into strings, and the basis priced the 8-byte inputs. The amendment prices the
  output cells the route holds (section 4.2a), with no constant changed. Remaining risk: another
  strategy turns numbers into wide strings. Guard: FM-13 leaves such a column unpriced rather than
  priced at its input width; AT-E1-29 mutation (c) kills the input-width fallback.
- The rerun shows a string-output cell under its lower bound even with output specs (an allocator
  effect larger than the TB-4 slope margin). Guard: the slice stops again (FM-12); the margin
  today is 1.84 or more on the measured cells.
- Review rejects the 4 to 6 times over-prediction on AT-E1-23. Guard: FM-14 states it is the
  native-slice gap, the same by-design direction as FM-6, with a V2-LOG for a native-aware term;
  the advisory contract is never below, not tight.
- The rerun fails the declaration-gate sentry on the sample readers. Guard: section 9 lists the
  four `READERS` rows.
- The sequential input term double counted or missed a table. Guard: section 4.2 states the rule
  from `_sequential.py:443`; AT-E1-3 pins it; AT-E1-18 is the lower-bound check.
- The fixed-width write term missed a live copy or summed copies that are never live together.
  Guard: section 4.2 states the two moments from the CLI code; AT-E1-26 pins the formula and
  kills the summed form; AT-E1-28 pins the integer-coercion term; AT-E1-27 checks the bounds on a real fixed-width write.
- The upper bound failed on a string cell. Guard: string execute cells are lower bound only, from
  the TB-4 ratios in 8.3.
- The upper bound failed on a cell that went native. Guard: realized route recorded; FM-6.
- The sample read leaked a cell value through a reader error. Guard: AT-E1-10.
- A new source format landed without a lifecycle rule. Guard: AT-E1-20.
- Accuracy cells were run on the devbox and stalled it. Guard: `benchmark` marker excluded by
  default; the brief names `vm-run`.
- Review went three rounds over whether `peak_bytes` may change. Guard: OQ-5 asked up front.
- The physical-seam sentry failed CI on the new modules. Guard: section 9 lists the entries.

## 19. Follow-ups (recorded, not in this row)

- V2-LOG: output specs for strategies other than `passthrough`, `hash` and `redact` (FM-13), each
  with a measured cell.
- V2-LOG: a native-aware execute term that prices string outputs as Arrow when the unified slice
  admits the plan (FM-14).
- V2-LOG: per-phase peaks in the accuracy worker (reset `VmHWM` between phases through
  `/proc/self/clear_refs`), so a cell can check each phase and not only the whole process.
- V2-LOG: string width per CPython encoding kind (FM-5).
- V2-LOG: a spread sample across the file (FM-8).
- V2-LOG: string-shape execute slopes so string cells can take an upper bound.
- V2-LOG: vault maps, post-scan baseline tables and quarantine frames in the lifecycle.
- V2-LOG: lazy and chunked handoff models (platform, `--chunked`).
- V2-LOG: move `_mem_estimate*`, `_job_estimate.py`, `_throughput_calibration.py` and the new
  `pipeline/_lifecycle*` modules into one `execution/estimate/` sub-package when one of them next
  changes (section 6).
- Platform (parked): extend `_KNOWN_NOTE_SHAPES` with the lifecycle note shapes at the next engine
  repin (section 12).
- V2: reservation model and enforced admission (platform, parked).
- CLI roadmap row 84: point at this plan.

## 20. Review record

- Revision 1, `f7c5065f4`: Dennis round 1, GO-WITH-FIXES (1 HIGH, 8 MEDIUM, 5 LOW).
- Revision 2 applies:
  - H1: per-class bounds from TB-4 ratios (8.3), OQ-4 reworded, sequential term
    `sum - max` with its reason, TB-4 input wording corrected (G2).
  - M1: types from the sample through `column_arrow_types`, one `arrow_column_bytes` helper in
    `_arrow_types.py`.
  - M2: generation reached only through `decoy_engine.generation`.
  - M3: format rule keyed on `FILE_FORMATS` with a guard.
  - M4: three value changes recorded, notes block with a shape test, platform follow-up.
  - M5: mutations on unit cells only; AT-E1-11 and the Latin-1 cell assert as asked.
  - M6: transform copy priced; vault maps, post-scan baseline and quarantine to non-goals.
  - M7: head-of-file bias row; all-null sample column unpriced.
  - M8: E2 reuses `classify_plan` and a payload-aware `_floor_by_table`; legacy path priced as
    object cells.
  - L1: catalog classes 1 to 11 named, class 9 head recorded.
  - L2: sentry number 103 used.
  - L3: kept in `execution/pipeline/`, reason in section 6.
  - L4: worker keyword set stated; fixed_width coercion copy priced (replaced in revision 3, see
    below).
  - L5: Parquet sample bounded in rows, stated.
  - CLI base refreshed to `b6f8558d`.
- Codex round 1 on `1181509d7`: NO-GO, one V1 finding (fixed-width write under-modeled).
- Revision 3 applies:
  - The fixed_width write term prices the `to_pandas` frame, the `_coerce_int_columns` copy and
    the writer's `.tolist()` lists beside the Arrow output (G3, section 4.2), with unit cell
    AT-E1-26 and accuracy cell AT-E1-27 (lower bound always; 1.5 when the model predicts write).
  - Checked against the reader: the revision 2 "integer coercion copy" at ingest was stale.
    `read_fixed_width` builds typed row dicts and one DataFrame, so the ingest transient is now
    `max(records + refs, frame + arrow)`; the extra copy is dropped.
- Codex round 2 on `d03677750`: NO-GO, two V1 findings; the ingest transient was confirmed.
- Revision 4 applies:
  - V1-1: the fixed_width write transient is `frame + max(refs, lists)`. Checked against
    `_targets.py:324` and `:372` and `_fixed_width_writer.py:310`: the `to_pandas` frame is
    unreferenced once `_coerce_int_columns` returns, and its str objects live on in the copy.
    G3, section 4.2, AT-E1-26 and the 8.3 row are updated; `lists >= refs` per cell is stated.
  - V1-2: AT-E1-27 claims only the bound check; the named mutation (summed `refs` and `lists`)
    sits on unit cell AT-E1-26. No accuracy cell carries a mutation.
- Codex round 3 (head 5059ef33a), V1: the per-column `Int64` coercion was left unpriced, and an
  int-declared string column was priced with its string spec at the list moment. Fixed by the
  orchestrator after the round cap: section 4.2 adds `coerce_moment` with the largest
  `coerce(c)` and prices `int_cols` lists as int objects; new unit cell AT-E1-28 with three
  named mutations.
  - CLI citations: CSV conversion `_sources.py:418-419`, fixed-width conversion `:423-424`.
- Codex round 3 ran on revision 4 (NO-GO, entry below the round-3 fix).
- Codex delta (head d1b794a4), V1: already-converted `Int64` columns stay resident during later
  coercions and `refs` prices them at their original cost. Fixed by the orchestrator: section 4.2
  adds `converted(t)`; AT-E1-28 gains a two-column cell and mutation (d). V2-LOG: the integer
  dtype note now says integer columns are not coerced at all.
- Orchestrator amendment after 84-E1 build, calibration (revision 5, plan head before it
  `65f7bff6e`). The build (draft PR #635, `feat/f24-84-e1`, record
  `docs/records/2026-11-17-f24-lifecycle-calibration.md` at `b1213e83a`) stopped under FM-12 with
  four cells below the measured peak and no constant tuned. Applied:
  - Accuracy: section 4.2a. Root cause read from the strategy and sequential code: `hash` and
    `redact` turn int64 cells into Python str cells (and, on sequential, key-map tokens and Arrow
    outputs) that a basis priced on the 8-byte inputs does not contain; TB-4 measured its slopes
    on `passthrough` numerics, where output and input cells cost the same. The execute basis now
    takes each column's working spec (the larger of input and output spec), with the TB-4 slopes
    and intercepts unchanged; the write phase prices outputs with output specs. Checked against
    the record: AT-E1-19 1.84 / 2.12, AT-E1-23 4.25 / 5.88, AT-E1-27 unchanged. AT-E1-19 is
    re-described on sequential (the router's choice at 1M and 3M); AT-E1-19 and AT-E1-23 move to
    lower-only as string-output cells; AT-E1-27 stays bounded and is recorded as execute-limited.
    New FM-13 and FM-14, new note constant, new unit cell AT-E1-29, pre-mortem and follow-ups
    updated.
  - Codex delta round 1 on `bd53d4de4`, NO-GO: the output widths were a second strategy registry
    in the lifecycle. Fixed: the handlers declare their output cell (`output_is_input`,
    `output_string_width`), sharing their config parsing with `run`; guard AT-E1-30 checks the
    declarations against `run` and keeps strategy names out of the lifecycle; three permit rows for
    the changed handler files. Also fixed: section 14 no longer claims an out_of_core FK cell.
  - Codex delta round 2 on `c5023773c`: GO, one LOW: a `truncate` above 64 declared a width the
    kernel never writes. Applied: the hash declaration is capped at the digest length, and
    AT-E1-30 gains a `truncate=100` case.
  - Sentries: section 9 is now a table, one row per registration with its reason: the three
    physical-seam permit rows and the four declaration-gate `READERS` rows for the sample readers
    in `_lifecycle_inputs.py` (missed in revision 4). No other allowlist, cap, pin or baseline
    moves.
  - Accepted builder divergences: AT-E1-7 uses a dictionary column (a `list<int64>` column makes
    the profiler raise before pricing, route "unknown", covered by its own cell); `FooterFacts`
    gains a defaulted `max_row_group_bytes`; the accuracy worker builds fixtures in a separate
    process; the AT-E1-12 mutation is "route taken from lifecycle".
  - Open for the rerun: the worker must pass the resource limits and the native gate result
    (section 8.2), which the calibration record says it does not.
