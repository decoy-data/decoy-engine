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

## 3. Row 30 remainder: the run hashes its scan baseline into evidence

### 3.1 Scope

When a pipeline YAML sets `scan_baseline`, `decoy run` reads the baseline file once at run start,
computes its SHA-256 and writes it to the `--evidence-out` manifest as a new optional member
`scan_baseline: {path, fingerprint, fingerprint_method, size_bytes}` (the existing `FileFingerprint`
shape). `decoy report verify` re-hashes it like an input file. The engine `EvidencePayload` model gets
the member so the library (L3a) and the platform importer can read it.

### 3.2 V1 behaviour

- No `scan_baseline` in the YAML: the manifest has no `scan_baseline` key, and its `manifest_hash` is
  unchanged (same rule as `path_base` in `records/_payloads.py`).
- With one: `path` is recorded the way input paths are (relative under a project marker, else
  absolute). `fingerprint` is `sha256:<hex>` of the bytes read at run start. Method `full`.
- The bytes are read once. Row 32's drift check parses the same bytes, so the hash in the evidence is
  the baseline the run compared against.
- A baseline file that is missing or unreadable at run start: exit 1 with the existing missing-file
  error naming the YAML key `scan_baseline.path`, before any source is read. S3b adds the same check
  to `decoy validate preflight`; the run applies it whether or not preflight ran.
- `decoy report verify` reports a changed or missing baseline file the way it reports a changed input.

### 3.3 Failure modes

| Failure | Behaviour |
|---|---|
| Baseline path is relative | Resolved from the YAML's folder, as sources are |
| Baseline changes between run start and evidence write | Not observable: the hash comes from the bytes read at start |
| Baseline is a library envelope (after L2) or a bare `scan-set/v1` file | Both are hashed as bytes; the hash needs no parse |
| A 0.27 engine reader meets a manifest with `scan_baseline` | It refuses it (extra keys forbidden). The CLI writes the key only after it pins the engine that reads it. A compatibility corpus sample covers the new shape |
| Path text holds a control character | Refused by the existing `RelPath` pattern, as input paths are |

### 3.4 Placement

| File | Repo | New or changed | Where Things Go line | Sits beside |
|---|---|---|---|---|
| `src/decoy_engine/records/_payloads.py` | engine | changed: `scan_baseline: FileFingerprint \| None = None` on `EvidencePayload` | records (evidence model) | `FileFingerprint` |
| `tests/integration/compat_corpus/records/evidence-cli-local-1-baseline.json` | engine | new sample | compatibility corpus | `evidence-cli-local-1-project.json` |
| `src/decoy/cli/io/_scan_set.py` | CLI | changed: `read_scan_baseline(config, yaml_path) -> BaselineFile \| None` (path, bytes, sha256) | io (`_scan_set.py`) | `load_scan_set` |
| `src/decoy/cli/evidence.py` | CLI | changed: `build_manifest(scan_baseline=...)`, `_FIELDS`, `_stored_files` re-hash | `cli-local-1` frozen surface | `_fingerprint` |
| `src/decoy/cli/run/_prepare.py`, `run/_evidence.py`, run context | CLI | changed: read once in prepare, pass to the manifest | run package | existing |

`cli-local-1` is a frozen surface (CLI `docs/release/frozen-surfaces.md`). The change is additive and
optional; the frozen-surface doc gets one line in B-2.

## 4. Row 31 DIST-INTEGRITY: distribution check within n%

### 4.1 Scope

Opt-in. Owner model (2026-11-05): the source shape is captured as the target shape, and the post-scan
asks "is the data the same distribution within n% of the selected shape". The capture is value-free
facts per column of the masking input. They are measured in the lockstep pass the post-scan column
suite already makes over source and output (`verification/postmask/_column_facts.py`). That pass
streams on every route since POSTSCAN-STREAM (row 60), so there is no new reader and no resident
requirement. The "capture" is the source side of that pass. Nothing is kept beyond the value-free
report.

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
| `row_count` | every mask table | relative change `abs(out - src) / src` above n% (both 0 passes) |
| `null_rate` | columns the strategy registry marks | absolute change above n percentage points |
| `distinct_ratio` (distinct / non-null) | marked columns | absolute change above n percentage points |
| `mean` | marked numeric columns, numeric on both sides | `abs(out - src) / src_std` above n% (relative change when `src_std` is 0; both 0 passes) |
| `std` | marked numeric columns | relative change above n% |

Which facts a strategy is meant to keep comes from one new registry,
`contracts/strategy_shape.py: PRESERVED_FACTS_BY_STRATEGY`, beside `strategy_requirements.py`. The
strategy catalog (`execution/_strategies/__init__.py`, `strategy_catalog()`) refuses a handler with no
entry, so a new strategy cannot skip the decision. Recommended entries (owner question Q5):

| Strategy | row_count | null_rate | distinct_ratio | mean, std |
|---|---|---|---|---|
| passthrough, shuffle | yes | yes | yes | yes |
| hash, tokenize, fpe, group_key | yes | yes | yes | no |
| faker, categorical, code_set, date_shift, windowed_date, truncate, text_mask, text_redact, geo_generalize, bucket_perturb, nested, joint_mask, bucketize, top_code | yes | yes | no | no |
| redact, formula, derived, derived_aggregate, grouped_series | yes | no | no | no |

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
- `on_breach: warn`: a breach is a `warning` row. The run delivers. The run-result
  `post_scan_integrity` check is `warned`. The CLI prints one line per breach.
- `on_breach: fail`: a breach is a `fail` row. `post_scan_verdict` adds the new blocking code
  `post_scan.distribution_breach`. The gate blocks before commit, nothing is published, exit 4 (status
  `findings`), and `block_location` names `table.column (fact)`.
- A fact that cannot be computed (a column read fails) is an `error` row. It blocks under `fail`
  (`check_error`) and warns under `warn`.
- A sink the gate cannot read back: refused before the run starts by the existing
  `runtime.post_scan_integrity_sink_unreadable`, because integrity is required. A test pins it.
- Plan hash: `post_scan` is already hashed. `distribution` is dropped from the dump when absent, so
  existing configs keep their hash.

### 4.3 Failure modes

| Failure | Behaviour |
|---|---|
| Quarantine removes rows | The gate's source is already aligned to the output (`_align_sources_to_output`); `row_count` compares aligned counts (test DI-T6) |
| Subset on | The source side is the subset the run masked, not the raw file (test DI-T7; if the gate sees the raw source, the slice stops and reports) |
| Float drift over 100M rows | Moments merged per batch with the Chan update in float64; no sum of raw squares |
| Non-numeric column with a moments entry | `mean` and `std` skipped for that column, recorded as `info` with `delta_pct: null` |
| A strategy that changes types (bucketize to labels) | Not marked for moments in the registry |
| Older reader of a stored report | Reads v3 and ignores the additive section; the verdict is computed in-run by the same engine |
| Value in an error message | Errors keep the class name only, as the column suite does today |

### 4.4 Placement

| File | Repo | New or changed | Where Things Go line | Sits beside |
|---|---|---|---|---|
| `src/decoy_engine/contracts/strategy_shape.py` | engine | new (~80): `PRESERVED_FACTS_BY_STRATEGY`, `preserved_facts()` | versioned contracts (`contracts/<contract>.py`) | `strategy_requirements.py` |
| `src/decoy_engine/execution/_strategies/__init__.py` | engine | changed: catalog refuses a handler with no shape entry | strategy catalog | `_CATALOG_FIELDS` check |
| `src/decoy_engine/config/_post_scan.py` | engine | changed: `DistributionCheck` model, inactive rule, dump omission | config | `PostScanConfig` |
| `src/decoy_engine/verification/postmask/_column_facts.py` | engine | changed: null counts and merged moments per side | verification (column facts) | `ColumnFacts` |
| `src/decoy_engine/verification/postmask/distribution.py` | engine | new (~180): `distribution_findings(facts, config)`, pure | verification (post-mask checks) | `residual_pii.py` |
| `src/decoy_engine/verification/postmask/types.py`, `runner.py` | engine | changed: `DistributionFinding`, report section and counts | verification | existing |
| `src/decoy_engine/verification/postmask/_blocked.py` | engine | changed: verdict reads `distribution` with the mode; code order; `block_location` | verification (the one verdict) | NER block logic |
| `src/decoy_engine/reasons/post_scan/_part2.py`, `reasons/_registry.py` | engine | changed: `distribution_breach`; registry minor | reasons | existing codes |
| `src/decoy_engine/execution/pipeline/_post_scan.py` | engine | changed: passes the mode to the verdict (small; file is 583 lines) | execution | `ner_findings` call |
| `src/decoy/cli/run/_render.py`, `src/decoy/cli/report.py` | CLI | changed: warn lines; `report integrity` bucket tuple (`report.py` near line 2064) | run package; report | existing buckets |

## 5. Row 32 DRIFT: opt-in drift check at run start

### 5.1 Scope

```yaml
scan_baseline:
  path: .decoy/library/objects/ab/cdef....json
  schema: scan-set/v1
  on_drift: warn            # warn | fail; absent = no check (opt-in)
```

At run start, before any masking read, `decoy run` rescans the config's sources with the per-table
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
- `--all` children each check their own YAML. `--sample` runs check too. `--rows` previews do not
  (they write nothing and no evidence).
- Parity: for the same YAML and sources, the drift verdict equals
  `decoy scan --config p.yaml --compare --strict`, because both call the same helper.

### 5.3 Failure modes

| Failure | Behaviour |
|---|---|
| Baseline missing, unreadable, or an unknown schema | Exit 1 with the `load_scan_set` messages (S3b, L2), before any source read |
| Baseline lacks a table the config now has | Reported as drift kind `table_added`; counts as drift (data the baseline never classified) |
| Config lacks a table the baseline has | Reported, not drift (the run masks less) |
| Rescan of a source fails | The coded error propagates as in `decoy scan`; exit by its category |
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

- DI facts: resident, `--chunked` and out-of-core all reach `PostScanGate`
  (`execution/pipeline/_post_scan.py:92`) and the one column-facts pass (`ColumnFacts`,
  `verification/postmask/_column_facts.py:37`). The source side is aligned to the output by
  `_align_sources_to_output` (`execution/_pipeline_finalize.py:193`). Generate tables: skipped.
- Drift: one route, CLI `run/_prepare.py` before execution. `--rows` previews: not checked.
- Baseline hash: one route, the same prepare step.

### Fields

- Strategy handlers that need a shape entry: the 25 names in `SCALAR_HANDLERS`
  (`execution/_strategies/__init__.py:48`), checked by `strategy_catalog()` (`:120`).
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
- Baseline missing: exit 1 (usage) before any source read.
- Uncalibrated NER model: `provider.ner_model_uncalibrated` at detector load, exit by the provider
  category, before any row is read.

### FK shapes

N/A. No slice reads or writes keys across tables. DI checks per column; `row_count` compares aligned
counts per table. Drift diffs per table.

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
| Source and output facts | `_column_facts.py` lockstep pass, `column_distinct` | a second reader |
| Block and exit 4 | `post_scan_verdict`, `PostScanBlockedError`, CLI `_errors.py` mapping | a new error path |
| Sink refusal | `post_scan_sink_refusal` | a DI-specific rule |
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
| Plan hash | new keys hashed only when set | B-T4, D-T1, DI-T1 guards |
| `post-scan-integrity/v3` | optional `distribution` section | v3 readers ignore it |
| `decoy-run-result/v1` | `CheckId` `scan_drift` | additive enum member; a 0.27 reader refuses it, so the CLI writes it only after the repin |
| Reason registry | `post_scan.distribution_breach`, `pre_scan.drift_detected`, `pre_scan.drift_blocked`, `provider.ner_model_uncalibrated` | registry minor bumps with fixtures |

## 6d. Pre-mortem

- DI breaches on correct runs because a strategy entry is wrong (for example `distinct_ratio` on a
  hash that collides). Guard: the registry entries are owner-reviewed (Q5), and DI-1 ships report-only
  before DI-2 can block.
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
| 4 | Route parity and silent fallback | DI on resident, chunked and out-of-core routes; drift rescan vs `scan --compare` | one column-facts pass for every route; one rescan helper shared with S3b | DI-T8, D-T5 | MDI-8, MD-5 |
| 5 | Referential integrity | baseline tables vs config tables; quarantine and subset alignment | explicit `table_added` drift kind; DI compares the aligned source the gate already builds | D-T3 table cases, DI-T6, DI-T7 | MDI-6, MDI-7 |
| 6 | Untrusted producer | hand-edited baseline file; config values | baseline read through `load_scan_set` (strict, versioned); strict config types (`tolerance_pct` bounds, enum `on_drift`, `on_breach`) | DI-T1, D-T1, B-T6 | MDI-1, MD-1 |
| 7 | Check then use (TOCTOU) | baseline hashed for evidence and parsed for drift | one read at run start; hash and parse use the same bytes | B-T7 | MB-7 |
| 8 | Weak tests | DI and NER threshold tests that pass vacuously | every DI test asserts both a breach case and a no-breach case; NER rate tests recompute the constant from digested corpora | DI-T4, M-T2, M-T3 | MDI-4, MM-2 |
| 9 | Refactor drift | configs without the new keys; manifests without `scan_baseline` | omission when absent; old dumps, plan hashes and manifest hashes byte-equal | B-T2, B-T4, DI-T1, D-T1, M-T8 | MB-2, MB-4, MM-8 |
| 10 | Frozen contract drift | `cli-local-1`, `EvidencePayload`, `post-scan-integrity/v3`, `decoy-run-result/v1`, reason registry, frozen config schema | additive optional members; registry minor with fixture; frozen-schema change recorded in `docs/compatibility-contract.md` (M-2) | B-T1, D-T2, M-T7, reason minor fixture test | MB-1, MD-2 |
| 11 | Parallel tables kept by hand | strategy list vs shape facts; model list vs NER rates; sm literal in two places | catalog refuses a handler with no shape entry; detectors refuse a model with no rate; one default constant with a sentry | DI-T2, M-T5, M-T7 | MDI-2, MM-5, MM-7 |

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
| B-T6 | B-2 | baseline path missing at run start: exit 1 naming `scan_baseline.path`, no source opened (read spy) | run ignores the key | MB-6: check after the masking read |
| B-T7 | D-2 | the bytes the drift check parses are the bytes hashed (spy counts one open) | no read | MB-7: read twice |

### Row 31 (DI-1, DI-2 engine; DI-3 CLI)

| Id | Slice | Asserts | Fails before | Mutation |
|---|---|---|---|---|
| DI-T1 | DI-1 | `distribution` without `integrity: true` refused with `post_scan_inactive`; `tolerance_pct` 0, 101, `True`, `"5"` refused; an omitted block keeps the old dump and plan hash | key unknown | MDI-1: lax float |
| DI-T2 | DI-1 | `strategy_catalog()` raises for a handler with no shape entry; every handler has one | no registry | MDI-2: default unknown strategies to all facts |
| DI-T3 | DI-1 | moments over batches cut at 1, 7 and 50 000 rows equal the whole-column mean and std to 1e-9 | no moments | MDI-3: average per-batch means |
| DI-T4 | DI-1 | shuffle on a numeric column: no breach at 1%; a planted transform scaling values by 1.2 under passthrough: `mean` breach at 5% with `delta_pct` set; no cell value in the report (canary sweep) | no section | MDI-4: compare output with itself |
| DI-T5 | DI-1 | hash column: `distinct_ratio` checked, `mean` not; faker column: only `row_count` and `null_rate` | no section | MDI-5: ignore the registry |
| DI-T6 | DI-1 | quarantine drops 3 of 100 rows: `row_count` compares aligned counts, no breach | no section | MDI-6: use the unaligned source |
| DI-T7 | DI-1 | with subset on, the source side is the subset rows | no section | MDI-7: read the raw source |
| DI-T8 | DI-1 | `--chunked` and the out-of-core route give the same `distribution` rows as the resident route | no section | MDI-8: skip on streaming |
| DI-T9 | DI-2 | `on_breach: fail` with a breach: the run raises `PostScanBlockedError` with `distribution_breach`, nothing published, exit 4 through the CLI; `warn`: the run delivers, check `warned` | never blocks | MDI-9: map fail rows to warnings |
| DI-T10 | DI-2 | a fact `error` row blocks under `fail` with `check_error` | no rows | MDI-10: drop error rows |
| DI-T11 | DI-2 | unreadable sink with `distribution` set is refused before start | guard (existing integrity rule) | MDI-11: exempt distribution |
| DI-T12 | DI-3 | e2e SCAN-10: warn prints one line per breach naming table, column and fact; fail exits 4 and names `table.column (fact)`; `report integrity` lists the section | no output | MDI-12: print the measured mean |

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

### Row 32c (M-1, M-2 engine; M-3 CLI)

| Id | Slice | Asserts | Fails before | Mutation |
|---|---|---|---|---|
| M-T1 | M-1 | clinical corpus digest equals the committed constant | file absent | MM-1: regenerate on load |
| M-T2 | M-1 (ner) | recomputes the md rule over calibration plus clinical negatives and asserts it equals `NER_MIN_RATES["en_core_web_md"]`; sm still 0.211 | no md entry | MM-2: share one threshold |
| M-T3 | M-1 (ner) | md flags the stripped 1-in-4 and 1-in-5 notes fixtures; the held-out corpus is not flagged | no md entry | MM-3: use 0.211 for md |
| M-T4 | M-1 | `NerRate` for md decides `hit` at the md rate (unit, no model) | one constant | MM-4: read the global constant |
| M-T5 | M-1 | an uncalibrated model name for scan NER is refused at load with `provider.ner_model_uncalibrated`, before any row is read | loads | MM-5: fall back silently |
| M-T6 | M-1 (ner) | the md wheel row's hash and spaCy range match the wheel's `meta.json` | no row | MM-6: wrong range |
| M-T7 | M-2 | default is md for `pre_scan`, `post_scan` and `text_redact`; no `"en_core_web_sm"` literal in `src/` outside `NER_MODEL_WHEELS` and `NER_MIN_RATES` (sentry) | default sm | MM-7: restore the literal in `_ner_config.py` |
| M-T8 | M-2 | hash stability: configs without `ner_model` keep their hashes; the explicit-sm cases move, listed by name in the test | n/a | MM-8: dump the default |
| M-T9 | M-3 | CLI hints name the engine's default model (a patched constant shows through) | names sm | MM-9: literal again |

## 8. Slices

At most 10 production files and 800 lines each (tests counted in lines). Risk per
`risk-and-exceptions.md`: R1 takes Codex-only review; R2 takes Dennis then Codex.

| Slice | Repo | Rows | Content | Prod files | ~Lines | Risk | Waits on |
|---|---|---|---|---|---|---|---|
| B-1 + D-1 | engine | 30, 32 | evidence member and corpus sample; `on_drift` field and hash rule; `pre_scan.drift_*` codes; `scan_drift` check id and `pre_checks` | 7 | 450 | R2 (frozen payload, config schema, run-result wire) | none |
| DI-1 | engine | 31 | config block, shape registry, catalog guard, facts and moments, `distribution.py`, report section (report-only) | 7 | 760 | R2 (config schema, report shape) | none |
| DI-2 | engine | 31 | verdict, `distribution_breach`, `block_location`, gate mode, docs | 5 | 380 | R2 (blocking decision) | DI-1 |
| M-1 | engine | 32c | clinical corpus, per-model rates, md wheel, uncalibrated refusal, CI installs all wheels; default unchanged | 6 | 520 | R2 (detection threshold) | none |
| M-2 | engine | 32c | default changes to md; `_ner_config` constant; frozen schema; hash tests; docs | 4 | 300 | R2 (frozen schema, default behaviour) | M-1; owner Q8 to Q10 |
| Engine release, CLI repin | both | all | releases on the daily train; CLI repin checklist (memory engine-repin-checklist) | n/a | n/a | per train | the engine slices above |
| B-2 | CLI | 30 | baseline read once, manifest member, verify, frozen-surface line | 5 | 420 | R2 (frozen `cli-local-1`) | repin with B-1 |
| DI-3 | CLI | 31 | warn lines, `report integrity` bucket, docs, SCAN-10 e2e | 3 | 300 | R1 | repin with DI-2 |
| M-3 | CLI | 32c | hints from the engine constant, README | 3 | 120 | R1 | repin with M-2 |
| D-2 | CLI | 32 | `run/_drift.py`, prepare call, `pre_checks` wiring, warn lines, SCAN-11 e2e | 5 | 600 | R2 (refuses runs, run-result content) | repin with D-1; B-2; S3b (row 29); RESULT C1a and C1b (row 62) |

Order: the engine slices can build in parallel (different files). B-1 + D-1 and DI-2 both bump the
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
| Q4 | What is the "selected shape" for DIST-INTEGRITY? | This run's own masking input, measured in the post-scan lockstep pass. A library scan record holds no moments and is sampled, so a comparison against it would need new scan-set fields (not in the row). Row 31's "After: SCAN-LIB" then no longer applies |
| Q5 | Which facts must each strategy keep? | The table in 4.1, in one registry that the catalog enforces |
| Q6 | What is "strict mode"? | The check's own `on_breach: fail`, default `warn`, like `ner_findings`. Not `delivery.mode`, which is strict by default and would make every opted-in breach block |
| Q7 | Must `post_scan.integrity` be on? | Yes, refused otherwise: the facts come from the integrity column suite |
| Q8 | md default for scans only, or also `text_redact`? | Both, one constant: one model to install and copy to offline hosts, and the duplicate literal goes. Alternative: scans only, keep sm for `text_redact` |
| Q9 | Do the clinical negatives enter the Q7 rule? | Yes, with the stop rule above 0.2005 (back to the owner) |
| Q10 | A scan NER model with no calibrated rate | Refuse at load (`provider.ner_model_uncalibrated`): a threshold not measured for the model has no meaning. Alternative: use the highest calibrated rate |
| Q11 | Row 30: is L3a's `links.baseline` enough? | No. Also write the fingerprint into the `--evidence-out` manifest, so evidence carries it with the library off and for bare-file baselines |
| Q12 | Row 80's strict-drift publication block | Reuses `on_drift: fail` from row 32. Row 80 keeps the bound-baseline object and the engine `scan-diff/v1` move |

## 10. Roadmap edits when this plan passes

Rows 30, 31, 32 and 32c: "Plan `E:plan/scan-checks` (`2026-11-16-scan-checks.md`)". Row 31's "After"
drops SCAN-LIB if Q4 is answered as recommended. Row 80's text points at row 32 for the refusal if
Q12 is answered as recommended.
