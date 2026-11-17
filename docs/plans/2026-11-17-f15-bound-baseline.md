Status: plan

# F15 bound baseline, strict-drift publication block and `scan-diff/v1` (row 80)

Rules consulted: `dev-rules/README.md`, `00-universal.md`, `risk-and-exceptions.md`,
`development-loop.md` (PLAN), `feature-dev.md`, `reuse-first.md`, `proportionality.md`,
`api-and-compatibility.md`, `cross-cutting-concerns.md`, `testing.md`, `architecture.md` (layout),
`workspace-and-vcs.md` (commit messages), `catalogs/recurring-defects.md`; memory notes
v1-bar-blocking-criteria, v1-threat-model-accidental-leaks, plan-defines-acceptance-tests,
develop-correctly-registries-and-sizing, best-practice-becomes-a-sentry, v1-scope-no-new-features,
v1-pragmatic-gate-priorities, engine-repin-checklist, decoy-parallel-ledger-files.

Revision 2 (Dennis round 1 on `e034c27c`). Section 17 lists each finding and its change. The CLI
half is rebuilt on drift plan revision 3 (`origin/plan/drift` `8f2d78bd`, section 13.1 ruling).

Bases (2026-11-17): engine `origin/main` `902968682` (last tag `v0.27.0`, `REGISTRY_VERSION`
1.29.0); CLI `origin/main` `419572a` (pins `decoy-engine==0.27.0`). Inputs read: CLI
`docs/ROADMAP.md` rows 29, 30, 32, 36, 56, 62, 76 and 80; CLI `docs/roadmap/row-detail.md` (F15
note); CLI `docs/qa/cli-v1-checklist.md` (SCAN-14); engine `plan/drift` at `8f2d78bd`
(`docs/plans/2026-11-17-drift-dist-integrity.md`, sections 4, 6, 8, 12 and 13.1); engine
`plan/scan-checks` (`docs/plans/2026-11-16-scan-checks.md`, section 2 and Q12); the master feature
spec F15 and its V1 scope note in the vault (`10_Projects/decoy/Market Expansion Specs/`);
`docs/publication.md`; the engine and CLI CODEMAP "Where things go" maps; the code cited below.

Risk: R2 overall (a new frozen artifact format, a config schema change, a check that refuses runs).
Per-slice tiers in section 13.

## 0. What row 80 adds, and what it does not

Row 80 reads: "F15: bound-baseline object, strict-drift publication block; scan-diff moves into an
engine `scan-diff/v1`". Its neighbours already cover part of it:

- Row 32 (DRIFT) owns the run-start check. Engine half D-1 is MERGED (engine #613, `03839e889`):
  `scan_baseline.on_drift` (`src/decoy_engine/config/_scan_baseline.py:30`), its plan-hash rule
  (`src/decoy_engine/plan/_compile.py:646`), the reason codes `pre_scan.drift_detected` and
  `pre_scan.drift_blocked` (`src/decoy_engine/reasons/pre_scan/_part1.py:19`), and the `scan_drift`
  check id (`src/decoy_engine/run_result/_build.py:232`). It ships in engine 0.28.0.
- The CLI half is planned in `plan/drift` (revision 3) as three slices, and that plan owns the CLI
  facade names (its section 13.1 ruling):
  - D-2a moves `ScanDiff` and `compute_scan_diff` from `scan.py` into `scanning/_diff.py` as
    `ScanDiff` and `diff_scan_sets`, exported from `decoy.cli.scanning`; `scan.py` and
    `ci/adapters.py` import them from the facade; the `scan.py` module-size max shrinks.
  - D-2b adds `scanning/_drift.py`: `rescan_and_diff`, `check_drift`, `DriftVerdict`,
    `DriftBlockedError`, detector reproduction, table matching (`table_added`, one
    `no_common_table` entry) and `read_scan_baseline` in `io/_scan_set.py`.
  - D-2c wires `decoy run` (`run/_drift.py`, the `_prepare.py` hooks, `ctx.drift_verdict`, the
    exit-4 arm) and `decoy.mask()` (`check_drift` before `_load_sources_from_config`).
- `plan/scan-checks` Q12 (owner, taken on the recommended answer): row 80's strict-drift publication
  block reuses `on_drift: fail`. There is one drift refusal, and it is row 32's.

So row 80 adds three things and no second refusal and no second set of CLI entry points:

1. **`scan-diff/v1` in the engine.** The per-field rules and the table matching move into one engine
   module with a versioned, value-free document. D-2a's `scanning/_diff.py` and D-2b's matching in
   `scanning/_drift.py` become thin calls into it; the facade names stay as D-2 defines them.
2. **The bound baseline.** Today `scan_baseline.path` points at a file and nothing pins its bytes.
   Rescanning drifted sources into the same path silently "approves" the drift. Row 80 adds
   `scan_baseline.sha256`, an engine `BoundBaseline` that is only built when the bytes match, and makes
   the digest required under `on_drift: fail`. The approval is the reviewed YAML change that sets the
   digest (the same model as a lock file pin). `check_drift` binds, so `decoy run` and `decoy.mask()`
   both get it.
3. **The strict block names the missing decision.** The engine decides the drift verdict
   (`evaluate_drift`). Under `on_drift: fail` the run stops before any masking read, so nothing
   reaches publication, and the error names each drifted `table.column` and its kind (QA item
   SCAN-14: "No output is published; the reason is named").

Non-goals (a review finding here becomes a follow-up item, not a blocker):

- An engine-side refusal inside the F22 commit path for callers that never ran the drift check
  (owner question Q5). V1's callers are `decoy run` and `decoy.mask()`, both through `check_drift`;
  the platform half of F15 (roadmap section 6, "Re-enable pre-scans" and "SCAN-MULTI platform
  half") takes it.
- Scheduled scans, review queues, suppressions with owner and expiry, inventory campaigns (platform,
  V2 per the vault scope note).
- Rename detection: a renamed column is a removed field plus an added field (Q8).
- A separate approval record file or library ref for baselines (Q1). L2 and L4a may add one later on
  top of the same digest.
- The run-result `scan_drift` entry: RESULT C1 (row 62) builds it from `ctx.drift_verdict`, whose
  type becomes the engine `DriftVerdict` in C1 (section 3.3).

Expected size: engine about 1,320 lines in 2 slices, 8 production files touched, 3 new
(`profiling/scan_diff.py`, `profiling/scan_set_read.py`, `profiling/bound_baseline.py`). CLI about
1,350 lines in 2 slices, 1 new production file (`scanning/_bind.py`). New public engine names,
exported from `decoy_engine.profiling` (as `ScanSetCoreRead` and `ScanSourceError` are today) and
not from the top-level package, whose `__init__.py` is at 599 lines against the 600-line module cap:
`SCAN_DIFF_SCHEMA`, `pii_bucket`, `diff_scan_tables`, `diff_scan_documents`, `TableDiff`,
`ScanSetDiff`, `FieldChange`, `FieldPresence`, `scan_diff_to_dict`, `ScanDiffCore`,
`ScanDiffCoreRead`, `read_scan_set`, `check_scan_finite`, `ScanSetReadError`, `BoundBaseline`,
`bind_baseline`, `BaselineBindingError`, `DriftVerdict`, `DriftFinding`, `evaluate_drift`. New
reason codes: `pre_scan.baseline_digest_mismatch`, `pre_scan.baseline_unreadable`,
`config.scan_baseline_unbound`, each since UNRELEASED.

## 1. Guarantee

- One implementation of the scan-diff rules and the table matching exists after slice C1: the
  engine's `profiling/scan_diff.py`. The CLI reaches it only through `scanning/_diff.py` and
  `scanning/_drift.py`, and the drift sentry fails on any other importer.
- For the same two scans, `decoy scan diff --json` gives the same `summary`, `changes` and `drift`
  values as before (numeric equality; section 3.4 lists the one representation change), the same text
  card and tables, and the same `--strict` exit code. This holds for `scan-set/v1` cores and for
  legacy profile documents.
- `scan-diff/v1` is a frozen format: one strict write model, a read model derived from it, a
  required tag with a stated minor rule, a corpus sample, a frozen-surface row.
- A config with `scan_baseline.on_drift: fail` must carry `scan_baseline.sha256`, or it is refused at
  config load. A run whose baseline file bytes do not hash to that digest stops with exit 1 before
  the rescan and before any source load, and nothing is written.
- Under `on_drift: fail`, a drifted source stops the run (and `decoy.mask()`) before any masking
  read. Nothing is staged for output or published, `decoy run` exits 4, and the message names each
  drifted table and, under it, each drifted `table.column` and its kind.
- No cell value reaches the diff document, a report, an error, a log line or the run result. The
  diff holds table and column names, PII scores (detector confidences), buckets, quasi-identifier
  group names, a re-identification risk delta and engine versions.

## 2. Established solutions

Search run (2026-11-17): codebase search `git grep -n -i "baseline|drift|sha256|fingerprint"`
over engine `src/` and CLI `src/`; the vault and `decoy-engine-archive` collections for "F15",
"bound baseline" and "strict drift"; known prior art below.

Found:

- **Content-digest pinning as approval.** pip hash-checking mode (`--require-hashes`: an install
  fails when a downloaded file's SHA-256 differs from the pinned one), W3C Subresource Integrity
  (`integrity="sha256-..."` on a script tag), container image digests (`image@sha256:...`) and
  Terraform's `.terraform.lock.hcl`. The pattern: a reviewed text file pins the exact bytes of an
  artifact, and any other bytes are refused, not merged.
- **Schema baselines with blocking checks.** TensorFlow Data Validation keeps an approved schema
  and reports anomalies of later data against it; Soda's schema check fails "when schema changes";
  dbt model contracts refuse a build whose columns differ from the declared contract. All three keep
  the baseline as a reviewed artifact and the comparison as a fixed rule set.
- **In the engine and CLI.** CLI `compute_scan_diff` (`src/decoy/cli/scan.py:865`, moved by D-2a to
  `scanning/_diff.py`) is the one rule set today. Engine `profiling/scan_set.py` already has the
  strict-writer, relaxed-reader pattern (`ScanSetCore`, `_relaxed` at
  `src/decoy_engine/profiling/scan_set.py:207`). Row 30 B-2 fingerprints the baseline file bytes
  with SHA-256 for the evidence manifest (`plan/scan-checks` B-T3). The F22 descriptor uses SHA-256
  content digests.

Choice and reasons:

- The bound baseline is a digest pin in the pipeline YAML (`scan_baseline.sha256`), as pip and SRI
  pin artifacts. The approval is the reviewed YAML change, so no second approval store, role model or
  record kind is needed in V1. The digest is SHA-256 over the raw file bytes, the same value B-2
  writes as the evidence fingerprint, so one number identifies the baseline in the config, the
  evidence and the error.
- The rule set moves unchanged. Row 32 and the owner model (2026-11-05) define drift as what
  `scan diff --strict` flags, plus `table_added` and `no_common_table` from `plan/drift`. No rule is
  added or relaxed by the move.

## 3. Behaviour

### 3.1 `scan-diff/v1` (engine, slice E1)

New module `src/decoy_engine/profiling/scan_diff.py`, pure, no I/O:

- `pii_bucket(score) -> Literal["none", "low", "med", "high"]`: the CLI thresholds today
  (`src/decoy/cli/scan.py:390`): `None` is `none`, `>= 0.6` high (the engine's
  `PII_CANDIDATE_THRESHOLD`), `>= 0.3` med, `> 0` low. `decoy scan fields` and `show` use it through
  the facade.
- `diff_scan_tables(old, new) -> TableDiff`: a line-for-line port of `compute_scan_diff` over two
  table dicts. It reads only `fields[].name`, `fields[].pii_score`, `quasi_identifier_groups` and
  `reid_risk_score` and does no core validation, so a legacy profile table (int scores, no
  `scan_schema`) diffs as it does today. Scores are kept as floats (`float(score)`; a missing score
  compares as `0.0`). Fields use today's attribute names: `added_rows`, `removed_rows`,
  `pii_increased`, `pii_decreased`, `qi_added`, `qi_removed`, `risk_delta`, `new_high_pii`; property
  `drift` and `drift_kinds`. Change rows are `FieldChange(name, old_score, new_score, old_bucket,
  new_bucket)`; added and removed rows are `FieldPresence(name, pii_score, pii_bucket)`. Each has
  `as_dict()` with today's key order.
- `diff_scan_documents(baseline, current, *, tables=None) -> ScanSetDiff`: the set-level compare,
  with the table matching D-2b specifies (`plan/drift` 4.3). A table matches when the names are
  equal. Matched tables (or the `tables` selection) get a `TableDiff`. A current table the baseline
  lacks is `tables_added` (drift kind `table_added`). A baseline table the current set lacks is
  `tables_removed` (reported, not drift). When no current table matches any baseline table, the
  result has exactly one set-level drift kind `no_common_table`, `no_common_table: true`, and an
  empty `tables_added` (the single-entry rule). `detectors_changed` is true when the two sets'
  `engine_version` or `detectors` runs differ; it is information, not drift (Q7).
- Drift kinds, a closed `Literal`: per table `pii_bucket_increased`, `new_high_pii_field`,
  `new_quasi_identifier_group`; per set `table_added`, `no_common_table`.
- `scan_diff_to_dict(diff: ScanSetDiff) -> dict` validates through `ScanDiffCore` (strict write
  model, unknown fields refused) and returns the document with `scan_diff_schema: "scan-diff/v1"`.
  `ScanDiffCoreRead` is derived from it with unknown fields ignored, through the same `_relaxed`
  helper `ScanSetCoreRead` uses (a sibling import inside `profiling/`, not another package's
  private module). `scan_set.py` itself is not edited: it is at the 600-line cap.
- Tag rule (mirrors `scan-set/v1`): a reader accepts `scan-diff/v1` and `scan-diff/v1.<minor>`
  (`re.fullmatch(r"scan-diff/v1(\.[0-9]+)?")`), refuses a missing tag, another major and any tag
  with trailing text. Unknown members are ignored. A drift kind the reader does not know (one a
  later minor could add) is refused with fixed text ("scan-diff document holds an unknown drift
  kind"), because a reader that drops a kind could report a drifted diff as clean (Q16).

New module `src/decoy_engine/profiling/scan_set_read.py`:

- `read_scan_set(data) -> dict`: the tag rule the CLI applies today
  (`src/decoy/cli/io/_scan_set.py:122`, `scan-set/v1` or a `scan-set/v1.<minor>` tag), then
  `ScanSetCoreRead`. Every refusal is `ScanSetReadError` (a `ValueError`) with a `kind` member
  (`missing_tag`, `unsupported_tag`, `invalid`, `non_finite`) and fixed text, raised after the
  `except` block closes.
- `check_scan_finite(data) -> None`: the one non-finite walk (NaN and Infinity anywhere in the
  document), raising `ScanSetReadError(kind="non_finite")`. `read_scan_set` calls it first; the CLI
  calls it once before its core-or-legacy branch, so legacy documents get the same check.

Document shape (`scan-diff/v1`):

```json
{
  "scan_diff_schema": "scan-diff/v1",
  "baseline_engine_version": "0.27.0",
  "current_engine_version": "0.29.0",
  "detectors_changed": false,
  "drift": true,
  "drift_kinds": [],
  "no_common_table": false,
  "tables_added": [],
  "tables_removed": [],
  "tables": [
    {"table": "customers", "drift": true,
     "drift_kinds": ["new_high_pii_field"],
     "added": [{"name": "alt_email", "pii_score": 0.91, "pii_bucket": "high"}],
     "removed": [], "pii_increased": [], "pii_decreased": [],
     "qi_added": [], "qi_removed": [], "risk_delta": null}
  ]
}
```

Top-level `drift_kinds` holds the set-level kinds; each table entry holds its own.

### 3.2 The bound baseline (engine, slice E2)

Config:

```yaml
scan_baseline:
  path: baselines/customers.scan.json
  schema: scan-set/v1
  sha256: "3f1c...e9"   # 64 lowercase hex, quoted; required when on_drift is fail
  on_drift: fail
```

- `sha256` is optional, a strict `str`, `re.fullmatch(r"[0-9a-f]{64}")`, omitted from the dump when
  absent, so every config without it keeps its dump and plan hash. An unquoted all-digit digest
  parses as a YAML integer and is refused by the strict type; `decoy scan bind` always prints it
  quoted.
- `on_drift: fail` without `sha256` is refused at config load with `config.scan_baseline_unbound`
  (a `PydanticCustomError`, as `config.post_scan_inactive` is built in
  `src/decoy_engine/config/_pre_scan.py:58`), naming the field, never a value. `on_drift: warn`
  without it is accepted and the verdict says the baseline is not bound.
- Compatibility: `on_drift` ships in 0.28.0 without a digest rule, so requiring the digest under
  `fail` in the next release is a tightening of a released key. It is allowed because the engine is
  pre-GA (`decoy_engine.is_pre_ga()`, `src/decoy_engine/release.py:53`; CLAUDE.md "Pre-GA = hard
  delete"). E2 records it as a breaking-change changelog fragment and a note in
  `docs/compatibility-contract.md` (Q2).
- Plan hash: when `on_drift` is set, the hashed block becomes `{on_drift, sha256}` (sha256 only when
  present). A re-approved baseline changes which drift blocks, so it changes the hash; the path and
  schema stay out (Q4). A consequence: re-binding a baseline changes the plan hash, so a run
  interrupted before the re-bind cannot resume after it (its resume fingerprint no longer matches);
  the drift guide says so.
- New module `src/decoy_engine/profiling/bound_baseline.py`:
  - `bind_baseline(raw: bytes, block) -> BoundBaseline`, in this order: SHA-256 of `raw`; when
    `block.sha256` is set and differs, `BaselineBindingError` with
    `pre_scan.baseline_digest_mismatch`; then `json.loads(raw)` and `read_scan_set`, any failure
    `BaselineBindingError` with `pre_scan.baseline_unreadable` (a legacy profile without
    `scan_schema` is unreadable here: it records no sampling or detectors). Both errors carry the
    code and fixed text naming `scan_baseline.sha256` or `scan_baseline.path` (the config keys),
    never the file path, the bytes or either digest, and have no `__cause__` or `__context__`.
    `BoundBaseline` is frozen: `sha256`, `bound` (the YAML pinned it), `on_drift`, the parsed scan
    dict. Only `bind_baseline` builds one (constructor guard, as `PreparedDeclaredSources` does).
  - `evaluate_drift(bound, current) -> DriftVerdict`: `diff_scan_documents(bound.scan, current)`;
    `status` `passed` (no drift), `warned` (drift under `warn`, code `pre_scan.drift_detected`) or
    `failed` (drift under `fail`, code `pre_scan.drift_blocked`). `findings` is a sorted tuple of
    `DriftFinding(table | None, column | None, kind)` (table `None` only for `no_common_table`);
    `drifted_tables` gives per table its kinds and field names (the shape D-2b's lines print);
    `diff` is the `ScanSetDiff`; `baseline_sha256` and `bound` are carried for the message and for
    RESULT C1.
- `starter_config(..., baseline_sha256=None)` writes `sha256` into the block when given (refused
  unless 64 lowercase hex), so `decoy scan --emit-config` (row 29) can write a bound block when it
  is built.

### 3.3 The strict-drift publication block (CLI, slices C1 and C2)

Hook positions stay D-2's (`plan/drift` 4.2): on the `--duckdb-source` path the baseline bytes are
read right after `check_static_before_acquire` (`src/decoy/cli/run/_prepare.py:376`), otherwise
right after `check_before_run` (`src/decoy/cli/run/_prepare.py:398`); `check_drift` runs right after
`_require_local_io_endpoints` (`src/decoy/cli/run/_prepare.py:546`), before `_check_chunked_tables`
and `_load_sources_from_config`. `decoy.mask()` calls `check_drift` before `_load_sources_from_config`
(`src/decoy/api.py:582`). Row 80 changes only the inside of `scanning/_drift.py` and the readers:

- `read_scan_baseline` (D-2b, `io/_scan_set.py`) returns the bytes only. It no longer parses
  (C1). `bind_baseline` is the one parse.
- `check_drift` order (C1): `bind_baseline(raw, block)` (digest, then parse), then D-2b's detector
  reproduction from `bound.scan["detectors"]`, then the rescan, then `evaluate_drift(bound, rescan)`.
  A digest mismatch or unreadable baseline raises `BaselineBindingError` before the rescan and
  before any source load. In `decoy run` it exits 1: C1 adds `BaselineBindingError` to
  `usage_error_types()` (`src/decoy/cli/exit_codes.py:245`), the one tuple the exit map and the run
  error arm in `run/_errors.py` both read. `decoy.mask()` raises it to the caller.
- `rescan_and_diff` keeps D-2b's descriptors, detector reproduction and per-(strategy, cap) rescans
  and calls engine `diff_scan_documents` for the matching and diff. D-2b's CLI matching (its
  `table_added` and `no_common_table` code) is deleted (C1).
- `DriftVerdict` on the facade becomes a re-export of the engine type (C1), so `ctx.drift_verdict`
  changes shape from D-2b's dataclass (status, code, per-table entries) to the engine verdict
  (status, code, `findings`, `drifted_tables`, `bound`, `baseline_sha256`, `diff`). RESULT C1 (row
  62) reads the engine shape; section 16 carries the roadmap note.
- `failed`: `DriftBlockedError` (D-2b's type, exit 4 through D-2c's arm). Output (C2): D-2's one line
  per drifted table stays; under each table, one line per finding as `table.column (kind)`, and
  `table (table_added)` or `no table in common (no_common_table)` for set kinds; at most 10 finding
  lines in total, then `and N more`; then one hint line: rescan, review with `decoy scan diff`, and
  re-bind with `decoy scan bind`. The `--json` error object carries `pre_scan.drift_blocked`.
- `warned`: the same lines on stderr; `decoy.mask()` keeps one `warnings.warn` per drifted table,
  its text now including that table's finding lines. One formatter in `scanning/_drift.py` builds the
  lines for both callers.
- Because the stop is before any masking read, `publish_unit`
  (`src/decoy_engine/publication/_publish.py:199`) is never reached: nothing is published.

`decoy scan bind SCAN` (C2), in new `scanning/_bind.py`: reads the file bytes once, calls
`bind_baseline` on them with an unbound block (so a legacy profile or another schema is refused with
the engine's fixed text), and prints the `scan_baseline:` block (path as given, schema, the digest
in double quotes) for the user to paste. `--json` prints `{command, status, path, schema, sha256}`.
Errors exit 1 (`EXIT_USAGE`). It never edits a YAML file (Q9).

### 3.4 `decoy scan diff`, `decoy ci check` and the scan readers (CLI, slice C1)

- `scanning/_diff.py` keeps D-2a's names. `diff_scan_sets(old_table, new_table)` calls engine
  `diff_scan_tables` and returns the facade `ScanDiff` with today's attributes (rows as dicts built
  by `as_dict()`). `pii_bucket` is re-exported from the facade for `scan fields` and `show`.
- `decoy scan diff OLD NEW` passes both full documents with `tables=[selected]` to a facade helper
  that calls `diff_scan_documents` once and returns the `ScanDiff` for the table plus the
  `scan-diff/v1` document, so the document carries both sets' `engine_version` and the
  `detectors_changed` member (M1). Text card, tables, `--strict` exit 4 and `--table` are unchanged.
- `--json` keeps every key and value; it gains one additive member `scan_diff` holding that document
  (Q6). The `summary` and `changes` payload builder moves from `scan.py` into `scanning/_diff.py`
  with it. The release-freeze shape snapshot and `CHANGELOG.md` move together.
- One representation change: a change row whose score was missing printed `0` and now prints `0.0`
  (the engine keeps scores as floats), and a legacy int score prints as a float. JSON numeric
  equality holds and the text output is identical; the CHANGELOG says so (Q11). D-2a's byte-equal
  guard D-T14 is updated in C1 for exactly this case.
- `decoy ci check` drift (`src/decoy/ci/adapters.py:158`) keeps its D-2a import of
  `diff_scan_sets`; rule ids, message ids and counts are unchanged.
- CLI `io/_scan_set.py`: `scan_set_from_data` calls `check_scan_finite` once before the core-or-legacy
  branch; `_from_core` delegates to `read_scan_set`. It catches `ScanSetReadError` and maps its
  `kind` to the CLI's current messages (`scan_schema ... not supported` and the others), so no user
  text changes (M3). The legacy-profile branch stays in the CLI.

## 4. Failure modes

| Failure | Behaviour |
|---|---|
| Baseline file replaced (drifted sources rescanned into the same path) | digest mismatch, exit 1, `pre_scan.baseline_digest_mismatch`, before the rescan and any source load |
| Baseline reformatted (same content, new bytes) | digest mismatch; a reviewed re-bind is required (Q3) |
| `on_drift: fail` with no `sha256` | refused at config load, `config.scan_baseline_unbound`; `decoy validate` reports it |
| `sha256` uppercase, 63 chars, a trailing newline, or an unquoted all-digit value | refused at config load (anchored match, strict string) |
| Baseline is a legacy profile or `scan-set/v2` | `pre_scan.baseline_unreadable`, exit 1 |
| Baseline or a `scan diff` input holds NaN or Infinity | `check_scan_finite` refuses, core and legacy alike, with today's CLI message |
| Config has a table the baseline lacks | `table_added` finding; drift |
| Baseline has a table the config lacks | `tables_removed`; not drift |
| No table in common | one `no_common_table` finding; drift |
| Detector or engine upgrade between baseline and rescan | `detectors_changed: true`, not drift; D-2b still refuses a recorded model it cannot reproduce |
| Column renamed | removed plus added; drift only if the added field is high PII |
| More than 10 findings | first 10 by (table, column, kind), then `and N more` |
| `on_drift: warn` and baseline not bound | runs; the warn line says the baseline is not bound |
| `decoy.mask()` with a mismatched digest | `BaselineBindingError` before `_load_sources_from_config` |
| Re-bind after an interrupted run | the plan hash changes, so the run cannot resume; documented |
| A `scan-diff/v1.N` document with a drift kind this reader lacks | refused with fixed text (Q16) |
| A second diff copy or a direct engine call outside the two facade modules | the drift sentry fails |
| Column name that is data (misdeclared header the guard cannot see) | the stated `scan-set/v1` limit; the diff carries what the core carries |

## 5. Design notes and choke points

- New structure: three pure engine modules beside `scan_set.py` and one small CLI command module.
  One place per rule: buckets, drift kinds and table matching in `scan_diff.py`; the scan tag and
  non-finite rules in `scan_set_read.py`; the verdict in `evaluate_drift`; the digest check in
  `bind_baseline`. Design principle applied: single responsibility (the diff rules change for
  drift-policy reasons and now live apart from both the CLI command and the rescan); no variant
  registry, since the drift kinds are a closed set of five.
- Choke point, diff rules and verdict: engine `profiling/scan_diff.py` and `bound_baseline.py`,
  reached from the CLI only through `src/decoy/cli/scanning/_diff.py` and
  `src/decoy/cli/scanning/_drift.py`. Guard: drift's sentry
  `tests/sentry/run/test_one_drift_rescan.py`, extended in C1 (no second sentry file). Today it
  walks `run/` and `api.py`; C1 widens the walk to every module under `src/decoy/`, top-level and
  function-body imports alike, and adds: an import of `diff_scan_tables`, `diff_scan_documents`,
  `scan_diff_to_dict`, `pii_bucket`, `evaluate_drift`, `bind_baseline` or `BoundBaseline` from the
  engine fails outside the two allowlisted paths (exact paths, not names); a module that defines
  `compute_scan_diff`, `_pii_bucket`, `_bucket_rank`, `_BUCKET_RANK` or `_canon_qi` fails. Listed
  shapes (recurring defect 5): `from decoy_engine import x`, `from decoy_engine.profiling import x`,
  `from decoy_engine.profiling.scan_diff import x` (and `bound_baseline`), `from x import y as z`,
  `import decoy_engine.profiling.scan_diff as m` then attribute access, and each inside a function
  body. Each shape has a seeded failing case. Mutation MC-2: a local bucket function in `scan.py`;
  MC-2b: a function-body import of `bind_baseline` in `run/_drift.py`.
- Choke point, baseline binding: `bind_baseline` is the only builder of `BoundBaseline`, and
  `evaluate_drift` takes only a `BoundBaseline`, so a verdict cannot be computed on unbound bytes.
  Guard: F15-T7 constructor cell. Mutation MF-7b: allow direct construction.
- Choke point, scan tag and non-finite rules: `read_scan_set` and `check_scan_finite`. Guard: the
  existing G-ONE-SCAN-READER sentry (`tests/sentry/test_scan_reader.py`) keeps holding, and F15-T4
  pins the rules.

## 6. Reuse inventory

| Need | Reused | Not built |
|---|---|---|
| Diff rules | `compute_scan_diff` (D-2a's `diff_scan_sets`), ported line for line, then reduced to a call | new rules |
| Table matching | D-2b's rules (`plan/drift` 4.3), moved into the engine | a second matcher |
| Facade names and modules | D-2a `scanning/_diff.py`, D-2b `scanning/_drift.py` | new CLI entry points |
| Strict writer and relaxed reader | `ScanSetCore` pattern and its `_relaxed` helper | a hand-copied read model |
| Scan tag and read model | `ScanSetCoreRead`, the CLI tag rule | a second tag parser |
| Rescan and detector reproduction | D-2b `rescan_and_diff` through engine `scan_sources` | a run-local scanner |
| Baseline bytes | D-2b (or B-2) one read in `read_scan_baseline` | a second read |
| Refusal, exit 4 | D-2b `DriftBlockedError`, D-2c's arm | a new exit code or error path |
| Exit 1 | `usage_error_types()` | a new error arm |
| Drift codes and check id | D-1 (`drift_detected`, `drift_blocked`, `scan_drift`) | new drift codes |
| Config refusal shape | `PydanticCustomError` with a reason code, as `post_scan_inactive` | a custom exception path |
| Digest | `hashlib.sha256` over raw bytes, as B-2 | a canonical re-serialization |
| Corpus pinning across repos | CLI `ci/vendored.toml` byte pins | a hand-kept second fixture |
| Sentry | drift's `test_one_drift_rescan.py` | a second sentry file |

## 7. Placement

Engine (map: engine `CODEMAP.md` "Where things go"; `execution/` is frozen for new top-level files
and this plan adds none there; `profiling/` holds 18 modules, 21 after this plan, under the 25 cap.
Module sizes: no ceiling moves. `plan/_compile.py` is at 656 against its census ceiling of 666 and
E2 adds at most 4 lines there).

| File | New or changed | Where things go line | Sits beside | Slice |
|---|---|---|---|---|
| `src/decoy_engine/profiling/scan_diff.py` | new (~320): `pii_bucket`, `diff_scan_tables`, `diff_scan_documents` with the matching, types, `ScanDiffCore`, `ScanDiffCoreRead`, `scan_diff_to_dict` | Detectors, profiling | `scan_set.py` | E1 |
| `src/decoy_engine/profiling/scan_set_read.py` | new (~90): `read_scan_set`, `check_scan_finite`, `ScanSetReadError` (`scan_set.py` is at the 600-line cap and is not edited) | Detectors, profiling | `scan_set.py` | E1 |
| `src/decoy_engine/profiling/__init__.py` | changed (127 lines): exports; the top-level `decoy_engine/__init__.py` (599 lines) is not edited | Public API | `ScanSetCoreRead` export | E1, E2 |
| `src/decoy_engine/profiling/bound_baseline.py` | new (~180): `BoundBaseline`, `bind_baseline`, `BaselineBindingError`, `DriftVerdict`, `DriftFinding`, `evaluate_drift` | Detectors, profiling | `scan_diff.py` | E2 |
| `src/decoy_engine/config/_scan_baseline.py` | changed: `sha256`, unbound rule, dump omission | Config models | `on_drift` | E2 |
| `src/decoy_engine/plan/_compile.py` | changed: hash `sha256` with `on_drift` | Plan compile and checks | the `on_drift` hash rule | E2 |
| `src/decoy_engine/profiling/_starter_config.py` | changed: `baseline_sha256` | Detectors, profiling | `baseline_path` | E2 |
| `src/decoy_engine/reasons/pre_scan/_part1.py`, `src/decoy_engine/reasons/config/_part2.py` | changed: three codes, since UNRELEASED | Reason codes | `DRIFT_BLOCKED` | E2 |
| `tests/sentry/baselines/f29-producer-inventory.json`, `tests/fixtures/f29/producer-inventory.json` | changed: the new producer sites in `bound_baseline.py` and `_scan_baseline.py`, and any moved line numbers in edited producer files (an inventory, not a ratchet: no allowance rises) | reason producer inventory | existing sites | E2 |
| `tests/unit/profiling/test_scan_diff.py`, `test_scan_set_read.py`, `test_bound_baseline.py` | new | Unit tests mirroring `src/` | `test_scan_set.py` | E1, E2 |
| `tests/integration/compat_corpus/scan_diff/` | new: `scan-diff-v1.json`, `scan-diff-v1.1.json` and the parity corpus `pairs.json` | compat corpus | `compat_corpus/records/` | E1 |
| `tests/snapshots/frozen_schemas/pipeline-config.schema.json` | changed: `sha256` | frozen schema snapshot | `on_drift` | E2 |
| `docs/frozen-surfaces.md`, `docs/compatibility-contract.md` | changed: `scan-diff/v1` row, tag, minor rule, paragraph and profiling names (E1); `sha256` and the pre-GA tightening note (E2) | Feature and contract docs | `scan-set/v1` | E1, E2 |
| `src/decoy_engine/_MAP.md`, `CODEMAP.md` | changed: one line each for the three modules | package map | `scan_set.py` line | E2 |
| `changelog.d/<slice-slug>.md` | new fragment per slice; E2's is marked breaking | Changelog fragments | other fragments | E1, E2 |

`pii_bucket`, `diff_scan_tables`, `diff_scan_documents`, `read_scan_set` and `check_scan_finite`
merge in E1 before their CLI callers (C1, after the release); `diff_scan_documents` also gets its
engine caller `evaluate_drift` in E2. This is the plan-named pair across the release boundary that
proportionality allows: the consumer slice C1 is named here and lands before row 80 closes.

CLI (map: CLI `CODEMAP.md` "Where things go"; flat `src/decoy/cli/` is frozen and takes no file).
All CLI rows assume D-2a, D-2b and (for C2) D-2c have merged.

| File | New or changed | Where things go line | Sits beside | Slice |
|---|---|---|---|---|
| `pyproject.toml`, `uv.lock` and the repin checklist files | changed: repin to the E2 release (one commit at the head of C1) | dependency pins | engine pin | C1 |
| `src/decoy/cli/scanning/_diff.py` | changed (D-2a file, ~130 to ~110): `diff_scan_sets` and the document helper call the engine; buckets deleted; `pii_bucket` re-exported; gains the `--json` payload builder from `scan.py` | `decoy scan` internals | `scanning/_multi.py` | C1 |
| `src/decoy/cli/scanning/_drift.py` | changed (D-2b file): CLI matching deleted; `bind_baseline` in `check_drift`; `evaluate_drift`; facade `DriftVerdict` is the engine type (C1); finding-line formatter (C2) | `decoy scan` internals | `_diff.py` | C1, C2 |
| `src/decoy/cli/scanning/__init__.py` | changed: `pii_bucket` re-export (C1), `bind` command export (C2) | `decoy scan` internals | D-2's exports | C1, C2 |
| `src/decoy/cli/scan.py` | changed: payload builder moved out and `scan_diff` member added (C1, net shrink of about 20 lines); `bind` registered (C2, about 4 lines). It may only shrink against `tests/sentry/baselines/module-size.json`: C1 lowers the max D-2a set, and C2 stays at or below it | Command module (legacy, over the cap) | `_diff` | C1, C2 |
| `src/decoy/cli/io/_scan_set.py` | changed: `read_scan_baseline` returns bytes only; `check_scan_finite` before the branch; `_from_core` on `read_scan_set` with the message map | Source readers | `load_scan_set` | C1 |
| `src/decoy/cli/exit_codes.py` | changed: `BaselineBindingError` in `usage_error_types()` | exit codes | `PlanCompileError` | C1 |
| `src/decoy/cli/scanning/_bind.py` | new (~90): `decoy scan bind` | `decoy scan` internals | `scanning/_diff.py` | C2 |
| `tests/sentry/run/test_one_drift_rescan.py` | changed: wider walk, engine-name rules, two allowlisted paths | Sentry test (`tests/sentry/run/`) | D-2c's rules | C1 |
| `tests/fixtures/scan_diff/pairs.json` | new, vendored byte-identical from the engine corpus and pinned in `ci/vendored.toml` | shared fixtures, vendored | `tests/fixtures/release_freeze/` | C1 |
| D-2 tests and fixtures | changed in C1: every D-2 config with `on_drift: fail` gains the `sha256` of its baseline bytes through one test helper (D-T3, D-T8, D-T11 and D-T13 fixtures; D-2c's e2e YAMLs); D-T8 and D-T9 move to the bytes-only reader and `baseline_unreadable`; D-T12 asserts the engine matching; D-T14 accepts `0.0`. Changed in C2: D-T3, D-T6 and D-T11 assert the finding lines | existing D-2 test homes | D-2 cells | C1, C2 |
| `tests/unit/test_exit_code_for.py` | changed: `BaselineBindingError` cell | unit tests | `PostScanBlockedError` cell | C1 |
| `tests/fixtures/release_freeze/json-shapes.json`, `CHANGELOG.md` | changed: `scan diff` `/scan_diff` (C1), new `scan bind` (C2) | `--json` success shapes | `scan diff` entry | C1, C2 |
| `tests/e2e/test_ci_unexpected_failures.py` | changed if its patched seam moved in D-2a: it keeps patching `decoy.cli.scanning` | existing e2e | `"drift"` entry | C1 |
| `docs/cli-reference.md`, `docs/guides/` drift page, `docs/ROADMAP.md` | changed: `scan bind`, bound baselines, re-bind and resume note, row 80 status | docs | row 32 text | C2 |

## 8. Enumerations

### Routes

- Drift, `decoy run`: baseline bytes read at `src/decoy/cli/run/_prepare.py:376` (duckdb path) or
  `src/decoy/cli/run/_prepare.py:398`; `check_drift` (bind, detectors, rescan, verdict) after
  `src/decoy/cli/run/_prepare.py:546`. It runs before route selection, so resident, out-of-core,
  sequential, chunked and `--sample` runs are all covered. `--rows` previews: not checked (D-2).
  `run --all`: each child `decoy run` checks its own YAML.
- Drift, `decoy.mask()`: `check_drift` before `src/decoy/api.py:582`.
- Engine publication: every route publishes through `publish_unit`
  (`src/decoy_engine/publication/_publish.py:199`), behind `observed_commit`
  (`src/decoy_engine/execution/_publication_observer.py:142`) and the gate's `before_commit`
  (`src/decoy_engine/execution/pipeline/_post_scan.py:310`). A blocked drift run never opens a
  route, so none of these is reached. Row 80 adds nothing to them (Q5).
- Diff consumers: `decoy scan diff` (`src/decoy/cli/scan.py:943`), `decoy ci check` drift
  (`src/decoy/ci/adapters.py:158`), `rescan_and_diff` (D-2b).

### Fields

- New config key `scan_baseline.sha256`; existing `scan_baseline.path`, `schema`, `on_drift`
  (`src/decoy_engine/config/_scan_baseline.py:30`).
- Scan members the diff reads: per field `name`, `pii_score` (`src/decoy_engine/profiling/scan_set.py:148`);
  per table `name`, `reid_risk_score`, `quasi_identifier_groups`; per set `engine_version`,
  `detectors`. `bind_baseline` also hands `detectors`, `sample_strategy` and `sample_row_cap` to
  D-2b's reproduction through `bound.scan`.
- `scan-diff/v1` members: listed in 3.1. `DriftFinding`: `table`, `column`, `kind`.

### Exit paths

- Drift `failed`: `DriftBlockedError`, exit 4 (D-2c arm), message with per-table and finding lines.
- Digest mismatch or unreadable baseline: `BaselineBindingError`, exit 1 through
  `usage_error_types()`, before the rescan and any source load.
- `on_drift: fail` without `sha256`: config refusal, exit 1 (`decoy run`, `decoy validate`).
- Detectors not reproducible: D-2b's exit 1, after binding.
- `decoy scan diff --strict` with drift: exit 4, unchanged.
- `decoy scan bind` on a file that is not a `scan-set/v1` core: exit 1 (`EXIT_USAGE`), fixed text.
- `decoy.mask()`: `BaselineBindingError` or `DriftBlockedError` raised to the caller.

### FK shapes

N/A: no slice reads or writes keys across tables. The diff compares per-table field metadata and
quasi-identifier groups; relationship facts in `scan-set/v1` are not compared (the rule set never
did), and D-2b's rescan runs with `integrity=False`.

### Output surfaces

- `scan-diff/v1` document (engine), returned by `scan_diff_to_dict`; the CLI shows it in
  `scan diff --json` as `scan_diff`.
- `decoy scan diff` text and `--json` (unchanged keys plus `scan_diff`); `decoy scan bind` text and
  `--json`.
- `decoy ci check` SARIF and JSON drift findings: unchanged.
- `decoy run` stderr drift lines and the `DriftBlockedError` text; the `--json` error object code.
- `decoy.mask()`: one `warnings.warn` per drifted table, with its finding lines.
- `ctx.drift_verdict`: the engine `DriftVerdict` (read by RESULT C1).
- Logs: none added.

## 9. Frozen contracts touched

| Contract | Change | Compatibility |
|---|---|---|
| Persisted formats (contract 3.1) | new `scan-diff/v1` | new tag with a minor rule; frozen-surface row, corpus samples for v1 and v1.1, read-model cells (E1) |
| Engine public names | the names in section 0, in `decoy_engine.profiling.__all__` | additive; described in the contract 3.1 paragraph beside `ScanSetCoreRead`; `decoy_engine.__all__` is unchanged |
| Pipeline config schema (snapshot) | `scan_baseline.sha256`; `on_drift: fail` requires it | optional key, omitted when absent; the `fail` rule tightens a key released in 0.28.0, allowed pre-GA (`is_pre_ga()`), with a breaking changelog fragment and a contract note |
| Plan hash | `sha256` hashed with `on_drift` when set | configs without `on_drift` keep their hash (F15-T6); a re-bind voids resume (documented) |
| Reason registry | three codes since UNRELEASED | `REGISTRY_VERSION` and reason manifests untouched; the release stamps them |
| CLI `--json` shapes (release freeze) | `scan diff` gains `/scan_diff`; new `scan bind` | additive; snapshot and CHANGELOG in the same slice |
| CLI command set | new `decoy scan bind` | additive; `docs/cli-reference.md` and `tests/unit/test_cli_surface.py` |
| CLI exit codes | none new | 1 and 4 reused |
| `decoy.mask()` library API | may raise `BaselineBindingError` when `scan_baseline` is bound and the bytes differ | opt-in key; no change without `on_drift` |
| `cli-local-1` evidence | none (B-2 owns the baseline fingerprint) | none |

## 10. Class table

| # | Class | Where it applies | Structure that closes it | Proof | Mutation |
|---|---|---|---|---|---|
| 1 | Value-bearing output | diff document, drift lines, binding errors | the diff reads only four table members; errors carry codes and config keys | F15-T3 canary, F15-C-T10 canary sweep | MF-3b, MC-10 |
| 2 | Cleanup missing on an exit path | blocked or unbound runs | the stop is before any masking read and any output stage, on D-2's existing error path | F15-C-T6 (no output, stage or lock files) | MC-6b: check after the source load |
| 3 | Shared state across calls | diff and verdict | pure functions over immutable inputs; frozen dataclasses | F15-T1 repeat-call cell over two pairs sharing a table name | MF-1c: module-level cache keyed by table name |
| 4 | Route parity and silent fallback | `scan diff`, `ci check`, `run`, `mask()` | one engine rule set behind two facade modules; `check_drift` is the only binding site | F15-C-T1, F15-C-T2 sentry, F15-C-T9 | MC-2, MC-9 |
| 5 | Referential counts across tables | baseline vs current table sets | engine matching: `table_added` drift, `tables_removed` reported, one `no_common_table` | F15-T2 | MF-2, MF-2c |
| 6 | Untrusted producer | hand-edited baseline, YAML digest, foreign diff documents | anchored digest match on a strict string; `read_scan_set` strict tag and model; strict `scan-diff/v1` types; unknown kind refused | F15-T4, F15-T6, F15-T3 | MF-4, MF-6, MF-3c |
| 7 | Check then use (TOCTOU) | baseline digest then parse | one read returning bytes; digest and parse over the same bytes inside `bind_baseline` | F15-T7, F15-C-T7 (one open spy) | MF-7: parse a second read |
| 8 | Weak tests | parity passing vacuously | corpus pairs each with a non-empty change list unless marked `no_drift`; a pair per drift kind; a legacy pair | F15-C-T1 corpus check | MC-1 |
| 9 | Refactor drift | moving the rules and the matching | line-for-line port with a vendored parity corpus captured from the CLI before the call-through | F15-T1, F15-C-T1, D-T12 | MC-1, MF-2c |
| 10 | Frozen contract drift | `scan-diff/v1`, config schema, `--json` shapes | strict writer, derived reader, tag and minor rule, corpus, frozen-surface row, snapshot | F15-T3, F15-T5, F15-T6, F15-C-T4 | MF-5, MF-6b |

Value-free errors (recurring defect 3): `ScanSetReadError`, `BaselineBindingError` and the C2 CLI
errors raise after their `except` block closes; F15-T4, F15-T7 and F15-C-T7 assert
`__cause__ is None and __context__ is None`.

## 11. Acceptance tests (written first; each red on today's main)

"Red before" says why the test fails on engine `902968682`, or on CLI main once D-2a to D-2c have
merged. Each has a named mutation that must turn it red; mutations run on the slice's final head
(recurring defect 9).

### Engine

| Id | Slice | Asserts | Red before | Mutation |
|---|---|---|---|---|
| F15-T1 | E1 | `diff_scan_tables` over the parity corpus equals the expected rows captured from CLI `compute_scan_diff` at `5b49510` (bucket up and down, added, removed, new high PII, QI added and removed order-insensitive, risk delta `None` when either side lacks it, missing score compared as `0.0`, a legacy pair with int scores and no `scan_schema`); the function reads no other member (a table holding only the four members diffs); two different pairs sharing a table name give their own results in either call order | module absent | MF-1: compare raw scores, not buckets; MF-1b: treat a missing score as `low`; MF-1c: cache by table name |
| F15-T2 | E1 | `diff_scan_documents`: a table only in `current` is `table_added` drift; one only in `baseline` is in `tables_removed` and not drift; no common table gives exactly one `no_common_table` kind and an empty `tables_added`; `tables=` selects; a different `engine_version` or detector run sets `detectors_changed` and not drift | absent | MF-2: count `tables_removed` as drift; MF-2b: count `detectors_changed` as drift; MF-2c: one `table_added` per table when nothing matches |
| F15-T3 | E1 | `scan_diff_to_dict` round trips through `ScanDiffCoreRead`; the write model refuses an unknown member, `True` or `"0.5"` as a score, free text as a drift kind; the read model accepts `scan-diff/v1.1` and ignores an unknown member, refuses a missing tag, `scan-diff/v2`, `"scan-diff/v1\n"` and an unknown drift kind with fixed text; a canary string in an unknown table member of the input never reaches the document; the corpus samples read | absent | MF-3: lax model; MF-3b: copy unknown table members through; MF-3c: drop an unknown drift kind instead of refusing |
| F15-T4 | E1 | `read_scan_set` accepts `scan-set/v1` and `scan-set/v1.3`, refuses `scan-set/v2`, `scan-set/v10`, a missing tag and a tag with a trailing newline, each with its `kind`; `check_scan_finite` refuses NaN and Infinity nested in a field and in a legacy document; no `__cause__` or `__context__` | absent | MF-4: `startswith("scan-set/v1")` without the `.` boundary; MF-4b: check only top-level members for non-finite values |
| F15-T5 | E1 | the frozen-surface map sentry lists `scan-diff/v1` with its pinning test; `decoy_engine.profiling.__all__` holds every E1 name and `decoy_engine.__all__` is unchanged | row absent | MF-5: drop the `scan-diff/v1` row |
| F15-T6 | E2 | `sha256` 64 lowercase hex accepted; uppercase, 63 chars, a trailing newline, `True` and an int refused; `on_drift: fail` without it refused with `config.scan_baseline_unbound` naming the field; `warn` without it accepted; absent `sha256` keeps the dump and plan hash byte-equal for configs with no `on_drift` and with `on_drift: warn`; setting `sha256` with `on_drift` moves the hash; `sha256` without `on_drift` does not; the schema snapshot holds the key | key unknown | MF-6: `re.match` with `$`; MF-6b: hash `sha256` when `on_drift` is absent; MF-6c: accept `fail` without a digest |
| F15-T7 | E2 | `bind_baseline` with matching bytes returns a bound `BoundBaseline`; one changed byte raises `pre_scan.baseline_digest_mismatch` before any parse (a non-JSON body with the wrong digest gives the mismatch code); a reformatted file with the same content also mismatches; non-JSON, a legacy profile and `scan-set/v2` with no digest set raise `pre_scan.baseline_unreadable`; error text holds neither digest nor path; no `__cause__` or `__context__`; `BoundBaseline(...)` outside `bind_baseline` raises `TypeError` | absent | MF-7: hash `json.dumps(json.loads(raw))`; MF-7b: allow direct construction; MF-7c: parse before the digest check |
| F15-T8 | E2 | `evaluate_drift` matrix: no drift `passed` with no code; drift under `warn` `warned` with `drift_detected`; under `fail` `failed` with `drift_blocked`; findings sorted by (table, column, kind) and hold names only; `drifted_tables` groups them per table; `no_common_table` gives one finding with table `None`; an unbound `warn` baseline reports `bound: false` | absent | MF-8: map `fail` to `warned` |
| F15-T9 | E2 | reason fixtures hold the three new codes with since UNRELEASED; `REGISTRY_VERSION` unchanged; the f29 producer inventory resolves every new site | codes absent | MF-9: bump the registry version |
| F15-T10 | E2 | `starter_config(baseline_sha256=...)` writes the bound block and the result passes `_check`; a non-hex value is refused | parameter absent | MF-10: write the digest without checking it |

### CLI

| Id | Slice | Asserts | Red before | Mutation |
|---|---|---|---|---|
| F15-C-T1 | C1 | for every pair in the vendored corpus, including the legacy pair, `decoy scan diff --json` without `scan_diff` equals the captured CLI output (parsed, numeric equality) and the text output is identical; `--strict` exits 4 exactly on the drift pairs; the corpus test refuses a pair with every change list empty unless it is marked `no_drift`; a legacy document with NaN is refused with today's message | `scan_diff` key absent | MC-1: facade drops `qi_added` |
| F15-C-T2 | C1 | the extended `test_one_drift_rescan.py` passes on the tree and fails on each seeded case: a local `_pii_bucket` in `scan.py`, each listed import shape of an engine diff or binding name outside `scanning/_diff.py` and `scanning/_drift.py`, including a function-body import in `run/_drift.py` and in `api.py` | rules absent | MC-2: a bucket function in `scan.py`; MC-2b: a function-body import of `bind_baseline` in `run/_drift.py` |
| F15-C-T3 | C1 | `decoy ci check` drift: the existing CI fixtures give the same rule ids, message ids, counts and exit (guard); the unexpected-failure test still reports `ci.drift_unreadable` | guard | MC-3: catch and drop the facade's error |
| F15-C-T4 | C1 | `scan diff --json` `scan_diff` reads through engine `ScanDiffCoreRead` with its tag; its `baseline_engine_version` and `current_engine_version` equal the two input documents' `engine_version`, and `detectors_changed` is set when their `detectors` differ (so the CLI passed full documents); the shape snapshot matches and `CHANGELOG.md` has the entry; reader messages for an unsupported `scan_schema` are unchanged | key absent | MC-4: pass only the selected tables, losing the set members |
| F15-C-T5 | C1 | `rescan_and_diff` matching is the engine's: a spy sees one `diff_scan_documents` call per check; D-T5 parity and D-T12 hold; `ctx.drift_verdict` is an engine `DriftVerdict` | CLI matching | MC-5: keep D-2b's CLI matching |
| F15-C-T6 | C2 | SCAN-14 e2e: `decoy scan`, `decoy scan bind`, paste the block with `on_drift: fail`, add a high-PII column to the source: exit 4; stderr has the `customers` table line, then `customers.alt_email (new_high_pii_field)`, and `pre_scan.drift_blocked`; the output directory holds no file, stage, descriptor or lock file; `--json` error code is `pre_scan.drift_blocked`; 12 drifted columns print 10 finding lines and `and 2 more` | no finding lines | MC-6: message without findings; MC-6b: check after the source load |
| F15-C-T7 | C1 | rescan the drifted source into the baseline path: exit 1 with `pre_scan.baseline_digest_mismatch` before the rescan and any source load (spies on `scan_sources` and `_load_sources_from_config`); the baseline file is opened once; `on_drift: fail` without `sha256` exits 1 at validation with `config.scan_baseline_unbound`; `exit_code_for(BaselineBindingError(...))` is 1 and the run error arm maps it to 1; errors have no `__context__` | no binding | MC-7: bind after the rescan instead of before it; MC-7b: drop the `usage_error_types()` entry |
| F15-C-T8 | C2 | `decoy scan bind scan.json` prints a block whose `sha256` is quoted and equals SHA-256 of the file bytes; a file whose digest is all digits prints a quoted value that reloads as a string; `--json` has `command`, `status`, `path`, `schema`, `sha256`; a legacy profile and a CSV are refused with exit 1 and fixed text; the printed block, pasted, gives a passing run | command absent | MC-8: hash the path text; MC-8b: print the digest unquoted |
| F15-C-T9 | C1 | `decoy.mask(config)` with a bound baseline whose bytes changed raises `BaselineBindingError` before `_load_sources_from_config` (spy); with a correctly bound baseline and a drifted source under `fail` it raises `DriftBlockedError`, also before the load | binding absent | MC-9: skip `bind_baseline` inside `check_drift` |
| F15-C-T10 | C2 | canary sweep: a canary cell value in every source column never appears in stderr, stdout, `--json`, `warnings.warn` text or the `scan_diff` document across F15-C-T6 to F15-C-T9 | no check | MC-10: print a sample value in the finding line |

## 12. Pre-mortem

- The port changes a result for an odd input (a missing score, an empty QI group, a legacy int
  score). Guard: the parity corpus is captured from the live CLI function before the call-through
  and vendored byte-identical into the CLI, so both repos test the same pairs.
- Between E1's merge and C1's merge two copies exist (one per repo). Guard: the window is bounded by
  the release and repin; E1's module docstring names C1; C1's sentry closes it.
- The repin breaks D-2's tests, because their `fail` configs have no digest. Guard: C1 opens with
  the repin and updates those fixtures in the same slice (section 7).
- A user rescans into the bound path and is surprised by exit 1. Guard: the error names
  `scan_baseline.sha256` and the hint says to review with `decoy scan diff` and re-bind with
  `decoy scan bind`; the guide has a worked example.
- Reformatting a baseline (an editor that rewrites JSON) breaks the binding. Guard: documented; raw
  bytes match the evidence fingerprint, and a rewritten file is a change to review (Q3).
- A re-bind stops an interrupted run from resuming. Guard: documented in the drift guide.
- A user writes an all-digit digest unquoted. Guard: the strict string type refuses it at load, and
  `scan bind` always quotes.
- `scan.py` is in the one-writer lane with rows 29, 36, 53 and 56. Guard: C1 and C2 take the lane in
  turn after D-2a; C1 shrinks the file.
- The engine release that carries E2 slips. Guard: E1 alone is additive and unused; nothing in the
  CLI changes until the repin.
- A platform or SDK caller sets `on_drift: fail` and calls `run_pipeline` directly, so no check runs.
  Guard: V1 has no such caller (platform parked; `decoy.mask()` checks through `check_drift`); Q5
  records it for the platform half.

## 13. Slices

At most 10 production files and about 800 lines each (tests counted). Risk per
`risk-and-exceptions.md`: R1 takes Codex-only review; R2 takes Dennis then Codex.

### 13.1 Slice table

| Slice | Repo | Content | Prod files | ~Lines | Risk | Waits on |
|---|---|---|---|---|---|---|
| E1 | engine | prep folded in: `scan_set_read.py` (`read_scan_set`, `check_scan_finite`); `scan_diff.py` (port, matching, document, models, minor rule); parity corpus captured from CLI `5b49510`; profiling exports; frozen-surface row, contract 3.1 tag and paragraph; changelog fragment; F15-T1 to F15-T5 | 3 | 740 | R2 (new frozen format) | none |
| E2 | engine | `scan_baseline.sha256` and unbound rule; plan-hash rule; `bound_baseline.py`; three reason codes and the f29 inventory; `starter_config(baseline_sha256=)`; schema snapshot; contract note on the pre-GA tightening, `_MAP.md` and CODEMAP lines; breaking changelog fragment; F15-T6 to F15-T10 | 7 | 660 | R2 (config schema, blocking verdict) | E1 |
| Release | engine | daily train with E2 (planned 0.29.0) | n/a | n/a | per train | E2 |
| C1 | CLI | repin to the E2 release (repin checklist); `_diff.py` call-through with the payload builder; `_drift.py` engine matching, `bind_baseline` in `check_drift`, engine `DriftVerdict`; `read_scan_baseline` bytes only; `check_scan_finite` and `read_scan_set` in the reader; `usage_error_types()` entry; `scan diff` `scan_diff` member; sentry extension; vendored corpus; D-2 fixture and cell updates; shape snapshot and CHANGELOG; F15-C-T1 to F15-C-T5, F15-C-T7, F15-C-T9 | 7 | 790 | R2 (frozen `--json` shape, refuses runs, library API) | the release; D-2a and D-2b merged |
| C2 | CLI | finding lines (one formatter in `_drift.py`) for `decoy run` and `decoy.mask()`; `decoy scan bind`; D-T3, D-T6 and D-T11 updates; docs last (cli-reference, drift guide with a worked bind example and the resume note, `decoy explain exit-codes` text if it lists drift, ROADMAP row 80, CHANGELOG); F15-C-T6, F15-C-T8, F15-C-T10 | 4 | 560 | R2 (user-facing refusal text, new command) | C1; D-2c merged |

Order: E1 then E2 (E2 imports `diff_scan_documents`). C1 then C2 (both write `scan.py` and
`scanning/_drift.py`). C1 waits on D-2a, as the drift plan's ruling says, and also on D-2b, because
it edits D-2b's `scanning/_drift.py` and `read_scan_baseline`. There is no F15-first path. Neither
CLI slice touches `run/_prepare.py` (564 lines against its 600-line cap) or `api.py`.

C1 is close to the cap. If the build passes about 800 lines, the payload-builder move and the
`scan_diff` member split into a C1b that merges after C1 with F15-C-T1 and F15-C-T4.

### 13.2 Engine release

The engine half is complete in the first daily-train release that contains E2, planned as engine
0.29.0 (0.28.0 carries D-1, and D-2b repins to it). If a train cuts between E1 and E2, E1 ships
additive and unused, which is safe. C1 repins the CLI to the E2 release with the repin checklist
(compatibility, fences, frozen surfaces, docs, `PIN_PREFIX`, the Dockerfile `ARG`, the catalog).

## 14. Owner questions (taken on the recommended answer)

Carried as decided: `plan/scan-checks` Q1 (`on_drift` on `scan_baseline`), Q2 (exit 4), Q12 (row 80
reuses `on_drift: fail`); `plan/drift` Q-A (one rescan helper in `scanning/_drift.py`), Q-B (D-2
stores a verdict; RESULT C1 builds the check), Q-F (`decoy.mask()` runs the check), Q-G
(`no_common_table` is drift), and its section 13.1 ruling (drift owns the facade names; F15 C1 waits
on D-2a).

| Q | Question | Answer taken (recommended) |
|---|---|---|
| Q1 | What is the bound-baseline object? | A digest pin `scan_baseline.sha256` in the reviewed YAML plus engine `BoundBaseline`, built only by `bind_baseline`. No approval store, role or record kind in V1; L2 and L4a can add a ref on the same digest |
| Q2 | Is the digest required? | Required under `on_drift: fail` (`config.scan_baseline_unbound`), optional under `warn`. A pre-GA tightening of the 0.28.0 key, with a breaking changelog fragment |
| Q3 | Digest of raw bytes or canonical JSON? | Raw bytes: equals B-2's evidence fingerprint, and a rewritten file is a change to review |
| Q4 | Does `sha256` enter the plan hash? | Yes, with `on_drift`, only when `on_drift` is set; a re-bind voids resume, documented |
| Q5 | Should the engine itself refuse to publish (at `observed_commit` or `publish_unit`) when `on_drift: fail` is set and no passing verdict was given? | No for V1. Both V1 callers go through `check_drift` and stop before any read. V2-LOG with the platform half of F15 |
| Q6 | How does the CLI expose `scan-diff/v1`? | Additive `scan_diff` member in `scan diff --json`; no new file output |
| Q7 | Is a detector or engine change drift? | No: `detectors_changed` is information; the bucket changes it causes count as before |
| Q8 | Rename detection? | No; removed plus added. V2-LOG |
| Q9 | How does a user bind? | `decoy scan bind SCAN` prints the block with the digest quoted; it never edits YAML. `--emit-config` (row 29) writes it through `starter_config(baseline_sha256=)` when built |
| Q10 | Who owns table matching? | The engine (`diff_scan_documents`), including the `no_common_table` single-entry rule; C1 deletes D-2b's CLI matching |
| Q11 | A missing score printed `0` in `scan diff --json`; the engine keeps floats (`0.0`). Accept? | Yes; numeric JSON equality and identical text; CHANGELOG line; D-T14 updated |
| Q12 | Which engine release carries the engine half? | The first train release containing E2, planned 0.29.0 |
| Q14 | Row 80's After lists STORM rename and SCAN-LIB. Keep? | Replace with "row 32 D-2a and D-2b (C1), D-2c (C2)". Row 80 adds no STORM-named surface and needs only a `scan-set/v1` file, not the library |
| Q15 | Fewer slices? | No. E1 plus E2 is about 1,400 lines and C1 plus C2 about 1,350, both over the 800-line cap. Prep is folded into E1 and C1; docs go in E2 (contract) and C2 (user docs) |
| Q16 | A `scan-diff/v1.N` document with a drift kind this reader does not know: refuse or tolerate? | Refuse with fixed text. Dropping the kind could report a drifted diff as clean |

Q13 (revision 1: `decoy.mask()` refuses `on_drift`) is withdrawn: `decoy.mask()` runs the drift
check through `check_drift` (drift plan Q-F) and gets the binding with it.

## 15. V2-LOG

- Engine-side refusal for callers that skip the drift check (Q5), with the platform pre-scan
  re-enable.
- Approval records with owner, reason and expiry; scoped suppressions; review queues (spec F15
  example 2).
- Rename detection; relationship-fact drift (orphans, key shape) in `scan-set/v1` diffs.
- A per-match detector version on `DetectorMatch` (row-detail note); V1 identifies the detector set
  by `engine_version` and the `detectors` runs, and the diff reports a change.
- `decoy validate` checking the baseline digest without a run.
- `decoy ci check` using `diff_scan_documents` matching instead of its one-table compare (drift plan
  section 16).

## 16. Roadmap edits when this plan passes

- Row 80: "Plan `E:plan/f15-bound-baseline` (`2026-11-17-f15-bound-baseline.md`), slices E1, E2, C1,
  C2; engine half in the release with E2 (planned 0.29.0)". After becomes "row 32 D-2a and D-2b
  (C1), D-2c (C2)" (Q14).
- Row 32: "F15 C1 (row 80) moves D-2b's table matching and `DriftVerdict` to the engine and binds the
  baseline in `check_drift`; D-2 builds as planned".
- Row 62: "RESULT C1 reads `ctx.drift_verdict` as the engine `DriftVerdict` once F15 C1 merges".
- Row 29: "`--emit-config` writes `scan_baseline.sha256` through `starter_config(baseline_sha256=)`".
- `plan/drift` section 6 "Where each drift fact lives": a pointer to this plan for the move of the
  per-field rules and matching into the engine.

## 17. Revision 2: Dennis round 1 resolutions (on `e034c27c`)

| Finding | Change | Sections |
|---|---|---|
| H1 C1/C2 written against drift revision 1 | C1 waits on D-2a (and D-2b, whose module it edits); no F15-first path; `scanning/_diff.py` keeps `ScanDiff` and `diff_scan_sets` and calls the engine; `_compare.py`, `diff_tables`, `diff_sets` dropped; `pii_bucket` re-exported from `_diff.py`; binding in `scanning/_drift.py` `check_drift`; hook positions from drift revision 3; `scan.py` effects measured against D-2a's max; section 0 and 16 rewritten (L6 folded in) | 0, 3.3, 3.4, 7, 8, 13, 16 |
| H2 `decoy.mask()` refusal contradicted drift Q-F | Q13 withdrawn; `mask()` binds through `check_drift`; F15-C-T9 rewritten with spies; mutation MC-9; `api.py` leaves the file list | 3.3, 7, 11, 14 |
| H3 two owners of table matching | engine `diff_scan_documents` owns matching including `no_common_table` and its single-entry rule; C1 deletes D-2b's matching; set-level names `diff_scan_documents` and `ScanSetDiff`, so `diff_scan_sets` means only the facade per-table call; facade `DriftVerdict` re-exports the engine type; `ctx.drift_verdict` shape change noted for row 62; F15-T2 cell, MF-2c, F15-C-T5 | 3.1, 3.3, 11, 16 |
| H4 exit 1 for binding errors had no path | `BaselineBindingError` added to `usage_error_types()`, read by the exit map and the run error arm; `test_exit_code_for.py` cell in F15-C-T7; MC-7b; `scan bind` errors exit 1 | 3.3, 7, 8, 11 |
| H5 binding landed after its own acceptance cell | `bind_baseline` in `check_drift` moves to C1; C1 updates D-2 fixtures to carry `sha256`; F15-C-T7 (mismatch exits 1 before any read) moves to C1 | 7, 11, 13 |
| H6 engine diff validated cores, breaking legacy diffs | `diff_scan_tables` reads four members with no validation; legacy pair with int scores in the corpus and F15-C-T1; one `check_scan_finite` export called once before the CLI branch; legacy NaN cells | 3.1, 3.4, 11 |
| M1 document lacked set members | the CLI passes both full documents with `tables=[selected]`; F15-C-T4 pins the versions and `detectors_changed`; MC-4 | 3.4, 11 |
| M2 tightening a released key | described as a pre-GA tightening of the 0.28.0 key (`is_pre_ga()`), breaking changelog fragment, contract note | 3.2, 9, 14 |
| M3 user text change in the reader | CLI catches `ScanSetReadError` and maps its `kind` to today's messages | 3.1, 3.4, 11 |
| M4 second sentry | one sentry: drift's `test_one_drift_rescan.py` extended, function-body imports, exact-path allowlist of `_diff.py` and `_drift.py`, engine names including `evaluate_drift` and `bind_baseline` | 5, 7, 11 |
| M5 minor rule for `scan-diff/v1` | `scan-diff/v1.<minor>` accepted as for `scan-set`; unknown drift kind refused (Q16); cells and MF-3c | 3.1, 11, 14 |
| M6 dropped D-2's per-table output | per-table lines and one `warnings.warn` per table kept; finding lines under each table, 10 in total; D-T3, D-T6, D-T11 updates named in C2 | 3.3, 7, 13 |
| M7 two parses of the baseline | `read_scan_baseline` returns bytes only; `bind_baseline` is the one parse; order digest, parse, detector reproduction; MF-7c | 3.2, 3.3, 11 |
| L1 MF-1c could not fail | cells use two different pairs sharing a table name | 11 |
| L2 all-digit digest read as an int | `scan bind` quotes the digest; strict string in config; cells and MC-8b | 3.2, 3.3, 11 |
| L3 f29 producer inventory | added to E2 placement | 7 |
| L4 resume after re-bind | documented as a consequence of the plan-hash rule | 3.2, 4, 12 |
| L5 D-T14 byte equality | named as updated by C1 for `0` to `0.0` | 3.4, 7 |

Slice sizes after the moves: E1 about 740, E2 about 660, C1 about 790 (with a named C1b split if
it passes the cap), C2 about 560.
