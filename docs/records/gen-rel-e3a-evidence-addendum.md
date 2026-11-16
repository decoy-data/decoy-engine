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

## Main merge (2026-11-15, `a7f278eb`), carried forward

`origin/feat/gen-rel-e2` `f3020cf6` merged into `702276a4` as `d5ccef41`, without a conflict. It
carries `origin/main` `a7f278eb` (#600, #582 one seed path for every seeded generator, #489
durable publication units) and slice 2's re-pin of the draw-site catalogue, which this slice does
not touch: `tests/native/test_draw_sites_catalogue_pinned.py` comes in as slice 2 resolved it
(both "Re-pinned for ..." lines, `_CATALOGUE_DIGEST` recomputed by the file's procedure) and
passes on this tree. Main's change touches no source file of this slice, and main's seed sentry
(`tests/sentry/defects/test_rng_construction.py`) passes over it.

Checks on `d5ccef41`, Python 3.10.20, `origin/main` `a7f278eb`: ruff and format on the changed
files pass; mypy clean (888 files); `tests/sentry` 5828 passed, 0 failed, 2 skipped; layers 15
passed; this slice's test files and their neighbours (the numeric-typing parity files,
`tests/unit/config`, `tests/unit/expressions`, `tests/unit/generation`, `tests/unit/plan`,
`tests/unit/generators`, the derived, windowed-date and timedelta tests) with the two draw-site
catalogue tests: 4544 passed, 0 failed, 40 skipped. Script checks (`registry_renumber.py`,
`ratchet_check.py`, `check_fragment.py`, `reason_release_pin.py --check`): each exit 0.
`generation/synthesize.py` 599 lines; the engine root and `config/` hold 25 modules.

Not run: the full T1 gate on this head, mutations and the full suite.

## Main merge (2026-11-16, `1c8e413c`), carried forward

`origin/feat/gen-rel-e2` `2fab1276` (holding `origin/main` `1c8e413c`) merged into `9251cc7b` as `955684c8`, without a conflict. `origin/main` `1c8e413c` (#496) adds
the `publication/` package (the `decoy-publication/v1` descriptor codec and receipt types),
places it in the `execution` tier of `.importlinter` and the layer snapshot (this chain's
`_capacity` entry in the bottom tier is unchanged), extends `_canonical` and adds a strict-JSON
sentry. It touches no source or test file of this slice and not the draw-site catalogue.

Checks on `955684c8`, Python 3.10.20, `origin/main` `1c8e413c`: ruff and format on the changed
files pass; mypy clean (891 files); `tests/sentry` 5846 passed, 0 failed, 2 skipped; layers 15 passed; this slice's test files and their neighbours (the numeric-typing parity files, `tests/unit/config`, `tests/unit/expressions`, `tests/unit/generation`, `tests/unit/plan`, `tests/unit/generators`, the derived, windowed-date and timedelta tests) with the two
draw-site catalogue tests: 4544 passed, 0 failed, 40 skipped. Script checks (`registry_renumber.py --check --main
origin/main`, `ratchet_check.py --base origin/main`, `check_fragment.py --base origin/main`,
`reason_release_pin.py --check`): each exit 0. `generation/synthesize.py` 599 lines; the
engine root and `config/` hold 25 modules, `publication/` 2.

Not run: the full T1 gate on this head, mutations and the full suite.

## Main merge (2026-11-16, `ddd014a5`), carried forward

`origin/feat/gen-rel-e2` `b235ec73` (holding `origin/main` `ddd014a5`, release 0.27.0) merged into `ac2495e6`
as `3cfb05cd`, with one documentation conflict: `docs/reasons.md`, where main added the thirteen F22 output-publication additions paragraph and this slice added the GEN-REL E3a paragraph at the same place; both are kept, main's first. Main's twelve commits after `1c8e413c` (publication judge and
bind, the sink state table, `publish_unit` through the sink and the isolated route, resume
store records, the pre-scan model pass, lazy-input streaming, the scratch arena move and the
frozen-surface map) do not touch the draw-site catalogue. Of this slice's files main touches `config/__init__.py` (the `post_scan_ner_findings` export), `reason_adapter.py` and `tests/sentry/test_reason_registry.py` (its publication and resume adapters), the secret-material census (line moves in main's files) and the sentry manifest; each merged beside this slice's lines.
The release consumed main's changelog fragments; this chain's fragments are kept. The
`generation/_streamed.py` comment rewording that holds it at 600 lines arrives from gen-rel-e1.

Checks on `3cfb05cd`, Python 3.10.20, `origin/main` `ddd014a5`: ruff, format and mypy pass;
`tests/sentry` 5951 passed, 0 failed, 2 skipped; layers 15 passed; `tests/unit/generation`
with the tests of this slice and the slices below it, the two draw-site catalogue tests and the fan-out sentry: 4613
passed, 0 failed, 43 skipped. Script checks (`registry_renumber.py --check --main ddd014a5`,
`ratchet_check.py --base ddd014a5`, `check_fragment.py --base ddd014a5`,
`reason_release_pin.py --check`): each exit 0. `generation/synthesize.py` 599 lines,
`generation/_streamed.py` 600; the engine root and `config/` hold 25 modules.

Not run: the full T1 gate on this head, mutations and the full suite.

## Main merge (2026-11-16, `13c95c7d`), carried forward

`origin/feat/gen-rel-e2` `f4973ba7` (holding `origin/main` `13c95c7d`) merged into `7d6502bb` as `9a109b47`, without a
conflict. Main's two commits after `ddd014a5` (run-stream E5b, the no-sink collector scratch
opened on first spill, and F22 b1, the durable vault adopt and `VaultCommit`) do not touch the
draw-site catalogue, `.importlinter`, `uv.lock` or `generation/`. Of this slice's files main touches `CODEMAP.md` (the no-sink collector spill row and the `internal/` row) and the secret-material census (line moves in main's `vault.py`); each merged beside this slice's lines. Main's two changelog
fragments arrive beside this chain's, which are kept. gen-rel-e1 narrows the three orphan-policy refusal
tests in `tests/property/test_ri_graph_invariants.py` to the reason code and field (owner
ruling A); the refusal source is unchanged.

Checks on `9a109b47`, Python 3.10.20, `origin/main` `13c95c7d`: ruff, format and mypy pass;
`tests/sentry` 5959 passed, 0 failed, 2 skipped; layers 15 passed; `tests/unit/generation`
with the tests of this slice and the slices below it, the two draw-site catalogue tests and the
fan-out sentry: 4650 passed, 0 failed, 43 skipped; `tests/property/test_ri_graph_invariants.py`
35 passed. Script checks (`registry_renumber.py --check --main origin/main`,
`ratchet_check.py --base origin/main`, `check_fragment.py --base origin/main`,
`reason_release_pin.py --check`): each exit 0. `generation/synthesize.py` 599 lines,
`generation/_streamed.py` 600; the engine root and `config/` hold 25 modules.

Not run: the full T1 gate on this head, mutations and the full suite.
