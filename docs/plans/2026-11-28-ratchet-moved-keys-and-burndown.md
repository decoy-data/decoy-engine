# RATCHET-GROWTH moved keys and RATCHET-BURNDOWN: follow pure moves, then shrink the debt lists

Status: plan

Rows: RATCHET-GROWTH (the moved-keys widening, owner 2026-11-27) and RATCHET-BURNDOWN (new 1.0
health row, owner 2026-11-27). Both row texts come from CLI PR #427 (`docs/ratchet-rehome-and-burndown`),
which is open and not merged on 2026-11-28. Build waits on that merge (OQ1).

Repos: engine (decoy-data/decoy-engine) and CLI (decoy-data/decoy). Release: the engine half ships
in the next engine release after main 8414da35c; the CLI half ships with the CLI repin that follows
it. No product behavior changes except BD-E1 (file mode of one temporary spool) and BD-E4 (three
additive public accessors).

Rules consulted: /home/cam/dev-rules/00-universal.md, development-loop.md (PLAN),
risk-and-exceptions.md, testing.md (Test depth; escalation trigger "test tooling"),
refactoring.md, proportionality.md, reuse-first.md, cross-cutting-concerns.md,
catalogs/recurring-defects.md; engine CODEMAP "Where things go"; PLAYBOOK-decoy.md R2 plan
done-state; owner rule "Ratchet 1:1 re-home" (OWNER-OPEN-DECISIONS.md:55, 2026-11-15); owner
ratchet rule 2026-11-25 (lists grow only with sign-off).

Base: engine origin/main 8414da35c (#828, 2026-11-28); CLI origin/main 2ca3bbd4.

## Changes in round 2 (Dennis R1 NO-GO, verdict bfe73f35e1b7)

An inferred move keeps one location part and passes a def-content proof (section 6.1). Bare-file
keys move only on a git-reported rename. All 61 registry ids are in the section 6.3 table.
Total-not-grow is a redundant invariant with a property test. MK-C1 vendors the engine's move
logic. The `_rehome.py:107` relaxation is stated. A new `MOVE_CASES` table is added. RG-E3 is a
hard start-after. BD-E1 has an exact recognition rule. The ledger goes to `docs/records/`. The A11
replay is widened. Acceptance tests come before the design. Open PRs that touch these baselines
are listed in section 1.

## 1. Frame

The sentry ratchet (`tests/sentry/_ratchet.py`) fails a slice whose baseline gains a key that was
not in the merge base. A code move renames keys without adding any site. Today only two sentries
(`secret-material-census`, `gcs-call-kwargs`) can follow a move, and only when the builder writes a
`moved_from` field (`tests/sentry/_ratchet.py:45`, `tests/sentry/_ratchet.py:534`). Every other
move needs a hand-written `approved_growth` row with an owner decision string. On 2026-11-27 four
slices stalled on this (F31 AE5, PER-COLUMN-ROUTING S0, COLUMN-SHAPE-RULE E5, G7-1). Earlier moves
that needed hand rows: lossless-int `adapter_fk_safe_columns` into `_oracle_step.py`, column-shape
`observed_shape` into `profile/arrow/_walk_arrow.py`, exception-text `is_memory_failure` into
`fileaccess/_errors.py`, the `yaml_mark` keys, the f29-consumer rename `_derive_pool_indices` to
`derive_pool_indices`, and the parquet vault `VaultWriter.serialize` to `_format::_encode_rows`.

Second problem: the debt lists only shrink when unrelated work touches the code. RATCHET-BURNDOWN
asks, per guard, for the one shared helper the allowed sites should go through, then moves them and
lowers the baseline. F31-AUDIT is the model (audit first, then burn slices with targets).

Open engine PRs #790, #778, #705, #685, #818, #808 and #670 edit baselines that MK infers on. Their
existing `moved_from` entries must stay valid: MK keeps the declared path for the two rehome
sentries unchanged except the stated relaxation (6.4), and A14 replays a declared entry of the
present form. Each of those PRs that merges before MK-E1 is in the A11 replay set.

Risk: R2 for the plan as a whole (test tooling that gates every merge, and one private-file
change). Per slice in section 8.

## 2. Guarantee and non-goals

Pinned guarantee (MK): a grown key passes the ratchet with no `approved_growth` row only when it is
the unique 1:1 partner of one lost key, keeps exactly one location part (same file, or same
qualname), keeps the bound name and ordinal, has no looser bounds and the same category, the old
site is proven gone, and the enclosing def is unchanged (content proof). Bare-file keys need a
git-reported rename instead. Every inferred move prints one report line that reaches gate stderr.
Anything else is still growth.

Pinned guarantee (BD): each debt guard named in the ledger (section 13) ends at or below its target
count, and each removed entry is routed through the guard's named owner helper. No baseline gains a
key and no allow-list gains an entry in any slice of this plan.

Non-goals:
- No change to growth rules: real growth still needs a dated owner row.
- No inferred split (one key into many) or merge (many into one). CLI `split_from` stays as is.
- No inferred move where both file and qualname change; that needs a declared `moved_from` plus
  the same content proof.
- No inferred moves for `GUARD_KEYS` (`sentry-limits`) or `REKEY_PER_SITE`
  (`validation-name-messages`) (`tests/sentry/_ratchet.py:40`, `tests/sentry/_ratchet.py:52`).
- Not the outbound-text burndown: engine-exception-text-copies, config-refusal-text, CLI
  one-error-emitter, engine-reason-code-copies stay with F31-AUDIT (AE5b, AC1, AC3).
- Not module-size (engine: STRUCTURE-REVIEW, "Not now"; CLI: CLI-SPLIT S2) unless OQ3 says so.
- Not census burndown (f29-producer, f29-reason, f29-consumer, secret-material-census,
  serial-resources, gcs-call-kwargs, import-layers, platform-census, exception-context,
  win32-import-surface). They record inventory. Moves are still followed for them.
- Not CLI lint-debt (its own tool and row).
- Not RG-E3, RG-C1a, RG-C1b (planned in
  `docs/plans/2026-11-24-postmask-fail-closed-and-ratchet-growth.md`). MK starts after them.

## 3. Acceptance tests (red before their slice unless marked control)

MK-E1 (`tests/sentry/ratchet/test_moved_keys.py`, seeded git repos in `tmp_path`):
- A1 file move of one def-keyed entry, same qualname, same bound name, same `max`, def body
  unchanged, old file gone: passes with no `approved_growth`; one report line.
- A2 same move with `max` raised by 1: finding.
- A3 two lost keys and one grown key of the same identity: finding naming the tie (no tie-break).
- A4 old site still present (copy): finding.
- A5 bound name differs: finding.
- A6 move accepted and a second unrelated new key appears: the new key is a finding.
- A7 a `sentry-limits` key moves: finding (guard keys excluded).
- A8 a `validation-name-messages` move follows its existing re-key path, unchanged (control).
- A9 qualname rename in the same file (`_derive_pool_indices` to `derive_pool_indices`): passes.
- A10 `min` lowered on a move: finding. `category` changed: finding.
- A11 engine-only replay from real history (each red before: needs a row today):
  - positive: the six moves in section 1, plus the moves of the four slices that stalled on
    2026-11-27 (F31 AE5, PER-COLUMN-ROUTING S0, COLUMN-SHAPE-RULE E5, G7-1), rebuilt from their
    branches, pass with no approval row;
  - negative (control): the real growth rows in `sentry_registry.toml` (F33 census rows for
    `sign_signing_input`, the `arrow_frames.py` public facade, the F26 publication stage modules,
    the 2026-11-21 policy-to-I/O edges), replayed with their approval removed, are still findings.
- A12 the section 6.3 table equals the registry: every id is in `IDENTITY` or `NO_INFERENCE` with a
  reason, or is a guard; a new registry id with no row fails.
- A13 malformed key (no `::`, non-identifier qualname, lambda, unknown prefix): no inference, no
  exception.
- A14 declared `moved_from` of the present form on `secret-material-census` passes (control); on a
  non-rehome sentry (lossless-int) it passes with the content proof; on `sentry-limits` it fails.
- A15 unrelated swap: site X deleted in file a, unrelated site Y with the same bound name added in
  file b, same qualname, different def body: finding (content proof fails).
- A16 bare-file key: delete file A, add unrelated file B under A's ceiling: finding (git reports no
  rename). A real `git mv` of A to B with the same ceiling: passes.
- A17 the `moved ... (inferred` line of A1 is present in the gate stderr from the RG-E3 gate step.
- A18 declared rehome of an entry with `max` (lifts `_rehome.py:107`): equal `max` passes, lower
  `max` passes, higher `max` fails.
- A19 `test_infer_moves_is_pure`: `infer_moves` called twice on deep-copied inputs returns equal
  results and leaves its inputs unchanged.
- A20 both file and qualname change, no declaration: finding. Same with declared `moved_from` and
  unchanged def: passes. Declared with changed def: finding.
- P1 property (Hypothesis, fixed seed): over generated base and head baselines, whenever `check`
  passes, the head total of non-approved keys (sum of `max`, or 1 per entry without `max`) is at
  most the base total. This states total-not-grow as a redundant invariant; no extra code path.

MK-C1 (CLI `tests/sentry/test_ratchet_check.py`, parametrized on `MOVE_CASES`): A1, A2, A3, A4, A7,
A15, A16 on the CLI checker; a top-level `moved_from` entry and an inferred move for the same key
give one verdict, declared wins; a declared CLI move keeps exact entry equality except a lower
`max`; `split_from` cases unchanged (control); vendored `_moves.py` digest pin.

BD-E1:
- B1 under umask 022, the pool-quality spool file is created mode 0600 (stat inside the run).
- B2 private-file-sinks baseline drops the pool-quality entry and each entry now matched by the
  recognition rule (6.6); stale test green.
- B3 seeded: a recognized write is not a finding; seeded negatives are findings: a reassigned
  handle, an unlink then reopen of the precreated path, a handle passed through a helper, an alias
  (`h2 = h`), a plain `open()` handle.

BD-E2:
- D1 golden bytes for the FK lane fixtures (single-column FK, composite FK, self-reference, nullable
  FK, int64 key over 2**53) are byte-identical before and after (control, must stay green).
- D2 lossless-int `ALLOWED` and baseline equal the target from BD-A0; a seeded direct ingestion
  site fails.

BD-E3:
- C1 `TRUTH_TEST_BASELINE` (`tests/sentry/test_table_kind_classifier.py:26`) drops to the target;
  `MUST_BE_ZERO` gains each module brought to zero.
- C2 seeded: a new inline truth test in a zeroed module fails.

BD-E4: E1 each accessor returns the same sorted names as the private registry; E2 compatibility
entry lists the three names as additive; E3 the frozen public surface snapshot updated in the
same commit.

BD-C1 and BD-C2: each guard's allow list equals its target; a seeded direct site still fails; the
engine-internal boundary sentry has no #2 to #4 entries.

## 4. Named mutations (each turns its named test red on the final head)

- M1 accept the first candidate on a tie (A3 red).
- M2 drop the `site_gone` call (A4 red).
- M3 compare `max` with `>=` instead of `<=` (A2, A18 red).
- M4 include `GUARD_KEYS` in inference (A7 red).
- M5 skip the def-content comparison (A15 red).
- M6 `open_private` back to `open(..., "wb")` in `_pool_quality.py` (B1 red).
- M7 restore one inline `.get("generate_columns")` truth test (C2 red).
- M8 swap the int64 ingestion helper for `to_pandas()` in one BD-E2 site (D1 red).
- M9 accept a bare-file move without the git rename check (A16 red).
- M10 accept a move where both file and qualname changed (A20 red).

## 5. Behavior and failure modes

MK, engine and CLI:
1. After the declared re-home step, every baseline not in `GUARD_KEYS` or `REKEY_PER_SITE`, and
   not in `NO_INFERENCE`, runs `infer_moves(lost, grown)`.
2. Each key is parsed by its sentry's row in the 6.3 table into a root prefix, location parts and
   a bound part. Identity is the bound part plus the location part that must stay equal.
3. A lost key and a grown key pair only when each is the only candidate of its identity on its side.
   A tie is a finding naming both candidates. There is no tie-break.
4. A pair is accepted only when the 6.1 rules hold and the entries match (6.2).
5. Each accepted pair prints `<sid>: moved <old> -> <new> (inferred; <proof>)`.
6. Declared `moved_from` (engine per-entry, CLI top-level map) is widened to every sentry with a
   proof kind in 6.3, with the same proofs. Declared wins over inferred.

BD: each burn slice moves sites onto the named helper, lowers the inline allow-list and the JSON
baseline together, and adds one seeded case per guard that shows a new direct site still fails.

| # | Failure | Guard |
|---|---------|-------|
| F1 | a new site is laundered as a move of a deleted unrelated site with the same bound name | one location part kept, def-content proof, uniqueness, report line (A15, A3) |
| F2 | a move raises `max` | bounds check after pairing; `loosened_findings` unchanged (A2) |
| F3 | the old site is still live under the old key (copy, not move) | proof of absence; mirror test (A4) |
| F4 | two sites move at once and swap identities | uniqueness and content proof (A3, A15) |
| F5 | a `sentry-limits` key moves and hides a raised limit | excluded by `GUARD_KEYS` (A7) |
| F6 | CLI and engine checkers disagree on a move | one vendored `_moves.py`, digest pin, `MOVE_CASES` |
| F7 | a bare-file count is paid for by an unrelated new file | git rename check (A16) |
| F8 | a burn slice changes output bytes on the FK lane | BD-E2 byte goldens (D1) |
| F9 | a private write moves onto a handle the rule wrongly trusts | BD-E1 seeded negatives (B3) |
| F10 | the checker crashes on an odd key and passes the run | malformed keys are "not proven", never raise (A13) |

## 6. Design

### 6.1 Move rules

- Keep one location part. A def-keyed move changes the file (same qualname) or the qualname (same
  file), never both. Both changing needs a declared `moved_from` and the content proof (A20).
- Content proof for def-keyed entries: parse the enclosing def at head and at base, strip
  `lineno`, `col_offset`, `end_*` and the def's own name, and compare `ast.dump(...,
  include_attributes=False)`. The base def is read through `BaseTree.blob`
  (`tests/sentry/ratchet/_integrity.py:101`); the head def through the existing checkout reader.
  Equal dumps, plus `site_gone` on the old key, prove the move.
- Bare-file and module-level keys (no enclosing def): the move is accepted, inferred or declared,
  only when `git diff -M --name-status <base> <head>` reports exactly `R<score> old new` for that
  pair (git's default 50% similarity). Otherwise the sentry is in `NO_INFERENCE` and the old
  behavior holds.
- This follows git rename detection: exact identity first, then content similarity; it drops git's
  basename heuristic because a ratchet must not guess.

### 6.2 Entry match

The grown entry equals the lost entry except `reason` text and bounds; `max` is equal or lower,
`min` equal or higher, `category` equal, JSON types kept. Total-not-grow follows from 1:1 pairing
plus bound checks plus "unpaired growth fails". It is a redundant invariant, checked by P1, with
approved keys excluded from both totals. No separate code path.

### 6.3 Registry table (61 ids at 8414da35c; A12 keeps it equal to `sentry_registry.toml`)

Shape notation: `F` file, `Q` qualname, `B` bound, `n` ordinal. Proof `def` is 6.1 content proof
plus `site_gone`; `rename` is the git rename check. Root is the prefix the file part is relative to.

| Id | Key shape | Location | Bound | Proof, root |
|----|-----------|----------|-------|-------------|
| f29-reason-baseline | `config::<code>` | none | code | NO_INFERENCE: a reason code, not a site |
| f29-producer-inventory | `F::Q::kind::B` | F, Q | kind, B | def, `src/decoy_engine/` |
| f29-consumer-inventory | `F::Q::B` | F, Q | B | def, `src/decoy_engine/` |
| secret-material-census | `F::Q::B` | F, Q | B | def, `src/` |
| module-size | `F` | F | none | rename, repo |
| public-import-boundary | `F` | F | none | rename, `src/decoy_engine/` |
| exception-hierarchy | `dotted.module::Class` | module | Class | def (class), `src/` dotted |
| file-access-entry-seams | `dotted.module.func` | module | func | def, `src/` dotted |
| post-scan-route-exempt | `dotted.module.func` | module | func | def, `src/` dotted |
| locator-waivers | `F::Q::B` | F, Q | B | def, `src/decoy_engine/` |
| log-interpolation | `F::Q::B` | F, Q | B | def, `src/decoy_engine/` |
| eval-sites | `F` | F | none | rename, `src/decoy_engine/` |
| phase-containment | bare name | none | name | NO_INFERENCE: no location part |
| validate-no-mutation | empty | none | none | NO_INFERENCE: empty baseline |
| physical-seam-connected | `F` | F | none | rename, `src/decoy_engine/` |
| wave-b-string-target-exempt | `testF::dotted.target` | testF | target | NO_INFERENCE: no def to compare; GA stub work owns it |
| wave-b-e0-test-files | `testF` | testF | none | rename, repo |
| handler-row-guard-exempt | `F` | F | none | rename, `src/decoy_engine/execution/` |
| private-file-sinks | `entry::F::Q::call::n` | F, Q | call, n | def, `src/` |
| gcs-call-kwargs | `F::Q::call::n` | F, Q | call, n | def, `src/` |
| serial-resources | `testF::test` | testF | test | def, repo |
| reason-policy-single-source | `F::func` | F | func | def, repo |
| reason-unchecked-helpers | `F::func` | F | func | def, `src/decoy_engine/` |
| exception-context | `F::Q::n` | F, Q | n | def, `src/` |
| validation-name-messages | `permitted::F::Q::hash` | F, Q | hash | NO_INFERENCE: `REKEY_PER_SITE` path |
| package-fanout | directory | dir | none | NO_INFERENCE: git does not report directory renames |
| import-layers | `layers::a -> b` | none | edge | NO_INFERENCE: an edge, not a site |
| table-kind-truth-tests | `F` | F | none | rename, `src/decoy_engine/` |
| post-scan-blocking | empty | none | none | NO_INFERENCE: empty baseline |
| post-scan-pass-through | `F::Q::kind::n` | F, Q | kind, n | def, `src/` |
| post-scan-key-core | empty | none | none | NO_INFERENCE: empty baseline |
| post-scan-reason-identity | empty | none | none | NO_INFERENCE: empty baseline |
| post-scan-gate-applies | empty | none | none | NO_INFERENCE: empty baseline |
| post-scan-commit | `F::Q::kind::n` | F, Q | kind, n | def, `src/` |
| post-scan-model-predicate | empty | none | none | NO_INFERENCE: empty baseline |
| post-scan-readability | empty | none | none | NO_INFERENCE: empty baseline |
| post-scan-route-coverage | empty | none | none | NO_INFERENCE: empty baseline |
| strategy-docs-agree | prose line | none | text | NO_INFERENCE: the key is doc text |
| win32-import-surface | `F::kind` | F | kind | rename, `src/` |
| platform-census | `F` | F | none | rename, `src/` |
| dir-fd-readers | `F` | F | none | rename, `src/` |
| physical-seam-scoped | `F::NAME` (module level) | F | NAME | rename, repo |
| ci-write-scopes | `x.yml::` | F | none | NO_INFERENCE: workflow permissions need review on rename |
| canonical-json-choke-point | `F::func` | F | func | def, `src/decoy_engine/` |
| ner-mismatch-single-site | `F::func` | F | func | def, `src/decoy_engine/` |
| validation-route-allowlist | `F::func` | F | func | def, `src/decoy_engine/` |
| snapshot-parse-single-owner | `F::func` | F | func | def, `src/decoy_engine/` |
| parquet-intermediate-writers | `F::func` | F | func | def, `src/` |
| metadata-carrier-allow | `F::func` | F | func | def, `src/` |
| date-shift-window-reader | `F::func` or `F::None` | F | func | def; `F::None` (module level) uses rename; `src/decoy_engine/` |
| group-by-single-reader | `F::func` | F | func | def, `src/decoy_engine/` |
| lossless-int-columns | `B::F::Q` (bound first) | F, Q | B | def, `src/decoy_engine/` |
| column-shape-classifier | `B::F` (bound first) | F | B | rename, `src/decoy_engine/` |
| bucketize-width-contract | `F` | F | none | rename, `src/decoy_engine/` |
| signature-exemptions | empty | none | none | NO_INFERENCE: empty baseline |
| output-assembly-one-path | `F::func` | F | func | def, `src/decoy_engine/` |
| faker-pool-size-one-resolver | empty | none | none | NO_INFERENCE: empty baseline |
| faker-native-allowlist-total | provider name | none | name | NO_INFERENCE: no location part |
| config-refusal-text | `F::Q::hash` | F, Q | hash | def, `src/decoy_engine/` |
| engine-exception-text-copies | `audit::F::Q::B::kind` | F, Q | B, kind | def, `src/decoy_engine/` |
| sentry-limits | `_ratchet.py::NAME` | none | NAME | NO_INFERENCE: `GUARD_KEYS` |

An empty baseline gets a row so that its first entry later cannot bypass A12. A key that does not
parse under its row is "not proven" (A13).

### 6.4 Relaxation of `_rehome.py:107`

Today a declared rehome is refused when the lost entry has a numeric `max`
(`max_of(lost[old]) is not None`, in `rehomes`, `tests/sentry/ratchet/_rehome.py:84`). MK allows it
when the head `max` is equal or lower. Reason: the stalled moves include counted entries, and an
equal or lower ceiling cannot loosen the guard; `loosened_findings` still runs after. Case A18.

### 6.5 Code layout and vendoring

- `tests/sentry/layout/_moves.py` (new, stdlib only, about 250 lines): key parsing from a passed-in
  identity table, pairing, entry match, def normalization. It takes the base reader, head reader
  and rename list as callables, so it has no repo imports. The engine is its source; the CLI
  copies it byte for byte, pinned by digest like `_ratchet_cases.py`.
- `tests/sentry/ratchet/_identity.py` (new, engine, about 120 lines): the 6.3 table and roots.
- `tests/sentry/ratchet/_rehome.py` (114 lines, about 140 after): wires `_moves.py` to `BaseTree`,
  the checkout reader and `git diff -M`; keeps `site_gone`.
- `tests/sentry/_ratchet.py` (582 lines): about 6 changed lines in the grown-key branch.
- `tests/sentry/layout/_ratchet_cases.py` (35 lines): adds a new repo-neutral `MOVE_CASES` table;
  `MAX_VALUE_CASES` and `REGISTRY_PATH_CASES` are unchanged. The A11 replay is engine-only and
  stays in `test_moved_keys.py`.
- MK-E1 updates the engine pin (`tests/sentry/layout/test_vendored_files.py:19`) and the vendored
  ledger rows. The CLI pin is one vendor behind today (CLI pins `038d0dff...`, engine is at
  `0305e162...`), so MK-C1 re-vendors across both changes.
- CLI: RG-C1a ports `_integrity.py` into CLI `tests/sentry/ratchet/`. MK-C1 adds the vendored
  `layout/_moves.py` and a CLI identity table `tests/sentry/ratchet/_identity.py` beside the ported
  `_integrity.py`. The CLI `_ratchet.py` is about 603 lines after RG-C1a and RG-C1b; MK-C1 adds zero
  net lines there: the body of `move_findings` is replaced by one call into `_moves.py`. The CLI
  declared `moved_from` keeps exact entry equality; only a lower `max` may relax it.

### 6.6 BD-E1 recognition rule

A write is routed when, in one function body: its sink argument is a `Name` bound exactly once,
by `with open_private(p) as h` or `h = open_private(p)`, and passed directly to `pq.write_table`,
`pq.ParquetWriter`, `pa.ipc.new_file` or `pa.ipc.new_stream`; or its path argument is a `Name`
bound exactly once by `precreate_private(p)` and passed directly to a duckdb `execute` COPY or an
ipc writer, with no `unlink`, `os.remove` or `open` of that name between. Not routed: a rebound
handle, an alias (`h2 = h`), a handle passed into another function (the callee is checked on its
own), an unlink then reopen. BD-A0 names one private-file owner: `fileaccess/_private.py`
(recommended) or `execution/out_of_core/_scratch.py`. The split of private helpers across those two
modules is recorded as a follow-up item, not V1 work.

### 6.7 Ordering and base-checker effect

MK-E1 starts after RG-E3 merges (hard dependency). RG-E3 makes the gate run the base checker
against the head, so a slice cannot use its own checker change to pass itself: inference applies to
PRs opened after MK-E1 merges, and MK-E1's own PR must carry no moves. RG-E3 already copies the
ratchet step log to gate stderr even on a pass (RG plan, limit L-A); A17 proves the inferred-move
lines are in it.

### 6.8 Design notes and choke point

- Principles: open/closed for key shapes (a new sentry adds one table row); one place per fact
  (move rules only in `_moves.py`, shapes only in `_identity.py`). Pattern: git rename detection.
- Refactoring names: BD-E1 and BD-E3 are Substitute Algorithm at each call site; BD-E2 is Move
  Function plus Replace Inline Code with Function Call.
- Choke point: the `_ratchet._check` grown-key branch (`tests/sentry/_ratchet.py:534` to `:545`)
  is the one place a grown key becomes a finding. Inference runs inside it, before
  `approved = grown & approvals`. Guard test
  `test_moved_keys.py::test_every_grown_key_reaches_one_verdict`: each grown key ends as moved,
  approved, or finding, exactly once. Mutation: M2.

## 7. Established solutions

Search run (2026-11-28): git rename detection, SonarQube issue tracking across moves, PHPStan
baseline behavior on moved files, plus the in-codebase ratchet helpers in both repos.

- git rename detection (`diffcore-rename.c`): exact matches, then content similarity, with a
  basename heuristic added in 2021 (Elijah Newren, "Optimization batch 7").
  https://lore.kernel.org/git/pull.843.v3.git.1612970140.gitgitgadget@gmail.com/
  We take exact identity plus content proof and the rename report itself (`git diff -M`); we drop
  the basename guess.
- SonarQube issue tracking: the server detects a file rename before it matches issues, so issues
  follow the file; an unmatched new issue is new.
  https://docs.sonarsource.com/sonarqube-server/user-guide/issues/solution-overview
- PHPStan baseline: counts per (message, file), no move inference, so a moved file shows as one new
  and one fixed entry. That is today's failure.
- House mechanism: `site_gone` (`tests/sentry/ratchet/_rehome.py:59`), `rehomes`
  (`tests/sentry/ratchet/_rehome.py:84`), `BaseTree` (`_integrity.py`), CLI `moved_from` and
  `split_from` maps. MK generalizes these; no second mechanism.
- The RATCHET-GROWTH plan's list (PHPStan baseline, pest-ratchets, Catraca, JSON Schema
  `additionalProperties`, PurePosixPath, git archive) applies unchanged.

Why custom code remains: no maintained library ratchets per-site AST baselines across two repos.

### Reuse inventory

| Need | Reuse | New |
|------|-------|-----|
| old site gone | `site_gone` (`_rehome.py:59`) | none |
| base file bytes | `BaseTree.blob` (`_integrity.py:101`) | none |
| file renames | `git diff -M` | none |
| declared moves | `rehomes` (`_rehome.py:84`) | relaxation 6.4 |
| loosened bounds | `bounds.loosened_findings` (`ratchet/_bounds.py`) | none |
| stale entries | each sentry's stale test, `test_baseline_registry.py` mirror | none |
| private files | `open_private` (`execution/out_of_core/_scratch.py:25`), `precreate_private` (`:54`), `write_private` (`fileaccess/_private.py:21`) | none |
| table kind | `generate_columns_of` (`config/_tables.py:485`) | none |
| cross-repo sync | digest-pinned vendoring (`test_vendored_files.py`) | `_moves.py` added to it |

## 8. Placement and slices

| New file | Directory | CODEMAP line | Beside |
|----------|-----------|-------------|--------|
| `_moves.py` | `tests/sentry/layout/` | sentry helpers shared with the CLI | `_ratchet_cases.py` |
| `_identity.py` | `tests/sentry/ratchet/` | ratchet helpers | `_rehome.py` |
| `test_moved_keys.py` | `tests/sentry/ratchet/` | ratchet tests | `test_bounds.py` |
| ledger record | `docs/records/` (`YYYY-MM-DD-ratchet-burndown-ledger.md`, dated on BD-A0) | records | other records |
| CLI `_identity.py` | CLI `tests/sentry/ratchet/` | ported by RG-C1a | `_integrity.py` |

| Slice | Repo | What | Depends on | Risk | Size |
|-------|------|------|-----------|------|------|
| MK-E1 | engine | `_moves.py`, `_identity.py`, `MOVE_CASES`, rehome relaxation, A1 to A20, P1 | RG-E3 merged (hard), OQ1 | R2 (test tooling: full suite) | 1.5 days |
| MK-C1 | CLI | vendor `_moves.py`, CLI identity table, `move_findings` call | MK-E1, RG-C1b | R2 (test tooling) | 0.5 day |
| BD-A0 | engine | ledger record: kind, owner helper, target, owning row, private-file owner | OQ1 | R0 (doc) | 0.5 day |
| BD-E1 | engine | recognition rule 6.6; pool-quality spool onto `open_private` | BD-A0 | R2 (private file class) | 0.5 day |
| BD-E2 | engine | lossless-int-columns sites call one ingestion helper | BD-A0, OQ5 | R2 (FK lane) | 1 day |
| BD-E3 | engine | inline `.get("generate_columns")` truth tests call `generate_columns_of` | BD-A0 | R1 | 0.5 day |
| BD-E4 | engine | public `list_mask_strategies`, `checksums.list_schemes`, `validators.list_validators` | OQ4 | R1 (additive API) | 0.5 day |
| BD-C1 | CLI | csv-read-allow, scan-call-allow, target-writes-allow, config-load-allow to their owners | BD-A0 | R1 | 0.5 day |
| BD-C2 | CLI | drop engine-internal-allow #2 to #4 after the repin with BD-E4 | BD-E4 release | R1 | 0.25 day |

Nine slices, about 5.5 build days. Further burn slices come by plan amendment after BD-A0 and OQ5.
Sizes: `_rehome.py` about 140, `_identity.py` about 120, `_moves.py` about 250,
`test_moved_keys.py` about 550 (split the replay into `test_moved_keys_replay.py` if it passes
600), engine `_ratchet.py` 588, CLI `_ratchet.py` unchanged in net lines. New public names: BD-E4's
three accessors only.

Tests per slice: T0 per edit, T1 per commit. MK-E1 and MK-C1 hit the "test tooling" trigger, so
each runs the full suite once on its merge head against the saved main baseline (`decoy-vm-t3`
default mode). BD-E2 runs the FK companion suite. Builders follow TEST-RUNBOOK.md and do not run t1.

## 9. Class table

| # | Class | Where it can happen | Closing structure | Sentry or test | Mutation |
|---|-------|---------------------|-------------------|----------------|----------|
| 1 | value-bearing output | report lines, findings | report lines carry keys only (paths, qualnames, bound names), never data values | A1 asserts the exact line | N/A: keys hold no data values; no new value surface |
| 2 | cleanup on exit paths | pool-quality spool | `open_private` handle in `with`; existing `finally` unlink kept | B1 (mode 0600 under umask 022) | M6 (plain `open`) |
| 3 | state and concurrency | checker helpers | `infer_moves` is a pure function of its arguments; no module cache | A19 `test_infer_moves_is_pure` | N/A: no shared state is added; A19 guards purity |
| 4 | route parity, silent fallback | a move that cannot be proven | falls back to growth, which fails; never to pass | A3, A4, A13, A16 | M1, M2, M9 |
| 5 | referential integrity | BD-E2 FK ingestion | one helper per site; byte goldens | D1 (FK byte goldens) | M8 (`to_pandas()` swap) |
| 6 | untrusted producer | baseline JSON edited by a builder | base read through `BaseTree.blob`; inference cannot pass a raised bound | A2, A10, A18 | M3 |
| 7 | toctou / check-then-use | proof at head vs base | content proof reads both sides from the commits the gate checks, not the work tree alone | A15 (unrelated swap) | M5 (skip content compare) |
| 8 | weak tests | moves that look like growth | real-history replay, positive and negative | A11 replay set | M1 (tie accepted) |
| 9 | refactor drift | burn slices | no behavior change: goldens and existing sentries stay green | D1, C1 | M7 |
| 10 | frozen contract drift | BD-E4 public names; vendored helpers | compatibility entry, surface snapshot, digest pins | E2, E3, vendored pin tests | N/A for MK: no frozen contract touched |

Recurring defect catalog: anchored validation N/A (no pattern match on values); strict types: an
int `max` against a bool `max` is a finding; no exception context N/A (no new raised error);
normalized guard scanners: B3 seeds the alias and pass-through spellings; no hidden CI failures:
plain pytest; allowlisted helpers still checked: B3, C2; no raised caps: no module-size pin raised.

## 10. Enumerations

### Exit paths (verdict for one grown key)

- declared move accepted (`tests/sentry/_ratchet.py:534` branch)
- inferred move accepted (same branch)
- approved growth (`tests/sentry/_ratchet.py:545`)
- finding: growth, tie, proof missing, content changed, no git rename, bound loosened
- malformed key: no inference, stays growth (A13)

### Routes (baseline kinds through the checker)

- `GUARD_KEYS` (`tests/sentry/_ratchet.py:52`): no inference
- `REKEY_PER_SITE` (`tests/sentry/_ratchet.py:40`): existing re-key path only
- `REHOME_BY_BINDING` (`tests/sentry/_ratchet.py:45`): declared as today, plus inference
- def-proof rows and rename-proof rows of the 6.3 table; `NO_INFERENCE` rows: unchanged

### FK shapes (BD-E2 only)

- single-column int FK; composite FK; self-reference; nullable FK; int64 key above 2**53.
- MK: N/A, it reads baselines, not data.

### Fields (baseline entry)

- `reason` (may differ on a move), `max` (equal or lower), `min` (equal or higher)
- `category` (equal), `moved_from` (declared old key), JSON type of each (kept)

### Output surfaces

- `scripts/dev/ratchet_check.py` report and findings, copied to gate stderr (A17)
- the pool-quality spool file mode (`src/decoy_engine/execution/native/_pool_quality.py:248`)
- BD-E4 public names and the CLI `list strategies|checksums|validators` output (same names)

## 11. Frozen contracts and compatibility

- `scripts/dev/sentry_registry.toml` closed schema (`ROW_KEYS = {"id","baseline","approved_growth"}`):
  unchanged. The identity table lives in code.
- Baseline JSON schema unchanged; `moved_from` is an existing optional field.
- Vendored files (`_ratchet_cases.py`, new `_moves.py`): engine first, CLI re-vendors with new
  digests and ledger rows.
- BD-E4: compatibility entry as additive, CHANGELOG `Added:` line, surface snapshot updated.
- No CLI output byte change.

## 12. Pre-mortem

- "Inference let a real new site through." Answer: one location part kept, def-content proof,
  uniqueness with no tie-break, git rename for bare files, a reviewed stderr line. A15, A16 and the
  A11 negative replay seed the laundering shapes.
- "Open PRs with `moved_from` break after MK-E1." Answer: the present declared form is a control
  (A14); merged ones join the A11 replay.
- "CLI and engine drift." Answer: one vendored `_moves.py` and `MOVE_CASES`, digest pinned.
- "Burndown turns into a refactor program." Answer: three burn slices start before OQ5; the rest
  wait for a signed ledger.
- "BD-E2 changes FK bytes." Answer: D1 goldens must stay green; a byte change stops the slice.
- "PR #427 is not merged and the rows change." Answer: OQ1; build does not start before the merge.

## 13. Guard ledger (input to BD-A0; counts at engine 8414da35c and CLI 2ca3bbd4)

| Guard | Count | Owner helper | Target | Slice |
|-------|-------|-------------|--------|-------|
| private-file-sinks (engine) | 17 | `open_private`, `precreate_private`, `write_private` | 6 or fewer | BD-E1 |
| table-kind-truth-tests | 26 | `generate_columns_of` | 1 (`config/_tables.py`) | BD-E3 |
| lossless-int-columns | 17 | `lossless_int_columns`, `to_pandas_fk_safe` | set in BD-A0 (OQ5) | BD-E2 |
| engine-internal-allow (CLI) | 10 | engine public API | 7 (logging #1 stays) | BD-E4, BD-C2 |
| csv-read, scan-call, target-writes, config-load allow (CLI) | 1, 1, 1, 11 | named in BD-A0 | set in BD-A0 | BD-C1 |
| canonical-json, snapshot-parse, group-by, date-shift | 12, 11, 6, 14 | `_canonical`, `parse_snapshot_json`, `group_by_sibling`, `shift_window` | amendment | later |
| metadata-carrier, parquet-intermediate-writers, column-shape | 14, 8, 6 | per BD-A0 | amendment | later |

Pool-quality spool today: written at the umask inside a temp dir that `connect_duckdb` restricts to
0700, unlinked in `finally`. No leak today; BD-E1 makes the file 0600 by construction.

Out of scope: census baselines and F31-owned lists, module-size (OQ3), CLI gate-single-entry-allow
(CONFIG-EXPLICIT C2), CLI private-file-sinks (WIN-FEAS).

## 14. Related plans

- `docs/plans/2026-11-24-postmask-fail-closed-and-ratchet-growth.md` (RG-E3, RG-C1a, RG-C1b).
- F31-AUDIT AE5b, AC1, AC3; CLI-SPLIT S2; EW2 to EW5; CONFIG-EXPLICIT C2.

## 15. Open owner questions (recommendation first)

- OQ1. PR #427 adds both rows and is not merged. (a) Merge as is and build this plan [recommended];
  (b) merge only the moved-keys widening, hold BURNDOWN for 1.x; (c) hold both.
- OQ2. Inferred moves with a stderr line, or declared `moved_from` only? (a) inferred plus declared
  [recommended, matches "a pure move needs no hand-written row"]; (b) declared only, widened.
- OQ3. Engine module-size burndown (25 entries, 9 under `scripts/`). (a) defer to STRUCTURE-REVIEW
  in 1.x [recommended, on the "Not now" list]; (b) `scripts/` entries only now; (c) all now.
- OQ4. BD-E4 adds three public engine accessors in 1.0. (a) yes, additive and already requested
  in `docs/handoffs/inputs/cli-needs-engine-public-api.md` [recommended]; (b) 1.x.
- OQ5. Burndown targets: (a) a reasoned floor per guard, signed in the BD-A0 ledger [recommended];
  (b) zero for every debt guard; (c) only the three slices here for 1.0, rest 1.x.
