Status: plan

# F15 bound baseline, strict-drift publication block and `scan-diff/v1` (row 80)

Rules consulted: `dev-rules/README.md`, `00-universal.md`, `risk-and-exceptions.md`,
`development-loop.md` (PLAN), `feature-dev.md`, `reuse-first.md`, `proportionality.md`,
`api-and-compatibility.md`, `cross-cutting-concerns.md`, `testing.md`, `architecture.md` (layout),
`workspace-and-vcs.md` (commit messages), `catalogs/recurring-defects.md`; memory notes
v1-bar-blocking-criteria, v1-threat-model-accidental-leaks, plan-defines-acceptance-tests,
develop-correctly-registries-and-sizing, best-practice-becomes-a-sentry, v1-scope-no-new-features,
v1-pragmatic-gate-priorities, engine-repin-checklist, decoy-parallel-ledger-files.

Bases (2026-11-17): engine `origin/main` `902968682` (last tag `v0.27.0`, `REGISTRY_VERSION`
1.29.0); CLI `origin/main` `5b49510` (pins `decoy-engine==0.27.0`). Inputs read: CLI
`docs/ROADMAP.md` rows 29, 30, 32, 36, 56, 62, 76 and 80; CLI `docs/roadmap/row-detail.md` (F15
note); CLI `docs/qa/cli-v1-checklist.md` (SCAN-14); engine `plan/drift`
(`docs/plans/2026-11-17-drift-dist-integrity.md`); engine `plan/scan-checks`
(`docs/plans/2026-11-16-scan-checks.md`, section 2 and Q12); the master feature spec F15 and its V1
scope note in the vault (`10_Projects/decoy/Market Expansion Specs/`); `docs/publication.md`; the
engine and CLI CODEMAP "Where things go" maps; the code cited below.

Risk: R2 overall (a new frozen artifact format, a config schema change, a check that refuses runs).
Per-slice tiers in section 13.

## 0. What row 80 adds, and what it does not

Row 80 reads: "F15: bound-baseline object, strict-drift publication block; scan-diff moves into an
engine `scan-diff/v1`". Its neighbours already cover part of it:

- Row 32 (DRIFT) owns the run-start check. Engine half D-1 is MERGED (engine #613, `03839e889`):
  `scan_baseline.on_drift` (`src/decoy_engine/config/_scan_baseline.py:30`), its plan-hash rule
  (`src/decoy_engine/plan/_compile.py:646`), the reason codes `pre_scan.drift_detected` and
  `pre_scan.drift_blocked` (`src/decoy_engine/reasons/pre_scan/_part1.py:19`), and the `scan_drift`
  check id (`src/decoy_engine/run_result/_build.py:232`). CLI half D-2 is planned in `plan/drift`
  and not built: `scanning/_compare.py` `rescan_and_diff`, `run/_drift.py` `check_drift`,
  `DriftVerdict`, `DriftBlockedError`, exit 4 before any masking read.
- `plan/scan-checks` Q12 (owner, taken on the recommended answer): row 80's strict-drift publication
  block reuses `on_drift: fail`. There is one drift refusal, and it is row 32's.

So row 80 adds three things and no second refusal:

1. **`scan-diff/v1` in the engine.** The drift rules move from CLI `compute_scan_diff`
   (`src/decoy/cli/scan.py:865`) into one engine module with a versioned, value-free document. The
   CLI copy is deleted; `decoy scan diff`, `decoy ci check` drift and the `decoy run` drift check all
   call the engine.
2. **The bound baseline.** Today `scan_baseline.path` points at a file and nothing pins its bytes.
   Rescanning drifted sources into the same path silently "approves" the drift. Row 80 adds
   `scan_baseline.sha256`, an engine `BoundBaseline` that is only built when the bytes match, and makes
   the digest required under `on_drift: fail`. The approval is the reviewed YAML change that sets the
   digest (the same model as a lock file pin).
3. **The strict block names the missing decision.** The engine decides the drift verdict
   (`evaluate_drift`) from the bound baseline and the rescan. Under `on_drift: fail` the run stops
   before any masking read, so nothing reaches publication, and the error names each drifted
   `table.column` and its kind (QA item SCAN-14: "No output is published; the reason is named").

Non-goals (a review finding here becomes a follow-up item, not a blocker):

- An engine-side refusal inside the F22 commit path for callers that never ran the drift check
  (owner question Q5). V1's only caller is the CLI; the platform half of F15 (roadmap section 6,
  "Re-enable pre-scans" and "SCAN-MULTI platform half") takes it.
- Scheduled scans, review queues, suppressions with owner and expiry, inventory campaigns (platform,
  V2 per the vault scope note).
- Rename detection: a renamed column is a removed field plus an added field (Q8).
- A separate approval record file or library ref for baselines (Q1). L2 and L4a may add one later on
  top of the same digest.
- The run-result `scan_drift` entry: RESULT C1 (row 62) builds it from the verdict, as `plan/drift`
  says.

Expected size: engine about 1,250 lines in 2 slices, 9 production files touched, 3 new
(`profiling/scan_diff.py`, `profiling/scan_set_read.py`, `profiling/bound_baseline.py`). CLI about 1,350 lines in 2 slices, 1 new
production file (`scanning/_bind.py`), plus `scanning/_compare.py` if D-2 has not created it. New
public engine names, exported from `decoy_engine.profiling` (as `ScanSetCoreRead` and
`ScanSourceError` are today) and not from the top-level package, whose `__init__.py` is at 599 lines
against the 600-line module cap: `SCAN_DIFF_SCHEMA`, `pii_bucket`, `diff_scan_tables`, `diff_scan_sets`,
`TableDiff`, `ScanDiff`, `FieldChange`, `FieldPresence`, `scan_diff_to_dict`, `ScanDiffCore`,
`ScanDiffCoreRead`, `read_scan_set`, `ScanSetReadError`, `BoundBaseline`, `bind_baseline`,
`BaselineBindingError`, `DriftVerdict`, `DriftFinding`, `evaluate_drift`. New reason codes:
`pre_scan.baseline_digest_mismatch`, `pre_scan.baseline_unreadable`, `config.scan_baseline_unbound`,
each since UNRELEASED.

## 1. Guarantee

- One implementation of the scan-diff rules exists after slice C1: the engine's
  `profiling/scan_diff.py`. Every CLI path that compares two scans calls it through
  `decoy.cli.scanning`, and a sentry fails on a second copy.
- For the same two scans, `decoy scan diff --json` gives the same `summary`, `changes` and `drift`
  values as before (numeric equality; section 3.4 lists the one representation change), the same text
  card and tables, and the same `--strict` exit code.
- `scan-diff/v1` is a frozen format: one strict write model, a read model derived from it, a
  required tag, a corpus sample, a frozen-surface row.
- A config with `scan_baseline.on_drift: fail` must carry `scan_baseline.sha256`, or it is refused at
  config load. A run whose baseline file bytes do not hash to that digest stops before any source is
  read or staged, and nothing is written.
- Under `on_drift: fail`, a drifted source stops the run before any masking read. Nothing is staged
  or published, the exit code is 4, and the message names each drifted `table.column` (or table) and
  its drift kind.
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
- **In the engine and CLI.** CLI `compute_scan_diff` (`src/decoy/cli/scan.py:865`) is the one rule
  set today (bucket rank, new high-PII field, new quasi-identifier group). Engine
  `profiling/scan_set.py` already has the strict-writer, relaxed-reader pattern (`ScanSetCore`,
  `_relaxed` at `src/decoy_engine/profiling/scan_set.py:207`). Row 30 B-2 fingerprints the baseline
  file bytes with SHA-256 for the evidence manifest (`plan/scan-checks` B-T3). The F22 descriptor
  uses SHA-256 content digests.

Choice and reasons:

- The bound baseline is a digest pin in the pipeline YAML (`scan_baseline.sha256`), as pip and SRI
  pin artifacts. The approval is the reviewed YAML change, so no second approval store, role model or
  record kind is needed in V1. The digest is SHA-256 over the raw file bytes, the same value B-2
  writes as the evidence fingerprint, so one number identifies the baseline in the config, the
  evidence and the error.
- The rule set moves unchanged. Row 32 and the owner model (2026-11-05) define drift as what
  `scan diff --strict` flags, plus `table_added` from `plan/drift`. No rule is added or relaxed by
  the move.

## 3. Behaviour

### 3.1 `scan-diff/v1` (engine, slice E1)

New module `src/decoy_engine/profiling/scan_diff.py`, pure, no I/O:

- `pii_bucket(score) -> Literal["none", "low", "med", "high"]`: the CLI thresholds today
  (`src/decoy/cli/scan.py:390`): `None` is `none`, `>= 0.6` high (the engine's
  `PII_CANDIDATE_THRESHOLD`), `>= 0.3` med, `> 0` low. `decoy scan fields` and `show` use it too.
- `diff_scan_tables(old, new) -> TableDiff`: a line-for-line port of `compute_scan_diff` over two
  `scan-set/v1` table dicts (the read-model dump the CLI already passes). Fields `added`, `removed`,
  `pii_increased`, `pii_decreased`, `qi_added`, `qi_removed`, `risk_delta`, `new_high_pii`; property
  `drift` and `drift_kinds`. Change rows are `FieldChange(name, old_score, new_score, old_bucket,
  new_bucket)`; added and removed rows are `FieldPresence(name, pii_score, pii_bucket)`, in the CLI's
  key order.
- `diff_scan_sets(baseline, current, *, tables=None) -> ScanDiff`: every table both sides hold
  (or the `tables` selection), plus `tables_added` (in `current`, not in `baseline`: drift kind
  `table_added`) and `tables_removed` (reported, not drift). `detectors_changed` is true when the two
  sets' `engine_version` or `detectors` runs differ; it is information, not drift (Q7).
- Drift kinds, a closed `Literal`: `pii_bucket_increased`, `new_high_pii_field`,
  `new_quasi_identifier_group`, `table_added`.
- `scan_diff_to_dict(diff) -> dict` validates through `ScanDiffCore` (strict write model, unknown
  fields refused) and returns the document with `scan_diff_schema: "scan-diff/v1"`.
  `ScanDiffCoreRead` is derived from it with unknown fields ignored, through the same `_relaxed`
  helper `ScanSetCoreRead` uses (a sibling import inside `profiling/`, not another package's
  private module). `scan_set.py` itself is not edited: it is at the 600-line cap.
- `read_scan_set(data) -> dict` in new `profiling/scan_set_read.py`: the tag rule the CLI applies today
  (`src/decoy/cli/io/_scan_set.py:122`, `scan-set/v1` or a `scan-set/v1.<minor>` tag), then
  `ScanSetCoreRead`. Every refusal is `ScanSetReadError` (a `ValueError`) with fixed text, raised
  after the `except` block closes. The CLI reader and `bind_baseline` both call it, so the tag rule
  exists once.

Document shape (`scan-diff/v1`):

```json
{
  "scan_diff_schema": "scan-diff/v1",
  "baseline_engine_version": "0.27.0",
  "current_engine_version": "0.29.0",
  "detectors_changed": false,
  "drift": true,
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

### 3.2 The bound baseline (engine, slice E2)

Config:

```yaml
scan_baseline:
  path: baselines/customers.scan.json
  schema: scan-set/v1
  sha256: 3f1c...e9   # 64 lowercase hex; required when on_drift is fail
  on_drift: fail
```

- `sha256` is optional, `re.fullmatch(r"[0-9a-f]{64}")`, omitted from the dump when absent, so every
  config without it keeps its dump and plan hash.
- `on_drift: fail` without `sha256` is refused at config load with `config.scan_baseline_unbound`
  (a `PydanticCustomError`, as `config.post_scan_inactive` is built in
  `src/decoy_engine/config/_pre_scan.py:58`), naming the field, never a value. `on_drift: warn`
  without it is accepted and the verdict says the baseline is not bound.
- Plan hash: when `on_drift` is set, the hashed block becomes `{on_drift, sha256}` (sha256 only when
  present). A re-approved baseline changes which drift blocks, so it changes the hash; the path and
  schema stay out (Q4).
- New module `src/decoy_engine/profiling/bound_baseline.py`:
  - `bind_baseline(raw: bytes, block) -> BoundBaseline`: SHA-256 of `raw`; when `block.sha256` is
    set and differs, `BaselineBindingError` with `pre_scan.baseline_digest_mismatch`; then
    `read_scan_set(json.loads(raw))`, any failure `BaselineBindingError` with
    `pre_scan.baseline_unreadable`. Both errors carry the code and fixed text naming
    `scan_baseline.sha256` or `scan_baseline.path` (the config keys), never the file path, the bytes
    or either digest, and have no `__cause__` or `__context__`. `BoundBaseline` is frozen: `sha256`,
    `bound` (the YAML pinned it), `on_drift`, the parsed scan dict. Only `bind_baseline` builds one
    (constructor guard, as `PreparedDeclaredSources` does).
  - `evaluate_drift(bound, current) -> DriftVerdict`: `diff_scan_sets(bound.scan, current)`;
    `status` `passed` (no drift), `warned` (drift under `warn`, code `pre_scan.drift_detected`) or
    `failed` (drift under `fail`, code `pre_scan.drift_blocked`). `findings` is a sorted tuple of
    `DriftFinding(table, column | None, kind)`; `diff` is the `ScanDiff`; `baseline_sha256` and
    `bound` are carried for the message and for RESULT C1.
- `starter_config(..., baseline_sha256=None)` writes `sha256` into the block when given (refused
  unless 64 lowercase hex), so `decoy scan --emit-config` (row 29) can write a bound block when it
  is built.

### 3.3 The strict-drift publication block (CLI, slices C1 and C2)

The block stays where row 32 D-2 puts it: CLI `run/_prepare.py` reads the baseline bytes once before
any `--duckdb-source` staging and calls `check_drift` after `check_before_run`
(`src/decoy/cli/run/_prepare.py:398`), before the normal source load. Row 80 changes what
`check_drift` does inside `run/_drift.py`:

- It calls `bind_baseline(raw, block)` on the bytes D-2 (or B-2's `read_scan_baseline`) already read.
  A digest mismatch or unreadable baseline exits 1 (configuration) with the engine code, before any
  source is read or staged.
- It rescans through `rescan_and_diff` (one helper, D-2), whose diff now comes from
  `diff_scan_sets`, and takes the verdict from `evaluate_drift`. `DriftVerdict` is the engine's; D-2's
  CLI dataclass of that name is deleted (or never written, Q10).
- `failed`: `DriftBlockedError` (D-2's type, exit 4 through `run/_errors.py` and `exit_code_for`).
  Its text lists up to 10 findings as `table.column (kind)` or `table (table_added)`, then
  `and N more`, then one hint line: rescan, review, and re-bind with `decoy scan bind`. The `--json`
  error object carries `pre_scan.drift_blocked`.
- `warned`: one stderr line per finding in the same form; the run continues.
- Because the stop is before any masking read, no stage is opened and `publish_unit`
  (`src/decoy_engine/publication/_publish.py:199`) is never reached: nothing is published and there
  is nothing to clean up.

`decoy scan bind SCAN` (C2): reads the file once through `load_scan_set`'s byte read, checks it is a
`scan-set/v1` core (a legacy profile is refused: a baseline must be `scan-set/v1`), and prints the
`scan_baseline:` block (path as given, schema, sha256 of the bytes read) for the user to paste.
`--json` prints `{command, status, path, schema, sha256}`. It never edits a YAML file (Q9).

`decoy.mask()` (CLI Python API): a config with `scan_baseline.on_drift` set raises the public
`ConfigValidationError` with fixed text ("on_drift is checked only by decoy run") before any source
is read. Today it would ignore the key and give false assurance (Q13).

### 3.4 `decoy scan diff` and `decoy ci check` (CLI, slice C1)

- `decoy scan diff OLD NEW` calls `decoy.cli.scanning.diff_tables`, the facade over
  `diff_scan_tables` that also adapts the engine result to the existing `--json` keys. Text card,
  tables, `--strict` exit 4 and `--table` are unchanged.
- `--json` keeps every key and value; it gains one additive member `scan_diff` holding the
  `scan-diff/v1` document for the compared table (Q6). The release-freeze shape snapshot and
  `CHANGELOG.md` move together.
- One representation change: a change row whose score was missing printed `0` and now prints `0.0`
  (the engine keeps scores as floats). JSON numeric equality holds and the text output is identical;
  the CHANGELOG says so (Q11).
- `decoy ci check` drift (`src/decoy/ci/adapters.py:158`) uses the same facade; its rule ids, message
  ids and counts are unchanged. The comment "saved STORM scans" becomes "saved scans" (row 56 names).
- CLI `io/_scan_set.py` `_from_core` delegates to engine `read_scan_set`; the legacy-profile branch
  stays in the CLI (only the CLI reads legacy `profile.to_dict()` files).

## 4. Failure modes

| Failure | Behaviour |
|---|---|
| Baseline file replaced (drifted sources rescanned into the same path) | digest mismatch, exit 1, `pre_scan.baseline_digest_mismatch`, before any source read or staging |
| Baseline reformatted (same content, new bytes) | digest mismatch; a reviewed re-bind is required (Q3) |
| `on_drift: fail` with no `sha256` | refused at config load, `config.scan_baseline_unbound`; `decoy validate` reports it |
| `sha256` uppercase, 63 chars, or with a trailing newline | refused at config load (anchored match) |
| Baseline is a legacy profile or `scan-set/v2` | `pre_scan.baseline_unreadable`, exit 1 |
| Baseline holds NaN or Infinity | `read_scan_set` refuses (the CLI's non-finite rule moves with it) |
| Config has a table the baseline lacks | `table_added` finding; drift |
| Baseline has a table the config lacks | `tables_removed`; not drift |
| Detector or engine upgrade between baseline and rescan | `detectors_changed: true`, not drift; bucket changes it causes are drift as before |
| Column renamed | removed plus added; drift only if the added field is high PII |
| More than 10 findings | first 10 by (table, column, kind), then `and N more` |
| `on_drift: warn` and baseline not bound | runs; the warn line says the baseline is not bound |
| `decoy.mask()` with `on_drift` set | `ConfigValidationError`, before any source read |
| Engine older than the CLI expects | the repin checklist: the CLI pins the release that carries E2 before C1 merges |
| A second diff copy reappears | the C1 sentry fails |
| Column name that is data (misdeclared header the guard cannot see) | the stated `scan-set/v1` limit; the diff carries what the core carries |

## 5. Design notes and choke points

- New structure: two pure engine modules beside `scan_set.py`, one small CLI command module. One
  place per rule: buckets and drift kinds in `scan_diff.py`; the tag rule in `read_scan_set`; the
  verdict in `evaluate_drift`; the digest check in `bind_baseline`. Design principle applied:
  single responsibility (the diff rules change for drift-policy reasons, `scan.py` for command
  reasons); no new variant registry, since the drift kinds are a closed set of four.
- Choke point, diff rules: engine `profiling/scan_diff.py`. CLI seam: `decoy.cli.scanning`
  (`diff_tables`, `diff_sets`, `rescan_and_diff`, `pii_bucket`). Guard: sentry
  `tests/sentry/defects/test_one_scan_diff.py`. It walks the import graph of `src/decoy/` (AST) and
  fails when any module defines `compute_scan_diff`, `_pii_bucket`, `_bucket_rank`, `_BUCKET_RANK`
  or `_canon_qi`, or when a module other than `src/decoy/cli/scanning/_compare.py` imports an engine
  diff name. Listed shapes (recurring defect 5): `from decoy_engine import x`,
  `from decoy_engine.profiling import x`, `from decoy_engine.profiling.scan_diff import x`,
  `import decoy_engine.profiling.scan_diff as m`, and attribute access `decoy_engine.diff_scan_tables`
  or `profiling.diff_scan_sets`. Each shape has a seeded failing case. Mutation MC-2: a local bucket
  function in `scan.py`.
- Choke point, baseline binding: `bind_baseline` is the only builder of `BoundBaseline`, and
  `evaluate_drift` takes only a `BoundBaseline`, so a verdict cannot be computed on unbound bytes.
  Guard: F15-T7 constructor cell. Mutation MF-7b: allow direct construction.
- Choke point, scan tag rule: `read_scan_set`. Guard: the existing G-ONE-SCAN-READER sentry
  (`tests/sentry/test_scan_reader.py`) keeps holding, and F15-T4 pins the rule.

## 6. Reuse inventory

| Need | Reused | Not built |
|---|---|---|
| Diff rules | CLI `compute_scan_diff`, ported line for line, then deleted | new rules |
| Strict writer and relaxed reader | `ScanSetCore` pattern and its relaxing helper | a hand-copied read model |
| Scan tag and read model | `ScanSetCoreRead`, the CLI tag rule | a second tag parser |
| Rescan | D-2 `rescan_and_diff` through engine `scan_sources` | a run-local scanner |
| Baseline bytes | D-2 or B-2 one read (`read_scan_baseline`) | a second read |
| Refusal, exit 4 | D-2 `DriftBlockedError`, `run/_errors.py`, `exit_code_for` | a new exit code or error path |
| Drift codes and check id | D-1 (`drift_detected`, `drift_blocked`, `scan_drift`) | new drift codes |
| Config refusal shape | `PydanticCustomError` with a reason code, as `post_scan_inactive` | a custom exception path |
| Digest | `hashlib.sha256` over raw bytes, as B-2 | a canonical re-serialization |
| Corpus pinning across repos | CLI `ci/vendored.toml` byte pins | a hand-kept second fixture |

## 7. Placement

Engine (map: engine `CODEMAP.md` "Where things go"; `execution/` is frozen for new top-level files
and this plan adds none there; `profiling/` holds 18 modules, 21 after this plan, under the 25 cap.
Module sizes: no ceiling moves. `plan/_compile.py` is at 656 against its census ceiling of 666 and
E2 adds at most 4 lines there).

| File | New or changed | Where things go line | Sits beside | Slice |
|---|---|---|---|---|
| `src/decoy_engine/profiling/scan_diff.py` | new (~260): `pii_bucket`, diff functions and types, `ScanDiffCore`, `ScanDiffCoreRead`, `scan_diff_to_dict` | Detectors, profiling | `scan_set.py` | E1 |
| `src/decoy_engine/profiling/scan_set_read.py` | new (~70): `read_scan_set`, `ScanSetReadError` (`scan_set.py` is at the 600-line cap and is not edited) | Detectors, profiling | `scan_set.py` | E1 |
| `src/decoy_engine/profiling/__init__.py` | changed (127 lines): exports; the top-level `decoy_engine/__init__.py` (599 lines) is not edited | Public API | `ScanSetCoreRead` export | E1, E2 |
| `src/decoy_engine/profiling/bound_baseline.py` | new (~170): `BoundBaseline`, `bind_baseline`, `BaselineBindingError`, `DriftVerdict`, `DriftFinding`, `evaluate_drift` | Detectors, profiling | `scan_diff.py` | E2 |
| `src/decoy_engine/config/_scan_baseline.py` | changed: `sha256`, unbound rule, dump omission | Config models | `on_drift` | E2 |
| `src/decoy_engine/plan/_compile.py` | changed: hash `sha256` with `on_drift` | Plan compile and checks | the `on_drift` hash rule | E2 |
| `src/decoy_engine/profiling/_starter_config.py` | changed: `baseline_sha256` | Detectors, profiling | `baseline_path` | E2 |
| `src/decoy_engine/reasons/pre_scan/_part1.py`, `src/decoy_engine/reasons/config/_part2.py` | changed: three codes, since UNRELEASED | Reason codes | `DRIFT_BLOCKED` | E2 |
| `tests/unit/profiling/test_scan_diff.py`, `tests/unit/profiling/test_bound_baseline.py` | new | Unit tests mirroring `src/` | `test_scan_set.py` | E1, E2 |
| `tests/integration/compat_corpus/scan_diff/` | new: `scan-diff-v1.json` and the parity corpus `pairs.json` | compat corpus | `compat_corpus/records/` | E1 |
| `tests/snapshots/frozen_schemas/pipeline-config.schema.json` | changed: `sha256` | frozen schema snapshot | `on_drift` | E2 |
| `docs/frozen-surfaces.md`, `docs/compatibility-contract.md` | changed: `scan-diff/v1` row, tag, paragraph, public names; `sha256` config note | Feature and contract docs | `scan-set/v1` | E1, E2 |
| `src/decoy_engine/_MAP.md`, `CODEMAP.md` | changed: one line each for the two modules | package map | `scan_set.py` line | E2 |
| `changelog.d/<slice-slug>.md` | new fragment per slice | Changelog fragments | other fragments | E1, E2 |

`pii_bucket`, `diff_scan_tables` and `read_scan_set` merge in E1 before their CLI callers (C1,
after the release); `diff_scan_sets` gets its engine caller `evaluate_drift` in E2. This is the
plan-named pair across the release boundary that proportionality allows: the consumer slice C1 is
named here and lands before row 80 closes.

CLI (map: CLI `CODEMAP.md` "Where things go"; flat `src/decoy/cli/` is frozen and takes no file).

| File | New or changed | Where things go line | Sits beside | Slice |
|---|---|---|---|---|
| `src/decoy/cli/scanning/_compare.py` | changed (created by D-2; created here if D-2 has not merged): `diff_tables`, `diff_sets`, `pii_bucket`; `rescan_and_diff` returns the engine `ScanDiff` | `decoy scan` internals | `scanning/_multi.py` | C1 |
| `src/decoy/cli/scanning/__init__.py` | changed: re-exports | `decoy scan` internals | existing re-exports | C1, C2 |
| `src/decoy/cli/scan.py` | changed (1,157 to ~1,010): rules and buckets deleted, `_diff` on the facade, additive `scan_diff`, `bind` registered. It is a legacy over-cap file that may only shrink (`tests/sentry/baselines/module-size.json`, max 1157): C1 lowers the recorded max to its new count, and C2 offsets its registration lines inside the file (the command body is in `scanning/_bind.py`), so the max never rises | Command module (existing) | `_diff` | C1, C2 |
| `src/decoy/ci/adapters.py` | changed: drift on the facade | CI integration | `drift_outcome` | C1 |
| `src/decoy/cli/io/_scan_set.py` | changed: `_from_core` delegates to `read_scan_set` | Source readers | `load_scan_set` | C1 |
| `src/decoy/cli/run/_drift.py` | changed (D-2 file): engine verdict in C1; `bind_baseline` and finding lines in C2 | `decoy run` internals | `run/_prepare.py` | C1, C2 |
| `src/decoy/cli/scanning/_bind.py` | new (~90): `decoy scan bind` | `decoy scan` internals | `scanning/_compare.py` | C2 |
| `src/decoy/api.py` | changed: `on_drift` refusal | Python API | `_load_config_dict` | C2 |
| `tests/sentry/defects/test_one_scan_diff.py` | new sentry | Sentry test (recurring-defect class rules) | other `defects/` rules | C1 |
| `tests/fixtures/scan_diff/pairs.json` | new, vendored byte-identical from the engine corpus and pinned in `ci/vendored.toml` | shared fixtures, vendored | `tests/fixtures/release_freeze/` | C1 |
| `tests/e2e/scan_drift/` | new package for the e2e tests (not the flat `tests/e2e/`) | `tests/e2e/` | `tests/e2e/release_freeze/` | C1, C2 |
| `tests/fixtures/release_freeze/json-shapes.json`, `CHANGELOG.md` | changed: `scan diff` `/scan_diff`, new `scan bind` | `--json` success shapes | `scan diff` entry | C1, C2 |
| `tests/e2e/test_ci_unexpected_failures.py` | changed: the patched seam moves from `decoy.cli.scan.compute_scan_diff` | existing e2e | `"drift"` entry | C1 |
| `docs/cli-reference.md`, `docs/guides/` drift page, `docs/ROADMAP.md` | changed: `scan bind`, bound baselines, row 80 status | docs | row 32 text | C2 |

## 8. Enumerations

### Routes

- Drift check: CLI `run/_prepare.py`, baseline bytes read before staging and the check after
  `check_before_run` (`src/decoy/cli/run/_prepare.py:398`); covers resident, out-of-core,
  sequential, chunked and `--sample` runs, because it runs before route selection. `--rows`
  previews: not checked (D-2). `run --all`: each child `decoy run` checks its own YAML.
- Engine publication: every route publishes through `publish_unit`
  (`src/decoy_engine/publication/_publish.py:199`), behind `observed_commit`
  (`src/decoy_engine/execution/_publication_observer.py:142`) and the gate's `before_commit`
  (`src/decoy_engine/execution/pipeline/_post_scan.py:310`). A blocked drift run never opens a
  route, so none of these is reached. Row 80 adds nothing to them (Q5).
- Python API: `decoy.mask()` refuses `on_drift` before any route.
- Diff consumers: `decoy scan diff` (`src/decoy/cli/scan.py:943`), `decoy ci check` drift
  (`src/decoy/ci/adapters.py:158`), `decoy run` drift (`run/_drift.py`, D-2).

### Fields

- New config key `scan_baseline.sha256`; existing `scan_baseline.path`, `schema`, `on_drift`
  (`src/decoy_engine/config/_scan_baseline.py:30`).
- Scan fields the diff reads: `FieldCore.name`, `pii_score` (`src/decoy_engine/profiling/scan_set.py:148`);
  table `name`, `reid_risk_score`, `quasi_identifier_groups`; set `engine_version`, `detectors`.
- `scan-diff/v1` members: listed in 3.1. `DriftFinding`: `table`, `column`, `kind`.

### Exit paths

- Drift `failed`: `DriftBlockedError`, exit 4 (D-2 mapping), message with findings.
- Digest mismatch or unreadable baseline: exit 1 with the engine code, before any read or staging.
- `on_drift: fail` without `sha256`: config refusal, exit 1 (`decoy run`, `decoy validate`).
- `decoy scan diff --strict` with drift: exit 4, unchanged.
- `decoy scan bind` on a file that is not a `scan-set/v1` core: exit 2 (usage), fixed text, as the
  other `scan` subcommands.
- `decoy.mask()` with `on_drift`: `ConfigValidationError`.

### FK shapes

N/A: no slice reads or writes keys across tables. The diff compares per-table field metadata and
quasi-identifier groups; relationship facts in `scan-set/v1` are not compared (the rule set never
did).

### Output surfaces

- `scan-diff/v1` document (engine), returned by `scan_diff_to_dict`; the CLI shows it in
  `scan diff --json` as `scan_diff`.
- `decoy scan diff` text and `--json` (unchanged keys plus `scan_diff`); `decoy scan bind` text and
  `--json`.
- `decoy ci check` SARIF and JSON drift findings: unchanged.
- `decoy run` stderr drift lines and the `DriftBlockedError` text; the `--json` error object code.
- Logs: none added.

## 9. Frozen contracts touched

| Contract | Change | Compatibility |
|---|---|---|
| Persisted formats (contract 3.1) | new `scan-diff/v1` | new tag; frozen-surface row, corpus sample, read-model cells (E1) |
| Engine public names | the names in section 0, in `decoy_engine.profiling.__all__` | additive; described in the contract 3.1 paragraph beside `ScanSetCoreRead`; `decoy_engine.__all__` is unchanged |
| Pipeline config schema (snapshot) | `scan_baseline.sha256`; `on_drift: fail` requires it | optional key, omitted when absent; the `fail`-needs-digest rule is a pre-GA tightening of a key that has not shipped in a release (D-1 is unreleased) |
| Plan hash | `sha256` hashed with `on_drift` when set | configs without `on_drift` keep their hash (F15-T6) |
| Reason registry | three codes since UNRELEASED | `REGISTRY_VERSION` and reason manifests untouched; the release stamps them |
| CLI `--json` shapes (release freeze) | `scan diff` gains `/scan_diff`; new `scan bind` | additive; snapshot and CHANGELOG in the same slice |
| CLI command set | new `decoy scan bind` | additive; `docs/cli-reference.md` and `tests/unit/test_cli_surface.py` |
| CLI exit codes | none new | 1, 2 and 4 reused |
| `cli-local-1` evidence | none (B-2 owns the baseline fingerprint) | none |

## 10. Class table

| # | Class | Where it applies | Structure that closes it | Proof | Mutation |
|---|---|---|---|---|---|
| 1 | Value-bearing output | diff document, drift lines, binding errors | the diff reads only `scan-set/v1` core members; errors carry codes and config keys | F15-T3 canary, F15-C-T10 canary sweep | MF-3b, MC-10 |
| 2 | Cleanup missing on an exit path | blocked or unbound runs | the stop is before staging and before any stage opens, so nothing exists to clean | F15-C-T6 (empty output dir, no lock or stage files) | MC-6b: check after staging |
| 3 | Shared state across calls | diff and verdict | pure functions over immutable inputs; frozen dataclasses | F15-T1 repeat-call cell | MF-1c: module-level cache |
| 4 | Route parity and silent fallback | `scan diff`, `ci check`, `run` drift, API | one engine rule set behind one CLI seam; API refuses rather than skips | F15-C-T1, F15-C-T2 sentry, F15-C-T9 | MC-2, MC-9 |
| 5 | Referential counts across tables | baseline vs current table sets | `tables_added` drift, `tables_removed` reported | F15-T2 | MF-2 |
| 6 | Untrusted producer | hand-edited baseline, YAML digest | anchored digest match; `read_scan_set` strict tag and model; strict `scan-diff/v1` types | F15-T4, F15-T6, F15-T3 | MF-4, MF-6 |
| 7 | Check then use (TOCTOU) | baseline digest then parse | one read; digest and parse over the same bytes inside `bind_baseline` | F15-T7, F15-C-T7 (one open spy) | MF-7: parse a second read |
| 8 | Weak tests | parity passing vacuously | corpus pairs each with at least one non-empty change list; a no-drift pair and a drift pair per kind | F15-C-T1 corpus check | MC-1 |
| 9 | Refactor drift | moving the rules | line-for-line port with a vendored parity corpus captured from the CLI before deletion | F15-T1, F15-C-T1 | MC-1 |
| 10 | Frozen contract drift | `scan-diff/v1`, config schema, `--json` shapes | strict writer, derived reader, tag, corpus, frozen-surface row, snapshot | F15-T3, F15-T5, F15-T6, F15-C-T4 | MF-5, MF-6b |

Value-free errors (recurring defect 3): `ScanSetReadError`, `BaselineBindingError` and the C2 CLI
errors raise after their `except` block closes; F15-T4, F15-T7 and F15-C-T7 assert
`__cause__ is None and __context__ is None`.

## 11. Acceptance tests (written first; each red on today's main)

"Red before" says why the test fails on engine `902968682` or CLI `5b49510`. Each has a named
mutation that must turn it red; mutations run on the slice's final head (recurring defect 9).

### Engine

| Id | Slice | Asserts | Red before | Mutation |
|---|---|---|---|---|
| F15-T1 | E1 | `diff_scan_tables` over the parity corpus equals the expected rows captured from CLI `compute_scan_diff` at `5b49510` (bucket up and down, added, removed, new high PII, QI added and removed order-insensitive, risk delta `None` when either side lacks it, missing score compared as 0); two calls give equal results | module absent | MF-1: compare raw scores, not buckets; MF-1b: treat a missing score as `low`; MF-1c: cache by table name |
| F15-T2 | E1 | `diff_scan_sets`: a table only in `current` is `table_added` drift; one only in `baseline` is in `tables_removed` and not drift; `tables=` selects; a different `engine_version` or detector run sets `detectors_changed` and not drift | absent | MF-2: count `tables_removed` as drift; MF-2b: count `detectors_changed` as drift |
| F15-T3 | E1 | `scan_diff_to_dict` round trips through `ScanDiffCoreRead`; the write model refuses an unknown member, `True` or `"0.5"` as a score, free text as a drift kind; the read model ignores an unknown member, refuses a missing tag, `scan-diff/v2` and `"scan-diff/v1\n"`; a canary string placed in an unknown table member of the input never reaches the document; the corpus sample `scan-diff-v1.json` reads | absent | MF-3: lax model; MF-3b: copy unknown table members through |
| F15-T4 | E1 | `read_scan_set` accepts `scan-set/v1` and `scan-set/v1.3`, refuses `scan-set/v2`, `scan-set/v10`, a missing tag, a tag with a trailing newline and a document holding NaN, all with the same fixed text and no `__cause__` or `__context__` | absent | MF-4: `startswith("scan-set/v1")` without the `.` boundary |
| F15-T5 | E1 | the frozen-surface map sentry lists `scan-diff/v1` with its pinning test; `decoy_engine.profiling.__all__` holds every new name and `decoy_engine.__all__` is unchanged | row absent | MF-5: drop the `scan-diff/v1` row |
| F15-T6 | E2 | `sha256` 64 lowercase hex accepted; uppercase, 63 chars, a trailing newline, `True` refused; `on_drift: fail` without it refused with `config.scan_baseline_unbound` naming the field; `warn` without it accepted; absent `sha256` keeps the dump and plan hash byte-equal for configs with no `on_drift` and with `on_drift: warn`; setting `sha256` with `on_drift` moves the hash; `sha256` without `on_drift` does not; the schema snapshot holds the key | key unknown | MF-6: `re.match` with `$`; MF-6b: hash `sha256` when `on_drift` is absent; MF-6c: accept `fail` without a digest |
| F15-T7 | E2 | `bind_baseline` with matching bytes returns a bound `BoundBaseline`; one changed byte raises `pre_scan.baseline_digest_mismatch`; a reformatted file with the same content also mismatches; non-JSON, a legacy profile and `scan-set/v2` raise `pre_scan.baseline_unreadable`; error text holds neither digest nor path; no `__cause__` or `__context__`; `BoundBaseline(...)` outside `bind_baseline` raises `TypeError` | absent | MF-7: hash `json.dumps(json.loads(raw))`; MF-7b: allow direct construction |
| F15-T8 | E2 | `evaluate_drift` matrix: no drift `passed` with no code; drift under `warn` `warned` with `drift_detected`; under `fail` `failed` with `drift_blocked`; findings sorted by (table, column, kind) and hold names only; an unbound `warn` baseline reports `bound: false` | absent | MF-8: map `fail` to `warned` |
| F15-T9 | E2 | reason fixtures hold the three new codes with since UNRELEASED; `REGISTRY_VERSION` unchanged | codes absent | MF-9: bump the registry version |
| F15-T10 | E2 | `starter_config(baseline_sha256=...)` writes the bound block and the result passes `_check`; a non-hex value is refused | parameter absent | MF-10: write the digest without checking it |

### CLI

| Id | Slice | Asserts | Red before | Mutation |
|---|---|---|---|---|
| F15-C-T1 | C1 | for every pair in the vendored corpus, `decoy scan diff --json` without `scan_diff` equals the captured CLI output (parsed, numeric equality) and the text output is identical; `--strict` exits 4 exactly on the drift pairs; the corpus test refuses a pair with every change list empty unless it is marked `no_drift` | `scan_diff` key absent | MC-1: facade drops `qi_added` |
| F15-C-T2 | C1 | sentry `test_one_scan_diff.py` passes on the tree and fails on each seeded case (a local `_pii_bucket`, each listed import shape outside `scanning/_compare.py`) | sentry absent | MC-2: a bucket function in `scan.py` |
| F15-C-T3 | C1 | `decoy ci check` drift: the existing CI fixtures give the same rule ids, message ids, counts and exit (guard); the unexpected-failure test patches the new seam and still reports `ci.drift_unreadable` | seam absent | MC-3: catch and drop the facade's error |
| F15-C-T4 | C1 | `scan diff --json` `scan_diff` reads through engine `ScanDiffCoreRead` with its tag; the shape snapshot matches and `CHANGELOG.md` has the entry | key absent | MC-4: emit the dataclass dict without the tag |
| F15-C-T5 | C1 | (when D-2 has merged) the run drift verdict is the engine's: a spy sees one `diff_scan_sets` call per run, and D-2's D-T5 parity holds | D-2 diff in CLI | MC-5: keep a CLI verdict |
| F15-C-T6 | C2 | SCAN-14 e2e: `decoy scan`, `decoy scan bind`, paste the block with `on_drift: fail`, add a high-PII column to the source: exit 4; stderr names `customers.alt_email (new_high_pii_field)` and `pre_scan.drift_blocked`; the output directory holds no file, stage, descriptor or lock file; `--json` error code is `pre_scan.drift_blocked`; 12 drifted columns print 10 and `and 2 more` | no binding, no finding text | MC-6: message without findings; MC-6b: check after staging |
| F15-C-T7 | C2 | rescan the drifted source into the baseline path: exit 1 with `pre_scan.baseline_digest_mismatch` before any source read or `--duckdb-source` staging (read spy); the baseline file is opened once; `on_drift: fail` without `sha256` exits 1 at validation with `config.scan_baseline_unbound`; errors have no `__context__` | no binding | MC-7: skip the digest check |
| F15-C-T8 | C2 | `decoy scan bind scan.json` prints a block whose `sha256` equals SHA-256 of the file bytes; `--json` has `command`, `status`, `path`, `schema`, `sha256`; a legacy profile and a CSV are refused with exit 2 and fixed text; the printed block, pasted, gives a passing run | command absent | MC-8: hash the path text |
| F15-C-T9 | C2 | `decoy.mask(config)` with `on_drift: warn` or `fail` raises `ConfigValidationError` and opens no source (spy) | key ignored | MC-9: drop the refusal |
| F15-C-T10 | C2 | canary sweep: a canary cell value in every source column never appears in stderr, stdout, `--json` or the `scan_diff` document across F15-C-T6 to F15-C-T8 | no check | MC-10: print a sample value in the finding line |

## 12. Pre-mortem

- The port changes a result for an odd input (a missing score, an empty QI group). Guard: the parity
  corpus is captured from the live CLI function before deletion and vendored byte-identical into the
  CLI, so both repos test the same pairs.
- Between E1's merge and C1's merge two copies exist (one per repo). Guard: the window is bounded by
  the release and repin; E1's module docstring names C1 as the deletion; C1's sentry closes it.
- D-2 lands its own CLI `DriftVerdict` first and C1 must rewrite it. Guard: Q10 (D-2 builds on the
  engine API if the release is out first); either order leaves one rule set at every merge.
- A user rescans into the bound path and is surprised by exit 1. Guard: the error names
  `scan_baseline.sha256` and the hint says to review with `decoy scan diff` and re-bind with
  `decoy scan bind`; the guide has a worked example.
- Reformatting a baseline (an editor that rewrites JSON) breaks the binding. Guard: documented; raw
  bytes match the evidence fingerprint, and a rewritten file is a change to review (Q3).
- `scan.py` is in the one-writer lane with rows 29, 36, 53 and 56. Guard: C1 and C2 take the lane in
  turn; C1 removes about 150 lines, so later rebases shrink.
- The engine release that carries E2 slips. Guard: E1 alone is additive and unused; nothing in the
  CLI changes until the repin.
- A platform or SDK caller sets `on_drift: fail` and calls `run_pipeline` directly, so no check runs.
  Guard: V1 has no such caller (platform parked, `decoy.mask()` refuses); Q5 records it for the
  platform half.

## 13. Slices

At most 10 production files and about 800 lines each (tests counted). Risk per
`risk-and-exceptions.md`: R1 takes Codex-only review; R2 takes Dennis then Codex.

### 13.1 Slice table

| Slice | Repo | Content | Prod files | ~Lines | Risk | Waits on |
|---|---|---|---|---|---|---|
| E1 | engine | prep folded in: `scan_set_read.py` (`read_scan_set`); `scan_diff.py` (port, sets, document, models); parity corpus captured from CLI `5b49510`; exports; frozen-surface row, contract 3.1 tag and paragraph; changelog fragment; F15-T1 to F15-T5 | 4 | 660 | R2 (new frozen format) | none |
| E2 | engine | `scan_baseline.sha256` and unbound rule; plan-hash rule; `bound_baseline.py`; three reason codes; `starter_config(baseline_sha256=)`; schema snapshot; contract note, `_MAP.md` and CODEMAP lines; changelog fragment; F15-T6 to F15-T10 | 7 | 620 | R2 (config schema, blocking verdict) | E1 |
| Release and repin | both | daily train; repin checklist (memory engine-repin-checklist) | n/a | n/a | per train | 13.2 |
| C1 | CLI | diff move: facade in `scanning/_compare.py`; delete the CLI rules and buckets; `scan diff` additive `scan_diff`; `ci check` on the facade; `_from_core` on `read_scan_set`; `run/_drift.py` verdict from the engine if D-2 has merged; vendored corpus; sentry; shape snapshot and CHANGELOG; F15-C-T1 to F15-C-T5 | 6 | 700 | R2 (frozen `--json` shape, CI exit path) | repin to the E2 release |
| C2 | CLI | binding and named block: `bind_baseline` and finding lines in `run/_drift.py`; `decoy scan bind`; `decoy.mask()` refusal; docs last (cli-reference, drift guide with a worked bind example, `decoy explain exit-codes` text if it lists drift, ROADMAP row 80, CHANGELOG); F15-C-T6 to F15-C-T10 | 5 | 650 | R2 (refuses runs) | C1; D-2 merged |

Order: E1 then E2 (E2 imports `diff_scan_sets`). C1 then C2 (both write `scan.py` and
`run/_drift.py`). C1 can merge before D-2; C2 cannot, because it changes D-2's `run/_drift.py`.
Neither CLI slice touches `run/_prepare.py` (564 lines against its 600-line cap).

### 13.2 Engine release

The engine half is complete in the first daily-train release that contains E2, planned as engine
0.29.0 (0.28.0 is expected to carry D-1 before E1 can merge). If a train cuts between E1 and E2, E1
ships additive and unused, which is safe. C1 repins the CLI to that release with the repin checklist
(compatibility, fences, frozen surfaces, docs, `PIN_PREFIX`, the Dockerfile `ARG`, the catalog).

## 14. Owner questions (taken on the recommended answer)

Carried as decided: `plan/scan-checks` Q1 (`on_drift` on `scan_baseline`), Q2 (exit 4), Q12 (row 80
reuses `on_drift: fail`); `plan/drift` Q-A (one rescan helper in `scanning/_compare.py`) and Q-B
(D-2 returns a verdict; RESULT C1 builds the check).

| Q | Question | Answer taken (recommended) |
|---|---|---|
| Q1 | What is the bound-baseline object? | A digest pin `scan_baseline.sha256` in the reviewed YAML plus engine `BoundBaseline`, built only by `bind_baseline`. No approval store, role or record kind in V1; L2 and L4a can add a ref on the same digest |
| Q2 | Is the digest required? | Required under `on_drift: fail` (`config.scan_baseline_unbound`), optional under `warn` |
| Q3 | Digest of raw bytes or canonical JSON? | Raw bytes: equals B-2's evidence fingerprint, and a rewritten file is a change to review |
| Q4 | Does `sha256` enter the plan hash? | Yes, with `on_drift`, only when `on_drift` is set |
| Q5 | Should the engine itself refuse to publish (at `observed_commit` or `publish_unit`) when `on_drift: fail` is set and no passing verdict was given? | No for V1. The CLI is the only caller and stops before any read; `decoy.mask()` refuses. V2-LOG with the platform half of F15 |
| Q6 | How does the CLI expose `scan-diff/v1`? | Additive `scan_diff` member in `scan diff --json`; no new file output |
| Q7 | Is a detector or engine change drift? | No: `detectors_changed` is information; the bucket changes it causes count as before |
| Q8 | Rename detection? | No; removed plus added. V2-LOG |
| Q9 | How does a user bind? | `decoy scan bind SCAN` prints the block; it never edits YAML. `--emit-config` (row 29) writes it through `starter_config(baseline_sha256=)` when built |
| Q10 | D-2 and the engine API: which first? | If the E2 release is out before D-2 starts, D-2 calls `evaluate_drift` and `diff_scan_sets` directly and C1 drops its `run/_drift.py` part; otherwise C1 switches D-2's call |
| Q11 | A missing score printed `0` in `scan diff --json`; the engine keeps floats (`0.0`). Accept? | Yes; numeric JSON equality and identical text; CHANGELOG line |
| Q12 | Which engine release carries the engine half? | The first train release containing E2, planned 0.29.0 |
| Q13 | `decoy.mask()` with `on_drift` set? | Refuse with `ConfigValidationError` before any read; the drift check runs only under `decoy run` in V1 |
| Q14 | Row 80's After lists STORM rename and SCAN-LIB. Keep? | Replace with "row 32 D-2 (C2 only)". Row 80 adds no STORM-named surface and uses V1 names; it needs only a `scan-set/v1` file, not the library |
| Q15 | Fewer slices? | No. E1 plus E2 is about 1,260 lines and C1 plus C2 about 1,350, both over the 800-line cap. Prep is folded into E1 and C1; docs go in E2 (contract) and C2 (user docs) |

## 15. V2-LOG

- Engine-side refusal for callers that skip the drift check (Q5), with the platform pre-scan
  re-enable.
- Approval records with owner, reason and expiry; scoped suppressions; review queues (spec F15
  example 2).
- Rename detection; relationship-fact drift (orphans, key shape) in `scan-set/v1` diffs.
- A per-match detector version on `DetectorMatch` (row-detail note); V1 identifies the detector set
  by `engine_version` and the `detectors` runs, and the diff reports a change.
- `decoy validate` checking the baseline digest without a run.

## 16. Roadmap edits when this plan passes

- Row 80: "Plan `E:plan/f15-bound-baseline` (`2026-11-17-f15-bound-baseline.md`), slices E1, E2, C1,
  C2; engine half in the release with E2 (planned 0.29.0)". After becomes "row 32 D-2 (C2 only)"
  (Q14).
- Row 32: "D-2 calls engine `evaluate_drift` if the F15 release is out first (Q10)".
- Row 29: "`--emit-config` writes `scan_baseline.sha256` through `starter_config(baseline_sha256=)`".
- `plan/drift` section 1 non-goal "Moving the scan-diff rules into the engine (row 80 F15)": a
  pointer to this plan.
