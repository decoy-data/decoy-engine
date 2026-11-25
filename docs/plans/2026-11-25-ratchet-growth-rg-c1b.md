# RG-C1b: CLI numeric bounds in the ratchet

Status: plan

Rules consulted: dev-rules README routing, 00-universal, risk-and-exceptions, development-loop
(PLAN), testing (test depth), workspace-and-vcs (commit messages), reuse-first,
catalogs/recurring-defects; owner notes on the V1 threat model and plan-defines-acceptance-tests.

Row: RATCHET-GROWTH. Parent plan: engine `docs/plans/2026-11-24-postmask-fail-closed-and-ratchet-growth.md`
(section "RG-C1b"), owner decisions Q1 to Q7 of 2026-11-24. Work lands in the CLI repo.

Risk: R2 (test tooling). Size: 1.5 days. Copied from the engine with CLI edits: about 480
helper lines (`_bindings.py`, `_bounds.py`, `_limit_constants.py`) and about 500 test lines from
engine `ratchet/test_bounds.py`. New logic: about +30 `_ratchet.py`, +20 `_baseline_sources.py`,
+10 TOML, one baseline, about +120 CLI-only tests. Depends on RG-C1a merged on CLI main and on RG-E2
(engine PR #801) merged on engine main. Anchor: CLI main `d6b9e4c7`, engine #801 head
`f15adce3f`. The builder re-anchors on both merge commits first.

## Problem

A CLI sentry can loosen by editing one constant. The cap and floor values live in Python
(`tests/sentry/layout/test_module_size.py:19` `LIMIT = 800`,
`tests/sentry/layout/test_package_fanout.py:20` `LIMIT = 25`,
`tests/sentry/release/test_retired_name_residual.py:270` `MANIFEST_FLOOR = 1400`,
`tests/sentry/release/test_tag_census.py:16` `FLOOR = 7`), no baseline records them, and the
registry mirror compares keys only (`tests/sentry/test_baseline_registry.py:121-125`). The CLI
checker also has no floor fields, no guard ids and no exact-key growth approval for a raised max.

## Guarantee

After this slice, raising a CLI cap or lowering a CLI floor fails the ratchet unless a fresh,
exact-key `approved_growth` row with a dated owner decision is added in the same diff. This is
the RG-E2 behavior, with CLI sources. A module-level integer under `tests/sentry` is either a
listed bound or listed as not a bound with a reason.

Non-goals:

- No change to the existing ceiling fields or the moved-field rule
  (`tests/sentry/_ratchet.py:48-49,175-194`).
- No new caps and no lowered caps. Recorded values equal today's values.
- Engine-only source tests stay in RG-E2.

## What exists (reuse, do not rebuild)

- Engine RG-E2 (#801): `tests/sentry/ratchet/_limit_constants.py` (261 lines, `LIMITS`,
  `NOT_A_BOUND`, `direction_problems`), `_bindings.py` (31), `_bounds.py` (186, file-free:
  `loosened_fields`, the successor exception and `[retired_growth]` rules at `:114-133`),
  `live_bounds` in `tests/sentry/_baseline_sources.py:95-108` (the one source reader, used by the
  registry mirror; the checker does not call it, `_ratchet.py:544-546`), and in
  `tests/sentry/_ratchet.py` `GUARD_KEYS` (line 51), the strict baseline read (`:232-238`),
  `parse_retired_growth` (177), the added-field rule (`:184-193`), the floor comparison through `loosened_findings` (`:544-546`) and
  the guard handling in `_check` (463-557). Tests in `tests/sentry/ratchet/test_bounds.py`
  (512 lines), `test_baseline_types.py` and `test_reader_guard.py` (which forbids file reads in
  `_bounds.py`, `:32-36`).
- CLI after RG-C1a: `tests/sentry/ratchet/` with `_integrity.py` (mirror) and `_base_run.py`
  (vendored), the `[retired]` tables, `--with-base`.
- CLI `_baseline_sources.py:99-105` `READERS` and `KINDS` (`:31`). CLI `test_baseline_registry.py`
  `CREATED_IN` is at `:43`; the mirror reader returns a set of keys (`:123-125`).
- Engine `test_baseline_registry.py:248-253,267-274` rejects tuple unpacking at module level
  (`SURFACE, SOURCE, OWNER, TEST = range(4)`, CLI `release/test_frozen_surface_map.py:25`).
  Engine `_limit_constants.py:12` imports `_bindings`.

## Design

1. Helpers in CLI `tests/sentry/ratchet/`:
   - `_bindings.py`: vendored byte for byte if the diff shows no engine path; else a mirror.
   - `_bounds.py`: a declared `[[mirror]]` in `ci/vendored.toml`, not a byte copy. The one CLI
     change: `CEILING_FIELDS = ("max", "count", "sites")`, so one comparison
     (`loosened_fields`) covers the existing CLI ceilings and the new floor. The port keeps the
     engine added-field rule (`_ratchet.py:184-193`): a field present on one side only is read
     with `.get`, never by index, so a `count` raise gives a finding, not a KeyError, and a
     `count` drop next to an added `max` is still compared. The CLI diagnostic text at
     `test_ratchet_check.py:413,442,464` is kept. Every ceiling and floor field is a non-bool
     int on both sides (`count: true`, `"3"` and `3.0` are findings). The header names the
     differences. It stays file-free, as in the engine.
   - `_limit_constants.py`: a mirror. Same `AnnAssign` and bool rules, same `DIRECTIONS`,
     CLI `LIMITS` and `NOT_A_BOUND` tables, and the engine's exception for vendored fixtures
     (engine `tests/sentry/test_baseline_registry.py:211-238`).
   - Update the ledger pins in CLI `tests/sentry/test_ci_lock_installs.py:501-507` (vendored
     paths and the mirror count) on the RG-C1a base.
   - Add `_bounds`, `_bindings` and `_limit_constants` to `CHECKER_HELPERS` in CLI `_ratchet.py`,
     so the RG-E3 base run treats an edit to them as a checker edit (on the C1a merge base).
2. CLI `LIMITS` (each row names the comparison line, checked by the builder on CLI main):

   | File | Constant | Direction |
   |---|---|---|
   | `layout/test_module_size.py` | `LIMIT` | max |
   | `layout/test_package_fanout.py` | `LIMIT` | max |
   | `layout/test_run_package_shape.py` | `MAX_LINES`, `MAX_RUN_STATEMENTS` | max |
   | `_ratchet.py` | `MIN_REASON` | min |
   | `release/test_retired_name_residual.py` | `MANIFEST_FLOOR` | min |
   | `release/test_tag_census.py` | `FLOOR` | min |
   | `cli_text/test_exit_code_docs.py` | `MIN_CODES` (uses `:54,79`) | min |

   `NOT_A_BOUND`, each with a reason: `ci_scan/_identity.py` `TRIES`,
   `cli_text/_error_sites.py` `FINGERPRINT_CHARS`, `test_mask_secret_ref_shape.py`
   `CANARY_INT`, `test_report_raw_value_isolation.py` `_NUMERIC_SENTINEL`,
   `test_engine_internal_boundary.py` `_MAX_ALIAS_ROUNDS` (the scan fails closed past it),
   `release/test_qa_checklist_shape.py` `EXPECTED_CHECKS`, `EXPECTED_GROUPS` (exact-equality
   pins), `io_policy/test_private_files.py` `LAUNCHER_MODE` (`0o755`, an equality pin at
   `:115,541`). Tuple bindings the reader refuses (`ci_scan/test_identity.py:20`,
   `release/test_frozen_surface_map.py:25`, column indices) are rewritten as plain assignments
   (`SURFACE = 0` and so on), so the engine rule stays unchanged and the census reads them as
   `NOT_A_BOUND` rows with a reason. A test asserts a later rebind of such a name still fails.
   The census must pass on CLI main with them, not only report them. If the builder finds a constant compared with `<`, `<=`, `>` or `>=` that this
   table calls not a bound, it moves to `LIMITS`; the census decides, not this list.
3. `tests/sentry/_ratchet.py` (+30): replace the CLI `max_raised` ceiling check
   (`:170-194`) with the one `_bounds.loosened_fields` comparison for surviving and successor
   keys, so `max`, `count`, `sites` and `min` follow one rule. Keep the new-ceiling-beside-an-
   old-one rule. Add `GUARD_KEYS = frozenset({"sentry-limits"})`, the strict baseline read
   (port of engine `_ratchet.py:232-238`: an int field that is a bool, a string or a float is a
   finding on head and on base), the exact-key fresh approval for a raised max or lowered min,
   and guard retirement: one fresh `[retired]` decision for the id plus a fresh
   `[retired_growth]` row for each lost key without a qualifying successor. Freshness compares
   both approval locations against base (engine `_ratchet.py:476-477,554-560`). A base
   approval does not excuse a raise (`:312-317`, kept).
4. `sentry-limits` baseline `tests/sentry/baselines/sentry-limits.json` with `created_in`,
   one entry per `LIMITS` row holding `max` or `min`, each with a substantive `reason`
   (`_ratchet.py:143-151`). The exact field check of parent lines 799-802: each entry has exactly
   `max` or exactly `min` plus `reason`; a missing field, an extra field, the wrong direction
   for its `LIMITS` row, a non-integer and `800.0` are findings. It reuses
   `test_baseline_registry.py:336-357`. Registry row with `kind = "from_scan"`, placed before `lint-debt`
   (`tests/sentry/test_lint_debt.py:53-57` copies the registry tail). Reader
   `live_bounds` in CLI `_baseline_sources.py` (+20), the one source reader, as in #801.
5. `tests/sentry/test_baseline_registry.py`: add `sentry-limits` to `CREATED_IN`
   (`:43`, used at `:103-107`) and extend `test_recomputed_keys_match_the_registered_baseline` (`:121-125`).
   For the numeric reader it also compares each live key's value to the recorded `max` or
   `min`; a source-only change in either direction fails. Lowering a recorded floor in JSON
   still needs an approval in the checker.
6. CHANGELOG entry, net-zero in length (CLI CHANGELOG is 876 lines). CODEMAP "Sentry test" row: name `sentry-limits` and the helpers.

Choke points: `_baseline_sources.live_bounds` is the one reader of source values (used by the
mirror); `_bounds.loosened_fields` is the one comparison of base and head JSON (used by the
checker). Guard: `test_cli_mirror_rejects_constant_only_loosening` and the ported
`test_bound_loosened_reads_both_directions`. Mutation: the mirror compares keys only (today's
code); the first guard fails.

Design notes: no new pattern. RG-E2 already set the structure (one `LIMITS` map, one reader,
one guard baseline); the CLI takes the same files through the vendoring ledger.

### Placement

| New or changed | Path | CODEMAP rule (`CODEMAP.md:73`) | Sits beside |
|---|---|---|---|
| Bound helpers | `tests/sentry/ratchet/_bindings.py`, `_bounds.py`, `_limit_constants.py` | `tests/sentry/<group>/` helper `_<name>.py`, vendored or mirrored in `ci/vendored.toml` | RG-C1a helpers |
| Bound tests | `tests/sentry/ratchet/test_bounds.py`, `test_limit_census.py` | `tests/sentry/<group>/test_<rule>.py` | |
| Baseline | `tests/sentry/baselines/sentry-limits.json` | `tests/sentry/baselines/` | `module-size.json` |
| Checker, sources, registry | `tests/sentry/_ratchet.py`, `tests/sentry/_baseline_sources.py`, `scripts/dev/sentry_registry.toml` | existing files | |

## Behavior and failure modes

| Change on a CLI branch | Expected |
|---|---|
| `LIMIT = 801` in `test_module_size.py`, baseline untouched | Mirror fails, naming the key |
| Same raise plus baseline `max` raised, no fresh approval | Ratchet fails |
| Same raise, baseline raised, fresh exact-key approval in the diff | Pass |
| Approval already on base, reused for a new raise | Fail (pin) |
| Reworded base approval | Fail (pin) |
| `FLOOR = 6` in `test_tag_census.py`, JSON untouched | Mirror fails |
| `FLOOR = 6` and JSON `min` lowered, no fresh approval | Ratchet fails |
| A floor raised in source only | Mirror fails (record the new value) |
| A floor raised in source and JSON | Pass |
| `count` or `sites` raised on an existing baseline | Fail, as on main |
| A `sentry-limits` key removed | Fail without approval |
| A key added to `sentry-limits` | Pass (a new guard tightens) |
| Whole `sentry-limits` id retired | Fail unless a fresh `[retired]` decision and a fresh `[retired_growth]` row per lost key |
| JSON `max: true`, `"800"` or `800.0`, on head or on base | Fail, non-integer |
| JSON `count: true`, `"3"` or `3.0` on an existing baseline | Fail, non-integer |
| `count` raised on one side with `max` added | Finding, no KeyError |
| `sentry-limits` entry with an extra field or the wrong direction | Fail |
| Rebind of a former tuple index name | Census fails |
| `FLOOR - 1` used at the comparison site, declaration untouched | Consumer boundary test fails |
| A new module-level int under `tests/sentry` in neither table | Census test fails |

## Acceptance tests (red first)

Tags: `red-before` fails on CLI main on its assertion; `pin` passes on main.

Ported from engine `test_bounds.py` and `test_baseline_types.py`, on CLI temp repos with valid
CLI rows (each row carries `kind`, per RG-C1a). Classify each ported test on CLI main as one of:
red-before (assertion fails on main), pin (passes on main, for example
`test_limit_raise_without_approval_fails`, already enforced at `_ratchet.py:312-317`), or
post-change (needs a helper main does not have; not red evidence). Port: both PRs of
`test_fresh_guard_deletion_passes_then_merged_approval_is_not_stale`, each seeded on its own
so the first failure cannot hide the second; `test_retired_guard_requires_every_lost_key_approval`;
`test_read_int_handles_annassign_and_refuses_bool`; `test_bound_loosened_reads_both_directions`;
the guard successor cases; the head and base stored-type cases of
`test_baseline_types.py:42-68`. Engine-only source cases (log interpolation, locator waivers,
faker floors) are not ported. The builder lists each name with its class and its red run.

CLI-only:

1. `test_cli_mirror_rejects_constant_only_loosening` (red-before): call the existing mirror
   function directly (`test_baseline_registry.py:121-125`) with a seeded numeric reader and a
   matching baseline, so it runs on main; the main reader returns a set of keys
   (`:123-125`), so the seeded reader returns a set too. Raise only `layout/test_module_size.py` `LIMIT`;
   then lower only `release/test_tag_census.py` `FLOOR`; then raise only that `FLOOR`. Keys and
   JSON stay byte-identical. Assert the exact diagnostic names the key. Main's key-only mirror
   accepts all three.
2. `test_every_cli_module_int_is_a_bound_or_named` (post-change: it imports `_limit_constants`,
   which main lacks): census of module-level ints under `tests/sentry`; each is in `LIMITS` or
   `NOT_A_BOUND`.
3. `test_live_sentry_limits_match_the_constants` (post-change: needs the new baseline): the
   live reader equals the baseline for every row.
4. `test_module_size_ceiling_raise_needs_approval` (pin): `baselines/module-size.json:4-8`
   records the max and the checker rejects the raise (`tests/sentry/_ratchet.py:312-317`).
5. `test_reworded_base_approval_does_not_exempt_a_raise` (pin).
6. `test_tag_census_floor_is_enforced_at_its_use` (post-change): a scratch copy of
   `release/test_tag_census.py` with the consumer at `:19-22` changed to `FLOOR - 1` must fail
   the consumer check. Use sites are recorded per `LIMITS` row, including the delegation at
   `layout/test_module_size.py:42`, `layout/test_package_fanout.py:54-55` and `MIN_CODES` at
   `cli_text/test_exit_code_docs.py:54,79`. The interpolation in an f-string at
   `layout/test_run_package_shape.py:105-108,157-158` is not a use site (a fixture case asserts
   that). Engine `_limit_constants.py:238-247` ignores same-file uses; the CLI mirror adds this
   case.
8. `test_count_field_strict_and_added_field_rule` (red-before on its assertion: main accepts
   `count: true`): bool, string and float `count` and `sites` on head and base; a `count` raise
   with `max` added gives a finding.
9. `test_sentry_limits_entry_fields_are_exact` (post-change): missing, extra, wrong direction,
   non-integer, `800.0`.
10. `test_former_tuple_index_rebind_fails` (post-change).
7. `test_ceiling_and_floor_share_one_comparison` (post-change): `count`, `sites` and a new
   ceiling beside an old one stay refused (CLI `tests/sentry/test_ratchet_check.py:402,432,454`
   kept unchanged and green).

Mutations (final head):

| ID | Mutation | Test that must fail |
|---|---|---|
| B1 | Mirror compares keys only | 1 |
| B2 | Drop `FLOOR_FIELDS` from `loosened_fields` | ported `test_bound_loosened_reads_both_directions` (engine `test_bounds.py:400-407`) |
| B3a | Source reader accepts bool | ported `test_read_int_handles_annassign_and_refuses_bool` |
| B3b | Strict baseline read accepts JSON `true` | ported `test_baseline_types.py` head and base cases |
| B4 | Drop `"sentry-limits"` from `GUARD_KEYS` | ported removed-key test |
| B5 | Drop one `LIMITS` row, JSON fixed | 2 and 3 (complete key-set compare) |
| B6 | Accept a base approval for a fresh raise | ported base-approval pin goes red |
| B7 | Drop `count` from CLI `CEILING_FIELDS` | `test_ratchet_check.py:402` |
| B8 | Ignore use sites in the census | 6 |
| B9 | Index the base field directly (`base[f]`) | 8 (KeyError, not a finding) |
| B10 | Accept bool in `count` | 8 |
| B11 | Drop the exact field check | 9 |
| B12 | Allow tuple unpacking at module level | 10 |
| B13 | Leave `_bounds` out of `CHECKER_HELPERS` | ported RG-E3 eligibility test with a `_bounds.py` edit |

## Enumerations

### Exit paths

- `ratchet_check.py`: exit 1 on any finding (`scripts/dev/ratchet_check.py:53-55`), now also
  for loosened bounds, stray or stale approvals and retired guards; exit 2 when no merge base
  is found (`:40-48`, unchanged).
- Registry mirror test: assertion failure naming the key and field
  (`tests/sentry/test_baseline_registry.py:121-125`).
- Census test: assertion failure naming file and constant.

### Routes

- Gate sentry step (`scripts/dev/gates.sh:269`): on CLI main it runs the checker without
  `--with-base`; RG-C1a adds the flag on the branch label. Pytest then runs mirror and census.
- PR CI "Baselines only shrink" (`.github/workflows/ci.yml:283-285`): `--base <PR base sha>`,
  `--with-base` after RG-C1a. The mirror and census run in the combined
  "pytest unit + sentry" step (`ci.yml:121-122`).
- Direct harness tests in `tests/sentry/ratchet/`.

### FK shapes

N/A. Repo files only; no keyed data.

### Fields

| Field | Where | Rule |
|---|---|---|
| `max`, `count`, `sites` | ceiling fields (`tests/sentry/_ratchet.py:49`) | unchanged |
| `min` | new floor field | may only rise without approval |
| `approved_growth[].key` | registry row | exact key, fresh in the diff |
| `approved_growth[].decision` | registry row | dated owner decision (`release_identity.py:58`) |
| `[retired].<id>` growth rows | registry | needed for each lost guard key |

### Output surfaces

- `ratchet_check.py` report lines: sentry id, key, field, counts, paths and the approved
  decision text (`_ratchet.py:293-305`). All are repo facts; no user data.
- Mirror and census assertion messages: file, constant and key names only. No values from
  scanned data; the integers printed are the bounds themselves.

## Defect classes

| # | Class | Closing structure | Test | Mutation |
|---|---|---|---|---|
| 1 | Value-bearing output | Findings name ids, keys and fields | test 1 exact diagnostic | Print the parsed baseline: exact-match assertion fails |
| 2 | Cleanup on an exit path | N/A: no temp state beyond pytest `tmp_path`; the base run cleanup is RG-C1a's | RG-C1a tests | N/A |
| 3 | Shared state | `LIMITS` is a constant; the reader caches nothing across calls | test 3 edits a source between two reads | Cache the reader: second read stale |
| 4 | Route parity | Checker and mirror both read through `live_bounds` | tests 1 and 3 | B1, keys only |
| 5 | Referential integrity | Every `LIMITS` row names a real file and constant; census closes the set | test 2 | B5, drop a row |
| 6 | Untrusted producer | N/A for V1: repo files under review (accidental-only threat model) | none | N/A |
| 7 | Check-then-use (toctou) | Bounds read once per run from one tree; base side from the one resolved sha (RG-C1a) | ported unreachable-base pin | Resolve twice: review finding |
| 8 | Weak tests | Pins never used as red evidence; seeded mirror fixture makes test 1 collect on main | builder report | B6, base approval accepted |
| 9 | Refactor drift | `max_raised` folded into `loosened_fields`; `move_findings` unchanged; existing tests unchanged | `tests/sentry/test_ratchet_check.py:402,432,454` | B7, drop `count` |
| 10 | Frozen contract drift | N/A: test tooling only; no CLI surface changes | release-freeze sentries | N/A |

### Recurring defect catalog (11 classes)

| # | Class | Result |
|---|---|---|
| 1 | Anchored validation | Decisions through `is_dated_owner_decision`; keys compared exactly, no prefix match |
| 2 | Strict wire types | `max` and `min` must be `int` and not `bool`, in source (B3a) and in stored JSON on head and base (B3b) |
| 3 | No exception context | Read errors become findings |
| 4 | Versioned read models | A base without `sentry-limits` is a fresh guard; tested |
| 5 | Normalized guard scanners | Constants read with `ast`, `AnnAssign` and signed literals included |
| 6 | Private modules | Helpers load by path |
| 7 | No hidden CI failures | No skip added; census fails on unknown ints |
| 8 | One input, one trust class | N/A: repo files only |
| 9 | Mutations on the final head | B1 to B13 after the last change |
| 10 | Allowlisted helpers still checked | `NOT_A_BOUND` rows need a reason and are re-read by the census |
| 11 | No raised caps | Recorded values equal today's; this slice is the guard against raised caps |

## Reuse inventory

- Engine `_bindings.py`, `_bounds.py`, `_limit_constants.py`, `test_bounds.py` cases.
- CLI `_ratchet.py` ceiling logic, `_baseline_sources.READERS`, `test_baseline_registry.py`
  mirror assertion, RG-C1a `tests/sentry/ratchet/` group and vendoring ledger.

## Frozen contracts

None. Test tooling only.

## Slices

One slice, one CLI PR: `feat(sentry): record CLI caps and floors in the ratchet`.
Test depth: T0 the CLI ratchet tests; T1 impact selection. Triggers: test tooling, so one full
CLI suite at merge with `gates.sh --full --baseline-file <stored main baseline>`. No module-size
baseline change: CLI `layout/test_module_size.py:3-6,19-20` excludes tests.

## Pre-mortem

- The census finds more bounds than the table above. Expected: the census decides; each extra
  row is recorded at today's value.
- `_bounds.py` holds engine paths and cannot be vendored. Then it is a declared mirror and the
  header names each difference.
- The mirror test passes on main because no numeric reader is registered there. The seeded
  reader in the fixture makes it collect and run on main; the builder shows the red run.
- A constant is shadowed or lowered inside the consumer test. Ported engine consumer cases
  cover it.

## Builder brief items

- Commit messages: Conventional Commits subject, 72 characters or fewer, last line `cam`, no
  trailers, file lists or test counts.
- Test depth as in "Slices"; use `~/bin/pytest-one`.
- Never raise a recorded bound to make a test pass. Never write owner decision rows.
- New tests go in `tests/sentry/ratchet/`; `test_baseline_registry.py` gets only the
  `CREATED_IN` row and the extended mirror assertion.
- Red-before tests run red on CLI main first; pins are not red evidence.
- `ruff check`, `ruff format --check`, `mypy` before each commit. CHANGELOG entry before merge,
  net-zero in length.
