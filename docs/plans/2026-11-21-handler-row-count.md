Status: plan

# HANDLER-ROW-COUNT: close-out (the guard shipped in engine #744)

Owner: Cam. Author: Opus plan agent. Date: 2026-11-21. Roadmap row: HANDLER-ROW-COUNT (CLI `docs/roadmap/groups/run.md:28`, state NOT STARTED at CLI `8d17419c`). Origin: vault `30_Resources/Decoy-Engine-Data-Flow-Gaps.md` gap 2 (owner 2026-11-21).

Anchors: a path with no prefix is in this repository (decoy-engine). `C:` is the decoy CLI. Read at engine `origin/main` `035543388` and CLI `origin/main` `8d17419c`.

Rules consulted: dev-rules `README.md`, `00-universal.md`, `risk-and-exceptions.md`, `development-loop.md`, `bugfix.md`, `cross-cutting-concerns.md`, `verification.md`, `testing.md`, `release-and-rollback.md`, `proportionality.md`, `scope-discipline.md`, `documentation.md`, `profiles/local-operations.md` (close-out), `workspace-and-vcs.md`. Engine `CODEMAP.md` "Where Things Go", `scripts/dev/sentry_registry.toml`.

Risk: R1 (roadmap, vault and ledger text only). Plan review: one round, Codex. Code gate: none (no code).

## 1. Frame

### 1.1 Finding: the row is already built

Engine #744 (`9c301f518`, merged 2026-11-21 03:48, `fix(execution): refuse a mask handler that changes the row count`) built the row as the gap note asked. It is on main but not released: the reason is still `since=UNRELEASED` (`src/decoy_engine/reasons/runtime/_part2.py:145-149`), and v0.28.2 does not contain it. Evidence at `035543388`:

- One guard: `require_same_rows` (`src/decoy_engine/execution/_gated_string_guard.py:108-126`) raises `handler_row_count_changed` when the returned index differs from the input index in length, labels or order. The message names the table, column, strategy and two counts, never a value.
- Plain path: `src/decoy_engine/execution/_when_gate.py:456-460`. Gated path, before the index-aligned write-back: `:486-488`. Composite path: `src/decoy_engine/execution/_pandas_adapter.py:386-393`. Scalar dispatch goes through `run_with_when_gate` (`_pandas_adapter.py:417-424`), so full-frame and sequential both pass the guard.
- Chunked pandas oracle: each chunk runs the same adapter, and the guard runs before `_chunked_carry.py:97-105` reattaches carried columns.
- Sentry: `tests/sentry/test_handler_row_guard_call_sites.py` with the two-entry baseline `tests/sentry/baselines/handler-row-guard-exempt.json` (orphan REMAP scratch frame, nested child scratch frame), registered in `scripts/dev/sentry_registry.toml:88-89`.
- Tests: `tests/unit/execution/test_handler_row_count.py` covers plain (`:123`), gated (`:130`), chunked (`:135`) and composite (`:212`), each with short, long and relabelled output, plus pass cases (`:142`, `:151`, `:206`).
- Changelog fragment: `changelog.d/handler-row-count.md`. Contract line: `docs/compatibility-contract.md` (one line, in #744).
- Not done: no gate-ledger row for #744 in the vault, and the roadmap row and gap note still say open.

### 1.2 The guarantee of this close-out

- G1. The roadmap row says MERGED (not yet released) and names engine #744, `9c301f518`, 2026-11-21. It moves to DONE when the next engine release stamps `handler_row_count_changed`.
- G2. Gap 2 in the vault note is marked closed by #744.
- G3. No engine code changes.

Non-goals: the uncoded `ArrowInvalid` on the native chunked lane at `src/decoy_engine/execution/native/_chunk_masking.py:291-293` (the gap note classes it NOT A GAP; V2-LOG); a rows-in against rows-out check per table in the run record (quarantine drops rows on purpose; V2-LOG).

## 2. Established solutions

N/A for new design: nothing is built. The shipped guard is a postcondition check at the adapter boundary, the standard design-by-contract shape.

## 3. Behaviour

| Path | Before #744 | Now (main) |
|---|---|---|
| plain handler drops a row | output has fewer rows, success | `handler_row_count_changed` |
| `when:` handler drops a row | null written for the row, success | `handler_row_count_changed` before the write-back |
| chunked oracle, carry off | concat silent | `handler_row_count_changed` |
| chunked oracle, carry on | uncoded `ArrowInvalid` | `handler_row_count_changed` |
| composite handler changes rows | silent | `handler_row_count_changed` |
| native chunked lane | uncoded `ArrowInvalid` | unchanged (V2-LOG) |
| OOC and SEQ native | coded checks | unchanged |
| any shipped handler | correct rows | unchanged output (no built-in handler changes rows) |

## 4. Failure modes

| Case | Behaviour |
|---|---|
| Handler keeps the count but reorders labels | refused ("changed their index labels or order") |
| Quarantine drops rows | outside the handler, not affected |
| Orphan REMAP or nested scratch frames | exempt by baseline, with a reason each |

## 5. Choke point and sentries

No new rule in this close-out. The shipped choke point is `require_same_rows` at the two adapter sites, and the call-site sentry fails when a handler call skips it. Its baseline may only shrink (`scripts/dev/ratchet_check.py`).

### 5.1 Class table

| # | Class | Where it applies | Structure that closes it | Proof | Mutation that must turn it red |
|---|---|---|---|---|---|
| 1 | Value-bearing output | the shipped message | N/A for this close-out: text only; the shipped message holds names and counts, never values | n/a | n/a |
| 2 | Cleanup on exit path | none | N/A: no code changes | n/a | n/a |
| 3 | State and concurrency | none | N/A: no code changes | n/a | n/a |
| 4 | Route parity | none | N/A: no code changes; the shipped tests cover plain, gated, chunked and composite | n/a | n/a |
| 5 | Referential integrity | none | N/A: no code changes; a dropped key row now fails instead of dangling | n/a | n/a |
| 6 | Untrusted producer | none | N/A: no new input | n/a | n/a |
| 7 | Check then use (TOCTOU) | none | N/A: no file read is added | n/a | n/a |
| 8 | Weak tests | the claim "shipped" | each claim above cites a test or a line at `035543388`; the verify probe in section 6 runs the shipped tests on a VM | AT-1, AT-2 | n/a |
| 9 | Refactor drift | none | N/A: no code changes | n/a | n/a |
| 10 | Frozen contract drift | new reason code | N/A for this close-out: the release stamps `since` (G1) | n/a | n/a |

### 5.2 Enumerations

#### Exit paths

- Guard raises `ExecutionError` before the write-back (`src/decoy_engine/execution/_when_gate.py:488`).
- Guard passes and returns (`src/decoy_engine/execution/_gated_string_guard.py:115-116`).

#### Routes

- Full-frame, sequential and the chunked oracle: guarded through `_pandas_adapter._dispatch_mask_node` (`src/decoy_engine/execution/_pandas_adapter.py:386-424`).
- Native chunked, OOC and SEQ native: their own checks; the native chunked lane stays uncoded (V2-LOG).

#### FK shapes

- N/A for the guard's logic: it compares row indexes, not keys.
- FK resolve nodes (`_pandas_adapter.py:371-383`) are not handlers and are outside the row's scope.

#### Fields

- Reason `runtime/handler_row_count_changed`, pending until the release.
- No result or record field changes.

#### Output surfaces

- N/A: no output change for shipped handlers.
- The error message on refusal (names and counts only).

## 6a. Reuse inventory

| Need | Reused | Changed |
|---|---|---|
| Proof the row shipped | #744 tests and sentry | none |
| Row state | CLI roadmap row format | the state cell |

## 6. Acceptance tests, red first

No new tests: no code changes. Verification:

- AT-1: `git -C decoy-engine merge-base --is-ancestor 9c301f518 origin/main` exits 0.
- AT-2: one probe on a VM, never on the devbox: `~/bin/vm-run engine <wt> '$PY -m pytest tests/unit/execution/test_handler_row_count.py tests/sentry/test_handler_row_guard_call_sites.py -q'`. Expect all pass. The mutation the row asked for (remove the guard) is the sentry's job: deleting the call at `_when_gate.py:488` turns `test_when_gated_path` red, and the reviewer of #744 recorded no ledger row, so D1 records this probe as that evidence.
- AT-3: after D1, the CLI row shows MERGED with `#744`.

## 7. Placement

| File | Directory | CODEMAP line |
|---|---|---|
| this plan | `docs/plans/` | "Plans, decisions, records" |
| roadmap row | CLI `docs/roadmap/groups/run.md` | CLI roadmap (the single roadmap) |
| gap note | vault `30_Resources/` | not in the engine map |

## 8. Frozen contracts touched

None by this close-out. Full-suite trigger: no (no code, no test, no lock change).

## 9. Slices

| Slice | Repo | Content | Size | Risk | Gate |
|---|---|---|---|---|---|
| D1 | CLI and vault | row 28 state: "MERGED (engine #744, `9c301f51`, 2026-11-21); DONE at the next engine release". Gap 2 marked closed. Gate-ledger row for #744 with the AT-2 probe result. Two V2-LOG lines (section 1.2 non-goals) | about 6 lines | R1 | diff check by the orchestrator |

## 10. Stop lines for builders

- Do not change any engine file in D1.
- Do not mark the row DONE before a release stamps the reason.

## 11. Owner questions (recommended option first)

None. Both follow-ups are V2-LOG under the V1 bar (no reachable path today).

## 12. Pre-mortem

- A builder rebuilds the guard from the NOT STARTED row: D1 fixes the row today.
- The next release is cut without the reason stamp: the release script stamps every `UNRELEASED` reason, so the CLI re-pin carries it.

## 13. Sources

- Engine #744, `9c301f518`; `changelog.d/handler-row-count.md`.
- Vault `30_Resources/Decoy-Engine-Data-Flow-Gaps.md` gap 2.
