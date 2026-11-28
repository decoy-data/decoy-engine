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

Risk: R2 for the plan as a whole (test tooling that gates every merge, and one private-file
change). Per slice in section 8.

## 2. Guarantee and non-goals

Pinned guarantee (MK): a key that moves 1:1, with the same bound name, no looser bounds, the same
category, the old site proven gone, and no growth in the sentry's total, passes the ratchet with no
`approved_growth` row. Every inferred move prints one report line. Anything else is still growth.

Pinned guarantee (BD): each debt guard named in the ledger (section 13) ends at or below its target
count, and each removed entry is routed through the guard's named owner helper. No baseline gains a
key and no allow-list gains an entry in any slice of this plan.

Non-goals:
- No change to growth rules: real growth still needs a dated owner row.
- No inferred split (one key into many) or merge (many into one). CLI `split_from` stays as is.
- No inferred moves for `GUARD_KEYS` (`sentry-limits`) or `REKEY_PER_SITE`
  (`validation-name-messages`) (`tests/sentry/_ratchet.py:40`, `tests/sentry/_ratchet.py:52`).
- Not the outbound-text burndown: engine-exception-text-copies, config-refusal-text, CLI
  one-error-emitter, engine-reason-code-copies stay with F31-AUDIT (AE5b, AC1, AC3).
- Not module-size (engine: STRUCTURE-REVIEW, "Not now"; CLI: CLI-SPLIT S2) unless OQ3 says so.
- Not census baselines (f29-producer, f29-reason, f29-consumer, secret-material-census,
  serial-resources, gcs-call-kwargs, import-layers, platform-census, exception-context,
  win32-import-surface). They record inventory, not debt. win32-import-surface entries are owned
  by EW2 to EW5.
- Not CLI lint-debt (its own tool and row).
- Not RATCHET-GROWTH RG-E3, RG-C1a, RG-C1b (already planned in
  `docs/plans/2026-11-24-postmask-fail-closed-and-ratchet-growth.md`). MK builds on them.

## 3. Established solutions

Search run (2026-11-28): git rename detection, SonarQube issue tracking across moves, PHPStan
baseline behavior on moved files, plus the in-codebase ratchet helpers in both repos.

- git rename detection (`diffcore-rename.c`): exact matches first, then a pairing guided by
  basenames that are unique among the candidates (Elijah Newren, "Optimization batch 7: use file
  basenames to guide rename detection", git list, 2021-02). We copy the shape: exact identity
  first, pair only when the candidate is unique on both sides, never guess among several.
  https://lore.kernel.org/git/pull.843.v3.git.1612970140.gitgitgadget@gmail.com/
- SonarQube issue tracking: the server detects a file rename before it matches issues, so issues
  follow the file; an unmatched new issue is new, an unmatched old issue is fixed.
  https://docs.sonarsource.com/sonarqube-server/user-guide/issues/solution-overview
  We copy "follow the move, then compare" and "unmatched means new".
- PHPStan baseline: counts per (message, file). It has no move inference, so a moved file shows as
  one new and one fixed entry. That is the failure we have today; the plan fixes it the Sonar way.
- The house mechanism: `tests/sentry/ratchet/_rehome.py` already proves a site gone by AST
  (`site_gone`, `tests/sentry/ratchet/_rehome.py:59`) and pairs declared moves
  (`rehomes`, `tests/sentry/ratchet/_rehome.py:84`). The CLI has a top-level `moved_from` map and
  `split_from` (CLI `tests/sentry/_ratchet.py`, docstring). MK generalizes these. It does not add
  a second mechanism.
- The RATCHET-GROWTH plan's established-solutions list (PHPStan baseline, pest-ratchets, Catraca,
  JSON Schema `additionalProperties`, PurePosixPath, git archive) applies unchanged.

Why custom code remains: no maintained library ratchets per-site AST baselines across two repos;
the house checker is the existing tool, so MK extends it in place.

### Reuse inventory

| Need | Reuse | New |
|------|-------|-----|
| proof the old site is gone | `site_gone` (`_rehome.py:59`) | a file-only and dotted-module proof beside it |
| declared moves | `rehomes` (`_rehome.py:84`) | `infer_moves` in the same module |
| key parsing | `_site_parts` | a per-sentry identity function table |
| loosened-bound check | `bounds.loosened_findings` (`ratchet/_bounds.py`) | none |
| stale-entry proof | each sentry's stale test, `test_baseline_registry.py` mirror | none |
| private file creation | `open_private` (`execution/out_of_core/_scratch.py:25`), `precreate_private` (`:54`), `write_private` (`fileaccess/_private.py:21`) | none |
| table kind | `generate_columns_of` (`config/_tables.py:485`), `classify_table_kinds` | none |
| CLI helper sync | vendored `_ratchet_cases.py` pinned by digest (CLI `tests/sentry/layout/test_vendored_files.py`) | re-vendor after MK-E1 |

## 4. Behavior

MK, engine and CLI:
1. After the existing declared re-home step, every baseline not in `GUARD_KEYS` or
   `REKEY_PER_SITE` runs `infer_moves(lost, grown)`.
2. The identity of a key is the key with its location segment removed. Location is the file part,
   or the file plus qualname part when the qualname also changed (the rename case). The bound name
   (the last `::` segment) and any ordinal must be equal. One identity function per key shape
   (section 6).
3. A lost key and a grown key pair only when each is the only candidate of its identity on its side.
   A tie between two or more candidates is broken only by an equal basename on exactly one candidate
   (git's rule). Otherwise no pair; the grown key stays growth and the finding names the tie.
4. A pair is accepted only when: the grown entry equals the lost entry except `reason` text and
   bounds; `max` is equal or lower; `min` is equal or higher; `category` is equal; and the old site
   is proven gone. Proof: `site_gone` for `<file>::<qualname>::<name>` keys; for a file-only key the
   file is absent at head and existed at base; for a dotted module key the module or attribute is
   absent by AST. A key with no available proof is never inferred (declared `moved_from` still works).
5. After pairing, the sum of `max` (or the entry count where there is no `max`) across the
   baseline must not exceed the base sum. This is the owner's "the total must not grow".
6. Each accepted pair prints `<sid>: moved <old> -> <new> (inferred; old site gone; bounds kept)`.
7. Declared `moved_from` (engine per-entry, CLI top-level map) is widened from the two rehome
   sentries to every non-guard sentry, with the same proofs. Declared wins over inferred.

BD: each burn slice moves sites onto the named helper, lowers the inline allow-list and the JSON
baseline together, and adds one seeded case per guard that shows a new direct site still fails.

## 5. Failure modes

| # | Failure | Guard |
|---|---------|-------|
| F1 | a new site is laundered as a move of a deleted unrelated site with the same bound name | uniqueness on both sides, entry equality, total-not-grow, report line reviewed at gate |
| F2 | a move raises `max` | bounds check after pairing; `loosened_findings` unchanged |
| F3 | the old site is still live under the old key (copy, not move) | proof of absence; mirror test |
| F4 | two sites move at once and swap identities | uniqueness fails, falls back to growth |
| F5 | a `sentry-limits` key moves and hides a raised limit | excluded by `GUARD_KEYS` |
| F6 | CLI and engine checkers disagree on a move | shared case table in vendored `_ratchet_cases.py`, digest pin |
| F7 | a burn slice changes output bytes on the FK lane | BD-E2 byte goldens |
| F8 | a burn slice moves a private write onto a helper that does not apply 0600 | BD-E1 stat test under umask 022 |
| F9 | a stale baseline entry stays after the site is routed | each sentry's stale test (already exists) |
| F10 | the checker crashes on an odd key and passes the run | malformed-key cases return "not proven", never raise; existing `test_malformed_registry.py` pattern |

## 6. Design notes

- Principles: open/closed for key shapes (a new sentry adds one identity function, the checker is
  unchanged); one place per fact (identity rules live only in `_rehome.py`). Pattern: git
  rename detection, cited above.
- Identity table: a dict `IDENTITY: {sid: callable}` in `_rehome.py`. Default shape
  `<file>::<qualname>::<name>[::ordinal]`. Other shapes in use: `entry::<file>::<qualname>::<call>::<n>`
  (private-file-sinks), bare `<file>` (table-kind-truth-tests, module-size), dotted
  `decoy_engine.<module>.<attr>` (post-scan-route-exempt), `<file>::<qualname>` (single-owner
  sentries). A sentry with no identity function gets no inference. The table is closed: a test
  asserts every registry row is either in `IDENTITY`, in an explicit `NO_INFERENCE` set with a
  reason, or a guard.
- Ordering: MK-E1 lands after RG-E3 (gate runs the base checker) so the gate also runs the
  inference on the base side. If RG-E3 is not merged when MK-E1 is ready, MK-E1 rebases onto it.
- `_ratchet.py` is 582 lines. The call site change is about 6 lines; all logic goes in
  `_rehome.py` (114 lines, about 260 after). If `_rehome.py` would pass 400 lines, the identity
  table goes to `ratchet/_identity.py`.
- CLI: `_ratchet.py` is 558 lines. The CLI port puts inference in a new
  `tests/sentry/ratchet_moves.py` (CLI flat layout) and calls it from `move_findings`. The case
  table shared with the engine is added to `_ratchet_cases.py`, landed in the engine first, then
  re-vendored with new digests (CLI `test_vendored_files.py` rule).
- BD audit first: BD-A0 writes the ledger as a record doc and the owner signs targets (OQ5) before
  burn slices beyond BD-E1, BD-E3 and BD-C1 start. Those three have clear homes today.
- Refactoring names (refactoring.md): BD-E1 and BD-E3 are Substitute Algorithm at each call site
  (replace an inline spelling with the owner call); BD-E2 is Move Function plus Replace Inline Code
  with Function Call.

### Choke point

`_ratchet._check` grown-key branch (`tests/sentry/_ratchet.py:534` to `:545`) is the one place a
grown key becomes a finding. MK adds no second path: inference runs inside that branch, before
`approved = grown & approvals`. Guard test: `test_moved_keys.py::test_every_grown_key_reaches_one_verdict`
asserts each grown key ends as moved, approved, or finding, exactly once. Mutation: skip the
`site_gone` call in `infer_moves` (A4 red).

## 7. Placement (engine CODEMAP "Where things go")

| Change | Place | Why |
|--------|-------|-----|
| inference logic | `tests/sentry/ratchet/_rehome.py` | ratchet helpers live in `tests/sentry/ratchet/` |
| inference tests | `tests/sentry/ratchet/test_moved_keys.py` (new, under 600) | beside `test_bounds.py` |
| historical replay cases | `tests/sentry/layout/_ratchet_cases.py` | vendored to the CLI |
| ledger record | `docs/audits/2026-11-ratchet-burndown-ledger.md` (new) | audit records go in `docs/audits/` |
| pool-quality spool | `src/decoy_engine/execution/native/_pool_quality.py` | in place |
| public accessors (BD-E4) | `checksums/__init__.py`, `validators/__init__.py`, top-level `decoy_engine.__init__` export | public names on the owning package |
| CLI inference | CLI `tests/sentry/ratchet_moves.py` | CLI sentry layout is flat |

Size: `_rehome.py` about 260 lines, `test_moved_keys.py` about 450, `_ratchet.py` 588,
`_pool_quality.py` unchanged size, CLI `_ratchet.py` about 565, CLI `ratchet_moves.py` about 200.
New public names: `infer_moves` (test helper only); BD-E4 `list_mask_strategies`,
`checksums.list_schemes`, `validators.list_validators`.

## 8. Slices

| Slice | Repo | What | Depends on | Risk | Size |
|-------|------|------|-----------|------|------|
| MK-E1 | engine | inferred 1:1 moves plus widened declared `moved_from`, identity table, report lines, historical replay | RG-E3, OQ1 | R2 (test tooling: full-suite trigger) | 1 day |
| MK-C1 | CLI | port to CLI checker, unify with top-level `moved_from`, re-vendor `_ratchet_cases.py` | MK-E1, RG-C1b | R2 (test tooling) | 0.5 day |
| BD-A0 | engine | ledger record of every engine and CLI guard: kind, owner helper, target, owning row | OQ1 | R0 (doc) | 0.5 day |
| BD-E1 | engine | private-file-sinks: count writes into an `open_private`/`precreate_private` handle as routed; move the pool-quality spool onto `open_private` | BD-A0 | R2 (private file class) | 0.5 day |
| BD-E2 | engine | lossless-int-columns: each listed site calls one ingestion helper | BD-A0, OQ5 | R2 (FK lane, byte goldens) | 1 day |
| BD-E3 | engine | table-kind truth tests: inline `.get("generate_columns")` truth tests call `generate_columns_of` | BD-A0 | R1 (mechanical) | 0.5 day |
| BD-E4 | engine | public `list_mask_strategies`, `checksums.list_schemes`, `validators.list_validators` | OQ4 | R1 (additive API, compat entry) | 0.5 day |
| BD-C1 | CLI | small CLI lists: csv-read-allow, scan-call-allow, target-writes-allow, config-load-allow routed to their owners | BD-A0 | R1 | 0.5 day |
| BD-C2 | CLI | after the repin carrying BD-E4, drop engine-internal-allow #2 to #4 | BD-E4 release | R1 | 0.25 day |

Nine slices, about 5 build days. Further burn slices (canonical-json, snapshot-parse, group-by,
date-shift, metadata-carrier, parquet-intermediate-writers) are added by plan amendment after
BD-A0 and OQ5. Each slice is one PR, one Conventional Commits subject, final line `cam`.

### Tests per slice (Test depth)

T0 touched tests per edit; T1 impact selection per commit. MK-E1 and MK-C1 hit the "test tooling"
escalation trigger, so each runs the full suite once on its merge head, diffed against the saved
main baseline (`decoy-vm-t3` default mode). BD-E2 runs the FK companion suite. Builders follow
TEST-RUNBOOK.md and do not run t1 themselves.

## 9. Acceptance tests (red before their slice unless marked control)

MK-E1 (`tests/sentry/ratchet/test_moved_keys.py`, seeded trees and baselines):
- A1 a pure file move of one key, same bound name, same `max`, old file gone: passes with no
  `approved_growth`; one report line.
- A2 same move with `max` raised by 1: finding.
- A3 two lost keys and one grown key of the same identity, no unique basename: finding naming the tie.
- A4 old site still present (copy): finding.
- A5 bound name differs: finding.
- A6 move accepted but a second unrelated new key appears: the new key is a finding; total check holds.
- A7 a `sentry-limits` key moves: finding (guard keys excluded).
- A8 a `validation-name-messages` move follows its existing re-key path, unchanged (control).
- A9 qualname rename in the same file (`_derive_pool_indices` to `derive_pool_indices` shape): passes.
- A10 `min` lowered on a move: finding. `category` changed: finding.
- A11 replay: the six historical moves listed in section 1, rebuilt as seeded cases, pass with no
  approval row. Red before: each needs a row today.
- A12 every registry row is in `IDENTITY`, `NO_INFERENCE` with a reason, or a guard.
- A13 malformed key (no `::`, non-identifier qualname, lambda): no inference, no exception.
- A14 declared `moved_from` on a non-rehome sentry (lossless-int) passes; on `sentry-limits` fails.

MK-C1 (CLI `tests/sentry/test_ratchet_check.py` additions): A1, A2, A3, A4, A7 on the CLI checker
using the shared cases; a top-level `moved_from` entry and an inferred move for the same key give
one verdict, declared wins; `split_from` cases unchanged (control).

BD-E1:
- B1 under umask 022, the pool-quality spool file is created mode 0600 (stat inside the run).
- B2 private-file-sinks baseline drops the pool-quality entry and each entry now written through an
  `open_private` handle; stale test green.
- B3 seeded: `pq.write_table` into a plain `open()` handle in a temp tree is still a finding;
  into an `open_private` handle is not (the new recognition).

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

## 10. Named mutations (each turns its named test red on the final head)

- M1 drop the uniqueness check in `infer_moves` (A3 red).
- M2 drop the `site_gone` call (A4 red).
- M3 compare `max` with `>=` instead of `<=` (A2 red).
- M4 include `GUARD_KEYS` in inference (A7 red).
- M5 skip the total-not-grow check (A6 red).
- M6 `open_private` back to `open(..., "wb")` in `_pool_quality.py` (B1 red).
- M7 restore one inline `.get("generate_columns")` truth test (C2 red).
- M8 swap the int64 ingestion helper for `to_pandas()` in one BD-E2 site (D1 red).

## 11. Class table

| # | Class | Where it can happen | Closing structure | Sentry or test | Mutation |
|---|-------|---------------------|-------------------|----------------|----------|
| 1 | value-bearing output | report lines, findings | report lines carry keys only (paths, qualnames, bound names), never data values | A1 asserts the exact line | N/A: keys hold no data values; no new value surface |
| 2 | cleanup on exit paths | pool-quality spool | `open_private` handle in `with`; existing `finally` unlink kept | B1 (mode 0600 under umask 022) | M6 (plain `open`) |
| 3 | state and concurrency | checker globals | `infer_moves` is a pure function of its arguments; no module cache | A12 runs it twice on one tree | N/A: no shared state is added |
| 4 | route parity, silent fallback | a move that cannot be proven | falls back to growth, which fails; never to pass | A3, A4, A13 | M1, M2 |
| 5 | referential integrity | BD-E2 FK ingestion | one helper per site; byte goldens | D1 (FK byte goldens) | M8 (`to_pandas()` swap) |
| 6 | untrusted producer | baseline JSON edited by a builder | the checker reads base and head through the existing reader guard; inference cannot pass a raised bound | A2, A10 | M3 |
| 7 | toctou / check-then-use | proof at head vs base | proof reads the head tree the gate checks out, same reader as `site_gone` today | A4 (copy, not move) | M2 (skip `site_gone`) |
| 8 | weak tests | moves that look like growth | historical replay A11 from real past moves | A11 | M1 |
| 9 | refactor drift | burn slices | no behavior change: goldens and existing sentries stay green | D1, C1 | M7 |
| 10 | frozen contract drift | BD-E4 public names; vendored helper | compatibility entry and surface snapshot; digest pin re-vendor | E2, E3, CLI vendored test | N/A for MK: no frozen contract touched |

Recurring defect catalog: anchored validation N/A (no pattern match on values); strict types: key
parts compared as `str` only, an int `max` against a bool `max` is a finding (JSON types kept, CLI
rule); no exception context N/A (no new raised error); normalized guard scanners: BD-E3 counts
every spelling the sentry already counts; no hidden CI failures: plain pytest; allowlisted helpers
still checked: B3, C2; no raised caps: no module-size pin raised.

## 12. Enumerations

### Exit paths (verdict for one grown key)

- declared move accepted (`tests/sentry/_ratchet.py:534` branch, existing)
- inferred move accepted (new, same branch)
- approved growth (`tests/sentry/_ratchet.py:545`)
- finding: growth, tie, proof missing, bound loosened, total grew
- malformed key: no inference, stays growth (A13)

### Routes (baseline kinds through the checker)

- `GUARD_KEYS` (`tests/sentry/_ratchet.py:52`): no inference
- `REKEY_PER_SITE` (`tests/sentry/_ratchet.py:40`): existing re-key path only
- `REHOME_BY_BINDING` (`tests/sentry/_ratchet.py:45`): declared, now also inferred
- every other row in `scripts/dev/sentry_registry.toml`: declared and inferred when in `IDENTITY`

### FK shapes (BD-E2 only)

- single-column int FK; composite FK; self-reference; nullable FK; int64 key above 2**53.
- MK: N/A, it reads baselines, not data.

### Fields (baseline entry)

- `reason` (may differ on a move), `max` (equal or lower), `min` (equal or higher)
- `category` (equal), `moved_from` (declared old key), JSON type of each (kept)

### Output surfaces

- `scripts/dev/ratchet_check.py` report and findings (CI log)
- the pool-quality spool file mode (`src/decoy_engine/execution/native/_pool_quality.py:248`)
- BD-E4 public names in `decoy_engine` and the CLI `list strategies|checksums|validators` output
  (same names, no byte change)

## 13. Guard ledger (input to BD-A0; counts at engine 8414da35c and CLI 2ca3bbd4)

Debt guards in scope (owner helper, proposed target, slice):

| Guard | Count | Owner helper | Target | Slice |
|-------|-------|-------------|--------|-------|
| private-file-sinks (engine) | 17 | `open_private`, `precreate_private`, `write_private` | 6 or fewer (the helpers' own sites plus quarantine) | BD-E1 |
| table-kind-truth-tests | 26 | `generate_columns_of`, `classify_table_kinds` | 1 (`config/_tables.py`) | BD-E3 |
| lossless-int-columns | 17 | `lossless_int_columns`, `to_pandas_fk_safe` | set in BD-A0 (OQ5) | BD-E2 |
| engine-internal-allow (CLI) | 10 | engine public API | 7 (logging #1 stays) | BD-E4, BD-C2 |
| csv-read-allow, scan-call-allow, target-writes-allow, config-load-allow (CLI) | 1, 1, 1, 11 | the CLI owner of each (BD-A0 names it) | set in BD-A0 | BD-C1 |
| canonical-json-choke-point | 12 | `decoy_engine._canonical` | amendment | later |
| snapshot-parse-single-owner | 11 | `parse_snapshot_json` (most entries decode config_json, not snapshot bytes: maybe a scope fix) | amendment | later |
| group-by-single-reader | 6 | `group_by_sibling` | amendment | later |
| date-shift-window-reader | 14 | `shift_window` (most entries are other strategies: scope fix) | amendment | later |
| metadata-carrier-allow, parquet-intermediate-writers, column-shape-classifier | 14, 8, 6 | per BD-A0 | amendment | later |

Pool-quality spool today: written at the umask inside a temp dir that `connect_duckdb` restricts to
0700, unlinked in `finally`. No leak today because of the 0700 directory; BD-E1 makes the file 0600
by construction so the guarantee does not rest on the directory.

Out of scope: census baselines and F31-owned lists (section 2), module-size (OQ3), CLI
gate-single-entry-allow (CONFIG-EXPLICIT C2 owns), CLI private-file-sinks (WIN-FEAS owns).

## 14. Frozen contracts and compatibility

- `scripts/dev/sentry_registry.toml` closed schema (`ROW_KEYS = {"id","baseline","approved_growth"}`):
  unchanged. No new registry key; `IDENTITY` lives in code.
- Baseline JSON schema: unchanged; `moved_from` is an existing optional field.
- Vendored `_ratchet_cases.py`: changes land in the engine first, the CLI re-vendors and updates
  both PINS and `ci/vendored.toml` (CLI `test_vendored_files.py`).
- BD-E4 adds public names: compatibility entry as additive, CHANGELOG `Added:` line, public surface
  snapshot updated. No removal.
- No CLI output byte change.

## 15. Related plans

- `docs/plans/2026-11-24-postmask-fail-closed-and-ratchet-growth.md` (RG-E3, RG-C1a, RG-C1b).
- F31-AUDIT AE5b, AC1, AC3 (outbound text).
- CLI-SPLIT S2 (CLI module-size), EW2 to EW5 (win32 surface), CONFIG-EXPLICIT C2.

## 16. Pre-mortem

- "Inference let a real new site through." Cause: identity too coarse. Answer: uniqueness on both
  sides, entry equality, total check, proof of absence, and a reviewed report line. A11 replays real
  moves; A3, A4, A6 seed the laundering shapes.
- "MK-E1 and RG-E3 conflict in `_ratchet.py`." Answer: MK-E1 waits for RG-E3 and changes about 6
  lines there; logic stays in `_rehome.py`.
- "CLI and engine drift." Answer: shared case table, digest pin, MK-C1 runs the same cases.
- "Burndown turns into a refactor program." Answer: only three burn slices start before OQ5; each
  is a routing change with a target; the rest wait for a signed ledger.
- "BD-E2 changes FK bytes." Answer: D1 goldens are a control that must stay green; any byte change
  stops the slice.
- "PR #427 is not merged and the rows change." Answer: OQ1; build does not start before the merge.

## 17. Open owner questions (recommendation first)

- OQ1. PR #427 adds both rows and is not merged. (a) Merge as is and build this plan [recommended];
  (b) merge only the moved-keys widening, hold BURNDOWN for 1.x; (c) hold both.
- OQ2. Inferred moves with a report line, or declared `moved_from` only? (a) inferred plus declared,
  report line reviewed at the gate [recommended, matches "a pure move needs no hand-written row"];
  (b) declared only, widened to every sentry.
- OQ3. Engine module-size burndown (25 entries, 9 under `scripts/`). (a) defer to STRUCTURE-REVIEW
  in 1.x [recommended, it is on the "Not now" list]; (b) `scripts/` entries only now; (c) all now.
- OQ4. BD-E4 adds three public engine accessors in 1.0. (a) yes, additive and already requested
  in `docs/handoffs/inputs/cli-needs-engine-public-api.md` [recommended]; (b) 1.x.
- OQ5. Burndown targets: (a) a reasoned floor per guard, signed in the BD-A0 ledger [recommended];
  (b) zero for every debt guard; (c) only the three slices here for 1.0, rest 1.x.
