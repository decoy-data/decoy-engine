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

## Main merge (2026-11-15, `64e9349b`), carried forward

`origin/feat/gen-rel-e1` `9a0b1181` merged into `04f7e4a8` as `814252f0`, without a conflict. It carries
`origin/main` `64e9349b` (#598, one format table for resident and lazy file sources), whose
change is in `profile/`, `fileaccess/` and their sentries; it touches no source or test file of
this slice (`CODEMAP.md`'s `profile/` row and the sentry manifest merged beside this slice's
lines).

Checks on `814252f0`, Python 3.10.20, `origin/main` `64e9349b`: ruff and format on the changed
files pass; mypy clean (884 files); `tests/sentry` 5717 passed, 0 failed, 2 skipped; layers 15 passed; this slice's test files (`tests/unit/config/test_generate_relational.py`, `tests/unit/execution/test_probe_scale.py`, `tests/unit/generation/relational`, `tests/unit/generation/test_generation_order.py`, `tests/unit/generation/test_pinned_generation.py`, `tests/unit/plan`, the unique old-input-bytes pins) with main's
`tests/unit/profile` and the two draw-site catalogue tests: 1897 passed, 0 failed. Script checks
(`registry_renumber.py --check --main origin/main`, `ratchet_check.py --base origin/main`,
`check_fragment.py --base origin/main`, `reason_release_pin.py --check`): each exit 0.
`generation/synthesize.py` 596 lines; the engine root and `config/` hold 25 modules,
`profile/` 19.

Not run: the full T1 gate on this head, mutations and the full suite.

## Main merge (2026-11-15, `a7f278eb`), carried forward

`origin/feat/gen-rel-e1` `1bccfb8a` merged into `d5962c3c` as `3a3f13a0`. It carries `origin/main` `a7f278eb`
(#600, #582 one seed path for every seeded generator, #489 durable publication units).

One conflict, `tests/native/test_draw_sites_catalogue_pinned.py`: this slice's
"Re-pinned for GEN-REL E2" line and main's DUP-FREEZE E2 line (two `joint_mask` stream sites and the
`gen.composite_build_pool` seed text) are both kept. The ordered ids, entry digests and
coverage-map digests merged without a conflict and each matches the merged catalogue;
`_CATALOGUE_DIGEST` is recomputed by the file's procedure (SHA-256 over
`repr(protocol.DRAW_SITES)`) on the merged tree: `fce3b00f...`. No other file conflicted;
main's change touches no source file of this slice, and main's seed sentry
(`tests/sentry/defects/test_rng_construction.py`) passes over it.

Checks on `3a3f13a0`, Python 3.10.20, `origin/main` `a7f278eb`: ruff and format on the changed
files pass; mypy clean (887 files); `tests/sentry` 5783 passed, 0 failed, 2 skipped; layers 15 passed; this slice's test files (`tests/unit/config/test_generate_relational.py`, `tests/unit/execution/test_probe_scale.py`, `tests/unit/generation/relational`, the generation-order, pinned and unique old-input-bytes tests, `tests/unit/plan`) and main's seed sentry with the two
draw-site catalogue tests: 1306 passed, 0 failed. Script checks (`registry_renumber.py --check --main
origin/main`, `ratchet_check.py --base origin/main`, `check_fragment.py --base origin/main`,
`reason_release_pin.py --check`): each exit 0. `generation/synthesize.py` 596 lines; the
engine root and `config/` hold 25 modules.

Not run: the full T1 gate on this head, mutations and the full suite.

## Main merge (2026-11-16, `1c8e413c`), carried forward

`origin/feat/gen-rel-e1` `a71617b6` (holding `origin/main` `1c8e413c`) merged into `f3020cf6` as `5d63c488`, without a conflict. `origin/main` `1c8e413c` (#496) adds
the `publication/` package (the `decoy-publication/v1` descriptor codec and receipt types),
places it in the `execution` tier of `.importlinter` and the layer snapshot (this chain's
`_capacity` entry in the bottom tier is unchanged), extends `_canonical` and adds a strict-JSON
sentry. It touches no source or test file of this slice and not the draw-site catalogue.

Checks on `5d63c488`, Python 3.10.20, `origin/main` `1c8e413c`: ruff and format on the changed
files pass; mypy clean (890 files); `tests/sentry` 5801 passed, 0 failed, 2 skipped; layers 15 passed; this slice's test files (`tests/unit/config/test_generate_relational.py`, `tests/unit/execution/test_probe_scale.py`, `tests/unit/generation/relational`, the generation-order, pinned and unique old-input-bytes tests, `tests/unit/plan`) with the two
draw-site catalogue tests: 1279 passed, 0 failed. Script checks (`registry_renumber.py --check --main
origin/main`, `ratchet_check.py --base origin/main`, `check_fragment.py --base origin/main`,
`reason_release_pin.py --check`): each exit 0. `generation/synthesize.py` 596 lines; the
engine root and `config/` hold 25 modules, `publication/` 2.

Not run: the full T1 gate on this head, mutations and the full suite.

## Main merge (2026-11-16, `ddd014a5`), carried forward

`origin/feat/gen-rel-e1` `a0fee945` (holding `origin/main` `ddd014a5`, release 0.27.0) merged into `2fab1276`
as `e033c67c`, without a conflict. Main's twelve commits after `1c8e413c` (publication judge and
bind, the sink state table, `publish_unit` through the sink and the isolated route, resume
store records, the pre-scan model pass, lazy-input streaming, the scratch arena move and the
frozen-surface map) do not touch the draw-site catalogue. Of this slice's files main touches `config/__init__.py` (the `post_scan_ner_findings` export), `docs/reasons.md`, the sentry manifest and the physical-seam sentry (its own new entries); each merged beside this slice's lines.
The release consumed main's changelog fragments; this chain's fragments are kept. The
`generation/_streamed.py` comment rewording that holds it at 600 lines arrives from gen-rel-e1.

Checks on `e033c67c`, Python 3.10.20, `origin/main` `ddd014a5`: ruff, format and mypy pass;
`tests/sentry` 5906 passed, 0 failed, 2 skipped; layers 15 passed; `tests/unit/generation`
with the tests of this slice and the slices below it, the two draw-site catalogue tests and the fan-out sentry: 3799
passed, 0 failed, 43 skipped. Script checks (`registry_renumber.py --check --main origin/main`,
`ratchet_check.py --base origin/main`, `check_fragment.py --base origin/main`,
`reason_release_pin.py --check`): each exit 0. `generation/synthesize.py` 596 lines,
`generation/_streamed.py` 600; the engine root and `config/` hold 25 modules.

Not run: the full T1 gate on this head, mutations and the full suite.

## Main merge (2026-11-16, `13c95c7d`), carried forward

`origin/feat/gen-rel-e1` `312c12ab` (holding `origin/main` `13c95c7d`) merged into `b235ec73` as `f494c72c`, without a
conflict. Main's two commits after `ddd014a5` (run-stream E5b, the no-sink collector scratch
opened on first spill, and F22 b1, the durable vault adopt and `VaultCommit`) do not touch the
draw-site catalogue, `.importlinter`, `uv.lock` or `generation/`. Main touches none of this slice's files. Main's two changelog
fragments arrive beside this chain's, which are kept. gen-rel-e1 narrows the three orphan-policy refusal
tests in `tests/property/test_ri_graph_invariants.py` to the reason code and field (owner
ruling A); the refusal source is unchanged.

Checks on `f494c72c`, Python 3.10.20, `origin/main` `13c95c7d`: ruff, format and mypy pass;
`tests/sentry` 5914 passed, 0 failed, 2 skipped; layers 15 passed; `tests/unit/generation`
with the tests of this slice and the slices below it, the two draw-site catalogue tests and the
fan-out sentry: 3836 passed, 0 failed, 43 skipped; `tests/property/test_ri_graph_invariants.py`
35 passed. Script checks (`registry_renumber.py --check --main origin/main`,
`ratchet_check.py --base origin/main`, `check_fragment.py --base origin/main`,
`reason_release_pin.py --check`): each exit 0. `generation/synthesize.py` 596 lines,
`generation/_streamed.py` 600; the engine root and `config/` hold 25 modules.

Not run: the full T1 gate on this head, mutations and the full suite.
