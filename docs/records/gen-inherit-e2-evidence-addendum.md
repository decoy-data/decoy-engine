# GEN-INHERIT E2 build evidence: addendum

This companion to [the GEN-INHERIT E2 build evidence](gen-inherit-e2-evidence.md) holds the
sections added after the primary record passed 800 lines.

## Main merge (2026-11-15), carried forward

`origin/feat/gen-rel-e3b` `4861862c` merged into `6db1b59c` as `e7bae5f4`. It carries
`origin/main` `38fddb2f` (through #597), slice 1's move of `_capacity` and
`config/_generate_relational` into packages (each module unchanged as the package's
`__init__.py`, so the engine root and `config/` stay at the fan-out cap of 25) and slice 4's
one-line post-pass import in `generation/synthesize.py`.

Conflicts, resolved keeping both sides:

- `docs/strategies.md`: this slice's paragraph on a formula filled after the column loop, then
  main's paragraphs on formulas reading number references (#574) and the row rules (#564).
- `generation/_numeric_typing.py` docstring: this slice's categorical conditioning beside main's
  formula wording; the code merged without a conflict (main's `reader_types` split, slice 4's
  config helpers, this slice's `categorical.condition_on` reader).
- `generation/statistical/__init__.py`: this slice's `_sample` exports and main's
  `parse_snapshot_json`.
- `reasons/runtime/_part2.py`: main's released `generate_formula_evaluation_failed` keeps its
  family; this slice's comment heads the `GenerationError` block with
  `categorical_condition_column_unavailable` (`UNRELEASED`).

Main's #574 and this slice's central refusal meet in
`plan/checks/_generate_columns.py`: `_check_formula` (now with main's text-use check) runs
before `_check_input_edges`, whose `earlier` set still leaves out a formula with `references`.
A probe through `run_config_only_checks` on the merged head, over a table `id` (sequence) and
`f = id * 2` (references `id`): a `derived` column reading `f` is refused with
`generate_column_forward_reference`; a formula `g = f + 1` with references `f` validates;
`'X' + id` is refused with `generate_formula_number_used_as_text`; the base config validates.

Checks on `e7bae5f4`, Python 3.10.20, `origin/main` `38fddb2f`: ruff and format pass; mypy
clean (886 files); `tests/sentry` 5761 passed, 0 failed, 2 skipped; layers 15 passed;
`tests/unit/config`, `tests/unit/execution/test_mem_estimate.py`, `tests/unit/generation`,
`tests/unit/plan`, `tests/unit/generators`, `tests/parity/test_numeric_typing_readers.py`,
`tests/parity/test_numeric_typing_fk.py` and `tests/unit/test_wave_b_definition_owners.py`
with the two draw-site catalogue tests: 4556 passed, 0 failed, 40 skipped. Script checks
(`registry_renumber.py --check --main origin/main`, `ratchet_check.py --base origin/main`,
`check_fragment.py --base origin/main`, `reason_release_pin.py --check`): each exit 0.

Line counts (at or above 550): `generation/synthesize.py` 596,
`config/_generate_relational/__init__.py` 562, `generation/statistical/_sample.py` 559,
`expressions/_lark_parser.py` 555, `plan/_checks.py` 698. The engine root and `config/` hold 25
modules each.

## Review round 2 (2026-11-15)

DESIGN 1: `tests/unit/plan/checks/test_generate_columns.py` had grown from 855 to 934 lines
with the late-formula cells of review round 1 (935 after the main merge, which adds one line),
over the 900-line test-file threshold. `cdc667e3` (`test(plan): move the late-formula refusal
cells to their own module`) moves the section, unchanged, into
`tests/unit/plan/checks/test_generate_columns_late_formula.py` (96 lines): its five tests and
its local fixtures (`_filled_late`, `_drawn_now`, `_conditional`, `_joint_snapshot`,
`_fitted`). The shared helpers (`cfg`, `seq`, `formula`, `derived`, `generated`, `p`,
`FORWARD`, `assert_refused`, `assert_accepted`) are imported from `test_generate_columns.py`,
so both sites (validate and compile) are still asserted by the one helper. The old file is 856
lines.

Proof, on `e7bae5f4` against `cdc667e3`: `pytest --collect-only -q` lists 99 node ids before
and 99 after, identical once the module path is mapped; `pytest -rA` passes the same 99 ids
before and after (99 passed, 0 failed, 0 skipped each time). The new module alone: 5 passed.
No sentry, manifest or inventory names the file or its tests; `tests/sentry` on `cdc667e3`:
5761 passed, 0 failed, 2 skipped; `tests/unit/plan` 864 passed.

## Main merge (2026-11-15, `64e9349b`), carried forward

`origin/feat/gen-rel-e3b` `91b0a80e` merged into `72bc46bf` as `1a379c6d`, without a conflict. It carries
`origin/main` `64e9349b` (#598, one format table for resident and lazy file sources), whose
change is in `profile/`, `fileaccess/` and their sentries; it touches no source or test file of
this slice (`CODEMAP.md`'s `profile/` row and the sentry manifest merged beside this slice's
lines).

Checks on `1a379c6d`, Python 3.10.20, `origin/main` `64e9349b`: ruff and format on the changed
files pass; mypy clean (887 files); `tests/sentry` 5785 passed, 0 failed, 2 skipped; layers 15 passed; `tests/unit/config`, `tests/unit/execution/test_mem_estimate.py`, `tests/unit/generation`, `tests/unit/plan` (with the moved late-formula module), `tests/unit/generators`, the numeric-typing parity files and the definition-owners test with main's
`tests/unit/profile` and the two draw-site catalogue tests: 5174 passed, 0 failed, 40 skipped. Script checks
(`registry_renumber.py --check --main origin/main`, `ratchet_check.py --base origin/main`,
`check_fragment.py --base origin/main`, `reason_release_pin.py --check`): each exit 0.
`generation/synthesize.py` 596 lines; the engine root and `config/` hold 25 modules,
`profile/` 19.

Not run: the full T1 gate on this head, mutations and the full suite.

## Main merge (2026-11-15, `a7f278eb`), carried forward

`origin/feat/gen-rel-e3b` `95797b8f` merged into `8899b393` as `43549869`, without a conflict. It
carries `origin/main` `a7f278eb` (#600, #582 one seed path for every seeded generator, #489
durable publication units) and slice 2's re-pin of the draw-site catalogue, which this slice does
not touch: `tests/native/test_draw_sites_catalogue_pinned.py` comes in as slice 2 resolved it
(both "Re-pinned for ..." lines, `_CATALOGUE_DIGEST` recomputed by the file's procedure) and
passes on this tree. Main's change touches no source file of this slice, and main's seed sentry
(`tests/sentry/defects/test_rng_construction.py`) passes over it.

Checks on `43549869`, Python 3.10.20, `origin/main` `a7f278eb`: ruff and format on the changed
files pass; mypy clean (890 files); `tests/sentry` 5851 passed, 0 failed, 2 skipped; layers 15
passed; `tests/unit/config`, `tests/unit/execution/test_mem_estimate.py`,
`tests/unit/generation`, `tests/unit/plan` (with the late-formula module), `tests/unit/generators`,
the numeric-typing parity files and the definition-owners test with the two draw-site
catalogue tests: 4588 passed, 0 failed, 40 skipped. Script checks (`registry_renumber.py`,
`ratchet_check.py`, `check_fragment.py`, `reason_release_pin.py --check`): each exit 0.
`generation/synthesize.py` 596 lines; the engine root and `config/` hold 25 modules.

Not run: the full T1 gate on this head, mutations and the full suite.

## Main merge (2026-11-16, `1c8e413c`), carried forward

`origin/feat/gen-rel-e3b` `ce151c92` (holding `origin/main` `1c8e413c`) merged into `ef6198b7` as `0cb17c93`, without a conflict. `origin/main` `1c8e413c` (#496) adds
the `publication/` package (the `decoy-publication/v1` descriptor codec and receipt types),
places it in the `execution` tier of `.importlinter` and the layer snapshot (this chain's
`_capacity` entry in the bottom tier is unchanged), extends `_canonical` and adds a strict-JSON
sentry. It touches no source or test file of this slice and not the draw-site catalogue.

Checks on `0cb17c93`, Python 3.10.20, `origin/main` `1c8e413c`: ruff and format on the changed
files pass; mypy clean (893 files); `tests/sentry` 5869 passed, 0 failed, 2 skipped; layers 15 passed; `tests/unit/config`, `tests/unit/execution/test_mem_estimate.py`, `tests/unit/generation`, `tests/unit/plan` (with the late-formula module), `tests/unit/generators`, the numeric-typing parity files and the definition-owners test with the two
draw-site catalogue tests: 4588 passed, 0 failed, 40 skipped. Script checks (`registry_renumber.py --check --main
origin/main`, `ratchet_check.py --base origin/main`, `check_fragment.py --base origin/main`,
`reason_release_pin.py --check`): each exit 0. `generation/synthesize.py` 596 lines; the
engine root and `config/` hold 25 modules, `publication/` 2.

Not run: the full T1 gate on this head, mutations and the full suite.

## Main merge (2026-11-16, `ddd014a5`), carried forward

`origin/feat/gen-rel-e3b` `8faf6090` (holding `origin/main` `ddd014a5`, release 0.27.0) merged into `21e827b6`
as `80f933ed`, without a conflict. Main's twelve commits after `1c8e413c` (publication judge and
bind, the sink state table, `publish_unit` through the sink and the isolated route, resume
store records, the pre-scan model pass, lazy-input streaming, the scratch arena move and the
frozen-surface map) do not touch the draw-site catalogue. Of this slice's files main touches `config/__init__.py` (the `post_scan_ner_findings` export), `docs/reasons.md` (the thirteen F22 output-publication additions paragraph) and the physical-seam sentry (its own run-stream entries); each merged beside this slice's lines.
The release consumed main's changelog fragments; this chain's fragments are kept. The
`generation/_streamed.py` comment rewording that holds it at 600 lines arrives from gen-rel-e1.

Checks on `80f933ed`, Python 3.10.20, `origin/main` `ddd014a5`: ruff, format and mypy pass;
`tests/sentry` 5974 passed, 0 failed, 2 skipped; layers 15 passed; `tests/unit/generation`
with the tests of this slice and the slices below it, the two draw-site catalogue tests and the fan-out sentry: 4985
passed, 0 failed, 43 skipped. Script checks (`registry_renumber.py --check --main ddd014a5`,
`ratchet_check.py --base ddd014a5`, `check_fragment.py --base ddd014a5`,
`reason_release_pin.py --check`): each exit 0. `generation/synthesize.py` 596 lines,
`generation/_streamed.py` 600; the engine root and `config/` hold 25 modules.

Not run: the full T1 gate on this head, mutations and the full suite.

## Main merge (2026-11-16, `13c95c7d`), carried forward

`origin/feat/gen-rel-e3b` `33dc4f8a` (holding `origin/main` `13c95c7d`) merged into `92bee24e` as `11f9ec31`, without a
conflict. Main's two commits after `ddd014a5` (run-stream E5b, the no-sink collector scratch
opened on first spill, and F22 b1, the durable vault adopt and `VaultCommit`) do not touch the
draw-site catalogue, `.importlinter`, `uv.lock` or `generation/`. Of this slice's files main touches `CODEMAP.md` (the no-sink collector spill row and the `internal/` row); it merged beside this slice's lines. Main's two changelog
fragments arrive beside this chain's, which are kept. gen-rel-e1 narrows the three orphan-policy refusal
tests in `tests/property/test_ri_graph_invariants.py` to the reason code and field (owner
ruling A); the refusal source is unchanged.

Checks on `11f9ec31`, Python 3.10.20, `origin/main` `13c95c7d`: ruff, format and mypy pass;
`tests/sentry` 5982 passed, 0 failed, 2 skipped; layers 15 passed; `tests/unit/generation`
with the tests of this slice and the slices below it, the two draw-site catalogue tests and the
fan-out sentry: 5022 passed, 0 failed, 43 skipped; `tests/property/test_ri_graph_invariants.py`
35 passed. Script checks (`registry_renumber.py --check --main origin/main`,
`ratchet_check.py --base origin/main`, `check_fragment.py --base origin/main`,
`reason_release_pin.py --check`): each exit 0. `generation/synthesize.py` 596 lines,
`generation/_streamed.py` 600; the engine root and `config/` hold 25 modules.

Not run: the full T1 gate on this head, mutations and the full suite.

## Main merges (2026-11-16, `b886c61d`, `57f5d25f` and `85429533`), carried forward

`origin/main` moved three times after the `13c95c7d` merge: `b886c61d` (#613, the scan-checks
evidence baseline member and `on_drift` surface; #614, the README; #615, generate-only edges
take a derived namespace), `57f5d25f` (#612, the date-shift MD5 offset path deleted and the
unkeyed refusal pinned) and `85429533` (#611, the distribution behavior table moved from
`execution/` to `contracts/`). gen-rel-e1 merged each in turn and the gen-rel slices carried
them forward. `origin/feat/gen-rel-e3b` `3452a9a9` (holding `origin/main` `85429533`) merged into
`57a73de3` as `92279cb9`, without a conflict. The `reasons/warning/_part1.py` and draw-site
catalogue pin resolutions arrive from gen-rel-e1 and gen-rel-e2. Of this slice's files main
touches `docs/strategies.md` and `CODEMAP.md`; each merged beside this slice's lines. Main's
census, baseline, fan-out and import-layer changes are its own deletions; nothing of this
chain's grows. Main does not touch `uv.lock` or `generation/`. Main's changelog fragments arrive
beside this chain's, which are kept.

Checks on `92279cb9`, Python 3.10.20, `origin/main` `85429533`: ruff, format and mypy pass;
`tests/sentry` 6001 passed, 0 failed, 2 skipped; layers 15 passed; `tests/unit/generation`
with the tests of this slice and the slices below it, the two draw-site catalogue tests and the
fan-out sentry: 5022 passed, 0 failed, 43 skipped; `tests/property/test_ri_graph_invariants.py`
35 passed. Script checks (`registry_renumber.py --check --main origin/main`,
`ratchet_check.py --base origin/main`, `check_fragment.py --base origin/main`,
`reason_release_pin.py --check`): each exit 0. `generation/synthesize.py` 596 lines,
`generation/_streamed.py` 600; the engine root and `config/` hold 25 modules.

Not run: the full T1 gate on this head, mutations and the full suite.

## Main merge (2026-11-17, `dda1b61f`), gate and mutations on the exact head

`origin/main` `dda1b61f` (16 commits after `85429533`: #609 to #634) merged into `e9a209d1` as
`bf392a09`. GEN-REL has not taken this main yet, so the merge goes straight into this slice and
the PR diff against `feat/gen-rel-e3b` shows main's 16 commits until gen-rel-e3b holds them too.
Three conflicts, both sides kept:

- `execution/native/_draw_sites_gen.py`: main's #628 keys call sites by `path::function[#n]`.
  The two `gen.reference` mirrors GEN-REL added (`_cardinality.py:198`,
  `_self_reference.py:86`) became `generation/relational/_cardinality.py::apply_cardinality_bounds`
  and `generation/relational/_self_reference.py::self_reference`; both resolve under main's
  `call_site_problems`.
- `generation/statistical/__init__.py`: main's `degenerate_finding` beside `fallback_counts`.
- `tests/native/test_draw_sites_catalogue_pinned.py`: main's per-id layout; the `gen.reference`
  entry digest and the whole-catalogue digest re-pinned by the file's procedure. No other entry
  or map digest moved.

Main's changes to this slice's anchor files are outside the mutated code: `statistical/_sample.py`
gains `check_degenerate` in `sample_column` (not `select_table` or `fallback_counts`), and
`pool/_events.py` a docstring line.

Gate on `bf392a09`: `GATES_WORKERS=4 scripts/dev/gates.sh --keep-going --baseline` (the
selection against `origin/main`, 1319 paths), Python 3.10.20. ruff, format and mypy pass; sentry
6082 passed, 0 failed, 2 skipped; layers 15 passed; licenses 63 passed; tests 43342 passed, 26
failed, 112 errors, 5384 skipped. Baseline `origin/main` `dda1b61f` on the same path list: the
same 138 ids fail. Branch-only failures: 0. The 138 are main's red `reason_release_pin` (8
`connector.*` rules from #624 differ from the release pin; `test_reason_release_pin.py`,
`test_stamp_release_compile.py`) and the scratch-permission tests (`tests/fileaccess/scratch`,
`tests/unit/execution/scratch`, `test_scratch_root_umask.py`), which error in this container on
main too.

Script checks against `origin/main` `dda1b61f`: `registry_renumber.py --check` 0;
`ratchet_check.py` 0; `check_fragment.py` 0; `reason_release_pin.py --check` 1 with the same 8
`connector.*` lines as `origin/main`, none from this chain.

Mutations: 29 of 29 red on `bf392a09` (M1 to M22, B1 to B4, F1 to F3), detached worktree
importing its own `src`, Python 3.10.20, every anchor matched once, the tree clean after each.
Each mutant ran the eight slice files (`test_conditional_categorical.py`,
`test_generate_options.py`, `test_generate_columns.py`, `test_generate_columns_late_formula.py`,
`test_mem_estimate.py`, `test_condition_fallback.py`, `test_aggregate_input.py`,
`test_reason_minor_fixtures.py`); unmutated 540 passed. Red counts: M1 3, M2 8, M3 10, M4 5,
M5 16, M6 1, M7 19, M8 2, M9 11, M10 3, M11 2, M12 2, M13 2, M14 1, M15 6, M16 1, M17 2, M18 1,
M19 1, M20 6, M21 2, M22 1, B1 1, B2 1, B3 4, B4 1, F1 4, F2 1, F3 3. Counts are over the eight
files, so several exceed the per-witness counts recorded earlier; every earlier witness is in its
mutant's red set. The harness was rebuilt from the mutation tables above (the earlier harness was
not kept).

`generation/synthesize.py` 596 lines. Not run: the full suite, Python 3.11.
