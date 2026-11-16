Status: plan

# Scan checks for CLI V1: baseline hash, drift, distribution integrity, NER md model (rows 30, 31, 32, 32c)

Rules consulted: `dev-rules/00-universal.md`, `risk-and-exceptions.md`, `development-loop.md`,
`feature-dev.md`, `api-and-compatibility.md`, `cross-cutting-concerns.md`, `testing.md`,
`architecture.md`, `catalogs/recurring-defects.md`; memory notes v1-bar-blocking-criteria,
plan-defines-acceptance-tests, develop-correctly-registries-and-sizing, best-practice-becomes-a-sentry,
v1-scope-no-new-features.

Bases (2026-11-16): engine `origin/main` `13c95c7de` (0.27.0, registry 1.29.0); CLI `origin/main`
`60cac678`. Inputs read: CLI `docs/ROADMAP.md` rows 27 to 32c, 36, 56, 80, 81; CLI
`docs/qa/cli-v1-checklist.md` group 4 (SCAN-09, SCAN-10, SCAN-11); engine `plan/scan-multi`
(`2026-11-05-scan-multi-fk-discovery.md`, S3-engine, S3a-cli, S3b-cli); CLI `plan/local-record-library`
(`2026-11-05-local-record-library.md`, L2, L3a); engine `plan/scan-ml`; engine `plan/storm-removal`
(`2026-11-16-storm-removal.md`, revision 3); vault
`handoffs/phase1/scanml-ner-model-comparison-2026-11-07.md`; the owner scan and checks model of
2026-11-05 (memory decoy-v1-ux-direction-2026-11-05).

## 1. Verdict per row

| Row | State on main | Plan branch before this one | Verdict |
|---|---|---|---|
| 30 SCAN-LIB | `scan-set/v1` (S1a), `scan_baseline: {path, schema}` (S3-engine.1, engine #586 `df92b604`) and `starter_config` (#589 `8caea5f5`) are merged. L2 (row 36) and L3a (row 37) are not. No `decoy run` reads `scan_baseline` (`plan/_compile.py:622` keeps it out of the plan hash as "a pointer no run reads"). The evidence manifest (`cli-local-1`) hashes the YAML (`pipeline_fingerprint`) but not the baseline file the YAML points at | none | Open. The remainder is the evidence hash only. Snapshots in the library are row 36 (L2); the run-result link `links.baseline` is row 37 (L3a). This plan adds the baseline fingerprint to the evidence manifest (section 3) |
| 31 DIST-INTEGRITY | Not built. The resident `--fidelity` quality report exists (report-only, forces the resident route); it is not this row | none | Plan below (section 4) |
| 32 DRIFT | Not built. `compute_scan_diff` (CLI `scan.py:865`) is the one drift rule set; `decoy scan --compare` (S3b, row 29) is planned, not built | none | Plan below (section 5) |
| 32c SCAN-ML-MD | Not built. `NER_MIN_RATE = 0.211` is one constant for every model (`detection/_ner_rate.py`); only the sm wheel is pinned (`detection/ner.py` `NER_MODEL_WHEELS`) | none | Plan below (section 6) |

No row here is done on main. The SCAN-MULTI plan (`plan/scan-multi`) stays valid for S3a-cli and
S3b-cli with one amendment: its `_scan_set_io.py` is now `src/decoy/cli/io/_scan_set.py`, and S3b's
`check_scan_baseline` calls the reader that slice B-2 adds (section 3.4). Whichever slice lands first
creates it.

## 2. Boundaries with other rows

- Row 36 (L2) stores scan snapshots in the library and adds the envelope branch to `load_scan_set`.
  Row 37 (L3a) fills the run-result `links.baseline` with the record id. Neither is planned here.
- Row 29 (S3b) owns `decoy scan --compare` and the rescan helper `src/decoy/cli/_scan_compare.py`.
  Row 32's run-start check calls that helper. It does not write a second rescan.
- Row 80 (F15) owns the bound (approved) baseline object and the move of the scan-diff rules into an
  engine `scan-diff/v1`. Row 32 uses today's CLI `compute_scan_diff`. When row 80 moves the rules,
  row 32's one call site switches. Row 80's "strict-drift publication block" reuses `on_drift: fail`
  from row 32 (owner question Q12), so there is one drift refusal.
- Row 56 (STORM removal) edits help text in `scan.py`, `explain.py`, `extras.py` and `README.md`. Only
  slice M-3 here touches the same files, on different lines. Whichever merges second rebases.
- Row 32a (SCAN-ML) owns `decoy models install`, which reads `NER_MODEL_WHEELS`. Row 32c only adds a
  row there and changes the default.
- The resident `--fidelity` report (engine `quality/`) stays as it is. Row 31 does not extend it: its
  snapshots hold raw top-K category values and it forces the resident route.
- Row 24e (CLI `plan/cli-qa1-di-close`, `docs/plans/2026-11-16-cli-qa1-di-close.md`, slice E0) moves
  the per-strategy distribution behaviour table (`execution/_distribution_behavior.py`
  `_STATIC_BEHAVIOR`) to engine `contracts/distribution_behavior.py` as a pure move. Row 31 builds on
  that one table and adds no second per-strategy table (section 4.1). DI-1a waits on E0.

## 3. Row 30 remainder: the run hashes its scan baseline into evidence

### 3.1 Scope

When a pipeline YAML sets `scan_baseline` and the run either sets `scan_baseline.on_drift` or is
given `--evidence-out`, `decoy run` reads the baseline file once at run start,
computes its SHA-256 and writes it to the `--evidence-out` manifest as a new optional member
`scan_baseline: {path, fingerprint, fingerprint_method, size_bytes}` (the existing `FileFingerprint`
shape). `decoy report verify` re-hashes it like an input file. The engine `EvidencePayload` model gets
the member so the library (L3a) and the platform importer can read it.

### 3.2 V1 behaviour

- No `scan_baseline` in the YAML: the manifest has no `scan_baseline` key, and its `manifest_hash` is
  unchanged (same rule as `path_base` in `records/_payloads.py`).
- With one: `path` is recorded the way input paths are (relative under a project marker, else
  absolute). `fingerprint` is `sha256:<hex>` of the bytes read at run start. Method `full`.
- `starter_config` writes `scan_baseline` into every config it makes
  (`profiling/_starter_config.py:141`). So a run with neither `on_drift` nor `--evidence-out` does not
  read the file at all, and a missing baseline file does not affect it.
- The bytes are read once, in `run/_prepare.py` before the `--duckdb-source` staging step
  (`_prepare.py:332-383`). The hash is taken over those bytes, and row 32's drift check parses the same
  bytes with `scan_set_from_data(json.loads(raw))` (CLI `io/_scan_set.py:78`), so the hash in the
  evidence is the baseline the run compared against.
- Missing or unreadable baseline file, one rule for rows 30 and 32:
  - `on_drift` set: exit 1 (usage) with the `load_scan_set` message naming `scan_baseline.path`,
    before any source is read or staged. Section 5.3 uses this same error.
  - `on_drift` not set, `--evidence-out` given: the run continues. The manifest records the path with
    `fingerprint: null` (`FileFingerprint.fingerprint` is already optional) and the CLI prints one
    warning line with registered code `warning.scan_baseline_missing` naming `scan_baseline.path`.
- `decoy report verify` reports a changed or missing baseline file the way it reports a changed input.

### 3.3 Failure modes

| Failure | Behaviour |
|---|---|
| Baseline path is relative | Resolved from the YAML's folder, as sources are |
| Baseline changes between run start and evidence write | Not observable: the hash comes from the bytes read at start |
| Starter config points at a baseline the user deleted | No effect unless `on_drift` is set or `--evidence-out` is given (3.2) |
| Baseline is a library envelope (after L2) or a bare `scan-set/v1` file | Both are hashed as bytes; the hash needs no parse |
| A 0.27 engine reader meets a manifest with `scan_baseline` | It refuses it (extra keys forbidden). The CLI writes the key only after it pins the engine that reads it. A compatibility corpus sample covers the new shape |
| Path text holds a control character | Refused by the existing `RelPath` pattern, as input paths are |

### 3.4 Placement

| File | Repo | New or changed | Where Things Go line | Sits beside |
|---|---|---|---|---|
| `src/decoy_engine/records/_payloads.py` | engine | changed: `scan_baseline: FileFingerprint \| None = None` on `EvidencePayload` | records (evidence model) | `FileFingerprint` |
| `tests/integration/compat_corpus/records/evidence-cli-local-1-baseline.json` | engine | new sample | compatibility corpus | `evidence-cli-local-1-project.json` |
| `src/decoy_engine/reasons/warning/`, `reasons/_registry.py` | engine | changed: `scan_baseline_missing`; registry minor | reasons | existing warning codes |
| `src/decoy/cli/io/_scan_set.py` | CLI | changed: `read_scan_baseline(config, yaml_path) -> BaselineFile \| None` (path, bytes, sha256) | io (`_scan_set.py`) | `load_scan_set` |
| `src/decoy/cli/evidence.py` | CLI | changed: `build_manifest(scan_baseline=...)`, `_FIELDS`, `_stored_files` re-hash | `cli-local-1` frozen surface | `_fingerprint` |
| `src/decoy/cli/run/_prepare.py`, `run/_evidence.py`, run context | CLI | changed: read once in prepare, pass to the manifest | run package | existing |

`cli-local-1` is a frozen surface (CLI `docs/release/frozen-surfaces.md`). The change is additive and
optional; the frozen-surface doc gets one line in B-2.

## 4. Row 31 DIST-INTEGRITY: distribution check within n%

### 4.1 Scope

Opt-in. Owner model (2026-11-05): the source shape is captured as the target shape, and the post-scan
asks "is the data the same distribution within n% of the selected shape". The capture is value-free
facts per column of the masking input. Nothing is kept beyond the value-free report.

How the facts are measured:

- On every supported route the source side is exactly
  `PostScanGate._source(name, caller_source, raw=True)` (`execution/pipeline/_post_scan.py:369-393`).
  That choke point applies the declared cast, drops rows quarantined by that cast, and runs
  `check_opened` when it lazily re-reads a caller source. It receives `ctx.caller_sources`, the map
  after any subset selection (`execution/pipeline/_routing_facts.py:63-86`). It does not read the
  aligned sources that
  `_align_sources_to_output` (`execution/_pipeline_finalize.py:193`) builds for post-validation.
- The lockstep column-facts pass pairs source and output only when their row counts match
  (`verification/postmask/_column_facts.py:184-195`). After quarantine they do not match.
- So the source-side facts (null_rate, distinct_ratio, moments) come from a source-only pass over each
  table through `_source`, in the same way `column_distinct` reads one side. The output-side facts
  come from the output pass that already runs. This is one new reader of the source per checked
  table. It is bounded by the columns that have a checked fact.
- `row_count` compares the output count with the source count minus the rows quarantine removed.
  `note_quarantined` (`_post_scan.py:286-302`) records that D8 per-table removed-row count whenever
  `post_scan.distribution` is set, including when the gate is deferred; its current early return at
  `:290` must no longer discard the count. Its separate parent-key capture can remain non-deferred.
  Declared-cast quarantine never reaches `note_quarantined`: the declared casting boundary removes
  the whole row (`declared_casting/_boundary.py:10-12`), and `_source(..., raw=True)` repeats that
  cast without recording it, so both source facts and output already exclude those rows.
- D8-quarantined rows stay in the source-side null_rate, distinct_ratio and moments. The source pass
  does not know which rows D8 removed on a streamed route. DI-T6 pins this: a small D8 quarantine
  does not breach, and the docs say that a large D8 quarantine can move the source-side facts.
- A transform-bearing mask table is refused in `bind_gate` whenever `post_scan.distribution` is set,
  before any route read or output. Transforms run inside the route
  (`execution/_transforms.py:7-12`), so a caller source is not what was masked. Reuse
  `runtime.post_scan_integrity_transforms_unsupported`, the refusal the staged path already uses at
  `_post_scan.py:327-337`; do not add a second reason code.
- A run with a `source_loader` is also refused in `bind_gate` when distribution is set. The sequential
  route can tee loader input (`_post_scan.py:480-492`), but the tee captures only key and declared-cast
  columns, not the configured distribution columns. Refusal is the selected M4 behavior and reuses
  `runtime.post_scan_distribution_deferred`.

Config (engine `PipelineConfig`, strict):

```yaml
post_scan:
  integrity: true
  distribution:
    tolerance_pct: 5        # required, 0 < n <= 100
    on_breach: warn         # warn (default) | fail ("strict mode")
```

Facts per mask table and per configured column (counts and aggregates only, never a cell value):

| Fact | Measured on | Breach when |
|---|---|---|
| `row_count` | every mask table | relative change `abs(out - (src - quarantined)) / (src - quarantined)` above n% (both 0 passes) |
| `null_rate` | columns whose strategy keeps nulls | absolute change above n percentage points |
| `distinct_ratio` (distinct / non-null) | columns whose behaviour keeps cardinality | absolute change above n percentage points |
| `mean` | numeric columns whose behaviour keeps all, numeric on both sides | `abs(out - src) / src_std` above n% (relative change when `src_std` is 0; both 0 passes) |
| `std` | same as `mean` | relative change above n% |

Which facts apply is derived, not kept in a second per-strategy table:

- `distinct_ratio`, `mean` and `std` come from the one distribution behaviour table that 24e E0 moves
  to `contracts/distribution_behavior.py`, through `distribution_behavior_for(strategy,
  provider_config)`, so the dynamic `categorical` case stays correct. `preserves_all` gives
  distinct_ratio and moments. `preserves_cardinality_only` gives distinct_ratio. Every other label
  (`destroys_frequency`, `coarsens`, `collapses`, `varies_shape`, `mixed`, `inherits`) gives neither.
- `null_rate` comes from one frozenset `NULLS_NOT_PRESERVED` in the same contract module as the
  behaviour table (`contracts/distribution_behavior.py` after E0). A strategy is in it when an output
  cell can be null, or not null, for a reason other than its own source cell being null. It sits with
  the behaviour table because it is a property of the same per-strategy distribution behaviour, and it
  avoids a one-line edit in each of the 25 handler modules (the handler list is
  `execution/_strategies/__init__.py:21-45`, `:69-74`). A declared handler attribute in
  `_CATALOG_FIELDS` was the other option; it would make DI-1a touch about 30 production files.
- One function `preserved_facts(strategy, provider_config)` in
  `verification/postmask/distribution.py` does the derivation. A test checks that it covers every
  behaviour label and every strategy in `SCALAR_HANDLERS`, that every name in `NULLS_NOT_PRESERVED` is
  a known strategy, and that the two do not disagree. A property test generated from
  `SCALAR_HANDLERS` runs every strategy claimed to keep nulls over a null-bearing column and asserts
  that the output null positions exactly equal the source null positions. This is the guard for the
  fact table, not a hand-written parallel strategy list.
- A column with `when:` gets only `row_count` and, when its strategy is not in
  `NULLS_NOT_PRESERVED`, `null_rate`. Conditional pass-through makes cardinality, frequency and
  moments a mixture of masked and source behavior, so those facts are not claimed.

Resulting facts per strategy (owner question Q5):

| Strategy | Behaviour label after E0 | Keeps nulls (not in `NULLS_NOT_PRESERVED`) | Facts checked |
|---|---|---|---|
| passthrough, shuffle | preserves_all | yes | row_count, null_rate, distinct_ratio, mean, std |
| categorical (weighted or `from_profile`) | preserves_all (dynamic) | yes | same as above |
| hash, fpe, tokenize | preserves_cardinality_only | yes | row_count, null_rate, distinct_ratio |
| faker, categorical (plain), bucketize, truncate, geo_generalize, code_set, bucket_perturb, top_code, date_shift, text_mask, text_redact, nested | other labels | yes | row_count, null_rate |
| joint_mask | coarsens | no: a null key selects a seeded random reference row (`transforms/joint_mask.py:385-392`) | row_count |
| group_key | destroys_frequency (fixed from preserves_cardinality_only, see below) | no: fills from `group_by` (`execution/_strategies/_group_key.py:13-17`) | row_count |
| windowed_date | varies_shape | no: null where the anchor is null (`windowed_date.py:308`) | row_count |
| grouped_series, derived, derived_aggregate, formula | other labels | no | row_count |
| redact | collapses | yes (`execution/_strategies/_redact.py:51`) | row_count, null_rate |

Fix to the existing table: `group_key` is labelled `preserves_cardinality_only` today, but its output
cardinality is the cardinality of its `group_by` column, not of its own source column. DI-1a changes
the label to `destroys_frequency`. That keeps it in 24e E2's intended-loss set, which is built from
`preserves_cardinality_only | destroys_frequency | collapses` (CLI
`docs/plans/2026-11-16-cli-qa1-di-close.md:77-84` on its plan branch). The moving golden pin is
`tests/unit/providers_v2/test_distribution_behavior_metadata.py:39`. The pipeline `plan_hash` remains
unchanged because it hashes config semantics (`plan/_compile.py:626-651`), but newly compiled decoy
plan YAML changes for `group_key` columns because `_serialize.py:164-165` emits the behavior label.
The CHANGELOG records the label and plan-YAML change.

Generate tables have no source and are skipped (generation has its own fidelity gate). Established
practice this follows: Deequ `RelativeRateOfChangeStrategy` and Great Expectations
`expect_column_mean_to_be_between` and `expect_column_proportion_of_unique_values_to_be_between` for
the rules; Chan, Golub and LeVeque (1979) pairwise merge of count, mean and M2 for streaming moments,
so batch boundaries do not change the result; the existing exact `column_distinct` for distinct counts.

### 4.2 V1 behaviour

- Off unless `post_scan.distribution` is set. `distribution` without `post_scan.integrity: true` is
  refused at config load with `config.post_scan_inactive` ("post_scan.distribution needs
  post_scan.integrity: true"), the existing rule shape.
- The post-scan report (`post-scan-integrity/v3`) gets an optional `distribution` section: one row per
  checked fact with `table`, `column` (null for `row_count`), `fact`, `severity`
  (`info`, `warning`, `fail`, `error`) and `delta_pct` rounded to 0.1. No source or output mean or std
  is written.
- Severity is decided once, in `distribution_findings`, from `on_breach`, as NER findings are promoted
  in `verification/postmask/_model_findings.py:244`. `warn` writes a breach as `warning`; `fail` writes
  it as `fail`. `post_scan_verdict` blocks on any `fail` or `error` row in the section. It gets no new
  argument, so its call sites (`_post_scan.py:209`, `:345`, `_blocked.py:302`, `:334`) do not change.
- Between DI-1b and DI-2 the section is report-only: DI-1 writes `warning` rows only, whatever
  `on_breach` says, and DI-2 turns on `fail` rows and the block.
- `on_breach: warn`: the run delivers. The run-result `post_scan_integrity` check is `warned`. The
  CLI prints one line per breach.
- `on_breach: fail`: a breach blocks before commit with the new code `post_scan.distribution_breach`.
  Nothing is published. Exit 4 (status `findings`). `block_location` names `table.column (fact)`.
- A fact that cannot be computed (a column read fails) is an `error` row. Under `fail` it blocks with
  `check_error`; under `warn` it is written as `warning`.
- Deferred gate: a distribution run whose source side would be deferred is refused in `bind_gate`
  with new `runtime.post_scan_distribution_deferred`, before any route read or output. This includes
  every `source_loader` run, even the teed sequential route selected in M4, and any remaining
  `_deferred` case (`_post_scan.py:480-493`). The refusal is not claimed to precede all source reads:
  `build_routing_facts` profiles through `profile_source` at `_routing_facts.py:89-94` before
  `execute_route` enters `bind_gate` at `_pipeline_route_dispatch.py:72`. DI-T9 spies at that route
  boundary. Declared D8 quarantine counting still records removed rows when the gate is deferred so
  the central count cannot silently diverge.
- Transform-bearing mask tables are refused in that same `bind_gate` choke point with the existing
  `runtime.post_scan_integrity_transforms_unsupported`, independent of route and `on_breach`.
- A sink the gate cannot read back: refused before the run starts by the existing
  `runtime.post_scan_integrity_sink_unreadable`, because integrity is required. A test pins it.
  Integrity plus deferred plus a sink is already refused by `post_scan_sink_refusal`
  (`config/_post_scan.py:209-220`). The new distribution refusal in `bind_gate` is still required so
  engine API runs with no sink fail closed too.
- CLI: `decoy run --chunked` already refuses post-scan integrity before any source is opened
  (`cli/run/_execute.py:156-178`). Distribution needs integrity, so the CLI refuses `--chunked` with
  `distribution` too. On the CLI the check runs on the resident and out-of-core routes. DI-T12 and the
  docs pin the refusal.
- Plan hash: `post_scan` is already hashed. `distribution` is dropped from the dump when absent, so
  existing configs keep their hash.

### 4.3 Failure modes

| Failure | Behaviour |
|---|---|
| D8 quarantine removes rows | `row_count` compares with source minus the recorded D8 count, including deferred runs. Source-side facts keep those rows (4.1). DI-T6 |
| Declared-cast quarantine removes rows | `_source(..., raw=True)` repeats the cast and removes the same rows before source facts; no D8 subtraction is applied. DI-T6 |
| Subset on | `caller_sources` is already the subset (`_routing_facts.py:63-86`), so the source side is the subset rows. DI-T7 |
| Transform-bearing mask table | Refused in `bind_gate` with `post_scan_integrity_transforms_unsupported` before any route read or output. DI-T8 |
| `source_loader` on any route | Refused in `bind_gate` with `post_scan_distribution_deferred` before any route read or output. DI-T9 |
| Other deferred gate | Refused in `bind_gate` before any route read or output (4.2). DI-T9 deferred cell |
| `--chunked` from the CLI | Refused before any source is opened, as integrity is today. DI-T12 |
| Float drift over 100M rows | Moments merged per batch with the Chan update in float64; no sum of raw squares. A lazy source is opened a second time for the source-only pass, so docs call out the I/O cost at 100M rows |
| Non-numeric column where moments apply | `mean` and `std` skipped for that column, written as `info` with `delta_pct: null` |
| Claimed null preservation disagrees with a handler | The generated null-position property test fails (4.1) |
| Older reader of a stored report | Reads v3 and ignores the additive section; the verdict is computed in-run by the same engine |
| Value in an error message | Errors keep the class name only, as the column suite does today |

### 4.4 Placement

| File | Repo | New or changed | Where Things Go line | Sits beside |
|---|---|---|---|---|
| `src/decoy_engine/contracts/distribution_behavior.py` | engine | changed (after 24e E0 moves it): `group_key` label fix; `NULLS_NOT_PRESERVED`, including `joint_mask` | versioned contracts | E0's moved table |
| `src/decoy_engine/config/_post_scan.py` | engine | changed: `DistributionCheck` model, inactive rule, dump omission | config | `PostScanConfig` |
| `src/decoy_engine/verification/postmask/_column_facts.py` | engine | changed: source-only pass for null counts, distinct and merged moments; output-side moments | verification (column facts) | `column_distinct` |
| `src/decoy_engine/verification/postmask/distribution.py` | engine | new (~200): `preserved_facts()` (DI-1a), `distribution_findings(facts, config)` with severity (DI-1b, DI-2), pure | verification (post-mask checks) | `residual_pii.py` |
| `src/decoy_engine/verification/postmask/types.py`, `runner.py` | engine | changed: `DistributionFinding`, report section and counts | verification | existing |
| `src/decoy_engine/verification/postmask/_blocked.py` | engine | changed: verdict blocks on `fail` and `error` rows in the section; code order; `block_location` | verification (the one verdict) | NER block logic |
| `src/decoy_engine/execution/pipeline/_post_scan.py` | engine | changed: all source facts use `_source(..., raw=True)`; D8 removed-row count survives deferred mode; transform, loader and deferred refusals in `bind_gate` (small; file is 583 lines) | execution | `_source`, `_deferred` |
| `src/decoy_engine/reasons/post_scan/_part2.py`, `reasons/runtime/`, `reasons/_registry.py` | engine | changed: `distribution_breach`, `post_scan_distribution_deferred`; registry minor | reasons | existing codes |
| `src/decoy/cli/run/_render.py`, `src/decoy/cli/report.py`, `cli/run/_execute.py` message | CLI | changed: warn lines; `report integrity` bucket tuple (`report.py:2064`); chunked refusal text names distribution | run package; report | existing buckets |

## 5. Row 32 DRIFT: opt-in drift check at run start

### 5.1 Scope

```yaml
scan_baseline:
  path: .decoy/library/objects/ab/cdef....json
  schema: scan-set/v1
  on_drift: warn            # warn | fail; absent = no check (opt-in)
```

Two positions in CLI `run/_prepare.py`. The baseline bytes are read with row 30's read, before the
`--duckdb-source` staging step (`_prepare.py:332-383`), so a missing baseline refuses before any
database is opened. After staging, `check_before_run` validates once and returns `ctx.config_dict`
(`_prepare.py:394-405`). The rescan runs immediately after that invariant and before the normal
source load. It reads `on_drift` from the validated config, never from `ctx.raw`, and a
`--duckdb-source` table is rescanned from its staged Parquet as `decoy scan` would see it. Then
`decoy run` rescans the config's sources with the per-table
sampling the baseline recorded (S3b's `_scan_compare` helper, which calls the engine `scan_sources`
through the CLI declared-read choke point). It diffs each table with `compute_scan_diff`. Drift means
what `scan diff --strict` means today: a PII bucket went up, a new high-PII field, or a new
quasi-identifier group.

The engine part: the `on_drift` field (config is engine-owned and strict), its plan-hash rule, the
reason codes, a `scan_drift` check id on the run result, and a `pre_checks` input to
`build_run_result`. The CLI part: the check and its wiring.

### 5.2 V1 behaviour

- No `on_drift`: no rescan, no change from today.
- `on_drift: warn` and drift: one stderr line per drifted table that names the table, the drift kind
  and the field names (names, never values). The run continues. The run result carries check
  `scan_drift` with status `warned`, `blocking: false`, and code `pre_scan.drift_detected`.
- `on_drift: fail` and drift: the run stops before any masking read. Nothing is written. Exit 4
  (status `findings`, as `scan diff --strict` and a blocked post-scan). The run result carries
  `scan_drift` `failed`, `blocking: true`, code `pre_scan.drift_blocked`.
- No drift: check `passed`.
- The baseline bytes are the ones row 30 hashed (one read).
- `on_drift` is read from the validated config returned by `check_before_run`.
- `--duckdb-source` tables are rescanned from their staged Parquet (position above).
- `--all` children each check their own YAML. `--sample` runs check too. `--rows` previews do not
  (they write nothing and no evidence).
- Parity: for the same YAML and sources, the drift verdict equals
  `decoy scan --config p.yaml --compare --strict`, because both call the same helper.

### 5.3 Failure modes

| Failure | Behaviour |
|---|---|
| Baseline missing, unreadable, or an unknown schema | Exit 1 (usage) with the `load_scan_set` message naming `scan_baseline.path`, before any source is read or staged. The same error as 3.2 |
| Baseline lacks a table the config now has | Reported as drift kind `table_added`; counts as drift (data the baseline never classified) |
| Config lacks a table the baseline has | Reported, not drift (the run masks less) |
| Rescan of a source fails | The coded error propagates as in `decoy scan`; exit by its category. The rescan is after `check_before_run`, so a validation failure wins without a source read |
| Rescan reads values | Only through `scan_sources`; the core is value-free; nothing of the rescan is stored |
| Library off (`--no-library`) | The check still runs: it reads the baseline by path |
| Cost on a large source | Bounded by the baseline's recorded `sample_strategy` and `sample_row_cap`; a `full` baseline rescans fully, which the docs state |

### 5.4 Placement

| File | Repo | New or changed | Where Things Go line | Sits beside |
|---|---|---|---|---|
| `src/decoy_engine/config/_scan_baseline.py` | engine | changed: `on_drift: Literal["warn","fail"] \| None`, dropped from dump when `None` | config | `ScanBaselineConfig` |
| `src/decoy_engine/plan/_compile.py` | engine | changed: `scan_baseline.on_drift` hashed when set; `path` and `schema` stay out; docstring | plan | `_UNHASHED_BLOCKS` |
| `src/decoy_engine/reasons/pre_scan/` | engine | changed: `drift_detected`, `drift_blocked`; registry minor | reasons | `profile_failed` |
| `src/decoy_engine/run_result/_model.py`, `_build.py` | engine | changed: `CheckId` gets `scan_drift`; `build_run_result(pre_checks=())` | run_result (one constructor) | `_checks` |
| `src/decoy/cli/run/_drift.py` | CLI | new (~140): `check_drift(ctx)` | run package (`run/_<noun>.py`) | `_prepare.py` |
| `src/decoy/cli/run/_prepare.py`, `_run_outcome.py` (RESULT C1), `run/_render.py` | CLI | changed: one call, `pre_checks`, warn lines | run package | existing |

## 6. Row 32c SCAN-ML-MD: `en_core_web_md` as the default NER model

### 6.1 Scope

- `NER_MODEL_WHEELS` gets the md 3.8.0 row (URL from explosion/spacy-models, SHA-256
  `5e6329fe3fecedb1d1a02c3ea2172ee0fede6cea6e4aefb6a02d832dba78a310`, spaCy `>=3.8.0,<3.9.0`). The sm
  row stays.
- The NER hit threshold becomes per model: `NER_MIN_RATES: Mapping[str, float]` in
  `detection/_ner_rate.py` (sm 0.211, md as measured). `NerRate` carries its threshold, set by
  `ner_rates(cells, model=...)`. `NerRate.hit` stays the one place a hit is decided.
- A clinical-vocabulary negative corpus is committed with its digest before any measurement (the M1
  method): free-text Synthea description values (drug, vaccine, lab, procedure, condition and device
  terms). Synthea is Apache-2.0; the values are vocabulary, not PII.
- The md rate is set by the owner's Q7 rule, `ceil_to_0.001(max(2 x highest false-hit rate, highest
  one-sided 95% Clopper-Pearson upper bound, 0.01))`, over the frozen calibration corpus plus the
  clinical negatives (owner question Q9). The vault measurement gives 0.087 on the frozen corpus only.
  `careplans.REASONDESCRIPTION` (md person rate 0.0615, bound 0.0978) suggests the clinical set may
  raise it to about 0.123. Stop rule: if the md rule comes out above 0.2005 (md would then miss the
  1-in-4 realistic-name notes column it was chosen to catch), the slice stops and goes back to the
  owner.
- Then `DEFAULT_NER_MODEL` becomes md for `pre_scan`, `post_scan` and the `text_redact` `ner` provider
  (owner question Q8). The literal `"en_core_web_sm"` in `execution/_strategies/_ner_config.py` is
  replaced by the constant, which removes the duplicate.
- A scan NER model with no calibrated rate is refused when detectors load, with a new
  `provider.ner_model_uncalibrated` (owner question Q10).
- CLI: the install hints in `README.md`, `cli/explain.py` and `cli/extras.py` read the model name from
  `decoy_engine.detection.ner.DEFAULT_NER_MODEL` instead of naming sm.

### 6.2 V1 behaviour

- A config that does not name `ner_model` uses md. Scan reports, run results and logs already name
  each model and version (`ModelRef`), so the change is visible.
- A config that names sm keeps sm with its own 0.211.
- A free-text column is an NER hit when its share of cells with a span reaches the model's rate.
- The ner-gate CI job installs every pinned wheel (loop over `NER_MODEL_WHEELS`, hash-checked), so
  both calibration tests run.

### 6.3 Failure modes

| Failure | Behaviour |
|---|---|
| A config names `en_core_web_lg` or `en_core_web_trf` for `pre_scan` or `post_scan` | Refused at detector load with `provider.ner_model_uncalibrated` (Q10). Today these load and use sm's 0.211. Listed in failure modes here, in the CHANGELOG and in `docs/compatibility-contract.md`. `text_redact` with such a model is not refused: it redacts spans and uses no rate |
| md not installed, NER asked | Existing `provider.ner_model_not_installed`; the hint names md |
| Plan hash | `ner_model` is dropped from the dump at its default. Configs that never set it keep their hash and now run md (named in reports). Configs that set sm explicitly now dump it and change hash once. The CHANGELOG lists this; the hash-stability test's expected values move in the same slice with the reason recorded |
| Frozen config schema | `tests/snapshots/frozen_schemas/pipeline-config.schema.json` default changes: a frozen-contract change, recorded in `docs/compatibility-contract.md` |
| Larger wheel | md is about 31 MB against sm's 12 MB; offline copy through `models install --from` (row 32a) is unchanged |
| text_redact output | Different spans redacted for configs that did not name a model: an output change, pre-release, in the CHANGELOG |
| Corpus tuned to the number | Corpus and digest commit first; the measuring test recomputes the rate and asserts it equals the constant, as `test_ner_min_rate.py` does |

### 6.4 Placement

| File | Repo | New or changed | Where Things Go line | Sits beside |
|---|---|---|---|---|
| `tests/unit/detection_verification/_ner_clinical_corpus.py` | engine | new, with digest | detection tests | `_ner_corpus.py` |
| `src/decoy_engine/detection/_ner_rate.py` | engine | changed: `NER_MIN_RATES`, threshold on `NerRate`; `NER_MIN_RATE` removed in M-2 once callers move | optional ML detectors | `NER_MIN_RATE` |
| `src/decoy_engine/detection/ner.py` | engine | changed: md wheel row (M-1); default (M-2) | optional ML detectors | `NER_MODEL_WHEELS` |
| `src/decoy_engine/profiling/model_pack/_detectors.py` | engine | changed: uncalibrated refusal | optional ML detectors | `load_detectors` |
| `src/decoy_engine/reasons/provider/` | engine | changed: `ner_model_uncalibrated` | reasons | `ner_model_not_installed` |
| `src/decoy_engine/execution/_strategies/_ner_config.py` | engine | changed: constant, not literal (M-2) | strategy catalog | existing option |
| `.github/workflows/ci.yml` | engine | changed: ner-gate installs every pinned wheel | CI | ner-gate job |

## 6a. Enumerations (engine `13c95c7de`, CLI `60cac678`)

### Routes

- DI facts, engine: resident, chunked and out-of-core reach `PostScanGate`
  (`execution/pipeline/_post_scan.py:92`). The output side uses the column-facts pass (`ColumnFacts`,
  `verification/postmask/_column_facts.py:37`); the source side always uses a new source-only pass
  through `PostScanGate._source(name, caller_source, raw=True)` (4.1). `_align_sources_to_output`
  (`execution/_pipeline_finalize.py:193`) feeds post-validation only and is not used. Generate
  tables: skipped.
- DI facts, unsupported sources: transform-bearing mask tables and `source_loader` runs are refused
  in `bind_gate`; any other deferred gate (`_deferred`, `_post_scan.py:480-493`) is refused there too.
- DI facts, CLI: `--chunked` with integrity is refused (`cli/run/_execute.py:156-178`), so the CLI
  runs DI on the resident and out-of-core routes only.
- Drift: CLI `run/_prepare.py`, baseline byte read before `--duckdb-source` staging; rescan after
  staging and after `check_before_run` (`_prepare.py:394-405`), but before the source load. The rescan
  reads `on_drift` from the validated config. `--rows` previews: not checked.
- Baseline read and hash: CLI `run/_prepare.py` before staging (`_prepare.py:332-383`), only when
  `on_drift` is set or `--evidence-out` is given.

### Fields

- Strategies that need a behaviour label and a null rule: the 25 handlers in `SCALAR_HANDLERS`
  (`execution/_strategies/__init__.py:48`). Behaviour labels: `_STATIC_BEHAVIOR`
  (`execution/_distribution_behavior.py:70`), moved by 24e E0. Null rule: `NULLS_NOT_PRESERVED`.
- New config keys: `post_scan.distribution.tolerance_pct`, `post_scan.distribution.on_breach`,
  `scan_baseline.on_drift` (`ScanBaselineConfig`, `config/_scan_baseline.py:19`).
- New payload member: `EvidencePayload.scan_baseline` (`records/_payloads.py:125`) of type
  `FileFingerprint` (`:49`).
- New check id: `CheckId` (`run_result/_model.py:182`) gets `scan_drift`.
- Default NER model sites: `DEFAULT_NER_MODEL` (`detection/ner.py:46`), `NER_MODEL_WHEELS` (`:63`),
  `NER_MIN_RATE` (`detection/_ner_rate.py:60`), the literal in `_ner_config.py:39`, the frozen config
  schema, CI ner-gate, `scripts/dev/base_install_smoke.py`; CLI `README.md`, `explain.py`, `extras.py`.

### Exit paths

- DI `fail`: `post_scan_verdict` (`verification/postmask/_blocked.py:224`, code order `_ORDER` at
  `:41`) raises `PostScanBlockedError`; CLI `run/_errors.py:187` maps it, and `:323` sets
  `blocking_failed`, so exit 4. No new exit path.
- Drift `fail`: a new `findings` outcome from `run/_drift.py` through `pre_checks` into
  `build_run_result` (`run_result/_build.py:193`, `_checks` at `:127`); exit 4 by the same map.
- Baseline missing with `on_drift` set: exit 1 (usage) before any source read or staging. With only
  `--evidence-out`: a warning and `fingerprint: null`, no exit change.
- Transform-bearing distribution table: `runtime.post_scan_integrity_transforms_unsupported` in
  `bind_gate`, runtime exit before any route read or output.
- Loader or other deferred distribution gate: `runtime.post_scan_distribution_deferred` in
  `bind_gate` (`_post_scan.py:496`), runtime exit before any route read or output. Routing facts may
  already have profiled sources before dispatch (`_pipeline_route_dispatch.py:72`).
- CLI `--chunked` with distribution: the existing chunked-integrity refusal, exit 1.
- Uncalibrated NER model: `provider.ner_model_uncalibrated` at detector load, exit by the provider
  category, before any row is read.

### FK shapes

N/A. No slice reads or writes keys across tables. DI checks per column; `row_count` compares output
with source minus quarantined rows per table. Drift diffs per table.

### Output surfaces

- CLI stderr: DI warn lines (`run/_render.py`), drift warn lines.
- `report integrity`: the bucket tuple at CLI `report.py:2064` gets `distribution`.
- Post-scan report JSON: optional `distribution` section.
- Run result: `checks[]` entry `scan_drift`; codes on the `post_scan_integrity` check.
- Evidence manifest: `scan_baseline` member, built by `build_manifest` (CLI `evidence.py:242`) and
  re-hashed by `_stored_files` (`evidence.py:507`).
- Callers of `compute_scan_diff` (CLI `scan.py:865`): `scan diff` (`scan.py:1004`),
  `ci/adapters.py:165`, later S3b `_scan_compare.py`, then D-2 through it.
- Logs: none added.

## 6b. Reuse inventory

| Need | Reused | Not built |
|---|---|---|
| Output facts | `_column_facts.py` output pass | a second output reader |
| Source facts | `PostScanGate._source(..., raw=True)` plus the `column_distinct` one-side read pattern | a lockstep pairing that fails after quarantine, or a route-private source reader |
| Per-strategy behaviour | 24e E0's `contracts/distribution_behavior.py` and `distribution_behavior_for` | a second per-strategy table |
| Severity decision | the NER promotion pattern (`_model_findings.py:244`) | a mode argument on `post_scan_verdict` |
| Block and exit 4 | `post_scan_verdict`, `PostScanBlockedError`, CLI `_errors.py` mapping | a new error path |
| Unsupported DI source refusal | `bind_gate`, reusing `post_scan_integrity_transforms_unsupported` and `post_scan_distribution_deferred`; existing sink refusal stays in `post_scan_sink_refusal` | a route-private refusal or new transform code |
| Drift rules | `compute_scan_diff` | new rules (row 80 moves them later) |
| Rescan | S3b `_scan_compare` over engine `scan_sources` | a run-local rescan |
| Baseline parse | `load_scan_set` (L2 adds envelopes) | a second parser |
| File hash shape | `FileFingerprint`, CLI `_fingerprint`, `_stored_files` | a new hash member type |
| Run-result check | `Check`, `derive_outcome`, `RUN_EXIT_MAP` | a new outcome path |
| NER wheel pinning | `NER_MODEL_WHEELS`, ner-gate job, Q7 rule and `_ner_corpus.py` method | a new calibration method |

## 6c. Frozen contracts touched

| Contract | Change | Compatibility |
|---|---|---|
| `cli-local-1` evidence manifest and `EvidencePayload` | optional `scan_baseline` | absent stays absent; manifest hashes of old runs unchanged; corpus sample added |
| Pipeline config schema (frozen snapshot) | `post_scan.distribution`, `scan_baseline.on_drift`; `ner_model` default | additive optional keys omitted when absent; default change recorded in `docs/compatibility-contract.md` |
| Plan hash | new config keys hashed only when set; the `group_key` behavior relabel does not change `pipeline_config_hash` | B-T4, D-T1, DI-T1 guards |
| `post-scan-integrity/v3` | optional `distribution` section | v3 readers ignore it |
| `decoy-run-result/v1` | `CheckId` `scan_drift` | additive enum member; a 0.27 reader refuses it, so the CLI writes it only after the repin |
| Reason registry | `post_scan.distribution_breach`, `runtime.post_scan_distribution_deferred`, `pre_scan.drift_detected`, `pre_scan.drift_blocked`, `provider.ner_model_uncalibrated`, `warning.scan_baseline_missing` | registry minor bumps with fixtures |
| Distribution behaviour label | `group_key` changes from `preserves_cardinality_only` to `destroys_frequency` | `pipeline_config_hash` unchanged; compiled plan YAML changes because the label is serialized; moving golden pin and CHANGELOG line |
| NER model names accepted for scans | `en_core_web_lg` and `en_core_web_trf` refused for `pre_scan` and `post_scan` | CHANGELOG and `docs/compatibility-contract.md` note (M-1) |

## 6d. Pre-mortem

- DI breaches on correct runs because a fact is derived wrongly for a strategy (for example
  `null_rate` on a strategy that fills nulls from another column). Guard: the 4.1 table is
  owner-reviewed (Q5), DI-T5 has a case per row-count-only strategy, and DI-1a and DI-1b write
  `warning` rows only before DI-2 can block.
- A large D8 quarantine moves the source-side facts, because D8-removed rows stay in them. Guard: the
  docs state it; DI-T6 pins resident and deferred counts; `row_count` subtracts the recorded count.
- A 100M-row lazy input incurs a second source read for distribution facts. Guard: the user docs name
  that cost explicitly; the implementation remains bounded by selected columns and streamed moments.
- The md rule comes out above the stop value once clinical negatives join. Guard: the stop rule in
  6.1; M-1 ships the rate table with the default unchanged.
- D-2 waits on S3b and RESULT C1 longer than the V1 date allows. Guard: B-2, DI-3 and M-3 do not
  depend on D-2; D-2 is the only slice blocked by other rows, and it is listed last.
- Drift rescan cost surprises users on large sources. Guard: sampling follows the baseline's recorded
  cap; the docs state that a `full` baseline rescans fully.
- Two plans add the baseline reader (this one and S3b). Guard: section 1 names one owner file; the
  second slice reuses it.

## 6e. Class table

| # | Class | Where it applies | Structure that closes it | Proof | Mutation that must turn it red |
|---|---|---|---|---|---|
| 1 | Value-bearing output | DI report rows and warn lines; drift stderr and run-result codes; uncalibrated-model refusal | DI rows carry only `delta_pct` and names, built in one pure function; drift lines come from `ScanDiff` names only; errors keep the class name | DI-T4, D-T6 canary sweeps | MDI-12, MD-6 |
| 2 | Cleanup missing on an exit path | drift `fail` stop; DI `fail` block | drift stops before any output is opened; DI uses the existing gate block-before-commit path, nothing new staged | D-T3 (no output written), DI-T9 (nothing published) | MD-3 |
| 3 | State and concurrency | moment merge across batches | pure Chan merge over immutable per-batch tallies; no shared cache | DI-T3 | MDI-3 |
| 4 | Route parity and silent fallback | DI on resident, chunked, out-of-core, transform-bearing, loader and deferred cases; declared-cast source; CLI `--chunked`; drift rescan vs `scan --compare`; `--duckdb-source` | every supported source side passes through `_source(..., raw=True)`; transform, loader and deferred cases refuse centrally; CLI chunked refusal; one rescan helper shared with S3b after validation and staging | DI-T6 cast-quarantine and deferred-quarantine cells, DI-T8 transform cell, DI-T9 loader/deferred cells, DI-T12, D-T5, D-T8 | MDI-6, MDI-8, MDI-13, MD-5, MD-8 |
| 5 | Referential integrity | baseline tables vs config tables; D8 quarantine, declared-cast quarantine and subset | explicit `table_added` drift kind; `row_count` subtracts the D8 count, while `_source` drops declared-cast quarantined rows; `caller_sources` is post-subset | D-T3 table cases, DI-T6, DI-T7 | MDI-6, MDI-7 |
| 6 | Untrusted producer | hand-edited baseline file; config values | baseline read through `load_scan_set` (strict, versioned); strict config types (`tolerance_pct` bounds, enum `on_drift`, `on_breach`) | DI-T1, D-T1, B-T6 | MDI-1, MD-1 |
| 7 | Check then use (TOCTOU) | baseline hashed for evidence and parsed for drift | one read at run start; hash and parse use the same bytes | B-T7 | MB-7 |
| 8 | Weak tests | DI and NER threshold tests that pass vacuously | every DI test asserts both a breach case and a no-breach case; NER rate tests recompute the constant from digested corpora | DI-T4, M-T2, M-T3 | MDI-4, MM-2 |
| 9 | Refactor drift | configs without the new keys; manifests without `scan_baseline` | omission when absent; old dumps, plan hashes and manifest hashes byte-equal | B-T2, B-T4, DI-T1, D-T1, M-T8 | MB-2, MB-4, MM-8 |
| 10 | Frozen contract drift | `cli-local-1`, `EvidencePayload`, `post-scan-integrity/v3`, `decoy-run-result/v1`, reason registry, frozen config schema | additive optional members; registry minor with fixture; frozen-schema change recorded in `docs/compatibility-contract.md` (M-2) | B-T1, D-T2, M-T7, reason minor fixture test | MB-1, MD-2 |
| 11 | Parallel tables kept by hand | per-strategy behaviour vs DI facts; model list vs NER rates; sm literal in two places | facts derived from the one behaviour contract module (label table and `NULLS_NOT_PRESERVED`), with a coverage and disagreement test over `SCALAR_HANDLERS`; detectors refuse a model with no rate; one default constant with a sentry | DI-T2, M-T5, M-T7 | MDI-2, MM-5, MM-7 |

## 7. Acceptance tests (written first; each fails on today's main)

"Fails before" says why the test is red on `13c95c7de` / `60cac678`. "Guard" tests pass before and
must keep passing. Each test lists a mutation that must turn it red.

### Row 30 (B-1 engine, B-2 CLI)

| Id | Slice | Asserts | Fails before | Mutation |
|---|---|---|---|---|
| B-T1 | B-1 | `EvidencePayload` accepts a manifest with `scan_baseline` and refuses an extra key inside it; the new corpus sample decodes | extra field forbidden | MB-1: make the member a loose dict |
| B-T2 | B-1 | a manifest without `scan_baseline` dumps with no such key (existing corpus samples byte-equal) | guard | MB-2: default to `{}` |
| B-T3 | B-2 | `decoy run p.yaml --evidence-out e.json` with `scan_baseline` set writes `scan_baseline.fingerprint` equal to the SHA-256 of the file bytes, path relative under a marker | key absent | MB-3: hash the path text |
| B-T4 | B-2 | without `scan_baseline` the manifest and its `manifest_hash` equal today's for the same run | guard | MB-4: always write the key |
| B-T5 | B-2 | edit one byte of the baseline after the run: `decoy report verify e.json` reports it changed; delete it: reports it missing | verify ignores it | MB-5: drop the baseline from `_stored_files` |
| B-T6 | B-2 | baseline file missing: (a) neither `on_drift` nor `--evidence-out`: the run passes and never opens the path (spy); (b) only `--evidence-out`: exit 0, one `warning.scan_baseline_missing` warning naming `scan_baseline.path`, manifest `fingerprint: null`; (c) `on_drift` set: exit 1 naming `scan_baseline.path`, no source opened or staged (read spy) | run ignores the key | MB-6: read the baseline on every run |
| B-T7 | D-2 | the bytes `scan_set_from_data(json.loads(raw))` parses are the bytes hashed (spy counts one open) | no read | MB-7: read twice |

### Row 31 (DI-1a, DI-1b, DI-2 engine; DI-3 CLI)

| Id | Slice | Asserts | Fails before | Mutation |
|---|---|---|---|---|
| DI-T1 | DI-1a | `distribution` without `integrity: true` refused with `post_scan_inactive`; `tolerance_pct` 0, 101, `True`, `"5"` refused; an omitted block keeps the old dump and plan hash | key unknown | MDI-1: lax float |
| DI-T2 | DI-1a | `preserved_facts` covers every behaviour label and every strategy in `SCALAR_HANDLERS`; an unknown name in `NULLS_NOT_PRESERVED` fails; a property test generated from `SCALAR_HANDLERS` runs every strategy claimed to preserve nulls on a null-bearing column and output null positions equal source null positions; `joint_mask` is in `NULLS_NOT_PRESERVED`; `redact` is not; `distribution_behavior_for("group_key") == "destroys_frequency"`; the golden at `tests/unit/providers_v2/test_distribution_behavior_metadata.py:39` moves with it | no function | MDI-2: give an unknown strategy every fact; drop `joint_mask` from `NULLS_NOT_PRESERVED` |
| DI-T3 | DI-1a | moments over batches cut at 1, 7 and 50 000 rows equal the whole-column mean and std to 1e-9 | no moments | MDI-3: average per-batch means |
| DI-T4 | DI-1b | shuffle on a numeric column: no breach at 1%; a planted transform scaling values by 1.2 under passthrough: `mean` breach at 5% with `delta_pct` set; no cell value in the report (canary sweep) | no section | MDI-4: compare output with itself |
| DI-T5 | DI-1b | hash column: `distinct_ratio` checked, `mean` not; faker and redact columns: only `row_count` and `null_rate`; `joint_mask`, `group_key`, `windowed_date` (null anchor rows), `grouped_series`, `derived` and `formula` columns: only `row_count`, and no breach when their nulls differ from the source; for every strategy with `when:`, only `row_count` plus `null_rate` when that strategy preserves nulls | no section | MDI-5: give a conditional column cardinality or moments; drop a null-destroying strategy from the fact table |
| DI-T6 | DI-1b | (a) resident D8 quarantine drops 3 of 100 rows at 5%: `row_count` compares 97 with 100 minus 3, no breach, source-side `null_rate` still counts all 100 rows, and a column fact is not `error`; (b) a deferred D8 quarantine records the same removed count despite the gate mode; (c) declared-cast quarantine drops bad rows before masking and `_source(..., raw=True)` drops the same rows on the source pass, so row count and fact inputs match without D8 subtraction | no section | MDI-6: compare with the raw source count; restore the deferred early return; bypass `_source` for the resident suite |
| DI-T7 | DI-1b | with subset on, the source side is the subset rows (`caller_sources`) | no section | MDI-7: read the supplied sources |
| DI-T8 | DI-1b | engine chunked and out-of-core routes give the same `distribution` rows as the resident route; a transform-bearing mask table is refused in `bind_gate` with `post_scan_integrity_transforms_unsupported` before any route read or output | no section | MDI-8: skip on streaming; allow a transform-bearing table through |
| DI-T9 | DI-2 | `on_breach: fail` with a breach: the run raises `PostScanBlockedError` with `distribution_breach`, nothing published, exit 4 through the CLI; `warn`: the run delivers, check `warned`; loader cell: even the teed sequential route refuses distribution with `post_scan_distribution_deferred`; deferred cell: the same code refuses any other deferred distribution gate. The spy is at `execute_route`'s `bind_gate` entry (`_pipeline_route_dispatch.py:72`) and proves no route read or output, while allowing the earlier `build_routing_facts` profile read | never blocks | MDI-9: map fail rows to warnings; MDI-13: let a loader or deferred distribution run enter the route |
| DI-T10 | DI-2 | a fact `error` row blocks under `fail` with `check_error` | no rows | MDI-10: drop error rows |
| DI-T11 | DI-2 | unreadable sink with `distribution` set is refused before start | guard (existing integrity rule) | MDI-11: exempt distribution |
| DI-T12 | DI-3 | e2e SCAN-10: warn prints one line per breach naming table, column and fact; fail exits 4 and names `table.column (fact)`; `report integrity` lists the section; `--chunked` with `distribution` is refused before any source is opened | no output | MDI-12: print the measured mean |

### Row 32 (D-1 engine, D-2 CLI)

| Id | Slice | Asserts | Fails before | Mutation |
|---|---|---|---|---|
| D-T1 | D-1 | `on_drift` accepts `warn` and `fail`, refuses others and `True`; absent keeps the old dump and plan hash; set moves the plan hash; changing `path` alone does not | key unknown | MD-1: hash the whole block |
| D-T2 | D-1 | `build_run_result(pre_checks=(scan_drift failed blocking,))` gives status `findings` and exit 4 through the map; the read model accepts `scan_drift` | unknown check id | MD-2: drop `pre_checks` |
| D-T3 | D-2 | e2e SCAN-11: baseline from `decoy scan`, then a source gets a high-PII column: `on_drift: fail` exits 4 before any masking read (read spy) and writes no output; `warn` warns and runs | no check | MD-3: check after masking |
| D-T4 | D-2 | no drift: exit 0, check `passed`; no `on_drift`: no rescan (spy) | no check | MD-4: always rescan |
| D-T5 | D-2 | parity: for five fixture pairs the run's drift verdict equals `scan --compare --strict` | no check | MD-5: own diff rules |
| D-T6 | D-2 | stderr and run result hold table and field names, never a value (canary sweep) | no check | MD-6: echo a sample row |
| D-T7 | D-2 | `--no-library` still checks; `--rows` does not | no check | MD-7: route through the library |
| D-T8 | D-2 | `--duckdb-source`: the baseline bytes are read before staging, `check_before_run` returns the validated config, then the rescan reads the staged Parquet before the normal source load and gets `on_drift` from that validated config; verdict equals `scan --compare`; a missing baseline refuses before the database is opened (spy), and invalid config refuses before rescan (spy) | no check | MD-8: rescan before staging or before `check_before_run`; read `on_drift` from raw YAML |

### Row 32c (M-1, M-2 engine; M-3 CLI)

| Id | Slice | Asserts | Fails before | Mutation |
|---|---|---|---|---|
| M-T1 | M-1 | clinical corpus digest equals the committed constant | file absent | MM-1: regenerate on load |
| M-T2 | M-1 (ner) | recomputes the md rule over calibration plus clinical negatives and asserts it equals `NER_MIN_RATES["en_core_web_md"]`; sm still 0.211 | no md entry | MM-2: share one threshold |
| M-T3 | M-1 (ner) | md flags the stripped 1-in-4 and 1-in-5 notes fixtures; the held-out corpus is not flagged. This is a second stop condition: if it fails at the measured rate, the slice stops and goes back to the owner, as for the 0.2005 rule | no md entry | MM-3: use 0.211 for md |
| M-T4 | M-1 | `NerRate` for md decides `hit` at the md rate (unit, no model) | one constant | MM-4: read the global constant |
| M-T5 | M-1 | an uncalibrated model name (`en_core_web_lg`) is refused at load with `provider.ner_model_uncalibrated` for `pre_scan` and for `post_scan`, before any row is read; the same name for `text_redact` is not refused | loads | MM-5: fall back silently; MM-5b: refuse in `text_redact` too |
| M-T6 | M-1 (ner) | the md wheel row's hash and spaCy range match the wheel's `meta.json` | no row | MM-6: wrong range |
| M-T7 | M-2 | default is md for `pre_scan`, `post_scan` and `text_redact`; no `"en_core_web_sm"` literal in `src/` outside `NER_MODEL_WHEELS` and `NER_MIN_RATES` (sentry) | default sm | MM-7: restore the literal in `_ner_config.py` |
| M-T8 | M-2 | hash stability: configs without `ner_model` keep their hashes; the explicit-sm cases move, listed by name in the test | n/a | MM-8: dump the default |
| M-T9 | M-3 | CLI hints name the engine's default model (a patched constant shows through) | names sm | MM-9: literal again |

## 8. Slices

At most 10 production files and 800 lines each (tests counted in lines). Risk per
`risk-and-exceptions.md`: R1 takes Codex-only review; R2 takes Dennis then Codex.

| Slice | Repo | Rows | Content | Prod files | ~Lines | Risk | Waits on |
|---|---|---|---|---|---|---|---|
| B-1 + D-1 | engine | 30, 32 | evidence member and corpus sample; `warning.scan_baseline_missing`; `on_drift` field and hash rule; `pre_scan.drift_*` codes; `scan_drift` check id and `pre_checks` | 8 | 480 | R2 (frozen payload, config schema, run-result wire) | none |
| DI-1a | engine | 31 | `NULLS_NOT_PRESERVED`, including `joint_mask`, and `group_key` label fix in the behaviour contract; null-position property guard; `preserved_facts`, including `when:`; config block; source-only pass; moments with the Chan merge | 4 | 620 | R2 (config schema, catalog contract) | 24e E0 |
| DI-1b | engine | 31 | `distribution.py` findings (`warning` severity only); report section; all source facts through `_source(..., raw=True)`; D8 count in `note_quarantined`, including deferred mode; transform refusal; route, cast-quarantine and D8-quarantine cells | 5 | 700 | R2 (report shape) | DI-1a |
| DI-2 | engine | 31 | `fail` severity; verdict blocks on `fail` and `error` rows; `distribution_breach`; loader and deferred refusal in `bind_gate`; `block_location`; docs | 5 | 430 | R2 (blocking decision) | DI-1b |
| M-1 | engine | 32c | clinical corpus, per-model rates, md wheel, uncalibrated refusal, CI installs all wheels; default unchanged | 6 | 520 | R2 (detection threshold) | none |
| M-2 | engine | 32c | default changes to md; `_ner_config` constant; frozen schema; hash tests; docs | 4 | 300 | R2 (frozen schema, default behaviour) | M-1; owner Q8 to Q10 |
| Engine release, CLI repin | both | all | releases on the daily train; CLI repin checklist (memory engine-repin-checklist) | n/a | n/a | per train | the engine slices above |
| B-2 | CLI | 30 | baseline read once, manifest member, verify, frozen-surface line | 5 | 420 | R2 (frozen `cli-local-1`) | repin with B-1 |
| DI-3 | CLI | 31 | warn lines, `report integrity` bucket, docs, SCAN-10 e2e | 3 | 300 | R1 | repin with DI-2 |
| M-3 | CLI | 32c | hints from the engine constant, README | 3 | 120 | R1 | repin with M-2 |
| D-2 | CLI | 32 | `run/_drift.py`, prepare call, `pre_checks` wiring, warn lines, SCAN-11 e2e | 5 | 600 | R2 (refuses runs, run-result content) | repin with D-1; B-2; S3b (row 29); RESULT C1a and C1b (row 62) |

Order: the engine slices can build in parallel (different files), except that DI-1a waits on 24e
E0. B-1 + D-1 and DI-2 both bump the
reason registry minor, so the second to merge rebases its bump. Each CLI slice follows its repin. D-2
is last: it is the only slice that waits on other rows (S3b, which waits on L2 and L1c; RESULT C1).

Group 4 QA readiness: rows 30, 31 and 32 close with B-2, DI-3 and D-2; row 32c with M-3. SCAN-09's
library path also needs rows 36 and 37, which are their own rows.

## 9. Owner questions (recommended answers)

| Q | Question | Recommended |
|---|---|---|
| Q1 | Where does `on_drift` go? | On `scan_baseline` (`scan_baseline.on_drift: warn \| fail`); absent means no check. It is a property of the baseline the YAML points at. `pre_scan` stays suggestion-only and unhashed |
| Q2 | Exit code when drift fails a run | 4 (status `findings`), as `scan diff --strict` and a blocked post-scan |
| Q3 | Plan hash | `scan_baseline.on_drift` and `post_scan.distribution` move the hash when set, because they decide what blocks (as `post_scan` already does). `scan_baseline.path` and `schema` stay out |
| Q4 | What is the "selected shape" for DIST-INTEGRITY? | This run's own masking input, measured by the post-scan gate. A library scan record holds no moments and is sampled, so a comparison against it would need new scan-set fields (not in the row). Row 31's "After: SCAN-LIB" then no longer applies |
| Q5 | Which facts must each strategy keep? | The table in 4.1, derived from the one distribution behaviour contract |
| Q6 | What is "strict mode"? | The check's own `on_breach: fail`, default `warn`, like `ner_findings`. Not `delivery.mode`, which is strict by default and would make every opted-in breach block |
| Q7 | Must `post_scan.integrity` be on? | Yes, refused otherwise: the facts come from the integrity column suite |
| Q8 | md default for scans only, or also `text_redact`? | Both, one constant: one model to install and copy to offline hosts, and the duplicate literal goes. Alternative: scans only, keep sm for `text_redact` |
| Q9 | Do the clinical negatives enter the Q7 rule? | Yes, with the stop rule above 0.2005 (back to the owner) |
| Q10 | A scan NER model with no calibrated rate | Refuse at load (`provider.ner_model_uncalibrated`): a threshold not measured for the model has no meaning. Alternative: use the highest calibrated rate |
| Q11 | Row 30: is L3a's `links.baseline` enough? | No. Also write the fingerprint into the `--evidence-out` manifest, so evidence carries it with the library off and for bare-file baselines |
| Q12 | Row 80's strict-drift publication block | Reuses `on_drift: fail` from row 32. Row 80 keeps the bound-baseline object and the engine `scan-diff/v1` move |

## 10. V2-LOG

- One shared `Literal["warn", "fail"]` for `ner_findings`, `on_breach` and `on_drift` (review round 1,
  L5). Each config block keeps its own literal in V1.
- The missing-at-run-time evidence warning gets registered code `warning.scan_baseline_missing`
  (review round 2, L2), with a fixed value-free summary and a reason fixture. It does not affect a
  run unless `--evidence-out` asked to hash the missing baseline.

## 11. Roadmap edits when this plan passes

Rows 30, 31, 32 and 32c: "Plan `E:plan/scan-checks` (`2026-11-16-scan-checks.md`)". Row 31's "After"
drops SCAN-LIB if Q4 is answered as recommended. Row 80's text points at row 32 for the refusal if
Q12 is answered as recommended.

## 12. Review round 1 resolutions (Dennis, on `a3eca6826`)

| Finding | Resolution | Section |
|---|---|---|
| H1 quarantine and lockstep pairing | source-only pass through `_source(..., raw=True)`; D8 `row_count` subtraction is separate from declared-cast quarantine; D8 rows stay in source facts, pinned | 4.1, 4.3, 6a, DI-T6 |
| H2 deferred gate never blocks | distribution refuses loader and all other deferred gates in `bind_gate`, independent of `on_breach` | 4.2, 4.3, 6a, DI-T9 |
| H3 second per-strategy table | no `strategy_shape.py`; facts derived from 24e E0's behaviour contract module (labels plus `NULLS_NOT_PRESERVED`), with a coverage and disagreement test; DI-1a waits on E0 | 2, 4.1, 4.4, 6b, DI-T2 |
| H4 group_key, windowed_date, grouped_series | row_count only; `group_key` label fix with test | 4.1, DI-T2, DI-T5 |
| H5 starter_config writes `scan_baseline` everywhere | read only with `on_drift` or `--evidence-out` | 3.1, 3.2, 3.3, B-T6 |
| M1 drift hook position and one error | read before staging, validate after staging, then rescan before source load; one missing-baseline error | 3.2, 5.1, 5.2, 5.3, D-T8 |
| M2 CLI refuses `--chunked` with integrity | stated; pinned | 4.2, 4.3, 6a, DI-T12 |
| M3 severity decided once | in `distribution_findings`; no new verdict argument | 4.2, 4.4, 6b |
| M4 lg and trf configs break | failure mode, CHANGELOG, compatibility note; post_scan and text_redact cells | 6.3, 6c, M-T5 |
| M5 DI-1 too large | split into DI-1a and DI-1b | 8 |
| L1 | DI-1 writes `warning` rows only | 4.2 |
| L2 | `_routing_facts.py:63-86` cited; contingency dropped | 4.1, 4.3, DI-T7 |
| L3 | `scan_set_from_data(json.loads(raw))` named | 3.2, B-T7 |
| L4 | M-T3 is a second stop condition | M-T3 |
| L5 | V2-LOG | 10 |

## 13. Review round 2 resolutions (Dennis, on `fd834971b`)

Verdict received: **NO-GO, 0 BLOCKER / 2 HIGH / 4 MEDIUM / 4 LOW**. Q1 through Q12 remain
decided as recorded in section 9.

| Finding | Label | Resolution | Section |
|---|---|---|---|
| H1 source side, quarantine and transforms | V1 | Every supported source side uses `_source(..., raw=True)`; D8 counts survive deferred mode; declared-cast quarantine is covered; transform-bearing mask tables reuse the existing refusal | 4.1 to 4.4, 6a, 6e, DI-T6, DI-T8, 8 |
| H2 null-preservation fact table | V1 | `joint_mask` is null-destroying, `redact` preserves nulls, conditional columns lose all but safe facts, and a generated null-position property guard covers `SCALAR_HANDLERS` | 4.1, 6e, DI-T2, DI-T5, 8 |
| M1 `group_key` relabel | V1 | Relabel to `destroys_frequency`, name the moving golden, preserve `pipeline_config_hash`, and record the compiled plan-YAML change | 2, 4.1, 6c, DI-T2 |
| M2 deferred refusal timing and impossible loader cell | V1 | Claim only before route read or output, pin the dispatch-boundary spy, remove the impossible report-only loader comparison, and state the no-sink engine API case | 4.2, 4.3, 6a, DI-T9 |
| M3 drift rescan ordering | V1 | Baseline bytes stay before staging; validation follows staging; rescan follows validation and reads `on_drift` from the validated config before normal source load | 5.1 to 5.3, 6a, D-T8 |
| M4 loader route | V1 | Select bind-time refusal for every loader-backed distribution run, including the teed sequential route | 4.1 to 4.3, 6a, DI-T9, 8 |
| L1 | V2-LOG | No additional edit was requested in the round 2 handoff | n/a |
| L2 missing-baseline evidence warning | V2-LOG | Register `warning.scan_baseline_missing` and pin it in the missing-baseline cell | 3.2, 3.4, 6c, B-T6, 10 |
| L3 100M-row cost | V2-LOG | State that the source-only facts pass opens a lazy source a second time | 4.3, 6d |
| L4 class 4 cells | V2-LOG | Name the transform, declared-cast quarantine and deferred-quarantine cells | 6e, DI-T6, DI-T8 |
