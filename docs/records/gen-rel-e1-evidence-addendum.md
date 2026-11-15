# GEN-REL E1 build evidence: merge and review addendum

This companion to [the GEN-REL E1 build evidence](gen-rel-e1-evidence.md) holds the delta
history after review round 1: the merge of `origin/main` (2026-11-13), review round 2 and its
final runs, and review round 3. The sections below were moved here unchanged from the primary
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
`registry_version` 1.25.0 from its release beside this branch's GEN-REL paragraph),
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
