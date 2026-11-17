Status: plan

# Drift and distribution integrity for CLI V1 (rows 31 and 32)

Rules consulted: `dev-rules/README.md`, `00-universal.md`, `risk-and-exceptions.md`,
`development-loop.md` (PLAN), `feature-dev.md`, `reuse-first.md`, `proportionality.md`,
`api-and-compatibility.md`, `cross-cutting-concerns.md`, `testing.md`, `architecture.md` (layout),
`catalogs/recurring-defects.md`; memory notes v1-bar-blocking-criteria,
plan-defines-acceptance-tests, develop-correctly-registries-and-sizing,
best-practice-becomes-a-sentry, v1-scope-no-new-features, v1-pragmatic-gate-priorities,
engine-repin-checklist.

Revision 2 (2026-11-17): applies Dennis round 1 on `020a37e10` (GO-WITH-FIXES, 5 HIGH, 5 MEDIUM,
6 LOW) with the coordinator's rulings. Section 19 maps each finding to its change. The DI and D-2
slices are re-cut for size (section 13).

Revision 3 (2026-11-17): applies Codex on `abc3c79f6` (NO-GO, two V1 findings). Section 20 lists the
changes.

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
- Nothing of the DI slices, DI-3 or the D-2 slices is built.

This plan carries the row 31 and row 32 parts of `plan/scan-checks` forward against today's main and
changes these things:

1. The D-2 work no longer waits on S3b (row 29) or RESULT C1 (row 62). S3b waits on L2, which waits on
   L1c, which waits on L1b.3 and WIN-RUNNER; none is started. D-2 creates the rescan helper that
   S3b's `--compare` will call (Q-A), and reaches exit 4 through the existing error map (Q-B).
2. Drift code goes in the `decoy scan` internals package `src/decoy/cli/scanning/` behind its public
   facade, not the frozen flat `src/decoy/cli/`. The scan-diff rules move there too (section 4.3).
3. `decoy.mask()` runs the same drift check as `decoy run` (section 4.2).
4. The engine releases are named (section 13.2) and the statistics choice is recorded (section 2).

When this plan passes, sections 4 and 5 of `plan/scan-checks` and its DI and D-2 rows point here.
Rows 30 (B-2) and 32c (M-1 to M-3) stay in `plan/scan-checks`.

## 1. Guarantee and non-goals

Guarantee:

- Row 31: with `post_scan.distribution` set, every mask table on a supported route gets value-free
  facts (`row_count`, and per column `null_rate`, `distinct_ratio`, `mean`, `std` where the strategy
  keeps them) on its masking input and its output. A fact that moved more than `tolerance_pct` is a
  breach. Under `on_breach: warn` the run delivers and reports it. Under `on_breach: fail` the run
  publishes nothing and exits 4. `fail` is accepted only from DI-2 on.
- Row 32: with `scan_baseline.on_drift` set, `decoy run` and `decoy.mask()` rescan the run's sources
  with the baseline's detectors and sampling before any masking read, and diff each table that the
  baseline and the config both name with the one scan-diff rule set. Under `warn` they report and
  run. Under `fail` they write nothing; `decoy run` exits 4 and `decoy.mask()` raises.
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
- Moving the scan-diff rules into the engine (row 80 F15). `decoy ci check` keeps its one-table
  compare; reusing the multi-table matching there is a follow-up (section 16).
- Library envelope baselines: they arrive with L2 (row 36) through the same reader.
- The run-result `scan_drift` entry from the CLI: RESULT C1 builds it from `ctx.drift_verdict`.
- The baseline evidence hash (row 30 B-2) and the md NER model (row 32c).

Expected size: engine about 1,800 lines in 4 slices, about 15 production files touched, 2 new
(`verification/postmask/distribution.py`, `execution/pipeline/_post_scan_distribution.py`). CLI
about 1,700 lines in 4 slices, 3 new files (`scanning/_diff.py`, `scanning/_drift.py`,
`run/_drift.py`). New public engine names: `DistributionCheck`, `NULLS_NOT_PRESERVED`,
`preserved_facts`, `distribution_findings`, `DistributionFinding`, and the two reason codes. New
names on the CLI `decoy.cli.scanning` facade: `ScanDiff`, `diff_scan_sets`, `rescan_and_diff`,
`read_scan_baseline` (unless B-2 adds it first), `check_drift`, `DriftVerdict`, `DriftBlockedError`.

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
  mean near 0 is not. `std` is the sample standard deviation (`ddof=1`, the pandas and Great
  Expectations default), from the Chan merge as `sqrt(M2 / (n - 1))`.
- Row 32 is not a statistical test. The owner model (2026-11-05) defines drift as what
  `scan diff --strict` flags: a PII bucket went up, a new high-PII field, or a new quasi-identifier
  group. The per-field rules are today's CLI `compute_scan_diff` (`src/decoy/cli/scan.py:865`),
  moved unchanged to `scanning/_diff.py` as `diff_scan_sets`. The new code is the rescan, the
  detector reproduction and the table matching.

## 3. Behaviour, row 31 DIST-INTEGRITY

### 3.1 Config

```yaml
post_scan:
  integrity: true
  distribution:
    tolerance_pct: 5        # required, 0 < n <= 100, strict number
    on_breach: warn         # warn (default) | fail ("strict mode", from DI-2)
```

- `distribution` without `integrity: true` is refused at config load with the existing
  `config.post_scan_inactive`.
- From DI-1b until DI-2, `on_breach` is `Literal["warn"]`: `fail` is refused at config load by the
  config schema, so no release accepts a strict setting that cannot block. DI-2 widens it to
  `Literal["warn", "fail"]`.
- `distribution` is dropped from the dump when absent, so existing configs keep their dump and plan
  hash. When set it is hashed, because it decides what blocks (scan-checks Q3).

### 3.2 Facts and where they are measured

Per mask table and per column whose strategy keeps the fact. Counts and aggregates only.

| Fact | Breach when |
|---|---|
| `row_count` (every mask table) | `abs(out - expected) / expected` above n%, with `expected = src - quarantined` |
| `null_rate` | absolute change above n percentage points |
| `distinct_ratio` (distinct / non-null) | absolute change above n percentage points |
| `mean` (numeric on both sides) | `abs(out - src) / src_std` above n%; `abs(out - src) / abs(src)` when `src_std` is 0 |
| `std` (numeric on both sides, `ddof=1`) | relative change above n% |

Undefined and non-finite cases. Each is one report row with `delta_pct: null` and the severity
given here. No row ever holds NaN or Infinity; the report passes a strict JSON round trip
(`allow_nan=False`).

| Case | Severity |
|---|---|
| `row_count`: `expected` and `out` both 0 | `info`, `delta_pct: 0.0` (not null) |
| `row_count`: `expected` 0 and `out` above 0 | breach (`warning`, or `fail` under `fail`) |
| `null_rate`: a side has 0 rows | `info` |
| `distinct_ratio`: both sides have 0 non-null cells | `info` |
| `distinct_ratio`: exactly one side has 0 non-null cells | breach |
| `mean` or `std`: a side has fewer than 2 numeric non-null cells | `info` |
| `mean`: `src_std` 0 and `src` mean 0, output mean not 0 | breach |
| `mean`: `src_std` 0 and both means 0 | `info`, `delta_pct: 0.0` |
| `std`: `src_std` 0 and output std above 0 | breach |
| A moment is not finite in the source (source origin; the output may be either) | `info` |
| A moment is finite in the source and not finite (inf or NaN) in the output | breach (`warning`, or `fail` under `fail`) |
| Non-numeric column where moments would apply | `info` |
| The fact could not be read (column read failed) | `error` (blocks only under `fail`, section 3.3) |

Where the facts come from:

- Source side: always `PostScanGate._source(name, caller_source, raw=True)`
  (`execution/pipeline/_post_scan.py:369`), in a source-only pass. That choke point applies the
  declared cast, drops declared-cast quarantined rows and reads `ctx.caller_sources`, the map after
  any subset. The lockstep pass pairs the sides only when row counts match (`_column_facts.py:190`),
  which fails after quarantine, so it is not used for the source side.
- Output side: the column-facts output pass that already runs (`_column_facts.py:176`), extended with
  null counts and merged moments.
- `row_count` subtracts the D8 quarantine count. `note_quarantined` (`_post_scan.py:286`) returns
  early today when the gate is deferred (`:290`); DI-1b keeps the per-table removed-row count when
  `distribution` is set. Deferred distribution runs are refused (3.3), so in practice the count is
  read on resident and streamed routes only. D8-removed rows stay in the source-side rate and moment
  facts (the source pass cannot know them on a streamed route); the docs say so.
- `_post_scan.py` is 583 lines against the engine's 600-line module aim. DI-1b first creates
  `execution/pipeline/_post_scan_distribution.py` and puts all distribution glue there: the
  source-only pass driver over `_source`, the per-table D8 count store, and the two bind-time refusal
  predicates. `_post_scan.py` gains only the calls and stays under 600.

Which facts apply comes from the one behaviour contract, not a second table:

- `distribution_behavior_for(strategy, provider_config)` (`contracts/distribution_behavior.py`):
  `preserves_all` gives distinct_ratio and moments, `preserves_cardinality_only` gives
  distinct_ratio, every other label gives neither. `null_rate` applies unless the strategy is in a new
  frozenset `NULLS_NOT_PRESERVED` in the same module.
- One rule overrides the label: `categorical` (weighted or `from_profile`) gets only `row_count` and
  `null_rate`, whatever its label. It draws a fresh value per row from weights, so its distinct ratio
  and moments match the source only in expectation; a small correct table would breach. The rule
  sits in `preserved_facts` with that reason in its docstring.
- One function `preserved_facts` in `verification/postmask/distribution.py` derives the set. A column
  with `when:` gets only `row_count` and, if eligible, `null_rate`.
- `group_key` is relabelled from `preserves_cardinality_only`
  (`contracts/distribution_behavior.py:142`) to `destroys_frequency`: its output cardinality is that
  of its `group_by` column. The `pipeline_config_hash` does not move. The compiled plan YAML does,
  because `plan/_serialize.py:165` emits the label. The golden pin
  `tests/unit/providers_v2/test_distribution_behavior_metadata.py` moves, with a changelog line.

Facts per strategy:

| Strategy | Label | Keeps nulls | Facts |
|---|---|---|---|
| passthrough, shuffle | preserves_all | yes | all five |
| categorical (any form) | preserves_all when weighted or `from_profile`; other otherwise | yes | row_count, null_rate |
| hash, fpe, tokenize | preserves_cardinality_only | yes | row_count, null_rate, distinct_ratio |
| faker, bucketize, truncate, geo_generalize, code_set, bucket_perturb, top_code, date_shift, text_mask, text_redact, nested, redact | other labels | yes | row_count, null_rate |
| joint_mask, group_key, windowed_date, grouped_series, derived, derived_aggregate, formula | other labels | no | row_count |

Generate tables have no source and are skipped.

### 3.3 Outcomes

- The post-scan report (`post-scan-integrity/v3`) gets an optional `distribution` section: one row
  per checked fact with `table`, `column` (null for `row_count`), `fact`, `severity` (`info`,
  `warning`, `fail`, `error`) and `delta_pct` rounded to 0.1 or null (3.2). No source or output mean,
  std or rate is written.
- Severity is decided once, in `distribution_findings`, from `on_breach` (the NER promotion pattern,
  `verification/postmask/_model_findings.py:244`). `post_scan_verdict`
  (`verification/postmask/_blocked.py:224`) blocks on any `fail` or `error` row in the section and
  gets no new argument.
- DI-1b writes `warning` rows only; the config refuses `fail` until DI-2.
- `warn`: the run delivers; the `post_scan_integrity` run-result check is `warned`; the CLI prints one
  line per breach naming table, column and fact.
- `fail` (DI-2): blocks before commit with new `post_scan.distribution_breach`; nothing is
  published; exit 4 through `PostScanBlockedError` (CLI `src/decoy/cli/run/_errors.py:187`).
  `block_location` names `table.column (fact)`.
- An `error` row blocks with `check_error` under `fail`; under `warn` it is written as `warning`.
- Refusals in `bind_gate` (`_post_scan.py:496`), only when `distribution` is set, before any route
  read or output (both in DI-1b): a transform-bearing mask table (existing
  `runtime.post_scan_integrity_transforms_unsupported`); a `source_loader` run or any other deferred
  gate (new `runtime.post_scan_distribution_deferred`). A config without `distribution` keeps
  today's behaviour on both. The routing-facts profile (`execution/pipeline/_routing_facts.py:89`)
  may already have read sources before dispatch (`execution/_pipeline_route_dispatch.py:72`), so the
  claim is "before any route read".
- Unreadable sink: refused before start by the existing `runtime.post_scan_integrity_sink_unreadable`.
- CLI `--chunked`: refused before any source is opened by the existing chunked-integrity refusal
  (`src/decoy/cli/run/_execute.py:53`); its text names distribution too.

## 4. Behaviour, row 32 DRIFT

### 4.1 Config (built in D-1)

```yaml
scan_baseline:
  path: scans/customers-baseline.json
  schema: scan-set/v1
  on_drift: warn            # warn | fail; absent = no check
```

### 4.2 Where the check runs

One check, `check_drift(config_dict, base_dir, baseline)`, on the public facade
`decoy.cli.scanning`. Two callers, both thin:

- `decoy run` (`src/decoy/cli/run/_prepare.py`), through `run/_drift.py`, which prints the warn lines
  and stores `ctx.drift_verdict` (a new `RunContext` field).
  - Baseline read: on the `--duckdb-source` path, right after `check_static_before_acquire`
    (`_prepare.py:376`) and before the database is opened, with `on_drift` taken from the config that
    call returns; otherwise right after `check_before_run` (`_prepare.py:398`), with `on_drift` from
    `ctx.config_dict`. Never from `ctx.raw`. A gate refusal therefore always wins over a missing
    baseline.
  - Rescan: right after `_require_local_io_endpoints(ctx.config_dict)` (`_prepare.py:546`) and before
    `_check_chunked_tables` and `_load_sources_from_config` (`_prepare.py:550`, `:553`). A cloud
    source is refused before any rescan read.
- `decoy.mask()` (`src/decoy/api.py:393`): after the config is validated and any in-memory `data` is
  staged to a file, it calls `_require_local_io_endpoints(config_dict)` and then `check_drift`,
  immediately before `_load_sources_from_config` (`src/decoy/api.py:582`). A warn verdict becomes one
  `warnings.warn` per drifted table with the same fixed text; a fail verdict raises
  `DriftBlockedError`. A staged in-memory frame is rescanned from its staged file.

No `on_drift`: the baseline is never opened and nothing is rescanned. `--all` children check their
own YAML. `--sample` runs check. `--rows` previews do not.

### 4.3 The check

- Baseline read: `read_scan_baseline(config_dict, base_dir)` in `src/decoy/cli/io/_scan_set.py`
  reads the file once. A relative `scan_baseline.path` resolves against the YAML folder through the
  existing `resolve_path` (`src/decoy/cli/_sources.py`). The same bytes are parsed with
  `scan_set_from_data(json.loads(raw))` (`src/decoy/cli/io/_scan_set.py:78`). A document without
  `scan_schema` (the legacy `profile.to_dict()` shape that `scan_set_from_data` otherwise accepts) is
  refused with a fixed message: a legacy scan records no sampling or detectors, so it cannot be
  reproduced. D-2 reads bare `scan-set/v1` files; L2 adds library envelopes inside this same reader.
  If row 30 B-2 merges first, D-2 extends its `read_scan_baseline` instead of adding one.
- Descriptors: `resolved_source_config(config_dict, base_dir)["sources"]`
  (`src/decoy/cli/_sources.py:40`), the same descriptors the run reads, after `--duckdb-source`
  staging has replaced a database table with its staged Parquet.
- Table matching: a config table and a baseline table match when the config's table name equals the
  baseline `TableCore.name`. Matched tables are rescanned and diffed. A config table with no baseline
  table is drift kind `table_added`. A baseline table the config lacks is reported, not drift. When
  no config table matches any baseline table, the verdict is one drift entry, kind
  `no_common_table`, with one message ("the baseline shares no table with this pipeline"), not one
  `table_added` per table.
- Detectors: the rescan uses the detector set the baseline recorded in `ScanSetCore.detectors`
  (regex; classifier and NER with model id and version), passed to `scan_sources(pre_scan=...)`. An
  empty list means regex only. If a recorded model is not installed, or its installed version differs
  from the recorded one, the check refuses with a fixed message naming the model id and both
  versions ("the drift check cannot reproduce the baseline detectors; rescan the baseline with this
  install"), exit 1, before any source row is read.
- Sampling: per matched table, the baseline's recorded `sample_strategy` and `sample_row_cap`. The
  rescan makes one `scan_sources` call per distinct (strategy, cap) pair, with `integrity=False` (no
  relationship facts; the diff does not use them). `head` reads a bounded prefix and `full` reads the
  whole table. `random` reads the whole table and keeps a fixed sample (`scan_set.py` docstring), so
  its cost is a full read.
- Diff: `diff_scan_sets(old_table, new_table)` per matched table. Drift means what
  `scan diff --strict` means: `ScanDiff.drift` is true.
- `rescan_and_diff` calls the engine `scan_sources` itself, not `run_scan`: `run_scan` is the
  `decoy scan SOURCES...` command body, which builds descriptors from file arguments and exits through
  `typer.Exit`.
- Failures inside the rescan map through the fixed-text helper `_failure_message`
  (`src/decoy/cli/scanning/_multi.py:228`, the class and engine table name only), and the drift error
  is raised after the `except` block closes, so it carries no `__context__`.
- Verdict: `DriftVerdict` holds status (`passed`, `warned`, `failed`), the reason code taken from the
  engine constants `reasons.pre_scan.DRIFT_DETECTED` and `reasons.pre_scan.DRIFT_BLOCKED`, and per
  drifted table the table name, drift kinds and field names. No score value is copied into it.
- Outcome: `warn` and drift prints one stderr line per drifted table naming the table, the drift kind
  and field names, and the run continues. `fail` and drift raises `DriftBlockedError` before any
  masking read; nothing is written; `decoy run` exits 4 through `run/_errors.py` (category none,
  blocking, as `PostScanBlockedError`) and `exit_codes.exit_code_for`.
- Parity: for the same YAML, sources and detectors, the verdict per table equals `diff_scan_sets`
  over a fresh `scan_sources` scan with the same descriptors, detectors and sampling. S3b's
  `decoy scan --compare --strict` will call `rescan_and_diff` and so agree.

## 5. Failure modes

### 5.1 Row 31

| Failure | Behaviour |
|---|---|
| D8 quarantine removes rows | `row_count` compares with source minus the recorded count; source-side facts keep those rows |
| Declared-cast quarantine | `_source(..., raw=True)` repeats the cast and drops the same rows; no D8 subtraction |
| Subset on | source side is `caller_sources`, the subset rows |
| Transform-bearing mask table with `distribution` | refused in `bind_gate`, existing code; without `distribution`, unchanged |
| `source_loader` or other deferred gate with `distribution` | refused in `bind_gate`, `post_scan_distribution_deferred` |
| `on_breach: fail` before DI-2 | refused at config load |
| `--chunked` from the CLI | refused before any source is opened |
| Float error over 100M rows | Chan merge in float64; no raw sum of squares |
| Undefined or non-finite fact | `delta_pct: null` with the severity in the 3.2 table; strict JSON |
| Masking turns a finite source moment into inf or NaN | breach, so `fail` blocks; never `info` |
| Weighted categorical on a small table | only `row_count` and `null_rate` are checked |
| A strategy's claimed null preservation is wrong | the generated null-position property test fails |
| Second source read on a lazy 100M input | cost stated in the docs; bounded to columns with a checked fact |
| Older reader of a stored report | v3 readers ignore the additive section |
| Value in an error message | errors keep the class name only, as the column suite does |

### 5.2 Row 32

| Failure | Behaviour |
|---|---|
| Baseline missing, unreadable, or another schema | exit 1 with the `load_scan_set` message naming `scan_baseline.path`, before any source is read or staged |
| Baseline is a legacy scan without `scan_schema` | exit 1, fixed message, before any source read |
| Config invalid and baseline missing | the gate refusal wins; the baseline is never opened |
| Cloud source with `on_drift` | the existing cloud refusal, before any rescan |
| Recorded detector model missing or another version | exit 1, fixed message naming model id and versions, before any source row |
| Config has a table the baseline lacks | drift kind `table_added` |
| Baseline has a table the config lacks | reported, not drift |
| No table in common | one drift entry `no_common_table` with one message |
| Rescan of a source fails | the `_failure_message` fixed text; exit by category; no chained context |
| Library off (`--no-library`) | still checks; the baseline is read by path |
| Large source | `head`: bounded prefix; `full` and `random`: a full read (docs) |
| `run/_prepare.py` near its 600-line cap (564 today) | two calls; the logic lives in `scanning/_drift.py` and `run/_drift.py` |

## 6. Design notes and choke points

- New structure: one pure engine module `verification/postmask/distribution.py` (fact derivation and
  findings), one engine glue module `execution/pipeline/_post_scan_distribution.py`, and three CLI
  modules. Principles applied: one place per fact (strategy facts derive from the behaviour contract
  plus one named override; severity decided once; per-field drift rules in `diff_scan_sets` only);
  typed config (`DistributionCheck`); no flag argument on `post_scan_verdict`.
- Where each drift fact lives: per-field rules in `scanning/_diff.py`; per-table matching, detector
  reproduction and sampling in `scanning/_drift.py` `rescan_and_diff`; the baseline read in
  `io/_scan_set.py`. `decoy ci check` (`src/decoy/ci/adapters.py`) calls `diff_scan_sets` on one
  selected table and does not use the multi-table matching yet (follow-up, section 16).
- Choke point, DI source side: `PostScanGate._source`. Guard: DI-T8 route-parity cells plus DI-T6.
  Mutation MDI-8: read the supplied sources directly on one route.
- Choke point, DI refusals: `bind_gate`, through the predicates in `_post_scan_distribution.py`.
  Guard: DI-T8 and DI-T9. Mutation MDI-9: refuse only on the sequential route.
- Choke point, drift: `decoy.cli.scanning.check_drift`, the only way `decoy run` and `decoy.mask()`
  reach drift. Guard: sentry `tests/sentry/run/test_one_drift_rescan.py`. It walks the syntax tree of
  every module under `src/decoy/cli/run/` and `src/decoy/api.py`, top-level and function-body
  (lazy) imports alike, and fails on an import of `scan_sources`, `diff_scan_sets`,
  `compute_scan_diff` or `rescan_and_diff`, or of `decoy.cli.scanning._drift` or `._diff`. Listed
  shapes (recurring defect 5): `from x import y`, `from x import y as z`, `import x.y` then
  attribute access, and the same inside a function body. D-T3 and D-T11 prove both entries call
  `check_drift`. Mutation MD-5: call `diff_scan_sets` from `run/_drift.py`.

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
| Drift rules | `compute_scan_diff`, moved as `diff_scan_sets` | new rules or a second copy |
| Rescan | engine `scan_sources` with `pre_scan` | a run-local scanner |
| Source descriptors | `resolved_source_config` | a second path resolver |
| Rescan failure text | `_failure_message` | new error text |
| Baseline parse | `scan_set_from_data` | a second parser |
| Exit 4 | `RUN_EXIT_MAP`, `derive_outcome`, `exit_code_for` | a new exit code |

## 8. Placement

Engine (map: engine `CODEMAP.md` "Where things go"; `execution/` is frozen for new top-level files;
`execution/pipeline/` is the named cluster sub-package and takes the glue module).

| File | New or changed | Where things go line | Sits beside | Slice |
|---|---|---|---|---|
| `src/decoy_engine/contracts/distribution_behavior.py` | changed: `NULLS_NOT_PRESERVED`; `group_key` label | Versioned contracts | `_STATIC_BEHAVIOR` | DI-1a |
| `src/decoy_engine/verification/postmask/distribution.py` | new (~240): `preserved_facts` with the categorical override, `distribution_findings` with the 3.2 cases, `DistributionFinding`; `fail` severity added in DI-2; pure | detectors, profiling and post-mask checks (`verification/`); `postmask/` holds 13 modules, under the 25 limit | `residual_pii.py` | DI-1a, DI-2 |
| `src/decoy_engine/verification/postmask/_column_facts.py` | changed: source-only pass, null counts, Chan moments (`ddof=1`) | same line (`_column_facts.py` holds the per-column facts) | `column_distinct` | DI-1a |
| `src/decoy_engine/config/_post_scan.py` | changed: `DistributionCheck` (`on_breach: Literal["warn"]`), inactive rule, dump omission; widened in DI-2 | Config models (`config/_<topic>.py`) | `PostScanConfig` | DI-1b, DI-2 |
| `src/decoy_engine/execution/pipeline/_post_scan_distribution.py` | new (~150): source-only pass driver over `_source`, D8 count store, the two refusal predicates | Pipeline spine and routes (`execution/pipeline/`) | `_post_scan.py` | DI-1b |
| `src/decoy_engine/execution/pipeline/_post_scan.py` | changed: calls only; stays under 600 lines | same line | `_source`, `bind_gate` | DI-1b |
| `src/decoy_engine/verification/postmask/types.py`, `runner.py` | changed: report section and counts | same line | existing sections | DI-1b |
| `src/decoy_engine/reasons/runtime/_part3.py` | changed: `post_scan_distribution_deferred`, since UNRELEASED | Reason codes | existing runtime codes | DI-1b |
| `src/decoy_engine/verification/postmask/_blocked.py` | changed: verdict rows, `_ORDER`, `block_location` | same line (`_blocked.py` holds the one verdict) | NER block logic | DI-2 |
| `src/decoy_engine/reasons/post_scan/_part2.py` | changed: `distribution_breach`, since UNRELEASED | Reason codes | existing codes | DI-2 |
| `tests/snapshots/frozen_schemas/pipeline-config.schema.json` | changed: `distribution` (DI-1b), enum widened (DI-2) | frozen schema snapshot | existing keys | DI-1b, DI-2 |
| `changelog.d/<slug>.md` | new fragment per slice | changelog fragments (REG-RELEASE E1) | other fragments | each |

Proportionality pairs: `preserved_facts`, `distribution_findings` and the column-facts collectors
merge in DI-1a before their caller; the caller is the DI-1b glue module of this plan.

CLI (map: CLI `CODEMAP.md` "Where things go"; flat `src/decoy/cli/` is frozen and takes no file).

| File | New or changed | Where things go line | Sits beside | Slice |
|---|---|---|---|---|
| `src/decoy/cli/scanning/_diff.py` | new (~130, moved): `ScanDiff`, `diff_scan_sets` (was `compute_scan_diff`) and its bucket helpers | `decoy scan` internals (`scanning/_<noun>.py`) | `scanning/_multi.py` | D-2a |
| `src/decoy/cli/scanning/__init__.py` | changed: export `ScanDiff`, `diff_scan_sets` (D-2a); `rescan_and_diff`, `check_drift`, `DriftVerdict`, `DriftBlockedError` (D-2b) | same line (the public facade) | existing exports | D-2a, D-2b |
| `src/decoy/cli/scan.py` | changed: imports the diff from the facade; module-size `max` in `tests/sentry/baselines/module-size.json` shrinks from 1157 to the new count | command module (legacy, over the cap, may only shrink) | `_diff` command | D-2a |
| `src/decoy/ci/adapters.py` | changed: imports `diff_scan_sets` from the facade | CI adapters | existing import | D-2a |
| `src/decoy/cli/scanning/_drift.py` | new (~220): `rescan_and_diff`, `check_drift`, `DriftVerdict`, `DriftBlockedError` | `decoy scan` internals | `_multi.py` | D-2b |
| `src/decoy/cli/io/_scan_set.py` | changed: `read_scan_baseline` with the legacy refusal (or B-2's, extended) | Source readers (`io/_scan_set.py`) | `load_scan_set` | D-2b |
| `src/decoy/cli/run/_drift.py` | new (~70): calls `check_drift`, prints lines, sets `ctx.drift_verdict` | `decoy run` internals (`run/_<noun>.py`) | `run/_prepare.py` | D-2c |
| `src/decoy/cli/run/_prepare.py`, `run/_context.py` | changed: baseline read after the gate call, one check call after `_require_local_io_endpoints`; `drift_verdict` field | same line | existing phases | D-2c |
| `src/decoy/cli/run/_errors.py`, `src/decoy/cli/exit_codes.py` | changed: `DriftBlockedError` arm, exit 4 | same line; exit codes | `PostScanBlockedError` arm | D-2c |
| `src/decoy/api.py` | changed: `_require_local_io_endpoints` then `check_drift` before `_load_sources_from_config` | library API | `mask()` | D-2c |
| `tests/sentry/run/test_one_drift_rescan.py` | new sentry | Sentry test (`tests/sentry/run/`) | `test_one_run_reason.py` | D-2c |
| `src/decoy/cli/run/_render.py` | changed: breach lines | `decoy run` internals | post-scan lines | DI-3 |
| `src/decoy/cli/report.py` | changed: one bucket tuple (2,305 lines, over the cap; no growth beyond the tuple) | command module (existing) | integrity buckets | DI-3 |
| `src/decoy/cli/run/_execute.py` | changed: chunked refusal text | `decoy run` internals | `_ChunkedIntegrityError` | DI-3 |

Proportionality pair: the D-2b facade names merge before their callers; the callers are `decoy run`
and `decoy.mask()` in D-2c of this plan.

## 9. Enumerations

### Routes

- DI, engine: resident, chunked and out-of-core reach `PostScanGate`
  (`execution/pipeline/_post_scan.py:92`); every source side goes through `_source`
  (`_post_scan.py:369`). Generate tables: skipped.
- DI, refused when `distribution` is set: transform-bearing, `source_loader` and deferred gates in
  `bind_gate` (`_post_scan.py:496`, `_deferred` at `_post_scan.py:480`).
- DI, CLI: `--chunked` refused (`src/decoy/cli/run/_execute.py:53`); resident and out-of-core only.
- Drift, `decoy run`: baseline read at `src/decoy/cli/run/_prepare.py:376` (duckdb path) or
  `src/decoy/cli/run/_prepare.py:398`; rescan after `src/decoy/cli/run/_prepare.py:546`. `--rows`
  previews: not checked.
- Drift, `decoy.mask()`: before `src/decoy/api.py:582`.

### Fields

- New config keys: `post_scan.distribution.tolerance_pct`, `post_scan.distribution.on_breach`.
  Existing: `scan_baseline.on_drift` (`config/_scan_baseline.py:30`).
- Strategies needing a fact rule: the handlers in `SCALAR_HANDLERS`
  (`execution/_strategies/__init__.py:48`); labels in `contracts/distribution_behavior.py:70`.
- Report fields per DI row: `table`, `column`, `fact`, `severity`, `delta_pct`.
- Baseline fields read by the drift check: `scan_schema`, `detectors`, per table `name`,
  `sample_strategy`, `sample_row_cap`, `fields`, `quasi_identifier_groups`, `reid_risk_score`.
- Check id `scan_drift` (`run_result/_model.py:183`), filled by RESULT C1 from `ctx.drift_verdict`.

### Exit paths

- DI `fail`: `post_scan_verdict` (`verification/postmask/_blocked.py:224`, order `_ORDER` at
  `_blocked.py:41`) raises `PostScanBlockedError`; CLI exit 4.
- DI refusals and `on_breach: fail` before DI-2: exit 1 (config) or runtime exit before any route
  read or output.
- DI with CLI `--chunked`: exit 1.
- Drift `fail`: `DriftBlockedError`, exit 4 through `run/_errors.py` and `exit_code_for`; raised to
  the caller of `decoy.mask()`.
- Drift baseline missing, legacy, or detectors not reproducible: exit 1 before any source row.
- Rescan source failure: exit by its category (1 or 3), fixed text.

### FK shapes

N/A: no slice reads or writes keys across tables. DI checks per column and per-table row counts;
drift diffs per table and the rescan runs with `integrity=False`.

### Output surfaces

- Post-scan report JSON: optional `distribution` section.
- CLI stderr: DI breach lines (`run/_render.py`), drift lines (`run/_drift.py`).
- `decoy.mask()`: one `warnings.warn` per drifted table under `warn`.
- `decoy report integrity`: the bucket tuple in CLI `report.py` gets `distribution`.
- Run result: `post_scan_integrity` check codes; `scan_drift` once RESULT C1 reads
  `ctx.drift_verdict`.
- Logs: none added.

## 10. Frozen contracts touched

| Contract | Change | Compatibility |
|---|---|---|
| Pipeline config schema (frozen snapshot) | `post_scan.distribution` (DI-1b, `warn` only), `on_breach` enum widened (DI-2) | optional, omitted when absent; noted in `docs/compatibility-contract.md` |
| Plan hash | `post_scan.distribution` hashed when set | absent keeps the hash (DI-T1) |
| Compiled plan YAML | `group_key` behaviour label | `pipeline_config_hash` unchanged; changelog line |
| `post-scan-integrity/v3` | optional `distribution` section | v3 readers ignore it |
| Reason registry | `runtime.post_scan_distribution_deferred` (DI-1b), `post_scan.distribution_breach` (DI-2), since UNRELEASED | `REGISTRY_VERSION` and reason manifests untouched; the release stamps them |
| `decoy-run-result/v1` | none new (D-1 added `scan_drift`) | none |
| CLI exit codes | none new (4 reused) | none |
| `decoy.mask()` library API | may raise `DriftBlockedError` when `on_drift: fail` is set | opt-in key; no change for configs without it |

## 11. Class table

| # | Class | Where it applies | Structure that closes it | Proof | Mutation |
|---|---|---|---|---|---|
| 1 | Value-bearing output | DI rows and lines; drift lines, warnings and verdict; errors | DI rows carry names and `delta_pct` only, built in one pure function; drift text from `ScanDiff` names; rescan errors through `_failure_message` | DI-T4, DI-T12, D-T6 canary sweeps | MDI-12, MD-6 |
| 2 | Cleanup missing on an exit path | drift `fail`; DI `fail` | drift stops before any output opens; DI uses the gate block-before-commit path | D-T3, DI-T9 | MD-3 |
| 3 | Shared state across batches | moment merge | pure Chan merge over per-batch tallies | DI-T3 | MDI-3 |
| 4 | Route parity and silent fallback | DI on each route; drift in `run` and `mask()`; drift vs a fresh scan | `_source` for every source side; central refusals; one `check_drift` with a sentry | DI-T8, DI-T9, D-T5, D-T11 | MDI-8, MD-5, MD-11 |
| 5 | Referential counts across tables | baseline vs config tables; quarantine and subset | name matching with `table_added` and `no_common_table`; D8 subtraction; `caller_sources` | D-T12, DI-T6, DI-T7 | MD-12, MDI-6, MDI-7 |
| 6 | Untrusted producer | hand-edited baseline; config values | strict reader, legacy refused, detectors checked against the install; strict `tolerance_pct` and enums | DI-T1, D-T8, D-T13 | MDI-1, MD-13 |
| 7 | Check then use (TOCTOU) | baseline read then parsed | one read; parse the same bytes | D-T9 | MD-9 |
| 8 | Weak tests | DI tests passing vacuously | each DI test has a breach and a no-breach cell | DI-T4 | MDI-4 |
| 9 | Refactor drift | configs without the new keys; the `compute_scan_diff` move | omission when absent; `scan diff` and `ci check` outputs byte-equal after the move | DI-T1, D-T14 | MDI-1b, MD-14 |
| 10 | Frozen contract drift | config schema, v3 report, registry | additive optional members; compatibility note | DI-T1, DI-T13 | MDI-13 |

Value-free errors (recurring defect 3): every new error raises after its `except` block closes;
DI-T12 and D-T6 assert `__cause__ is None and __context__ is None` on the new errors.

## 12. Acceptance tests (written first; each red on today's main)

"Red before" says why the test fails on `09f6d7c70` / `5b49510`. "Guard" tests pass before and must
keep passing. Each has a mutation that must turn it red.

### Row 31

| Id | Slice | Asserts | Red before | Mutation |
|---|---|---|---|---|
| DI-T2 | DI-1a | `preserved_facts` covers every label and every `SCALAR_HANDLERS` strategy; an unknown name in `NULLS_NOT_PRESERVED` fails; generated property test: every strategy claimed to keep nulls keeps the exact null positions on a null-bearing column; `joint_mask` in the set, `redact` not; `group_key` label is `destroys_frequency` | names absent | MDI-2: restore the `group_key` label; MDI-2b: mark `redact` null-destroying |
| DI-T3 | DI-1a | moments over batches cut at 1, 7 and 50,000 rows equal the whole-column mean and `ddof=1` std (pandas `Series.std()`) to 1e-9 | no moments | MDI-3: average per-batch means; MDI-3b: `ddof=0` |
| DI-T5 | DI-1a | `preserved_facts`: hash gives `distinct_ratio`, no `mean`; weighted and `from_profile` categorical give only `row_count` and `null_rate`; faker and redact give `row_count`, `null_rate`; joint_mask, group_key, windowed_date, grouped_series, derived, formula give `row_count` only; `when:` columns give `row_count` plus eligible `null_rate` | names absent | MDI-5: give every column all facts; MDI-5b: drop the categorical override |
| DI-T4 | DI-1a, DI-1b | facts level (DI-1a): equal frames give no breach at 1%; output mean 1.2x the source gives a `mean` breach at 5% with `delta_pct` set; one cell per row of the 3.2 undefined-case table gives the stated `delta_pct` and severity; a finite source column whose output mean or std is inf, and one whose output is NaN, each give a breach row with `delta_pct: null` (and DI-2 promotes it to `fail` under `fail`, DI-T9), while an inf already in the source gives `info`; every findings list survives `json.dumps(allow_nan=False)` and back. Pipeline (DI-1b): a test-only scaling handler in place of `SCALAR_HANDLERS["passthrough"]` gives a breach row; a weighted categorical column on 20 rows gives no `mean` or `distinct_ratio` row; canary sweep finds no cell value in the report | no section | MDI-4: compare the output with itself; MDI-4b: emit NaN for an undefined delta; MDI-4c: map an output-origin non-finite moment back to `info` |
| DI-T1 | DI-1b | `distribution` without `integrity: true` refused with `post_scan_inactive`; `tolerance_pct` 0, 101, `True`, `"5"` refused; `on_breach: block` refused; `on_breach: fail` refused (until DI-2); an omitted block keeps the old dump and plan hash; a set block moves it | unknown key | MDI-1: lax float; MDI-1b: always dump the block; MDI-1c: accept `fail` early |
| DI-T13 | DI-1b | frozen config schema snapshot holds `distribution` with its bounds and enum; reason fixture holds `post_scan_distribution_deferred` since UNRELEASED | snapshot lacks it | MDI-13: drop the field from the schema export |
| DI-T6 | DI-1b | (a) resident D8 quarantine drops 3 of 100 at 5%: no `row_count` breach, source `null_rate` counts 100; (b) streamed route records the same count; (c) declared-cast quarantine rows dropped on both sides | no section | MDI-6: skip the subtraction |
| DI-T7 | DI-1b | with subset on, the source side is the subset rows | no section | MDI-7: read the unsubset sources |
| DI-T8 | DI-1b | chunked and out-of-core give the same rows as resident; with `distribution`, a transform-bearing mask table is refused in `bind_gate` with the existing code before any route read or output; guard cell: the same transform-bearing config without `distribution` runs as today | no section | MDI-8: skip on streaming; MDI-8b: refuse transforms without `distribution` |
| DI-T9a | DI-1b | a loader run (teed sequential included) and any other deferred gate with `distribution` are refused with `post_scan_distribution_deferred` (spy at the route-dispatch boundary) | runs silently | MDI-9: refuse only on sequential |
| DI-T15 | DI-1b | `_post_scan.py` stays under 600 lines (module-size sentry, no ceiling raised) | guard | none (sentry) |
| DI-T9 | DI-2 | `fail` with a breach raises `PostScanBlockedError` with `distribution_breach` and publishes nothing; `warn` delivers with check `warned` | no block | MDI-9b: never promote to `fail` |
| DI-T10 | DI-2 | an `error` row blocks under `fail` with `check_error` and is written as `warning` under `warn` | no rows | MDI-10: drop error rows |
| DI-T11 | DI-2 | an unreadable sink with `distribution` is refused before start | guard | MDI-11: exempt distribution |
| DI-T14 | DI-2 | `on_breach: fail` accepted; reason fixture holds `distribution_breach` since UNRELEASED; `REGISTRY_VERSION` unchanged | refused | MDI-14: bump the registry version |
| DI-T12 | DI-3 | CLI e2e: `warn` prints one line per breach naming table, column and fact and exits 0; `fail` exits 4 and names `table.column (fact)`; `report integrity` lists the section; `--chunked` with `distribution` is refused before any source opens; canary sweep of stderr and `--json` | no output | MDI-12: print the measured mean |

### Row 32

D-T1 and D-T2 (config and `pre_checks`) shipped green with D-1 (#613) and stay as guards.

| Id | Slice | Asserts | Red before | Mutation |
|---|---|---|---|---|
| D-T14 | D-2a | after the move, `decoy scan diff` and `decoy ci check` give byte-equal output to today on the existing fixtures; `scan.py` line count is at or below the new baseline `max` | guard | MD-14: change a bucket rank in the move |
| D-T5 | D-2b | parity: for six fixture pairs the `rescan_and_diff` verdict per table equals `diff_scan_sets` over a direct `scan_sources` call with the same descriptors, detectors and sampling. Detector sets: (1) regex only, `head`; (2) regex only, `full`; (3) regex only, `random`; (4) regex + classifier; (5) regex + NER; (6) regex + classifier + NER. Pairs 4 to 6 use the test model stubs the scan-ml suite already loads | no helper | MD-5b: rescan with default detectors; MD-5c: drop only the classifier from the rebuilt `pre_scan` (pairs 4 and 6 go red) |
| D-T9 | D-2b | the bytes parsed are the bytes read (spy counts one open of the baseline); a relative `path` resolves against the YAML folder, not the working directory | no read | MD-9: read twice; MD-9b: resolve from cwd |
| D-T12 | D-2b | table matching: config table absent from the baseline gives `table_added`; baseline table absent from the config is reported, not drift; no common table gives exactly one `no_common_table` entry and one message | no helper | MD-12: one `table_added` per table |
| D-T13 | D-2b | detectors: a baseline recording an NER model that is not installed, one recording another NER version, one recording a classifier that is not installed, and one recording another classifier version each refuse with the fixed message before any source is opened (spy on the source open and on `scan_sources`); the regex + classifier + NER baseline rebuilds `pre_scan` with both models at their recorded versions (spy on the `scan_sources` argument); an empty `detectors` list rescans regex only | no helper | MD-13: fall back to the default detectors; MD-13b: skip the version check for the classifier only |
| D-T8 | D-2b, D-2c | baseline input (D-2b): a missing file, another `scan_schema` and a legacy document without `scan_schema` each refuse with exit 1 naming `scan_baseline.path`. Ordering (D-2c): invalid config plus a missing baseline exits with the gate refusal and never opens the baseline (spy); on `--duckdb-source` the baseline is read after `check_static_before_acquire` and before the database opens (spy), and the rescan reads the staged Parquet; a cloud source with `on_drift` gets the cloud refusal and no rescan (spy); `on_drift` comes from the validated config, not `ctx.raw` | no check | MD-8: read `on_drift` from `ctx.raw`; MD-8b: accept a legacy scan |
| D-T6 | D-2b, D-2c | stderr, `warnings.warn` text and `DriftVerdict` carry table and field names, never a value (canary sweep); a rescan whose source read fails gives the `_failure_message` text with the canary absent, and the raised error has no `__cause__` or `__context__` | no check | MD-6: echo a sample row; MD-6b: use `str(exc)` |
| D-T3 | D-2c | e2e: baseline from `decoy scan`, then a source gains a high-PII column: `on_drift: fail` exits 4 before any masking read (read spy) and writes no output; `warn` prints the drift line and runs | no check | MD-3: check after masking |
| D-T4 | D-2c | no drift: exit 0 and `ctx.drift_verdict.status == "passed"`; no `on_drift`: baseline never opened and no rescan (spy) | no check | MD-4: always rescan |
| D-T7 | D-2c | `--no-library` still checks; `--rows` does not; `--all` children each check | no check | MD-7: route through the library |
| D-T10 | D-2c | `exit_code_for(DriftBlockedError(...))` is 4 and `run/_errors.py` maps it to 4 | no type | MD-10: map to 3 |
| D-T11 | D-2c | `decoy.mask()` with `on_drift: fail` and drift raises `DriftBlockedError` before any source load (spy on `_load_sources_from_config`); with `warn` it emits one warning per drifted table and returns; with an in-memory DataFrame the staged file is rescanned; sentry `test_one_drift_rescan.py` fails on a seeded case per listed shape in `run/` and in `api.py`, including a function-body import | no check | MD-11: skip the check in `mask()`; MD-5: call `diff_scan_sets` from `run/_drift.py` |

## 13. Slices

At most 10 production files and about 800 lines each (tests counted). Risk per
`risk-and-exceptions.md`: R1 takes Codex-only review; R2 takes Dennis then Codex.

### 13.1 Slice table

| Slice | Repo | Row | Content | Prod files | ~Lines | Risk | Waits on |
|---|---|---|---|---|---|---|---|
| DI-1a | engine | 31 | prep, no config surface yet: `NULLS_NOT_PRESERVED` and `group_key` relabel; `preserved_facts` with the categorical override; source-only pass, null counts, Chan moments (`ddof=1`); `distribution_findings` (`warning` only) with every 3.2 case; changelog fragment | 3 | 700 | R2 (behaviour contract, data facts) | none |
| DI-1b | engine | 31 | `DistributionCheck` (`warn` only), frozen schema; `_post_scan_distribution.py` glue; report section in `types.py` and `runner.py`; D8 count; transform and deferred refusals when `distribution` is set, with `post_scan_distribution_deferred`; route, subset and quarantine cells | 7 | 700 | R2 (config schema, report shape) | DI-1a |
| DI-2 | engine | 31 | `on_breach: fail` accepted; `fail` severity; verdict blocks on `fail` and `error` rows; `_ORDER`; `block_location`; `distribution_breach`; engine docs (post-scan guide, compatibility note, CODEMAP lines for the two new modules) | 5 | 430 | R2 (blocking decision) | DI-1b |
| Release and repin | both | 31, 32 | daily train; repin checklist (memory engine-repin-checklist) | n/a | n/a | per train | 13.2 |
| D-2a | CLI | 32 | move `ScanDiff` and `compute_scan_diff` to `scanning/_diff.py` as `diff_scan_sets`, export from the facade, update `scan.py` and `ci/adapters.py`, shrink the `scan.py` module-size `max`; no behaviour change | 4 | 300 | R1 (pure move) | none |
| D-2b | CLI | 32 | `scanning/_drift.py` (`rescan_and_diff`, `check_drift`, `DriftVerdict`, `DriftBlockedError`); detector reproduction; table matching; `read_scan_baseline` with the legacy refusal; failure mapping; unit cells | 3 | 650 | R2 (reads source data, refusal rules) | D-2a; repin to engine 0.28.0 |
| D-2c | CLI | 32 | `run/_drift.py`, `_prepare.py` hooks, `ctx.drift_verdict`, `_errors.py` and `exit_code_for` arm, `decoy.mask()` hook, sentry, e2e cells, drift docs and `decoy explain exit-codes` text, CHANGELOG | 7 | 620 | R2 (refuses runs, library API) | D-2b |
| DI-3 | CLI | 31 | breach lines in `run/_render.py`; `report integrity` bucket; chunked refusal text; CLI docs and CHANGELOG; DI-T12 | 3 | 300 | R1 | repin to the release with DI-2 |

Order: DI-1a, DI-1b and DI-2 are serial (shared files). D-2a can start now. D-2b and D-2c need
engine 0.28.0 for D-1's codes and can run in parallel with the DI slices. D-2a is a separate slice
because it is a pure R1 move and keeping it apart holds D-2b under the size cap. DI-3 and open CLI PR
#301 (scan-ml C2a) both edit `run/_render.py`; whichever merges second rebases. D-2c and DI-3 share
no file.

Coordination with row 80: `plan/f15-bound-baseline` will later move `diff_scan_sets` from CLI
`scanning/_diff.py` into an engine `scan-diff/v1` module. D-2a's move stays as planned. F15 C1 moves
the rules on from `scanning/_diff.py` and leaves the `decoy.cli.scanning` facade names pointing at
the engine module, so `rescan_and_diff`, `scan.py` and `ci/adapters.py` keep their imports. If F15 C1
merges before D-2a, D-2a is dropped and D-2b imports from the facade F15 C1 leaves.

### 13.2 Engine releases

- Row 32 engine half (D-1, #613) is merged and unreleased. It ships in engine 0.28.0, the next
  daily-train release. D-2b repins the CLI to 0.28.0.
- Row 31 engine half is DI-1a, DI-1b and DI-2. It is complete in the first release that contains
  DI-2, planned as engine 0.29.0. A train that cuts after DI-1a only ships no config surface. A train
  that cuts after DI-1b ships `distribution` with `on_breach: warn` only; `fail` is refused at config
  load until DI-2. DI-3 repins the CLI to the release that contains DI-2.

## 14. Pre-mortem

- A fact derived wrongly for a strategy breaches correct runs. Guard: the 3.2 table, the categorical
  override, the generated null-position property test, DI-T5, and warn-only DI-1b before DI-2 can
  block.
- A large D8 quarantine moves the source-side facts. Guard: docs, DI-T6, the `row_count` subtraction.
- A 100M-row lazy input pays a second source read. Guard: docs; bounded to checked columns; moments
  streamed.
- A baseline taken with an NER model reports drift only because the rescan ran regex only. Guard:
  detector reproduction and D-T13.
- A pipeline renamed its tables and every table shows as added. Guard: `no_common_table` gives one
  message (D-T12).
- `decoy.mask()` skips the check. Guard: D-T11 and the sentry over `api.py`.
- S3b later writes its own rescan. Guard: the sentry and the roadmap note on row 29.
- RESULT C1 forgets the drift verdict. Guard: D-1's `pre_checks` accepts only `scan_drift`, and the
  roadmap note on row 62 names `ctx.drift_verdict`.
- B-2 and D-2b both add `read_scan_baseline`. Guard: the one-reader rule in 4.3; the second rebases.
- `run/_prepare.py` (564) and `_post_scan.py` (583) hit their caps. Guard: the logic lives in the new
  modules; the hosts gain calls only; no ceiling is raised.
- Users misread `tolerance_pct` (points for rates, standardized shift for means). Guard: the docs give
  one sentence per fact and one worked example.

## 15. Owner questions (taken on the recommended answer)

Carried from `plan/scan-checks` as decided there: Q1 `on_drift` on `scan_baseline`; Q2 exit 4; Q3
new keys hashed when set; Q4 the "selected shape" is this run's own masking input, so row 31's After
drops SCAN-LIB; Q5 the facts table (amended by the categorical override, ruling H1); Q6 strict mode
is `on_breach: fail`, not `delivery.mode`; Q7 `distribution` needs `integrity: true`; Q12 row 80
reuses `on_drift: fail`.

New in this plan:

| Q | Question | Answer taken (recommended) |
|---|---|---|
| Q-A | D-2 waits on S3b (row 29), which waits on L2, L1c and L1b.3. Wait, or build the rescan helper here? | Build it in D-2b at `scanning/_drift.py`; S3b's `--compare` calls `rescan_and_diff`. Rows 29 and 32 share one helper and row 32 leaves the library chain |
| Q-B | RESULT C1 (the CLI run-result document) is not built. Wait for it? | No. D-2c reaches exit 4 through the existing error map and stores `ctx.drift_verdict`; RESULT C1 turns it into the `scan_drift` check |
| Q-C | Statistic for "within n%" | Tolerance on five value-free facts (Deequ and Great Expectations model; standardized mean shift for `mean`; points for rates; `ddof=1`). Not PSI, KS or chi-square (section 2) |
| Q-D | Which release carries row 31's engine half, and what may an earlier train ship? | The first release containing DI-2, planned 0.29.0. An earlier train ships either no config surface (after DI-1a) or `distribution` with `on_breach: warn` only (after DI-1b), with `fail` refused at config load |
| Q-E | How many slices? | Engine: DI-1a, DI-1b, DI-2, each under about 800 lines after the review moves. CLI: D-2a (R1 move), D-2b, D-2c, DI-3; D-2 is split three ways because the move, the facade and the two-entry wiring together exceed 1,500 lines |
| Q-F | Does `decoy.mask()` refuse `on_drift` for in-memory `data`? | No. `mask()` stages in-memory data to a file before the source load, so the check rescans the staged file like any other source |
| Q-G | Is "no table in common" a refusal or drift? | Drift, one entry `no_common_table`: it blocks under `fail` and warns once under `warn` |

## 16. V2-LOG and follow-ups

- One shared `Literal["warn", "fail"]` for `ner_findings`, `on_breach` and `on_drift` (from
  scan-checks).
- Statistical drift of value shape against a library baseline (needs histogram fields in
  `scan-set/v1`; not in the row).
- DI on transform-bearing tables and `source_loader` runs (refused in V1).
- `decoy ci check` reuses `rescan_and_diff`'s multi-table matching instead of its one-table compare
  (`src/decoy/ci/adapters.py`).
- CLI `report.py` is 2,305 lines, over the design cap; DI-3 changes one tuple and adds no module.

## 17. Roadmap edits when this plan passes

- Row 31: "Plan `E:plan/drift` (`2026-11-17-drift-dist-integrity.md`), slices DI-1a, DI-1b, DI-2,
  DI-3; engine half in the release with DI-2 (planned 0.29.0)". After drops SCAN-LIB (Q4).
- Row 32: "Engine half MERGED (engine #613, D-1), in 0.28.0; CLI half D-2a, D-2b, D-2c per
  `E:plan/drift`". After becomes "0.28.0 repin".
- Row 29: "`--compare` calls `decoy.cli.scanning.rescan_and_diff` from D-2b; the diff rules are in
  `scanning/_diff.py`".
- Row 62: "RESULT C1 turns `ctx.drift_verdict` into the `scan_drift` pre-check".
- `plan/scan-checks` sections 4 and 5: a pointer to this plan.

## 18. Done when

- Every acceptance test in section 12 is green on the merged head of its slice, with its mutation
  recorded red on that head.
- Engine 0.28.0 and the release that contains DI-2 are cut and the CLI pins them.
- The roadmap edits in section 17 are made and the docs named in DI-2, D-2c and DI-3 are current.

## 19. Revision 2: Dennis round 1 resolutions (on `020a37e10`)

| Finding | Ruling | Change | Sections |
|---|---|---|---|
| H1 weighted and `from_profile` categorical claimed distinct ratio and moments | V1 | categorical gets only `row_count` and `null_rate` in `preserved_facts`, whatever its label; DI-T5 and DI-T4 cells; mutation MDI-5b | 3.2, 12 |
| H2 rescan underspecified | V1 | `rescan_and_diff` calls `scan_sources` itself with `resolved_source_config` descriptors; baseline detectors reproduced or refused with a fixed message; name matching; one `no_common_table` entry; D-T5 uses the same descriptors and detectors; D-T12, D-T13 | 4.3, 5.2, 12 |
| H3 hook position | V1 | rescan after `_require_local_io_endpoints`, before `_check_chunked_tables` and `_load_sources_from_config`; baseline read after `check_static_before_acquire` on the duckdb path, else after `check_before_run`; D-T8 cells | 4.2, 9, 12 |
| H4 `decoy.mask()` bypass | V1 | `check_drift` on the `scanning` facade; `run/_drift.py` and `api.py` are thin callers; D-T11; sentry covers `api.py` | 4.2, 6, 8, 12 |
| H5 strict setting accepted before it can block | DESIGN, taken | `on_breach: fail` refused at config load in DI-1b (DI-1a has no config surface); DI-2 lifts it; deferred refusal moved into DI-1b; DI-T1 cell; Q-D reworded | 3.1, 3.3, 13, 15 |
| M1 diff rules sit in the command module | V1 | `ScanDiff` and `diff_scan_sets` move to `scanning/_diff.py` (D-2a), exported from the facade; `scan.py` and `ci/adapters.py` updated; module-size `max` shrinks; "one place" claim corrected; CI multi-table reuse logged | 2, 6, 8, 13, 16 |
| M2 undefined and non-finite facts | V1 | `ddof=1`; every undefined case has `delta_pct: null` and a stated severity; strict JSON round trip in DI-T4 | 2, 3.2, 12 |
| M3 legacy and relative baselines | V1 | legacy scan refused; bare `scan-set/v1` only, envelopes with L2 through the same reader; relative path from the YAML folder; D-T8, D-T9 cells | 4.3, 12 |
| M4 transform refusal too broad | V1 | fires only when `distribution` is set; DI-T8 guard cell | 3.3, 12 |
| M5 rescan failure text | V1 | `_failure_message` fixed text, raised after the `except` block; D-T6 cell | 4.3, 12 |
| L1 wrong citations | V1 | `_column_facts.py:190` and `_model_findings.py:244` | 3.2, 3.3 |
| L2 unnamed verdict store | V1 | `ctx.drift_verdict` on `RunContext` | 4.2, 8 |
| L3 reason code strings | V1 | codes taken from `reasons.pre_scan` constants | 4.3 |
| L4 sentry misses lazy imports | V1 | the sentry walks function-body imports; listed shapes | 6, 12 |
| L5 "bounded by sample cap" wrong for `random` | V1 | `random` and `full` are full reads | 4.3, 5.2 |
| L6 `_post_scan.py` growth | V1 | `_post_scan_distribution.py` named up front; host gains calls only; DI-T15 | 3.2, 8, 12 |

Slice re-cut: DI-1b would have grown past 800 lines, so the pure facts and findings moved into DI-1a
and the config surface moved into DI-1b. D-2 would have grown to about 1,500 lines, so it split
into D-2a (R1 move), D-2b (facade) and D-2c (wiring).

## 20. Revision 3: Codex resolutions (on `abc3c79f6`)

| Finding | Change | Sections |
|---|---|---|
| A finite source moment that became inf or NaN in the output was `info`, so strict mode passed it | non-finite split by origin: source origin stays `info`; finite source with non-finite output is a breach (`fail` blocks under `fail`); DI-T4 cells for inf and NaN output; mutation MDI-4c (DI-1a) | 3.2, 5.1, 12 |
| Detector parity covered NER and regex only | D-T5 names six fixture pairs including regex + classifier and regex + classifier + NER; D-T13 adds classifier missing and classifier version refusals before any source is opened, and a spy on the rebuilt `pre_scan`; mutations MD-5c and MD-13b | 12 |
| Coordination with row 80 | `plan/f15-bound-baseline` C1 moves `diff_scan_sets` on from `scanning/_diff.py` into an engine `scan-diff/v1` module; D-2a stays | 13.1 |
