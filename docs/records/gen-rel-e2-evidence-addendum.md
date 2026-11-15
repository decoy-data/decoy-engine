# GEN-REL E2 build evidence: addendum

This companion to [the GEN-REL E2 build evidence](gen-rel-e2-evidence.md) holds the sections
added after the primary record reached 800 lines.

## Main merge (2026-11-15), carried forward

`origin/feat/gen-rel-e1` `36e20e9e` merged into `1b33bc6d` as `48609197`. It carries
`origin/main` `38fddb2f` (through #597) and e1's move of `_capacity` and
`config/_generate_relational` into packages (each module unchanged as the package's
`__init__.py`, so the engine root and `config/` stay at the fan-out cap of 25); the e1 merge
record is in [gen-rel-e1-evidence-addendum.md](gen-rel-e1-evidence-addendum.md).

- Conflict: `config/__init__.py` `__all__` only (`relationship_shape_error` from main beside this
  slice's `self_reference_problems`), resolved keeping both, sorted.
- Git carried this slice's additions to `config/_generate_relational.py` (the self-reference
  checks, `is_exact_sequence_key`, `_tree_problem`) into the moved `__init__.py`: its content
  equals this slice's module byte for byte, so the `output_type` refusal in `_tree_problem` is
  intact.
- In the merge commit, `tests/sentry/defects/test_sequence_key_predicate.py` names the owner and
  the caller by the new path `config/_generate_relational/__init__.py`. With the old path the
  predicate's own definition would be scanned as a restatement and the caller check would read a
  missing file.
- Read hunk by hunk against both parents: `synthesize.py` keeps this slice's
  `is_self_reference` import beside main's `reader_types`, and `plan/checks/_generate_columns.py`
  keeps this slice's weights check beside main's formula-type check (#574).

Checks on `48609197`, Python 3.10.20, `origin/main` `38fddb2f`: ruff and format on the changed
files pass; mypy clean (883 files); `tests/sentry` (the gate's sentry step) 5693 passed, 0
failed, 2 skipped; layers 15 passed; this slice's test files
(`tests/unit/config/test_generate_relational.py`,
`tests/unit/execution/test_probe_scale.py`, `tests/unit/generation/relational`,
`tests/unit/generation/test_generation_order.py`, `tests/unit/generation/test_pinned_generation.py`,
`tests/unit/plan`, the GEN-UNIQUE old-input-bytes pins) with
`tests/native/test_draw_site_inventory_coverage.py` and
`tests/native/test_draw_sites_catalogue_pinned.py`: 1279 passed, 0 failed. Script checks:
`registry_renumber.py --check --main origin/main`, `ratchet_check.py --base origin/main`,
`check_fragment.py --base origin/main` and `reason_release_pin.py --check` each exit 0.
`generation/synthesize.py` is 596 lines; the engine root and `config/` hold 25 modules each.

Not run: the full T1 gate on this head, mutations and the full suite.
