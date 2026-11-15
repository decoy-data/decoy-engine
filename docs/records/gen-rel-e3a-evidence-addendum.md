# GEN-REL E3a build evidence: addendum

This companion to [the GEN-REL E3a build evidence](gen-rel-e3a-evidence.md) holds the sections
added after the primary record reached 800 lines.

## Main merge (2026-11-15), carried forward

`origin/feat/gen-rel-e2` `04f7e4a8` merged into `a920292e` as `f70c271f`. It carries
`origin/main` `38fddb2f` (through #597) and slice 1's move of `_capacity` and
`config/_generate_relational` into packages (each module unchanged as the package's
`__init__.py`, so the engine root and `config/` stay at the fan-out cap of 25). Git carried this
slice's version of `config/_generate_relational.py` (the parent lookups and
`iter_generate_input_refs`) into the moved `__init__.py` byte for byte.

Conflicts, resolved keeping both sides:

- `CODEMAP.md`: this slice's `config/` row with the package wording, and main's `plan/` row
  (`checks/_formula_types.py`).
- `docs/reasons.md`: main's CONFIG-EXPLICIT E2b-s paragraph, then this slice's paragraph.
- `execution/_runner.py`: main's `_masked_driver_columns` (#571) now asks
  `scalar_creating_reads`; the `derived` branch this slice had pointed at
  `expressions.column_refs` is gone with it, and `execution/_column_access.py`, which main's
  version reads, already calls `column_refs` (merged without a conflict).
- `transforms/derived.py`: this slice's `column_refs` import with main's `is_null_cell`; main's
  `_is_null = is_null_cell` (#564) replaces the local `_is_null`; `_get_column_refs` stays
  removed, as this slice moved it to `expressions.column_refs` and nothing else calls it.
- `generation/_numeric_typing.py`: imports `Collection` (main) and drops `re` (this slice's
  resolver replaced `_IDENTIFIER`). Main's `reader_types` and the safe `formula.references`
  reader (#574) sit beside this slice's `_readers` over `iter_generate_input_refs`; a formula's
  reference edge has the registry id `formula.references`, so the two agree.
- `plan/checks/_generate_columns.py`: main's `_check_formula(..., types)` keeps this slice's
  order (formula rules, then `_check_input_edges`).
- `tests/sentry/defects/test_sequence_key_predicate.py` keeps this slice's caller
  `parent_key_problem`; it and `tests/sentry/defects/test_generate_input_edges.py`
  (`RESOLVER_FILE`) name the new path `config/_generate_relational/__init__.py`.

Checks on `f70c271f`, Python 3.10.20, `origin/main` `38fddb2f`: ruff and format on the changed
files pass; mypy clean (884 files); `tests/sentry` 5738 passed, 0 failed, 2 skipped; layers 15
passed; this slice's test files and their neighbours (`tests/parity/test_numeric_typing_readers.py`,
`tests/parity/test_numeric_typing_fk.py`, `tests/unit/config`, `tests/unit/expressions`,
`tests/unit/generation`, `tests/unit/plan`, `tests/unit/generators`,
`tests/unit/test_numpy_generic_timedelta.py`, `tests/unit/transforms/test_derived.py`,
`tests/unit/transforms/test_windowed_date.py`, main's
`tests/unit/execution/test_created_derive_chain.py` and `test_derived_strategy.py`) with the two
draw-site catalogue tests: 4572 passed, 0 failed, 40 skipped. Script checks
(`registry_renumber.py --check --main origin/main`, `ratchet_check.py --base origin/main`,
`check_fragment.py --base origin/main`, `reason_release_pin.py --check`): each exit 0.
`generation/synthesize.py` is 599 lines; the engine root and `config/` hold 25 modules each.

Not run: the full T1 gate on this head, mutations and the full suite.

## Main merge (2026-11-15, `64e9349b`), carried forward

`origin/feat/gen-rel-e2` `d5962c3c` merged into `233a54bb` as `4c2d8048`, without a conflict. It carries
`origin/main` `64e9349b` (#598, one format table for resident and lazy file sources), whose
change is in `profile/`, `fileaccess/` and their sentries; it touches no source or test file of
this slice (`CODEMAP.md`'s `profile/` row and the sentry manifest merged beside this slice's
lines).

Checks on `4c2d8048`, Python 3.10.20, `origin/main` `64e9349b`: ruff and format on the changed
files pass; mypy clean (885 files); `tests/sentry` 5762 passed, 0 failed, 2 skipped; layers 15 passed; this slice's test files and their neighbours (the numeric-typing parity files, `tests/unit/config`, `tests/unit/expressions`, `tests/unit/generation`, `tests/unit/plan`, `tests/unit/generators`, the derived, windowed-date and timedelta tests) with main's
`tests/unit/profile` and the two draw-site catalogue tests: 5130 passed, 0 failed, 40 skipped. Script checks
(`registry_renumber.py --check --main origin/main`, `ratchet_check.py --base origin/main`,
`check_fragment.py --base origin/main`, `reason_release_pin.py --check`): each exit 0.
`generation/synthesize.py` 599 lines; the engine root and `config/` hold 25 modules,
`profile/` 19.

Not run: the full T1 gate on this head, mutations and the full suite.
