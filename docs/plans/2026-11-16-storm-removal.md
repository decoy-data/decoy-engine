Status: plan

# STORM name removal from the CLI and the engine before V1 (roadmap rows 16 and 56)

Rules consulted: `/home/cam/dev-rules/README.md`, `00-universal.md`, `risk-and-exceptions.md`,
`development-loop.md`, `proportionality.md`, `cross-cutting-concerns.md`, `api-and-compatibility.md`;
engine `docs/compatibility-contract.md` (section 1), `docs/frozen-surfaces.md`, `docs/reasons.md`,
`CONTRIBUTING.md` (reason registry rules), `changelog.d/README.md`; CLI `CODEMAP.md` ("Where Things
Go"), `docs/release/frozen-surfaces.md`, `docs/ROADMAP.md` (rows 16, 18, 56),
`tests/sentry/cli_text/_banned_text.py`; inputs: platform `origin/plan/storm-rename-recut`
`docs/plans/2026-11-01-storm-rename-recut.md` (name map, CLI slices C0 to C4, Q11), CLI
`origin/claude/storm-split-cli` `a677d509`, engine `docs/plans/2026-10-09-storm-split-taxonomy.md`
and `-survey.md`.

Revision 3 (Dennis r2 fixes; the revision map is section 17).

Bases (2026-11-16): engine `origin/main` `ddd014a5` (the `v0.27.0` release commit, registry
`1.29.0`); CLI `origin/main` `307a189a` (pins `decoy-engine==0.26.0`, `pyproject.toml:136`; the
0.27.0 repin is not merged yet). Every count and line number below is read at these bases with
`git grep -I -i storm`.

Owner decisions used: the owner goal of 2026-11-16 (no V1 user meets the word in the CLI or the
engine); pre-GA hard delete (engine `docs/compatibility-contract.md` section 1); Q1 yes (the
one-time registry exception, 2026-11-16); Q2 yes (release gate B-3 owns decoy-web, 2026-11-16);
Q11 version B of the old plan (no engine code for the parked platform, confirmed 2026-11-16); the CLI verbs `scan`, `report integrity` and
`report fidelity` keep their names (out of scope); "Renames after 1.0 are 2.0" (CLI
`docs/roadmap/post-1.0-plan.md:59`), which is why this lands before V1.

Risk: E1 (engine) is R2: it removes two identities from the frozen reason registry under a recorded
exception (Q1) and changes what the sdist ships. C1, C1b and C3 (CLI) are R1: text, names, test
file names and docs. C2 (CLI) is R2 because it touches the frozen `decoy-ci/v1` schema (annotation
only) and the text `decoy init` writes into user YAML.

## 1. Frame

### 1.1 Measurement

Unit: tracked text lines that contain the token, case-insensitive (`git grep -I -i -c`), plus
tracked paths whose name contains it. Occurrences (`git grep -o`) are given for comparison.

| Repo | Lines (files) | Occurrences | Paths with the token in the name | History lines (files) | Non-history lines (files) |
|---|---|---|---|---|---|
| engine `ddd014a5` | 436 (69) | 620 | 8, all under `docs/plans/` and `docs/records/` | 390 (64) | 46 (5) |
| CLI `307a189a` | 509 (89) | 578 | 6: `src/decoy/ui/storm_animation.py` and five `tests/e2e/test_storm_*.py` | 169 (25) | 340 (64): src 96 (17), tests 153 (29), docs and generated 91 (18) |

"History" here is the final allowlist of section 4.4.

Engine non-history files: `src/decoy_engine/reasons/route/_retired.py` (8),
`tests/fixtures/f29/reason-manifest-v1.json` (2), `tests/fixtures/f29/reason-registry-release.json`
(2), `tests/unit/test_shipped_reason_identities.py` (4), `tests/sentry/test_no_residual_removed_surface.py` (30).
Nothing else in engine `src/`, `README.md`, `CODEMAP.md` or the guides carries it.

The published Sphinx site is not clean today. `docs/conf.py:404` to `:434` excludes `archive/**`,
`plans/**` and `decisions/**`, but not `records/**`, so the 22 token-bearing files under
`docs/records/` become pages and search entries. Two published pages link into `records/`
(`docs/execution-backends.md:9`, `docs/security/file-access-policy.md:10`); the docs build runs
with `-W` (`.github/workflows/docs.yml:50`), so excluding the folder also needs those two links
turned into plain path text, the form `docs/compatibility-contract.md:494` already uses.

Packaging: both sdists keep hatchling's default file selection (engine `pyproject.toml:359`
excludes only `.claude`, `.hypothesis`, `tests`; CLI `pyproject.toml:247` only `tests`), so every
history file under `docs/` ships to PyPI. Wheels hold no `docs/`.

CLI non-history files: src `api.py` 2, `ci/adapters.py` 1, `ci/contracts.py` 1,
`cli/_init_inference.py` 24, `cli/compile_explain.py` 1, `cli/completers.py` 1, `cli/demo.py` 6,
`cli/exit_codes.py` 1, `cli/explain.py` 8, `cli/extras.py` 1, `cli/init.py` 8, `cli/report.py` 9,
`cli/scan.py` 19, `cli/scanning/_multi.py` 4, `templates/__init__.py` 1, `ui/progress.py` 1,
`ui/storm_animation.py` 8; 29 test files (153 lines, the five `test_storm_*` files hold 86); docs
`.tours/1-onboarding.tour` 2, `CHANGELOG.md` 13 (all under `[Unreleased]`, which becomes the V1
notes), `CODEMAP.md` 3, `README.md` 3, `SECURITY.md` 2, `docs/ROADMAP.md` 17, `docs/ci-contracts.md`
1, `docs/cli-reference.md` 14, `docs/diagrams/*.svg` 23, `docs/qa/cli-v1-checklist.md` 2,
`docs/roadmap/` living pages 10, `docs/schemas/decoy-ci-v1.schema.json` 1.

### 1.2 What a V1 user meets today

- `decoy explain storm` is a topic, listed in `decoy explain` (`src/decoy/cli/explain.py:177`,
  `:711`); `decoy scan --help` says "See also: decoy explain storm" (`src/decoy/cli/scan.py:145`).
- Help and card text: "STORM (Statistical Top-down Risk Mapping)" (`scan.py:4`), "Path to a STORM
  scan JSON" (`scan.py:617`, `:727`, `:945`, `:948`), "flagged by STORM pattern matching"
  (`src/decoy/cli/scanning/_multi.py:329`), "JobStormReport" in `report integrity` help
  (`src/decoy/cli/report.py:1933`, `:1947`), the Rich table title "Storm integrity" (`report.py:2063`).
- Output and errors: `decoy demo` prints "Scanning with STORM..." (`src/decoy/cli/demo.py:161`);
  `decoy init <file>` fails with "STORM scan failed: ..." (`src/decoy/cli/init.py:378`).
- Scaffolded YAML: every `# REVIEW:` comment `decoy init <file>` writes starts "STORM detected ..."
  (`src/decoy/cli/_init_inference.py:75` to `:219`).
- Schemas: the `decoy-ci/v1` `DriftCheck` description (`src/decoy/ci/contracts.py:519`, generated into
  `docs/schemas/decoy-ci-v1.schema.json:49`).
- Reason codes: the engine registry still carries two tombstones, `route.run_storm` and
  `route.run_storm_requested`, with summaries that say "STORM" (`_retired.py:20`, `:27`). They are
  never emitted, but `decoy_engine.reasons.manifest()` lists them, and the CLI's SARIF rule-code
  allowlist is built from that manifest, tombstones included (`src/decoy/ci/rule_codes.py:200` to `:209`).
- Module, file and test names: `decoy.ui.storm_animation`, `stormy_multistage`, `_StormyHandle`, the
  five `tests/e2e/test_storm_*.py` files, the private alias `_storm_infer_format` (`src/decoy/api.py:54`).
- Docs: README, SECURITY.md, CODEMAP (which still points at a deleted `src/decoy/cli/storm.py`,
  `CODEMAP.md:95`), the onboarding tour, `docs/cli-reference.md`, `docs/ci-contracts.md:31`, the
  diagrams, and the `[Unreleased]` CHANGELOG section.
- Engine docs site: 22 `docs/records/` pages (1.1). Both sdists on PyPI: the dated history under
  `docs/` (1.1).
- Decoded old records: none today. No CLI code decodes a persisted reason or renders
  `original_identity` (`git grep` at `307a189a`; the one reason emitter, `src/decoy/cli/run/_errors.py:79`,
  builds from a live exception, where that field is always empty). The engine path that could carry
  it is `run_result/_model.py:211` (`read_reason` re-emits `to_payload()`, context included), which
  the CLI does not call.

### 1.3 Interactions

- Engine release and CLI repin. The CLI cannot drop the tombstones from its SARIF allowlist or from
  any engine text until it pins an engine release that carries E1. The CLI is at 0.26.0 today; the
  0.27.0 repin is in flight and does not carry E1. E1 ships in the next engine release (0.28.0 or
  later, daily train) and the CLI repins to it.
- Parked platform. It still uses the old names in thousands of places and, on repin, would lose
  `reasons.route.RUN_STORM` and `RUN_STORM_REQUESTED`. Its own wave (the old plan) owns that; under
  Q11 version B it needs no engine code. Nothing here waits on the platform.
- Public docs live in a third repo, decoy-web (`origin/main` `5137913`: 87 occurrences in 21 files,
  among them `docs-src/components/marketing/storm.tsx` and the vendored
  `docs-src/content/docs/reference/cli/_source/cli-reference.md`, 16 lines). CLI release gate B-3
  (`docs/roadmap/release-gates.md:13`) owns taking `docs-src/` off this branding (owner Q2, decided
  yes). This plan does not edit decoy-web.
- Busy CLI files: `scan.py`, `report.py`, `init.py` and `explain.py` are touched by other V1 rows.
  C1 and C2 are text edits and rebase cheaply; they do not move code between modules.
- The old CLI branch `claude/storm-split-cli` (`a677d509`) is the 0.17.0 import migration, already
  superseded on main. Nothing is taken from it; it retires with this wave
  (`docs/roadmap/branch-register.md:28`).

## 2. Guarantee

After the last slice of each repo merges:

1. No tracked path and no tracked file in the engine or the CLI contains the token, case-insensitive,
   outside the history allowlist of 4.4. A residual sentry in each repo enforces this on every merge.
2. The installed engine's reason registry (`reasons.manifest()`) holds no identity whose code,
   summary, owner or symbol contains the token, and therefore neither does the CLI's SARIF rule-code
   allowlist.
3. No CLI help page, `explain` topic, human or `--json` output, error line, scaffolded YAML from
   `init` or `demo`, or schema text that a CLI command renders contains the token, checked by
   rendering them with the pinned engine. No CLI code renders a decoded reason's
   `original_identity`, so a record that names a removed code never puts the old name on screen
   (AT-C7). The engine docs site and both sdists carry no history folder (AT-S1, 4.4).
4. Behaviour is unchanged apart from the text: same verbs, same flags, same exit codes, same `--json`
   keys, same `decoy-ci/v1` validation, same generated and masked output. The only removed
   behaviours are `decoy explain storm` (now a usage error, its body moves to `decoy explain scan`)
   and the resolution of the two retired route codes (a record naming one decodes as
   `decoy.unknown_reason_from_future`; its context keeps `original_identity`, the old pair, which
   only engine diagnostics read). Two known effects of not moving the registry version: engine
   0.27.0 and the first release with E1 both report registry `1.29.0` with different catalogs, and
   an engine branch forked before E1 sees the two codes as `stale-since` in its registry checks
   until it rebases (4.2).

Non-goals: renaming the verbs `scan`, `report integrity`, `report fidelity`; the platform; decoy-web
(B-3, owner Q2); rewriting dated history; the scan progress animation's look (the cloud art stays, only
its names change); a registry version mechanism for removals (section 4.2).

## 3. Established solutions

Search run: the codebase first (both repos and the old platform plan), then the general practice for
retiring a product name and for keeping it out (deprecation guides, "forbidden term" lint rules,
and the ratchet and allowlist pattern).

- Keeping a retired name out: the established form is a repository-wide forbidden-term check with an
  explicit allowlist, run in CI (Vale and alex style term lists, `git grep` based pre-commit hooks,
  and the engine's own `tests/sentry/test_no_residual_removed_surface.py`, which already does this for
  this token). This plan reuses the engine sentry's shape (path scan plus content scan over `git
  ls-files`, a documented `Allowed` table, seeded violations per surface) and copies it to the CLI,
  as the engine sentry's docstring already says each consumer repo should.
- Migrating many files under a guard: the ratchet manifest (a per-file count that may only fall),
  as in the CLI's shrink-only baselines (`tests/sentry/_ratchet.py`, `tests/sentry/baselines/`) and
  the old plan's C0. Used for the CLI only, for the two slices between the sentry landing and the
  last slice.
- Removing a registered error code before GA: semantic-versioning practice for error catalogs is
  "codes are append-only after release; pre-1.0 anything may change". The engine already encodes the
  reader side of this: an unknown identity under a supported registry major degrades to
  `decoy.unknown_reason_from_future`, keeping the original identity as context
  (`src/decoy_engine/reasons/_record.py:397`, `:398`). That is the established "tolerant reader"
  pattern, so a hard delete needs no new reader code.
- Not reused: the old plan's `storm_inventory.py` and `storm_slice_measure.py` (platform branch).
  They were built for 10130 platform occurrences across 63 slices. Here the non-history surface is
  46 engine lines in 5 files and 340 CLI lines in 64 files; `git grep -c` and `git diff --numstat`
  measure that directly, and vendoring two scripts plus a JSON slice file would add more lines than
  the CLI edits they measure.

Custom code that remains: the two sentries (about 150 lines each, one already exists), one CLI
test that renders the runtime outputs the banned-text sentry cannot reach, and one pattern added to
the CLI's existing banned-text registry. No production machinery is added.

## 4. Design

### 4.1 Name map

| Old | New | Where |
|---|---|---|
| `decoy explain storm` topic | `decoy explain scan` (same summary and body, reworded) | `src/decoy/cli/explain.py:177`; every "see also" that points at it |
| "STORM", "STORM (Statistical Top-down Risk Mapping)" in help and prose | "the scan", "pre-scan detection" | `scan.py`, `scanning/_multi.py`, `init.py`, `demo.py`, `explain.py`, docs |
| "STORM scan JSON" | "saved scan JSON" | `scan.py` help, `docs/ci-contracts.md:31`, `decoy-ci/v1` description |
| "JobStormReport" (help), "Storm integrity" (table title) | "integrity report", "Post-scan integrity" | `report.py:1890`, `:1933`, `:1947`, `:2063` |
| `# REVIEW:` text "STORM detected X. ..." | "The scan found X. ..." (rest of each sentence unchanged) | `_init_inference.py:75` to `:219` |
| "Scanning with STORM...", "STORM scan failed: {type}." | "Scanning...", "Scan failed: {type}." | `demo.py:161`, `init.py:378` |
| `src/decoy/ui/storm_animation.py`, `stormy_multistage`, `_StormyHandle` | `src/decoy/ui/scan_progress.py`, `scan_multistage`, `_StageHandle` | `ui/`, `scanning/_multi.py:35`, `:445`; `ui/progress.py:39` docstring |
| `_storm_infer_format` (private import alias) | the imported name `_infer_format`, no alias | `src/decoy/api.py:54`, `:703` |
| `tests/e2e/test_storm_animation.py`, `_command.py`, `_diff.py`, `_explore.py`, `_sp16.py` | `tests/e2e/test_scan_progress.py`, `test_scan_default.py`, `test_scan_diff.py`, `test_scan_fields_show.py`, `test_scan_formats.py` | `git mv`, then edit |
| `ml` extra: "The STORM field-classifier" | "The field classifier `decoy scan` uses" | `explain.py:571`, `README.md:45` |
| comments "storm-reframe-C", "storm.py", "`storm` group" | the plain history ("the V1 recommender was removed", "moved from the old scan group") | 7 comment-only modules (C2: 5; C3: `templates/__init__.py`, `ci/adapters.py`) |
| engine `route.run_storm`, `route.run_storm_requested` (tombstones) | removed, no replacement name (4.2) | `_retired.py:20`, `:27` |

### 4.2 The two retired engine codes: hard delete

Options weighed:

- Rename to new tombstone names. A tombstone exists only so a persisted record that names the old
  code still resolves. A renamed tombstone resolves a name no release ever wrote, and the old
  identity is still deleted, so renaming carries every cost of deletion and none of its value.
- Keep them. They are user-visible through `reasons.manifest()` and the CLI's SARIF allowlist, so
  the owner goal is not met.
- Hard delete (chosen). Pre-GA rule ("pre-GA = hard delete", compatibility contract section 1). The
  only readers of records naming them are the engine and its consumers; the engine reader degrades an
  unknown identity to `decoy.unknown_reason_from_future` without raising (`_record.py:398`). No CLI
  release has shipped (`CHANGELOG.md` has only `[0.1.0]` below `[Unreleased]`), and no CLI code names
  either code.

What E1 must change, in one change, so every carrier agrees on one head. Items 1 to 7 are the hard
delete; items 8 to 11 are the files that break or leak once the sentry drops its token entries.

1. `src/decoy_engine/reasons/route/_retired.py`: delete `RUN_STORM_REQUESTED`, `RUN_STORM`, their
   `__all__` entries, and the docstring line about the sentry exception. The third tombstone
   (`POST_SCAN_INTEGRITY_REQUESTED`) stays.
2. `tests/fixtures/f29/reason-manifest-v1.json`: delete the two entries, so
   `test_v1_manifest_is_append_only` (`tests/unit/test_reason_registry.py:33`) compares against the
   catalog without them.
3. `tests/fixtures/f29/reason-registry-release.json`: delete the two identity records and lower
   `since_counts["1.0.0"]` by 2, so `scripts/release/reason_release_pin.py --check` and
   `--release-ready` pass. `registry_version` and `baseline_ceiling` stay `1.29.0`.
4. `tests/unit/test_shipped_reason_identities.py`: delete the file. Its guarantee is "every route
   reason v0.15.1 and v0.16.0 emitted resolves by name", which is exactly what E1 withdraws for two of
   its 29 rows. The 27 live rows stay guarded by the append-only manifest test. Its one general check,
   `test_no_tombstone_without_a_live_replacement`, moves to the new `tests/unit/test_reason_tombstones.py`
   unchanged.
5. `docs/reasons.md:27`: "Three tombstones exist today" becomes one (`route.post_scan_integrity_requested`).
6. `docs/compatibility-contract.md`: one "Pre-GA correction" paragraph after the existing ones.
7. `changelog.d/reason-tombstone-removal.md`: `Breaking:` line plus `### Removed`. Neither text spells
   the token: they name the replacements (`route/post_scan_integrity_requested`,
   `route/post_scan_integrity`) and "the two v0.16.0 route tombstones they replaced".
8. The string-target sentry. `tests/sentry/test_engine_string_targets.py:31` sets
   `_REMOVED = next(token for token in FORBIDDEN_TOKENS if _DOTTED.match(token))`; the only dotted
   entry is a token-bearing module path that 4.3 deletes, so the module raises `StopIteration` at
   collection. E1 deletes `_REMOVED`, its `EXEMPT` row (`:42`) and the `FORBIDDEN_TOKENS` import if
   nothing else uses it; the `("_REMOVED",)` masks argument at `tests/sentry/_baseline_sources.py:227`;
   and the `tests/sentry/test_no_residual_removed_surface.py::<removed-surface>` entry at
   `tests/sentry/baselines/wave-b-string-target-exempt.json:11`. These are shrinks (section 11).
9. `docs/conf.py` `exclude_patterns`: add `"records/**"` beside `"plans/**"`, with the comment the
   other working buckets carry. `docs/execution-backends.md:9` and
   `docs/security/file-access-policy.md:10` change their links into `records/` to plain path text
   (the `-W` build would fail on a link to an excluded page). AT-S1 asserts every engine
   `HISTORY_ROOTS` entry is excluded.
10. `pyproject.toml` `[tool.hatch.build.targets.sdist] exclude`: add `"docs/plans"`,
    `"docs/records"`, `"docs/archive"`, `"docs/decisions"`, one entry each. The wheel force-include
    of `docs/v2/ml/packs/lgbm-v1` is untouched (the comment at `pyproject.toml:347` explains why it
    must stay in the sdist). The packaging gate (`pytest -m packaging`) proves the sdist still
    builds a wheel with the pack.
11. `tests/sentry/test_physical_seam_disconnection.py:234`: replace the local `_RETIRED = "sto" +
    "rm"` reconstruction with an import of `RETIRED_NAME as _RETIRED` from
    `tests.sentry.test_no_residual_removed_surface`. The use at line 1000 and its behaviour stay
    unchanged, while the residual sentry remains the one source of the name.

Registry version. The branch rule forbids editing `REGISTRY_VERSION` (`CONTRIBUTING.md:57`), and the
release stamp moves the version only for pending additions, deprecations and summary edits. E1 adds
no removal mechanism (Proportionality: one removal, no second use). Consequence: the registry stays
`1.29.0` until the next release that carries an addition. A `1.29.0` record from 0.27.0 that names a
removed code decodes, in a later engine, as `decoy.unknown_reason_from_future` with the original
identity in context; this is the same path a record from a newer engine takes and needs no version
signal. Recorded in the compatibility contract paragraph.

Exception record (risk-and-exceptions): policy domain "reason registry append-only rule"
(`docs/reasons.md:23`, `CONTRIBUTING.md:58`); scope exactly the two identities above, one time, E1
only; risk R2; rationale as above; compensating controls AT-E2 to AT-E5, AT-C7 and the unchanged
tolerant reader; approver: the owner (Q1, approved 2026-11-16); expiry: closes when E1 merges.
Residual risks, all accepted:

- A pre-release record naming a removed code reads as an unknown reason instead of its tombstone
  summary. Only engine 0.15.1 and 0.16.0 emitted the two codes, before any CLI release a V1 user
  installs.
- The decoded record keeps `original_identity = ("route", <old code>)` in its context, and that
  pair spells the old name. It stays: it is the engine's diagnostic for an unknown reason and the
  same field a record from a newer engine uses. What stops a V1 user from reading it is the CLI
  side: no CLI output renders `original_identity` (measured, 1.2), and AT-C7 keeps it so.
- Registry `1.29.0` names two catalogs: the one in engine 0.27.0 (with the two codes) and the one
  in the first release with E1 (without them), until a later addition moves the version. A
  consumer that keys a cache on the registry version alone would hold a stale catalog; no consumer
  does (the CLI reads `manifest()` live).
- An engine branch forked before E1 still has the two codes in its catalog while main's pin and
  manifest fixture do not, so its registry checks report them as `stale-since` (and
  `registry_renumber.py --check` as extra identities) until it rebases onto E1. Rebasing clears it;
  no code change. `python scripts/dev/registry_renumber.py --check --main origin/main` (a manual pre-merge
check, not in CI) is expected to print exactly two lines, `deleted-existing route.run_storm` and
`deleted-existing route.run_storm_requested`; any other line stops the merge.

Q11 version B: `config.post_scan_owned_by_platform` was never registered (absent at `v0.17.0`
through `ddd014a5`). Row 16 no longer adds it. If the platform unparks, it uses a platform-local
constant as version B describes.

### 4.3 Residual sentries (the choke point)

The rule "the token never appears" has one site per tracked file, so the choke point is a scan of
the real artifact: `git ls-files` paths and contents. One sentry per repo:

- Engine: `tests/sentry/test_no_residual_removed_surface.py`, edited in place.
- CLI: new `tests/sentry/release/test_retired_name_residual.py`, the engine shape copied.

Both:

- Spell the token in two parts, `RETIRED_NAME = "st" + "orm"`, and compile it once as
  `RETIRED_PATTERN` (case-insensitive substring). Seeds and every other test that needs the string
  import `RETIRED_NAME` or `RETIRED_PATTERN` from the sentry module (one place per fact).
- Also compile `SPLIT_PATTERN`: the five letters with `[\s'"+]*` between each pair,
  case-insensitive, counted as a hit only when the matched span holds at least one `'` or `"`. It
  catches the name rebuilt from string pieces (`"st" + "orm"`, `"St" "orm"`, `'s' 'torm'`). The
  sentry module is the one file exempt from `SPLIT_PATTERN`, by exact path in code, not by a
  `HISTORY` row; `RETIRED_PATTERN` still scans it, and it holds no plain literal.
- Check the path and the content of every tracked file not matched by `HISTORY`.
- A tracked file is binary when its first 8000 bytes hold a NUL (git's own rule); binary files get
  the path check only. A tracked file that is not binary and does not decode as UTF-8 is a failure
  (`<path>: undecodable`), not a skip. Today's engine `scan()` does `continue` on
  `UnicodeDecodeError` (`tests/sentry/test_no_residual_removed_surface.py:114`), so a file saved in
  another encoding hides the token; E1 changes that.
- Carry `HISTORY` as `Allowed(glob, purpose)` rows and a fixed `HISTORY_ROOTS` tuple; a test fails if
  any `HISTORY` glob is not under one of the roots, so a non-history exception cannot be added
  without editing the roots in review.
- Keep seeded violations per surface: a path under `src/`, a Python identifier, a help string, a YAML
  comment, a JSON schema description, a test file name, a doc page, a CHANGELOG `[Unreleased]` line,
  a quote-split literal in a `src/` file, and a Latin-1 file holding the name (fails as undecodable).
- The engine sentry keeps its non-token forbidden list (the removed canary-check surface); its 16
  token-bearing entries go, since the case-insensitive scan already covers them.
- Engine only: `CHANGELOG.md` is history for released sections only. A line under `## [Unreleased]`
  that carries the token fails; a line under a dated release heading passes.

The CLI's `PENDING` ratchet (C1 and C2 only): a dict `{path: line_count}` of non-history files not yet
migrated, measured at each slice head. A file with hits that is not in `HISTORY` or `PENDING` fails;
a `PENDING` count that differs from the live count in either direction fails, so every slice lowers
it. C3 deletes `PENDING` and the sentry becomes absolute.

The CLI's one banned-text registry. `tests/sentry/cli_text/_banned_text.py` is where the CLI keeps
text a user must never read, and `tests/sentry/cli_text/test_user_text_internal_names.py` already
applies `BANNED_USER_TEXT` to the command tree, rendered help, usage lines, `explain` topics, AST
string constants and bundled templates. C2 appends `RETIRED_PATTERN` (imported from the residual
sentry, so the name is spelled once) to `BANNED_USER_TEXT` (`_banned_text.py:72`), and in the same
edit deletes the eight token-bearing `DEAD_STRINGS` entries and the `storm-reframe` pattern, which
the residual sentry and the new pattern cover more strictly. It lands in C2, not C1, because the
AST-constant check would fail on the `# REVIEW:` strings in `_init_inference.py` until C2 rewrites
them; C1's `explain` and help edits are pinned until then by AT-C3 and the residual sentry.

The runtime-output test (CLI): `tests/sentry/cli_text/test_no_retired_name_in_output.py`. It covers
only what the banned-text sentry does not reach, which is text produced by running a command:
`decoy scan` and the report-integrity output on a synthetic fixture, human and `--json` (C1); the
`decoy init <csv>` scaffold YAML, `decoy demo` output and `decoy schema` text (added in C2). It
finds each command path through the existing walker (`tests/command_tree.py`, so a renamed path
fails instead of being skipped) and checks the output with the same `BANNED_USER_TEXT` patterns
and hit helper the banned-text sentry uses. In C1, before C2 registers the pattern, it checks with
`RETIRED_PATTERN` itself, the same object C2 adds to the registry. No second scanner or matcher.

AT-C7 (CLI, C1) is a source-text proxy: no `src/decoy` module names a decoded reason's
`original_identity`. The string `original_identity` appears in no `src/decoy` file (measured: none
at `307a189a`). It does not prove that every rendering path drops the field. The library store calls
`records.decode` (`decoy/cli/library/_store.py:239`), and a run-result record can pass through
`RunResultRead.read_reason` (`run_result/_model.py:206`) and re-emit the original identity without
spelling the field in CLI source. Only engine 0.15.1 and 0.16.0 wrote records with either retired
identity, before any CLI release or the library store existed, so this gap is V2-LOG. A future
source renderer still has to delete or narrow AT-C7 in review, which is where the "never show the
old pair" decision is re-made.

Mutations that must turn each guard red: add `x = "Storm"` to `src/decoy/cli/scan.py` (CLI sentry);
add `x = "St" + "orm"` to `src/decoy/cli/scan.py` (split pattern); add `src/decoy/` to the CLI
`HISTORY` (roots test); put the token in a `changelog.d/` fragment (engine sentry); save a doc
page with the token as Latin-1 (undecodable); drop `"records/**"` from `docs/conf.py` (AT-S1
exclusion check); restore one `# REVIEW:` string in `_init_inference.py` (banned-text sentry and
the runtime-output test via `init`); add `print(ctx.original_identity)` to a `src/decoy` module
(AT-C7); restore `RUN_STORM` in `_retired.py` (engine sentry and AT-E2).

### 4.4 The history allowlist (final state)

Engine (`HISTORY_ROOTS` = `docs/plans/`, `docs/records/`, `docs/archive/`, `docs/decisions/`, plus
the CHANGELOG rule):

| Glob | Why it is history |
|---|---|
| `docs/plans/*` (with `docs/plans/evidence/`) | dated plans and their captured evidence; immutable once built; this plan lives here |
| `docs/records/*` | dated build, gate and audit records |
| `docs/archive/*` | archived reviews and discussions |
| `docs/decisions/*` | ADRs and the dated module-size census history |
| `CHANGELOG.md`, released sections only | entries for past releases (`[0.27.0]` and older) |

Removed from today's engine list (they are not history): `src/decoy_engine/reasons/route/_retired.py`,
the two f29 fixtures, `tests/unit/test_shipped_reason_identities.py`, and the sentry itself.

Every engine `HISTORY_ROOTS` folder is also kept out of what the engine publishes: the Sphinx site
(`docs/conf.py` `exclude_patterns`, E1 item 9, asserted by AT-S1) and the sdist (`pyproject.toml`
sdist `exclude`, E1 item 10).

CLI (`HISTORY_ROOTS` = `docs/plans/`, `docs/records/`, `docs/archive/`, `docs/superpowers/plans/`,
`docs/overnight-dev/findings/`, `docs/handoffs/`, and the two named logs):

| Glob | Lines today | Why it is history |
|---|---|---|
| `docs/plans/*` | 113 | dated plans |
| `docs/records/*` (with `docs/records/2026-11-12-duplication-census/`) | 16 | dated QA, health and census records |
| `docs/archive/*` | 6 | archived shipped logs |
| `docs/superpowers/plans/*` | 1 | a dated plan in the old plan folder |
| `docs/overnight-dev/findings/*` | 5 | a dated review finding |
| `docs/handoffs/[0-9][0-9][0-9][0-9]-*` | 1 | dated handoffs, the CLI's archived handoff folder; the date-prefix glob keeps a new undated file out |
| `docs/roadmap/decisions.md` | 12 | the dated owner decision log, the CLI's ADR record |
| `docs/RECENTLY-SHIPPED.md` | 4 | the dated shipped log |

Not history, so cleaned: CLI `CHANGELOG.md` (every hit is under `[Unreleased]`, which becomes the V1
notes), `docs/ROADMAP.md`, the living `docs/roadmap/` pages, `docs/qa/`, generated docs and diagrams.

The CLI has no published docs site of its own (decoy-web vendors its reference). Its sdist gets the
same treatment as the engine's in C3: `pyproject.toml:247` `exclude` adds `"docs/plans"`,
`"docs/records"`, `"docs/archive"`, `"docs/superpowers"`, `"docs/overnight-dev"`, `"docs/handoffs"`,
`"docs/roadmap/decisions.md"` and `"docs/RECENTLY-SHIPPED.md"`, one entry each.

The allowlist is written in its final form when each sentry lands and never grows: E1 lands the
engine list above; C1 lands the CLI list above. Adding a row needs a change to `HISTORY_ROOTS`, which
is a stop line (section 11).

### 4.5 Behaviour of `decoy explain storm`

Hard delete, no alias (pre-GA). It goes through the existing unknown-topic path: usage exit
(`EXIT_USAGE`, `src/decoy/cli/explain.py:23`) and the did-you-mean suggestion, which may suggest
`scan` by edit distance or nothing; the test pins only the exit and that the token is not echoed
back in a suggestion list.

## 5. Behaviour

| Surface | Before | After |
|---|---|---|
| `decoy explain` topic list | includes `storm` | includes `scan` in the same place |
| `decoy explain storm` | topic body | usage error, exit as any unknown topic |
| `decoy scan`, `scan fields/show/diff` help | "STORM ..." | "the scan ..."; flags and arguments unchanged |
| `decoy report integrity` | help names `JobStormReport`; table titled "Storm integrity" | "integrity report"; "Post-scan integrity"; `--json` unchanged |
| `decoy init <file>` scaffold | `# REVIEW: STORM detected ...` | `# REVIEW: The scan found ...`; strategies and YAML keys unchanged |
| `decoy demo` | "Scanning with STORM..." | "Scanning..." |
| `decoy-ci/v1` schema | `DriftCheck.description` names STORM | "Compare two saved scan JSON files with the `scan diff` categorizer."; `$id`, `schema_version` and validation unchanged |
| engine `reasons.find("route", <old code>)` | the tombstone | `None` |
| engine record naming an old code | decodes to the tombstone | decodes to `decoy.unknown_reason_from_future`, original identity in context |
| CLI SARIF rule-code allowlist | contains the two old codes | does not (after the repin) |

## 6. Failure modes

### 6.1 Class table

| # | Class | Structure that closes it | Proof | Mutation that turns it red |
|---|---|---|---|---|
| 1 | Value-bearing output | the reworded strings are fixed text; `init.py:378` keeps `type(exc).__name__` only; no new interpolation; the unknown-topic path echoes no user text beyond the topic word it already echoes; no CLI output renders a decoded reason's `original_identity` | AT-C2 renders the init and demo paths with a sentinel cell value and asserts the value is absent; AT-C7; existing `test_profile_raw_value_isolation.py` and `test_report_raw_value_isolation.py` stay green | interpolate `str(exc)` into the init failure line |
| 2 | Cleanup missing on an exit path | N/A: no file, lock or scratch state is added; the renamed progress module keeps its `with` block exactly | `tests/e2e/test_scan_progress.py` (renamed) keeps the Live-stop assertions | drop the `finally` in `scan_multistage` |
| 3 | State and concurrency | N/A: no shared state; the removal of two registry entries is import-time data | AT-E2, `reasons.check_integrity()` in AT-E4 | keep one entry in `__all__` without its declaration |
| 4 | Route parity and silent fallback | the two codes were never emitted on any route (`_pipeline_routing` and the output sink emit their replacements); a record naming one takes the existing tolerant-reader branch, never a silent default | AT-E3 (decodes to `unknown_reason_from_future` with the identity kept); engine route tests unchanged | make `parse_payload` return `None` for an unknown identity |
| 5 | Referential integrity | each tombstone's `replaced_by` link goes away with it; the remaining tombstone still links to a live identity | AT-E5 (moved chain test); `append_only_violations` replacement check | point the remaining tombstone at a deleted code |
| 6 | Untrusted producer | persisted reason records are untrusted input; `parse_payload` already validates identity shape before keeping it as context (`_SAFE_IDENTITY`) | AT-E3 with a malformed identity next to the removed one | drop the `_SAFE_IDENTITY` check |
| 7 | Check then use (TOCTOU) | N/A: no check-then-use; the release pin and the live catalog are read in one process by one command | AT-E4 | none applies |
| 8 | Weak tests and overclaimed evidence | sentries scan the real artifact (`git ls-files`); an undecodable text file fails instead of being skipped; the quote-split pattern catches the name rebuilt from pieces; seeds per surface; help, `explain`, AST strings and templates go through the existing banned-text sentry, and AT-C2 only adds the runtime outputs it cannot reach, found through the live command tree; the deleted engine test is named with its reason, and the one general check it held moves intact | AT-S1, AT-S2 seeds; reviewers rerun the 4.3 mutations | narrow the CLI sentry to `src/` only (the docs seed goes green); restore `continue` on `UnicodeDecodeError` (the Latin-1 seed goes green) |
| 9 | Behaviour-preserving refactor drift | renames are `git mv` plus import edits; the progress module keeps its frames; `api.scan` keeps its signature; `--json` shapes are pinned | `tests/e2e/release_freeze/test_json_shapes.py`, `tests/unit/test_api.py` signature tests, `tests/unit/test_cli_surface.py` green with `docs/cli-reference.md` regenerated | change a frame in `scan_progress.py` (the progress test goes red) |
| 10 | Frozen contract drift | reason registry: a recorded one-time exception, every carrier edited in E1, pin checks green; `decoy-ci/v1`: description only, validation projection pinned; explain topic name: pre-GA, CHANGELOG line | AT-E4, AT-C5, `shape-changelog` CI job | change a `type` keyword in the schema (AT-C5 red); delete a third registry identity (AT-E4 append-only red) |

### 6.2 Enumerations

#### Exit paths

| Path | Where | Result |
|---|---|---|
| `decoy explain storm` | unknown-topic branch, `src/decoy/cli/explain.py:23` (`EXIT_USAGE`) | usage exit, no topic body |
| `decoy init <file>` scan failure | `src/decoy/cli/init.py:378` | same exit code, reworded line |
| `decoy demo` scan step | `src/decoy/cli/demo.py:161` | unchanged exit, reworded progress line |
| engine record decode with a removed code | `src/decoy_engine/reasons/_record.py:398` | no raise; `decoy.unknown_reason_from_future` |

#### Routes

- Engine routing deciders: no change. Neither removed code is emitted by
  `execution/_pipeline_routing.py` or `execution/_chunked_output_sink.py` at `ddd014a5` (the source
  scan finds the token only in `src/decoy_engine/reasons/route/_retired.py:20` and `:27`).
- CLI: no route, no command added or removed; `decoy scan` keeps its default-command routing
  (`src/decoy/cli/scan.py:500`).

#### FK shapes

N/A: no key, foreign key, vault or relationship code is touched; the change is names, text and two
never-emitted registry entries.

#### Fields

- `decoy-ci/v1` `checks.drift[].description` annotation (`src/decoy/ci/contracts.py:519`): text only.
- Engine `PipelineConfig`: no field changes (the old config key was removed in 0.17.0).
- Engine `reasons.manifest()["entries"]`: two entries fewer; entry shape unchanged.

#### Output surfaces

- Help, usage and `explain` text: reworded (`src/decoy/cli/scan.py:137`, `src/decoy/cli/explain.py:177`).
- Rich cards and tables: "Post-scan integrity" title (`src/decoy/cli/report.py:2063`); scan card
  footnote (`src/decoy/cli/scanning/_multi.py:329`).
- `--json` success shapes and the error object: no key or type changes.
- Scaffolded YAML comments (`src/decoy/cli/_init_inference.py:75`).
- SARIF: the rule-code allowlist loses two codes after the repin (`src/decoy/ci/rule_codes.py:209`).
- Generated docs: `docs/cli-reference.md` regenerated; diagram node labels renamed.

## 7. Acceptance tests, red first

Engine (E1). Each is red on `ddd014a5` except where marked.

| Id | Test | Red on base | Place |
|---|---|---|---|
| AT-S1 | engine residual sentry: no token outside `HISTORY`, plain or quote-split; `_retired.py`, the f29 fixtures and the sentry itself are scanned; a token in `CHANGELOG.md` `[Unreleased]` or a `changelog.d/` fragment fails; a non-binary tracked file that does not decode fails; every `HISTORY` glob is under `HISTORY_ROOTS`; every `HISTORY_ROOTS` folder `docs/<x>/` has `"<x>/**"` in `docs/conf.py` `exclude_patterns` (read with `ast`, not imported) and a matching sdist `exclude` entry in `pyproject.toml` (read with `tomllib`); seeds per 4.3 | yes (the five non-history files; `records/**` not excluded; sdist excludes none) | `tests/sentry/test_no_residual_removed_surface.py` |
| AT-E2 | `reasons.find("route", code)` is `None` for both removed codes (built from `RETIRED_NAME`); no `reasons.manifest()` entry has the token in `code`, `summary`, `owner` or `symbol` | yes | `tests/unit/test_reason_registry.py` |
| AT-E3 | `ReasonRecord.parse_payload` on a 1.29.0 record naming each removed code returns `decoy.unknown_reason_from_future`, never raises, keeps `original_identity`; a malformed identity beside it is dropped | yes (today it resolves to the tombstone) | the same file |
| AT-E4 | `reason_release_pin.py --check` and `--release-ready` exit 0; `test_v1_manifest_is_append_only` and `reasons.check_integrity()` green against the edited fixtures; a rehearsal `stamp_release.py --version 0.28.0` in a throwaway worktree succeeds (not committed) | control | CLI of the scripts, `tests/unit/test_reason_release_pin.py` |
| AT-E5 | every tombstone links to a live end (moved unchanged from the deleted file) | control | `tests/unit/test_reason_tombstones.py` |

CLI (C1 to C3).

| Id | Test | Red on base | Slice | Place |
|---|---|---|---|---|
| AT-S2 | CLI residual sentry with `HISTORY` (4.4) and `PENDING`, plain and quote-split patterns, undecodable files fail; seeds per 4.3; roots test | yes without `PENDING`; green with `PENDING` at the C1 head | C1 (C1b and C2 lower `PENDING`, C3 deletes it) | `tests/sentry/release/test_retired_name_residual.py` |
| AT-C2 | runtime outputs the banned-text sentry cannot reach hold no token: scan and report-integrity output, human and `--json` (C1); init scaffold, demo and `decoy schema` with a sentinel cell value that must also be absent (C2) | yes (scan card footnote, "Storm integrity" title; then the scaffold) | C1, extended in C2; no `xfail` | `tests/sentry/cli_text/test_no_retired_name_in_output.py` |
| AT-C2b | `RETIRED_PATTERN` is in `BANNED_USER_TEXT`, so `test_user_text_internal_names.py` checks help, usage, `explain`, AST string constants and templates for it; its existing bite tests gain one case with the name in a help string | yes | C2 | `tests/sentry/cli_text/_banned_text.py`, `test_user_text_internal_names.py` |
| AT-C3 | `decoy explain scan` prints the moved body; `decoy explain storm` exits `EXIT_USAGE` and its stderr suggestion list does not contain the token | yes | C1 | `tests/e2e/test_explain_command.py` |
| AT-C4 | the installed engine's `reasons.manifest()` and `decoy.ci.rule_codes._engine_registry_codes()` hold no token | yes until the repin to the release with E1 | C3 | `tests/sentry/release/test_retired_name_residual.py` |
| AT-C5 | `decoy-ci/v1` validation projection: walk the schema and drop `description`, `title` and `examples` only where they are schema keywords (keys of a schema object); a key with one of those names under `properties`, `patternProperties`, `$defs` or `definitions` is a property or definition name and stays; dump as canonical JSON (sorted keys, no spaces); its SHA-256 equals the value the builder computes at the C2 merge base (`git merge-base origin/main HEAD`) and records in the test with that sha; `$id` and `schema_version` unchanged; the existing docstring-equals-schema check (`tests/unit/test_ci_manifest.py:282`) green | control (proves C2 changes annotation only) | C2 | `tests/unit/test_ci_manifest.py` |
| AT-C6 | every `decoy init <file>` `# REVIEW:` line for the 17 detector rows plus the fallback and multi-signal rows reads "The scan found ..." or its fallback text; the scaffold round-trips through `validate` | yes | C2 | `tests/unit/test_init_inference.py`, `tests/e2e/test_init_scaffold_roundtrip.py` |
| AT-C7 | no `src/decoy` file contains `original_identity`, so no CLI output renders the old pair from a decoded record | control (measured none at `307a189a`) | C1 | `tests/sentry/release/test_retired_name_residual.py` |

### 7b. Existing tests that change

- Engine `tests/unit/test_shipped_reason_identities.py`: deleted (4.2 item 4); its tag re-derivation
  needs the old literals and its purpose is withdrawn. Escalation trigger "moved or deleted tests":
  E1 takes a full suite on its merge head.
- Engine `tests/sentry/test_engine_string_targets.py`, `tests/sentry/_baseline_sources.py` and
  `tests/sentry/baselines/wave-b-string-target-exempt.json`: the `_REMOVED` row goes (4.2 item 8).
  The exempted negative test it named loses its token entries in the same change, so nothing that
  was exempt is now unguarded.
- Engine `tests/sentry/test_physical_seam_disconnection.py`: replace its local split spelling with
  the residual sentry's `RETIRED_NAME`; the exact-diff check keeps the same value and behaviour
  (4.2 item 11).
- CLI: the five `test_storm_*` files are renamed in C1b and their token-bearing names and
  docstrings edited (C1 edits only their imports of the renamed progress module);
  `test_explain_command.py:44`, `:78`, `:94` move from `storm` to `scan`; `test_release_smoke.py:207`
  topic list; `_banned_text.py` entries (4.3); comment-only edits in `test_s1_deletions.py`,
  `test_s4b_consolidation.py`, `test_no_dead_command_strings.py`, `test_surface_docs_consistency.py`,
  `test_csv_read_choke_point.py` and `tests/sentry/baselines/csv-read-allow.json` (the reason text of
  one entry; the baseline's keys are unchanged). No assertion is weakened: each edit replaces a
  token-bearing expected string with the new expected string.

## 7a. Reuse inventory

| Need | Reused | From |
|---|---|---|
| repo-wide token scan with allowlist and seeds | the engine sentry's `scan()`, `Allowed`, `SEEDS` shape | `tests/sentry/test_no_residual_removed_surface.py` |
| shrink-only migration list | the CLI ratchet convention | `tests/sentry/_ratchet.py`, the old plan's C0 |
| live command tree walk | `walk`, `visible_paths` | CLI `tests/command_tree.py` |
| tolerant decode of a removed code | `ReasonRecord.parse_payload` | engine `reasons/_record.py:370` |
| registry carrier checks | `reason_release_pin.py`, `append_only_violations`, `registry_renumber.py --check` | engine `scripts/` |
| sentry registration | `SENTRIES`, `scripts/dev/sentry_registry.toml` | CLI `tests/sentry/test_sentry_manifest.py` |
| CLI reference regeneration | `python -m typer decoy.__main__ utils docs ...` | CLI `tests/unit/test_cli_surface.py:5` |

## 8. Placement

| File | Directory | Map line that places it | Beside |
|---|---|---|---|
| `tests/sentry/release/test_retired_name_residual.py` (new) | `tests/sentry/release/` | CLI CODEMAP "Sentry test": "release-gate sentries in `tests/sentry/release/`" | `tests/sentry/release/test_frozen_surface_map.py` |
| `tests/sentry/cli_text/test_no_retired_name_in_output.py` (new; runtime outputs only, 4.3) | `tests/sentry/cli_text/` | CLI CODEMAP "User-facing CLI text and crash handling": new sentries go here | `test_user_text_internal_names.py`, whose `_banned_text.py` registry it reuses |
| `src/decoy/ui/scan_progress.py` (renamed) | `src/decoy/ui/` | CLI CODEMAP "Terminal output": `src/decoy/ui/<concern>.py` | `ui/progress.py`; no fan-out change |
| `tests/e2e/test_scan_*.py` (five renamed) | `tests/e2e/` | CLI CODEMAP "Command module": `tests/e2e/test_<command>*.py` | `test_scan_command.py`; renames, no new module in the flat folder |
| `tests/unit/test_reason_tombstones.py` (new) | engine `tests/unit/` | engine CODEMAP tests by area; reason tests sit flat in `tests/unit/` | `tests/unit/test_reason_registry.py` |
| `changelog.d/reason-tombstone-removal.md` (new fragment) | engine `changelog.d/` | engine `changelog.d/README.md` | other fragments |

No new production module in either repo. Engine production files touched: one.

## 9. Frozen contracts touched

| Contract | Map row | Change | Proof |
|---|---|---|---|
| Engine reason registry (contract 3.4) | engine `docs/frozen-surfaces.md` "Reason registry" | two tombstones removed under the Q1 exception; `REGISTRY_VERSION` unchanged; pin and v1 manifest edited in the same change; compatibility contract paragraph and `Breaking:` fragment | AT-E2 to AT-E5; `test_reason_registry.py`, `test_reason_baseline_frozen.py` (the baseline holds neither code, so it is unchanged), `test_reason_release_pin.py` |
| Engine public attributes `reasons.route.RUN_STORM`, `RUN_STORM_REQUESTED` | covered by the registry row | removed, pre-GA | AT-E2; no CLI reference (`git grep` at `307a189a`) |
| CLI `decoy-ci/v1` schema | CLI `docs/release/frozen-surfaces.md` "CI manifest" | `DriftCheck` description text only | AT-C5 |
| CLI command and flag set | "Command and flag set" | none; `docs/cli-reference.md` regenerated for help text | `tests/unit/test_cli_surface.py` |
| CLI `--json` success shapes and error object | "`--json` success shapes", "`--json` error object" | none | `tests/e2e/release_freeze/test_json_shapes.py`, `tests/unit/test_ui_emit_error.py` |
| CLI Python API `scan` | "Python API" | none (private alias only) | `tests/unit/test_api.py` signature tests |
| CLI `explain` topic names | not a frozen row (topics are arguments) | `storm` becomes `scan`, pre-GA; CHANGELOG `[Unreleased]` line | AT-C3 |
| CLI engine pin | `pyproject.toml:136`, `uv.lock` | the repin PR (not a slice) to the first engine release with E1 | the engine repin checklist; AT-C4 |

## 10. Slices

Sizes: changed lines (added plus deleted, tests and docs included) estimated from the measured hit
lines at the bases (two changed lines per hit line), measured file sizes for deleted files and the
new sentries, and a fixed allowance for each rewritten block. Each builder records `git diff
--numstat` against its base and stops past 800 or 10 production files.

| Slice | Repo | What | Production files | Changed lines (est.) | Risk | Depends on |
|---|---|---|---|---|---|---|
| E1 | engine | 4.2 items 1 to 11; sentry tightened to the final history list with the split pattern and the undecodable-file failure (AT-S1); AT-E2 to AT-E5 | 3 (`reasons/route/_retired.py`, `pyproject.toml` sdist exclude, `tests/sentry/test_physical_seam_disconnection.py`) | about 542: test file deleted 250, sentry 135, `test_reason_tombstones.py` 60, release pin 36, `_retired.py` 20, docs, fragment and `docs/conf.py` 22, string-target sentry and its two baselines 9, physical-seam sentry 2, `pyproject.toml` 6 | R2 | Q1 (approved) |
| C1 | CLI | AT-S2 sentry with final `HISTORY` and `PENDING`; AT-C7; AT-C2 for scan and report-integrity output; scan, scan subcommands, explain (topic move, extras line, topic list), report integrity text, `scanning/_multi.py`, `ui/storm_animation.py` to `ui/scan_progress.py`, `ui/progress.py` docstring, `api.py` alias; the import lines of the e2e files that use the renamed module; explain, report, scan, api, profile, first-user, release-smoke and raw-value test edits | 7 | about 470: prod 110, tests 80, sentry with `PENDING` 200, AT-C2 part one 60, AT-C7 20 | R1 | none (may go before E1) |
| C1b | CLI | the five `git mv` renames of 4.1 and their token-bearing test names, docstrings and strings (86 hit lines); `PENDING` lowered by five keys | 0 | about 180: renamed files 172, `PENDING` 10 | R1 | C1 |
| C2 | CLI | `_init_inference.py` review strings, `init.py`, `demo.py`; comment-only `compile_explain.py`, `completers.py`, `exit_codes.py`, `extras.py`; `ci/contracts.py` description with the regenerated `docs/schemas/decoy-ci-v1.schema.json` (AT-C5); `_banned_text.py` (pattern added, token `DEAD_STRINGS` and `storm-reframe` removed, AT-C2b); AT-C2 part two (init, demo, schema); init, demo, scaffold, template, exit-code and comment-only test edits; AT-C6; `PENDING` lowered | 8 | about 300: prod 90, schema 2, tests 60, banned-text 30, AT-C2 part two 30, AT-C5 30, AT-C6 30, `PENDING` 30 | R2 | C1b |
| C3 | CLI | comment-only `templates/__init__.py` and `ci/adapters.py`; CLI sdist `exclude` (4.4); docs: README, SECURITY, CODEMAP (also fixes the dead `storm.py` row), `.tours`, `docs/ci-contracts.md`, `docs/cli-reference.md` regenerated, diagram labels renamed in place (node ids and titles; layout unchanged since only the name changed), CHANGELOG `[Unreleased]` reworded plus one line for this wave, `docs/ROADMAP.md` non-row lines, living `docs/roadmap/` pages and `docs/qa/cli-v1-checklist.md`; `PENDING` deleted; AT-C4 | 3 (two comment-only modules, `pyproject.toml`) | about 290: docs 210, comment-only modules 4, `pyproject.toml` 10, sentry minus 30, AT-C4 30, CHANGELOG line 5 | R1 | C2 and the CLI repin to the engine release with E1 |

Order: E1 (engine) merges, the next engine release carries it, the CLI repins to that release
(its own PR on the engine repin checklist), then C3. C1, C1b and C2 do not wait: they share no file
with E1, do not read the engine registry, and their tests pass on the current pin, so they run in
parallel with E1 and may merge first. Inside the CLI they go in order C1, C1b, C2, C3, because each
lowers `PENDING` in the one sentry file and C1b's renamed files import the module C1 renames. Only C3 needs the repin, because AT-C4 reads the installed
engine and the CLI's SARIF allowlist is derived from it.

Test depth: T0 per edit, T1 impact-selected per commit, T2 at each gate on the exact head. Full
suite triggers: E1 (deleted test file; frozen reason registry; sdist contents, so the packaging
gate too), C1b (moved tests), C2 (frozen `decoy-ci/v1` contract). C1 and C3 take T1 plus the
sentry set; C3 also builds the CLI sdist and checks the excluded folders are absent. No tests run on the devbox (Mac first, then the VM pool).

Review: E1 and C2 get two independent reviewers in sequence (Dennis, then Codex); C1, C1b and C3
get Codex only.

## 11. Stop lines for builders

- A `HISTORY_ROOTS` or `HISTORY` change, in any slice: stop and ask.
- A `PENDING` key added or a count raised: stop.
- Allowed baseline shrinks, E1 only: the `_REMOVED` entry of `test_engine_string_targets.py`
  `EXEMPT`, the `("_REMOVED",)` masks argument in `tests/sentry/_baseline_sources.py:227`, and the
  `<removed-surface>` entry in `tests/sentry/baselines/wave-b-string-target-exempt.json:11`. Any
  other baseline or allowlist edit in E1: stop. In C2, the banned-text registry changes only as 4.3
  says (one pattern in, nine token entries out).
- A `src/decoy` change that renders `original_identity`, or a request to drop AT-C7: stop and ask.
- A sdist exclude that removes anything outside the history folders, or touches the engine wheel
  force-include: stop.
- Any change to engine `REGISTRY_VERSION`, a minor fixture, `consumer-contract.json` or
  `reason-baseline.json`: stop. E1 edits only `reason-manifest-v1.json` and `reason-registry-release.json`.
- `registry_renumber.py --check` printing anything beyond the two expected `deleted-existing` lines: stop.
- A `--json` shape snapshot or `decoy-ci/v1` validation change: stop (the change is text only).
- Renaming a verb, flag or `--json` key: out of scope, stop.
- Rewriting a file under a `HISTORY` glob: not needed, do not.
- A slice past 800 changed lines or 10 production files: stop and split along the table above.
  The splits are already named: the e2e renames are C1b; the two comment-only modules are in C3.

## 12. Owner decisions (all answered 2026-11-16, go-with-recommended)

- Q1, decided yes. The one-time pre-GA exception to the reason registry's append-only rule:
  hard-delete `route.run_storm` and `route.run_storm_requested`; a record naming either decodes as
  `decoy.unknown_reason_from_future`; `REGISTRY_VERSION` does not move for it. The residual risks in
  the exception record (4.2) are part of what was approved.
- Q2, decided yes. Release gate B-3 owns decoy-web (87 occurrences in 21 files at `5137913`,
  including the marketing component `storm.tsx` and the vendored CLI reference): B-3 copies the
  CLI residual sentry shape into decoy-web, re-syncs the vendored `cli-reference.md` after C3, and
  closes before V1.
- Q11, decided version B. No engine code for the parked platform; row 16 drops
  `config.post_scan_owned_by_platform`.

## 13. V2-LOG and follow-ups

- The substring check would flag an unrelated word that contains the token ("brainstorm"); none
  exists in either repo today. If one is needed later, reword it; the sentry does not get a word list.
- `docs/RECENTLY-SHIPPED.md` and `docs/roadmap/decisions.md` are whole-file history; a new entry could
  carry the token without failing. Both are internal; the residual risk is accepted.
- The diagrams keep their old layout until the next routine `scripts/build_docs.py` run.
- Add a rendered library-view test for a decoded pre-release run-result record. AT-C7 is only a
  source-text proxy because the library decode path can re-emit `original_identity` without naming
  it in CLI source. This is V2-LOG because only engine 0.15.1 and 0.16.0 wrote the affected records,
  before any CLI release or the library store.
- Retire `claude/storm-split-cli` and `claude/eager-clarke-14deh1` per the branch register after C3
  (normal branch hygiene; deleting a remote branch stays an owner call).

## 14. Pre-mortem

- The next engine release stamp refuses the hand-edited pin. Caught in E1 by the rehearsal stamp in
  AT-E4, not at release time.
- Another engine branch edits `reason-manifest-v1.json` or the release pin at the same time. The
  branch rules forbid both edits outside release prep, so a conflict means a rule break; rebase E1.
- C1 or C2 conflicts with another V1 row in `scan.py`, `report.py`, `init.py` or `explain.py`.
  Text-only edits; rebase, rerun T1, re-measure `PENDING`.
- The CLI repin to the E1 release slips, so C3 waits and V1 notes still carry the token. C3 is the
  only slice gated on it; track it on row 56.
- A builder adds a second matcher for the name in the runtime-output test. 4.3 says it reuses the
  banned-text registry; Codex checks the import at C1 and C2.
- Someone later adds a CLI renderer for reason context and the old pair from a stored record
  reaches a user. AT-C7 fails first and the decision goes back to review.
- An engine branch forked before E1 fails its registry checks on the two codes. Expected; it
  rebases (4.2 residual risks).
- decoy-web is forgotten and a V1 user meets the name on the public site. B-3 owns it (Q2 decided).

## 15. Verification status

Planning only. Measured at the bases with `git grep` and `git show`; no test run, no build. The
size estimates are not measured diffs. Revision 2 re-read `docs/conf.py`, both `pyproject.toml`
sdist sections, `tests/sentry/test_engine_string_targets.py`, `_baseline_sources.py`, the
string-target baseline, `_banned_text.py`, `run_result/_model.py` and the CLI sources for
`original_identity` (none) at the same bases.

## 16. Roadmap row text (for the orchestrator; this plan does not edit `docs/ROADMAP.md`)

The rows must not spell the token, since `docs/ROADMAP.md` is not history; refer to this plan by its
commit on engine branch `plan/` (the branch name holds the token, so cite the commit sha).

- Row 16 (engine half): "Retired product name, engine half (E1): hard-delete the two retired route
  tombstones from the reason registry under a one-time pre-GA exception (owner Q1, approved),
  tighten the engine residual sentry to history paths only (split-literal and undecodable-file
  checks included), keep the history folders out of the docs site and the sdist. Registry version
  unchanged. Drops the parked platform's `config.post_scan_owned_by_platform` (Q11 version B).
  Ships in the next engine release after merge. | engine | NOT STARTED; plan at engine `<plan sha>`
  (revision 2) | none |".
- Row 56 (CLI half): "Retired product name, CLI half (C1, C1b, C2, C3): residual sentry, runtime
  output test and the name added to the banned-text registry; scan, explain and report text and
  the progress module renamed (C1); five scan test files renamed (C1b); init and demo text and the
  `decoy-ci/v1` description (C2); docs, the V1 notes, the sdist history exclude and two comment-only
  modules (C3). C1 to C2 can merge before the engine half; C3 needs the CLI repin to the engine
  release carrying row 16. | CLI | NOT STARTED; plan at engine `<plan sha>` (revision 2) | row 16
  release and repin (C3 only) |".

`<plan sha>` is the revision 2 commit on the plan branch; the orchestrator fills it in.

## 17. Revision map

Revision 3 answers Dennis r2 (GO-WITH-FIXES, 0 V1, 2 V2-LOG).

| Finding | Fix | Where |
|---|---|---|
| V2-LOG: `SPLIT_PATTERN` catches the local split spelling in the physical-seam sentry | E1 imports the residual sentry's `RETIRED_NAME` there; the file is included in the changed-file count and size | 4.2 item 11, 7b, 10 |
| V2-LOG: AT-C7 is a source-text proxy and misses the library decode path | 4.3 names the proxy limit and why it is V2-LOG; the rendered library-view test is logged for follow-up | 4.3, 13 |

Revision 2 answers Dennis r1 (GO-WITH-FIXES, 0 HIGH, 4 MEDIUM, 4 LOW) and records the owner calls.

| Finding | Fix | Where |
|---|---|---|
| 1 MEDIUM: `test_engine_string_targets.py` raises at collection once the dotted token goes | E1 deletes `_REMOVED`, its `EXEMPT` row, the masks argument and the baseline entry; listed as the only allowed baseline shrinks | 4.2 item 8, 7b, 11 |
| 2 MEDIUM: Sphinx publishes `docs/records/**` | E1 adds `"records/**"` to `exclude_patterns` and turns the two published links into path text; AT-S1 asserts every `HISTORY_ROOTS` folder is excluded; 1.1 corrected | 1.1, 1.2, 4.2 item 9, 4.4, 7 AT-S1 |
| 3 MEDIUM: a second scanner beside the banned-text registry | the name goes into `BANNED_USER_TEXT` (C2, AT-C2b); AT-C2 shrinks to runtime outputs, reuses the walker and the registry patterns; the C1 `xfail` is gone | 4.3, 6.1 row 8, 7, 10, 14 |
| 4 MEDIUM: split literals and undecodable files | `SPLIT_PATTERN` with a quote required, the sentry module its only exemption; non-binary undecodable files fail; seeds and mutations for both | 4.3, 6.1 row 8, 7 AT-S1 and AT-S2 |
| 5 LOW: AT-C5 base and keyword stripping | SHA captured at the C2 merge base; keywords stripped only at schema-object positions, never under `properties` and the other name maps | 7 AT-C5 |
| 6 LOW: two catalogs at 1.29.0, stale-since on old branches, `original_identity` | all three are in the exception record and Guarantee 4; decision: the engine keeps `original_identity` as a diagnostic, the CLI never renders it (measured none today), pinned by AT-C7 in C1 | 1.2, 2, 4.2, 4.3, 7, 11, 14 |
| 7 LOW: name the splits | C1b holds the five e2e renames; `templates/__init__.py` and `ci/adapters.py` move to C3 | 4.1, 10, 11 |
| 8 LOW: sdists ship `docs/` history | excluded, one line each: engine `docs/plans`, `records`, `archive`, `decisions` in E1; the CLI history folders and two logs in C3; AT-S1 checks the engine side | 1.1, 1.2, 4.2 item 10, 4.4, 7, 10 |
| Owner calls | Q1 yes, Q2 yes (B-3 owns decoy-web), Q11 B, recorded as decided | header, 1.3, 12 |
| Row text | rows 16 and 56 updated for C1b, the moved modules, the docs-site and sdist work | 16 |
