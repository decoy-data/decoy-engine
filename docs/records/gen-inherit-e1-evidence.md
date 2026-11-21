# GEN-INHERIT E1 build evidence

Status: built on `feat/gen-inherit-e1`. No census number, threshold, baseline or allowlist rose.
One catalogue-procedure pin moved (the `GEN_KIND_TO_SITE` map digest, below). No existing digest,
golden or snapshot value moved, and no expected output value was edited.

Spec: `docs/plans/2026-11-10-gen-inherit.md` on `origin/plan/gen-inherit`, slice row E1 (the
`inherit` generate type), and GEN-REL's "GEN-INHERIT handoff frozen by E3a"
(`docs/plans/gen-rel.md` on `origin/plan/gen-rel`). The plans stay on their plan branches.

## Heads and environment

- Base: `feat/gen-inherit-e2` at `3d6838b5` (slice 5, PR #561; it holds GEN-REL E1 to E3b with
  their review fixes and `origin/main` `c86ca58d`). Main is not merged into this branch.
- Commits: `2ad64961` the `synthesize.py` move (refactor), `ae1de728` the red acceptance tests
  (source as at `2ad64961`), `838033de` the feature, `f58c0452` the generate-surface count in
  the proof-manifest sentry (test only). Final source head: `838033de`. This record and one
  fragment bullet are added in a docs-only commit after `f58c0452`.
- Gates and script checks: Python 3.10.20 (temporary venv under the session scratch directory,
  synced with `uv sync --frozen --python 3.10 --extra dev --extra lint --extra vault --extra
  cloud`, removed after; `decoy_engine.__file__` is the checkout's `src`), PyArrow 24.0.0,
  DuckDB 1.5.4. The `layers` step ran in `.venv-layers`.
- Move run, red run, sweeps and mutations: Python 3.11.18 (the `.venv`), PyArrow 24.0.0,
  DuckDB 1.5.4.

## Commit 1: the `synthesize.py` move (`2ad64961`)

`generation/synthesize.py` was 597 lines (aim 600, hard max 700, no census entry). The E1
dispatch and the typed `arrow_table` call add 9 lines, so a move came first. The top-level
definitions of `synthesize.py` are frozen by `tests/fixtures/h1/definition_owners.json`, so only a
function-body block moved: the table guard of the referenced-formula post-pass.
`_generate_tables_from_config` tested `any(c.get("type") == "formula" and c.get("references")
...)` before a lazy import of `fill_referenced_formula_columns`; that function already selects
exactly those columns (`type == "formula"`, a non-empty `formula`, non-empty `references`) and
returns before it imports pandas when there are none. The guard now lives only there: the call
is made for every table and the lazy import stays (the Phase F post-pass witnesses patch the
module attribute and still see every call that fills a column). Behavior is unchanged.
`synthesize.py`: 597 to 588 at the move, 597 at the final head. No definition left the file.

Green run of the move (Python 3.11, 4 workers, the move applied, before the red tests):
`tests/unit/generation tests/parity tests/native/test_determinism_goldens.py
tests/native/test_draw_site_inventory_coverage.py tests/native/test_draw_sites_catalogue_pinned.py
tests/unit/test_wave_b_definition_owners.py tests/unit/test_check_pure_move_scope.py
tests/unit/test_v2_generation.py tests/integration/golden tests/unit/transforms
tests/sentry/test_module_size.py tests/sentry/defects tests/acceptance`: 12083 passed, 1261
skipped, 37 xfailed, 0 failed.

## Red first (commit `ae1de728`, source as at `2ad64961`)

`.venv/bin/python -m pytest -p no:xdist tests/unit/generation/relational/test_inherit.py
tests/unit/config/test_generate_options.py tests/sentry/defects/test_reference_pool_choke_point.py`:
40 failed, 284 passed, no collection error.

| File | Red |
| --- | --- |
| `tests/unit/generation/relational/test_inherit.py` (new; AT-1, AT-3 to AT-7, AT-13, AT-14) | 26 |
| `tests/unit/config/test_generate_options.py` (AT-2) | 12 |
| `tests/sentry/defects/test_reference_pool_choke_point.py` (AT-12) | 2 |

Reasons:

- Absent type: `inherit` is not in the `GenerateColumnConfig.type` Literal, so every config cell
  is refused with pydantic `literal_error` at `type` instead of its own code and location (AT-2,
  AT-3 config cells); `GENERATE_OPTIONS["inherit"]` and the registry rows are missing
  (`KeyError`, the registered-inputs and minimal-column cells).
- Absent dispatch: `_generate_column` raises `ValueError: unexpected generator type 'inherit'`
  (AT-3 runtime cell, AT-4, AT-5, AT-6 run cells, AT-13, AT-14 output cells).
- Wrong outcome: plan compile does not refuse a missing parent column or a later `via` (`DID NOT
  RAISE PlanCompileError`); reproducibility does not exclude the copy of a fresh parent column;
  pinned compile refuses with `pinned_type_not_allowlisted`; the streamed entry raises
  `GenerationUnboundedError` (no width bound for the type); `numeric_plan` gives no `int64` for
  the parent key under a copy; `reference_root` stops at the copy (`('claims', 'member_state')`
  instead of `('members', 'state')`, `('lines', 'code')` instead of `('members', 'member_id')`).
- Absent module: `generation/relational/_inherit.py` (`FileNotFoundError`, AT-12).

Green on the base by design (2 cells), each tied to a mutation shown red below:

| Cell | Why green on the base | Mutation |
| --- | --- | --- |
| `test_at14_without_a_yielded_edge_the_key_is_returned_unchanged` | the base never hops at `inherit` | M7 (dereference a missing resolved edge), M6 |
| `test_at14_a_malformed_copy_with_no_via_is_its_own_root` | the same | M7 |

Test change after the red commit (none weakened): `_tampered_pinned_plan` in `test_inherit.py`
built its placeholder column as `{"name": "member_state", **STATE}`, so `STATE`'s own `name`
won and the plan held no `member_state` column (`StopIteration` in the helper, not a product
outcome). It is now `{**STATE, "name": "member_state"}`; the assertions are unchanged.

## What the slice does

- Type and registry (`config/_tables.py`, `config/_generate_options.py`): `inherit` joins the
  Literal. Its registry entry: `via` is `OptionSpec(_str, ref_kind="column")` and `column` is
  `OptionSpec(_str, ref_kind="column_via_reference", ref_context_key="via")` (inline phase), both
  required. New `parent_lookup_keys(type_)` in the registry module returns the companion key of
  each `column_via_reference` input of a type (`anchor_via`, `via`).
- Config check (`config/_generate_relational.py`): `parent_lookup_problems` reads its lookup
  options from `parent_lookup_keys` instead of the literal `anchor_via`, so `inherit.via` gets the
  same `parent_key_problem` rule and codes (`config.generate_parent_lookup_key_not_unique`,
  `config.generate_parent_lookup_self_reference`) at its own location. No new check.
- Numeric typing root (`config/_generate_relational.py::reference_root`): an `inherit` column
  hops to the source endpoint of the `column` edge yielded by `iter_generate_input_refs` (an edge
  with a `source_key`, so resolved through the reference); with no such edge it returns the
  incoming key. It reads neither `via` nor `reference_table`. `READERS` classifies `inherit.via`
  (equality match to the parent key) and `inherit.column` (copies the cell and its type; the
  copy joins the parent's group) as numeric-safe.
- Generator (`generation/relational/_inherit.py`, new, 110 lines): `inherit_values` takes both
  edges from the resolver, reads the parent table named on the `column` edge from `pools`, and
  calls `_parent_lookup.lookup_parent_values` only. A caller that skipped validation and the plan
  check gets a typed `ValueError` naming the column only (the per-parent aggregate's precedent;
  no reason code). `inherit_types` gives each copy its parent column's `pa.DataType` from
  `pools[...].schema`. Method cited in the docstring: SQL `LEFT JOIN` on a unique key and SDV
  HMA1 parent-to-child propagation.
- Resident route (`generation/synthesize.py`, `generation/_statistical_column.py`): the
  dispatch beside `reference`; `arrow_table(..., parent_types=...)` builds each copy with
  `pa.array(values, type=parent_type)`. Only the resident call passes it.
- Routes: `ADMISSION_MATRIX["inherit"] = (False, "reads a parent row by FK; no cross-table row
  seam")` (streamed declines, `family_declined:inherit`); `REJECTED_TYPES["inherit"]` carries
  `plan.pinned_relational_option_unsupported`, and `_reject_column` raises it through the one
  relational refusal builder, so pinned compile gives the plan code and pinned execute the runtime
  twin (`GenerationError`).
- Bounds (`generation/_bounds.py`): the copy's width bound is its root column's bound
  (`reference_root`), so a bounded streamed call over a plan with a copy is not refused as
  unbounded before it falls back.
- Native registries (`execution/native/_determinism_protocol.py`,
  `execution/native/_capabilities.py`): `GEN_KIND_TO_SITE["inherit"] = DETERMINISTIC_NO_DRAW`
  and a `_GEN_ONLY` row (not row-local, global over the parent table, output type not static).
  No draw site was added.

## Mutations (final source head `838033de`, detached worktree; 14 of 14 red)

Each was applied once in a detached worktree of `838033de` that imports its own `src`
(`PYTHONPATH=<worktree>/src`; the harness printed `decoy_engine.__file__` under the worktree),
the four test files `test_inherit.py`, `test_generate_options.py`,
`test_reference_pool_choke_point.py` and `test_generate_input_edges.py` run (Python 3.11.18,
4 workers), and the file restored; every anchor matched exactly once. Statuses are read from the
harness's results JSON: 14 entries, 14 `RED`. The worktree was clean at the end and is removed.
No witness starts a child process, so no mutation was applied in the checkout.

| Id | Mutation (plan name first) | File | Red |
| --- | --- | --- | --- |
| M1 | draw a random parent row | `generation/relational/_inherit.py` | 8: AT-3 missing key, AT-4 (two), AT-5, AT-6 copy, AT-13, AT-14 int64 ... |
| M2 | resolve `column` in the child | `_inherit.py` | 1: `test_at6_the_copy_reads_the_parent_and_not_a_same_named_column` |
| M3 | restore `inherit.column` to sibling-only `ref_kind="column"` | `config/_generate_options.py` | 24: AT-3 (config and run cells), AT-4, AT-5, AT-6, AT-7 streamed, AT-13, AT-14, `test_the_registered_inputs_are_exactly_these`, and the sentry's descriptor and lookup-key manifests ... |
| M4 | inline a dict lookup in the `inherit` generator | `_inherit.py` | 3: AT-12 `test_inherit_copies_through_the_parent_lookup_and_builds_no_index`, scan 6 `test_only_the_parent_lookup_builds_a_key_to_row_map_over_a_pool_column`, AT-3 missing key |
| M5 | `_reference_root` stops at `inherit` | `config/_generate_relational.py` | 6: AT-14 root cells and formula cell, AT-7 streamed (unbounded), `test_the_acceptance_cells_hold_on_the_registered_descriptors[inherit-column]` |
| M6 | restore manual `via` lookup plus `via.reference_table` and `inherit.column` resolution | `config/_generate_relational.py` | 5: `test_at14_the_root_hop_reads_the_yielded_edge`, `test_at14_without_a_yielded_edge_...`, scan 8 `test_only_the_via_resolver_follows_a_lookup_column_to_its_parent`, the resolver-caller inventory, the inherit descriptor cell |
| M7 | dereference a missing resolved edge | `config/_generate_relational.py` | 3: `test_at14_without_a_yielded_edge_the_key_is_returned_unchanged`, `test_at14_a_malformed_copy_with_no_via_is_its_own_root`, the inherit descriptor cell |
| M8 | allow a non-unique key | `config/_generate_relational.py` | 3: the AT-3 not-unique cells |
| M9 | resolve the table again at run from `column` | `_inherit.py` | 1: `test_at6_the_copy_reads_the_parent_and_not_a_same_named_column` |
| M10 | drop the parent types so Arrow infers | `generation/synthesize.py` | 1: `test_at4_the_copy_has_the_parent_columns_type` |
| M11 | pinned refuses `inherit` with a plain type code | `generation/_pinned_compile.py` | 2: AT-7 pinned compile and execute |
| M12 | streaming admits `inherit` | `generation/_admission.py` | 2: AT-1, AT-7 streamed |
| M13 | the copy's width bound is unbounded | `generation/_bounds.py` | 1: AT-7 streamed |
| M14 | `inherit.via` is a numeric-unsafe reader | `generation/_numeric_typing.py` | 2: AT-1, `test_at14_without_a_text_reader_the_key_and_its_copy_are_int64` |

M1 to M10 are the plan's E1 mutations, in the brief's order; M11 to M14 cover the pinned twin,
the streamed decline, the bound and the reader classification. Under M3 the AT-3 config cells go
red too: the lookup check reads its options from the `column_via_reference` descriptors, so a
copy whose `column` is a sibling read is no lookup and gets no key check, as intended.

## Draw-site catalogue (catalogue procedure)

`inherit` draws nothing and adds no draw site; `DRAW_SITES`, its order and each entry digest are
unchanged. `GEN_KIND_TO_SITE` gains `"inherit": DETERMINISTIC_NO_DRAW`, so its map digest in
`tests/native/test_draw_sites_catalogue_pinned.py` was re-pinned by the file's procedure (a
comment line naming the change, as GEN-TYPES E1 and E3 did): `2174d2a8...` to `b3836a41...`.
The static draw-site scan needs no allowlist entry (`_inherit.py` holds no RNG token).

## Execution files and the seam sentry

`execution/native/_determinism_protocol.py` and `execution/native/_capabilities.py` changed, one
data entry each, as the plan's Placement row lists. Both are already on the permitted lists of
`tests/sentry/test_physical_seam_disconnection.py`; the list that records reasons gains a comment
line for this change. Neither imports anything from `execution.physical`. No other `execution/`
file changed.

## Files outside the plan's E1 list

- `generation/_referenced_formula.py` (the move; docstring only).
- `config/_generate_relational.py` beyond `reference_root`: `parent_lookup_problems` reads its
  options from the registry so `inherit.via` gets the shared key rule (the plan says the rule is
  shared; the check was keyed to the literal `anchor_via`).
- `support/_shape.py`: `StrategyKind.INHERIT`. `tests/unit/support/test_bundle_fields.py`
  requires the support-bundle enum to mirror every generate type (the `lookup` precedent, #550).
- `docs/proof-manifest.json` (regenerated by `scripts/gen_proof_manifest.py`: generate surface
  14 to 15, `inherit` listed) and `docs/capability-matrix.md` (regenerated by
  `scripts/gen_capability_matrix.py`).
- Test support for the type enumerations: `tests/parity/_f0_matrix.py` (a `DEFERRED` row),
  `tests/parity/_f_audit_matrix.py` and `_f_audit_cells.py` (an `inherit` row and cell),
  `tests/fixtures/gen_strict/generate-config-identity.json` (additive: `t1.key`, `t2.r4`,
  `t2.ih`; every existing dump entry and fingerprint unchanged), and the sentry manifest of
  `tests/sentry/defects/test_generate_input_edges.py` (resolver callers `_inherit._edges` and
  `reference_root`, lookup caller `inherit_values`, lookup keys `anchor_via` and `via`, and the
  `inherit.column` descriptor cells).
- `CODEMAP.md` (the Generation row names the copy), `docs/strategies.md`.

`READER_FILES` did not need widening: `_inherit.py` reads no option key literally (both inputs
come from the resolved edges). Module counts: `generation/` gains no direct module (`_inherit.py`
is in `generation/relational/`); `config/` and `plan/` gain none.

## Pre-existing tests whose expectation changed

| Test | Before | Now | Why |
| --- | --- | --- | --- |
| `tests/parity/test_phase_f_audit_matrix.py::test_the_literal_has_fifteen_kinds_...` (renamed from `fourteen`) | 14 kinds | 15 | the new type |
| `tests/unit/generation/test_pinned_generation.py::test_pinnable_allowlist_covers_every_config_type` | `REJECTED_TYPES == {faker, formula, lookup}` | `+ inherit` | the plan's pinned refusal |
| `tests/unit/generation/unique/test_gu_e2_config.py` `VALID` | 14 types | `+ inherit` | the registry-remainder cell; `unique: true` on `inherit` is refused |
| `tests/unit/config/test_generate_options.py::test_the_registered_inputs_are_exactly_these` | no `inherit` | `inherit.via`, `inherit.column` | AT-2 |
| `tests/sentry/defects/test_generate_input_edges.py` | lookup keys `[anchor_via]`; three cross-table descriptors | `[anchor_via, via]`; four, with cells | the plan's registration |
| `tests/native/test_draw_sites_catalogue_pinned.py` | `GEN_KIND_TO_SITE` digest `2174d2a8...` | `b3836a41...` | catalogue procedure |

No masked-output test changed and no expected output value was edited.

## Line counts

Source, final head (base in brackets): `generation/synthesize.py` 597 (597; 588 after the move),
`config/_generate_relational.py` 577 (562), `config/_generate_options.py` 574 (549),
`execution/native/_capabilities.py` 560 (548), `config/_tables.py` 495 (494),
`generation/_bounds.py` 431 (419), `generation/_pinned_compile.py` 413 (403),
`support/_shape.py` 395, `generation/_numeric_typing.py` 333 (327), `generation/_admission.py`
296 (295), `generation/_statistical_column.py` 222 (217),
`execution/native/_determinism_protocol.py` 177 (176), `generation/relational/_inherit.py` 110
(new), `generation/_referenced_formula.py` 76. At or above 550: `synthesize.py` 597,
`_generate_relational.py` 577, `_generate_options.py` 574, `_capabilities.py` 560. All under the
600 aim; no census entry added or raised. Tests at or above 550: `test_generate_options.py` 1013,
`test_pinned_generation.py` 855, `test_generate_input_edges.py` 774, `_f_audit_cells.py` 710,
`test_inherit.py` 604 (new).

## Gates

`GATES_WORKERS=4 scripts/dev/gates.sh --keep-going --baseline --steps
ruff,format,mypy,sentry,layers,licenses,tests <the 154 T1 paths below>`, Python 3.10.20
(temporary venv, `DECOY_VENV`), PyArrow 24.0.0, DuckDB 1.5.4, `origin/main` at `13c8e62b`. The
baseline reruns only the steps that failed on the branch, in a detached worktree of
`origin/main` with the same venv.

| Step | Run 1 (`838033de`) | Run 2 (`f58c0452`, final head of code and tests) | Run 3 (`f58c0452`, `tests` only) |
| --- | --- | --- | --- |
| ruff | pass | pass | |
| format | pass | pass | |
| mypy | pass | pass | |
| sentry | 5519 passed, 1 failed, 2 skipped | 5520 passed, 0 failed, 2 skipped | |
| layers | 15 passed, 0 failed | 15 passed, 0 failed | |
| licenses | 63 passed, 0 failed | 63 passed, 0 failed | |
| tests | 13525 passed, 0 failed, 351 skipped | 13524 passed, 1 failed, 351 skipped | 13524 passed, 1 failed, 351 skipped |
| baseline (`origin/main`) | sentry: 5612 passed, 0 failed | tests: 12893 passed, 1 failed | tests: 12893 passed, 1 failed |

- Run 1, sentry: `tests/sentry/test_proof_manifest.py::test_surface_counts_match_capability_matrix`
  (branch only) counts the generate surface by hand (14). It is a pre-existing test whose
  expectation follows the new type, updated by its own procedure (a dated comment, 14 to 15, as
  GEN-TYPES E1 and E3 did) in `f58c0452`, a test-only commit. Run 2's sentry step passes.
- Runs 2 and 3, tests:
  `tests/unit/execution/test_byte_estimate_routing.py::TestEndToEndWiring::test_width_change_flips_route_at_a_fixed_budget_and_row_count`
  hit `Timeout (>300.0s) from pytest-timeout` on the branch and passed on `origin/main` (6.4 s)
  in both baselines. It is the test slice 5 recorded timing out on the branch and on main alike.
  It is a mask-only routing test (200 000-row parquet sources, faker masks, a fidelity report)
  and reaches no code this slice changed. On the same source it passed in run 1's tests step;
  on `f58c0452` it passed alone (6.4 s, gate venv), with the relational, config and audit tests
  under 4 workers (5.5 s), and in a direct 4-worker run of every non-serial T1 path (13515
  passed, 0 failed, 350 skipped). It is recorded as an intermittent timeout, branch-only in two
  of four full T1 runs; I could not reproduce it outside the gate script and did not find a cause.
  The test was not skipped, weakened or rerun with a longer timeout in the gate.
- `tests/unit/test_version_agreement.py::test_installed_metadata_matches_pyproject` fails only on
  the baseline worktree: the shared venv's editable install reports the branch's 0.23.0 while
  `origin/main`'s `pyproject.toml` says 0.26.0. It passes on the branch.
- Failure sets: run 2 branch 1, baseline 1, branch-only 1 (the timeout above); run 3 the same.
  Other than that intermittent timeout there is no branch failure.
- Draw-site results (runs 1 to 3): `tests/native/test_draw_site_inventory_coverage.py` 12 of 12
  passed (`test_static_scan_finds_no_uncatalogued_draw_site` passed) and
  `tests/native/test_draw_sites_catalogue_pinned.py` 5 of 5 passed (with the re-pinned map digest).

### Script checks

On `f58c0452` (clean tree), each against `origin/main` (`13c8e62b`) and against `c86ca58d`
(the main this branch holds through slice 4; main is not merged here).

| Check | `origin/main` (`13c8e62b`) | `c86ca58d` |
| --- | --- | --- |
| `registry_renumber.py --check --main` | 2 (`main-not-merged`) | 0 (`registry consistent`) |
| `ratchet_check.py --base` | 1 | 0 |
| `check_fragment.py --base` | 0 | 0 |
| `reason_release_pin.py --check` | 0 (`reason release pin current`) | (no base) |

The exit 2 is the known main-not-merged effect. The ratchet exit 1 names two
`f29-producer-inventory` keys (`_text_mask.py` / `_mask_group_c.py`
`ner_model_version_mismatch`) that `origin/main` removed from its own baseline in #577; this
branch does not touch that file or those modules, so it clears on the main merge.


## Main merges and owner rulings (2026-11-15)

Totals in this section belong to the head named beside them and supersede the sections above
for the final head.

### Merges

- `ade8c178` merged `origin/feat/gen-inherit-e2` `72bc46bf`, which carried `origin/main`
  `38fddb2f` (32 commits through #597) up the stack, slice 1's move of `_capacity` and
  `config/_generate_relational` into packages (each module unchanged as the package's
  `__init__.py`; the engine root and `config/` stay at the fan-out cap of 25) and the
  late-formula test move of slice 5. One conflict, `generation/synthesize.py`: this slice's
  unconditional post-pass call (the guard lives in `fill_referenced_formula_columns`) now passes
  main's `name, types=types`; the module is 598 lines. `config/_generate_relational/__init__.py`
  equals this slice's module byte for byte (577 lines).
- `97ff1401` merged `origin/feat/gen-inherit-e2` `8899b393`, carrying `origin/main`
  `64e9349b` (#598, a `profile/` format table) without a conflict.

On `ade8c178` the T1 gate below had four branch-only failures, all from main #574 (a formula
reads its references typed and refuses a text spelling of a number): AT-14's formula cell, the
input-edges sentry's `inherit-column` cell (a formula as the text reader), main's per-type table
in `test_formula_types.py` (no `inherit` entry) and the testflight live-registry guard (no job
or allowlist entry for `inherit`).

### Owner rulings

1. Main wins on AT-14 (`1a936f42`). The cells are re-derived from main's behaviour; main's code
   is unchanged.

   | Before | After |
   | --- | --- |
   | `test_at14_a_child_formula_reading_the_copy_keeps_the_parent_key_text`: a formula `'M-' + member_code` keeps `members.member_id` text | `test_at14_a_child_text_reader_of_the_copy_keeps_the_parent_key_text`: a `group_key` with `group_by: member_code` (a reader that still reads text) keeps both columns text and the copy equal to the key |
   | (none) | `test_at14_a_child_formula_using_the_copy_as_text_is_refused`: `'M-' + member_code` is refused at validate with `plan.generate_formula_number_used_as_text` at `tables.claims.generate_columns.label.formula` |
   | (none) | `test_at14_a_child_formula_reads_the_copy_as_a_number` (`'M-' + str(member_code)` and `f'M-{member_code}'`): `member_id` and the copy stay `int64` and each label is `M-` and the key |
   | input-edges sentry `COPY_READER`: a formula `'x' + copied` | a `group_key` with `group_by: copied` |

   `tests/unit/generators/test_formula_types.py` gains an `inherit` entry in `_EXAMPLES` (a
   copy of a parent `sequence` through a reference) and `_EXAMPLE_TABLES` for its parent table,
   so the fidelity cells run it with and without nulls. The other AT-14 cells (without a text
   reader the key and copy are `int64`, the root hops) are unchanged.

   Red first: the new test file against the pre-merge source (`a2302bf4`, detached worktree):
   the refusal cell fails (`DID NOT RAISE PlanCompileError`) and both number cells fail
   (`None == int64`: the formula kept the key text). The `group_key` cell and the sentry cell
   pass on both sources: they hold under the old and the new formula rule, so neither can be red
   without a mutation; they stay tied to M1, M3 and M5 (below).
2. Testflight (`d15634dc`): `testflight/_coverage.py` `_GENERATE_TYPE_ALLOWLIST` gains
   `inherit`, with the reason "copies a parent row's column through a reference foreign key, so
   a job needs a generated parent and child table; it makes no draw of its own (pinned as
   DETERMINISTIC_NO_DRAW in the draw-site catalogue) and is covered by
   tests/unit/generation/relational/test_inherit.py; a test-flight job case is a tracked
   V2-LOG item". No test ratchets the dict's size.
3. Facade import (`a27a82c5`): `generation/relational/__init__.py` exports `inherit_types` and
   `inherit_values`; `synthesize.py` imports the package (`from decoy_engine.generation import
   _faker_pool, relational`) and calls `relational.inherit_types(...)` and
   `relational.inherit_values(...)`. Importing the two names beside `reference_draw_extras`
   would format to a six-line block (602 lines). The module is 597 lines; the
   definition-owners fixture is unchanged; `decoy_engine`, `generation.synthesize`,
   `generation.relational` and `config` import fresh without a cycle; layers 15 passed. The
   other crossings into `relational._aggregate` and `relational._self_reference` are unchanged.

### Mutations (final source head `a27a82c5`, detached worktree, 15 of 15 red)

The harness now names `config/_generate_relational/__init__.py`, and M10's anchor is the
`relational.inherit_types(` call. M15 is new. Red counts (previous run in brackets):

| Id | Red | AT-14 cells among them |
| --- | --- | --- |
| M1 | 10 (8) | both number cells, the int64 cell, the text-reader cell |
| M2 | 1 (1) | |
| M3 | 27 (24) | the refusal, number, int64, root and text-reader cells |
| M4 | 3 (3) | |
| M5 `reference_root` stops at inherit | 7 (6) | the refusal cell, the three root cells, the text-reader cell, the sentry's `inherit-column` cell |
| M6 | 5 (5) | the yielded-edge and missing-edge cells |
| M7 dereference a missing resolved edge | 3 (3) | the missing-edge and no-`via` cells |
| M8 to M13 | 3, 1, 1, 2, 2, 1 (unchanged) | |
| M14 `inherit.via` numeric-unsafe | 4 (2) | both number cells and the int64 cell |
| M15 a formula reads its references as text again | 2 (new) | both number cells |

### Gates (final source head `a27a82c5`)

`GATES_WORKERS=4 scripts/dev/gates.sh --keep-going --baseline --steps
ruff,format,mypy,sentry,layers,licenses,tests` over the 154 T1 paths below (they include
`tests/unit/execution/test_byte_estimate_routing.py`), Python 3.10.20, baseline `origin/main`
`64e9349b`:

| Step | `ade8c178` | `a27a82c5` |
| --- | --- | --- |
| ruff, format, mypy | pass | pass |
| sentry | 5772 passed, 1 failed, 2 skipped | 5796 passed, 0 failed, 2 skipped |
| layers | 15 passed | 15 passed |
| licenses | 63 passed | 63 passed |
| tests | 13773 passed, 3 failed, 351 skipped | 13781 passed, 0 failed, 351 skipped |

`ade8c178` ran against `origin/main` `38fddb2f` (main 5625 sentry and 12894 tests passed, 0
failed); its four failures are listed above. `a27a82c5` has no failing step, the routing test
included. Script checks on `a27a82c5` against `origin/main` `64e9349b`:
`registry_renumber.py --check --main origin/main`, `ratchet_check.py --base origin/main`,
`check_fragment.py --base origin/main` and `reason_release_pin.py --check` each exit 0.
`generation/synthesize.py` 597 lines; `tests/unit/plan/checks/test_generate_columns.py` 856;
the engine root and `config/` hold 25 modules, `profile/` 19.

## Main merge (2026-11-16, `a7f278eb`), carried forward

`origin/feat/gen-inherit-e2` `ef6198b7` merged into `16d54f90` as `cd1e129a`, without a
conflict. It carries `origin/main` `a7f278eb` (#600, #582 one seed path for every seeded
generator, #489 durable publication units) and slice 2's re-pin of the draw-site catalogue:
`tests/native/test_draw_sites_catalogue_pinned.py` keeps both "Re-pinned for ..." lines and a
`_CATALOGUE_DIGEST` recomputed by the file's procedure, and it passes on this tree. The merge
touches none of the files the 15 mutations anchor in (`_inherit.py`,
`config/_generate_relational/__init__.py`, `_generate_options.py`, `synthesize.py`,
`_pinned_compile.py`, `_admission.py`, `_bounds.py`, `_numeric_typing.py`), so the mutation run
on `a27a82c5` stands and was not repeated. Main's seed sentry
(`tests/sentry/defects/test_rng_construction.py`) passes over this slice's code.

Gate on `cd1e129a`, the same command over the 154 T1 paths, Python 3.10.20, baseline
`origin/main` `a7f278eb`: ruff, format and mypy pass; sentry 5862 passed, 0 failed, 2 skipped;
layers 15 passed; licenses 63 passed; tests 13826 passed, 0 failed, 351 skipped; no
branch-only failure (the routing test included). Script checks against `origin/main`
(`registry_renumber.py`, `ratchet_check.py`, `check_fragment.py`, `reason_release_pin.py
--check`): each exit 0. `generation/synthesize.py` 597 lines; the engine root and `config/` hold
25 modules (main's packages: `determinism/` 3, `fileaccess/` 17, `generation/composite/` 10).

## Main merge (2026-11-16, `1c8e413c`), test-flight coverage and full suite

### Merge

`origin/feat/gen-inherit-e2` `21e827b6` merged into `66e1d352` as `c7e07e82`, without a
conflict. It carries `origin/main` `1c8e413c` (#496: the `publication/` package with the
`decoy-publication/v1` descriptor codec and receipt types, placed in the `execution` tier of
`.importlinter` and the layer snapshot; `_canonical` gains strict JSON reading). The merge touches
none of the files the 15 mutations anchor in, so the run on `a27a82c5` stands. The engine root
and `config/` hold 25 modules, `publication/` 2; `generation/synthesize.py` 597 lines.

### Test-flight covers `inherit` (`2aa2d027`)

The orchestrator ruling replaces the allowlist entry of ruling 2 with a flight job.
`testflight/_coverage.py` is main's file again (no `inherit` entry). Red first: with the entry
removed and no job, `tests/unit/config/test_testflight_manifests_parse.py` failed 1 of 8 with
"generate-column type(s) uncovered and not allowlisted: ['inherit']".

No job had a generated parent and child table (Job D's `visits` is a standalone generate
table), so Job D gains two: `clinics` (40 rows: `clinic_id` sequence, `clinic_tier`
categorical) and `clinic_stays` (600 rows: `stay_id` sequence, `clinic_id` a `reference` to
`clinics.clinic_id` with `null_probability: 0.1`, `clinic_tier` an `inherit` column via
`clinic_id`). A new harness invariant, `inherited_columns` (`testflight/_inherited.py`, wired in
`_evaluate.py`, spec `InheritedColumnSpec` in `_spec.py`), checks from the output tables alone
that the parent key is unique, every child copy equals its parent row's value with the same
type, every non-null key has a parent row, and a null key gives a null, with floors on null-key
rows (20) and distinct copied values (3). `testflight/test_testflight_inherited.py` holds nine
mutation controls (a copy from the wrong row, a value beside a null key, a key with no parent, a
type change, a repeated parent key, both vacuity floors, the faithful case, and the
`evaluate_invariants` wiring). `docs/acceptance-test-flight.md` describes the check. The engine
is unchanged; `reference` stays in main's allowlist although Job D now also covers it.

Job D's golden fingerprint moved by `python scripts/test_flight.py --update-fingerprints`:
`a3e53cc7...` to `3fde329a...`. The run's other five goldens are unchanged, and the
fingerprint of Job D's outputs without the two new tables is still `a3e53cc7...`, so only the
added tables moved it. The suite run on `2aa2d027`: `python scripts/test_flight.py` 61 of 61
checks passed (`inherited_columns verified: clinic_stays.clinic_tier(rows=600, null_keys=49,
distinct=3)`), fingerprints 6 of 6 match; `pytest testflight -m testflight` 148 passed; the
live-registry guard reports generate types live 15, covered 15, allowlisted 1.

### Full suite (head `2aa2d027`, Python 3.10.20)

`GATES_WORKERS=4 scripts/dev/gates.sh --keep-going --baseline --full` (the regression-gate
selection: `pytest tests` without benchmark, packaging, codspeed and determinism_harness
markers, plus env, ruff, format, mypy, sentry, layers and licenses), baseline `origin/main`
`1c8e413c`:

| Step | Branch | Main |
| --- | --- | --- |
| env, ruff, format, mypy | pass | not rerun |
| sentry | 5880 passed, 0 failed, 2 skipped | not rerun |
| layers | 15 passed | not rerun |
| licenses | 63 passed | not rerun |
| tests | 45509 passed, 3 failed, 93 errors, 5369 skipped | 44477 passed, 0 failed, 93 errors, 5369 skipped |

- Shared with main (93 errors): `tests/fileaccess/scratch/test_private_creators.py` (56),
  `tests/fileaccess/scratch/test_scratch_arena.py` (31) and
  `tests/unit/execution/test_scratch_root_umask.py` (6) refuse to run as root ("root ignores
  directory modes"); this container runs as root.
- Branch-only (3), `tests/property/test_ri_graph_invariants.py`:
  `test_multi_parent_conflicting_policy_is_rejected`, `test_invalid_policy_value_is_rejected`
  and `test_duplicate_conflicting_policy_is_rejected` require the orphan-policy refusals to
  echo the policy values and the column tuples (`"['fail', 'preserve']"`,
  `"orphan_policy='sometimes'"`, `"p.['id']"`, `"c.('pid',)"`). Slice 1 (`55c73d28`) made those
  messages value-free on purpose and pins that with its own tests
  (`test_an_invalid_policy_is_refused_without_echoing_it`, `test_a_duplicate_names_neither_policy`,
  `test_conflicting_policies_raise`). The same three fail on `feat/gen-rel-e1`. Not changed
  here: making them pass means either dropping the value-free messages or narrowing the property
  test's assertions, which is a ruling.

Other CI lanes, run on the same head: `pytest -m ml` with `DECOY_REQUIRE_ML=1` 92 passed, 8
skipped; the DP certified profile (`check_fit_environment` OK; `-m dp_certified` 79 passed and
`junit_ran.py` passed=79, none skipped; license sentries strict 63 passed); the determinism
harness 3 passed (`junit_ran.py` passed=3); packaging (`build==1.2.2`, sdist built with
`hatchling-1.32.4`, `-m packaging` 137 passed, 10 skipped); NER (the pinned
`en_core_web_sm-3.8.0` wheel, sha256 checked, `DECOY_REQUIRE_NER=1`, `-m ner` 39 passed, 10
skipped); base install (no extras) `scripts/dev/base_install_smoke.py` OK; import smoke on
Python 3.11.18 and 3.12.3 OK; test-flight on Python 3.11.18 with `dev geo` 146 passed, 2
skipped, script 61 of 61 and fingerprints 6 of 6; `pip-audit==2.10.1` on 3.10, 3.11 and 3.12
"No known vulnerabilities found"; `semgrep==1.183.0` on the secret-provider rules 0 findings.

Python 3.12.3 (`gates.sh --steps ruff,mypy,sentry,tests --full`, no baseline): ruff pass; sentry
5880 passed; tests 45424 passed, 3 failed, 93 errors, 5454 skipped (the same three branch-only
failures and the same 93 root refusals); mypy stops on two environment errors (numpy's 3.12
stubs under the configured `python_version = "3.10"`, and no `tomli` on 3.12), neither in this
stack's files. CI runs mypy on 3.10 only.

Docs: `sphinx-build -b html -W --keep-going docs` fails locally on main as well (209 "document
isn't included in any toctree" warnings on `origin/main`); this stack adds 11 more of that kind,
one per evidence record. No other warning.

Not run: the native companion wheel workflows (`decoy-engine-native`, a Rust and maturin build
this stack does not touch); `benchmark` and `codspeed` (manual performance lanes);
`compat-preflight` and `regression-proof` (pull-request checks that read the PR body or a
`bugfix` label).

## Main merge (2026-11-16, `ddd014a5`), carried forward

`origin/feat/gen-inherit-e2` `92bee24e` merged into `5aa93830` as `9ecfa437`, without a
conflict. It carries `origin/main` `ddd014a5` (release 0.27.0 and the twelve commits after
`1c8e413c`: publication judge and bind, the sink state table, `publish_unit` through the sink and
the isolated route, resume store records, the pre-scan model pass, lazy-input streaming, the
scratch arena move and the frozen-surface map). Main does not touch the draw-site catalogue,
`.importlinter`, `testflight/` or any of the files the 15 mutations anchor in, so the run on
`a27a82c5` stands. Of this slice's files main touches `docs/proof-manifest.json` (the engine
version), `CODEMAP.md` and the physical-seam sentry (its own run-stream entries); each merged
beside this slice's lines. The release consumed main's changelog fragments; this chain's seven
fragments are kept. gen-rel-e1 rewords two `generation/_streamed.py` comments to hold the module
at 600 lines once main's `publication_receipt` field meets that slice's reference policy.

Checks on `9ecfa437`, Python 3.10.20, `origin/main` `ddd014a5`: ruff, format and mypy pass;
`tests/sentry` 5985 passed, 0 failed, 2 skipped; layers 15 passed; `tests/unit/generation`
with the tests of this slice and the slices below it, the two draw-site catalogue tests and the fan-out sentry:
5112 passed, 0 failed, 43 skipped. Script checks (`registry_renumber.py --check --main
ddd014a5`, `ratchet_check.py --base ddd014a5`, `check_fragment.py --base ddd014a5`,
`reason_release_pin.py --check`): each exit 0. `generation/synthesize.py` 597 lines,
`generation/_streamed.py` 600; the engine root and `config/` hold 25 modules. Not run on this
head: the full T1 gate, mutations and the full suite.

## Main merge (2026-11-16, `13c95c7d`), carried forward

`origin/feat/gen-inherit-e2` `57a73de3` (holding `origin/main` `13c95c7d`: #605, the run-stream
E5b no-sink collector scratch opened on first spill, and #607, the F22 b1 durable vault adopt and
`VaultCommit`) merged into `bb381ab5` as `3b11bbee`, without a conflict. It carries gen-rel-e1's
owner ruling A: the three orphan-policy refusal tests in
`tests/property/test_ri_graph_invariants.py` assert the reason code and field, not the declared
policies, and the refusal source is unchanged. Main does not touch the draw-site catalogue,
`.importlinter`, `uv.lock`, `generation/` or `testflight/`. Of this slice's files main touches
`CODEMAP.md`; it merged beside this slice's lines. Main's changelog fragments arrive beside this
chain's six, which are kept. This head was not pushed: `origin/main` moved before its record.

Checks on `3b11bbee`, Python 3.10.20: ruff, format and mypy pass; `tests/sentry` 5993 passed, 0
failed, 2 skipped; layers 15 passed; `tests/unit/generation` with the tests of this slice and the
slices below it, the two draw-site catalogue tests and the fan-out sentry: 5149 passed, 0 failed,
43 skipped; `tests/property/test_ri_graph_invariants.py` 35 passed. Script checks against
`13c95c7d` (`registry_renumber.py --check --main`, `ratchet_check.py --base`,
`check_fragment.py --base`, `reason_release_pin.py --check`): each exit 0. `generation/synthesize.py`
597 lines, `generation/_streamed.py` 600; the engine root and `config/` hold 25 modules.

## Main merges (2026-11-16, `b886c61d`, `57f5d25f` and `85429533`), carried forward

`origin/main` moved three times more: `b886c61d` (#613, the scan-checks evidence baseline member
and `on_drift` surface; #614, the README; #615, generate-only edges take a derived namespace),
`57f5d25f` (#612, the date-shift MD5 offset path deleted and the unkeyed refusal pinned) and
`85429533` (#611, the distribution behavior table moved from `execution/` to `contracts/`).
gen-rel-e1 merged each in turn: `reasons/warning/_part1.py` kept main's `SCAN_BASELINE_MISSING`
beside gen-rel-e1's `REFERENCE_PARENT_POOL_EMPTY`, both `since=UNRELEASED`, and
`tests/native/test_draw_sites_catalogue_pinned.py` re-pinned the whole-catalogue digest to the
merged catalogue in gen-rel-e1 and gen-rel-e2. `origin/feat/gen-inherit-e2` `e9a209d1` (holding
`origin/main` `85429533`) merged into `3b11bbee` as `47f82498`, without a conflict; this slice's
`GEN_KIND_TO_SITE` map pin is unchanged and the two catalogue tests pass. No file of this chain
imports the moved distribution behavior module, and no generation or relationship test of this
chain depends on the namespace refusal #615 lifts for generate-only edges. Of this slice's files
main touches `docs/strategies.md` and `CODEMAP.md`; each merged beside this slice's lines. Main's
census, baseline, fan-out and import-layer changes are its own deletions; nothing of this chain's
grows. Main does not touch `uv.lock`, `generation/` or `testflight/`. Main's changelog fragments
arrive beside this chain's six, which are kept.

Checks on `47f82498`, Python 3.10.20, `origin/main` `85429533`: ruff, format and mypy pass;
`tests/sentry` 6012 passed, 0 failed, 2 skipped; layers 15 passed; `tests/unit/generation` with
the tests of this slice and the slices below it, the two draw-site catalogue tests and the
fan-out sentry: 5149 passed, 0 failed, 43 skipped; `tests/property/test_ri_graph_invariants.py`
35 passed. Script checks (`registry_renumber.py --check --main origin/main`,
`ratchet_check.py --base origin/main`, `check_fragment.py --base origin/main`,
`reason_release_pin.py --check`): each exit 0. `generation/synthesize.py` 597 lines,
`generation/_streamed.py` 600; the engine root and `config/` hold 25 modules. Not run on this
head: the full T1 gate, mutations and the full suite.

## Main merge (2026-11-17, `dda1b61f`), gate and mutations on the exact head

`origin/feat/gen-inherit-e2` `bf392a09` (holding `origin/main` `dda1b61f`, #609 to #634)
merged into `7212b047` as `1479f413`, without a conflict. gen-inherit-e2 merged that main
directly, because GEN-REL has not taken it yet; its record lists the three conflicts. The draw-site
catalogue arrives with `gen.reference` in main's `path::function` form and re-pinned there; this
slice's `GEN_KIND_TO_SITE` map pin is unchanged and both catalogue tests pass. Main touches none
of the files the 15 mutations anchor in.

Gate on `1479f413`: `GATES_WORKERS=4 scripts/dev/gates.sh --keep-going --baseline` (the selection
against `origin/main`, 1324 paths), Python 3.10.20. ruff, format and mypy pass; sentry 6093
passed, 0 failed, 2 skipped; layers 15 passed; licenses 63 passed; tests 43486 passed, 138
failed or errored, 5384 skipped. Baseline `origin/main` `dda1b61f` on the same paths: 139 fail.
Branch-only test failures: 0. The 138 are the same ids gen-inherit-e2 records: main's red
release pin and the scratch-permission tests that error in this container on main. The env step
failed once because the shared venv's editable install pointed at the gen-inherit-e2 worktree
(tests import each tree's `src` through `PYTHONPATH`); after `bootstrap.sh` in this tree, `--steps
env` passes.

Script checks against `origin/main` `dda1b61f`: `registry_renumber.py --check` 0;
`ratchet_check.py` 0; `check_fragment.py` 0; `reason_release_pin.py --check` 1 with the same 8
`connector.*` lines as `origin/main`, none from this chain.

Mutations: 15 of 15 red on `1479f413`, detached worktree importing its own `src`, Python 3.10.20,
every anchor matched once, the tree clean after each. M1 to M14 ran the four slice files
(`test_inherit.py`, `test_generate_options.py`, `test_reference_pool_choke_point.py`,
`test_generate_input_edges.py`; unmutated 361 passed); M15 those plus `test_formula_types.py`
(399 passed). Red counts (the `a27a82c5` run in brackets): M1 13 (10), M2 1, M3 27, M4 6 (3),
M5 8 (7), M6 5, M7 3, M8 3, M9 1, M10 1, M11 3 (2; AT-1 also red), M12 2, M13 1, M14 4, M15 14
(2; the 12 more are `test_formula_types.py` cells, now in its run). The harness was rebuilt from
the mutation tables above (the earlier harness was not kept).

`generation/synthesize.py` 597 lines. Not run: the full suite, Python 3.11.

## Main merge (2026-11-17, `dc2d397b`), gate and mutations on the exact head

`origin/feat/gen-inherit-e2` `ab1c657d` (holding `origin/main` `dc2d397b`: #622, #631, #632,
#633, #636, #637, #639) merged into `22825a87` as `d5908c79`, without a conflict. The
`problem_details` and `CODEMAP.md` resolutions are in gen-inherit-e2's record. This slice's
refusals pass no third item to `problem_details`, so main's template form does not touch them.

Gate on `d5908c79`: `GATES_WORKERS=4 scripts/dev/gates.sh --keep-going --baseline` (1336
paths), Python 3.10.20, baseline `origin/main` `dc2d397b`. ruff, format and mypy pass; sentry
6141 passed, 0 failed, 2 skipped; licenses 63 passed; layers 11 passed, 4 failed; tests 43870
passed, 115 failed or errored, 5388 skipped. The same 119 ids fail on `origin/main`;
branch-only 0. They are the ids gen-inherit-e2's record names: 113 scratch-permission tests
that error in this container, 4 layer tests (main's `.importlinter` keeps an ignore #632 made
stale) and 2 in `test_subset_run_entry_policy.py` (#639's `run_ner_models` unclassified).

Script checks against `dc2d397b`: `registry_renumber.py --check`, `ratchet_check.py`,
`check_fragment.py` and `reason_release_pin.py --check` each exit 0.

Mutations: 15 of 15 red on `d5908c79`, the same harness and test files as the `1479f413` run;
every red count equals that run's.

`generation/synthesize.py` 597 lines, `config/_generate_options.py` 583. Not run: the full
suite, Python 3.11.

## T1 paths (154: slice 5's 126, 27 importers, 1 changed test)

```
tests/acceptance/test_f06_route_cells.py
tests/acceptance/test_f06_route_parity.py
tests/fileaccess/test_char_error_text.py
tests/fileaccess/test_x2_locators.py
tests/fileaccess/test_x3_classification.py
tests/generation
tests/integration/compat_corpus/test_compat_corpus.py
tests/integration/golden
tests/integration/golden/test_determinism_invariants.py
tests/integration/golden/test_fidelity_report_golden.py
tests/native/test_c8_iii_d2_native_positional_when.py
tests/native/test_capabilities.py
tests/native/test_chunked_categorical_admission.py
tests/native/test_chunked_entry_rev9_read.py
tests/native/test_chunked_entry_side_channels.py
tests/native/test_chunked_nondet_categorical_admission.py
tests/native/test_column_access_surfaces.py
tests/native/test_determinism_goldens.py
tests/native/test_determinism_protocol.py
tests/native/test_draw_site_providers_golden.py
tests/native/test_draw_sites_catalogue_pinned.py
tests/native/test_pooled_faker_draw_sites.py
tests/native/test_unconfigured_passthrough_read.py
tests/parity/test_numeric_typing_fk.py
tests/parity/test_numeric_typing_readers.py
tests/parity/test_phase_d_d1b2_categorical_disposition.py
tests/parity/test_phase_d_d2c_ii_cat_seq.py
tests/parity/test_phase_f_audit_matrix.py
tests/parity/test_phase_f_audit_no_legacy.py
tests/parity/test_phase_f_audit_vacuity.py
tests/parity/test_phase_f_audit_zero_companion.py
tests/parity/test_phase_f_f0_comparator.py
tests/parity/test_phase_f_f0_composite_repeatability.py
tests/parity/test_phase_f_f0_invariants.py
tests/parity/test_phase_f_f0_matrix.py
tests/parity/test_phase_f_f0_oracle.py
tests/parity/test_phase_f_f0_witness.py
tests/parity/test_phase_f_f2_mixed_admission.py
tests/parity/test_phase_f_f2_mixed_backend_witness.py
tests/parity/test_phase_f_f2_mixed_parity.py
tests/parity/test_phase_f_f2_mixed_publish.py
tests/parity/test_phase_f_f2_mixed_sweep.py
tests/parity/test_phase_f_fr0_mixed_stitch.py
tests/parity/test_phase_f_fr0_refreeze.py
tests/parity/test_phase_f_fr0_route_independence.py
tests/parity/test_phase_f_fr0_witness.py
tests/physical/test_characterization_synthesis.py
tests/physical/test_shadow_full_frame.py
tests/physical/test_shadow_generation.py
tests/physical/test_shadow_generation_faker.py
tests/physical/test_unified_slice_positional.py
tests/secret_providers/test_keyed_columns.py
tests/unit/config
tests/unit/determinism/test_derive_vectors.py
tests/unit/execution/test_c8_iii_c_plan_when.py
tests/unit/execution/test_categorical_weighted.py
tests/unit/execution/test_created_target_contract.py
tests/unit/execution/test_dgrn_windowed_date.py
tests/unit/execution/test_group_key_chunked.py
tests/unit/execution/test_multi_table_gates.py
tests/unit/execution/test_ooc_cross_row_decline_message.py
tests/unit/execution/test_pipeline_generation_contract.py
tests/unit/execution/test_probe.py
tests/unit/execution/test_probe_scale.py
tests/unit/execution/test_probe_scale_kills.py
tests/unit/execution/test_r3_failure_publication_trace.py
tests/unit/execution/test_r3_public_signature_freeze.py
tests/unit/execution/test_r3_route_executors.py
tests/unit/execution/test_r3_within_route_baseline.py
tests/unit/execution/test_technique_class.py
tests/unit/execution/test_text_mask_chunked.py
tests/unit/expressions
tests/unit/generation
tests/unit/generation/test_generate_determinism_ratchets.py
tests/unit/generation/unique/test_gen_unique_old_input_bytes.py
tests/unit/generators
tests/unit/plan
tests/unit/profiling/test_snapshot_cell_format.py
tests/unit/profiling/test_snapshot_values.py
tests/unit/profiling/test_snapshot_values_numeric_shape.py
tests/unit/providers_v2/test_distribution_behavior_metadata.py
tests/unit/quality/test_dp_flag_e2e.py
tests/unit/quality/test_retention_gate.py
tests/unit/quality/test_snapshot_fanout.py
tests/unit/reasons
tests/unit/relationships
tests/unit/run_result
tests/unit/scripts
tests/unit/strategy_catalog
tests/unit/test_check_pure_move_scope.py
tests/unit/test_de02_keyprovider.py
tests/unit/test_numpy_generic_timedelta.py
tests/unit/test_public_api.py
tests/unit/test_public_api_v2_choke_points.py
tests/unit/test_r3_10_generation_key_contract.py
tests/unit/test_reason_manifest_policy.py
tests/unit/test_reason_registry.py
tests/unit/test_reason_release_pin.py
tests/unit/test_registry_renumber.py
tests/unit/test_v2_generation.py
tests/unit/test_wave_b_definition_owners.py
tests/unit/transforms
tests/native/test_draw_site_inventory_coverage.py
tests/unit/execution/test_mem_estimate.py
tests/unit/execution/test_byte_estimate_routing.py
tests/unit/execution/test_mem_estimate_arrow_types.py
tests/unit/execution/test_mem_estimate_nullable_metadata.py
tests/unit/execution/test_pipeline_routing_route_kills.py
tests/integration/test_byte_estimate_arrow_types_e2e.py
tests/unit/generation/test_fr0_budget.py
tests/unit/generation/relational/test_aggregate.py
tests/unit/config/test_generate_relational.py
tests/unit/expressions/test_column_refs.py
tests/unit/expressions/test_lark_if_lazy.py
tests/unit/transforms/test_derived.py
tests/unit/test_expressions.py
tests/unit/execution/test_derived_strategy.py
tests/unit/execution/derived_visibility
tests/unit/execution/test_engine_transforms_routes.py
tests/unit/execution/test_runner.py
tests/native/test_draw_sites_assembly.py
tests/native/test_c1b_i_metadata_inventory.py
tests/native/test_c5b_i_metadata_inventory.py
tests/unit/plan/checks/test_generate_columns.py
tests/unit/generation/test_conditional_categorical.py
tests/unit/generation/test_fr0_reproducibility.py
tests/connectors/test_community_connector_example.py
tests/fileaccess/test_nested_explicit_policy.py
tests/integration/test_fk_sequential_row_error_leak.py
tests/native/test_native_plan.py
tests/native/test_native_plan_config_aware.py
tests/native/test_operator_registry.py
tests/native/test_pool_quality.py
tests/parity/test_phase_d_d2a_seq_baseline.py
tests/parity/test_phase_d_d2a_seq_native.py
tests/parity/test_phase_d_d2b_seq_shapes.py
tests/parity/test_phase_d_d2c_fpe_seq.py
tests/parity/test_phase_d_d2c_gap_closure.py
tests/parity/test_phase_d_dcomp_composite_route.py
tests/parity/test_phase_d_dcomp_composite_seq.py
tests/parity/test_phase_d_fpe_int_key_seq.py
tests/parity/test_phase_d_fpe_key_route.py
tests/parity/test_phase_d_fpe_key_seq.py
tests/parity/test_phase_d_fpe_key_seq_real.py
tests/physical/test_bench_compare_harness.py
tests/unit/detection_verification/postscan/test_fk_findings.py
tests/unit/execution/test_expression_log_redaction.py
tests/unit/execution/test_mixed_admission_core.py
tests/unit/execution/test_out_of_core_join_chunked.py
tests/unit/profile/test_dataclass_shapes.py
tests/unit/providers_v2/test_registry.py
tests/unit/support/test_bundle_fields.py
tests/unit/support/test_shape_cells.py
tests/unit/test_version_agreement.py
```

slice 5's 126 paths (its `gate_paths.txt`, including
`tests/unit/execution/test_byte_estimate_routing.py`), the 27 test files outside them that import
or name a module this slice changes (a grep for the touched modules and symbols), and
`tests/unit/test_version_agreement.py`. Every other test file the slice adds or changes is
inside a listed directory or in `tests/sentry`; the `sentry` step runs all of `tests/sentry`
and the `layers` step `tests/sentry/layout/test_import_layers.py`.

## Not run

- The full suite; `tests/perf`; `testflight`; `tests/physical`, `tests/unit/execution`,
  `tests/native` and `tests/parity` beyond the T1 paths (the earlier Python 3.11 sweep below
  covered all of `tests/parity`, `tests/native`, `tests/unit` except `tests/unit/execution` and
  `tests/unit/scripts`, `tests/integration/golden`, `tests/acceptance` and `tests/generation`).
- The gate steps under Python 3.11; gates against a branch holding the current `origin/main`.
- The full gate on the docs-only commit that adds this record and the fragment bullet; on it
  `tests/sentry` (without the import-layer test) and the changelog ratchet test passed (5490
  passed, 0 failed), and `check_fragment.py` exits 0 against both bases.

Sweep (Python 3.11, before the support-enum, audit-matrix and pin updates): 9 failed, 25893
passed; eight were the type enumerations fixed above, and
`tests/unit/test_version_agreement.py::test_installed_metadata_matches_pyproject` failed because
the `.venv` holds a stale 0.22.0 install (it passes in the gate venv). A first attempt that also
ran `tests/unit/scripts` filled the disk (those tests copy the repository per case) and was
discarded, as was a first direct T1 run without `tmp_path_retention_policy=failed`.

## V2-LOG

- `inherit` takes no `output_type`; a user who wants the copy cast differently from its parent
  derives a column from it.
- Pinned mode refuses `inherit` (the plan's non-goal); a pinned lookup seam would admit it.
- The streamed route declines it; a cross-table row seam in the batch core would admit it.
- `parent_lookup_keys` lives in the registry module and is not exported from `config`; the
  public catalog does not say which option is a lookup column.
- A caller that skips validation and the plan check gets an uncoded `ValueError` naming the
  column (as the per-parent aggregate does); a coded run-time twin would need a reason code.
- `tests/unit/scripts` copies the repository per case and can fill a 26 GB disk under a broad
  sweep; keep it out of broad local runs.
- The pre-existing `ratchet_check.py --base origin/main` finding (keys `origin/main` #577 removed
  from `f29-producer-inventory`, a file this stack does not touch) clears on the main merge.
- (Done in `2aa2d027`: Job D covers `inherit`, and `_GENERATE_TYPE_ALLOWLIST` is main's again;
  see "Main merge (2026-11-16, `1c8e413c`), test-flight coverage and full suite".)
