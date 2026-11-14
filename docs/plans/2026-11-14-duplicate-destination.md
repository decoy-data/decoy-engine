Status: plan

# DUP-DEST: refuse two tables that write to one destination

Rules consulted: `/home/cam/dev-rules/README.md`, `00-universal.md`, `risk-and-exceptions.md`,
`development-loop.md`, `bugfix.md`, `architecture.md`, `cross-cutting-concerns.md`,
`reuse-first.md`, `exploration.md`, `scope-discipline.md`, `code-review.md`,
`workspace-and-vcs.md`, `api-and-compatibility.md`, `config-secrets-and-supply-chain.md`,
`security.md`, `testing.md`, `verification.md`, `documentation.md`,
`catalogs/recurring-defects.md`; engine `CLAUDE.md`, `CODEMAP.md`,
`docs/compatibility-contract.md`; CLI `CODEMAP.md`, `docs/ROADMAP.md`.

Revision 3: Dennis round 1 (GO-WITH-FIXES, 2 V1, 5 DESIGN, 4 V2-LOG) and round 2 (GO-WITH-FIXES,
0 V1, 4 DESIGN, 6 V2-LOG) remediated; changes are marked "(r2)" or "(r3)".

Revision 4: Codex plan-gate remediation. The engine identity is conservative around
symlink-sensitive parent segments and S3-compatible storage namespaces, only targets for declared
tables take part, final-head tests prove the CLI checks precede source reads, test placement follows
both CODEMAPs, and CL2 owns the engine repin so no intermediate CLI head has mismatched error order.

Bases (2026-11-14): engine `origin/main` `187a14e6`, CLI `origin/main` `65b710c` (pins
`decoy-engine==0.24.0`). Related work in review: engine PR #589 (SCAN-MULTI S3-engine.2, branch
`feat/scan-multi-s3e2`), which adds `config.target_identity(target)` in `config/_targets.py`
as the one definition of "same destination". Orchestrator ruling (2026-11-14, T0888): #589 merges
with its current public `target_identity` unchanged (its S3 identity already includes
`endpoint_url`). E1, after #589 merges, adjusts that identity into the private conservative
primitive of 4.1, adds the public `duplicate_target_groups`, and moves #589's starter allocator
onto it, so the allocator and `PipelineConfig` do not keep two `seen` loops. This plan adds no
second definition.

Owner decisions used: the V1 bar (2026-11-02: a product-function break, data loss or corruption,
or real values or secrets shown to a non-admin block V1); "names may show in messages; data values
never" (2026-11-06); row 24b QA-GATE (2026-11-08: "`decoy validate` refuses what `run` would
refuse ... fail at the gate with exit 1, the config-error code").

Risk: R2 (a config refusal widens on every caller, and the CLI's Python API gains a refusal before
its first write). Out of scope: two outputs that collide only after a run starts (a file another
process creates mid-run), quarantine paths on the engine side (the sink's
`committed_table_path` check and the CLI collision rule already cover them), the parked platform's
own writers, storage aliases that cannot be decided from a target declaration alone (for example,
two spellings of one S3 endpoint URL), and SFTP targets
(no `SFTPTarget` exists).

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

1. A pipeline config in which two or more declared tables have targets in one group from
   `duplicate_target_groups` is refused by `PipelineConfig` validation. Product entry points that
   validate through `parse_pipeline_config` or `PipelineConfig.model_validate` do so before any
   source read or output write. Targets whose keys do not name a declared table do not take part
   because the current writers skip them. The code is `target_shared_destination` (namespace
   `config`; the string tests and `--json` see has no prefix, r3); each table in the clash gets one
   problem located at the
   field that names the destination (`targets.<table>.path`, `.key` or `.object`, the locations
   the CLI already prints), in config order (r2). The text is the registry's fixed summary. No
   path, endpoint URL, credential reference, bucket, key, object or unknown-type literal appears
   in any message, location or log line.
2. `decoy.mask()` and `decoy tokenize` (both routes) refuse two outputs that the route can publish
   and that resolve to one file
   on disk (symlinked folder, case-only difference on a folding volume, hard link, relative
   against absolute spelling, a relative path that leaves the base folder, a target against an
   enabled quarantine path, and for tokenize a target against `--vault`) with the CLI's existing
   `layout.output_path_collision`, before any declared source file or database relation is read
   and before any output is written. (`mask()` spools an in-memory `data=` frame to a private temp
   input first, `api.py:245-255`; that is the existing source adapter, not a published output.)
   They use the layout identity `decoy run` and `decoy validate` use: an existing file's inode
   is its identity, so two hard-linked names are one destination, and every file target takes
   part, including one no table writes. A refusal there loses no data (ruling C, T0895);
   hard-link-aware layout identity is a V2-LOG item.
3. For a config that is otherwise schema-valid, `decoy validate` and `decoy run` report the same
   first collision code: the engine code for declarations with one conservative identity, the
   layout code for outputs that meet only on disk. Exit 1 in both. Existing ordering for a config
   with another schema fault is unchanged and is not widened into a claim of universal first-code
   parity.
4. A config whose effective targets are all distinct behaves exactly as today: same validation
   result, same output bytes. In particular, validation does not newly refuse two file paths whose
   `..` segments can traverse different symlink targets, two S3-compatible bindings with different
   endpoint declarations, or duplicate unused target entries.

## 3. Established solutions

- dbt refuses at compile time two models that resolve to one relation identifier
  (`database.schema.alias`) and names both nodes, rather than letting the second build replace
  the first. The rule here is the same shape: compare a canonical identity of each declared
  output, refuse a shared one, name the declarers.
- GNU Make warns "overriding recipe for target" when two rules write one target; we refuse instead
  of warning, because the second write destroys data.
- The CLI already holds the filesystem half (`_destination_key`, plan 3.6.1 B of
  `plan/project-layout`); this plan reuses it rather than writing a second one.
- A declaration-only identity must be conservative. POSIX and Windows resolve a `..` after a
  symlink from the symlink target, not from the lexical path, and an S3-compatible endpoint can
  give the same bucket and key text a different storage namespace. The engine therefore refuses
  only identities the declaration proves equal and leaves physical aliasing to the writer check.

## 4. Design

### 4.1 Engine: one validator on `PipelineConfig`

- `PipelineConfig._targets_distinct`, a `model_validator(mode="after")` in `config/_pipeline.py`.
  It first takes the names in `self.tables`, then passes those names and `self.targets` to
  `duplicate_target_groups`. The filter matches `write_targets`, which skips a
  target whose key has no output (`cli/io/_targets.py:479-489`); refusing unused entries would
  reject a config that the current product accepts and never writes.
- `config/_targets.py` owns both levels of the rule. Its private identity primitive computes the
  conservative tuple, and public `duplicate_target_groups(targets, active_names)` is the only
  grouping loop. It returns duplicate table-name groups in mapping order and renders no error.
  #589's starter allocator (moved onto it in E1) and E1's model validator call that function, then render their own
  established exception shapes. Export it from `decoy_engine.config` so the starter code does not
  import another package's private module. A sentry in `tests/sentry/defects/` reuses
  `_defect_scan.ModuleIndex` for normalized imports and ASTs, asserts both `_pipeline.py` and
  `profiling/_starter_config.py` call the public grouping function, and fails on any import or
  call of the private identity primitive outside `_targets.py`. Its realistic seeded mutation replaces the
  `_pipeline.py` grouping call with a direct private-identity call.
- The private conservative identity uses file paths with no `..` component through
  `os.path.normpath`, so repeated separators and `.` compare equal. If the platform path parser
  finds a `..` component, the identity keeps the path text unchanged, so it never erases a
  symlink-sensitive traversal. S3 uses `("s3", endpoint_url, bucket, key)`: an endpoint selects
  the S3-compatible storage namespace, while region and credentials only route or authorize access
  to that namespace and cannot make two writes to one endpoint, bucket and key safe.
  GCS remains `("gcs", bucket, object)` because GCS bucket names identify one global namespace.
  For each identity held by two or more tables it adds one
  `(("targets", table, field), code)` problem per table, `field` being `path`, `key` or `object`, then raises through `problem_details` and `ValidationError.from_exception_data`, the
  pattern `_unique_domains_valid` already uses (`_pipeline.py:340`). `validation_problems` turns a
  registered code into its fixed summary, so the message carries no input.
- Reason code `target_shared_destination` in the `config` domain, declared in
  `reasons/config/_part2.py` under `_catalog.config("PipelineValidationError")`
  (`_part2.py:50`), the owner of every code `PipelineConfig` raises through `problem_details`
  (r2; the `target_file.*` codes in `_part1.py` belong to the legacy `validation_result` owner).
  `since=UNRELEASED`, summary "Two or more targets write to one destination. Give each table its
  own target." It joins the unreleased set that release prep stamps, and gets its own registry test
  (T-E11), not a row in an existing pinned table.
- Calling convention (r2). `self.targets` holds pydantic models; #589's starter builder holds
  dicts. `duplicate_target_groups` accepts either and normalizes a model with `model_dump()` in
  its one identity primitive. The `type` field is a discriminated union, so an unknown type never
  reaches the validator. The private identity primitive's unknown-type error (#589) must be a fixed, value-free
  `ValueError` that does not echo the submitted type literal. A later typed config caller sees a
  `ValidationError`, never a bare exception through `parse_pipeline_config`
  (`config/_parse.py:24-29`). E1 pins the identity, the fixed error and their tests; #589 merges
  unchanged (T0888).
- Identity is declaration-only. Symlinks, hard links, case folding, `..` aliases and relative
  against absolute are the writer's concern at run time, and the CLI's writer check covers them
  (4.2).
- Table kind does not enter: mask, generate and mixed tables are all keys of `targets`.
- One choke point. `compile_plan` and `run_config_only_checks` do not repeat the check:
  `run_pipeline` documents that its config is the validated dump, and the engine writes no
  target path itself (1.1). The starter builder and `PipelineConfig` share the one grouping
  function; the AST sentry makes the realistic direct-identity bypass fail.

### 4.2 CLI

- **CL1, `decoy.mask()` (r2: placed paths).** After `parse_pipeline_config` and the `out=` merge,
  before `_load_sources_from_config` (`api.py:506`), check the paths the writer will use, not the
  declared text. Build a fresh check input, never a shallow copy (r3): a new dict
  `{"targets": {t: {"type": "file", "path": str(layout.place_target(raw))}, ...}}` for each local
  file target whose key names a table in `config_dict["tables"]`, plus
  `{"quarantine": {"enabled": True, "output_path": str(q)}}` only when
  `q = layout.place_quarantine(config_dict)` is not `None` (`_layout.py:597-602` returns `None`
  defensively when no string path is present; `PipelineConfig` already refuses that shape when
  quarantine is enabled), on the `RunLayout.fixed(base_dir)` the call builds. This matches
  `write_targets`, which skips target keys absent from the result
  (`io/_targets.py:479-489`). Then call `resolved_output_collisions(placed, None)`. `config_dict`
  itself is never
  edited: the plan hash covers `quarantine` (`plan/_compile.py:622`), so a placed absolute path
  there would change `mask()`'s hash against `decoy run` for the same config.
  Every path is now absolute, so `names_a_file_inside` no longer drops `../x.csv`. On a clash
  raise `OUTPUT_PATH_COLLISION.error(first=..., second=...)` with the original config locations,
  the same `LayoutError` `decoy run` raises, documented under the API's `Raises:`. Import
  `LayoutError` and `resolved_output_collisions` from the public `decoy.cli.io`
  (`io/__init__.py:69`, `:98`), not `_placement`; `OUTPUT_PATH_COLLISION` is not exported there
  yet, so CL1 adds it to `io/__init__.py` and its `__all__` (r3). There is no second collision
  algorithm and no new reason code. This lands on the current engine pin and closes the `mask()`
  data loss by itself.
- **CL1, `decoy tokenize` (r2).** Move the layout check out of the `if out_dir is not None` guard
  (`tokenize.py:310`): before any folder or source, call `layout_findings(config_path, raw,
  placement)` with `OutputPlacement.fixed(out_dir, (("--vault", vault),))` under `--out-dir` (as
  today) and `OutputPlacement(typed=(("--vault", vault),))` on the project route (the shape
  `run` uses, `run/_prepare.py:257`), and render the refusal the way the `--out-dir` branch does
  (`tokenize.py:315-321`). This brings the whole layout gate `run` already applies to the project
  route, not only the collision rule (r3): `layout_issues` (`_placement.py:261-357`) also refuses
  an escaping target, a path over the Windows length budget, mixed relative and absolute targets
  (delivery root split), `--vault` under the project's `out/` (`layout.side_file_in_out`) and the
  cloud root checks. Each is a refusal `decoy run` gives today for the same config; exit 1.
- **CL2, run and validate parity (after the repin to the engine release that carries E1).**
  `decoy run` checks layout before the gate (`run/_prepare.py:260` `_refuse_layout_faults`,
  called at `:319`), while `decoy validate` runs the schema first and stops there
  (`gate/_layers.py:117`). With E1 in, the same config would give `layout.output_path_collision`
  from run and `target_shared_destination` from validate. `_refuse_layout_faults` skips the
  early refusal only when `parse_pipeline_config(ctx.raw)` refuses with a problem whose code is
  `target_shared_destination` (r2); the gate then reports it in both commands. Any other
  schema refusal keeps today's order, so a source-less YAML that relies on `--duckdb-source`
  (refused by the schema at `_pipeline.py:216` before staging) still gets its layout fault
  before `acquire_relation` reads a source, the invariant at `_prepare.py:316-319` that
  `tests/e2e/test_vault_commit_order.py` pins. After-validators stop at the first raise, so that
  YAML never reaches E1. On `target_shared_destination` the early check raises the schema refusal
  itself instead of returning (r3), so a YAML that declares `sources:`, runs with
  `--duckdb-source` and has equal targets is refused before `acquire_relation`
  (`_prepare.py:365-366`) reads a source. The refusal is built by the gate's own
  `PipelineConfigError` to `GateFinding` mapping (`gate/_layers.py:136-141`), moved into one
  helper both call, so no second construction appears. Export the helper from `decoy.cli.gate`;
  `run/_prepare.py` imports that public facade and never reaches into `gate._layers`.
- **CL2, test expectations.** The AT-31 cells in `tests/e2e/project_layout/test_layout_gate.py`
  whose outputs are provably the same from their declarations (two equal relative paths, equal
  absolute paths, and `.` or repeated-separator spellings with no `..`) now expect
  `target_shared_destination` at `targets.a.path` and `targets.b.path`, which
  `_assert_collision` (`test_layout_gate.py:513-517`) already checks. The parent-segment cell at
  `test_layout_gate.py:585-593`, plus the symlink, hard-link, case-folding and
  target-against-quarantine cells, keeps
  `layout.output_path_collision`. The `validate preflight` cells (`test_layout_gate.py:525`,
  `:554`, `:585`) report a schema failure as `schema.field` with no code
  (`preflight.py:695-700`); they change to expect `schema.field` at those locations. A `code` on
  preflight schema failures is a `--json` change and belongs to row 24zf's one error shape, not
  here (OQ-5).
- **CL2, CL1 cells that flip (r3).** CL1's equal-text cells (one per entry point: T-C1 for
  `mask()`, T-C8 (a) for tokenize) start failing at the repin, because the engine refuses first.
  CL2 changes them to expect the engine refusal: `ConfigValidationError` with
  `target_shared_destination` from `mask()`, and tokenize's schema-error exit
  (`tokenize.py:238-242`) with that code. Every other CL1 cell uses a clash the engine cannot
  see and keeps `layout.output_path_collision`. Cloud
  cells with two equal keys expect the engine code; the CLI's "shares its file name" branch in
  `_key_issues` stays as a defense.

## 5. Behaviour

| Input | Before | After |
|---|---|---|
| engine `PipelineConfig.model_validate` with two declared tables on one conservative identity (any type) | accepted | `ValidationError`, one `target_shared_destination` per table |
| engine config with symlink-sensitive `..` paths, distinct S3-compatible bindings, or duplicate unused targets | accepted | accepted unchanged; the writer layer decides physical aliases |
| CLI `validate`, two equal targets | exit 1 layout or cloud code | exit 1 `target_shared_destination` |
| CLI `run`, two equal targets | exit 1 layout or cloud code | exit 1 `target_shared_destination` |
| CLI `run` or `validate`, outputs equal only on disk | exit 1 `layout.output_path_collision` | unchanged |
| `decoy.mask()`, two equal targets or `out=` paths | silent overwrite | CL1: `LayoutError` `layout.output_path_collision`; after the repin `ConfigValidationError` (`api.py:458-466`) with the engine code fires first (OQ-4; CLI changelog line) |
| `decoy.mask()`, outputs equal only on disk, or `../x.csv` twice | silent overwrite | `LayoutError` `layout.output_path_collision` |
| `decoy tokenize` (project route), two equal targets, or a target on `--vault` | silent overwrite | exit 1 `layout.output_path_collision`; after the repin, equal targets give the engine code first |
| `decoy tokenize` (project route), an escaping target, mixed relative and absolute targets, `--vault` under `out/`, a path over the Windows budget, a cloud root fault | runs | exit 1 with the code `decoy run` gives for the same config (`layout.output_path_escapes`, `layout.side_file_in_out` and the other `layout_issues` codes) (r3) |
| any config with distinct effective targets | runs | runs, same bytes |

## 6. Failure modes

### 6.1 Class table

| # | Class | Structure that closes it | Proof | Mutation that turns it red |
|---|---|---|---|---|
| 1 | Value-bearing output | the engine problem text is the registry summary; the location is `targets.<table>.path`, `.key` or `.object`; no path, bucket, key or object reaches a message, `str(exc)`, a log line or `--json`. CL1 reuses `OUTPUT_PATH_COLLISION`, which names config locations only | T-E8, T-C1 | interpolate the path into a custom message |
| 2 | Cleanup missing on an exit path | N/A with a reason: both refusals fire before any output is opened, so nothing is left behind | T-C1 (no file under the folder) | move the CL1 check after `_write_mask_outputs` |
| 3 | State and concurrency | N/A: the validator and the CL1 check are pure functions of the config and the folder; no shared or module state is added | T-E6 (stable order) | collect problems in a module-level set |
| 4 | Route parity and silent fallback | one engine choke point (`PipelineConfig`) covers every engine caller; CL1 brings `decoy.mask()` and `decoy tokenize` (both routes) to the rule `run`, `validate` and `ci check` already use, on the placed paths; CL2 makes `validate` and `run` report the same first code and keeps every other ordering | T-C1, T-C2, T-C5, T-C8, T-C9, T-C10, T-C11 | skip the CL1 check when `out=` is given; keep the tokenize `out_dir` guard; skip the early refusal on any schema failure |
| 5 | Referential integrity | no key or FK path changes; the tokenize vault is protected by entering the collision rule as a typed side file, so no target can replace it | T-C8 (target on `--vault`) | drop `--vault` from the tokenize placement |
| 6 | Untrusted producer | the config is user input; the discriminated `type` refuses an unknown type before the validator, and the private identity primitive raises a fixed `ValueError` without the submitted type literal, so a type added later without an identity fails instead of being skipped | T-E10, #589's identity value-canary test | return `None` for an unknown type and skip it; echo the type in the error |
| 7 | Check then use (TOCTOU) | the engine check is on conservative declarations, so it has no filesystem window and does not collapse a symlink-sensitive `..`. CL1 checks the paths `place_target` returns, the ones the writer then uses; a file or link created by another process between the check and the write is out of scope (header), same as today's `run` | T-E12, T-C3, T-C9 | normalize a file identity containing `..`; check the declared text instead of the placed path |
| 8 | Weak tests and overclaimed evidence | every refusal test names the code and locations; the persistent disk-only cells spy the source reader and engine and assert no output or vault change; each core failure has a named mutation in section 7; mutations rerun on the final head | gate reviewers rerun them | relax T-E1 to "raises `ValidationError`"; move a CL1 check below the source loader |
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
| cloud delivery (CLI-CLOUD, row 64) | yes, `("s3", endpoint_url, bucket, key)` / `("gcs", bucket, object)` | `_cloud.py:_key_issues` (`io/_cloud.py:111`) stays as a defense |

#### FK shapes

N/A: no key, FK or relationship code path changes. Two tables in a parent and child pair that
share a destination are refused like any other pair.

#### Fields

| Field | Part of the identity |
|---|---|
| `targets.<t>.type` | yes, first element |
| file `path` | yes; `normpath` only when it has no `..` component, otherwise text unchanged |
| file `format`, `layout` | no: two formats in one file still destroy one table |
| S3 `endpoint_url`, `bucket`, `key` | yes, as the storage address; none is ever rendered in the refusal |
| S3 `region`, `credentials_ref` | no: routing and authorization do not make one storage address distinct |
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
| T-E1 | two file targets, same path: refused, problems at `targets.a.path` and `targets.b.path`, code `target_shared_destination` | M-E1: remove the validator |
| T-E2 | `out/a.csv` against `out/./a.csv` and `out//a.csv`: refused | M-E2: compare raw `path` instead of the shared grouping function |
| T-E3 | S3 same endpoint, bucket and key refused even with different region or credential references; another bucket or key accepted | M-E3: drop the bucket from the comparison; include region or credential reference in the identity |
| T-E4 | GCS same bucket and object refused; another bucket or object accepted | M-E4: drop the bucket from the GCS comparison |
| T-E5 | file `a.csv` against S3 key `a.csv`: accepted | M-E5: compare without the type element |
| T-E6 | three tables on one destination give three problems in config order; two separate pairs give four | M-E6: report only the second table of a group |
| T-E7 | a mask table and a generate table on one path: refused | M-E7: group only tables with `columns` |
| T-E8 | on the raw `PipelineConfig.model_validate` error (r2): no path, endpoint URL (including URL credentials), credential reference, bucket, key or object canary in `str(exc)` or any `errors()` `msg`, `input` or `ctx`; the same on `PipelineConfigError` problems and #589's starter-builder duplicate exception; `__cause__` and `__context__` are `None`; the code is registered | M-E8: interpolate the path into a custom message or the starter exception |
| T-E9 | distinct targets: the existing config fixtures still validate; the E1 full suite is green after the 7.1a migration | none |
| T-E10 | an unknown target `type` is refused as today (discriminator), not by a bare exception from the validator; the #589 direct-helper value-canary test proves the fixed fallback does not echo the type | M-E10: make the validator accept a raw dict and call the grouping function before the union check; echo the type in the fallback error |
| T-E11 | a standalone registry test (r3): `target_shared_destination` has owner `PipelineValidationError`, `since == UNRELEASED`, kind FAILURE, retry CONFIGURATION_REPAIR. It is not added to the `GEN_STRICT` table at `test_reason_registry.py:357`, whose tests pin `since == "1.13.0"` and the 1.13 manifest (`:379-400`) | M-E11: declare it under the `decoy_engine.validation_result` owner |
| T-E12 | two paths with distinct text and a `..` component are accepted by the engine even when `normpath` would merge them; a real symlink fixture proves the two spellings land at different files | M-E12: call `normpath` unconditionally |
| T-E13 | two equal target entries whose keys name no declared table are accepted; when one key names a declared table and the other does not, only the declared output takes part | M-E13: group every entry in `self.targets` |
| T-E14 | S3 same bucket and key with a different endpoint is accepted; the same endpoint, bucket and key is refused | M-E14: omit endpoint from the identity |
| T-E15 | the AST sentry proves `_pipeline.py` and `profiling/_starter_config.py` call public `duplicate_target_groups` and no module outside `_targets.py` imports or calls the private identity primitive. Add the sentry path to `test_sentry_manifest.py:SENTRIES`; its existing collection tests prove the local gate runs it | M-E15: replace `_pipeline.py`'s group call with a direct import and call of the private identity; remove its `SENTRIES` entry |

### 7.1a Engine callers E1 migrates (r2)

Each gives every table one target path today; E1 gives each table its own placeholder (for
`/dev/null` users, a per-table name under the test's `tmp_path`, or a path the test never writes).
This list is from an AST scan at `187a14e6`; the builder reruns the scan on the E1 base and stops
if a production caller appears.

| File | Line |
|---|---|
| `scripts/gen_proof_manifest.py` (release prep; `tests/sentry/test_proof_manifest.py`) | 148-152 |
| `tests/native/_chunked_entry_support.py` (about 74 test files use it) | 59-61 |
| `tests/unit/execution/run_stream/_support.py` | 143-145 |
| `tests/unit/generation/kinds/_support.py` | 35 |
| `tests/unit/generation/unique/_gu_corpus.py` | 28 |
| `tests/unit/generation/unique/_gu_e2_support.py` | 24 |
| `tests/unit/test_v2_generation.py` | 1053-1055 |

`scripts/gen_proof_manifest.py` has an exact size pin of 1230 lines
(`tests/sentry/test_module_size.py:154`, `tests/sentry/baselines/module-size.json:23`): its edit is
line-count neutral (four lines for four lines) with no census change (r3).

Shared test helpers are a `testing.md` escalation trigger: E1 runs the full engine suite against
the stored main baseline.

### 7.2 CLI CL1 (current pin)

Tests live in `tests/unit/test_api.py` and
`tests/e2e/project_layout/test_tokenize_out_dir.py`.

| Id | Test | Mutation |
|---|---|---|
| T-C1 | `decoy.mask(config=...)` with two equal absolute targets (the one equal-text `mask()` cell; flips in CL2) raises `LayoutError` `layout.output_path_collision`; no source read (patch `decoy.api._load_sources_from_config`, bound at import, `api.py:40`); `run_pipeline` never called (spy; quarantine is written inside it); no file under the folder | M-C1: skip the check |
| T-C2 | `out={"a": p, "b": q}` where `q` is `p` through a symlinked folder, on distinct declared targets: refused. This disk-only cell remains a CL1 refusal after CL2 and asserts `_load_sources_from_config` and `run_pipeline` were not called and neither destination exists | M-C2: check before the `out=` merge; move the check below `_load_sources_from_config` |
| T-C3 | case-only and NFC/NFD names with `_placement._folds_case` monkeypatched true (as `test_layout_gate.py:609` does, so Linux CI runs them), a symlinked folder, and two existing hard links | M-C3: compare `normpath` text instead of `resolved_output_collisions` |
| T-C4 | distinct targets: both files written with their own rows; `config_dict` (targets and quarantine) is equal before and after the check (r3). Equal unused target entries remain accepted and unwritten | M-C4: build the check input with a shallow copy and edit it in place; include target keys that name no declared table |
| T-C9 | `../shared.csv` against its absolute spelling; `sub/../a.csv` through a symlinked `sub` against the real path: all refused, nothing written outside the base | M-C9: pass the declared `config_dict` with `base_dir` instead of the placed paths |
| T-C10 | a target equal to a valid enabled `quarantine.output_path`: refused, `_load_sources_from_config` and `run_pipeline` never called, neither file written | M-C10: leave quarantine out of the placed copy |
| T-C8 | in `tests/e2e/project_layout/test_tokenize_out_dir.py`, `decoy tokenize` on the project route: (a) two equal targets (the one equal-text tokenize cell; flips in CL2), (b) a symlinked spelling of one target, (c) a target equal to `--vault`: exit 1 `layout.output_path_collision`, no output written, the vault file absent or byte-identical; (d) (b) and (c) under `--out-dir` stay refused; (e) distinct absolute targets with a vault outside `out/` still succeed. The disk-only (b) and (c) cells reuse that file's `_no_source_read`, spy `run_pipeline`, and prove neither is called | M-C8: keep the `out_dir is not None` guard; move `layout_findings` below `_load_sources_from_config` |

### 7.3 CLI CL2 (after the repin)

| Id | Test | Mutation |
|---|---|---|
| T-C5 | the same config through `validate` and `run`: same first code, exit 1, for (a) two equal relative paths: `target_shared_destination`; (b) a symlinked folder: `layout.output_path_collision` | M-C5: keep the early layout refusal |
| T-C6 | two S3 targets with one key: `target_shared_destination` from both commands | M-C6: as M-C5 |
| T-C7 | updated AT-31 cells per 4.2, with the `..` parent-segment cell kept on the layout code; T-C1 and T-C8 (a) flipped to the engine refusal, including only the `validate preflight` cells whose declarations have the engine identity expecting `schema.field` at `targets.a.path` and `targets.b.path` | none |
| T-C11 | a source-less YAML that relies on `--duckdb-source`, plus a symlink collision: `run` exits 1 `layout.output_path_collision` and `acquire_relation` is never called | M-C11: skip the early refusal on any schema failure |
| T-C11b | a YAML with `sources:`, run with `--duckdb-source`, and two equal targets: exit 1 `target_shared_destination`, `acquire_relation` never called (r3) | M-C11b: return instead of raising on that code |

## 7a. Reuse inventory

| Need | Reused | Not reused, why |
|---|---|---|
| same destination as declared | private identity plus public `config.duplicate_target_groups` (added in E1 from #589's `target_identity`, shared by its starter and E1) | none |
| coded value-free config problem | `_generate_options.problem_details`, `validation_problems` | none |
| same file on disk | CLI `resolved_output_collisions`, `OUTPUT_PATH_COLLISION` (from public `decoy.cli.io`) | none |
| placed path the writer uses | `RunLayout.place_target`, `RunLayout.place_quarantine` | none |
| tokenize layout check | `layout_findings`, `OutputPlacement`, the `--out-dir` branch's renderer | none |
| choke-point AST index | `tests/sentry/defects/_defect_scan.py::ModuleIndex` | none |

## 8. Placement

| Change | File | CODEMAP row |
|---|---|---|
| declaration identity and duplicate grouping | E1 updates `src/decoy_engine/config/_targets.py` (from #589's `target_identity`) and exports `duplicate_target_groups` from `config/__init__.py` | engine CODEMAP line 243: config models and their rules live in `src/decoy_engine/config/` |
| validator | `src/decoy_engine/config/_pipeline.py` (406 lines, about +25) | `config/_pipeline.py` |
| reason code | `src/decoy_engine/reasons/config/_part2.py`, owner table in `tests/unit/test_reason_registry.py` | reasons |
| engine tests | `tests/unit/config/test_target_destinations.py` (new, beside the other config model tests) | engine CODEMAP "Where things go" lines 240-244 and 275: config model tests mirror into `tests/unit/config/` |
| engine choke-point sentry | `tests/sentry/defects/test_target_destination_choke_point.py` (new), registered in `tests/sentry/test_sentry_manifest.py:SENTRIES` | engine CODEMAP line 265: recurring-defect sentries go in `tests/sentry/defects/`; the manifest is the existing gate registry |
| E1 caller migration | the seven files in 7.1a | |
| changelog | engine `changelog.d/dup-dest-e1.md`; CLI `CHANGELOG.md` Unreleased entry for `mask()`'s exception at the repin | engine CODEMAP lines 268-271; CLI edits its existing changelog file, so CL2 adds no unmapped file |
| docs | engine `docs/config-reference.md` targets section, or the existing target-reference file found on the E1 base: one line, "each table needs its own destination" | engine CODEMAP lines 268-269, feature and contract docs in `docs/` |
| CLI API check | `src/decoy/api.py` (CL1) | CLI `api.py` |
| CLI tokenize check | `src/decoy/cli/tokenize.py` (CL1) | CLI `tokenize.py` |
| CLI export | `src/decoy/cli/io/__init__.py`: `OUTPUT_PATH_COLLISION` and its `__all__` entry (CL1) | CLI `io/` |
| CLI schema-refusal helper | the `PipelineConfigError` to `GateFinding` mapping becomes one helper in `gate/_layers.py`, exported by `gate/__init__.py`; `run/_prepare.py` and `_layers.py` call it through the owning package (CL2) | CLI CODEMAP lines 50-52: shared pre-run gate in `cli/gate/`, run phases in `cli/run/` |
| CLI run parity | `src/decoy/cli/run/_prepare.py` (CL2) | CLI `run/` |
| CLI tests | `tests/unit/test_api.py` (CL1, T-C1 to T-C4 and T-C9 to T-C10); `tests/e2e/project_layout/test_tokenize_out_dir.py` (CL1, T-C8); `tests/e2e/project_layout/test_layout_gate.py` (CL2) | CLI CODEMAP lines 54 and 58: Python API tests in `tests/unit/test_api.py`, layout tests in `tests/e2e/project_layout/` |

No new source module; `config/` and top-level source-module counts are unchanged. The two new
engine test modules are in the CODEMAP's existing `tests/unit/config/` and
`tests/sentry/defects/` packages.

## 9. Frozen contracts touched

- **Reason registry.** One code added, `since=UNRELEASED`; release prep stamps it.
- **Exit codes.** None move (1 before, 1 after).
- **`--json` shapes.** Unchanged; some configs report a different code before REL-GATE (row 93)
  freezes codes. Preflight gains no `code` field here (OQ-5).
- **`decoy tokenize`.** The project route gains the `layout_issues` refusals `decoy run` gives for
  the same config (5); exit 1, existing codes (r3).
- **Python API.** `decoy.mask()` raises `LayoutError` for a destination clash after CL1; after the
  repin, equal declarations raise `ConfigValidationError` instead (OQ-4).
- **Engine pin.** CL2 updates the engine pin and its certified lock evidence on the same head as
  the error-order fix; the version-pin full-suite trigger applies.
- **Determinism and output bytes.** Unchanged for every config that still validates.

## 10. Slices

| Slice | Repo | Depends on | Content | Risk |
|---|---|---|---|---|
| CL1 | CLI | nothing | 4.2 CL1 bullets (`mask()`, `tokenize`, the `OUTPUT_PATH_COLLISION` export), T-C1 to T-C4, T-C8 to T-C10 | R2 |
| E1 | engine | #589 merged with its current `target_identity` | adjust the identity into the private conservative primitive (4.1), add public `duplicate_target_groups` with the fixed unknown-type error and calling convention, move #589's starter allocator onto it; 4.1, 7.1a migration, T-E1 to T-E15, changelog, docs line; full suite | R2 |
| CL2 | CLI | the engine release with E1 | atomically repin the engine and apply the 4.2 CL2 bullets (parity, the public shared schema-refusal helper, the flipped CL1 cells), T-C5 to T-C7, T-C11, T-C11b, CLI changelog line; full CLI suite because a version pin and compatibility/error contract change | R2 |

If #589 has not merged when E1 starts, E1 waits; it builds on #589's `target_identity` and does not add a second identity function. CL2
does not take a prior standalone repin: its repin and parity fix are one reviewed head, so main
never carries E1 with `run` and `validate` choosing different first codes for equal targets.

## 11. Open questions (owner)

- **OQ-1.** May two tables ever write into one destination on purpose (append, or a union file)?
  Working answer: no, refuse; a union belongs in a table, not in the writer.
- **OQ-2.** Two codes stay: `target_shared_destination` (the declarations name one destination)
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
| 5 | Normalized guard scanners | T-E15 parses AST and resolves `import decoy_engine.config._targets as x`, `import decoy_engine.config._targets` attribute calls, `from ... import _target_identity as x`, and unaliased calls before matching. Its seeded direct-import mutation must fail. The 7.1a scan remains a one-off builder check, not a guard. |
| 6 | No reaching into private modules | CL1 imports `resolved_output_collisions`, `LayoutError` and `OUTPUT_PATH_COLLISION` from public `decoy.cli.io`, adding the missing `OUTPUT_PATH_COLLISION` export there, never `_placement` or `_layout_errors`. The starter imports `duplicate_target_groups` from public `decoy_engine.config`; only `_pipeline.py`, inside the owning config package, may import its sibling `_targets.py`. CL2 exports its finding helper from `decoy.cli.gate`. |
| 7 | No hidden CI failures | N/A: no CI change. |
| 8 | One input, one trust class per entry point | the config's target paths are one input with one shared rule per trust class: conservative `duplicate_target_groups` for declarations and CLI `resolved_output_collisions` for placed files. Command routes enter it through `layout_issues`; the fixed-layout Python API calls the same disk core after its `out=` binding. T-C2 and T-C8 keep both exceptional entry points ordered before source reads. |
| 9 | Mutations on the final head | every M-* in section 7 reruns on the final head of each slice. |
| 10 | Allowlisted helpers are still checked | N/A: no allowlist entry. |
| 11 | No raised caps | `config/_pipeline.py` grows by about 25 lines (406 now) and stays under 600; no cap, ratchet or allowlist is raised. |

Case and Unicode variants of one file name are the CLI's `_destination_key`, reused. Windows
paths with no parent segment are compared by the host's `normpath`, which treats separators as
that host's writer does. A path with a parent segment stays text-exact in the engine and is decided
only after CLI placement; no new OS branch.

## 13. V2-LOG

- **Existing 800-line test file.** CLI `tests/e2e/project_layout/test_layout_gate.py` is 803 lines
  at `65b710c`; CL2 changes expectations in place and may add a few lines. This is in the
  owner-defined 800 to 900 cleanup band, not a merge blocker.
- **Opaque storage aliases.** Two textually different S3 endpoint URLs may resolve to one service.
  Declarations cannot prove that equality without network resolution, so E1 leaves it to the
  platform writer. This plan does not change that parked writer.

## 14. Pre-mortem

- E1 rejects a shipped example or fixture that reuses a target path. Known hits are the 7.1a
  helpers, migrated in E1; the YAML and JSON fixtures of both repos have no duplicate (Dennis r1
  scan). The full engine suite runs for E1.
- E1 rejects an unused target or two distinct storage bindings because their locator text looks
  equal. T-E12 to T-E14 pin the conservative boundary and fail on the over-broad identities.
- CL2's deferral hides another layout fault that used to come first. Check: T-C5 plus the
  existing AT-4 and AT-16 cells.
- A new target type (SFTP) is added without an identity. The private identity primitive raises on
  an unknown type, so validation fails loudly until it is added.

## 15. Stop lines for builders

- Do not add a second identity function, a second collision loop or a second reason code.
- Do not quote a path, bucket, key or object in any message.
- Do not echo an endpoint, credential reference or unknown target-type literal in an error.
- Do not change exit codes or `--json` shapes.
- E1 does not start before #589 merges; E1 itself makes #589's identity the conservative one in 4.1.
- CL1 checks placed paths, never declared text; do not widen `names_a_file_inside`.
- Both engine E1 and mask CL1 ignore target keys that name no declared table.
- CL2 changes the early layout refusal only for `target_shared_destination`, and then raises.
- CL2 owns the engine repin; do not merge a repin-only intermediate head.
- The CL1 check input is built fresh; `config_dict` is never edited.

## 16. Verification status

- Probe results in 1.2: real runs on the Mac mini (CLI `65b710c` with engine 0.24.0; engine
  `187a14e6`).
- Code facts in 1.1 and 4.2: read at the bases, not run. The tokenize gap and the `../x.csv`
  hole in CL1 come from Dennis r1's code reading, not from a probe.
- #589 merges with its current public `target_identity` (orchestrator ruling, T0888). The
  conservative identity and the grouping boundary of 4.1 are E1's work, after #589 merges.
