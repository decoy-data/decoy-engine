Status: plan

# Drift and distribution integrity for CLI V1 (rows 31 and 32)

Rules consulted: `dev-rules/README.md`, `00-universal.md`, `risk-and-exceptions.md`,
`development-loop.md` (PLAN), `feature-dev.md`, `reuse-first.md`, `proportionality.md`,
`api-and-compatibility.md`, `cross-cutting-concerns.md`, `testing.md`, `architecture.md` (layout),
`catalogs/recurring-defects.md`; memory notes v1-bar-blocking-criteria,
plan-defines-acceptance-tests, develop-correctly-registries-and-sizing,
best-practice-becomes-a-sentry, v1-scope-no-new-features, v1-pragmatic-gate-priorities,
engine-repin-checklist.

Bases (2026-11-17): engine `origin/main` `09f6d7c70` (last tag `v0.27.0`, `REGISTRY_VERSION`
1.29.0); CLI `origin/main` `5b49510` (pins the engine 0.27.0 line). Inputs read: CLI
`docs/ROADMAP.md` rows 24e, 29, 30, 31, 32, 36, 37, 60, 62, 76, 80; engine `plan/scan-checks`
(`docs/plans/2026-11-16-scan-checks.md` at `f9198fb2f`, after two Dennis rounds and one Codex
round); engine `plan/scan-multi` (S3b-cli); engine `plan/postscan-stream`; the engine and CLI
CODEMAP "Where things go" maps; the code cited below.

Risk: R2 overall (config schema, a blocking decision on data, refusing runs). Per-slice tiers in
section 13.

## 0. Relation to the scan-checks plan

Rows 31 and 32 are already designed in `plan/scan-checks` sections 4 and 5. That plan passed two
Dennis rounds and a Codex round, and its owner questions Q1 to Q7 and Q12 cover these two rows. Part
of it is built:

- B-1 + D-1 MERGED (engine #613, `03839e889`, 2026-11-16): `scan_baseline.on_drift`
  (`config/_scan_baseline.py:30`), its plan-hash rule (`plan/_compile.py:646`), the reason codes
  `pre_scan.drift_detected` and `pre_scan.drift_blocked` (since UNRELEASED), the `scan_drift` check
  id and `build_run_result(pre_checks=...)` (`run_result/_build.py:232`). Not yet in a release.
- 24e E0 MERGED (engine #611, `854295339`): the per-strategy distribution behaviour table now lives
  in `contracts/distribution_behavior.py`. DI-1a no longer waits on anything.
- Nothing of DI-1a, DI-1b, DI-2, DI-3 or D-2 is built.

This plan does not redesign. It carries the row 31 and row 32 parts of `plan/scan-checks` forward
against today's main, keeps its DI and D slice ids, and changes four things:

1. D-2 no longer waits on S3b (row 29) or RESULT C1 (row 62). S3b waits on L2, which waits on L1c,
   which waits on L1b.3 and WIN-RUNNER; none is started. D-2 now creates the one rescan helper that
   S3b's `--compare` will call (owner question Q-A), and reaches exit 4 through the existing error map
   (owner question Q-B).
2. The rescan helper goes in `src/decoy/cli/scanning/_compare.py`, not the flat
   `src/decoy/cli/_scan_compare.py` that `plan/scan-multi` named: the flat CLI folder is frozen.
3. The engine release that carries each engine half is named (section 13.2).
4. Section 2 records the statistics search and the choice.

When this plan passes, sections 4 and 5 of `plan/scan-checks` and its DI and D-2 rows point here.
Rows 30 (B-2) and 32c (M-1 to M-3) stay in `plan/scan-checks`.

## 1. Guarantee and non-goals

Guarantee:

- Row 31: with `post_scan.distribution` set, every mask table on a supported route gets value-free
  facts (`row_count`, and per column `null_rate`, `distinct_ratio`, `mean`, `std` where the strategy
  keeps them) on its masking input and its output. A fact that moved more than `tolerance_pct` is a
  breach. Under `on_breach: warn` the run delivers and reports it. Under `on_breach: fail` the run
  publishes nothing and exits 4.
- Row 32: with `scan_baseline.on_drift` set, `decoy run` rescans its sources before any masking read
  and diffs each table against the baseline with the one scan-diff rule set. Under `warn` it reports
  and runs. Under `fail` it writes nothing and exits 4.
- Both checks are off unless configured. Configs without the new keys keep their dump, plan hash and
  behaviour byte for byte.
- No cell value reaches a report, a log line, an error or the run result.

Non-goals (a review finding here becomes a follow-up item, not a blocker):

- Statistical drift of value distributions against a library scan. The `scan-set/v1` core holds no
  histogram or moments (section 2).
- Shape tests beyond the five facts (PSI, KS, chi-square on the post-scan). The resident `--fidelity`
  report keeps its binned KS and Cramer's V.
- DI on CLI `--chunked`, on transform-bearing mask tables and on `source_loader` runs: each is
  refused (section 3.3).
- Moving the scan-diff rules into the engine (row 80 F15).
- The run-result `scan_drift` entry from the CLI: RESULT C1 (row 62) builds it from the drift verdict.
- The baseline evidence hash (row 30 B-2) and the md NER model (row 32c).

Expected size: engine about 1,780 lines in 3 slices, about 14 production files touched, 1 new
(`verification/postmask/distribution.py`). CLI about 1,010 lines in 2 slices, 2 new files
(`scanning/_compare.py`, `run/_drift.py`). New public engine names: `DistributionCheck`,
`NULLS_NOT_PRESERVED`, `preserved_facts`, `distribution_findings`, `DistributionFinding`, and the two
reason codes. New CLI-internal names: `rescan_and_diff`, `check_drift`, `DriftVerdict`,
`DriftBlockedError`.

## 2. Established solutions

Search run (2026-11-17): web search for PSI threshold conventions, TFDV drift and skew comparators,
and Deequ relative rate-of-change anomaly strategies; codebase search
`grep -rn -i "psi|ks_2samp|kolmogorov|chi2|jensen|tvd" src/` and `grep -rn drift src/`.

Found:

- Population Stability Index (PSI). Bands of 0.1 and 0.25 are credit-scorecard conventions
  (Yurdakul and Naranjo, "Statistical properties of the population stability index", Journal of
  Risk Model Validation; Arize and Qlik docs repeat them and call them heuristics). PSI needs a
  common binning taken from the reference side (usually its deciles). A streamed route then needs two
  passes or a quantile sketch, and the bin edges are values.
- Two-sample Kolmogorov-Smirnov (`scipy.stats.ks_2samp`) and chi-square homogeneity
  (`scipy.stats.chisquare`). Both are hypothesis tests. At 1M to 100M rows their p-values flag
  differences of no practical size (Lin, Lucas and Shmueli, "Too big to fail: large samples and the
  p-value problem", Information Systems Research 24(4), 2013), and neither gives the user an "n%".
  KS also needs the ordered values or a sketch of them.
- TFDV drift and skew comparators: L-infinity distance for categorical features and approximate
  Jensen-Shannon divergence for numeric ones, with a user-set threshold. Both need per-value
  frequency histograms.
- Deequ anomaly checks (`RelativeRateOfChangeStrategy(maxRateIncrease, maxRateDecrease)`) and Great
  Expectations (`expect_column_mean_to_be_between`,
  `expect_column_proportion_of_unique_values_to_be_between`): a tolerance on a named summary
  statistic, given as a relative or absolute change. This is the "within n%" model the row asks for.
- In the engine: `quality/_distribution_gof.py` already has a binned KS complement and a
  common-partition Cramer's V over `distribution-snapshot` stats for the resident `--fidelity`
  report. Its inputs hold histogram edges and top-K category labels (values), and it runs on the
  resident route only. `verification/postmask/_column_facts.py` already computes exact per-column
  facts over batches on every route.
- Streaming moments: Chan, Golub and LeVeque, "Updating formulae and a pairwise algorithm for
  computing sample variances" (1979; The American Statistician 37(3), 1983): merge (count, mean, M2)
  per batch, so batch cuts do not change the result and no raw sum of squares is kept.

Choice and reasons:

- Row 31 follows the Deequ and Great Expectations tolerance model on five value-free facts. The row
  asks for "within n%", which is a tolerance on a statistic, not a significance test. Rates and
  moments are aggregates, so the report stays value-free; bins and labels would not. They stream on
  every route through the existing column-facts pass, and the Chan merge keeps them exact across
  batches. PSI, KS and chi-square are rejected for this check for the reasons above. The existing
  binned KS and Cramer's V stay in `--fidelity` and are not copied.
- Breach rules: `row_count` and `std` use relative change (Deequ rate of change). `null_rate` and
  `distinct_ratio` are proportions, so they use absolute change in percentage points (the Great
  Expectations "proportion between" form; a relative change of a rate near 0 is unstable). `mean`
  uses the shift in source standard deviations, `abs(out - src) / src_std`, the standardized mean
  difference (Cohen's d with the reference spread). It is scale-free where the relative change of a
  mean near 0 is not. Relative change is used when `src_std` is 0.
- Row 32 is not a statistical test. The owner model (2026-11-05) defines drift as what
  `scan diff --strict` flags: a PII bucket went up, a new high-PII field, a new quasi-identifier
  group, or a table the baseline never classified. The rule set is the existing CLI
  `compute_scan_diff` (`src/decoy/cli/scan.py:865`). The only new code is the rescan wiring.

## 3. Behaviour, row 31 DIST-INTEGRITY

### 3.1 Config

```yaml
post_scan:
  integrity: true
  distribution:
    tolerance_pct: 5        # required, 0 < n <= 100, strict number
    on_breach: warn         # warn (default) | fail ("strict mode")
```

- `distribution` without `integrity: true` is refused at config load with the existing
  `config.post_scan_inactive`.
- `distribution` is dropped from the dump when absent, so existing configs keep their dump and plan
  hash. When set it is hashed, because it decides what blocks (scan-checks Q3).

### 3.2 Facts and where they are measured

Per mask table and per column whose strategy keeps the fact. Counts and aggregates only.

| Fact | Breach when |
|---|---|
| `row_count` (every mask table) | `abs(out - (src - quarantined)) / (src - quarantined)` above n%; both 0 passes |
| `null_rate` | absolute change above n percentage points |
| `distinct_ratio` (distinct / non-null) | absolute change above n percentage points |
| `mean` (numeric on both sides) | `abs(out - src) / src_std` above n%; relative change when `src_std` is 0; both 0 passes |
| `std` (numeric on both sides) | relative change above n% |

- Source side: always `PostScanGate._source(name, caller_source, raw=True)`
  (`execution/pipeline/_post_scan.py:369`), in a source-only pass. That choke point applies the
  declared cast, drops declared-cast quarantined rows and reads `ctx.caller_sources`, the map after
  any subset. The lockstep pass pairs the sides only when row counts match (`_column_facts.py:191`),
  which fails after quarantine, so it is not used for the source side.
- Output side: the column-facts output pass that already runs (`_column_facts.py:176`), extended with
  null counts and merged moments.
- `row_count` subtracts the D8 quarantine count. `note_quarantined` (`_post_scan.py:286`) returns
  early today when the gate is deferred (`:290`); DI-1b keeps the per-table removed-row count in every
  mode when `distribution` is set. D8-removed rows stay in the source-side rate and moment facts (the
  source pass cannot know them on a streamed route); the docs say so.
- Which facts apply comes from the one behaviour contract, not a second table.
  `distribution_behavior_for(strategy, provider_config)` (`contracts/distribution_behavior.py`):
  `preserves_all` gives distinct_ratio and moments, `preserves_cardinality_only` gives
  distinct_ratio, every other label gives neither. `null_rate` applies unless the strategy is in a new
  frozenset `NULLS_NOT_PRESERVED` in the same module. One function `preserved_facts` in
  `verification/postmask/distribution.py` derives the set. A column with `when:` gets only
  `row_count` and, if eligible, `null_rate`.
- `group_key` is relabelled from `preserves_cardinality_only`
  (`contracts/distribution_behavior.py:142`) to `destroys_frequency`: its output cardinality is that
  of its `group_by` column. The `pipeline_config_hash` does not move. The compiled plan YAML does,
  because `plan/_serialize.py:165` emits the label. The golden pin
  `tests/unit/providers_v2/test_distribution_behavior_metadata.py` moves, with a changelog line.

Facts per strategy (scan-checks Q5, checked against today's handlers):

| Strategy | Label | Keeps nulls | Facts |
|---|---|---|---|
| passthrough, shuffle, categorical (weighted or `from_profile`) | preserves_all | yes | all five |
| hash, fpe, tokenize | preserves_cardinality_only | yes | row_count, null_rate, distinct_ratio |
| faker, categorical (plain), bucketize, truncate, geo_generalize, code_set, bucket_perturb, top_code, date_shift, text_mask, text_redact, nested, redact | other labels | yes | row_count, null_rate |
| joint_mask, group_key, windowed_date, grouped_series, derived, derived_aggregate, formula | other labels | no | row_count |

Generate tables have no source and are skipped.

### 3.3 Outcomes

- The post-scan report (`post-scan-integrity/v3`) gets an optional `distribution` section: one row
  per checked fact with `table`, `column` (null for `row_count`), `fact`, `severity` (`info`,
  `warning`, `fail`, `error`) and `delta_pct` rounded to 0.1. No source or output mean, std or rate is
  written.
- Severity is decided once, in `distribution_findings`, from `on_breach` (the NER promotion pattern,
  `verification/postmask/_model_findings.py:243`). `post_scan_verdict`
  (`verification/postmask/_blocked.py:224`) blocks on any `fail` or `error` row in the section and
  gets no new argument.
- DI-1b writes `warning` rows only, whatever `on_breach` says. DI-2 turns on `fail` and the block.
- `warn`: the run delivers; the `post_scan_integrity` run-result check is `warned`; the CLI prints one
  line per breach naming table, column and fact.
- `fail`: blocks before commit with new `post_scan.distribution_breach`; nothing is published; exit
  4 through `PostScanBlockedError` (CLI `src/decoy/cli/run/_errors.py:187`). `block_location` names
  `table.column (fact)`.
- A fact that cannot be computed is an `error` row. Under `fail` it blocks with `check_error`; under
  `warn` it is written as `warning`.
- Refusals in `bind_gate` (`_post_scan.py:496`), before any route read or output: a
  transform-bearing mask table (existing `runtime.post_scan_integrity_transforms_unsupported`); a
  `source_loader` run or any other deferred gate (new `runtime.post_scan_distribution_deferred`). The
  routing-facts profile (`execution/pipeline/_routing_facts.py:89`) may already have read sources
  before dispatch (`execution/_pipeline_route_dispatch.py:72`), so the claim is "before any route
  read".
- Unreadable sink: refused before start by the existing `runtime.post_scan_integrity_sink_unreadable`.
- CLI `--chunked`: refused before any source is opened by the existing chunked-integrity refusal
  (`src/decoy/cli/run/_execute.py:53`); its text names distribution too.

## 4. Behaviour, row 32 DRIFT

### 4.1 Config (built in D-1)

```yaml
scan_baseline:
  path: .decoy/library/objects/ab/cdef....json
  schema: scan-set/v1
  on_drift: warn            # warn | fail; absent = no check
```

### 4.2 Run-start check (D-2)

- Position in CLI `run/_prepare.py`: the baseline bytes are read once before the `--duckdb-source`
  staging step (`src/decoy/cli/run/_prepare.py:339`), so a missing baseline refuses before any
  database is opened. After staging, `check_before_run` validates and returns `ctx.config_dict`
  (`_prepare.py:398`). The rescan runs right after that, before the normal source load, and reads
  `on_drift` from the validated config, never from `ctx.raw`.
- The baseline is parsed with `scan_set_from_data(json.loads(raw))`
  (`src/decoy/cli/io/_scan_set.py:78`) over the same bytes. If row 30 B-2 has merged, D-2 calls its
  `read_scan_baseline`. If not, D-2 adds it in `io/_scan_set.py` with B-2's signature and B-2 reuses
  it (one reader).
- Rescan: new `scanning/_compare.py` `rescan_and_diff(config, baseline)` calls the engine
  `scan_sources` through the existing CLI scan path (`src/decoy/cli/scanning/_multi.py:443`, behind
  the declared-read choke point) with each table's recorded `sample_strategy` and `sample_row_cap`,
  then `compute_scan_diff` per table. A `--duckdb-source` table is rescanned from its staged Parquet.
  S3b's `decoy scan --compare` later calls the same function.
- No `on_drift`: no read, no rescan.
- `warn` and drift: one stderr line per drifted table naming the table, the drift kind and field
  names. The run continues.
- `fail` and drift: `DriftBlockedError` before any masking read; nothing written; exit 4 through
  `run/_errors.py` (category none, blocking, as `PostScanBlockedError`) and `exit_code_for`. Its
  message carries code `pre_scan.drift_blocked`; the warn line carries `pre_scan.drift_detected`.
- `check_drift(ctx)` returns a `DriftVerdict` (status `passed`, `warned` or `failed`, the code, the
  table names). RESULT C1, when it wires the run-result document, turns that verdict into the
  `scan_drift` `Check` for `pre_checks`; D-2 adds no conversion with no caller.
- `--all` children check their own YAML. `--sample` runs check. `--rows` previews do not.
- Parity: for the same YAML and sources, the verdict equals what `decoy scan --compare --strict`
  gives once S3b lands, because both call `rescan_and_diff`.

## 5. Failure modes

### 5.1 Row 31

| Failure | Behaviour |
|---|---|
| D8 quarantine removes rows | `row_count` compares with source minus the recorded count, deferred mode included; source-side facts keep those rows |
| Declared-cast quarantine | `_source(..., raw=True)` repeats the cast and drops the same rows; no D8 subtraction |
| Subset on | source side is `caller_sources`, the subset rows |
| Transform-bearing mask table | refused in `bind_gate`, existing code |
| `source_loader` or other deferred gate | refused in `bind_gate`, `post_scan_distribution_deferred` |
| `--chunked` from the CLI | refused before any source is opened |
| Float error over 100M rows | Chan merge in float64; no raw sum of squares |
| Non-numeric column where moments apply | `mean` and `std` written as `info` with `delta_pct: null` |
| A strategy's claimed null preservation is wrong | the generated null-position property test fails |
| Second source read on a lazy 100M input | cost stated in the docs; bounded to columns with a checked fact |
| Older reader of a stored report | v3 readers ignore the additive section |
| Value in an error message | errors keep the class name only, as the column suite does |

### 5.2 Row 32

| Failure | Behaviour |
|---|---|
| Baseline missing, unreadable, or another schema | exit 1 with the `load_scan_set` message naming `scan_baseline.path`, before any source is read or staged |
| Config has a table the baseline lacks | drift kind `table_added`; counts as drift |
| Baseline has a table the config lacks | reported, not drift |
| Rescan of a source fails | the coded error propagates as in `decoy scan`; exit by category |
| Config invalid | `check_before_run` refuses before the rescan reads anything |
| Library off (`--no-library`) | still checks; the baseline is read by path |
| Large source | rescan bounded by the baseline's recorded sample cap; a `full` baseline rescans fully (docs) |
| `run/_prepare.py` near its 600-line cap (564 today) | the hook is one call; the logic lives in `run/_drift.py` |

## 6. Design notes and choke points

- New structure: one pure engine module `verification/postmask/distribution.py` (fact derivation and
  findings) and two CLI modules. Principles applied: one place per fact (strategy facts derive from
  the behaviour contract; severity decided once; drift rules only in `compute_scan_diff`); typed
  config (`DistributionCheck`); no flag argument on `post_scan_verdict`.
- Choke point, DI source side: `PostScanGate._source`. Guard: DI-T8 route-parity cells plus DI-T6.
  Mutation MDI-8: read the supplied sources directly on one route.
- Choke point, DI refusals: `bind_gate`. Guard: DI-T9. Mutation MDI-9: refuse only on the sequential
  route.
- Choke point, rescan: `scanning/_compare.py` `rescan_and_diff`, the only caller of
  `compute_scan_diff` from `decoy run`. Guard: D-T5 parity and a sentry
  `tests/sentry/run/test_one_drift_rescan.py` (no import of `scan_sources` or `compute_scan_diff`
  under `src/decoy/cli/run/`; the listed shapes are `from x import y`, `import x as y` and module
  attribute access, per recurring defect 5). Mutation MD-5: call `compute_scan_diff` from
  `run/_drift.py`.

## 7. Reuse inventory

| Need | Reused | Not built |
|---|---|---|
| Output facts | `_column_facts.py` output pass | a second output reader |
| Source facts | `PostScanGate._source(..., raw=True)` | a lockstep pairing or a route-private reader |
| Per-strategy behaviour | `contracts/distribution_behavior.py`, `distribution_behavior_for` | a second per-strategy table |
| Severity | the NER promotion pattern | a mode argument on `post_scan_verdict` |
| Block and exit 4 | `post_scan_verdict`, `PostScanBlockedError`, CLI `_errors.py` | a new error path |
| Refusals | `bind_gate`; the existing transforms and sink codes | a route-private refusal |
| Shape metrics | none needed; `_distribution_gof.py` stays with `--fidelity` | PSI, KS or chi-square copies |
| Drift config, codes, check id | D-1 (#613) | anything new in the engine for row 32 |
| Drift rules | `compute_scan_diff` | new rules |
| Rescan | engine `scan_sources` through `scanning/_multi.py` | a run-local scanner |
| Baseline parse | `load_scan_set` and `scan_set_from_data` | a second parser |
| Exit 4 | `RUN_EXIT_MAP`, `derive_outcome`, `exit_code_for` | a new exit code |

## 8. Placement

Engine (map: engine `CODEMAP.md` "Where things go"; `execution/` is frozen for new top-level files and
this plan adds none there).

| File | New or changed | Where things go line | Sits beside | Slice |
|---|---|---|---|---|
| `src/decoy_engine/contracts/distribution_behavior.py` | changed: `NULLS_NOT_PRESERVED`; `group_key` label | Versioned contracts | `_STATIC_BEHAVIOR` | DI-1a |
| `src/decoy_engine/config/_post_scan.py` | changed: `DistributionCheck`, inactive rule, dump omission | Config models (`config/_<topic>.py`) | `PostScanConfig` | DI-1a |
| `src/decoy_engine/verification/postmask/distribution.py` | new (~220): `preserved_facts` (DI-1a), `distribution_findings` and `DistributionFinding` (DI-1b), `fail` severity (DI-2); pure | detectors, profiling and post-mask checks (`verification/`), 13 modules in `postmask/`, under the 25 limit | `residual_pii.py` | DI-1a to DI-2 |
| `src/decoy_engine/verification/postmask/_column_facts.py` | changed: source-only pass, null counts, Chan moments | same line (`postmask/_column_facts.py` holds the per-column facts) | `column_distinct` | DI-1a |
| `src/decoy_engine/verification/postmask/types.py`, `runner.py` | changed: report section and counts | same line | existing sections | DI-1b |
| `src/decoy_engine/execution/pipeline/_post_scan.py` | changed: source facts through `_source`; D8 count in deferred mode; refusals in `bind_gate` (583 lines against the 600-line module aim: the refusal predicates and the source-only pass live in `distribution.py` and `_column_facts.py`, so this file gains only calls and stays under 600) | Pipeline spine and routes (`execution/pipeline/`) | `_source`, `_deferred` | DI-1b, DI-2 |
| `src/decoy_engine/verification/postmask/_blocked.py` | changed: verdict rows, `_ORDER`, `block_location` | same line (`_blocked.py` holds the one verdict) | NER block logic | DI-2 |
| `src/decoy_engine/reasons/post_scan/_part2.py`, `reasons/runtime/_part3.py` | changed: `distribution_breach`, `post_scan_distribution_deferred`, since UNRELEASED | Reason codes | existing codes | DI-2 |
| `tests/snapshots/frozen_schemas/pipeline-config.schema.json` | changed: `distribution` | frozen schema snapshot | existing keys | DI-1a |
| `changelog.d/<slug>.md` | new fragment per slice | changelog fragments (REG-RELEASE E1) | other fragments | each |

`preserved_facts` merges in DI-1a before its caller; its caller is `distribution_findings` in DI-1b
of this plan (proportionality pair).

CLI (map: CLI `CODEMAP.md` "Where things go"; flat `src/decoy/cli/` is frozen and takes no file).

| File | New or changed | Where things go line | Sits beside | Slice |
|---|---|---|---|---|
| `src/decoy/cli/scanning/_compare.py` | new (~150): `rescan_and_diff` | `decoy scan` internals (`scanning/_<noun>.py`) | `scanning/_multi.py` | D-2 |
| `src/decoy/cli/run/_drift.py` | new (~140): `check_drift`, `DriftVerdict`, `DriftBlockedError`, warn lines | `decoy run` internals (`run/_<noun>.py`) | `run/_prepare.py` | D-2 |
| `src/decoy/cli/run/_prepare.py` | changed: baseline read before staging, one `check_drift` call after `check_before_run` | same line | existing phases | D-2 |
| `src/decoy/cli/run/_errors.py`, `src/decoy/cli/exit_codes.py` | changed: `DriftBlockedError` arm, exit 4 | same line; exit codes | `PostScanBlockedError` arm | D-2 |
| `src/decoy/cli/io/_scan_set.py` | changed only if B-2 has not merged: `read_scan_baseline` | Source readers (`io/_scan_set.py`) | `load_scan_set` | D-2 |
| `src/decoy/cli/run/_render.py` | changed: breach lines | `decoy run` internals | post-scan lines | DI-3 |
| `src/decoy/cli/report.py` | changed: one bucket tuple (file is 2,305 lines, over the cap; no growth beyond the tuple) | command module (existing) | integrity buckets | DI-3 |
| `src/decoy/cli/run/_execute.py` | changed: chunked refusal text | `decoy run` internals | `_ChunkedIntegrityError` | DI-3 |
| `tests/sentry/run/test_one_drift_rescan.py` | new sentry | Sentry test (`tests/sentry/run/`) | `test_one_run_reason.py` | D-2 |

## 9. Enumerations

### Routes

- DI, engine: resident, chunked and out-of-core reach `PostScanGate`
  (`execution/pipeline/_post_scan.py:92`); every source side goes through `_source`
  (`_post_scan.py:369`). Generate tables: skipped.
- DI, refused: transform-bearing, `source_loader` and deferred gates in `bind_gate`
  (`_post_scan.py:496`, `_deferred` at `_post_scan.py:480`).
- DI, CLI: `--chunked` refused (`src/decoy/cli/run/_execute.py:53`); resident and out-of-core only.
- Drift: CLI `src/decoy/cli/run/_prepare.py:339` (byte read before staging) and
  `src/decoy/cli/run/_prepare.py:398` (rescan after validation). `--rows` previews: not checked.

### Fields

- New config keys: `post_scan.distribution.tolerance_pct`, `post_scan.distribution.on_breach`.
  Existing: `scan_baseline.on_drift` (`config/_scan_baseline.py:30`).
- Strategies needing a fact rule: the handlers in `SCALAR_HANDLERS`
  (`execution/_strategies/__init__.py:48`); labels in `contracts/distribution_behavior.py:70`.
- Report fields per DI row: `table`, `column`, `fact`, `severity`, `delta_pct`.
- Check id `scan_drift` (`run_result/_model.py:183`), filled by RESULT C1 from `DriftVerdict`.

### Exit paths

- DI `fail`: `post_scan_verdict` (`verification/postmask/_blocked.py:224`, order `_ORDER` at
  `_blocked.py:41`) raises `PostScanBlockedError`; CLI exit 4.
- DI refusals: runtime exit before any route read or output.
- DI with CLI `--chunked`: exit 1.
- Drift `fail`: `DriftBlockedError`, exit 4 through `run/_errors.py` and `exit_code_for`.
- Drift baseline missing with `on_drift`: exit 1 before any read or staging.
- Rescan source failure: exit by its category (1 or 3).

### FK shapes

N/A: no slice reads or writes keys across tables. DI checks per column and per-table row counts;
drift diffs per table.

### Output surfaces

- Post-scan report JSON: optional `distribution` section.
- CLI stderr: DI breach lines (`run/_render.py`), drift lines (`run/_drift.py`).
- `decoy report integrity`: the bucket tuple in CLI `report.py` gets `distribution`.
- Run result: `post_scan_integrity` check codes; `scan_drift` once RESULT C1 passes `pre_checks`.
- Logs: none added.

## 10. Frozen contracts touched

| Contract | Change | Compatibility |
|---|---|---|
| Pipeline config schema (frozen snapshot) | `post_scan.distribution` | optional, omitted when absent; snapshot regenerated in DI-1a and noted in `docs/compatibility-contract.md` |
| Plan hash | `post_scan.distribution` hashed when set | absent keeps the hash (DI-T1) |
| Compiled plan YAML | `group_key` behaviour label | `pipeline_config_hash` unchanged; changelog line |
| `post-scan-integrity/v3` | optional `distribution` section | v3 readers ignore it |
| Reason registry | `post_scan.distribution_breach`, `runtime.post_scan_distribution_deferred`, since UNRELEASED | `REGISTRY_VERSION` and reason manifests untouched; the release stamps them |
| `decoy-run-result/v1` | none new (D-1 added `scan_drift`) | none |
| CLI exit codes | none new (4 reused) | none |

## 11. Class table

| # | Class | Where it applies | Structure that closes it | Proof | Mutation |
|---|---|---|---|---|---|
| 1 | Value-bearing output | DI rows and lines; drift lines; errors | DI rows carry names and `delta_pct` only, built in one pure function; drift lines from `ScanDiff` names | DI-T4, DI-T12, D-T6 canary sweeps | MDI-12, MD-6 |
| 2 | Cleanup missing on an exit path | drift `fail`; DI `fail` | drift stops before any output opens; DI uses the gate block-before-commit path | D-T3, DI-T9 | MD-3 |
| 3 | Shared state across batches | moment merge | pure Chan merge over per-batch tallies | DI-T3 | MDI-3 |
| 4 | Route parity and silent fallback | DI on each route; drift vs `scan --compare` | `_source` for every source side; central refusals; one rescan helper | DI-T8, DI-T9, D-T5 | MDI-8, MD-5 |
| 5 | Referential counts across tables | baseline vs config tables; quarantine and subset | `table_added` kind; D8 subtraction; `caller_sources` | D-T3, DI-T6, DI-T7 | MDI-6, MDI-7 |
| 6 | Untrusted producer | hand-edited baseline; config values | `load_scan_set` strict reader; strict `tolerance_pct` and enums | DI-T1, D-T8 | MDI-1 |
| 7 | Check then use (TOCTOU) | baseline read then parsed | one read; parse the same bytes | D-T9 | MD-9 |
| 8 | Weak tests | DI tests passing vacuously | each DI test has a breach and a no-breach cell | DI-T4 | MDI-4 |
| 9 | Refactor drift | configs without the new keys | omission when absent; dumps and hashes byte-equal | DI-T1 | MDI-1b |
| 10 | Frozen contract drift | config schema, v3 report, registry | additive optional members; compatibility note | DI-T1, DI-T13 | MDI-13 |

Value-free errors (recurring defect 3): every new error raises after its `except` block closes;
DI-T12 and D-T6 assert `__cause__ is None and __context__ is None` on the new errors.

## 12. Acceptance tests (written first; each red on today's main)

"Red before" says why the test fails on `09f6d7c70` / `5b49510`. "Guard" tests pass before and must
keep passing. Each has a mutation that must turn it red.

### Row 31

| Id | Slice | Asserts | Red before | Mutation |
|---|---|---|---|---|
| DI-T1 | DI-1a | `distribution` without `integrity: true` refused with `post_scan_inactive`; `tolerance_pct` 0, 101, `True`, `"5"` refused; `on_breach: block` refused; an omitted block keeps the old dump and plan hash; a set block moves it | unknown key | MDI-1: lax float; MDI-1b: always dump the block |
| DI-T2 | DI-1a | `preserved_facts` covers every label and every `SCALAR_HANDLERS` strategy; an unknown name in `NULLS_NOT_PRESERVED` fails; generated property test: every strategy claimed to keep nulls keeps the exact null positions on a null-bearing column; `joint_mask` in the set, `redact` not; `group_key` label is `destroys_frequency` | names absent | MDI-2: restore the `group_key` label; MDI-2b: mark `redact` null-destroying |
| DI-T3 | DI-1a | moments over batches cut at 1, 7 and 50,000 rows equal the whole-column mean and std to 1e-9 | no moments | MDI-3: average per-batch means |
| DI-T13 | DI-1a | frozen config schema snapshot holds `distribution` with its bounds and enum | snapshot lacks it | MDI-13: drop the field from the schema export |
| DI-T4 | DI-1b | facts level: equal frames give no breach at 1%; output mean 1.2x the source gives a `mean` breach at 5% with `delta_pct` set; full pipeline: a test-only scaling handler in place of `SCALAR_HANDLERS["passthrough"]` gives a breach row; canary sweep finds no cell value in the report | no section | MDI-4: compare the output with itself |
| DI-T5 | DI-1b | hash column: `distinct_ratio`, no `mean`; faker and redact: `row_count` and `null_rate` only; joint_mask, group_key, windowed_date, grouped_series, derived, formula: `row_count` only and no breach when nulls differ; `when:` columns: `row_count` plus eligible `null_rate` | no section | MDI-5: give every column all facts |
| DI-T6 | DI-1b | (a) resident D8 quarantine drops 3 of 100 at 5%: no `row_count` breach, source `null_rate` counts 100; (b) deferred mode records the same count; (c) declared-cast quarantine rows dropped on both sides | no section | MDI-6: skip the subtraction; MDI-6b: early return in deferred mode |
| DI-T7 | DI-1b | with subset on, the source side is the subset rows | no section | MDI-7: read the unsubset sources |
| DI-T8 | DI-1b | chunked and out-of-core give the same rows as resident; a transform-bearing mask table is refused in `bind_gate` with the existing code before any route read or output | no section | MDI-8: skip on streaming; let transforms through |
| DI-T9 | DI-2 | `fail` with a breach raises `PostScanBlockedError` with `distribution_breach` and publishes nothing; `warn` delivers with check `warned`; a loader run (teed sequential included) and any other deferred gate are refused with `post_scan_distribution_deferred` (spy at the route-dispatch boundary) | no block | MDI-9: refuse only on sequential |
| DI-T10 | DI-2 | an `error` row blocks under `fail` with `check_error` and is written as `warning` under `warn` | no rows | MDI-10: drop error rows |
| DI-T11 | DI-2 | an unreadable sink with `distribution` is refused before start | guard | MDI-11: exempt distribution |
| DI-T14 | DI-2 | reason fixtures hold both new codes with since UNRELEASED and `REGISTRY_VERSION` is unchanged | codes absent | MDI-14: bump the registry version |
| DI-T12 | DI-3 | CLI e2e: `warn` prints one line per breach naming table, column and fact and exits 0; `fail` exits 4 and names `table.column (fact)`; `report integrity` lists the section; `--chunked` with `distribution` is refused before any source opens; canary sweep of stderr and `--json` | no output | MDI-12: print the measured mean |

### Row 32

D-T1 and D-T2 (config and `pre_checks`) shipped green with D-1 (#613) and stay as guards.

| Id | Slice | Asserts | Red before | Mutation |
|---|---|---|---|---|
| D-T3 | D-2 | e2e: baseline from `decoy scan`, then a source gains a high-PII column: `on_drift: fail` exits 4 before any masking read (read spy) and writes no output; `warn` prints the drift line and runs | no check | MD-3: check after masking |
| D-T4 | D-2 | no drift: exit 0, verdict `passed`; no `on_drift`: baseline never opened and no rescan (spy) | no check | MD-4: always rescan |
| D-T5 | D-2 | parity: for five fixture pairs the `rescan_and_diff` verdict equals `compute_scan_diff` over a fresh `decoy scan` of the same sources; sentry `test_one_drift_rescan.py` with a seeded bypass case per listed shape | no helper | MD-5: own diff call in `run/_drift.py` |
| D-T6 | D-2 | stderr and the verdict carry table and field names, never a value (canary sweep); `DriftBlockedError` has no `__cause__` or `__context__` | no check | MD-6: echo a sample row |
| D-T7 | D-2 | `--no-library` still checks; `--rows` does not; `--all` children each check | no check | MD-7: route through the library |
| D-T8 | D-2 | `--duckdb-source`: baseline bytes read before staging; invalid config refused before the rescan (spy); missing baseline refused before the database opens (spy), exit 1 naming `scan_baseline.path`; the rescan reads the staged Parquet; a hand-edited baseline with a bad tag refused | no check | MD-8: read `on_drift` from `ctx.raw` |
| D-T9 | D-2 | the bytes parsed are the bytes read (spy counts one open of the baseline) | no read | MD-9: read twice |
| D-T10 | D-2 | `exit_code_for(DriftBlockedError(...))` is 4 and `run/_errors.py` maps it to 4 | no type | MD-10: map to 3 |

## 13. Slices

At most 10 production files and 800 lines each (tests counted). Risk per `risk-and-exceptions.md`:
R1 takes Codex-only review; R2 takes Dennis then Codex.

### 13.1 Slice table

| Slice | Repo | Row | Content | Prod files | ~Lines | Risk | Waits on |
|---|---|---|---|---|---|---|---|
| DI-1a | engine | 31 | prep folded in: `NULLS_NOT_PRESERVED` and `group_key` relabel in the behaviour contract; `DistributionCheck` config block, inactive rule, dump omission; `preserved_facts`; source-only pass, output null counts, Chan moments; frozen schema snapshot; changelog fragment | 5 | 650 | R2 (config schema, behaviour contract) | none |
| DI-1b | engine | 31 | `distribution_findings` (`warning` only); report section in `types.py` and `runner.py`; every source fact through `_source(..., raw=True)`; D8 count kept in deferred mode; transform refusal in `bind_gate`; route, subset and quarantine cells | 5 | 700 | R2 (report shape, data handling) | DI-1a |
| DI-2 | engine | 31 | `fail` severity; verdict blocks on `fail` and `error` rows; `_ORDER`; `block_location`; codes `distribution_breach` and `post_scan_distribution_deferred`; loader and deferred refusal in `bind_gate`; engine docs (post-scan guide, compatibility note, CODEMAP line for `distribution.py`) | 6 | 430 | R2 (blocking decision) | DI-1b |
| Release and repin | both | 31, 32 | daily train; repin checklist (memory engine-repin-checklist) | n/a | n/a | per train | 13.2 |
| D-2 | CLI | 32 | `scanning/_compare.py`, `run/_drift.py`, one call in `run/_prepare.py`, `_errors.py` and `exit_code_for` arm, `read_scan_baseline` if B-2 has not merged, sentry, drift docs and `decoy explain exit-codes` text, CHANGELOG | 6 | 710 | R2 (refuses runs) | repin to engine 0.28.0 |
| DI-3 | CLI | 31 | breach lines in `run/_render.py`; `report integrity` bucket; chunked refusal text; CLI docs and CHANGELOG; DI-T12 | 3 | 300 | R1 | repin to the release with DI-2 |

Order: DI-1a, DI-1b and DI-2 are serial (shared files). D-2 can build now, in parallel with them: its
engine half is on main and ships in 0.28.0. D-2 and DI-3 share no file. DI-3 and open CLI PR #301
(scan-ml C2a) both edit `run/_render.py`; whichever merges second rebases.

### 13.2 Engine releases

- Row 32 engine half (D-1, #613) is merged and unreleased. It ships in engine 0.28.0, the next
  daily-train release. D-2 repins the CLI to 0.28.0.
- Row 31 engine half is DI-1a, DI-1b and DI-2. It is complete in the first release that contains
  DI-2, planned as engine 0.29.0. A train that cuts with only DI-1a or DI-1b ships them report-only
  (`warning` rows, no block), which is safe by design. DI-3 repins the CLI to the release that
  contains DI-2.

## 14. Pre-mortem

- A fact derived wrongly for a strategy breaches correct runs. Guard: the 3.2 table, the generated
  null-position property test, DI-T5, and report-only DI-1a and DI-1b before DI-2 can block.
- A large D8 quarantine moves the source-side facts. Guard: docs, DI-T6, the `row_count` subtraction.
- A 100M-row lazy input pays a second source read. Guard: docs; bounded to checked columns; moments
  streamed.
- S3b later writes its own rescan. Guard: the D-2 sentry and the roadmap note on row 29.
- RESULT C1 forgets the drift verdict. Guard: D-1's `pre_checks` accepts only `scan_drift`, and the
  roadmap note on row 62 names `DriftVerdict`.
- B-2 and D-2 both add `read_scan_baseline`. Guard: the one-reader rule in 4.2; the second rebases.
- `run/_prepare.py` hits its 600-line cap. Guard: one call; the logic is in `run/_drift.py`.
- Users misread `tolerance_pct` (points for rates, standardized shift for means). Guard: the docs give
  one sentence per fact and one worked example.

## 15. Owner questions (taken on the recommended answer)

Carried from `plan/scan-checks` as decided there: Q1 `on_drift` on `scan_baseline`; Q2 exit 4; Q3
new keys hashed when set; Q4 the "selected shape" is this run's own masking input, so row 31's After
drops SCAN-LIB; Q5 the facts table; Q6 strict mode is `on_breach: fail`, not `delivery.mode`; Q7
`distribution` needs `integrity: true`; Q12 row 80 reuses `on_drift: fail`.

New in this plan:

| Q | Question | Answer taken (recommended) |
|---|---|---|
| Q-A | D-2 waits on S3b (row 29), which waits on L2, L1c and L1b.3. Wait, or build the rescan helper in D-2? | Build it in D-2 at `scanning/_compare.py`; S3b's `--compare` calls it. Rows 29 and 32 share one helper and row 32 leaves the library chain |
| Q-B | RESULT C1 (the CLI run-result document) is not built. Wait for it? | No. D-2 reaches exit 4 through the existing error map and returns a `DriftVerdict`; RESULT C1 turns it into the `scan_drift` check when it lands |
| Q-C | Statistic for "within n%" | Tolerance on five value-free facts (Deequ and Great Expectations model; standardized mean shift for `mean`; points for rates). Not PSI, KS or chi-square (section 2) |
| Q-D | Which release carries row 31's engine half? | The first release containing DI-2, planned 0.29.0; earlier trains may carry DI-1a and DI-1b report-only |
| Q-E | Fewer DI slices? | No. DI-1b plus DI-2 is about 1,130 lines, over the 800-line cap, and DI-2 carries the blocking risk alone. Prep is folded into DI-1a; docs go into DI-2, D-2 and DI-3 |

## 16. V2-LOG

- One shared `Literal["warn", "fail"]` for `ner_findings`, `on_breach` and `on_drift` (from
  scan-checks).
- Statistical drift of value shape against a library baseline (needs histogram fields in
  `scan-set/v1`; not in the row).
- DI on transform-bearing tables and `source_loader` runs (refused in V1).
- CLI `report.py` is 2,305 lines, over the design cap; DI-3 changes one tuple and adds no module.

## 17. Roadmap edits when this plan passes

- Row 31: "Plan `E:plan/drift` (`2026-11-17-drift-dist-integrity.md`), slices DI-1a, DI-1b, DI-2,
  DI-3; engine half in the release with DI-2 (planned 0.29.0)". After drops SCAN-LIB (Q4).
- Row 32: "Engine half MERGED (engine #613, D-1), in 0.28.0; CLI half D-2 per `E:plan/drift`". After
  becomes "0.28.0 repin".
- Row 29: "`--compare` calls `scanning/_compare.py` `rescan_and_diff` from D-2".
- Row 62: "RESULT C1 turns D-2's `DriftVerdict` into the `scan_drift` pre-check".
- `plan/scan-checks` sections 4 and 5: a pointer to this plan.
