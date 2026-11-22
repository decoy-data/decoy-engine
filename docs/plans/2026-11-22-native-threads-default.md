Status: plan (revision 1, 2026-11-22)

# NATIVE-THREADS-DEFAULT: native kernels use the usable cores by default, and the positional draw moves to an AES PRF

Owner: Cam. Author: Opus (plan author). Date: 2026-11-22. Roadmap row: NATIVE-THREADS-DEFAULT (group mask engine, 1.0), from the V1 fast-path audit (vault `10_Projects/decoy/v1-fast-path-audit-2026-11-22.md`) and the owner direction of 2026-11-22: V1 is fast and reproducible, the faster and more robust design wins even when output bytes change, output stays deterministic per seed, and every byte change is named here and on the changelog `Breaking:` line. Two slices, each one engine PR. It follows ENGINE-THREADS-DEFAULT (#729, plan `docs/plans/2026-11-21-engine-threads-default.md` on `origin/plan/engine-threads-default`), which made `run_pipeline` request the usable cores but left the kernel knee at 4 and the chunked entry at 1.

Anchors: paths are in this repository (decoy-engine) unless they start with `CLI:`. Read at engine `origin/main` `70881ad79` (0.28.3). Line numbers are at that head.

Rules consulted: dev-rules `README.md`, `00-universal.md`, `development-loop.md` (PLAN), `profiles/local-operations.md`, `risk-and-exceptions.md`, `feature-dev.md`, `performance.md`, `security.md`, `api-and-compatibility.md`, `cross-cutting-concerns.md`, `observability-and-resilience.md` (concurrency), `reuse-first.md`, `scope-discipline.md`, `proportionality.md`, `testing.md`, `architecture.md`, `documentation.md`, `workspace-and-vcs.md`, `catalogs/recurring-defects.md`; engine `CLAUDE.md` and `CODEMAP.md`.

Risk: S1 R2 (default concurrency of every native kernel; public default of `run_mask_chunked`). S2 R3-adjacent: it replaces a keyed primitive. It changes no key, no vault format and no source-keyed (deterministic) path, but the plan review must include the security lens. Plan review: Dennis, then Codex. Code gate: Codex and Dennis, with `/cso` on S2.

## 1. Frame

Evidence, measured on the Dell 26-core node (scratch probe `_fpaudit/probe_plan.py`, 3M rows, compiled index kernel, `mask_key` 32 bytes, pool 10,000):

| `native_threads` | knee 4 (default), ns/row | knee 26 (env), ns/row |
|---|---|---|
| 1 | 586 | 583 |
| 2 | 296 | 300 |
| 4 | 150 | 154 |
| 8 | 147 | 135 |
| 13 | 150 | 94 |
| 26 | 218 | 64 |

- The knee caps every kernel at 4 threads (`decoy-engine-native/src/threads.rs:45` `DEFAULT_NATIVE_MASK_THREAD_KNEE = 4`, "measured on the 8-core class"). On 26 cores the kernel scales to 9.1x at 26 threads; the knee holds it at 3.9x. Asking for 26 under the knee is slower than asking for 4 (218 against 150), so the knee also clamps badly above itself.
- A plain `decoy run` mask with a pooled faker column reaches the kernel with `native_threads=26` (spy on `_CompiledIndexKernel.derive_index_batch`, 60 calls, all 26), so the `run_pipeline` default from #729 works on the native route. The clamp is the knee.
- Three Python paths drop the count before the kernel: `derive_validated_indices` (`src/decoy_engine/generation/pool/_sampler.py:119`) takes no `native_threads` and calls `derive_index_batch` without it (`:138`), and the wrapper's `None` resolves to 1 thread in Rust. Its callers are the faker positional oracle (`src/decoy_engine/execution/_strategies/_faker_positional.py:64`), the pool sampler (`_sampler.py:176`, `:189`) and `windowed_date` (`src/decoy_engine/transforms/windowed_date.py:286`).
- The chunked entries default to 1: `run_mask_chunked` (`src/decoy_engine/execution/native/_chunked_entry.py:614`), the inner entry (`:435`), `execution/_pipeline_route_exec.py:146`, `:233`, `:576`, `execution/_sequential.py:246`, `execution/native/chunked/_core.py:42`, `execution/physical/drivers/_chunked.py:116`, `:162`, `execution/out_of_core/_runner.py:125`.
- The per-row cost at 1 thread is one HMAC-SHA256 (clone, update, finalize) per row (`decoy-engine-native/src/derive.rs` `DeriveContext`, the HKDF key already hoisted per batch). For the positional draw the input is a fixed 16-byte (domain code, position) pair keyed by `job_seed`, so a block cipher PRF does the same job. Python `cryptography` AES-256-ECB over 10M blocks costs 19 ns/row plus 8 ns for the modulo, against 2,000 ns per row for Python `hmac.digest` and about 580 ns for the Rust HMAC.

## 2. Established solutions

- **Thread count from the host.** Rust `std::thread::available_parallelism` reads sched affinity and the cgroup v2 CPU quota on Linux; Python `os.sched_getaffinity` plus the cgroup `cpu.max` read in `detect_usable_cpus` (`src/decoy_engine/execution/pipeline/_host.py:153`) do the same on the Python side. Polars, DuckDB and Arrow all default to the usable cores with an env override (`POLARS_MAX_THREADS`, DuckDB `threads`, `OMP_NUM_THREADS` for Arrow's CPU pool). This plan follows that: default to usable cores, keep the env override, no fixed knee.
- **Rayon pool.** The kernels already split with rayon over one shared pool; thread count never changes output (lowest-row error arbitration, in-crate test `derive_index_thread_count_never_changes_output`, `decoy-engine-native/src/batch/tests.rs:317`). No new scheduler.
- **Block-cipher PRF for counter inputs.** AES used as a PRF on a counter is the construction of AES-CTR (NIST SP 800-38A) and of the CTR_DRBG (NIST SP 800-90A): the output block for input `i` is `AES_K(i)`. The PRP/PRF switching lemma (Bellare and Rogaway; Bellare, Desai, Jokipii, Rogaway 1997) bounds the distinguishing gap at `q^2 / 2^129` for `q` queries. Key derivation stays HKDF-SHA256 (RFC 5869), as today. The Rust `aes` 0.9.3 crate (RustCrypto, already a dependency for FF1 in `decoy-engine-native/src/fpe.rs:27`, AES-NI detected at run time) and Python `cryptography` (hard dependency, OpenSSL AES) are the two implementations; no new dependency.
- Considered and not chosen: keyed BLAKE2b (RFC 7693, stdlib `hashlib`): 594 ns/row in Python per row, no vector form; BLAKE3 keyed mode: a new dependency; SipHash: a 64-bit-key PRF meant for hash tables, weaker margin than the 256-bit key here.

### Reuse inventory

- `native_threads_for_run` (`src/decoy_engine/execution/pipeline/_host.py:175`): the one resolver of the run's count (`explicit`, `auto`, `auto_fallback`), capped at `MAX_NATIVE_THREADS` 1024.
- `NativeThreadBudget::resolve` and `resolve_on_host` (`decoy-engine-native/src/threads.rs:144`, `:157`): the one Rust clamp.
- `derive_validated_indices` (`_sampler.py:119`): the one checked index draw for the Python callers.
- `positional_key_array` (`src/decoy_engine/execution/_positional_keys.py:53`): the one source of positional keys (uint64 full-table positions), used by the faker oracle, the native operator step (`execution/native/_operator_step.py:176`) and the native categorical step (`execution/native/_categorical_ext.py:180`).
- `hkdf_key` (`decoy-engine-native/src/derive.rs:82`) and the Python `_hkdf.py` twin: key derivation, reused with a new info label.
- The existing thread tests `tests/unit/execution/native_threads/test_default.py` and `test_capped.py`.

## 3. Guarantee and non-goals

After S1:

- With no explicit count, every native kernel call in a `run_pipeline` or `run_mask_chunked` run uses the run's resolved count: the usable cores from affinity and cgroup quota, capped at `MAX_NATIVE_THREADS`, and never more than Rust's `available_parallelism`. `DECOY_NATIVE_MASK_THREAD_KNEE` still lowers it when set.
- Explicit counts are honored as today. `run_pipeline_isolated` with a memory cap and `run_job_with_governor` keep forwarding 1 (named exceptions, `docs/compatibility-contract.md:1194`).
- Output bytes are identical at every thread count and under any affinity or quota (A1, A2, A3).

After S2:

- The positional draw (faker without `deterministic`, positional categorical) computes `index = u64_be(AES-256_K(code_u64 || position_u64)[0:8]) mod pool_size` with `K = HKDF-SHA256(salt, job_seed, info = "decoy/positional-prf/v1" || namespace)`. Same in Rust and in the Python reference.
- Security property kept: without `job_seed`, the index sequence of a column is indistinguishable from uniform indices except with advantage at most `q^2 / 2^129` plus the modulo bias `pool_size / 2^64` (both negligible: `q = 10^10` rows gives about `2^-63`). Different namespaces get independent keys. The draw is keyed: knowing the output of one run or one namespace gives nothing about another.
- Not claimed, unchanged from today: the strength is bounded by `job_seed`'s entropy (8 bytes); the source-keyed deterministic path (`mask_key`, variable-length source values) stays HMAC-SHA256.

Non-goals: changing the deterministic (source-keyed) HMAC path, FF1, the crypto hash kernel, vault formats, `SEED_PROTOCOL_VERSION` (see section 9 and owner question 2), thread use in generation (generation has no native kernel on its main path; GEN-STREAM-ALL covers its speed).

## 4. Enumerations

### Exit paths

1. Normal run: count recorded in `quality_metrics["execution"]["native_threads"]` as today; `auto_chunk["native_thread_clamp"]` now reports the Rust clamp (cores), not the knee 4.
2. Invalid explicit count: `invalid_native_threads` (`src/decoy_engine/execution/native/_chunked_entry.py:104` `_validate_native_threads`), unchanged.
3. Invalid knee env value: the existing Rust `DeriveError` at first kernel call (`decoy-engine-native/src/threads.rs:58`), unchanged.
4. S2: `pool_size` out of range (`check_pool_size`) and the index validation in `_sampler.py:100` to `:115` apply to the AES draw unchanged; an AES key length error cannot happen (HKDF output is fixed at 32 bytes).

### Routes (where a native thread count is consumed)

| Route | Entry | Count before | Count after S1 |
|---|---|---|---|
| plain run, native route | `run_pipeline` to `_operator_step` | run count, clamped to 4 | run count |
| plain run, Python oracle faker | `_faker_positional.py:64` to `derive_validated_indices` | 1 | run count |
| pool sampler (deterministic faker, generation pools) | `_sampler.py:176`, `:189` | 1 | run count |
| windowed_date offsets | `windowed_date.py:286` | 1 | run count |
| chunked public | `run_mask_chunked` (`_chunked_entry.py:614`) | 1 | `None` = run count |
| chunked internals | `_chunked_entry.py:435`, `_pipeline_route_exec.py:146`, `:233`, `:576`, `_sequential.py:246`, `native/chunked/_core.py:42`, `physical/drivers/_chunked.py:116`, `:162`, `out_of_core/_runner.py:125` | 1 | passed from the caller; default `None` |
| isolated with memory cap | `run_pipeline_isolated` | 1 | 1 (exception) |
| governed job | `run_job_with_governor` | 1 | 1 (exception) |

### FK shapes

N/A for S1: thread count never changes which rows join, and FK-preserving kernels are covered by the thread-invariance test like every other kernel. For S2: positional draws are not joinable by design (they key on position, not value), so no FK shape reads them; a column used as a join key must be `deterministic: true`, which stays HMAC.

### Fields

S1 changes no field. S2 changes the values of:

- faker columns without `deterministic: true` on the mask path (`src/decoy_engine/execution/_strategies/_faker.py:123`, native `execution/native/_operator_step.py:176`);
- categorical columns drawn by position (`execution/native/_categorical_ext.py:180` and its oracle twin).

No other strategy reads `positional_key_array` (walk in S2's guard).

### Output surfaces

- Masked bytes: S1 none. S2 the columns in Fields.
- `quality_metrics["execution"]["native_threads"]` and `auto_chunk["native_thread_clamp"]`: the clamp value changes from 4 to the host's usable cores.
- `lock/v1` probe digest: changes in S2 only if `run_probe` (`src/decoy_engine/support/_probe.py:128`) covers the positional draw; the builder checks and, if it does, regenerates the golden in the same PR.
- `run_mask_chunked` signature default: `1` to `None` (public; signature freeze test `tests/unit/execution/test_r3_public_signature_freeze.py:56`).

## 5. Slices and size

- **S1 THREADS.** Rust: `DEFAULT_NATIVE_MASK_THREAD_KNEE` removed; `resolve` clamps to `min(requested, host_available)` and to the env knee only when set; a minimum rows-per-thread (measured; start at 16,384) so a small batch does not fan out (`threads.rs`, 662 lines, net about -10; Rust files are not under the Python size sentry). Python: one context-local run budget (`contextvars.ContextVar`) set by the run entry from `native_threads_for_run` and read by `derive_validated_indices` and the native wrappers when no explicit count is passed; the `= 1` defaults listed in Routes become `None`. Files: `execution/pipeline/_host.py` (238, about +25), `generation/pool/_sampler.py` (543, about +6), `execution/native/_index_ext.py` (334, about +4), `execution/native/_chunked_entry.py` (689, census ceiling 689: the edits are default values only, net 0 lines, so the exact-match ceiling holds), the other default sites (one token each), contract and changelog. New module: none.
- **S2 POSITIONAL-PRF.** Rust: `derive.rs` gains `PositionalPrf` (AES-256 key from HKDF, `encrypt_blocks` over 8-block chunks, about 60 lines; file 679 to about 740) or a new `decoy-engine-native/src/positional.rs` (recommended, keeps `derive.rs` on the HMAC path only); `batch/index.rs` gains `derive_positional_index_array` (about 30). Python: the reference in `execution/_positional_keys.py` (about +40, using `cryptography` ECB over the packed uint64 pairs), `_faker_positional.py` and the two native call sites switch to it. A known-answer test file with fixed vectors shared by Rust and Python. New module in `execution/`: none (the Python reference goes into the existing `_positional_keys.py`).

## 6. Placement

| New file | Directory | CODEMAP row | Sits beside |
|---|---|---|---|
| `positional.rs` (S2) | `decoy-engine-native/src/` | native companion crate | `derive.rs`, `fpe.rs` |
| `test_thread_invariance.py` (S1) | `tests/unit/execution/native_threads/` | engine native tests | `test_default.py`, `test_capped.py` |
| `test_kernel_thread_sites.py` (S1 guard) | `tests/sentry/` engine sentry folder for execution choke points (builder takes the folder CODEMAP names for kernel-call sentries) | sentries | existing native choke-point sentries |
| `positional_prf_kat.json` and `test_positional_prf.py` (S2) | `tests/native/` | native parity tests | `test_determinism_goldens.py` |

`execution/` is at its frozen 103 and `execution/native/` at 55: no module is added to either.

## 7. Class table

| # | Class | Where it applies | Structure that closes it | Proof | Mutation that must turn it red |
|---|---|---|---|---|---|
| 1 | Value-bearing output | thread and clamp metrics; PRF errors | metrics hold counts; PRF errors name codes, never a key or position | existing metric tests, A7 | log the derived key in an error (A7 red) |
| 2 | Cleanup missing on an exit path | the run budget context variable | set and reset in one `with` at the run entry, so a failed run does not leak its count to the next call in the process | A4 | set without reset (A4 red: next call sees the old count) |
| 3 | State and concurrency | rayon pool and parallel row ranges | output by row index, lowest-row error wins; two concurrent runs with different counts in threads keep their own budget (context-local) | A1, A4 | write results by completion order (A1 red) |
| 4 | Route parity and silent fallback | native vs Python reference; oracle path dropping the count | one budget read inside `derive_validated_indices`; guard A5 walks every kernel call | A5, A6 | drop the budget read in `_sampler.py` (A5 red) |
| 5 | Referential integrity | none | N/A: thread count does not reorder rows, and positional draws are not join keys (deterministic columns stay HMAC) | A1 | n/a |
| 6 | Untrusted producer | `DECOY_NATIVE_MASK_THREAD_KNEE` env | existing strict parse; 0, negative and junk refused | existing Rust tests | accept 0 (red) |
| 7 | Check then use | cgroup quota read once per run | resolved once at run start and passed down; no kernel re-reads the host mid-run except Rust's own `available_parallelism` cap | A3 | re-read per batch (A3 count flips under a changing fake quota: red) |
| 8 | Weak tests | invariance checked at 1 vs 2 only | counts {1, 2, 4, 8, 13, 26, auto} and row counts that are not multiples of the chunk (1, 16,383, 16,385, 3,000,001) | A1 | split rows by thread count in the output (A1 red at 13) |
| 9 | Refactor drift | the deterministic HMAC path | S2 touches only positional sites; the deterministic goldens stay byte-identical | A8 | route a deterministic column through the PRF (A8 red) |
| 10 | Frozen contract drift | `run_mask_chunked` default; positional bytes | contract entries and `Breaking:` lines; signature freeze test updated with the entry | A9, A6 | change the default without the contract entry (freeze test red) |

## 8. Acceptance tests (each fails before its slice, except A1 and A8, controls that pass before and after)

S1:

- **A1 thread invariance.** For each kernel (index, crypto hash, FF1, raw hex) and for a full `run_pipeline` mask of a 6-column table (faker pooled, faker deterministic, categorical, hash, fpe, date shift), output digests at counts {1, 2, 4, 8, 13, 26, None} and rows {1, 16,383, 16,385, 3,000,001} are all equal. Run on the Dell node through `vm-run` for the 26 case; the unit suite runs {1, 2, 4, None} at small rows.
- **A2 chunked default.** `run_mask_chunked` with no `native_threads` records source `auto` and the usable-core count; its output equals the explicit-1 output. Fail-before: records `explicit` 1.
- **A3 affinity and quota.** With `os.sched_setaffinity` to two CPUs in a child process, and with a fake cgroup root whose `cpu.max` is `200000 100000` (the `fs_root` parameter of `detect_usable_cpus`), the run records 2 and the kernel receives 2. Fail-before for the kernel half: the oracle path receives 1 whatever the host says (spy, as in the probe).
- **A4 budget scope.** Two threads in one process run `run_pipeline` with explicit 3 and 5; each kernel call sees its own run's count; after a failed run the next library call without a run sees the Rust default. Fail-before: no budget exists, so the oracle path sees 1 in both.
- **A5 guard.** A syntax walk of `src/decoy_engine/` lists every call of a compiled-kernel method (each public method of the wrappers in `execution/native/_*_ext.py`, `derive_index_batch` among them, found by resolving the wrapper classes, not by name list); each passes `native_threads=` from the run budget or is in a ratchet allowlist with a reason. Seeded bypass (a call without the argument in a scratch copy) turns it red; removing a real site lowers the count.
- **A6 speed (performance gate, vm-run on the Dell node).** Mask 10M rows Parquet to Parquet with one pooled faker column: at least 1.8x faster than knee 4 at `70881ad79` (audit 8.67 s). Index kernel at 26 threads at most 80 ns/row (probe 64). On the Mac node (10 cores), no count is slower than the knee-4 result (guards the small-host case the knee was set for).

S2:

- **A7 known answers.** Fixed vectors (job seed, namespace, code, positions 0, 1, 2^32, 2^64-1, pool sizes 1, 7, 10,000, 2^31) give the same indices in Rust, in the Python reference and in a third computation inside the test from `cryptography` primitives directly. Fail-before: the functions do not exist.
- **A8 deterministic unchanged.** The deterministic faker, hash and FF1 goldens (`tests/native/test_determinism_goldens.py` deterministic cases) are byte-identical before and after.
- **A9 positional parity and keyed-ness.** For a positional faker column and a positional categorical column: native and oracle routes give identical bytes; output is identical across thread counts and chunk offsets (chunk at offset 0 and 4,096 of a 10,000-row table equals the whole); changing `job_seed` changes at least 99% of indices; changing the namespace does the same; a uniformity check (chi-square over 10^6 draws into 100 buckets) passes at p > 0.001. Fail-before: the positional path is HMAC, so the A7 vectors do not match.
- **A10 speed.** Positional index draw at 1 thread at most 40 ns/row in Rust (HMAC about 580), and the Python reference at most 60 ns/row (Python per-row HMAC about 2,000).

## 9. Frozen contracts and compatibility

S1:

- `run_mask_chunked(..., native_threads: int | None = None)`: default `1` to `None` (usable cores). Contract entry beside `docs/compatibility-contract.md:866` and the ENGINE-THREADS-DEFAULT entry at `:1186`; that entry's sentence "the native kernels apply at most their own knee (4 threads)" is replaced by the new clamp rule. Signature freeze test updated in the same PR with a `Breaking:` changelog line (the public default changed).
- `auto_chunk["native_thread_clamp"]` values change (cores in place of 4). Shape unchanged.
- Output bytes: none.
- CLI: none required (the CLI already passes no count). The platform passes its own grant; its re-pin checklist note at `docs/compatibility-contract.md:1201` stands.

S2 (byte change, `Breaking:` line): masked values of positional faker and positional categorical columns change for every seed. Deterministic columns, vaults, tokens and FF1 output do not change. Positional draws are not reversible and no vault stores their indices (the builder confirms with a walk of vault writers before merge). Recommended versioning: the HKDF info label `decoy/positional-prf/v1` versions this draw on its own, and `SEED_PROTOCOL_VERSION` is not bumped, because a bump re-keys synthetic generation and every vault too (`docs/compatibility-contract.md:600` to `:610`). Owner question 2.

## 10. Pre-mortem

- A user on a shared 64-core host gets a run that takes every core. Same as Polars and DuckDB defaults; an explicit `native_threads` and the knee env lower it, and cgroup quotas are honored. The CLI help names the env.
- Small batches pay thread spawn cost. The rows-per-thread floor limits fan-out; A6 on the Mac checks the small-host case.
- A process embeds the engine and calls kernels outside a run (library users). With no run budget, the Rust default is the host clamp, not 1: a change for direct kernel callers, named in the changelog.
- AES-NI absent (old or emulated CPU): the `aes` crate falls back to a constant-time bitsliced software AES, still well under the HMAC cost; A10 records the host.
- Someone later uses a positional faker column as a join key across runs. It never was joinable across seeds; within one seed it stays stable by position. The deterministic mode remains the join-safe choice, as the docs already say.
- The knee env was set in some operator's environment to 4. It keeps working; the run record shows the clamp.

## 11. Open questions for the owner

1. Thread cap: no fixed cap beyond the usable cores and `MAX_NATIVE_THREADS` (recommended, matches Polars and DuckDB), or a fixed default cap such as 32 with the env to raise it?
2. Versioning the S2 byte change: a per-draw label (`decoy/positional-prf/v1` in the HKDF info, recommended, positional bytes change and nothing else re-keys) or a `SEED_PROTOCOL_VERSION` bump (re-keys generation and vaults as well)?
3. The source-keyed deterministic path (HMAC-SHA256, variable-length values) stays as is in V1 (recommended). A later row could move it to AES-CMAC (NIST SP 800-38B), which would change every deterministic value and every vault lookup, so it is not proposed here.
