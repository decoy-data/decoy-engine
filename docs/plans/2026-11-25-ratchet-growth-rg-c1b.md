# RG-C1b: CLI numeric bounds in the ratchet

Status: plan

Rules consulted: dev-rules README routing, 00-universal, risk-and-exceptions, development-loop
(PLAN), testing (test depth), workspace-and-vcs (commit messages), reuse-first,
catalogs/recurring-defects; owner notes on the V1 threat model and plan-defines-acceptance-tests.

Row: RATCHET-GROWTH. Parent plan: engine `docs/plans/2026-11-24-postmask-fail-closed-and-ratchet-growth.md`
(section "RG-C1b"), owner decisions Q1 to Q7 of 2026-11-24. Work lands in the CLI repo.

Risk: R2 (test tooling). Size: one day (about +20 `_ratchet.py`, +60 helpers, +15 sources,
+8 TOML, one new baseline, +200 tests). Depends on RG-C1a merged on CLI main and on RG-E2
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
  `NOT_A_BOUND`, `direction_problems`), `_bindings.py` (31), `_bounds.py` (186, `live_bounds`,
  guard successor rules), and in `tests/sentry/_ratchet.py` `GUARD_KEYS` (line 51),
  `bound_loosened` (274), `parse_retired_growth` (177) and the guard handling in `_check`
  (463-557). Tests in `tests/sentry/ratchet/test_bounds.py` and `test_reader_guard.py`.
- CLI after RG-C1a: `tests/sentry/ratchet/` with `_integrity.py` (mirror) and `_base_run.py`
  (vendored), the `[retired]` tables, `--with-base`.
- CLI `_baseline_sources.py:99-105` `READERS` and `KINDS` (`:31`).

## Design

1. Helpers in CLI `tests/sentry/ratchet/`:
   - `_bindings.py` and `_bounds.py`: vendored byte for byte when the engine files take no
     engine path; otherwise a declared `[[mirror]]` in `ci/vendored.toml` whose header lists
     each difference. The builder diffs first and picks one; no silent fork.
   - `_limit_constants.py`: a mirror. Same `AnnAssign` and bool rules, same `DIRECTIONS`,
     CLI `LIMITS` and `NOT_A_BOUND` tables.
2. CLI `LIMITS` (each row names the comparison line, checked by the builder on CLI main):

   | File | Constant | Direction |
   |---|---|---|
   | `layout/test_module_size.py` | `LIMIT` | max |
   | `layout/test_package_fanout.py` | `LIMIT` | max |
   | `layout/test_run_package_shape.py` | `MAX_LINES`, `MAX_RUN_STATEMENTS` | max |
   | `_ratchet.py` | `MIN_REASON` | min |
   | `release/test_retired_name_residual.py` | `MANIFEST_FLOOR` | min |
   | `release/test_tag_census.py` | `FLOOR` | min |
   | `cli_text/test_exit_code_docs.py` | `MIN_CODES` | min |

   `NOT_A_BOUND`, each with a reason: `ci_scan/_identity.py` `TRIES`,
   `cli_text/_error_sites.py` `FINGERPRINT_CHARS`, `test_mask_secret_ref_shape.py`
   `CANARY_INT`, `test_report_raw_value_isolation.py` `_NUMERIC_SENTINEL`,
   `test_engine_internal_boundary.py` `_MAX_ALIAS_ROUNDS` (the scan fails closed past it),
   `release/test_qa_checklist_shape.py` `EXPECTED_CHECKS`, `EXPECTED_GROUPS` (exact-equality
   pins). If the builder finds a constant compared with `<`, `<=`, `>` or `>=` that this
   table calls not a bound, it moves to `LIMITS`; the census decides, not this list.
3. `tests/sentry/_ratchet.py` (+20): `FLOOR_FIELDS = ("min",)` beside `CEILING_FIELDS`,
   `GUARD_KEYS = frozenset({"sentry-limits"})`, `bound_loosened` for both directions, and the
   exact-key fresh approval for a raised max. A base approval does not excuse a raise
   (`tests/sentry/_ratchet.py:312-317` already rejects it; kept).
4. `sentry-limits` baseline `tests/sentry/baselines/sentry-limits.json` with `created_in`,
   one entry per `LIMITS` row holding `max` or `min`. Registry row with `kind = "from_scan"`
   (+8 TOML). Reader in `READERS` returning the live values through `_bounds.live_bounds`
   (+15).
5. `tests/sentry/test_baseline_registry.py`: extend `test_recomputed_keys_match_the_registered_baseline`
   at its existing assertion. Keys stay equal; for the numeric reader also compare each live
   key's field and integer value to the recorded `max` or `min`. Reject missing, extra,
   wrong-direction and non-integer bounds, bool included. No new test in that file (416 lines).
6. CHANGELOG entry. CODEMAP "Sentry test" row: name `sentry-limits` and the helpers.

Choke point: `_bounds.live_bounds` is the one reader of bound values; the registry mirror and
the checker both read through it. Guard: `test_cli_mirror_rejects_constant_only_loosening`.
Mutation: have the mirror compare keys only (today's code); the guard fails.

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
| `FLOOR = 6` in `test_tag_census.py` | Mirror fails; ratchet fails without approval |
| A floor raised | Pass |
| A `sentry-limits` key removed | Fail without approval |
| A key added to `sentry-limits` | Pass (a new guard tightens) |
| Whole `sentry-limits` id retired | Fail unless every lost key has a `[retired]` approval |
| `max = true` or `max = "800"` | Fail, non-integer |
| A new module-level int under `tests/sentry` in neither table | Census test fails |

## Acceptance tests (red first)

Tags: `red-before` fails on CLI main on its assertion; `pin` passes on main.

Ported from engine `test_bounds.py`, run on CLI temp repos with CLI sources: every red-before
case, including both PRs of `test_fresh_guard_deletion_passes_then_merged_approval_is_not_stale`,
the whole-id case `test_retired_guard_requires_every_lost_key_approval`,
`test_read_int_handles_annassign_and_refuses_bool`, `test_bound_loosened_reads_both_directions`
and the guard successor cases. Engine-only source cases (log interpolation, locator waivers,
faker floors) are not ported. The builder lists each ported name with its red result.

CLI-only:

1. `test_cli_mirror_rejects_constant_only_loosening` (red-before): in a scratch tree install
   the numeric reader and a matching baseline; seed a reader in the existing mirror fixture
   on main so the test collects on main and runs its key comparison. Run the mirror before
   and after raising only `layout/test_module_size.py` `LIMIT`; repeat with only
   `release/test_tag_census.py` `FLOOR` lowered. Keys and JSON stay byte-identical. Assert the
   mirror names the key. Main's key-only mirror accepts both.
2. `test_every_cli_module_int_is_a_bound_or_named` (red-before): census of module-level ints
   under `tests/sentry`; each is in `LIMITS` or `NOT_A_BOUND`.
3. `test_live_sentry_limits_match_the_constants` (red-before): the live reader equals the
   baseline for every row.
4. `test_module_size_ceiling_raise_needs_approval` (pin): `baselines/module-size.json:4-8`
   records the max and the checker rejects the raise (`tests/sentry/_ratchet.py:312-317`).
5. `test_reworded_base_approval_does_not_exempt_a_raise` (pin).

Mutations (final head):

| ID | Mutation | Test that must fail |
|---|---|---|
| B1 | Mirror compares keys only | 1 |
| B2 | Drop `FLOOR_FIELDS` from `bound_loosened` | ported floor test, 1 (floor half) |
| B3 | Accept bool as an integer | ported `test_read_int_handles_annassign_and_refuses_bool` |
| B4 | Drop `"sentry-limits"` from `GUARD_KEYS` | ported removed-key test |
| B5 | Drop one `LIMITS` row | 2 and 3 |
| B6 | Accept a base approval for a fresh raise | ported base-approval pin goes red |

## Enumerations

### Exit paths

- `ratchet_check.py`: exit 1 on any finding (`scripts/dev/ratchet_check.py:53-55`), now also
  for loosened bounds, stray or stale approvals and retired guards.
- Registry mirror test: assertion failure naming the key and field
  (`tests/sentry/test_baseline_registry.py:121-125`).
- Census test: assertion failure naming file and constant.

### Routes

- Gate sentry step (`scripts/dev/gates.sh:269`) runs `ratchet_check.py --with-base` and then
  pytest, which runs the mirror and census.
- PR CI "Baselines only shrink" (`.github/workflows/ci.yml:283-285`) runs the checker; the
  sentry pytest job runs the mirror and census.
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

- `ratchet_check.py` report lines: sentry id, key and field only.
- Mirror and census assertion messages: file, constant and key names only. No values from
  scanned data; the integers printed are the bounds themselves.

## Defect classes

| # | Class | Closing structure | Test | Mutation |
|---|---|---|---|---|
| 1 | Value-bearing output | Findings name ids, keys and fields | test 1 message assertion | Print the parsed baseline: assertion fails |
| 2 | Cleanup on an exit path | N/A: no temp state beyond pytest `tmp_path`; the base run cleanup is RG-C1a's | RG-C1a tests | N/A |
| 3 | Shared state | `LIMITS` is a constant; the reader caches nothing across calls | test 3 runs twice | B5, drop a row |
| 4 | Route parity | Checker and mirror both read through `live_bounds` | tests 1 and 3 | B1, keys only |
| 5 | Referential integrity | Every `LIMITS` row names a real file and constant; census closes the set | test 2 | B5, drop a row |
| 6 | Untrusted producer | N/A for V1: repo files under review (accidental-only threat model) | none | N/A |
| 7 | Check-then-use (toctou) | Bounds read once per run from one tree; base side from the one resolved sha (RG-C1a) | ported unreachable-base pin | Resolve twice: review finding |
| 8 | Weak tests | Pins never used as red evidence; seeded mirror fixture makes test 1 collect on main | builder report | B6, base approval accepted |
| 9 | Refactor drift | `max_raised` and `move_findings` unchanged; their tests unchanged | `tests/sentry/test_ratchet_check.py` | N/A |
| 10 | Frozen contract drift | N/A: test tooling only; no CLI surface changes | release-freeze sentries | N/A |

### Recurring defect catalog (11 classes)

| # | Class | Result |
|---|---|---|
| 1 | Anchored validation | Decisions through `is_dated_owner_decision`; keys compared exactly, no prefix match |
| 2 | Strict wire types | `max` and `min` must be `int` and not `bool` (B3) |
| 3 | No exception context | Read errors become findings |
| 4 | Versioned read models | A base without `sentry-limits` is a fresh guard; tested |
| 5 | Normalized guard scanners | Constants read with `ast`, `AnnAssign` and signed literals included |
| 6 | Private modules | Helpers load by path |
| 7 | No hidden CI failures | No skip added; census fails on unknown ints |
| 8 | One input, one trust class | N/A: repo files only |
| 9 | Mutations on the final head | B1 to B6 after the last change |
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
CLI suite at merge with `gates.sh --full`, diffed against the stored main baseline.

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
- New tests go in `tests/sentry/ratchet/`; `test_baseline_registry.py` gets only the one
  extended assertion.
- Red-before tests run red on CLI main first; pins are not red evidence.
- `ruff check`, `ruff format --check`, `mypy` before each commit. CHANGELOG entry before merge.
