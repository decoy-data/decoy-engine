# GEN-REL E3b build evidence: addendum

This companion to [the GEN-REL E3b build evidence](gen-rel-e3b-evidence.md) holds the sections
added after the primary record passed 800 lines.

## Main merge (2026-11-15), carried forward

`origin/feat/gen-rel-e3a` `233a54bb` merged into `e1d8a024` as `f38de86b`. It carries
`origin/main` `38fddb2f` (through #597) and slice 1's move of `_capacity` and
`config/_generate_relational` into packages (each module unchanged as the package's
`__init__.py`, so the engine root and `config/` stay at the fan-out cap of 25). Git carried this
slice's version of `config/_generate_relational.py` into the moved `__init__.py`.

Conflicts, resolved keeping both sides:

- `CODEMAP.md`: this slice's `config/` row with the package wording, and main's `plan/` row
  (`checks/_formula_types.py`).
- `config/__init__.py`: both export lists, sorted.
- `reasons/config/_part2.py`: main's `CanonicalJsonError` block and `target_shared_destination`
  stay as main has them; this slice's two `UNRELEASED` aggregate codes follow, still under the
  `PipelineValidationError` family.
- `generation/_numeric_typing.py`: main split `numeric_plan` into `_base_types`,
  `_generated_type` and `reader_types` (#574); this slice had moved the reference-root walk and
  the non-candidate type to `config.reference_root` and `config.generated_arrow_type`. The
  merge keeps main's structure and calls this slice's two helpers in `_generated_type`, whose
  branches are the ones the old inline code had.
- `tests/sentry/defects/test_generate_input_edges.py` names `_reads_aggregate` by the new path
  `config/_generate_relational/__init__.py`.

`generation/synthesize.py` was 600 lines on this slice and main adds one
(`types = reader_types(...)` for the formula post-pass), so the merge held 601 and
`test_module_within_size_budget` failed. `types` has one use, but passing the call inline does
not fit in 100 characters at that indent and formats to 607 lines. `b9beaf25`
(`refactor(generation): keep the post-pass import on one line`) instead writes the lazy
`fill_referenced_formula_columns` import of the post-pass on one line (99 characters): the same
import in the same place, formatting only. The module is 599 lines.

Checks on `b9beaf25`, Python 3.10.20, `origin/main` `38fddb2f`: ruff and format pass; mypy
clean (885 files); `tests/sentry` 5752 passed, 0 failed, 2 skipped (the module-size cell
passes); layers 15 passed; this slice's test files and their neighbours
(`tests/parity/test_numeric_typing_readers.py`, `tests/parity/test_numeric_typing_fk.py`,
`tests/unit/config`, `tests/unit/generation`, `tests/unit/plan`, `tests/unit/generators`,
`tests/unit/transforms/test_derived_aggregate.py`, `tests/unit/transforms/test_derived.py`,
`tests/unit/test_wave_b_definition_owners.py`) with the two draw-site catalogue tests: 4536
passed, 0 failed, 40 skipped. On `f38de86b` the same runs gave sentry 5751 passed and 1 failed
(the module-size cell) and 4534 passed. Script checks (`registry_renumber.py --check --main
origin/main`, `ratchet_check.py --base origin/main`, `check_fragment.py --base origin/main`,
`reason_release_pin.py --check`): each exit 0. The engine root and `config/` hold 25 modules
each.

Not run: the full T1 gate on this head, mutations and the full suite.

## Main merge (2026-11-15, `64e9349b`), carried forward

`origin/feat/gen-rel-e3a` `702276a4` merged into `4861862c` as `c90f6567`, without a conflict. It carries
`origin/main` `64e9349b` (#598, one format table for resident and lazy file sources), whose
change is in `profile/`, `fileaccess/` and their sentries; it touches no source or test file of
this slice (`CODEMAP.md`'s `profile/` row and the sentry manifest merged beside this slice's
lines).

Checks on `c90f6567`, Python 3.10.20, `origin/main` `64e9349b`: ruff and format on the changed
files pass; mypy clean (886 files); `tests/sentry` 5776 passed, 0 failed, 2 skipped (the module-size cell passes); layers 15 passed; this slice's test files and their neighbours (the numeric-typing parity files, `tests/unit/config`, `tests/unit/generation`, `tests/unit/plan`, `tests/unit/generators`, the derived and aggregate transforms, the definition-owners test) with main's
`tests/unit/profile` and the two draw-site catalogue tests: 5154 passed, 0 failed, 40 skipped. Script checks
(`registry_renumber.py --check --main origin/main`, `ratchet_check.py --base origin/main`,
`check_fragment.py --base origin/main`, `reason_release_pin.py --check`): each exit 0.
`generation/synthesize.py` 599 lines; the engine root and `config/` hold 25 modules,
`profile/` 19.

Not run: the full T1 gate on this head, mutations and the full suite.
