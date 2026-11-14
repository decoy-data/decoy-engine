Status: plan

# DUP-DEST: refuse two tables that write to one destination

Rules consulted: `/home/cam/dev-rules/README.md`, `00-universal.md`, `risk-and-exceptions.md`,
`development-loop.md`, `bug-fix.md`, `architecture.md`, `reuse-first.md`,
`api-and-compatibility.md`, `security.md`, `testing.md`, `verification.md`, `documentation.md`,
`catalogs/recurring-defects.md`; engine `CLAUDE.md`, `CODEMAP.md`,
`docs/compatibility-contract.md`; CLI `CODEMAP.md`, `docs/ROADMAP.md`.

Revision 2: Dennis round 1 (GO-WITH-FIXES, 2 V1, 5 DESIGN, 4 V2-LOG) remediated; changes are
marked "(r2)" where a reviewer needs to find them.

Bases (2026-11-14): engine `origin/main` `187a14e6`, CLI `origin/main` `65b710c` (pins
`decoy-engine==0.24.0`). Related work in review: engine PR #589 (SCAN-MULTI S3-engine.2, branch
`feat/scan-multi-s3e2`), whose plan amendment adds `config.target_identity(target)` to
`config/_targets.py` as the one definition of "same destination". This plan reuses it and adds no
second definition.

Owner decisions used: the V1 bar (2026-11-02: a product-function break, data loss or corruption,
or real values or secrets shown to a non-admin block V1); "names may show in messages; data values
never" (2026-11-06); row 24b QA-GATE (2026-11-08: "`decoy validate` refuses what `run` would
refuse ... fail at the gate with exit 1, the config-error code").

Risk: R2 (a config refusal widens on every caller, and the CLI's Python API gains a refusal before
its first write). Out of scope: two outputs that collide only after a run starts (a file another
process creates mid-run), quarantine paths on the engine side (the sink's
`committed_table_path` check and the CLI collision rule already cover them), the parked platform's
own writers, and SFTP targets (no `SFTPTarget` exists).

## 1. Frame

### 1.1 What exists

- **CLI `decoy validate`, `decoy run`, `decoy ci check`, and `decoy tokenize --out-dir`.** These
  reach `layout_issues` (`src/decoy/cli/io/_placement.py:261`), whose last step is
  `resolved_output_collisions` (`_placement.py:213`). It keys every local file target, an enabled
  quarantine and the typed side files by filesystem identity (`_destination_key`, `:127`: device
  and inode for existing files, nearest existing directory plus a normalized suffix otherwise,
  case and NFC folding where the volume folds) and refuses the first clash with
  `layout.output_path_collision`, exit 1, naming config locations only. Cloud targets take a
  separate rule (`_cloud.py:_key_issues`, `:111`): every cloud target must share one directory
  (`_split_issues`), and two with the same file name are refused with `cloud.target_invalid`.
  `resolved_output_collisions` keys a relative path only when `names_a_file_inside(raw)` holds
  (`_placement.py:231`, `io/_layout.py:187`), so `../x.csv`, backslash names and trailing slashes
  are left out; in a contained layout those paths are refused elsewhere.
- **CLI `decoy tokenize` without `--out-dir` (r2).** Runs the schema (`tokenize.py:239`), then
  the layout check only under `--out-dir` (`tokenize.py:310`). The project route goes to
  `open_run_layout` (`:335`), `run_pipeline` with a quarantine path (`:349`) and
  `_write_mask_outputs` (`:367`) with no collision rule: two equal targets, or a target on the
  `--vault` path, overwrite silently. A lost vault makes the run's tokens irreversible.
- **CLI `decoy.mask()`** (`src/decoy/api.py:326`). Validates with `parse_pipeline_config`, builds
  `RunLayout.fixed(base_dir)` (`api.py:509`) and calls `_write_mask_outputs` (`api.py:559`,
  defined at `cli/run/_execute.py:302`), which loops `write_targets`
  (`src/decoy/cli/io/_targets.py:461`). It never calls `layout_issues` or
  `resolved_output_collisions`. A fixed layout is not contained: `place_target` resolves any
  relative path, `../x.csv` included, against the base and follows links
  (`io/_layout.py:575-576`).
- **Engine.** `PipelineConfig` (`config/_pipeline.py`) checks no pair of targets. `FileTarget`,
  `S3Target` and `GCSTarget` (`config/_targets.py`) validate one target each. The only
  cross-target path rule is `_subset_stage_constraints` (`_pipeline.py:370`), which compares
  targets with sources. The engine itself writes no target path: `run_pipeline` returns one table
  per output, and a `TransactionalSink` names each file by table (`_transactional_sink.py:344`),
  so two tables cannot meet in a sink.

### 1.2 Probe (2026-11-14, Mac mini, macOS arm64)

Throwaway probes, never committed: CLI worktree at `65b710c` (engine 0.24.0 from the lock) and
engine worktree at `187a14e6`, made-up values only.

| Case | Engine `PipelineConfig` | CLI `validate` | CLI `run` | CLI `decoy.mask()` |
|---|---|---|---|---|
| two file targets, same relative path | accepted | exit 1 `layout.output_path_collision` | exit 1, same code, nothing written | **both tables written to one file; the second replaced the first; no error** |
| `out/a.csv` vs `out/./a.csv` | accepted | exit 1 | exit 1, nothing written | **overwrite, no error** |
| `out/a.csv` vs `out/A.csv` (APFS folds case) | accepted | not probed | exit 1, nothing written | not probed |
| same absolute path | accepted | not probed | exit 1, nothing written | **overwrite, no error** |
| `out=` dict giving two tables one path | not applicable | not applicable | not applicable | **overwrite, no error** |
| mask table and generate table, same path | accepted | not probed | exit 1, nothing written | not probed |
| `run --out-dir build`, same relative path | not applicable | not applicable | exit 1, nothing written | not applicable |
| `run --chunked`, two mask tables, same path | not applicable | not applicable | exit 1, nothing written | not applicable |
| two S3 targets, same bucket and key | accepted | exit 1 `cloud.target_invalid` | exit 1, nothing written | refused (`UnsupportedCloudEndpointError`, no cloud in the API) |
| two GCS targets, same bucket and object | accepted | exit 1 (`cloud.target_unsupported` for GCS, plus `cloud.target_invalid`) | exit 1 | refused as above |
| engine `run_pipeline`, two generate tables, same target path | n/a | n/a | n/a | engine returned both tables and wrote no file |

`decoy tokenize` was not probed; its gap (1.1) is read from the code (Dennis r1).

### 1.3 Problem

`decoy.mask()` writes two tables to one file without a word: the first table is lost on disk while
the call returns both frames, so the caller sees success. That is data loss, a V1 blocker. The
engine accepts the same config, so any engine caller that writes targets (the parked platform
runner, a script on the public API) has to find the clash itself, and today only the CLI's
command routes do. `decoy tokenize` on the project route has the same gap as `mask()`, with the
vault as one more file that can be lost.

## 2. Guarantee

1. A pipeline config in which two or more targets have the same `target_identity` is refused by
   `PipelineConfig` validation, so by every caller that validates (`parse_pipeline_config`,
   `PipelineConfig.model_validate`), before any source is read or any output written. The code
   is `config/target_shared_destination`; each table in the clash gets one problem located at the
   field that names the destination (`targets.<table>.path`, `.key` or `.object`, the locations
   the CLI already prints), in config order (r2). The text is the registry's fixed summary. No path, bucket,
   key or object appears in any message, location or log line.
2. `decoy.mask()` and `decoy tokenize` (both routes) refuse two outputs that resolve to one file
   on disk (symlinked folder, case-only difference on a folding volume, hard link, relative
   against absolute spelling, a relative path that leaves the base folder, a target against an
   enabled quarantine path, and for tokenize a target against `--vault`) with the CLI's existing
   `layout.output_path_collision`, before any source is read and before any output is written.
   (`mask()` spools `data=` frames to private temp files first, `api.py:245-255`; those are
   inputs, not outputs.)
3. For one config, `decoy validate` and `decoy run` report the same first code: the engine code
   for declarations that are the same destination as written, the layout code for outputs that
   meet only on disk. Exit 1 in both.
4. A config whose targets are all distinct behaves exactly as today: same validation result, same
   output bytes.

## 3. Established solutions

- dbt refuses at compile time two models that resolve to one relation identifier
  (`database.schema.alias`) and names both nodes, rather than letting the second build replace
  the first. The rule here is the same shape: compare a canonical identity of each declared
  output, refuse a shared one, name the declarers.
- GNU Make warns "overriding recipe for target" when two rules write one target; we refuse instead
  of warning, because the second write destroys data.
- The CLI already holds the filesystem half (`_destination_key`, plan 3.6.1 B of
  `plan/project-layout`); this plan reuses it rather than writing a second one.

## 4. Design

### 4.1 Engine: one validator on `PipelineConfig`

- `PipelineConfig._targets_distinct`, a `model_validator(mode="after")` in `config/_pipeline.py`.
  It groups `self.targets` by `target_identity(target)` (from #589; file:
  `("file", os.path.normpath(path))`, S3: `("s3", bucket, key)`, GCS: `("gcs", bucket, object)`).
  For each identity held by two or more tables it adds one
  `(("targets", table, field), code)` problem per table, `field` being `path`, `key` or `object`, then raises through `problem_details` and `ValidationError.from_exception_data`, the
  pattern `_unique_domains_valid` already uses (`_pipeline.py:340`). `validation_problems` turns a
  registered code into its fixed summary, so the message carries no input.
- Reason code `target_shared_destination` in the `config` domain, declared in
  `reasons/config/_part2.py` under `_catalog.config("PipelineValidationError")`
  (`_part2.py:49`), the owner of every code `PipelineConfig` raises through `problem_details`
  (r2; the `target_file.*` codes in `_part1.py` belong to the legacy `validation_result` owner).
  `since=UNRELEASED`, summary "Two or more targets write to one destination. Give each table its
  own target." It joins the unreleased set that release prep stamps, and the owner table in
  `tests/unit/test_reason_registry.py:357`.
- Calling convention (r2). `self.targets` holds pydantic models; #589's starter builder holds
  dicts. E1 calls `target_identity(t.model_dump())` unless #589 lands a signature that takes
  both. The `type` field is a discriminated union, so an unknown type never reaches the
  validator; `target_identity`'s own unknown-type error (#589) must still name the type only and
  subclass `ValueError`, so a later caller sees a `ValidationError`, never a bare exception
  through `parse_pipeline_config` (`config/_parse.py:24-29`). Request to the orchestrator: pin
  both in #589 before it merges.
- Identity is the text form only. Symlinks, case folding and relative against absolute are the
  writer's concern at run time (#589's amendment says the same for the starter builder), and the
  CLI's writer already checks them (4.2).
- Table kind does not enter: mask, generate and mixed tables are all keys of `targets`.
- One choke point. `compile_plan` and `run_config_only_checks` do not repeat the check:
  `run_pipeline` documents that its config is the validated dump, and the engine writes no
  target path itself (1.1).

### 4.2 CLI

- **CL1, `decoy.mask()` (r2: placed paths).** After `parse_pipeline_config` and the `out=` merge,
  before `_load_sources_from_config` (`api.py:506`), check the paths the writer will use, not the
  declared text. Copy `config_dict`; replace each local file target's `path` with
  `str(layout.place_target(raw))` and an enabled `quarantine.output_path` with
  `str(layout.place_quarantine(config_dict))` (the call `api.py:535` already makes), on the
  `RunLayout.fixed(base_dir)` the call builds; then call `resolved_output_collisions(placed, None)`.
  Every path is now absolute, so `names_a_file_inside` no longer drops `../x.csv`. On a clash
  raise `OUTPUT_PATH_COLLISION.error(first=..., second=...)` with the original config locations,
  the same `LayoutError` `decoy run` raises, documented under the API's `Raises:`. Import both
  from the public `decoy.cli.io` (`io/__init__.py:69`, `:98`), not `_placement`. No new rule, no
  new code. This lands on the current engine pin and closes the `mask()` data loss by itself.
- **CL1, `decoy tokenize` (r2).** Move the layout check out of the `if out_dir is not None` guard
  (`tokenize.py:310`): before any folder or source, call `layout_findings(config_path, raw,
  placement)` with `OutputPlacement.fixed(out_dir, (("--vault", vault),))` under `--out-dir` (as
  today) and `OutputPlacement(typed=(("--vault", vault),))` on the project route (the shape
  `run` uses, `run/_prepare.py:257`), and render the refusal the way the `--out-dir` branch does
  (`tokenize.py:315-321`). Same rule, same code, exit 1.
- **CL2, run and validate parity (after the repin to the engine release that carries E1).**
  `decoy run` checks layout before the gate (`run/_prepare.py:260` `_refuse_layout_faults`,
  called at `:319`), while `decoy validate` runs the schema first and stops there
  (`gate/_layers.py:117`). With E1 in, the same config would give `layout.output_path_collision`
  from run and `config/target_shared_destination` from validate. `_refuse_layout_faults` skips the
  early refusal only when `parse_pipeline_config(ctx.raw)` refuses with a problem whose code is
  `config/target_shared_destination` (r2); the gate then reports it in both commands. Any other
  schema refusal keeps today's order, so a source-less YAML that relies on `--duckdb-source`
  (refused by the schema at `_pipeline.py:216` before staging) still gets its layout fault
  before `acquire_relation` reads a source, the invariant at `_prepare.py:315-316` that
  `tests/e2e/test_vault_commit_order.py` pins. After-validators stop at the first raise, so that
  YAML never reaches E1.
- **CL2, test expectations.** The AT-31 cells in `tests/e2e/project_layout/test_layout_gate.py`
  whose outputs are the same as written (two equal relative paths, equal absolute paths, dot and
  separator spellings) now expect `config/target_shared_destination` at `targets.a.path` and
  `targets.b.path`, which `_assert_collision` (`test_layout_gate.py:513-517`) already checks;
  the symlink, hard-link, case-folding and target-against-quarantine cells keep
  `layout.output_path_collision`. The `validate preflight` cells (`test_layout_gate.py:525`,
  `:554`, `:585`) report a schema failure as `schema.field` with no code
  (`preflight.py:695-700`); they change to expect `schema.field` at those locations. A `code` on
  preflight schema failures is a `--json` change and belongs to row 24zf's one error shape, not
  here (OQ-5). Cloud
  cells with two equal keys expect the engine code; the CLI's "shares its file name" branch in
  `_key_issues` stays as a defense.

## 5. Behaviour

| Input | Before | After |
|---|---|---|
| engine `PipelineConfig.model_validate` with two equal targets (any type) | accepted | `ValidationError`, one `config/target_shared_destination` per table |
| CLI `validate`, two equal targets | exit 1 layout or cloud code | exit 1 `config/target_shared_destination` |
| CLI `run`, two equal targets | exit 1 layout or cloud code | exit 1 `config/target_shared_destination` |
| CLI `run` or `validate`, outputs equal only on disk | exit 1 `layout.output_path_collision` | unchanged |
| `decoy.mask()`, two equal targets or `out=` paths | silent overwrite | CL1: `LayoutError` `layout.output_path_collision`; after the repin `ConfigValidationError` (`api.py:458-465`) with the engine code fires first (OQ-4; CLI changelog line) |
| `decoy.mask()`, outputs equal only on disk, or `../x.csv` twice | silent overwrite | `LayoutError` `layout.output_path_collision` |
| `decoy tokenize` (project route), two equal targets, or a target on `--vault` | silent overwrite | exit 1 `layout.output_path_collision`; after the repin, equal targets give the engine code first |
| any config with distinct targets | runs | runs, same bytes |

## 6. Failure modes

### 6.1 Class table

| # | Class | Structure that closes it | Proof | Mutation that turns it red |
|---|---|---|---|---|
| 1 | Value-bearing output | the engine problem text is the registry summary; the location is `targets.<table>`; no path, bucket, key or object reaches a message, `str(exc)`, a log line or `--json`. CL1 reuses `OUTPUT_PATH_COLLISION`, which names config locations only | T-E8, T-C1 | interpolate the path into a custom message |
| 2 | Cleanup missing on an exit path | N/A with a reason: both refusals fire before any output is opened, so nothing is left behind | T-C1 (no file under the folder) | move the CL1 check after `_write_mask_outputs` |
| 3 | State and concurrency | N/A: the validator and the CL1 check are pure functions of the config and the folder; no shared or module state is added | T-E6 (stable order) | collect problems in a module-level set |
| 4 | Route parity and silent fallback | one engine choke point (`PipelineConfig`) covers every engine caller; CL1 brings `decoy.mask()` and `decoy tokenize` (both routes) to the rule `run`, `validate` and `ci check` already use, on the placed paths; CL2 makes `validate` and `run` report the same first code and keeps every other ordering | T-C1, T-C2, T-C5, T-C8, T-C9, T-C10, T-C11 | skip the CL1 check when `out=` is given; keep the tokenize `out_dir` guard; skip the early refusal on any schema failure |
| 5 | Referential integrity | no key or FK path changes; the tokenize vault is protected by entering the collision rule as a typed side file, so no target can replace it | T-C8 (target on `--vault`) | drop `--vault` from the tokenize placement |
| 6 | Untrusted producer | the config is user input; the discriminated `type` refuses an unknown type before the validator, and `target_identity` raises a `ValueError` naming the type only, so a type added later without an identity fails validation instead of being skipped | T-E10, #589's `target_identity` tests | return `None` for an unknown type and skip it |
| 7 | Check then use (TOCTOU) | the engine check is on declarations, so it has no filesystem window. CL1 checks the paths `place_target` returns, the ones the writer then uses; a file or link created by another process between the check and the write is out of scope (header), same as today's `run` | T-C3, T-C9 | check the declared text instead of the placed path |
| 8 | Weak tests and overclaimed evidence | every test names the code, the locations and that no file exists; each test has a named mutation in section 7; mutations rerun on the final head | gate reviewers rerun them | relax T-E1 to "raises `ValidationError`" |
| 9 | Behaviour-preserving refactor drift | no product code moves; E1 migrates test helpers and one script that gave every table one placeholder target (7.1a) to one placeholder per table; targets are not part of the config hash (`plan/_compile.py:622`), so outputs and the proof manifest do not change | T-E9, the E1 full suite, `tests/sentry/test_proof_manifest.py` | keep `/dev/null` for every table in `_chunked_entry_support.py` |
| 10 | Frozen contract drift | one reason code added (`since=UNRELEASED`, owner `PipelineValidationError`); no exit code or `--json` shape moves; CL2 changes which code some configs report, and `mask()`'s exception type for equal targets, before REL-GATE (row 93) | T-C5, T-C6, T-E11 | renumber or rename an existing code; declare the code under the `validation_result` owner |

### 6.2 Enumerations

#### Exit paths

| Entry point | Where it refuses | Exit or raise |
|---|---|---|
| engine `parse_pipeline_config` / `PipelineConfig.model_validate` | `_targets_distinct`, beside `_unique_domains_valid` (`config/_pipeline.py:340`) | `ValidationError` (`PipelineConfigError` from `parse_pipeline_config`) |
| CLI `decoy validate` | gate schema layer (`gate/_layers.py:117`) | 1 |
| CLI `decoy run` (plain, `--chunked`, `--out-dir`) | today `_refuse_layout_faults` (`run/_prepare.py:260`, called at `:319`); after CL2 the gate | 1 |
| CLI `decoy ci check` | `layout_findings` in the gate | 1 |
| CLI `decoy tokenize` (both routes) | the engine schema (`tokenize.py:239`), then after CL1 `layout_findings` before `open_run_layout` (`:335`) | 1 |
| CLI `decoy.mask()` | CL1 check after `parse_pipeline_config` (`api.py:460`), before `_load_sources_from_config` (`api.py:506`) | raises `LayoutError`; after the repin `ConfigValidationError` for equal declarations |

#### Routes

| Route | Reaches the engine rule | Reaches the CLI disk rule |
|---|---|---|
| whole-frame `run` | yes, schema | yes, `resolved_output_collisions` (`io/_placement.py:213`) |
| `run --chunked` | yes | yes |
| `decoy.mask()` | yes, `parse_pipeline_config` (`api.py:460`) | CL1 adds it, on placed paths |
| `decoy tokenize`, project route | yes, `parse_pipeline_config` (`tokenize.py:239`) | CL1 adds it, with `--vault` as a typed side file |
| out-of-core and sink routes | yes; the sink names files by table (`execution/_transactional_sink.py:344`) | the CLI's `run` rule, as today |
| cloud delivery (CLI-CLOUD, row 64) | yes, `("s3", bucket, key)` / `("gcs", bucket, object)` | `_cloud.py:_key_issues` (`io/_cloud.py:111`) stays as a defense |

#### FK shapes

N/A: no key, FK or relationship code path changes. Two tables in a parent and child pair that
share a destination are refused like any other pair.

#### Fields

| Field | Part of the identity |
|---|---|
| `targets.<t>.type` | yes, first element |
| file `path` | yes, after `os.path.normpath` |
| file `format`, `layout` | no: two formats in one file still destroy one table |
| S3 `bucket`, `key` | yes |
| S3 `region`, `endpoint_url`, `credentials_ref` | no (#589's definition; an endpoint override pointing at two stores is out of scope and the CLI refuses `endpoint_url`) |
| GCS `bucket`, `object` | yes |
| GCS `credentials_ref` | no |

#### Output surfaces

- Masked and generated table bytes: unchanged for every config that still validates.
- Config refusal on stderr and the `--json` error envelope: one new code; locations name tables.
- Evidence, reports, manifests, the run result: unchanged (the refusal precedes them all).

## 7. Acceptance tests, red first

### 7.1 Engine (E1), `tests/unit/config/test_target_destinations.py`

| Id | Test | Mutation that must turn it red |
|---|---|---|
| T-E1 | two file targets, same path: refused, problems at `targets.a` and `targets.b`, code `config/target_shared_destination` | M-E1: remove the validator |
| T-E2 | `out/a.csv` against `out/./a.csv` and `out//a.csv`: refused | M-E2: compare `path` instead of `target_identity` |
| T-E3 | S3 same bucket and key refused; same key in another bucket accepted; same bucket, other key accepted | M-E3: drop the bucket from the comparison |
| T-E4 | GCS, the three cells of T-E3 | M-E4: as M-E3 for GCS |
| T-E5 | file `a.csv` against S3 key `a.csv`: accepted | M-E5: compare without the type element |
| T-E6 | three tables on one destination give three problems in config order; two separate pairs give four | M-E6: report only the second table of a group |
| T-E7 | a mask table and a generate table on one path: refused | M-E7: group only tables with `columns` |
| T-E8 | on the raw `PipelineConfig.model_validate` error (r2): no path, bucket, key or object text in `str(exc)` or any `errors()` `msg`, `input` or `ctx`; the same on `PipelineConfigError` problems; `__cause__` and `__context__` are `None`; the code is registered | M-E8: interpolate the path into a custom message |
| T-E9 | distinct targets: the existing config fixtures still validate; the E1 full suite is green after the 7.1a migration | none |
| T-E10 | an unknown target `type` is refused as today (discriminator), not by a bare exception from the validator | M-E10: make the validator accept a raw dict and call `target_identity` on it before the union check |
| T-E11 | registry: `target_shared_destination` has owner `PipelineValidationError`, `since=UNRELEASED`, and the kind and retry of the other config codes (modelled on the GEN_UNIQUE registry test) | M-E11: declare it in `_part1.py` |

### 7.1a Engine callers E1 migrates (r2)

Each gives every table one target path today; E1 gives each table its own placeholder (for
`/dev/null` users, a per-table name under the test's `tmp_path`, or a path the test never writes).
This list is from an AST scan at `187a14e6`; the builder reruns the scan on the E1 base and stops
if a production caller appears.

| File | Line |
|---|---|
| `scripts/gen_proof_manifest.py` (release prep; `tests/sentry/test_proof_manifest.py`) | 148-151 |
| `tests/native/_chunked_entry_support.py` (about 74 test files use it) | 52 |
| `tests/unit/execution/run_stream/_support.py` | 120 |
| `tests/unit/generation/kinds/_support.py` | 30 |
| `tests/unit/generation/unique/_gu_corpus.py` | 23 |
| `tests/unit/generation/unique/_gu_e2_support.py` | 19 |
| `tests/unit/test_v2_generation.py` | 1048 |

Shared test helpers are a `testing.md` escalation trigger: E1 runs the full engine suite against
the stored main baseline.

### 7.2 CLI CL1 (current pin), `tests/e2e/test_mask_api_destinations.py`

| Id | Test | Mutation |
|---|---|---|
| T-C1 | `decoy.mask(config=...)` with two equal absolute targets raises `LayoutError` `layout.output_path_collision`; no source read (patch `decoy.api._load_sources_from_config`, bound at import, `api.py:40`); `run_pipeline` never called (spy; quarantine is written inside it); no file under the folder | M-C1: skip the check |
| T-C2 | `out={"a": p, "b": p}` on distinct declared targets: refused | M-C2: check before the `out=` merge |
| T-C3 | relative dot spelling; case-only names with `_placement._folds_case` monkeypatched true (as `test_layout_gate.py:609` does, so Linux CI runs it); a symlinked folder | M-C3: compare `normpath` text instead of `resolved_output_collisions` |
| T-C4 | distinct targets: both files written with their own rows | none |
| T-C9 | two `../shared.csv` targets; `../shared.csv` against its absolute spelling; `sub/../a.csv` through a symlinked `sub` against the real path: all refused, nothing written outside the base | M-C9: pass the declared `config_dict` with `base_dir` instead of the placed paths |
| T-C10 | a target equal to the enabled `quarantine.output_path`: refused, `run_pipeline` never called | M-C10: leave quarantine out of the placed copy |
| T-C8 | `decoy tokenize` on the project route: (a) two equal targets, (b) a symlinked spelling of one target, (c) a target equal to `--vault`: exit 1 `layout.output_path_collision`, no output written, the vault file absent or byte-identical; (d) the same three under `--out-dir` stay refused | M-C8: keep the `out_dir is not None` guard |

### 7.3 CLI CL2 (after the repin)

| Id | Test | Mutation |
|---|---|---|
| T-C5 | the same config through `validate` and `run`: same first code, exit 1, for (a) two equal relative paths: `config/target_shared_destination`; (b) a symlinked folder: `layout.output_path_collision` | M-C5: keep the early layout refusal |
| T-C6 | two S3 targets with one key: `config/target_shared_destination` from both commands | M-C6: as M-C5 |
| T-C7 | updated AT-31 cells per 4.2, including the three `validate preflight` cells expecting `schema.field` at `targets.a.path` and `targets.b.path` | none |
| T-C11 | a source-less YAML that relies on `--duckdb-source`, plus a symlink collision: `run` exits 1 `layout.output_path_collision` and `acquire_relation` is never called | M-C11: skip the early refusal on any schema failure |

## 7a. Reuse inventory

| Need | Reused | Not reused, why |
|---|---|---|
| same destination as declared | `config.target_identity` (#589) | none |
| coded value-free config problem | `_generate_options.problem_details`, `validation_problems` | none |
| same file on disk | CLI `resolved_output_collisions`, `OUTPUT_PATH_COLLISION` (from public `decoy.cli.io`) | none |
| placed path the writer uses | `RunLayout.place_target`, `RunLayout.place_quarantine` | none |
| tokenize layout check | `layout_findings`, `OutputPlacement`, the `--out-dir` branch's renderer | none |

## 8. Placement

| Change | File | CODEMAP row |
|---|---|---|
| validator | `src/decoy_engine/config/_pipeline.py` (406 lines, about +25) | `config/_pipeline.py` |
| reason code | `src/decoy_engine/reasons/config/_part2.py`, owner table in `tests/unit/test_reason_registry.py` | reasons |
| engine tests | `tests/unit/config/test_target_destinations.py` (new) | |
| E1 caller migration | the seven files in 7.1a | |
| changelog | `changelog.d/dup-dest-e1.md`; CLI changelog line for `mask()`'s exception at the repin | |
| docs | engine `docs/config-reference.md` targets section, or the file the builder finds holding it (`git grep -l "targets:" docs/`): one line, "each table needs its own destination" | |
| CLI API check | `src/decoy/api.py` (CL1) | CLI `api.py` |
| CLI tokenize check | `src/decoy/cli/tokenize.py` (CL1) | CLI `tokenize.py` |
| CLI run parity | `src/decoy/cli/run/_prepare.py` (CL2) | CLI `run/` |
| CLI tests | `tests/e2e/test_mask_api_destinations.py` (new, CL1); a tokenize cell file beside the existing tokenize e2e tests (CL1); `tests/e2e/project_layout/test_layout_gate.py` (CL2) | |

No new module; `config/` and top-level module counts are unchanged.

## 9. Frozen contracts touched

- **Reason registry.** One code added, `since=UNRELEASED`; release prep stamps it.
- **Exit codes.** None move (1 before, 1 after).
- **`--json` shapes.** Unchanged; some configs report a different code before REL-GATE (row 93)
  freezes codes. Preflight gains no `code` field here (OQ-5).
- **Python API.** `decoy.mask()` raises `LayoutError` for a destination clash after CL1; after the
  repin, equal declarations raise `ConfigValidationError` instead (OQ-4).
- **Determinism and output bytes.** Unchanged for every config that still validates.

## 10. Slices

| Slice | Repo | Depends on | Content | Risk |
|---|---|---|---|---|
| CL1 | CLI | nothing | 4.2 CL1 bullets (`mask()` and `tokenize`), T-C1 to T-C4, T-C8 to T-C10 | R2 |
| E1 | engine | #589 merged (`target_identity` on main, with the 4.1 calling convention pinned) | 4.1, 7.1a migration, T-E1 to T-E11, changelog, docs line; full suite | R2 |
| CL2 | CLI | the engine release with E1, and the repin | 4.2 CL2 bullets, T-C5 to T-C7, T-C11, CLI changelog line | R1 |

If #589 has not merged when E1 starts, E1 waits; it does not add its own identity function.

## 11. Open questions (owner)

- **OQ-1.** May two tables ever write into one destination on purpose (append, or a union file)?
  Working answer: no, refuse; a union belongs in a table, not in the writer.
- **OQ-2.** Two codes stay: `config/target_shared_destination` (the declarations name one destination)
  and `layout.output_path_collision` (two outputs meet on disk). Working answer: keep both; they
  point the user at different fixes.
- **OQ-3 (r2).** Seven engine test helpers and `scripts/gen_proof_manifest.py` give every table
  the placeholder target `/dev/null` (7.1a). Is a shared placeholder a supported engine-API idiom?
  Working answer: no exemption; migrate the callers to one placeholder per table.
- **OQ-4 (r2).** After the repin, `decoy.mask()` raises `ConfigValidationError` instead of
  `LayoutError` for two equal declared targets. Acceptable? Working answer: yes, pre-GA, with a
  CLI changelog line; both carry a stable code.
- **OQ-5 (r2).** Must `validate preflight` report the same code as `validate` and `run`, or only
  the same failure? Working answer: only `validate` and `run` must match in this row; a `code` on
  preflight's schema failures goes to row 24zf's one `--json` error shape.

## 12. Recurring-defect walk (`/home/cam/dev-rules/catalogs/recurring-defects.md`)

| # | Class | Here |
|---|---|---|
| 1 | Anchored validation | N/A: no regex is added. |
| 2 | Strict wire and stored types | N/A: no persisted or wire model is added; the targets keep their models. |
| 3 | No exception context | the E1 problem is built by `problem_details` and raised by `ValidationError.from_exception_data` outside any `except`; CL1 raises `OUTPUT_PATH_COLLISION.error` outside any `except`. T-E8 and T-C1 assert `__cause__` and `__context__` are `None` on the refusal. |
| 4 | Versioned read models | N/A: nothing persisted is read. |
| 5 | Normalized guard scanners | N/A: no sentry is added. The 7.1a scan is a one-off builder check, not a guard. |
| 6 | No reaching into private modules | CL1 imports `resolved_output_collisions`, `LayoutError` and `OUTPUT_PATH_COLLISION` from public `decoy.cli.io`, never `_placement` or `_layout_errors`. |
| 7 | No hidden CI failures | N/A: no CI change. |
| 8 | One input, one trust class per entry point | the config's target paths are one input with one rule per layer: engine identity on the declaration, CLI identity on the placed path; `mask()`, `tokenize`, `run`, `validate` and `ci check` all take the same CLI rule. |
| 9 | Mutations on the final head | every M-* in section 7 reruns on the final head of each slice. |
| 10 | Allowlisted helpers are still checked | N/A: no allowlist entry. |
| 11 | No raised caps | `config/_pipeline.py` grows by about 25 lines (406 now) and stays under 600; no cap, ratchet or allowlist is raised. |

Case and Unicode variants of one file name are the CLI's `_destination_key`, reused. Windows
paths are compared by `normpath` text in the engine, which folds `\` to `/` only on Windows; no
new OS branch.

## 13. V2-LOG

- **Other copies of "same destination" (r2).** `_subset_stage_constraints` keeps its own
  `normpath` file identity and quotes `src.path` in its message (`_pipeline.py:394-405`), a
  value-bearing message that predates this plan; #589's `_allocate_targets` compares `path in
  seen`. Later: route the subset rule through `target_identity` and drop the quote; let the
  starter builder rely on E1.
- **`normpath` collapses `..` as text (r2).** The engine may refuse `a/link/../x.csv` against
  `a/x.csv` although a symlinked `link` names another place (the CLI avoids this,
  `_placement.py:235-238`). A false refusal, not data loss; note it in #589's definition.

## 14. Pre-mortem

- E1 rejects a shipped example or fixture that reuses a target path. Known hits are the 7.1a
  helpers, migrated in E1; the YAML and JSON fixtures of both repos have no duplicate (Dennis r1
  scan). The full engine suite runs for E1.
- CL2's deferral hides another layout fault that used to come first. Check: T-C5 plus the
  existing AT-4 and AT-16 cells.
- A new target type (SFTP) is added without an identity. `target_identity` raises on an unknown
  type, so validation fails loudly until it is added.

## 15. Stop lines for builders

- Do not add a second identity function, a second collision loop or a second reason code.
- Do not quote a path, bucket, key or object in any message.
- Do not change exit codes or `--json` shapes.
- E1 does not start before #589 merges.
- CL1 checks placed paths, never declared text; do not widen `names_a_file_inside`.
- CL2 skips the early layout refusal only for `config/target_shared_destination`.

## 16. Verification status

- Probe results in 1.2: real runs on the Mac mini (CLI `65b710c` with engine 0.24.0; engine
  `187a14e6`).
- Code facts in 1.1 and 4.2: read at the bases, not run. The tokenize gap and the `../x.csv`
  hole in CL1 come from Dennis r1's code reading, not from a probe.
- `target_identity` is defined in #589's plan amendment (`ed9e65c9`); its code is not on that
  branch yet.
