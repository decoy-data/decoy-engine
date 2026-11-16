# GEN-REL E1 build evidence: merge and review addendum

This companion to [the GEN-REL E1 build evidence](gen-rel-e1-evidence.md) holds the delta
history after review round 1: the merge of `origin/main` (2026-11-13), review round 2 and its
final runs, review round 3 and the main merge of 2026-11-15. The first sections below were moved here unchanged from the primary
record; the primary keeps the build, the mutation tables, the owner rulings and review round 1.

## Main merge (2026-11-13)

PR #523 showed a conflict after round 1, so `origin/main` at `c86ca58d` was merged once
(merge commit `26ffedb2`, no rebase). Main had released 0.23.0 since `c0961a17`, so the venv
was resynced (`uv sync --frozen --python 3.10 --extra dev --extra lint --extra vault --extra
cloud`; `decoy-engine` 0.22.0 to 0.23.0) and `decoy_engine.__file__` checked to be in this
checkout. Main is not merged again after this.

Conflicts, each resolved as a union:

- `src/decoy_engine/config/__init__.py`: `__all__` keeps this branch's `per_parent_bounds`
  and `per_parent_problems` and main's `post_scan_gate_applies`; both import lines merged
  without conflict.
- `tests/native/test_draw_sites_catalogue_pinned.py`: keeps main's `mask.tokenize` entry
  digest and both `Re-pinned for ...` lines (B-6, then GEN-REL E1), and the catalogue digest
  is recomputed with both changes in, by the file's procedure: main `483f424e...`, this branch
  `3e12aa89...`, merged `49e1c138...`. Against main's pin file only the catalogue digest and
  the `gen.reference` entry digest (`a53519d7...`) differ; `mask.tokenize` is main's.

Files both sides touched that merged without a conflict were read against both parents:
`CODEMAP.md` (main's rows added beside this branch's), `docs/reasons.md` (main's
released `registry_version` beside this branch's GEN-REL paragraph),
`tests/sentry/test_physical_seam_disconnection.py` (main's new permitted entries beside the
`_probe_scale.py` entry) and `tests/sentry/test_sentry_manifest.py` (main's new sentries
added). Main's changes are in the vault, post-scan, connector, run-result, chunked and
reason areas; none touches `generation/`, `generators/`, the reference draw, the draw-site
entries this branch edits or the option registry. The ten GEN-REL codes stay
`since=UNRELEASED` beside main's released stamps (`reason_release_pin.py --check` current,
`registry_renumber.py` consistent). The five ratchet baselines that gained keys in main
(`exception-context`, `f29-producer-inventory`, `gcs-call-kwargs`, `private-file-sinks`,
`secret-material-census`) are main's own rows; this branch adds no key to them, and
`ratchet_check.py --base origin/main` now exits 0.

On the merge head `26ffedb2` (before review round 2): 61 of 61 mutations red in a detached
worktree, every anchor matched once and every red count equal to the run on `9e31b706`; M4
applied once in this checkout, red, clean before and after. The T1 gate run started on that
head was stopped for review round 2, which changed source; the gates below are on the final
source head.

## Review round 2 (2026-11-13)

Review round 2 (delta on `9e1734e1`) found two config-side readers of the bounds that the
exclusivity sentry could not see. The widened sentry found a third.

| Commit | Subject |
| --- | --- |
| `dc8956ef` | `test(sentry): scan config modules for per-parent bound reads` (red first) |
| `f6e2a63b` | `refactor(config): read config-side per-parent bounds through the helper` (final source head) |

Sentry: `test_per_parent_bounds_are_read_only_through_the_config_helper` now scans `config/`
beside `generation/`, `generators/` and `execution/`. The only owners are named definitions,
not directories: `per_parent_bounds` in `config/_generate_relational.py`, and `_BASE_OPTIONS`
and `_NONE_MEANS_ABSENT` in `config/_generate_options.py`
(`test_every_bound_key_owner_names_a_real_definition` fails if one is renamed away). A key
counts as read when it is passed to a call, used as a subscript, compared, or listed in a
tuple, list or set that is iterated or assigned to a name. A key that only labels a problem
location (`return ("min_per_parent", code)`, `problems.append((("max_per_parent",), code))`)
or is a write target reads nothing. `test_the_bound_scan_sees_a_direct_read` pins each case.

Red on `26ffedb2` source (`dc8956ef`): 1 failed, 56 passed;
`config/_generate_unique.py:73`, `config/_generate_unique.py:123`, `config/_pipeline.py:343`
and `config/_pipeline.py:344`.

The three readers, now routed through `per_parent_bounds`:

- `config/_generate_unique.py` `column_conflict_problems`: `type(value) is int and value > 0`
  per key, now one helper call; each positive bound still reports its own location, in the
  same order.
- `config/_generate_unique.py` `_pair_member_blocked`: the bounds left `_PAIR_MEMBER_BLOCKED`
  (found by the widened scan; it read them through `_is_set`) and are tested through the
  helper. The helper is imported inside a small wrapper because `_generate_relational`
  imports `_tables`, which imports `_generate_unique`.
- `config/_pipeline.py` `_per_parent_bounds_valid`: the early exit asks the helper instead of
  truth-testing both keys.

| Input | Registry | unique conflict (`type(v) is int and v > 0`) | `_pair_member_blocked` (`_is_set`) | pipeline early exit (truthiness) | `any(per_parent_bounds)` |
| --- | --- | --- | --- | --- | --- |
| absent | accepted | False | False | False | False |
| None | accepted | False | False | False | False |
| 0 | accepted | False | False | False | False |
| 3 | accepted | True | True | True | True |
| -1 | refused | False | True | True | False |
| True | refused | False | True | True | False |
| False | refused | False | False | False | False |
| 2.5 | refused | False | True | True | False |
| 0.0 | refused | False | False | False | False |
| '3' | refused | False | True | True | False |
| '0' | refused | False | True | True | False |

Every value a validated config can carry reads the same in all three, so behaviour is
unchanged for validated configs. The early exit only skips `per_parent_problems`, which reads
through the helper, so its result is unchanged for every input. The pair-member check differs
only on values the registry refuses, where the config is refused either way. With this, the
three non-readers noted under round 1 B are settled: two were readers and now use the helper;
`plan/_generation.py`'s fitted-conflict check stays a presence test (`is not None`) outside the
scanned packages.

## Final runs (final source head `f6e2a63b`)

Mutations: 64 of 64 red in a detached worktree at `/home/user/` importing its own `src`
(Python 3.10.20), removed after; every anchor matched exactly once, and the 61 earlier red
counts equal the run on `9e31b706`. M4 applied once in this checkout at `f6e2a63b`, clean
before and after: red, 2 tests. New:

| Id | Mutation | File | Red tests |
| --- | --- | --- | --- |
| R7 | a config module reads the bound itself (unique conflict check) | `config/_generate_unique.py` | 1: `test_per_parent_bounds_are_read_only_through_the_config_helper` |
| R8 | the pipeline early exit bypasses the helper | `config/_pipeline.py` | 1: `test_per_parent_bounds_are_read_only_through_the_config_helper` |
| R9 | the pair-member check reads a bound through its own key tuple | `config/_generate_unique.py` | 1: `test_per_parent_bounds_are_read_only_through_the_config_helper` |

Gates, same command and paths as round 1, `origin/main` `c86ca58d`, Python 3.10.20:

| Step | Branch (`f6e2a63b`) |
| --- | --- |
| ruff | pass |
| format | pass |
| mypy | pass |
| sentry | 5427 passed, 0 failed, 2 skipped |
| layers | 15 passed, 0 failed, 0 skipped |
| licenses | 63 passed, 0 failed, 0 skipped |
| tests | 12268 passed, 0 failed, 62 skipped |

Failure sets: branch 0, main 0, branch-only 0. In that run
`tests/native/test_draw_site_inventory_coverage.py` passed 12 of 12 (including
`test_static_scan_finds_no_uncatalogued_draw_site`) and
`tests/native/test_draw_sites_catalogue_pinned.py` passed 5 of 5;
`tests/sentry/defects/test_generate_option_reads.py` passed 57 of 57.

Script checks on `f6e2a63b` with `origin/main` at `c86ca58d`:
`registry_renumber.py --check --main origin/main` exit 0, `ratchet_check.py --base
origin/main` exit 0, `check_fragment.py --base origin/main` exit 0,
`reason_release_pin.py --check` exit 0.

No digest, golden or snapshot of generated output moved. Not run: the full suite, Python
3.11, a rerun of `origin/main` (no branch step failed).

## Review round 3 (2026-11-15)

Review round 3 on `872f097d` asked for two fixes.

| Commit | Subject |
| --- | --- |
| `2cb980ae` | `test(sentry): resolve bound-key aliases in the reader scan` |
| (this commit) | `docs(records): split the gen-rel e1 evidence addendum` |

1. The bound-reader scan in `test_per_parent_bounds_are_read_only_through_the_config_helper`
   saw only the literal key, so `k = "min_per_parent"` followed by `col.get(k)`, `col[k]`,
   `k in col` or a loop over a tuple holding `k` read a bound unseen. `_bound_aliases` now
   resolves, per module and to a fixed point, every name assigned a bound key, a tuple, list
   or set holding one, or another such name (plain, annotated and walrus assignments). A name
   in that set counts as the key in a call argument, a subscript, a comparison and a
   container that is iterated or assigned, and iterating the name itself reads its keys.
   Assignments inside an owner definition do not alias, so the owner scoping is unchanged.
   `test_the_bound_scan_sees_a_read_through_an_alias` pins each case.
2. This record was 912 lines. The main merge, review round 2 and its final runs moved here
   unchanged; the primary keeps one link line where they were and is 778 lines.

Red: the seeded cell on the unchanged scanner (source `872f097d`) failed with
`assert [] == [3, 4, 5, 6, 7, 9]`: none of the alias reads were seen. Green after `2cb980ae`:
`tests/sentry/defects/test_generate_option_reads.py` 58 passed, 0 failed (the source tree
still passes; no alias read exists in `config/`, `generation/`, `generators/` or `execution/`).
The same scan over the sources of `feat/gen-rel-e2`, `feat/gen-rel-e3a`, `feat/gen-rel-e3b`,
`feat/gen-inherit-e2` and `feat/gen-inherit-e1` before the forward merges found nothing.

Not run: the full suite and the gate script; only the focused files named here, ruff on the
changed file, and `tests/sentry/test_module_size.py`. No source, digest, golden or snapshot
changed.

## Main merge (2026-11-15)

`origin/main` `38fddb2f` (32 commits past `c86ca58d`, through #597, the fixed width-flip
routing test) merged into `4983ed22` as `3a9199e9`. Follow-up commits: `d48e05d6` (the four
headings above were `###` under an H1, which the docs build refuses) and `f48e7854`
(`refactor(engine): hold capacity and relational config as packages`).

Conflicts, each resolved keeping both sides:

- `.importlinter` and the layer snapshot in `tests/sentry/layout/test_import_layers.py`: the
  bottom tier holds this branch's `_capacity` and main's `_arrow_types` and `_canonical`.
- `CODEMAP.md`: this branch's `config/` row and main's `plan/` row (`checks/_formula_types.py`).
- `config/__init__.py`, `relationships/__init__.py`, `tests/sentry/test_sentry_manifest.py`:
  both export or sentry lists, sorted.
- `generation/synthesize.py`: `policies = reference_policies(config)` beside main's
  `types = reader_types(...)`; 600 lines.
- `reasons/runtime/_part2.py`: main's `generate_formula_evaluation_failed` (released) stays above
  this branch's catalog switch, so it keeps main's family; the five GEN-REL runtime codes stay
  `since=UNRELEASED`. `reasons/warning/_part1.py`: main's `post_scan_output_unreadable`
  (released) beside `reference_parent_pool_empty` (`UNRELEASED`); the `UNRELEASED` import kept.
- `tests/unit/generation/unique/test_gen_unique_old_input_bytes.py`: both docstring paragraphs.
  The two sides moved different digests (this branch `reference_shapes.cells`, from the
  room-aware repair of `child.bounded`; main `all_basic_types.cells`, from a formula reading
  `score` as a number). Neither corpus config has the other side's feature, and the merged code
  reproduces both pinned values, so nothing was re-pinned.

Semantic checks: `git diff HEAD^1 HEAD` and `git diff HEAD^2 HEAD` read hunk by hunk for the 18
files both sides touched. Nothing was dropped: `_per_parent_bounds_valid` sits beside main's
`_targets_distinct`, `PinnedPlan.reference_policies` is in the fingerprint (now built by main's
`canonical_json_bytes`), the reference draw keeps `reference_policy` and `on_warning`, and the
formula post-pass takes main's `types=`. Main's new code passes this chain's sentries (bound
reads, `generate_columns_of`, draw-site inventory, seam), so no call site needed a fix.

Fan-out: each side added one module to the engine root and to `config/` (this branch
`_capacity.py` and `_generate_relational.py`, main `_arrow_types.py` and `_scan_baseline.py`), so
the merge held 26 in each against the cap of 25 (`test_package_fanout_within_limit`, 2 failed on
`3a9199e9`, 0 on main). `f48e7854` keeps each module unchanged as its package's `__init__.py`,
after main's `_canonical/` precedent: the import paths, `.importlinter` and the layer snapshot do
not change, no allowlist entry is added, and CODEMAP and `_MAP.md` say why. The option-read
sentry names the new path; a bound read seeded into the moved module still fails
`test_per_parent_bounds_are_read_only_through_the_config_helper`.

Gates, `GATES_WORKERS=4 scripts/dev/gates.sh --keep-going --baseline --steps
ruff,format,mypy,sentry,layers,licenses,tests` over the 57 T1 paths, `tests/unit/reasons` and
the native catalogue readers (inventory coverage, assembly, determinism protocol, the c1b and c5b
inventories, capabilities), Python 3.10.20, `origin/main` `38fddb2f`:

| Step | `3a9199e9` | `f48e7854` |
| --- | --- | --- |
| ruff, format, mypy | pass | pass |
| sentry | 5673 passed, 2 failed, 2 skipped | 5675 passed, 0 failed, 2 skipped |
| layers | 15 passed | 15 passed |
| licenses | 63 passed | 63 passed |
| tests | 7108 passed, 0 failed, 60 skipped | 7108 passed, 0 failed, 60 skipped |

On `3a9199e9` main's sentry step passed 5625 with 0 failed; the two fan-out cells were the only
branch-only failures. `f48e7854` has no failing step.

Script checks against `origin/main` `38fddb2f`, on this record's commit: `registry_renumber.py
--check --main origin/main` exit 0 (it had flagged the version this addendum named in its first
merge section, now reworded), `ratchet_check.py --base origin/main` exit 0, `check_fragment.py
--base origin/main` exit 0, `reason_release_pin.py --check` exit 0.

Not run: the full suite and Python 3.11.

## Main merge (2026-11-15, `64e9349b`)

`origin/main` `64e9349b` (#598, one format table for resident and lazy file sources) merged into
`36e20e9e` as `f07dc0d7`, without a conflict. Main's change is in `profile/` (a new
`_lazy_build.py`), `fileaccess/` and their sentries; it touches no file of this slice except
`CODEMAP.md` (its `profile/` row) and `tests/sentry/test_sentry_manifest.py` (its new sentry
beside this slice's), both read against the two parents.

Checks on `f07dc0d7`, Python 3.10.20: ruff and format on the changed files pass; mypy clean
(883 files); `tests/sentry` 5698 passed, 0 failed, 2 skipped; layers 15 passed; this slice's
test files (`tests/unit/config`, `tests/unit/generation/relational`, the probe-scale, pinned,
streamed-entry, capacity, unique old-input-bytes and relationships tests, the phase-F witness
and invariant files, `tests/unit/test_v2_generation.py`) with main's `tests/unit/profile` and
the two draw-site catalogue tests: 2053 passed, 0 failed, 7 skipped. Script checks against
`origin/main` `64e9349b` (`registry_renumber.py`, `ratchet_check.py`, `check_fragment.py`,
`reason_release_pin.py --check`): each exit 0. `generation/synthesize.py` 600 lines; the engine
root and `config/` hold 25 modules, `profile/` 19.

Not run: the full T1 gate on this head, mutations and the full suite.

## Main merge (2026-11-15, `a7f278eb`)

`origin/main` `a7f278eb` (#600 install story, #582 one seed path for every seeded generator,
#489 durable publication units) merged into `9a0b1181` as `39383719`.

One conflict, `tests/native/test_draw_sites_catalogue_pinned.py`: both sides re-pinned
`_CATALOGUE_DIGEST`. Main (DUP-FREEZE E2) added `mask.joint_mask_null_fallback` and
`mask.joint_mask_gen_row` after `mask.joint_mask_keyed_row` and changed the
`gen.composite_build_pool` seed text; this slice changed `gen.reference`. The ordered ids, the
entry digests and the coverage-map digests merged without a conflict and each matches the merged
catalogue (42 entries). Both "Re-pinned for ..." lines are kept, and `_CATALOGUE_DIGEST` is the
file's own procedure (SHA-256 over `repr(protocol.DRAW_SITES)`) on the merged tree:
`895b26ce...`; main pinned `cfaa8fd8...` and this branch `49e1c138...`, each without the other
side's entries. `execution/native/_draw_sites_gen.py` auto-merged main's `gen.composite_build_pool`
seed text beside this slice's `gen.reference` entry.

Files both sides touched, read against both parents: `CODEMAP.md` (main's `fileaccess/` and
`determinism/` rows), `docs/reasons.md` (main's F22 paragraph), `docs/strategies.md`, the sentry
manifest (main's `test_rng_construction.py`). Main's new seed sentry
(`tests/sentry/defects/test_rng_construction.py`) passes over this chain's generation code.

Gate on `39383719` (`GATES_WORKERS=4 scripts/dev/gates.sh --keep-going --baseline --steps
ruff,format,mypy,sentry,layers,licenses,tests` over the 57 T1 paths, `tests/unit/reasons` and
the native catalogue readers, Python 3.10.20, baseline `a7f278eb`): ruff, format and mypy pass;
sentry 5764 passed, 0 failed, 2 skipped; layers 15 passed; licenses 63 passed; tests 7142
passed, 0 failed, 60 skipped; no branch-only failure. Script checks against `origin/main`
(`registry_renumber.py`, `ratchet_check.py`, `check_fragment.py`, `reason_release_pin.py
--check`): each exit 0. `generation/synthesize.py` 600 lines; the engine root and `config/` hold
25 modules (main's packages: `determinism/` 3, `fileaccess/` 17, `generation/composite/` 10).

## Main merge (2026-11-16, `1c8e413c`)

`origin/main` `1c8e413c` (#496, publication descriptor codec) merged into `1bccfb8a` as `ffadf9c1`, without a conflict. `origin/main` `1c8e413c` (#496) adds
the `publication/` package (the `decoy-publication/v1` descriptor codec and receipt types),
places it in the `execution` tier of `.importlinter` and the layer snapshot (this chain's
`_capacity` entry in the bottom tier is unchanged), extends `_canonical` and adds a strict-JSON
sentry. It touches no source or test file of this slice and not the draw-site catalogue.

Checks on `ffadf9c1`, Python 3.10.20, `origin/main` `1c8e413c`: ruff and format on the changed
files pass; mypy clean (889 files); `tests/sentry` 5782 passed, 0 failed, 2 skipped; layers 15 passed; this slice's test files (`tests/unit/config`, `tests/unit/generation/relational`, the probe-scale, pinned, streamed-entry, capacity, unique old-input-bytes and relationships tests, the phase-F witness and invariant files, `tests/unit/test_v2_generation.py`) with main's `tests/unit/publication` and `tests/unit/canonical` with the two
draw-site catalogue tests: 1624 passed, 0 failed, 7 skipped. Script checks (`registry_renumber.py --check --main
origin/main`, `ratchet_check.py --base origin/main`, `check_fragment.py --base origin/main`,
`reason_release_pin.py --check`): each exit 0. `generation/synthesize.py` 600 lines; the
engine root and `config/` hold 25 modules, `publication/` 2.

Not run: the full T1 gate on this head, mutations and the full suite.

## Main merge (2026-11-16, `ddd014a5`)

`origin/main` `ddd014a5` (release 0.27.0 and the twelve commits after `1c8e413c`: publication
judge and bind, the sink state table, `publish_unit` through the sink and the isolated route,
resume store records, the pre-scan model pass, lazy-input streaming, the scratch arena move and
the frozen-surface map) merged into `a71617b6` as `03322a2e`. Two documentation conflicts, both
resolved to main's text with this chain's `_capacity/` rows kept: `CODEMAP.md` (main's
`_canonical/` row with `_strict_spec.py` and its `tests/sentry/release/` sentry row, beside this
chain's `_capacity/` and capacity-foundation rows) and `src/decoy_engine/_MAP.md` (main's
`_canonical/` row, beside this chain's `_capacity/` row). The release consumed main's five
changelog fragments; this slice's `changelog.d/gen-rel-e1.md` is kept.

`generation/_streamed.py` merged without a conflict: main's `publication_receipt` field and this
slice's reference policy each add four lines, which took the module to 602. `c7ccf051` rewords
two comments to hold it at 600, with no code change and no census entry. Main does not touch the
draw-site catalogue, `.importlinter`, `generation/synthesize.py` or
`tests/property/test_ri_graph_invariants.py`.

Checks on `c7ccf051`, Python 3.10.20, `origin/main` `ddd014a5`: ruff, format and mypy pass;
`tests/sentry` 5887 passed, 0 failed, 2 skipped; layers 15 passed; `tests/unit/generation` with
this slice's test files and the two draw-site catalogue tests and the fan-out sentry: 3649
passed, 0 failed, 43 skipped. Script checks (`registry_renumber.py --check --main origin/main`,
`ratchet_check.py --base origin/main`, `check_fragment.py --base origin/main`,
`reason_release_pin.py --check`): each exit 0. `generation/synthesize.py` 600 lines,
`generation/_streamed.py` 600; the engine root and `config/` hold 25 modules.

Not run: the full T1 gate on this head, mutations and the full suite.
