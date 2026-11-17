# F22 slice b2: build evidence

Slice b2 of `docs/plans/2026-10-30-f22-publication-replan.md` (revision 11, V1 scope; design 5.5,
rule V, G4, G1a, D1 and D3): `publish_unit` commits or adopts the request's vault under the
destination lock, after a bind verdict and before the bind; a republish needs the bound vault's
digest on disk and this writer's rows.

## Environment

- Container, Linux, effective uid 0. Lock profile `.venv` (`bash scripts/dev/bootstrap.sh`, then
  `--check`: OK, in sync with `uv.lock`). Python 3.10.20, PyArrow 24.0.0, DuckDB 1.5.4.
- Branch `feat/f22-b2` from `origin/main` `13c95c7d` (b1, #607, merged). Main baseline for
  failure sets: `13c95c7d`, run in a temporary detached worktree with `PYTHONPATH=<worktree>/src`
  from the worktree root (`decoy_engine.__file__` printed under the worktree); removed after.
- Commits: `47e2997f` red tests; `931588cb` production; `d3d00144` docs and changelog fragment.
  Code head for every check below: `d3d00144`; the commit after it adds only this record.

## Production files

| File | Lines (start to head) | Change |
|---|---|---|
| `publication/_publish.py` | 376 to 456 | `check_request` accepts a vault request (the `NotImplementedError` is gone; a `vault.writer` that is not a `VaultWriter` raises `TypeError`). `_commit_vault` (5.5 steps 1 to 3): `writer.publish(out)`; on `vault_exists`, `adopt_vault` (D1), whose `VaultConflict` becomes a `refused` receipt `publication_vault_conflict`; any other `VaultError` re-raised. `_bind` takes the `VaultCommit` (or `None` only for a request without a vault) and writes the descriptor's `vault` from it. `_check_vault` (D3) on the `already_committed` path, before D2. Module docstring cites WAL ordering |

One file, exactly plan 9's list. No census entry needed (456 < 600). No new reason code
(`publication_vault_mismatch` and `publication_vault_conflict` were registered in a3);
`registry_renumber.py --check --main origin/main`: `registry consistent`.
`scripts/dev/check_fragment.py --base origin/main`: exit 0. `vault.py` untouched, so the secret
census is unchanged.

## Red first (start commit `13c95c7d`)

All 40 b2 tests were run on `13c95c7d` (the branch head was main's code plus the test commit):
40 failed, none passed. Every one fails because `check_request` raised
`NotImplementedError("a vault-bound publication needs vault ordering")` for a vault request (in the
crash and hook tests it is raised in the `spawn` child, so the child exits 1 instead of being
killed or binding).

| Test (plan 7.2 row) | Cells | Red because |
|---|---|---|
| `test_vault_order_is_structural` | 2 | vault request refused (absent) |
| `test_vault_order_is_structural_under_faults` (same row: stage write, file fsync, link EIO, dir fsync EIO, chain fsync EIO) | 10 | absent |
| `test_vault_exists_with_other_rows_is_never_bound` (same row: `vault_exists` with different content) | 2 | absent |
| `test_vault_exists_with_the_same_rows_is_adopted` (5.5 step 2) | 2 | absent |
| `test_output_bound_vault_missing_unreachable` | 2 | absent |
| `test_republish_requires_vault_digest` | 14 | absent |
| `test_two_writers_same_output_different_vault` | 8 | absent |

Non-vacuity lines: the fault injector fired in the vault step (`fired[0] == case`); a vault is at
the leaf before the conflict cell; the kill marker names the cut step and the set of cut kinds is
`{fsync, link, rename}` with `link` before `rename`; the republish result has the bound
`result_id` (so D3 decided); W was parked in `_after_judge` and L's `flock` probe saw
`EWOULDBLOCK`; W's rows still give `already_committed`.

## Mutations (each applied once, test red, reverted with `git checkout`; none committed)

| Mechanism | Mutation | Red |
|---|---|---|
| vault before bind (plan 7.2) | `_commit_vault` called after `_bind` (so after `txn.publish()`) | `test_vault_order_is_structural` (2), `..._under_faults` (10), `test_output_bound_vault_missing_unreachable` (2): 14 |
| digest compare on republish | drop the SHA-256 compare in `_check_vault` | `test_republish_requires_vault_digest[*-same_rows_rewritten]` (2) |
| writer rows on republish (class 3) | drop `same_rows` in `_check_vault` | `test_two_writers_same_output_different_vault` (8) |
| presence both ways (LOW-1) | `_check_vault` returns `None` when either side has no vault | `test_republish_requires_vault_digest[*-request_without_vault, *-bound_without_vault]` (4) |
| adopt conflict refused | ignore `VaultConflict` | `test_vault_exists_with_other_rows_is_never_bound` (2) |

## Checks (code head `d3d00144`, uid 0 unless stated)

Each failing-id set was diffed against the main baseline run of the same command; all identical.

| Command | Branch | Main `13c95c7d` |
|---|---|---|
| `pytest tests/unit/publication tests/fileaccess tests/sentry -n 2` | 7228 passed, 10 failed, 92 errors, 6 skipped | 7188 passed, same 10 failed, same 92 errors, 6 skipped |
| `pytest tests/unit/execution tests/integration tests/parity tests/security -n 2` | 12934 passed, 18 failed, 3 errors, 2403 skipped, 37 xfailed | identical counts and ids |
| `pytest tests/unit -n 2 --ignore=tests/unit/execution --ignore=tests/unit/scripts` | 15009 passed, 0 failed, 100 skipped | 14969 passed, 0 failed, 100 skipped |
| `bash scripts/dev/gates.sh --keep-going --steps sentry,layers` | `[sentry] PASS passed=5845 failed=0 errors=0 skipped=2`; `[layers] PASS passed=15 failed=0 errors=0 skipped=0` | not run |
| `ratchet_check.py`; `ruff check src tests`; `ruff format --check src tests`; `mypy src/decoy_engine` | clean | not run |
| uid 65534 (`setpriv`, copied interpreter): `tests/fileaccess/publication tests/unit/publication`, `test_private_creators.py`, `test_scratch_root_umask.py`, `test_scratch_arena.py`, `test_isolated_umask.py` | 518 passed, 0 failed | not run |
| F22 crash tests: `test_output_bound_vault_missing_unreachable`, `test_adopt_syncs_ancestor_chain`, `test_make_parent_dir_modes_and_crash`, `test_restart_recovery` (and `test_restart_same_operation_different_result`), `test_vault_ancestor_chain_durable` | 41 passed | not run |

The collected count rises by 40 in the first and third commands: the 40 new b2 tests. The baseline
failures are the known root-only ones: 56 errors in `test_private_creators.py`, 36 in
`test_scratch_arena.py`, 3 in `test_scratch_root_umask.py`, 18 failures in
`tests/unit/execution/scratch/test_scratch_modes.py`, and the 10 `test_import_layers.py` failures
outside gates (gates runs them in `.venv-layers`: 15 passed). All of them pass under uid 65534
where run.

Every test file naming a changed signature (`check_request`, `publish_unit`, `publish_tables`,
`VaultBinding`) lies under the directories above (`git grep` outside them: none).

## Plan differences (need a call)

- E8 (`vault_commit_failed`) is raised as the vault module's `VaultError`, not returned as a
  receipt. `CommitReceipt.reason_code` accepts `decoy` codes only (a3), and `vault_commit_failed`
  is a `runtime` code (plan Q6: "the vault code is B-6's"). The stage is aborted first and nothing
  is bound. The other vault errors (`vault_crypto_not_installed`, the step-1 policy errors of
  `out.begin`) propagate the same way, as from `VaultWriter.write`.
- `adopt_vault` returns a `VaultConflict` value on conflict, as #607 merged it (the b1 docs and
  fragment said `None`); `docs/publication.md` now says `VaultConflict`. The b1 fragment on main
  is not edited.
- D3 maps every `OSError` from `adopt_file` to `commit_uncertain`, including a symlink (`ELOOP`) or
  non-regular leaf (`EINVAL`), since `adopt_file` does not separate an open refusal from an fsync
  failure; `LeafTooLarge` and `FileAccessDenied` are `publication_vault_mismatch`. Both are
  fail-closed (never `already_committed`).
- `test_output_bound_vault_missing_unreachable` cuts before every durability step after the bind
  verdict (each fsync, the vault `link`, the stage rename), counted, instead of a named hook per
  step; the cut kinds are asserted. The plan row's "a fresh retry gives `published`" holds for cuts
  before the output rename; after it the unit is bound and the retry gives `already_committed`,
  which the test asserts.

## Not run

Full suite, perf, macOS, Windows (w1), `tests/unit/scripts`, baseline gates (sentry and layers).

## V2-LOG

- D3 could tell an unadoptable leaf (`ELOOP`, `EINVAL`) from an fsync failure and report it as
  `publication_vault_mismatch` instead of `commit_uncertain`, if `adopt_file` separated the two.
- A raw `OSError` from the vault stage's `out.begin` (B-6 step 1, "keeps the policy's shape")
  reaches the `publish_unit` caller unchanged.
