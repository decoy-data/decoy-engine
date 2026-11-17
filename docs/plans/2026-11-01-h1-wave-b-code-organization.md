# H-1 Wave B: code organization plan (engine and CLI slices, roadmap rows 46 to 54)

Status: plan, revision 4.2 (re-anchor plus Codex fixes D13 to D15; plan only, no production code, no moves). Risk R2.
Repo and branch: decoy-engine `plan/h1-wave-b` (this file). It also plans the CLI slices C0 and C3, which build in decoy (CLI).
Date: 2026-11-17. Author: Opus plan author. Review: Codex reviews the "Re-anchor deltas" section only; the design it changes was GO'd on revision 3.
Moved from: decoy-platform `P:plan/h1-wave-b` `944fb295` (revision 3, Codex GO, measured 2026-11-01). Every roadmap row this plan serves (46 to 54) targets engine or CLI files. The platform clusters (P0 to P11) and the web list stay in the platform copy, which is parked with the platform (owner 2026-11-05: CLI V1 first). The platform copy gets a one-line pointer to this file.
Baselines: engine `origin/main` `bb993f398` (2026-11-17); CLI `origin/main` `5fa4cb26` (2026-11-17). Every line count, line number and claim below was read on these heads. Line counts are newline counts (`wc -l`), the convention of both size sentries.
Rules consulted: `/home/cam/dev-rules/00-universal.md`, `risk-and-exceptions.md`, `cross-cutting-concerns.md`, `api-and-compatibility.md`, `testing.md` (test depth T0 to T4), `workspace-and-vcs.md` (commit messages); engine `CODEMAP.md` "Where Things Go" (`CODEMAP.md:237`); CLI `CODEMAP.md` "Where Things Go"; the engine size sentry `tests/sentry/test_module_size.py` (goal 600, max 700); the CLI size sentry `tests/sentry/layout/test_module_size.py` (limit 800); the engine ratchet `tests/sentry/_ratchet.py` and `scripts/dev/ratchet_check.py`; the package fan-out sentry `tests/sentry/layout/test_package_fanout.py`; owner standing rules "develop correctly" (central registry, about 800-line files, cohesive dirs) and "V1 pragmatic gates".

## Re-anchor deltas (revision 4 against revision 3 `944fb295`)

Codex: this section is the whole review surface. Everything below it is revision 3's GO'd design re-measured, plus these changes.

| # | Delta | Why (evidence on today's heads) | Where |
|---|---|---|---|
| D1 | Plan moved from platform to engine `plan/h1-wave-b`; scope cut to engine and CLI slices (rows 46 to 54). Platform P0 to P11 and the web list are dropped from this copy | The platform is parked; no row 46 to 54 touches a platform file | header |
| D2 | Slices already done are dropped: E0 (engine #372 to #375), E3 (#386), E5 (#381), E1.1 (`detection/_scoring.py`, landed by #468 on 2026-11-10; its module docstring says "split from detectors.py (H-1 E1.1)"), E6a (`generation/_synthesize_derived.py`, #419, 2026-11-09; `synthesize.py` is 593 lines, no census entry) | `git log` on each file; the five targets are under 600 or gone from the census (`tests/sentry/test_module_size.py:91` to `:157`) | section 2 |
| D3 | Row 47 (C1, `distribution/installer.py`) is dropped: the file is 731 lines and the CLI limit is now 800 with no dense band (LAYOUT C2, `tests/sentry/layout/test_module_size.py:18`). A split would serve no limit | CLI size sentry; owner rule "files about 800 lines" | section 5 |
| D4 | Row 46 (C0) is cut to the pure-move checker port only. The CLI size census exists already (FILE-SIZE, CLI #199) | `tests/sentry/layout/test_module_size.py` on CLI main | section 5 |
| D5 | Row 53 (C3) is re-listed on today's counts: only `cli/report.py` 2305, `cli/scan.py` 1037, `cli/preflight.py` 859 and `cli/fit.py` 818 are over 800. `run()` is done (RUN-SPLIT, CLI #179). `validate.py`, `tokenize.py`, `explain.py`, `init.py` and `api.py` are under 800 and leave the list | CLI line counts on `5fa4cb26` | section 5 |
| D6 | E0r is redesigned. Revision 3 made `tests/fixtures/f29/producer-inventory.json` an exact regeneration of the live scan. Since #379 (2026-11-04, after the GO) the ratchet derives the `f29-producer-inventory` and `f29-consumer-inventory` baselines from that file's keys and refuses any added key (`tests/sentry/_baseline_sources.py:137` to `:146`). The live scan has 1493 sites; the file has 1387, of which 1176 name no live site. Exact regeneration would add about 1280 keys, which the ratchet refuses. New E0r: prune the rows that name no live site (a shrink, which the ratchet allows), refresh the drifted non-key fields of the rest, and land revision 3's second guard (`test_every_row_is_its_ast_site`) so a row cannot go stale again. The exact-regeneration guard is withdrawn. The file's own contract (`tests/sentry/_reason_baseline.py:6`: "may only shrink as producers migrate") is what E0r enforces | measured on `2e1108a0d` with the repo's own `_reason_baseline.build()` under system CPython, no test run | E0r |
| D7 | New slice E0m: the ratchet learns to accept a key that a pure move re-homes, when the slice's committed move manifest proves the move. Without it E2 cannot land: moving `check_statistical_columns` re-keys rows in three ratchet baselines (`f29-producer-inventory`, `f29-consumer-inventory`, `table-kind-truth-tests`), and `REHOME_BY_BINDING` (`tests/sentry/_ratchet.py:40`) covers only two other sentries | `tests/sentry/_ratchet.py:35`, `:40`; baselines on main | E0m |
| D8 | E2's three new modules go in `plan/checks/`, not beside `_checks.py`. The `plan/` package is frozen at 30 modules (`tests/sentry/layout/test_package_fanout.py:40`) and CODEMAP says new checks go in `plan/checks/` (`CODEMAP.md:254`). Names: `plan/checks/_statistical_columns.py`, `plan/checks/_ner_available.py`, `plan/checks/_fpe_checksum.py`. Split points and contents are unchanged | fan-out sentry, CODEMAP | E2 |
| D9 | E1.2 also rewrites the three production importers that still read `_scoring` names through `detectors` (`profiling/profiler.py:19`, `profiling/sentinels.py:30`, `verification/postmask/_column_facts.py:31`). E1.1 landed with a re-export, which rule 1.2 (no shims) forbids. E1.2's touched set grows from 3 to 5 files | `detectors.py:58` to `:71` (`# noqa: F401 re-exported constants`) | E1 |
| D10 | Gates re-measured. A-4 (#361) and F06 (#338) merged, so every revision 3 WAIT on them clears. New claims come from open PRs: PROP EF0 #617 (`detectors.py`, `text_mask.py`, `_compile.py`); GEN-REL and GEN-INHERIT #523, #546, #555, #557, #561, #596 (`plan/_checks.py`, `generators/columns.py`, `test_table_kind_classifier.py`); #645 and #655 (`producer-inventory.json`). The STORM CLI half (row 56) still gates C3 | `gh pr list --state open` and `git diff origin/main...<head>` on 2026-11-17 | section 3 |
| D11 | Added for plan-lint and the current plan format: Placement table, Ratchets touched line, class table, enumerations, reuse inventory | plan format | sections 6 to 11 |
| D13 | Codex NO-GO round 1 on `810442380`, V1: E0r's replacement count came from the pruned fixture, so it proved nothing, and removed rows were not proven dead. Fix: (a) a stdlib-only site finder, `tests/sentry/_ast_site.py`, independent of the scanner, proves every pruned row has no live site before the prune writes, and again on every run through a committed `pruned-rows.json`; (b) `test_every_producer_resolves` moves to the live scan and counts code entries (literal codes plus resolved registry constants), checked against a fixed floor in `tests/sentry/baselines/f29-resolved-entries.json` (1353 on `2e1108a0d`) that the ratchet lets only rise. Measured: the fixture's 1306 coded rows hold 1327 code entries, but the live tree has 0 literal code entries (every producer now uses a registry constant), so a fixture-based floor would be 0 after the prune | measured on `2e1108a0d` with `build()`; Codex `h1b` | E0r steps 1, 4, 5, 7 |
| D15 | Codex NO-GO round 2 on `f58718228`, V1: the resolver in E0r step 5 did not cover the scanner's finite registry tables, whose constants are dicts. Fix: step 5 defines resolution for each `registry` shape (chain rooted at `reasons`, other name or attribute, finite table) and how each counts toward the floor; measured with that algorithm: 1353 of 1353 sites resolve, 2 of them tables. V2-LOG fixed: output surfaces name the two new artifacts | Codex `h1b2`; measured on `2e1108a0d` | E0r step 5; Output surfaces |
| D14 | Codex NO-GO round 1, DESIGN: E0m trusted the manifest without running the pure-move checker in the ratchet. Fix: condition 6 runs `check_move` (`scripts/check_pure_move.py:210`) inside `_ratchet.py`; one function, `manifest_rehomes()`, is the only acceptance path, guarded by an AST test; new test and mutation: a manifest that meets conditions 1 to 5 but fails the checker is refused | Codex `h1b` | E0m |
| D12 | Row 49's E6b stays dropped (revision 3: an import cycle, not a move). `native/_dispatch.py` is now 677 (ceiling 688) and `native/_requirements.py` 657 (ceiling 677); both stay dense, owner question Q7 | `tests/sentry/test_module_size.py:118`, `:126` | E6 |

Proposed roadmap bookkeeping (for the coordinator; this plan does not edit the roadmap): row 48 DONE (E1.1, #468); row 49 DONE (E6a #419; E6b dropped by revision 3); row 47 CLOSED as not needed (D3); rows 46, 50, 51, 52 re-planned here; row 53 still waits on row 56; row 54 per file. The roadmap's plan link moves to `E:docs/plans/2026-11-01-h1-wave-b-code-organization.md` on `E:plan/h1-wave-b`.

## 1. Rules this plan is built on (revision 3, unchanged)

### 1.1 Behavior-preserving, defined

A move is behavior-preserving when each item holds before and after, proven by a named test that is red on a seeded violation before the move:

1. Public import surface byte-identical (`decoy_engine.__all__`, pinned by `tests/unit/test_public_api.py`; package `__all__` where the slice names one).
2. The F29 reason registry unchanged: no identity added, removed or re-homed; `reason-baseline.json` byte-identical (`tests/sentry/test_reason_baseline_frozen.py`).
3. Every string that names a moved module (`patch("...")`, `monkeypatch.setattr("...")`, `importlib.import_module("...")`) resolves after the move (engine `tests/sentry/test_engine_string_targets.py`).
4. The touched tests equal main by test id: the same collected set and the same pass, fail and skip sets.

Defect classes used below: (1) value; (2) cleanup; (3) state; (4) route parity; (5) referential integrity; (6) untrusted producer; (7) check then use; (8) weak tests; (9) refactor drift; (10) frozen contract drift.

### 1.2 Re-export policy

A moved definition lives in exactly one module. No shim stays at the old path. Importers are rewritten to the defining module in the same PR. Patch and monkeypatch strings are rewritten to the defining module, never served by a re-export (class 8: a patch on an alias does not patch the call site).

### 1.3 How a pure move is proven

The engine checker is on main: `scripts/check_pure_move.py` (249 lines) and `scripts/check_pure_move_scope.py` (214), with `tests/unit/test_check_pure_move.py`. Each slice commits a manifest `docs/plans/h1-wave-b/manifests/<slice>.json` (`old`, `new` in execution order, `map`, `importers`, `docstring_prose`, `tests`, optional `frozen_partners`; `scripts/check_pure_move.py:31`). The rules (ordered statement sequence, closed import map, owners, execution order and cycles, importers, the 10-file bound) are revision 3's and are not restated. Existing manifests: `e3.json`, `e5.json`.

### 1.4 Slice bounds

A slice is one PR for one cluster. Its touched set (moved-from file, new files, every production file whose import or string target changes, and listed non-test frozen partners) is at most 10 production files. Tests, fixtures, docs and census edits do not count toward 10 and do count toward at most 800 changed lines besides the pure move.

### 1.5 Ceilings

Limits only go down. A pure move deletes or lowers census entries; no slice raises one. A new module enters a census only if it is over the goal, at its exact count.

## 2. What is done, and what is left

| Row | Slice | State on today's heads | This plan |
|---|---|---|---|
| 43 to 45 | E0, E5, E3 | merged (#372 to #375, #381, #386) | n/a |
| 46 | C0 | CLI size census exists (FILE-SIZE C3, CLI #199); no CLI pure-move checker | C0 cut to the checker port (D4) |
| 47 | C1 `installer.py` | 731 lines, under the CLI limit 800 | dropped (D3) |
| 48 | E1.1 | `detection/_scoring.py` on main (#468) | done; its re-export residue goes into E1.2 (D9) |
| 49 | E6a, E6b | E6a merged (#419); E6b dropped in revision 3 | done (D12) |
| 50 | E0r | not started; the fixture has drifted further (D6) | redesigned (D6) |
| 51 | E1.2, E1.3 | `detectors.py` 920, legacy entry 920 | re-anchored, below |
| 52 | E2, E4 | `plan/_checks.py` 696 (dense ceiling 700); `transforms/text_mask.py` 650 (dense ceiling 670) | re-anchored; E2 placement changed (D8); E0m added (D7) |
| 53 | C3 | four CLI files over 800 | re-listed (D5) |
| 54 | E7 | 15 engine files over 600 with no slice | re-measured, below |

## 3. Live-branch claims (method unchanged from revision 3, inputs re-measured)

A branch claims a file when the file is in `git diff --name-only $(git merge-base origin/main B) B` and B's version still differs from `origin/main`. Revision 4 counts open PRs only (`gh pr list --state open`, engine 27 open, CLI 13 open on 2026-11-17). PRs untouched since October (engine #313, #333, #335, #337; CLI #68, F26 parked) are listed, not counted, and are re-checked the day a slice opens.

| File | Open-PR claims |
|---|---|
| `detection/detectors.py` | #617 (PROP EF0) |
| `profiling/profiler.py`, `profiling/sentinels.py`, `verification/postmask/_column_facts.py`, `profiling/features/builder.py`, `providers_v2/identifiers/_iban.py`, `_icd10.py`, `validation/post/_checks/_composite_coherence.py` | none |
| `plan/_checks.py` | #555, #557, #561, #596 (GEN-REL E3a, E3b, GEN-INHERIT E2, E1; remote-owned) |
| `plan/_compile.py` | #617 |
| `plan/_generation.py` | none counted |
| `transforms/text_mask.py` | #617 |
| `tests/sentry/test_table_kind_classifier.py` | #523, #546, #555, #557, #561, #596 |
| `tests/fixtures/f29/producer-inventory.json` | #645, #655 |
| `tests/sentry/_ratchet.py`, `scripts/dev/ratchet_check.py`, `tests/sentry/_reason_baseline.py`, `tests/unit/test_reason_registry.py` | none |
| CLI `cli/report.py` | #301 (SCANML C2a), #312 (PROP CS1a) |
| CLI `cli/preflight.py` | #312 |
| CLI `cli/scan.py`, `cli/fit.py` | none counted |

## 4. Engine slices

Frozen partners that move with any engine move (revision 3, re-checked): the size census `tests/sentry/test_module_size.py` and its ratchet baseline `tests/sentry/baselines/module-size.json`; `tests/sentry/test_physical_seam_disconnection.py` path lists; `tests/sentry/test_reason_registry.py::ADAPTERS` keys; `tests/fixtures/f29/producer-inventory.json` (after E0r, its rows are AST-checked); `tests/sentry/test_table_kind_classifier.py::TRUTH_TEST_BASELINE`; the strict mypy module list in `pyproject.toml` and `tests/sentry/test_mypy_override_targets.py`; ruff per-file ignores; `CODEMAP.md` paths (`tests/sentry/test_package_map_paths.py`).

### E0m. Ratchet re-home by move manifest (new, D7; R2; claim-free)

Behavior. `tests/sentry/_ratchet.py` gains `REHOME_BY_MANIFEST`, a frozenset of sentry ids whose keys start with a source path: `f29-producer-inventory`, `f29-consumer-inventory`, `table-kind-truth-tests`. A key K that is in head and not in base passes only when all hold:

1. A manifest under `docs/plans/h1-wave-b/manifests/` is added or changed between base and head, and lists `old` = O and N in `new`, with N not equal to O.
2. K starts with N's src-relative path, and the key K' made by replacing that path with O is in base and not in head (lost).
3. For a key with a function part (`<file>::<function>::...`), the function's top-level name is in the manifest `map` and assigned to N.
4. The key count of the sentry does not grow. For a sentry with `max` values (`table-kind-truth-tests`), the head maxes of O and N together are at most the base max of O, and N's entry carries `moved_from: <K'>`.
5. Each lost key is claimed once.

6. The pure-move checker passes on that manifest, run inside the ratchet (D14). `_ratchet.py` loads `scripts/check_pure_move.py` by path (as `scripts/dev/ratchet_check.py:24` loads `_ratchet.py`) and calls `check_move(manifest, read_base, read_head, production_files)` (`scripts/check_pure_move.py:210`) with readers over `git show <base>:` and `git show HEAD:`. Any problem it returns refuses every re-home that manifest would allow, and the checker's lines are printed as ratchet findings. A `ValueError` from a malformed manifest refuses too.

Conditions 1 to 6 are checked in one function, `manifest_rehomes()`, the only code in `_ratchet.py` that names `REHOME_BY_MANIFEST`. So no ratchet path, `ratchet_check.py` or a direct call of `_ratchet.check()`, can accept a manifest re-home without the checker passing. Any other added key fails as today. The gate prints one review line per re-homed key. This follows the existing `REHOME_BY_BINDING` rule (`tests/sentry/_ratchet.py:40`, `rehomes` at `:227`), which proves a re-home by AST inside the ratchet; here the proof is the manifest plus the checker, both run inside the ratchet.

Touched set: `tests/sentry/_ratchet.py`, one new test file. No production file. `scripts/dev/ratchet_check.py` only loads `_ratchet.py` and is unchanged; `scripts/check_pure_move.py` is called, not changed.

Tests, red first (`tests/sentry/test_ratchet_rehome_manifest.py`, using scratch git repos like the existing ratchet tests):
- `::test_manifest_move_rehomes_keys`: a scratch move of one function from O to N with its manifest; three baselines re-keyed; passes.
- `::test_rehome_without_manifest_fails` (seeded: same tree, manifest deleted).
- `::test_rehome_to_unlisted_file_fails` (seeded: N not in `new`).
- `::test_rehome_of_unmoved_function_fails` (seeded: a key for a function not in `map`).
- `::test_rehome_that_grows_count_fails` (seeded: O keeps its max and N adds 1).
- `::test_double_claim_fails` (seeded: two new keys claim one lost key).
- `::test_rehome_with_impure_manifest_fails` (D14, seeded): a manifest that meets conditions 1 to 5, but the moved function's body differs by one constant between base O and head N, so `check_move` reports a rule-1 problem; the re-home is refused and the checker line is printed.
- `::test_manifest_rehome_has_one_acceptance_path` (D14, AST over `_ratchet.py`): `REHOME_BY_MANIFEST` is referenced only in `manifest_rehomes`, `check()` reaches manifest re-homes only through it, and `manifest_rehomes` calls `check_move` on every path that returns a non-empty acceptance set.

Named mutations: drop condition 3 (the unmoved-function test goes red); drop condition 4's max sum (the count test goes red); accept any manifest in the tree instead of one changed in the diff (a stale-manifest case goes red); skip the `check_move` call, so a manifest that meets conditions 1 to 5 but fails the checker is accepted (the impure-manifest test and the one-path test go red).

### E0r. F29 producer inventory: prune to live sites and guard each row (redesigned, D6; R2)

Measured on engine `2e1108a0d` (`git diff --stat 2e1108a0d bb993f398 -- tests/fixtures/f29 tests/sentry` is empty) by running `tests/sentry/_reason_baseline.py::build()` on an exported tree under system CPython 3.13 (no test run):

- Live scan: 1493 sites, 114 consumers. Fixture: 1387 sites (1217 distinct keys), 51 consumers.
- 1176 fixture rows have no live site with the same `(file, function, kind, expr)` key. Most are literal-code rows whose producer moved to a registry constant (top files: `validation_result.py` 91, `execution/physical/_reasons.py` 44, `execution/native/_route_decline_codes.py` 30).
- Of the 211 rows that match, `line` drifted in 189 and `codes` and `value_class` in 137.
- 1 of 51 consumer rows names no live consumer.

Also measured (D13): the fixture's 1306 coded rows hold 1327 code entries. The live scan has 0 literal code entries: its 1493 sites are 1353 `registry` (a registry constant such as `reasons.plan.DEDUPE_UNSUPPORTED_TYPE`), 88 `forward`, 39 `dynamic` and 13 `none`. The 211 rows the prune keeps carry 0 code entries once refreshed (137 of them are `registry`). So after the prune, `tests/unit/test_reason_registry.py::test_every_producer_resolves` (`:126`), which reads the fixture and counts only literal codes, would check 0 entries.

The slice (no production code; touched set: `tests/sentry/_reason_baseline.py`, `tests/sentry/_ratchet.py`, the fixture, the two baselines, one new baseline, one new helper, one test file, `tests/unit/test_reason_registry.py`):

1. Independent site finder. New `tests/sentry/_ast_site.py`: given `(file, function, line, expr)`, it parses `src/decoy_engine/<file>` with `ast`, walks the qualified name, and returns the nodes in that definition whose `ast.unparse` (cut at the scanner's 100 characters) equals `expr`. It imports only the standard library; `::test_ast_site_imports_only_stdlib` fails if it imports `_reason_scan`, `_reason_baseline` or any `decoy_engine` module. So the scanner that chose the rows is never the thing that proves them.
2. Red first: `tests/sentry/test_reason_inventory_paths.py::test_every_row_is_its_ast_site`, built on `_ast_site`. For every site row: `src/decoy_engine/<file>` exists; `function` names a definition reached by the qualified-name walk, or `<module>`; `line` lies inside that definition; a node starting on `line` unparses to `expr`; `kind` and `value_class` are in closed sets the test holds; `family` equals the callee or target chain of that node; each member of `codes` is a string literal in that node, or `codes` is empty and `value_class` is not `literal`. The same walk runs over `consumers`. It is red on today's fixture (1176 site rows and 1 consumer row fail).
3. Seeded fixture mutants under `tests/fixtures/f29/mutants/`, each red on its own through `::test_guard_rejects_each_seeded_mutant`: one `line` off by one; one `expr` edited; one `codes` emptied while `value_class` stays `literal`; one `function` renamed; one `file` renamed.
4. Repair with a dead-row proof (D13). `_reason_baseline.py` gains `--prune-inventory`. It selects the rows whose key the live scan does not yield, then proves each one dead with `_ast_site`: the named file is gone, or the named definition is gone, or no node in it unparses to the row's `expr`. If any selected row still has a site, the tool writes nothing and lists the rows (a scanner miss to fix first). For the kept rows it rewrites the non-key fields (`line`, `codes`, `value_class`, `family`) from the live row. It never adds a row. The removed rows, with the base commit, are committed as `tests/fixtures/f29/pruned-rows.json`, and `::test_pruned_rows_have_no_live_site` checks every one with `_ast_site` on every run, so a removed row whose site returns fails. `--write` and its refusal (`_reason_baseline.py:228`) are unchanged, so `reason-baseline.json` cannot change on this path. The two ratchet baselines lose the pruned keys (a shrink).
5. Completeness floor that the fixture cannot set (D13). `test_every_producer_resolves` stops reading the fixture. It runs on the live scan (`_reason_baseline.build()`), and it counts one code entry for each literal code (resolved as today) and one for each `registry` site. A `registry` site resolves by evaluating its `expr` (parsed with `ast`, names and attributes only, never `eval`):
   - a chain rooted at `reasons` is evaluated against `decoy_engine.reasons` itself, without importing the site's module (seven such sites sit in `providers_v2/mimesis/_adapter.py`, which needs an optional extra to import);
   - any other name or attribute chain (a module constant such as `FK_KEY_DTYPE_UNSUPPORTED_CODE`, a class constant `Cls.CONST`) is evaluated against the imported site module;
   - a subscript (the scanner's two finite-table shapes, `reasons.<ns>.TABLE[key]` and a module dict `_TABLE[key]` of registry symbols, `tests/sentry/_reason_scan.py:280` and `:286`; today `_checks_grouped_series.py:157` and `_sequential_native.py:621`) evaluates the table, which must be a non-empty mapping or sequence whose every value passes `reasons.is_registered`.
   The resolved value (or every table value) must pass `reasons.is_registered`. Each `registry` site counts one entry, a table site included; a site that does not resolve fails, as does a site module that cannot import when its chain is not rooted at `reasons`.
   Measured with this algorithm on `2e1108a0d` (engine dependencies installed, no test run): 1353 `registry` sites, all 1353 resolve (2 table sites holding 11 distinct registered codes). Literal codes on the live tree: 0. It asserts `checked >= FLOOR`, where `FLOOR` is a fixed number in a new baseline, `tests/sentry/baselines/f29-resolved-entries.json` (`{"floor": N}`), set by hand to the count this algorithm gives on the E0r base (1353 on `2e1108a0d`), re-measured that day and reviewed in the PR. The old `checked > 1000` (`tests/unit/test_reason_registry.py:145`) goes. The floor can only rise: E0r adds a `FLOORS` table to `tests/sentry/_ratchet.py` with this one baseline, and the ratchet fails when head's `floor` is below base's; the baseline is registered in `scripts/dev/sentry_registry.toml`. A scanner regression that finds fewer registry sites fails the floor; deleting producers for real needs an owner exception to lower it.
6. Determinism: `--prune-inventory` runs twice and once under the CI interpreter (3.10); the three outputs are byte-identical, or the slice stops and goes to the owner.
7. Mutations before push: add one stale row back (the AST guard goes red); add a live row to `pruned-rows.json` (the dead-row test goes red); make the scanner skip one module (the floor goes red); lower the floor by one (the ratchet goes red).

Named mutations: the `line`-span check removed (the off-by-one mutant survives, so the test must go red only with the check); the `codes` literal check removed; the prune keeping rows with no live key; the prune skipping the `_ast_site` dead-row proof (a seeded live row is pruned and the dead-row test goes red); `FLOOR` computed from the fixture or the scan instead of read from the baseline (the skip-one-module mutant passes, so the test must go red only with the fixed floor).

Why this order: E2 and E4 move or shift reason sites, and after E0r each such slice updates its rows' non-key fields (E4) or re-homes keys through E0m (E2). E0r opens after #645 and #655 merge or close, because both edit the fixture; re-measure that day.

### E1. `detection/detectors.py` (E1.2 and E1.3; E1.1 done)

Measured on `bb993f398`: 920 lines, legacy census entry 920 (`tests/sentry/test_module_size.py:104`). Top-level layout:

| Lines | Block |
|---|---|
| 1 to 82 | docstring, imports (`_patterns` 33 to 57; `_scoring` 58 to 71 with `# noqa: F401 re-exported constants`; `_validators` 72 to 81) |
| 91 to 198 | name hints: `_hint` 91, mid-file import of `load_name_hint_terms` 114, `_NAME_HINTS` 116, mid-file `contextlib`/`contextvars` imports 134 and 135, `_NAME_HINT_EXTRAS` 137, `name_hint_extras` 144, `_hits_name_hint` 171, `hits_name_hint` 191 |
| 210 to 608 | builtin detectors: `_variant` 210, eight variant tables 218 to 278, 26 `detect_*` 284 to 608 |
| 613 to 724 | `DetectorFn` 613, `REGISTERED_DETECTORS` 615, `run_all_detectors` 648, custom detectors 685 to 724 |
| 743 to 920 | spans: mid-file `dataclasses` import 743, `Span` 747, `_USPS_STREET_SUFFIXES` 768, `_STREET_ADDRESS_RE` 817 (built from it), `_SPAN_DETECTORS` 842 (holds it), `iter_spans` 857 |

Production importers of `decoy_engine.detection.detectors` (grep and AST over `src/`):

- Spans (`Span`, `iter_spans`, `_SPAN_DETECTORS`): 13 files, among them `detection/__init__.py:18`, `detection/ner.py:43`, `transforms/text_mask.py:116`, `transforms/_text_mask_splice.py:22`, five under `execution/native/`, two under `execution/out_of_core/`, two under `execution/_strategies/`.
- `run_all_detectors`: `profiling/_scan_text_checks.py:20`, `profiling/eval/harness.py:30`, `profiling/eval/bands.py:145` (lazy), `verification/postmask/residual_pii.py:51`, `verification/postmask/_column_facts.py:31`.
- `REGISTERED_DETECTORS`: `detection/__init__.py:18`, `detection/domains.py:93` (lazy).
- Hints: `profiling/profiler.py:19` (`hits_custom_name_hint`, `hits_name_hint`) and `:365` (lazy `name_hint_extras`).
- `_scoring` re-exports (D9): `profiling/profiler.py:19` (`_series_str`, `prepared_scope`), `profiling/sentinels.py:30` (`PreparedValues`, `_series_str`), `verification/postmask/_column_facts.py:31` (`counting_scope`, `decide_detector`).
- `_patterns`/`_validators` re-exports: `profiling/features/builder.py:29` (14 regexes, 5 validators), `providers_v2/identifiers/_iban.py:38`, `_icd10.py:40`, `validation/post/_checks/_composite_coherence.py:191` (lazy).

| Slice | Moves | Touched production files | Count | Open-PR claims | Verdict |
|---|---|---|---:|---|---|
| E1.2 | 91 to 198 to `detection/_hints.py` (a sibling, not inside `name_hints/`, for revision 3's execution-order reason); rewrite the three `_scoring` re-export importers to `detection._scoring` (D9) and drop the re-export names from the `detectors` import | `detectors.py`, `_hints.py`, `profiling/profiler.py`, `profiling/sentinels.py`, `verification/postmask/_column_facts.py` | 5 | #617 (`detectors.py`) | WAIT-FOR #617 |
| E1.3 | 210 to 608 to `detection/builtin.py`; the four `_patterns`/`_validators` re-export importers import from the defining modules | `detectors.py`, `builtin.py`, `profiling/features/builder.py`, `providers_v2/identifiers/_iban.py`, `_icd10.py`, `validation/post/_checks/_composite_coherence.py` | 6 | #617 | after E1.2 |
| not in Wave B | spans 743 to 920 | 13 importers plus 2 | 15 | #617 | does not move: over the 10-file bound |

After E1.3, `detectors.py` keeps the imports, `DetectorFn`, `REGISTERED_DETECTORS` (built from the `detect_*` it imports from `builtin`), `run_all_detectors`, the custom detectors and the spans block: about 400 lines. The census entry `detection/detectors.py: 920` is deleted in E1.3. `detection/__init__.py` is unchanged (it imports `REGISTERED_DETECTORS` and `Span`, which stay). The platform pin on `decoy_engine.detection.detectors.REGISTERED_DETECTORS` (`tests/sentry/test_engine_string_targets.py:183`) still resolves.

Ruff: `pyproject.toml:549` (`detection/detectors.py = ["E402"]`) stays, because the spans block keeps its mid-file import. `_hints.py` keeps its three mid-module imports in place with inline `# noqa: E402`. No `pyproject.toml` key changes.

Behavior-preservation tests (red first, in E1.2 before any move; none of them exists on main):

- `tests/unit/detection/test_detectors_characterization.py::test_registered_detectors_order_and_identity`: the ordered `(detector_id, __module__, __qualname__)` list of `REGISTERED_DETECTORS` equals a frozen list from the base. E1.3 re-keys only `__module__` (`detectors` to `builtin`). Seeded fixture violation: swap two entries. Seeded production mutant: swap `detect_first_name` and `detect_last_name` in `detectors.py:615`; red.
- `::test_every_builtin_detector_fixed_series_golden`: four fixed series per detector (match, near-miss, null-heavy, name-hinted) give frozen `DetectorMatch` values. Seeded production mutant: `_scoring.py` `SAMPLE_MISS_LIMIT` changed by one; red.
- `tests/unit/detection/test_spans_characterization.py::test_iter_spans_golden`: `list(iter_spans(text))` over a fixed 12-string corpus equals frozen `(detector_id, start, end, value)` tuples. Seeded production mutant: `_STREET_ADDRESS_RE` (`detectors.py:817`) compiled without `re.IGNORECASE`; red.
- `tests/unit/detection/test_detection_import_order.py::test_detectors_import_executes_modules_in_order`: a subprocess import with a hook recording first execution of `decoy_engine.detection.*` modules equals the manifest order. Seeded mutant: `detectors.py` imports `builtin` before `_hints`; red.
- `tests/unit/detection/test_detection_package_surface.py::test_detection_all_and_identity_unchanged`: `decoy_engine.detection.__all__` equals the base, and `decoy_engine.detection.Span is decoy_engine.detection.detectors.Span`.
- `tests/unit/test_public_api.py::test_all_lists_every_public_name` (existing).
- The checker over each manifest; E1.2's three `_scoring` rewrites and E1.3's four rewrites are importer hunks under rule 5. Checker seeded mutant for E1.2: `from contextvars import ContextVar` hoisted above `_NAME_HINTS` in `_hints.py`; red.

Named mutations per slice: E1.2: the hoisted import above; one `_scoring` importer left on `detectors` (the no-re-export check in `test_wave_b_definition_owners.py` goes red once the re-export is dropped). E1.3: the `REGISTERED_DETECTORS` swap; one variant table moved out of order (checker rule 1a).

Ceilings: `detection/detectors.py: 920` deleted in E1.3; `builtin.py` about 400 lines; `_hints.py` about 110; no new file over 600.

### E2. `plan/_checks.py` (placement changed, D8)

Measured on `bb993f398`: 696 lines, dense ceiling 700 (`tests/sentry/test_module_size.py:109`). Layout: `_INT_NULL_REJECTED_STRATEGIES` 37, `_is_integer_dtype` 40, `check_unknown_provider` 54, `check_non_poolable_provider_with_pool_backend` 99, `check_basic_uniqueness_pre_flight` 148, `check_null_bearing_int_unsupported` 198, `check_composite_columns_length_match` 259, `check_statistical_columns` 286 to 391, `_check_ner_available_for_strategy` 394 to 428, `check_text_redact_ner_available` 431 to 441, `check_text_mask_ner_available` 444 to 452, `check_fpe_checksum_scheme` 455 to 562, `check_derived_column_refs` 565 to 696 (new since revision 3; it stays).

Target layout (revision 3's cut, new home):

| New module | Takes | Lines |
|---|---|---|
| `plan/checks/_statistical_columns.py` | `check_statistical_columns` | 286 to 391 |
| `plan/checks/_ner_available.py` | `_check_ner_available_for_strategy`, `check_text_redact_ner_available`, `check_text_mask_ner_available` | 394 to 452 |
| `plan/checks/_fpe_checksum.py` | `check_fpe_checksum_scheme` | 455 to 562 |
| `plan/_checks.py` (kept) | the other eight definitions | about 420 lines |

`plan/checks/__init__.py` is not changed, so the moved names are not added to the package surface. Importers import from the defining module.

Touched set: `plan/_checks.py`, the three new modules, `plan/_compile.py:55` to `:62` (imports `check_fpe_checksum_scheme` and both NER checks), and `plan/_generation.py:484` (lazy `check_statistical_columns`): 6 production files. `execution/_guards.py:34`, `plan/_checks_correctness.py:12` and `plan/checks/_generate_columns.py:25` import names that stay. Frozen partners in the same PR:

- `tests/sentry/test_reason_registry.py:160` and `:161` (`ADAPTERS` keys re-keyed to the new files).
- The fixture rows of the moved functions (8 rows on today's fixture; after E0r, the rows that survive), re-keyed. Both f29 baselines re-home through E0m.
- `tests/sentry/test_table_kind_classifier.py:43` `"plan/_checks.py": 3` becomes 2, and `"plan/checks/_statistical_columns.py": 1` is added (the truth test at `plan/_checks.py:345` moves). The `table-kind-truth-tests` baseline re-homes through E0m with `moved_from`.
- `pyproject.toml` strict mypy list (`decoy_engine.plan._checks` is listed at `pyproject.toml:652`): add the three new modules, so the moved code stays strict.
- The census: `plan/_checks.py: 700` deleted.

`plan/` stays at 30 modules. `plan/checks/` goes from 7 to 10, under the cap of 25.

Behavior-preservation tests (red first):

- `tests/unit/plan/test_compile_check_order.py::test_config_violating_every_check_raises_the_first_in_base_order`: for each check k in `_compile.py`'s call order, a config that breaks every check from k onward raises check k's code; the order is captured on the base. Seeded violation: swap two codes in the expected list. Mutation of the move: the `_compile.py` import rewrite drops `check_text_mask_ner_available` from the call sequence; red at that k.
- `tests/sentry/test_reason_registry.py::test_adapters_exist_and_are_used` (existing; red if an `ADAPTERS` key still names `plan/_checks.py` for a moved function), `::test_no_ad_hoc_reason_codes`, `::test_registry_symbols_exist`.
- `tests/sentry/test_reason_baseline_frozen.py` (existing; `reason-baseline.json` byte-identical).
- E0r's `test_every_row_is_its_ast_site` (re-keyed rows must name the new file).
- `tests/sentry/test_table_kind_classifier.py` (existing).
- The checker over `e2.json`. Every new module is reached only through importers, so it may hold inert definitions and imports only (rule 4).

Named mutations: drop `check_text_mask_ner_available` from the rewritten import (the order test goes red); leave one `ADAPTERS` key on the old path (the adapters test goes red); keep the truth-test count at 3 on `plan/_checks.py` (the classifier sentry goes red as an over-count, and E0m refuses the growth).

Why E2 waits: #555, #557, #561 and #596 edit `plan/_checks.py` and `test_table_kind_classifier.py`. E2 opens after they merge or close, after E0r and E0m, re-measured that day. No E2 test names a registry version (`tests/sentry/test_wave_b_no_registry_version_literal.py`, on main).

### E4. `transforms/text_mask.py` (prose move only)

Measured on `bb993f398`: 650 lines, dense ceiling 670 (`tests/sentry/test_module_size.py:143`). The synthetic-value helpers already moved to `transforms/_text_mask_synthetic.py`. Docstrings: module 103 lines (1 to 103), `mask_cell` 54 lines (579 to 632), 237 docstring lines in all. Reason sites: 4 (`_apply_sub_floor_span_policy` 2, `_mask_fpe` 2).

Slice (revision 3, unchanged): move the narrative of the module docstring (keep about 10 lines that point to the decision page) and of the `mask_cell` docstring (keep about 10) to `docs/decisions/text-mask-span-masking.md`. No code token changes. The file lands at about 513 lines and its census entry is deleted. The manifest sets `docstring_prose: true`. The four reason rows shift `line`; after E0r, those non-key fields are refreshed in the same PR (no key changes, so no ratchet re-home). `secret-material-census` and `gcs-call-kwargs` keys for this file are keyed by function, not line, and do not change.

Tests (red first): `tests/unit/transforms/test_text_mask_characterization.py::test_mask_cell_golden` over a fixed corpus (SSN, phone, date, PAN with checksum, a sub-floor span, a lone surrogate) under a fixed key. Seeded production mutant: the `code=` on the sub-floor raise in `_apply_sub_floor_span_policy` removed; the golden and `test_no_ad_hoc_reason_codes` go red. Checker seeded mutant for the prose move: one code token edited in the same commit; red.

Named mutations: the code-token edit above; a docstring line moved into code as a string constant (checker red).

Why E4 waits: #617 edits `text_mask.py`; E4 also needs E0r. The `_span_key` dedupe stays out (F-5, Q8).

### E6. Dense entries with a named split target (D12)

E6a is done (#419). `execution/native/_dispatch.py` 677 and `execution/native/_requirements.py` 657 have no pure split (revision 3: the moved code reads names the kept module defines, an import cycle). Both stay dense entries; Q7. The decline-order oracle gap (F-13) stays recorded for whoever splits `_dispatch.py`.

### E7. Engine files over 600 with no slice (per file)

Re-measured on `bb993f398`:

| File | Lines | Census ceiling | Open-PR claims | Trigger |
|---|---:|---:|---|---|
| `profiling/model_pack/trainer.py` | 712 | 712 (legacy) | none | design a split (target "split, fit, calibrate, evaluate") |
| `execution/_sequential_native.py` | 697 | 700 | none | cohesive; Q7 |
| `execution/_pandas_adapter.py` | 694 | 700 | none | design a split |
| `transforms/_codeset_loader.py` | 683 | 700 | none counted | target `_codeset_verify.py` |
| `execution/native/_chunked_entry.py` | 676 | 689 | none counted | design a split |
| `execution/_sequential.py` | 676 | 680 | none counted | target "split the per-table mask loop" |
| `internal/faker_setup.py` | 667 | 688 | none counted | cohesive; Q7 |
| `generators/columns.py` | 658 | 678 | #523, #546, #555, #557, #561, #596 | those merge |
| `plan/_compile.py` | 656 | 666 | #617 | #617 merges |
| `quarantine.py` | 650 | 658 | none counted | target "split the publish cluster" |
| `execution/out_of_core/_stream_join.py` | 645 | 665 | none | cohesive |
| `execution/out_of_core/_spill_estimate.py` | 638 | 665 | none counted | target `_spill_widths.py` |
| `execution/out_of_core/_budget.py` | 622 | 622 | none | target `_disk_budget.py` |
| `execution/_pipeline_route_exec.py` | 616 | 632 | none | design a split |
| `execution/_pipeline_routing_signals.py` | 613 | 633 | none counted | target "split the probe-recovery resolver" |

Every file is under 700, so each is a dense entry with a ceiling. Each gets its own cut when it opens: a manifest, red-first characterization tests and the checker, as for E1. No E7 cut is designed in this plan.

E8 (`execution/` root restructure) stays deferred to after CLI V1 (owner H-1 Q3, roadmap row 55).

## 5. CLI slices

### C0. Pure-move checker port (cut, D4; R1; claim-free)

Port `E:scripts/check_pure_move.py` and `E:scripts/check_pure_move_scope.py` to `C:scripts/dev/check_pure_move.py` and `C:scripts/dev/check_pure_move_scope.py` (the CLI CODEMAP row for developer scripts). Only the source root changes (`src/decoy/` instead of `src/decoy_engine/`). Port `E:tests/unit/test_check_pure_move.py` to `C:tests/unit/scripts/test_check_pure_move.py`, with its fixtures re-cut from a CLI file (`src/decoy/cli/report.py` at the C0 base) under `tests/fixtures/pure_move/`. The size census is not ported: it exists (`tests/sentry/layout/test_module_size.py`, limit 800).

Tests: every engine checker test, ported, each red on its seeded mutant before the checker exists: reordered statement, wrong import source, dropped statement, hoisted import, duplicated definition, changed constant, import cycle, use before bind, unforced non-inert module, inert reorder accepted, extra importer hunk, unlisted importer, manifest over the file bound. Named mutations: rule 1a order check removed (reorder test red); rule 6 bound removed (bound test red).

Drift between the two copies is a class 9 risk. C0 adds `tests/unit/scripts/test_check_pure_move_parity.py::test_rules_match_engine_copy`: it hashes the two scripts with the source-root constant normalized and compares the digest to one recorded in the test. A change to either copy must update the digest in both repos in the same release window. Named mutation: edit one rule in the CLI copy; red.

### C1. `distribution/installer.py`: dropped (D3)

### C3. CLI files over 800 (WAIT)

| File | Lines | Census | Open-PR claims | Trigger |
|---|---:|---:|---|---|
| `cli/report.py` | 2305 | 2305 (legacy) | #301, #312 | those merge, and row 56 (STORM CLI half) |
| `cli/scan.py` | 1037 | 1037 | none counted (#68 parked) | row 56 |
| `cli/preflight.py` | 859 | 859 | #312 | #312 and row 56 |
| `cli/fit.py` | 818 | 818 | none | row 56 (re-check: its names may not be touched by the rename) |

Revision 3's rules for C3 stand: the first C3 slice lands a per-copy characterization test and a duplicate inventory for `_check_target_overwrite` and the other duplicate helpers; any merge of copies is an owner decision. The `cli/run/` package is done (RUN-SPLIT). Placement for each split follows the CLI CODEMAP: command internals go in a named sub-package below `src/decoy/cli/` (for example `src/decoy/cli/scanning/` already exists for `scan`). C3's cut is designed when row 56 lands; this plan fixes only its gate and placement rule.

## 6. Placement

Checked against engine `CODEMAP.md` "Where Things Go" (`CODEMAP.md:237`) and the CLI `CODEMAP.md` "Where Things Go".

| New path | Slice | CODEMAP row | Fan-out after |
|---|---|---|---|
| `E:src/decoy_engine/detection/_hints.py` | E1.2 | "Detectors, profiling": `src/decoy_engine/detection/`, by detection concern | `detection/` 9 to 10 of 25 |
| `E:src/decoy_engine/detection/builtin.py` | E1.3 | same | 10 to 11 of 25 |
| `E:src/decoy_engine/plan/checks/_statistical_columns.py` | E2 | "Plan compile and checks": new checks in `src/decoy_engine/plan/checks/`, `_<topic>.py` (`CODEMAP.md:254`) | `plan/checks/` 7 to 10 of 25; `plan/` stays 30 (frozen) |
| `E:src/decoy_engine/plan/checks/_ner_available.py` | E2 | same | as above |
| `E:src/decoy_engine/plan/checks/_fpe_checksum.py` | E2 | same | as above |
| `E:docs/decisions/text-mask-span-masking.md` | E4 | decision records | n/a (doc) |
| `E:tests/sentry/test_ratchet_rehome_manifest.py` | E0m | "Sentry test" | n/a (tests) |
| `E:tests/sentry/test_reason_inventory_paths.py`, `E:tests/sentry/_ast_site.py` | E0r | "Sentry test" | n/a (tests) |
| `E:tests/fixtures/f29/pruned-rows.json`, `E:tests/sentry/baselines/f29-resolved-entries.json` | E0r | beside the f29 fixture and the baselines | n/a (data) |
| `E:docs/plans/h1-wave-b/manifests/e1-2.json`, `e1-3.json`, `e2.json`, `e4.json` | each slice | beside `e3.json`, `e5.json` | n/a |
| `C:scripts/dev/check_pure_move.py`, `C:scripts/dev/check_pure_move_scope.py` | C0 | "Developer environment scripts": `scripts/dev/` | `scripts/dev/` 10 to 12 |
| `C:tests/unit/scripts/test_check_pure_move.py`, `test_check_pure_move_parity.py` | C0 | "Developer environment scripts" tests: `tests/unit/scripts/` | n/a |

Ratchets touched: engine `module-size` (shrink only: E1.3 deletes `detection/detectors.py`, E2 deletes `plan/_checks.py`, E4 deletes `transforms/text_mask.py`); `f29-producer-inventory` and `f29-consumer-inventory` (E0r shrink; E2 re-home through E0m, count unchanged); `table-kind-truth-tests` (E2 re-home through E0m, total unchanged); `package-fanout` (no entry changes; `plan/` stays 30); `secret-material-census` and `gcs-call-kwargs` (unchanged; E4 shifts lines only, keys are by function); `import-layers` (unchanged: no new cross-layer import); `public-import-boundary` (unchanged); the ratchet tool itself (E0m adds `REHOME_BY_MANIFEST`, checked by `check_move`; E0r adds `FLOORS`); new registered baseline `f29-resolved-entries` (E0r, a floor that only rises). CLI: `module-size` unchanged (C0 adds no file over 800).

## 7. Order

| Order | Slice | Repo | Tier | Waits on |
|---:|---|---|---|---|
| 1 | C0 | CLI | R1 | nothing |
| 1 | E0m | engine | R2 | nothing |
| 2 | E0r | engine | R2 | #645 and #655 merged or closed |
| 3 | E1.2, then E1.3 | engine | R2 | #617 merged or closed |
| 4 | E4 | engine | R2 | #617 and E0r |
| 5 | E2 | engine | R2 | #555, #557, #561, #596 merged or closed; E0r; E0m |
| later | C3 | CLI | R2 | row 56 and the PRs in section 5 |
| per file | E7 | engine | R2 | its own cut |

Tiers: R1 means Codex review only; R2 means Dennis then Codex. C0 is R1 because it ports tooling that already passed an R2 gate on the engine and changes no product code. Every engine slice is R2 because each touches a frozen partner (the ratchet, the reason fixture or the census).

Cross-repo order: no remaining engine slice moves a path the CLI imports. `git grep decoy_engine.detection` on CLI `src/` and `tests/` finds imports of `detection.ner` and `detection.types` only, plus one comment naming `detectors` (`C:src/decoy/cli/_init_inference.py:65`), which stays true because `detectors.py` keeps its name. The platform pin on `decoy_engine.detection.detectors.REGISTERED_DETECTORS` still resolves after E1.

## Slices

| Slice | Repo | Touched production files | Risk | Review | Named mutations | Test depth |
|---|---|---|---|---|---|---|
| E0m | engine | none | R2 | Dennis then Codex | drop the unmoved-function condition; drop the max-sum condition; accept a manifest not in the diff; skip the `check_move` call | T1: `tests/sentry/`; full suite on the merge head (test tooling is an escalation trigger) |
| E0r | engine | none | R2 | Dennis then Codex | remove the line-span check; remove the codes-literal check; prune keeps a row with no live key; skip the dead-row proof; compute the floor from the scan | T1: `tests/sentry/`, `tests/unit/test_reason_registry.py`; full suite on the merge head (shared fixture) |
| E1.2 | engine | 5 | R2 | Dennis then Codex | hoisted `ContextVar` import; one `_scoring` importer left on `detectors` | T1: `tests/unit/detection/`, `tests/unit/profiling/`, `tests/unit/verification/`, `tests/sentry/` |
| E1.3 | engine | 6 | R2 | Dennis then Codex | swap two `REGISTERED_DETECTORS` entries; move one variant table out of order | T1: as E1.2 plus `tests/unit/providers_v2/`, `tests/unit/validation/` |
| E2 | engine | 6 | R2 | Dennis then Codex | drop `check_text_mask_ner_available` from the rewritten import; leave one `ADAPTERS` key on the old path; keep the truth-test count at 3 | T1: `tests/unit/plan/`, `tests/sentry/`, `tests/unit/test_reason_registry.py`; full suite on the merge head (reason fixture and ratchet baselines move) |
| E4 | engine | 1 | R2 | Dennis then Codex | one code token edited with the prose move; the sub-floor `code=` removed | T1: `tests/unit/transforms/`, `tests/sentry/` |
| C0 | CLI | 0 (tooling only) | R1 | Codex | rule 1a removed; rule 6 removed; one rule edited in the CLI copy | T1: `tests/unit/scripts/` |
| C3 | CLI | per cut | R2 | Dennis then Codex | per cut | per cut |

Each slice: manifest first, tests red first, pure move next, importer rewrites and frozen partners in the same PR, checker output attached, before and after test-id sets attached. T0 per edit; T1 on the slice head; the gate reruns T1 on the exact head plus the named mutations. Commits follow Conventional Commits, subject at most 72 characters, final line `cam`, no other trailers.

## Acceptance tests, red first (hostile corpus)

| Id | Slice | Test | Red on |
|---|---|---|---|
| AT-1 | E0m | `tests/sentry/test_ratchet_rehome_manifest.py` (eight tests in E0m) | each seeded case, including the impure manifest; the accepting case is the control |
| AT-2 | E0r | `tests/sentry/test_reason_inventory_paths.py` (row guard, dead-row proof, stdlib-only import guard) and `tests/unit/test_reason_registry.py::test_every_producer_resolves` (fixed floor) | today's fixture (1176 site rows, 1 consumer row), each of five seeded mutants, a live row in `pruned-rows.json`, a scanner that skips one module |
| AT-3 | E1.2 | `tests/unit/detection/test_detectors_characterization.py` (two tests) | the swapped-entry and `SAMPLE_MISS_LIMIT` mutants |
| AT-4 | E1.2 | `tests/unit/detection/test_spans_characterization.py::test_iter_spans_golden` | `_STREET_ADDRESS_RE` without `re.IGNORECASE` |
| AT-5 | E1.2 | `tests/unit/detection/test_detection_import_order.py` | `builtin` imported before `_hints` |
| AT-6 | E1.2 | `tests/unit/detection/test_detection_package_surface.py` | an extra or missing name in `detection.__all__` |
| AT-7 | E2 | `tests/unit/plan/test_compile_check_order.py` | a dropped check in the rewritten import |
| AT-8 | E4 | `tests/unit/transforms/test_text_mask_characterization.py::test_mask_cell_golden` | the sub-floor `code=` removed |
| AT-9 | C0 | `C:tests/unit/scripts/test_check_pure_move.py` (ported) and `test_check_pure_move_parity.py` | each structural mutant; an edited rule in one copy |
| AT-10 | every move | the checker over the slice manifest | reorder, wrong source, cycle, unlisted importer, over-bound |

## Class table

| # | Class | Where it can bite here | Closing structure | Sentry or property test | Mutation |
|---|---|---|---|---|---|
| 1 | Wrong value | A moved detector or check gives a different verdict; a reordered variant table changes the first match | Pure move proven by the checker; frozen goldens for every detector and for `mask_cell` | AT-3, AT-4, AT-8, AT-10 | swap two variant tables; change `SAMPLE_MISS_LIMIT` |
| 2 | Cleanup | N/A: no slice opens a file, handle, temp dir or process in product code; E0m's tests use scratch git repos under `tmp_path`, which pytest removes | `tmp_path` fixtures only | the existing ratchet test pattern | n/a, no product cleanup path |
| 3 | State | Import-time state: `_NAME_HINT_EXTRAS` is a `ContextVar`; module execution order decides when `_NAME_HINTS` is built | Checker rule 4 (execution order) and the runtime import-order test | AT-5, AT-10 | hoist the `ContextVar` import; import `builtin` first |
| 4 | Route divergence | `validate` and `run` call the plan checks through two entry points; a moved check dropped from one import breaks only one route | Both entry points import from the defining module; the order test runs `compile_plan` and `run_config_only_checks` | AT-7 | drop one check from the `_compile.py` import |
| 5 | Referential integrity | A ratchet key re-homed to a file that does not hold the function; a fixture row naming a deleted function | E0m condition 3; E0r AST guard | AT-1, AT-2 | re-home an unmoved function; rename a fixture `function` |
| 6 | Untrusted producer | A manifest is hand-written and could claim any move | The ratchet runs the pure-move checker itself (E0m condition 6) in its one acceptance function, and takes only a manifest changed in the slice diff | AT-1 impure-manifest and stale-manifest cases | skip the `check_move` call; accept a manifest not in the diff |
| 7 | TOCTOU / check-then-use | Claims measured today and stale on the day a slice opens | Rule 2.1: each slice re-measures claims on its own base before opening | the slice's opening checklist | open E2 while #596 is unmerged (the rebase conflict is the evidence) |
| 8 | Weak test | The `checked > 1000` floor in `test_every_producer_resolves` proves only size; a count taken from the fixture under test proves nothing; revision 3's decline-order oracle survived its mutant (F-13) | E0r: a fixed resolved-entry floor on the live scan that only rises, a scanner-independent dead-row proof and the AST row guard; F-13 stays recorded | AT-2 | remove the AST line-span check; compute the floor from the scan |
| 9 | Refactor drift | Two copies of the checker (engine and CLI) drift; E1.1 landed with a re-export shim | Parity digest test in C0; E1.2 removes the shim | AT-9, `test_wave_b_definition_owners.py` | edit one rule in the CLI copy; leave one importer on the re-export |
| 10 | Frozen contract | Reason registry, `reason-baseline.json`, the public surface, the ratchet baselines and the mypy strict list | No identity changes (8.2 of revision 3); `test_reason_baseline_frozen.py`; `test_public_api.py`; E0m keeps key counts; `test_mypy_override_targets.py` | AT-1, `test_reason_baseline_frozen.py`, `test_public_api.py` | re-home with a count increase; omit a new module from the strict list |

## Reuse inventory

- Pure-move checker: `E:scripts/check_pure_move.py`, `E:scripts/check_pure_move_scope.py` (on main since #372 to #374). C0 ports it; it is not rewritten.
- Wave B sentries on main: `tests/sentry/test_wave_b_no_registry_version_literal.py`, `tests/unit/test_wave_b_definition_owners.py`, `tests/sentry/test_engine_string_targets.py`, `tests/sentry/test_reason_baseline_frozen.py`.
- Ratchet re-home precedent: `REHOME_BY_BINDING` in `tests/sentry/_ratchet.py:40`, with `moved_from`. E0m follows its shape.
- Reason scanner: `tests/sentry/_reason_baseline.py::build()` and `_reason_scan.py`. E0r adds a flag; it does not write a second scanner. `_ast_site.py` is a site finder for one known row, not a scanner: it never lists sites.
- Pure-move checker inside the ratchet: `check_move` (`scripts/check_pure_move.py:210`), called, not copied.
- Manifest format: `docs/plans/h1-wave-b/manifests/e3.json`, `e5.json`.
- CLI size census: `C:tests/sentry/layout/test_module_size.py` (exists; not ported).
- Established method: the move is checked by AST comparison (`ast.dump`, the Python language reference's import semantics), the approach revision 3 chose over `git diff -M`.

## Enumerations

### Exit paths

- Checker refusal: `scripts/check_pure_move.py` exits non-zero with a rule tag per problem (`scripts/check_pure_move.py:31` lists the manifest fields it requires).
- Ratchet refusal: `scripts/dev/ratchet_check.py` exits 1 on a finding (`scripts/dev/ratchet_check.py:57`); E0m adds a pass path for proven re-homes and changes no other exit.
- Prune refusal: `--prune-inventory` writes nothing when the live scan fails to import; `--write` keeps its refusal (`tests/sentry/_reason_baseline.py:228`).
- Product exit paths: N/A, no slice changes product behavior; the plan checks keep their codes and order (AT-7).

### Routes

- `compile_plan` and `run_config_only_checks` both reach the moved plan checks (`plan/_compile.py:250` and `:555` call the same check list).
- `decoy validate` reaches them through the CLI gate's compile layer; no CLI change.
- Detector routes: profiling (`profiling/profiler.py:19`), post-scan (`verification/postmask/residual_pii.py:51`) and span masking (`transforms/text_mask.py:116`) read `detectors`; E1 keeps every one of them working through the defining modules.

### FK shapes

- N/A: no slice reads, writes or plans a relationship; the moved code has no FK logic (checked: no `relationships` import in the moved blocks of `detectors.py:91` to `:608` or `plan/_checks.py:286` to `:562`).
- `check_composite_columns_length_match` (composite FK column lists) stays in `plan/_checks.py` and does not move.

### Fields

- Manifest fields: `old`, `new`, `map`, `importers`, `docstring_prose`, `tests`, `frozen_partners` (`scripts/check_pure_move.py:31`).
- Fixture row fields: `file`, `function`, `kind`, `expr` (the ratchet key, `tests/sentry/_baseline_sources.py:140`) and `line`, `codes`, `family`, `value_class` (refreshed by E0r).
- Ratchet entry fields: `reason`, `max`, `moved_from` (`tests/sentry/_ratchet.py:40` for the existing re-home rule).

### Output surfaces

- Gate output: the ratchet's review lines (`ratchet: <line>`), one per re-homed key in E0m.
- Fixture files: `tests/fixtures/f29/producer-inventory.json`, the two f29 baselines (E0r, E2), `tests/fixtures/f29/pruned-rows.json` and `tests/sentry/baselines/f29-resolved-entries.json` (E0r).
- Docs: `docs/decisions/text-mask-span-masking.md` (E4) and `CODEMAP.md` rows for the new modules.
- Product output surfaces (reports, logs, CLI text): N/A, no slice changes them; AT-8 and the detector goldens pin the values.

## Frozen contracts

- `decoy_engine.__all__` and `decoy_engine.detection.__all__`: unchanged (`tests/unit/test_public_api.py`, AT-6).
- F29 reason registry and `tests/fixtures/f29/reason-baseline.json`: no identity added, removed or re-homed; byte-identical (`tests/sentry/test_reason_baseline_frozen.py`).
- `REGISTERED_DETECTORS` order and identity (AT-3); `iter_spans` output (AT-4); `mask_cell` output (AT-8).
- Ratchet baselines: key counts never grow; re-homes only through E0m with a manifest.
- Platform and CLI import paths into the engine: unchanged (`tests/sentry/test_engine_string_targets.py:183`).

## Pre-mortem

| Failure | Likelihood | Guard |
|---|---|---|
| E0m becomes a general escape hatch for growing a baseline | medium | Only three sentry ids; manifest must be in the diff and pass `check_move` inside the ratchet; one acceptance function; key count and max sums cannot grow; AT-1 |
| E0r's prune deletes a row that is still a live site because the scanner misses it | low | The stdlib-only `_ast_site` proves each removed row dead before the write and on every run (`pruned-rows.json`); the live-scan floor catches a scanner that finds fewer sites |
| The checker copies drift between repos | medium | C0 parity digest |
| E2 lands while a GEN-REL PR still edits `plan/_checks.py`, and the rebase silently re-adds a moved function | medium | Rule 2.1 re-measure; the checker's owner rule (a name defined twice is red) |
| #617 lands a different cut of `detectors.py` | medium | E1 re-measures every line number on its base; the design is by block, not by line |
| A reviewer reads the `checked > 1000` change as a weakened test | high | It is named in D6 and D13; the replacement is a fixed floor (1353 entries, above the old 1000) on the live scan that only rises |

## Findings in the existing code (listed, not fixed)

- F-9 (revision 3) holds and is larger: 1176 of 1387 fixture rows name no live site (D6).
- F-14 (new, class 8): `tests/unit/test_reason_registry.py:145` (`checked > 1000`) passes on a fixture that is 85% stale; it proves size, not truth. On the live tree its literal-code count is 0. E0r fixes it (D13).
- F-15 (new, class 9): E1.1 (#468) left `_scoring` names re-exported through `detectors.py:58` to `:71` with `# noqa: F401`, against rule 1.2. E1.2 fixes it.
- F-13 (revision 3): the decline-order oracle gap in `native/_dispatch.py` stays recorded.

## Owner questions

- Q7 (revision 3, still open): `native/_dispatch.py`, `native/_requirements.py`, `_sequential_native.py`, `internal/faker_setup.py` and `out_of_core/_stream_join.py` have no pure split. Recommendation: keep them as dense entries until a behavior change gives a reason to cut them.
- Q8 (revision 3, still open): `_span_key` dedupe. Recommendation: leave out of Wave B.

## Not verified

- No test was run (devbox rule). The fixture measurement ran the scanner's `build()` only, on an exported tree under system CPython 3.13; the CI interpreter (3.10) was not run.
- CLI checker port: the CLI test environment was not built; C0 records the collection count.
- Claims come from open PRs on 2026-11-17; branches without a PR are not counted.
