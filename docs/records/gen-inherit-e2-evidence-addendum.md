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
