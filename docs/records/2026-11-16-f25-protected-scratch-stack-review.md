Status: record

# F25 protected scratch: stack review record

Date: 2026-11-16. The stack is nine engine PRs: #500, #502, #505, #507, #509, #513, #516, #518 and
#522 (top branch `feat/f25-s2a-1c`). F25 makes scratch directories private (0700, files 0600),
quota-bound and cleaned up. Each PR merges its base branch forward, so a PR's own diff is
`git diff <base>...<branch>`. The stack merges into main as one unit through #522.

## Result

| PR | Branch | Head after review | Dennis | Codex review-low | CI |
|---|---|---|---|---|---|
| #500 | `feat/f25-s1b` | `d7bc70833` | remote round 1, 2 DESIGN | GO | green |
| #502 | `feat/f25-s1b-ii` | `9e1af8cfa` | remote round 1, 1 DESIGN (fixed) | GO | green |
| #505 | `feat/f25-s2a-1` | `6beb4189d` | round 1, 1 V1 (ruled V2-LOG) | 2 V1 ruled V2-LOG, delta GO | green |
| #507 | `feat/f25-s2a-1-ii` | `f9aca1c94` | round 1, 1 DESIGN (fixed) | GO | green |
| #509 | `feat/f25-s2a-1a` | `b13826599` | round 1, GO | 1 V1 ruled V2-LOG | green |
| #513 | `feat/f25-s2a-1b` | `0aae525af` | round 1, GO | GO | green |
| #516 | `feat/f25-s2a-1b-ii` | `32dde7206` | round 1, GO | GO | green |
| #518 | `feat/f25-s2a-1b-fix` | `28b0b8b1f` | round 1, 1 DESIGN (fixed) | GO | green |
| #522 | `feat/f25-s2a-1c` | `23fef97f8` | round 1, GO | GO | green |

A full suite (T3, legacy mode) on the stack top merged with main `8dfc02086` passed: branch-only
failures 0, tests 44680 passed, 0 failed, 5364 skipped.

## Fixed in the stack

- #500: the docstring of `test_d9_connection_sites_are_native_connections` names the slice (S4b)
  that owns folding the D9 tracker into the native-flow tracker. The two trackers stay for now.
- #502: the arena prefix sentry reuses the project index and sites from `scan_tree`. The second
  index and its own walk are gone.
- #505: changelog line and symlink cell corrected.
- #507: `ScratchArena.open` is now `ScratchArena.fresh`. The `open_arena` alias that hid the call
  from the outbound-client sentry is gone, with no delegate kept and the sentry untouched.
- #513: `WALK_FLOOR` in the outbound-client sentry went from 149 to 148 together with the dropped
  baseline row.
- #516: the tee test spy joins the stager's component to the tee's scratch root.
- #518: one shared `fd_path` helper in `tests/fileaccess/support.py`.

## Rulings

- #505, two arena roots across declared-casting recursion: closed by #507, so the stack merges as
  one unit. Merging #505 alone leaves the gap.
- #505, the reclaim RETAINED report is discarded: V2-LOG. Main already removes scratch with
  `rmtree(ignore_errors=True)`.
- #509, child arena descriptors close by collection, not deterministically: V2-LOG. It matters
  only on an interpreter without reference counting, and only CPython is certified.
- #505, a planted symlink in a shared writable base directory: V2-LOG. It needs a hostile local
  user, outside the accidental-leak bar. Descriptor-spill slice follows.

## V2-LOG items, not fixed

- #505: the test in `test_scratch_modes.py` checks only `ARENA_PREFIX`; `local_path()` runs outside
  the try; `dict(locals())` carries the arena; a private import of `ARENA_PREFIX`.
- #507: no `QuotaReport` assertion on over-budget; the error class differs between the arena arm
  and the path arm until T18; mutations C1 to C6 were recorded before the code landed.
- #509: reorder cells never see the join subtree; no cell pins directories made through the arena;
  each `create_dir` adds a descriptor to the root's children that is never removed; a test-only
  copy of the descriptor probe.
- #513: the `ScratchAccess` finalizer is registered before `super().__init__`, so a failed
  construction can close a descriptor twice; the out-of-core scratch module calls private
  `ScratchArena._adopt`; `scratch_access_for` does not clean up on partial failure; no cell fails
  if the reader finalizer is dropped.
- #516: changelog claims `scratch_access_for` is removed (it is not; the clause should go); the
  staging open changed from `O_TRUNC` to `O_EXCL`; write and close failures surface as
  `FileAccessReadError("engine.scratch")`; the 0600 arena cell runs only under the ambient umask.
- #518: no check that directories were observed; the rmdir recorder sees only `dir_fd` calls; modes
  are read only at removal.
- #522: `_adopt` has no win32 guard; no handling of `FileExistsError` on a missing leaf under
  concurrent connects; an adopted descriptor is freed only by reference count on connect failure;
  a stale comment in `_pool_quality.py`; no test forces a spill to show files land in
  `temp_directory`.

## Main merge note

Merging main into the stack conflicts once, in the count header of
`tests/sentry/file_access_registry.toml`. Keep both sides' entries and set the count to the number
of `[[entry]]` rows. The stack removes three rows, so the count is main's minus three.
