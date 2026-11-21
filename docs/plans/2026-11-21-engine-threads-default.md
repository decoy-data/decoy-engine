Status: plan

# ENGINE-THREADS-DEFAULT: close-out (the code shipped in engine #729)

Owner: Cam. Author: Opus plan agent. Date: 2026-11-21. Roadmap row: ENGINE-THREADS-DEFAULT (CLI `docs/roadmap/groups/run.md:26`, state NOT STARTED at CLI `8d17419c`). Source record: `docs/records/2026-11-19-engine-speed-and-route-completeness.md` (engine #715), section 5.2 F3 and section 2.4.

Anchors: a path with no prefix is in this repository (decoy-engine). `C:` is the decoy CLI. Read at engine `origin/main` `035543388` and CLI `origin/main` `8d17419c`.

Rules consulted: dev-rules `README.md`, `00-universal.md`, `risk-and-exceptions.md`, `development-loop.md`, `verification.md`, `api-and-compatibility.md`, `testing.md`, `proportionality.md`, `scope-discipline.md`, `documentation.md`, `profiles/local-operations.md` (close-out), `workspace-and-vcs.md`. Engine `CODEMAP.md` "Where Things Go", `docs/compatibility-contract.md`.

Risk: R1 (roadmap and ledger text only; no engine code). Plan review: one round, Codex. Code gate: none (no code).

## 1. Frame

### 1.1 Finding: the row is already built

The row is marked NOT STARTED, but engine #729 (`667a5e082`, merged 2026-11-20, `feat(execution): default run_pipeline native_threads to the usable cores`) built it, and it shipped in v0.28.2 (`git tag --contains 667a5e082` gives `v0.28.2`). The CLI pins `decoy-engine==0.28.2` (`C:pyproject.toml:151`). Evidence at `035543388`:

- `run_pipeline(..., native_threads: int | None = None)` (`src/decoy_engine/execution/_pipeline.py:140`).
- `None` resolves through `native_threads_for_run` (`src/decoy_engine/execution/pipeline/_host.py:175-193`): usable cores from `detect_usable_cpus` (cgroup quota and affinity), capped at `MAX_NATIVE_THREADS`, `1` with source `auto_fallback` when the cgroup read fails. Called once at `src/decoy_engine/execution/_pipeline_context.py:266`.
- The run records `quality_metrics["execution"]["native_threads"] = {"count", "source"}` (`src/decoy_engine/execution/_pipeline_route_dispatch.py:97-100`).
- Memory-capped `run_pipeline_isolated` keeps 1 thread (`src/decoy_engine/execution/_isolated_run.py:222-225`). A governed job keeps 1 thread (`src/decoy_engine/execution/_governor.py:483`).
- Byte safety: `tests/unit/execution/native_threads/test_default.py:286` (`test_default_output_bytes_equal_single_thread_per_route`), plus the in-crate `thread_count_never_changes_output` tests.
- Contract: `docs/compatibility-contract.md:1160-1175` ("Pre-GA default change (ENGINE-THREADS-DEFAULT, 2026-11-20)"). Signature freeze: `tests/unit/execution/test_r3_public_signature_freeze.py:56`. Changelog: `CHANGELOG.md:144`.
- No plan file exists for #729 (`docs/plans/` has none), and the gate ledger (`10_Projects/decoy/gate-ledger.tsv` in the vault) has no #729 row.

### 1.2 The guarantee of this close-out

- G1. The roadmap row says DONE and names engine #729, `667a5e082`, 2026-11-20, and release 0.28.2.
- G2. No engine code changes. No output byte changes.

Non-goals: changing `run_mask_chunked`'s default (Q1); measuring the speed gain on library callers (the record's section 2.7 already has the numbers).

## 2. Established solutions

N/A for new design: nothing is built. The shipped probe follows uber-go/automaxprocs and the JVM container support, as its module docstring records (`src/decoy_engine/execution/pipeline/_host.py:3-12`).

## 3. Behaviour

| Caller | Before #729 | Now (0.28.2) |
|---|---|---|
| `run_pipeline` with no `native_threads` | 1 thread | usable cores, capped; source `auto` |
| `run_pipeline(native_threads=n)` | n | n, source `explicit` |
| cgroup file unreadable | 1 | 1, source `auto_fallback` |
| `run_pipeline_isolated` with a memory cap | 1 | 1 |
| `run_job_with_governor` | 1 | 1 |
| CLI `decoy run` | all usable cores (CLI-side) | unchanged |

## 4. Failure modes

| Case | Behaviour |
|---|---|
| Invalid explicit value | still refused with `invalid_native_threads` (`test_default.py:111`) |
| Other CPU detection errors | raised, not swallowed (`test_default.py:94`) |
| Host with more than 4 cores | the Rust knee clamps to 4 (`auto_chunk["native_thread_clamp"]`) |

## 5. Choke point and sentries

No new rule. The shipped choke point is `native_threads_for_run`, called once in `build_run_context`.

### 5.1 Class table

| # | Class | Where it applies | Structure that closes it | Proof | Mutation that must turn it red |
|---|---|---|---|---|---|
| 1 | Value-bearing output | none | N/A: this close-out writes roadmap text only; the shipped record fields are a count and a closed set of three words | n/a | n/a |
| 2 | Cleanup on exit path | none | N/A: no code changes | n/a | n/a |
| 3 | State and concurrency | none | N/A: no code changes; the shipped cache is `functools.cache` on a per-process read | n/a | n/a |
| 4 | Route parity | none | N/A: no code changes; shipped parity is `test_default.py:286` per route | n/a | n/a |
| 5 | Referential integrity | none | N/A: thread count does not touch keys | n/a | n/a |
| 6 | Untrusted producer | none | N/A: no new input | n/a | n/a |
| 7 | Check then use (TOCTOU) | none | N/A: no file read is added | n/a | n/a |
| 8 | Weak tests | the claim "shipped" | each claim above cites a test or a line at `035543388` | section 1.1 | n/a |
| 9 | Refactor drift | none | N/A: no code changes | n/a | n/a |
| 10 | Frozen contract drift | the public default (a freeze item) | already recorded in `docs/compatibility-contract.md:1160-1175` before 1.0 | signature freeze test `:56` | n/a |

### 5.2 Enumerations

#### Exit paths

- N/A: no code changes; the shipped exit paths are listed in `src/decoy_engine/execution/pipeline/_host.py:175-193`.
- The `auto_fallback` path returns 1 instead of raising.

#### Routes

- Every route reads `ctx.native_threads` from one resolution (`src/decoy_engine/execution/_pipeline_context.py:266`).
- Isolated and governed runs set 1 before that resolution (`src/decoy_engine/execution/_isolated_run.py:225`, `src/decoy_engine/execution/_governor.py:483`).

#### FK shapes

- N/A: the thread count is independent of FK shape.
- OOC and SEQ receive the same count as the lane.

#### Fields

- `quality_metrics["execution"]["native_threads"]["count"]` and `["source"]` (shipped).
- No new field in this close-out.

#### Output surfaces

- N/A for this close-out: roadmap text only.
- Shipped: the `execution` block of `quality_metrics` gained one mapping (contract `:1160`).

## 6a. Reuse inventory

| Need | Reused | Changed |
|---|---|---|
| Proof the row shipped | #729 tests and contract note | none |
| Row state | CLI roadmap row format | the state cell |

## 6. Acceptance tests, red first

No new tests: no code changes. Verification is a read of `origin/main`:

- AT-1: `git -C decoy-engine merge-base --is-ancestor 667a5e082 origin/main` exits 0. Fails if #729 were reverted.
- AT-2: `git show origin/main:src/decoy_engine/execution/_pipeline.py` line 140 reads `native_threads: int | None = None`.
- AT-3: after D1, `git -C decoy grep -n ENGINE-THREADS-DEFAULT origin/main -- docs/roadmap/groups/run.md` shows DONE with `#729`.

## 7. Placement

| File | Directory | CODEMAP line |
|---|---|---|
| this plan | `docs/plans/` | "Plans, decisions, records" |
| roadmap row | CLI `docs/roadmap/groups/run.md` | CLI roadmap (the single roadmap) |

## 8. Frozen contracts touched

None by this close-out. The default change is already in the contract (`:1160-1175`). Full-suite trigger: no (no code, no test, no lock change).

## 9. Slices

| Slice | Repo | Content | Size | Risk | Gate |
|---|---|---|---|---|---|
| D1 | CLI | row 26 state: "DONE. Engine #729 (`667a5e08`, 2026-11-20), released in 0.28.2." Shipped-log line. Gate-ledger row for #729 in the vault | about 3 lines | R1 | diff check by the orchestrator |

## 10. Stop lines for builders

- Do not change any engine file in D1.
- Do not change `run_mask_chunked`'s default without Q1 answered yes.

## 11. Owner questions (recommended option first)

1. Q1. `run_mask_chunked` (a public entry) still defaults `native_threads=1` (`docs/compatibility-contract.md:843`). Changing it is a freeze item too. Recommended: leave it at 1 for V1. The platform passes its own grant, and the CLI does not call it. Record a V2-LOG line.

## 12. Pre-mortem

- A reader trusts the NOT STARTED state and a builder rebuilds the default: D1 fixes the row today.
- Q1 surfaces after 1.0 as a complaint: then it is a 2.0 change. The recommended answer accepts that.

## 13. Sources

- Engine #729, `667a5e082`; `changelog.d/engine-threads-default.md` (folded into `CHANGELOG.md:144`).
- Record section 5.2 F3.
