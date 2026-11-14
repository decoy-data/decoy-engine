Status: plan

# DUP-DEST: refuse two tables that write to one destination

Rules consulted: `/home/cam/dev-rules/README.md`, `00-universal.md`, `risk-and-exceptions.md`,
`development-loop.md`, `bug-fix.md`, `architecture.md`, `reuse-first.md`,
`api-and-compatibility.md`, `security.md`, `testing.md`, `verification.md`, `documentation.md`,
`catalogs/recurring-defects.md`; engine `CLAUDE.md`, `CODEMAP.md`,
`docs/compatibility-contract.md`; CLI `CODEMAP.md`, `docs/ROADMAP.md`.

Revision 1, not yet reviewed.

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

- **CLI `decoy validate`, `decoy run`, `decoy tokenize`, `decoy ci check`.** All four reach
  `layout_issues` (`src/decoy/cli/io/_placement.py:263`), whose last step is
  `resolved_output_collisions` (`_placement.py:213`). It keys every local file target, an enabled
  quarantine and the typed side files by filesystem identity (`_destination_key`, `:127`: device
  and inode for existing files, nearest existing directory plus a normalized suffix otherwise,
  case and NFC folding where the volume folds) and refuses the first clash with
  `layout.output_path_collision`, exit 1, naming config locations only. Cloud targets take a
  separate rule (`_cloud.py:_key_issues`, `:111`): every cloud target must share one directory
  (`_split_issues`), and two with the same file name are refused with `cloud.target_invalid`.
- **CLI `decoy.mask()`** (`src/decoy/api.py:326`). Validates with `parse_pipeline_config`, builds
  `RunLayout.fixed(base_dir)` and calls `_write_mask_outputs` (`api.py:540`), which loops
  `write_targets` (`src/decoy/cli/io/_targets.py:461`). It never calls `layout_issues` or
  `resolved_output_collisions`.
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

### 1.3 Problem

`decoy.mask()` writes two tables to one file without a word: the first table is lost on disk while
the call returns both frames, so the caller sees success. That is data loss, a V1 blocker. The
engine accepts the same config, so any engine caller that writes targets (the parked platform
runner, a script on the public API) has to find the clash itself, and today only the CLI's
command routes do.

## 2. Guarantee

1. A pipeline config in which two or more targets have the same `target_identity` is refused by
   `PipelineConfig` validation, so by every caller that validates (`parse_pipeline_config`,
   `PipelineConfig.model_validate`), before any source is read or any output written. The code
   is `target.shared_destination`; each table in the clash gets one problem located at
   `targets.<table>`, in config order. The text is the registry's fixed summary. No path, bucket,
   key or object appears in any message, location or log line.
2. `decoy.mask()` refuses two outputs that resolve to one file on disk (symlinked folder,
   case-only difference on a folding volume, hard link, relative against absolute spelling, a
   target against an enabled quarantine path) with the CLI's existing
   `layout.output_path_collision`, before any source is read and before any file is written.
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
  For each identity held by two or more tables it adds one `(("targets", table), code)` problem per
  table, then raises through `problem_details` and `ValidationError.from_exception_data`, the
  pattern `_unique_domains_valid` already uses (`_pipeline.py:340`). `validation_problems` turns a
  registered code into its fixed summary, so the message carries no input.
- Reason code `target.shared_destination`, declared beside the `target_file.*` codes in
  `reasons/config/_part1.py`, `since=UNRELEASED`, summary "Two or more targets write to one
  destination. Give each table its own target." It goes in the unreleased set that release prep
  stamps.
- Identity is the text form only. Symlinks, case folding and relative against absolute are the
  writer's concern at run time (#589's amendment says the same for the starter builder), and the
  CLI's writer already checks them (4.2).
- Table kind does not enter: mask, generate and mixed tables are all keys of `targets`.
- One choke point. `compile_plan` and `run_config_only_checks` do not repeat the check:
  `run_pipeline` documents that its config is the validated dump, and the engine writes no
  target path itself (1.1).

### 4.2 CLI

- **CL1, `decoy.mask()`.** After `parse_pipeline_config` and the `out=` merge, before
  `_load_sources_from_config`, call `resolved_output_collisions(config_dict, base_dir)` and on a
  clash raise `OUTPUT_PATH_COLLISION.error(first=..., second=...)`, the same `LayoutError`
  `decoy run` raises, documented under the API's `Raises:`. No new rule, no new code. This lands
  on the current engine pin and closes the data loss by itself; the engine rule (E1) then adds
  the same refusal for every other engine caller.
- **CL2, run and validate parity (after the repin to the engine release that carries E1).**
  `decoy run` checks layout before the gate (`run/_prepare.py:260` `_refuse_layout_faults`,
  called at `:319`), while `decoy validate` runs the schema first and stops there
  (`gate/_layers.py:117`). With E1 in, the same config would give `layout.output_path_collision`
  from run and `target.shared_destination` from validate. `_refuse_layout_faults` returns without
  findings when `parse_pipeline_config(ctx.raw)` refuses, so the gate reports the schema problem
  first in both commands. Builder: re-read `_prepare.py:300-330` and confirm nothing else depends
  on the early layout refusal before changing it; if something does, stop and report.
- **CL2, test expectations.** The AT-31 cells in `tests/e2e/project_layout/test_layout_gate.py`
  whose outputs are the same as written (two equal relative paths, equal absolute paths, dot and
  separator spellings) now expect `target.shared_destination`; the symlink, hard-link,
  case-folding and target-against-quarantine cells keep `layout.output_path_collision`. Cloud
  cells with two equal keys expect the engine code; the CLI's "shares its file name" branch in
  `_key_issues` stays as a defense.

## 5. Behaviour

| Input | Before | After |
|---|---|---|
| engine `PipelineConfig.model_validate` with two equal targets (any type) | accepted | `ValidationError`, one `target.shared_destination` per table |
| CLI `validate`, two equal targets | exit 1 layout or cloud code | exit 1 `target.shared_destination` |
| CLI `run`, two equal targets | exit 1 layout or cloud code | exit 1 `target.shared_destination` |
| CLI `run` or `validate`, outputs equal only on disk | exit 1 `layout.output_path_collision` | unchanged |
| `decoy.mask()`, two equal targets or `out=` paths | silent overwrite | CL1: `LayoutError` `layout.output_path_collision`; after the repin the engine's `PipelineConfigError` fires first |
| `decoy.mask()`, outputs equal only on disk | silent overwrite | `LayoutError` `layout.output_path_collision` |
| any config with distinct targets | runs | runs, same bytes |

## 6. Failure modes

### 6.1 Class table

| # | Class | Structure that closes it | Proof | Mutation that turns it red |
|---|---|---|---|---|
| 1 | Value-bearing output | the engine problem text is the registry summary; the location is `targets.<table>`; no path, bucket, key or object reaches a message, `str(exc)`, a log line or `--json`. CL1 reuses `OUTPUT_PATH_COLLISION`, which names config locations only | T-E8, T-C1 | interpolate the path into a custom message |
| 2 | Cleanup missing on an exit path | N/A with a reason: both refusals fire before any output is opened, so nothing is left behind | T-C1 (no file under the folder) | move the CL1 check after `_write_mask_outputs` |
| 3 | State and concurrency | N/A: the validator and the CL1 check are pure functions of the config and the folder; no shared or module state is added | T-E6 (stable order) | collect problems in a module-level set |
| 4 | Route parity and silent fallback | one engine choke point (`PipelineConfig`) covers every engine caller; CL1 brings `decoy.mask()` to the rule `run`, `validate`, `tokenize` and `ci check` already use; CL2 makes `validate` and `run` report the same first code | T-C1, T-C2, T-C5, T-C6 | skip the CL1 check when `out=` is given; keep the early layout refusal in `run` |
| 5 | Referential integrity | N/A with a reason: no key, FK or vault path changes; side files (vault, evidence, result) keep the CLI's existing typed placement rule | existing AT-31 cells | none new |
| 6 | Untrusted producer | the config is user input; `target_identity` raises on an unknown target type, so a type added later without an identity fails validation instead of being skipped | #589's `target_identity` tests, T-E9 | return `None` for an unknown type and skip it |
| 7 | Check then use (TOCTOU) | the engine check is on declarations, so it has no filesystem window. CL1 resolves the folder once before the first write; a file created by another process between the check and the write is out of scope (header), same as today's `run` | T-C3 | resolve the targets again inside `write_targets` and compare there |
| 8 | Weak tests and overclaimed evidence | every test names the code, the locations and that no file exists; each test has a named mutation in section 7; mutations rerun on the final head | gate reviewers rerun them | relax T-E1 to "raises `ValidationError`" |
| 9 | Behaviour-preserving refactor drift | N/A: no code moves; a config with distinct targets validates and writes the same bytes | T-E9, T-C4 | none |
| 10 | Frozen contract drift | one reason code added (`since=UNRELEASED`); no exit code or `--json` shape moves; CL2 changes which code some configs report before REL-GATE (row 93) | T-C5, T-C6, registry tests | renumber or rename an existing code |

### 6.2 Enumerations

#### Exit paths

| Entry point | Where it refuses | Exit or raise |
|---|---|---|
| engine `parse_pipeline_config` / `PipelineConfig.model_validate` | `_targets_distinct`, beside `_unique_domains_valid` (`config/_pipeline.py:340`) | `ValidationError` (`PipelineConfigError` from `parse_pipeline_config`) |
| CLI `decoy validate` | gate schema layer (`gate/_layers.py:117`) | 1 |
| CLI `decoy run` (plain, `--chunked`, `--out-dir`) | today `_refuse_layout_faults` (`run/_prepare.py:260`, called at `:319`); after CL2 the gate | 1 |
| CLI `decoy tokenize`, `decoy ci check` | `layout_findings`, then the engine schema | 1 |
| CLI `decoy.mask()` | CL1 check after `parse_pipeline_config` (`api.py:460`), before `_load_sources_from_config` (`api.py:506`) | raises `LayoutError` |

#### Routes

| Route | Reaches the engine rule | Reaches the CLI disk rule |
|---|---|---|
| whole-frame `run` | yes, schema | yes, `resolved_output_collisions` (`io/_placement.py:213`) |
| `run --chunked` | yes | yes |
| `decoy.mask()` | yes, `parse_pipeline_config` (`api.py:460`) | CL1 adds it |
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
| T-E1 | two file targets, same path: refused, problems at `targets.a` and `targets.b`, code `target.shared_destination` | M-E1: remove the validator |
| T-E2 | `out/a.csv` against `out/./a.csv` and `out//a.csv`: refused | M-E2: compare `path` instead of `target_identity` |
| T-E3 | S3 same bucket and key refused; same key in another bucket accepted; same bucket, other key accepted | M-E3: drop the bucket from the comparison |
| T-E4 | GCS, the three cells of T-E3 | M-E4: as M-E3 for GCS |
| T-E5 | file `a.csv` against S3 key `a.csv`: accepted | M-E5: compare without the type element |
| T-E6 | three tables on one destination give three problems in config order; two separate pairs give four | M-E6: report only the second table of a group |
| T-E7 | a mask table and a generate table on one path: refused | M-E7: group only tables with `columns` |
| T-E8 | no path, bucket, key or object text in `str(exc)`, in any problem text or location; the code is registered | M-E8: interpolate the path into a custom message |
| T-E9 | distinct targets: the existing config fixtures still validate (the config suite stays green) | none |

### 7.2 CLI CL1 (current pin), `tests/e2e/test_mask_api_destinations.py`

| Id | Test | Mutation |
|---|---|---|
| T-C1 | `decoy.mask(config=...)` with two equal absolute targets raises `LayoutError` `layout.output_path_collision`; no source read (spy on `_load_sources_from_config`); no file under the folder | M-C1: skip the check |
| T-C2 | `out={"a": p, "b": p}` on distinct declared targets: refused | M-C2: check before the `out=` merge |
| T-C3 | relative dot spelling; case-only names on a folding volume (skip where the volume does not fold); a symlinked folder | M-C3: compare `normpath` text instead of `resolved_output_collisions` |
| T-C4 | distinct targets: both files written with their own rows | none |

### 7.3 CLI CL2 (after the repin)

| Id | Test | Mutation |
|---|---|---|
| T-C5 | the same config through `validate` and `run`: same first code, exit 1, for (a) two equal relative paths: `target.shared_destination`; (b) a symlinked folder: `layout.output_path_collision` | M-C5: keep the early layout refusal |
| T-C6 | two S3 targets with one key: `target.shared_destination` from both commands | M-C6: as M-C5 |
| T-C7 | updated AT-31 cells per 4.2 | none |

## 7a. Reuse inventory

| Need | Reused | Not reused, why |
|---|---|---|
| same destination as declared | `config.target_identity` (#589) | none |
| coded value-free config problem | `_generate_options.problem_details`, `validation_problems` | none |
| same file on disk | CLI `resolved_output_collisions`, `OUTPUT_PATH_COLLISION` | none |

## 8. Placement

| Change | File | CODEMAP row |
|---|---|---|
| validator | `src/decoy_engine/config/_pipeline.py` (406 lines, about +25) | `config/_pipeline.py` |
| reason code | `src/decoy_engine/reasons/config/_part1.py` | reasons |
| engine tests | `tests/unit/config/test_target_destinations.py` (new) | |
| changelog | `changelog.d/dup-dest-e1.md` | |
| docs | `docs/` config reference: one line under targets ("each table needs its own destination") | |
| CLI API check | `src/decoy/api.py` (CL1) | CLI `api.py` |
| CLI run parity | `src/decoy/cli/run/_prepare.py` (CL2) | CLI `run/` |
| CLI tests | `tests/e2e/test_mask_api_destinations.py` (new, CL1); `tests/e2e/project_layout/test_layout_gate.py` (CL2) | |

No new module; `config/` and top-level module counts are unchanged.

## 9. Frozen contracts touched

- **Reason registry.** One code added, `since=UNRELEASED`; release prep stamps it.
- **Exit codes.** None move (1 before, 1 after).
- **`--json` shapes.** Unchanged; some configs report a different code before REL-GATE (row 93)
  freezes codes.
- **Determinism and output bytes.** Unchanged for every config that still validates.

## 10. Slices

| Slice | Repo | Depends on | Content | Risk |
|---|---|---|---|---|
| CL1 | CLI | nothing | 4.2 first bullet, T-C1 to T-C4 | R2 |
| E1 | engine | #589 merged (`target_identity` on main) | 4.1, T-E1 to T-E9, changelog, docs line | R2 |
| CL2 | CLI | the engine release with E1, and the repin | 4.2 second and third bullets, T-C5 to T-C7 | R1 |

If #589 has not merged when E1 starts, E1 waits; it does not add its own identity function.

## 11. Open questions (owner)

- **OQ-1.** May two tables ever write into one destination on purpose (append, or a union file)?
  Working answer: no, refuse; a union belongs in a table, not in the writer.
- **OQ-2.** Two codes stay: `target.shared_destination` (the declarations name one destination)
  and `layout.output_path_collision` (two outputs meet on disk). Working answer: keep both; they
  point the user at different fixes.

## 12. Recurring-defect walk (`/home/cam/dev-rules/catalogs/recurring-defects.md`)

All ten classes are walked in 6.1. Two notes the table does not hold: case and Unicode variants
of one file name are the CLI's `_destination_key`, reused, and Windows paths are compared by the
same `normpath` text in the engine (`out\\a.csv` and `out/a.csv` are one identity only on
Windows, where `normpath` folds the separator); no new OS branch.

## 13. V2-LOG

None.

## 14. Pre-mortem

- E1 rejects a shipped example or fixture that reuses a target path. Check: the engine and CLI
  example configs and test fixtures validate in T-E9 and CL2's suite; a hit is a fixture bug.
- CL2's deferral hides another layout fault that used to come first. Check: T-C5 plus the
  existing AT-4 and AT-16 cells.
- A new target type (SFTP) is added without an identity. `target_identity` raises on an unknown
  type, so validation fails loudly until it is added.

## 15. Stop lines for builders

- Do not add a second identity function, a second collision loop or a second reason code.
- Do not quote a path, bucket, key or object in any message.
- Do not change exit codes or `--json` shapes.
- E1 does not start before #589 merges.

## 16. Verification status

- Probe results in 1.2: real runs on the Mac mini (CLI `65b710c` with engine 0.24.0; engine
  `187a14e6`).
- Code facts in 1.1 and 4.2: read at the bases, not run.
- `target_identity` is defined in #589's plan amendment (`ed9e65c9`); its code is not on that
  branch yet.
