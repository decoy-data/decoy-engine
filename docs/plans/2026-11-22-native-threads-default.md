Status: plan (revision 2, 2026-11-22; Dennis round 1 applied)

# NATIVE-THREADS-DEFAULT: native kernels use the usable cores by default; per-row keyed draws move to AES primitives

Owner: Cam. Author: Opus (plan author). Date: 2026-11-22. Roadmap row: NATIVE-THREADS-DEFAULT (group mask engine, 1.0), from the V1 fast-path audit (vault `10_Projects/decoy/v1-fast-path-audit-2026-11-22.md`) and the owner direction of 2026-11-22: V1 is fast and reproducible, the faster and more robust design wins even when output bytes change, output stays deterministic per seed, and every byte change is named here and on the changelog `Breaking:` line. Three slices, each one engine PR. It follows ENGINE-THREADS-DEFAULT (#729, plan `docs/plans/2026-11-21-engine-threads-default.md` on `origin/plan/engine-threads-default`), which made `run_pipeline` request the usable cores but left the kernel knee at 4 and the chunked entry at 1.

Anchors: paths are in this repository (decoy-engine) unless they start with `CLI:`. Read at engine `origin/main` `70881ad79` (0.28.3). Line numbers are at that head.

Rules consulted: dev-rules `README.md`, `00-universal.md`, `development-loop.md` (PLAN, design notes, choke point), `profiles/local-operations.md`, `risk-and-exceptions.md`, `feature-dev.md`, `performance.md`, `security.md`, `config-secrets-and-supply-chain.md` (S3 adds a crate), `api-and-compatibility.md`, `cross-cutting-concerns.md`, `observability-and-resilience.md`, `reuse-first.md`, `scope-discipline.md`, `proportionality.md`, `testing.md`, `architecture.md`, `documentation.md`, `workspace-and-vcs.md`, `catalogs/recurring-defects.md`; engine `CLAUDE.md` and `CODEMAP.md`.

Risk: S1 R2 (default concurrency of every native kernel; a public default). S2 R3 (replaces the keyed primitive of the positional draw). S3 R3 (replaces the keyed primitive of every source-keyed per-row draw). Plan review: Dennis, then Codex. Code gate: Codex and Dennis; `/cso` on S2 and S3.

## 1. Frame

Evidence, measured on the Dell 26-core node (Xeon, AES-NI, no SHA-NI; scratch probe `_fpaudit/probe_plan.py`, 3M rows, compiled index kernel, 32-byte `mask_key`, pool 10,000):

| `native_threads` | knee 4 (default), ns/row | knee 26 (env), ns/row |
|---|---|---|
| 1 | 586 | 583 |
| 2 | 296 | 300 |
| 4 | 150 | 154 |
| 8 | 147 | 135 |
| 13 | 150 | 94 |
| 26 | 218 | 64 |

- The knee caps every kernel at 4 threads (`decoy-engine-native/src/threads.rs:45` `DEFAULT_NATIVE_MASK_THREAD_KNEE = 4`). On 26 cores the kernel reaches 9.1x at 26 threads; the knee holds it at 3.9x, and asking for 26 under the knee is slower than 4 (218 against 150).
- A plain `decoy run` mask with a pooled faker column reaches the kernel with `native_threads=26` (spy, 60 calls), so #729's `run_pipeline` default works on the native route; the knee is the clamp.
- Python paths that drop the count: `derive_validated_indices` (`src/decoy_engine/generation/pool/_sampler.py:119`) calls `derive_index_batch` without it (`:138`), and `None` resolves to 1 thread in Rust. Its callers: faker positional oracle (`src/decoy_engine/execution/_strategies/_faker_positional.py:64`), pool sampler (`_sampler.py:176`, `:189`), `windowed_date` (`src/decoy_engine/transforms/windowed_date.py:286`). The Python FF1 path sizes its worker pool from `os.cpu_count()` (`src/decoy_engine/execution/_strategies/_fpe.py:353`), which ignores cgroup quota and affinity.
- Chunked defaults of 1: `run_mask_chunked` (`src/decoy_engine/execution/native/_chunked_entry.py:614`), `:435`, `src/decoy_engine/execution/_pipeline_route_exec.py:146`, `:233`, `:576`, `src/decoy_engine/execution/_sequential.py:246`, `src/decoy_engine/execution/native/chunked/_core.py:42`, `src/decoy_engine/execution/physical/drivers/_chunked.py:116`, `:162`, `src/decoy_engine/execution/out_of_core/_runner.py:125`.
- Per-row cost at 1 thread is one HMAC-SHA256 (clone, update, finalize; `decoy-engine-native/src/derive.rs` `DeriveContext`, HKDF key hoisted per batch). Python `cryptography` AES-256-ECB over 10M blocks costs 19 ns/row plus 8 ns for the modulo; Python `hmac.digest` costs about 2,000 ns per row and the Rust HMAC about 580.

## 2. Established solutions

- **Thread count from the host.** Rust `std::thread::available_parallelism` reads affinity and the cgroup v2 CPU quota on Linux; `detect_usable_cpus` (`src/decoy_engine/execution/pipeline/_host.py:153`) does the same in Python. Polars (`POLARS_MAX_THREADS`), DuckDB (`threads`) and Arrow (`OMP_NUM_THREADS`) default to the usable cores with an override. This plan does the same: no fixed knee.
- **Context propagation to worker threads.** Python `contextvars.copy_context()` per task (PEP 567). The engine already has it: `run_in_context` and `map_in_context` (`src/decoy_engine/fileaccess/_entry.py:277-295`), used by the FF1 pool (`_fpe.py:357-359`).
- **Block-cipher PRF on a counter (S2).** AES used as a PRF on a counter is AES-CTR (NIST SP 800-38A) and CTR_DRBG (SP 800-90A). The PRP/PRF switching lemma bounds the gap at `q^2 / 2^129`.
- **Variable-length MAC from a block cipher (S3).** AES-CMAC (NIST SP 800-38B, RFC 4493) is a PRF on variable-length input with a bound of about `sigma^2 / 2^128` (`sigma` total blocks). It replaces HMAC-SHA256 where the input is the length-prefixed frame.
- **Key separation.** HKDF-SHA256 (RFC 5869) with a distinct salt per primitive, and `info` that length-prefixes the namespace (NIST SP 800-108 fixed-input encoding), so no namespace string can make two primitives share a key.
- Implementations: Rust `aes` 0.9.3 (already a dependency, `decoy-engine-native/Cargo.toml:42`; AES-NI on x86_64 and ARMv8 crypto on aarch64, detected at run time; `--cfg aes_force_soft` forces the constant-time software path); RustCrypto `cmac` (S3, new crate); Python `cryptography` (hard dependency; ECB and `cmac`).
- Not chosen: keyed BLAKE2b (594 ns/row in Python, no vector form); BLAKE3 (new dependency); SipHash (64-bit-key hash-table PRF).

### Reuse inventory

- `native_threads_for_run` (`src/decoy_engine/execution/pipeline/_host.py:175`): the one resolver of the run's count.
- `NativeThreadBudget::resolve`, `resolve_on_host` (`decoy-engine-native/src/threads.rs:144`, `:157`): the one Rust clamp.
- `derive_validated_indices` (`_sampler.py:119`): the one checked index draw in Python.
- `map_in_context`, `run_in_context` (`src/decoy_engine/fileaccess/_entry.py:277-295`).
- `positional_key_array` (`src/decoy_engine/execution/_positional_keys.py:53`): uint64 full-table positions for the faker oracle, native operator step (`src/decoy_engine/execution/native/_operator_step.py:176`) and native categorical (`src/decoy_engine/execution/native/_categorical_ext.py:180`).
- `src/decoy_engine/determinism/_hkdf.py` and `_derive.py`: Python key derivation and HMAC frame; Rust twin `hkdf_key` (`decoy-engine-native/src/derive.rs:82`, salt `decoy-engine/determinism/v1` at `:31`).
- Secret-material census: `scripts/secret_material_census.py`, `tests/sentry/secret_material_census.json`, `tests/sentry/test_secret_material_census.py`.
- Thread tests `tests/unit/execution/native_threads/test_default.py`, `test_capped.py`; Rust `derive_index_thread_count_never_changes_output` (`decoy-engine-native/src/batch/tests.rs:317`).

## 3. Guarantee and non-goals

After S1:

- With no explicit count, every native kernel call in a `run_pipeline` or `run_mask_chunked` run, and every Python worker pool in the run (FF1), uses the run's resolved count: usable cores from affinity and cgroup quota, capped at `MAX_NATIVE_THREADS`, and never above Rust's `available_parallelism`. `DECOY_NATIVE_MASK_THREAD_KNEE` still lowers it when set.
- The count reaches executor workers: tasks are submitted through `map_in_context`/`run_in_context`, and a guard rejects a bare `executor.submit`/`map` in `src/decoy_engine/`.
- Explicit counts are honored. `run_pipeline_isolated` with a memory cap and `run_job_with_governor` keep 1 (named exceptions, `docs/compatibility-contract.md:1194-1198`).
- Output bytes are identical at every count and under any affinity or quota (A1, A2, A3).

After S2 (positional draw):

- `index = u64_be(AES-256_K(u64_be(code) || u64_be(position))[0:8]) mod pool_size`.
- `K = HKDF-SHA256(salt = "decoy-engine/positional-prf/v1", ikm = job_seed, info = u32_be(len(ns)) || ns_utf8)`, built once per (job, namespace) per batch call (key schedule in a context object, as `DeriveContext` hoists HKDF today).
- `code` is a fixed per-site constant from one table, `POSITIONAL_SITES` in `src/decoy_engine/determinism/_positional_prf.py`: faker positional `1`, categorical positional `2`; never derived from a string at run time.
- Security property: without `job_seed`, the indices of a column are indistinguishable from uniform except with advantage at most `q^2 / 2^129` plus the modulo bias `pool_size / 2^64` (`q = 10^10` gives about `2^-63`). Distinct namespaces and distinct primitives get independent keys (distinct salt; length-prefixed `info`). Bounded by `job_seed`'s 8-byte entropy, as today.

After S3 (source-keyed per-row draws):

- The deterministic per-row value draws compute `AES-CMAC_K(frame)` with the current length-prefixed frame (version | ns_len | ns | src_len | src) and `K = HKDF-SHA256(salt = "decoy-engine/row-cmac/v1", ikm = mask_key, info = u32_be(len(ns)) || ns_utf8)`. The index is `u64_be(tag[0:8]) mod pool_size`, as today.
- Sites, all in one slice so every table and every FK sees the same primitive in one release: deterministic pool index through `derive_validated_indices` and the native operator step (`src/decoy_engine/execution/native/_operator_step.py:117`); deterministic categorical (`src/decoy_engine/execution/native/_categorical_ext.py:73`); date shift (`src/decoy_engine/execution/native/_date_shift_ext.py:110`); bucket perturb (`src/decoy_engine/execution/native/_bucket_perturb_ext.py:172`); `windowed_date` (`src/decoy_engine/transforms/windowed_date.py:286`); and every other caller of the source-keyed index kernel found by S3's walk.
- Stay on HMAC-SHA256: vault per-vault keys, `K_tok`, plan and subset seeds, the `hash` strategy (its output is the HMAC by contract), FF1 (already AES).
- Security property: AES-CMAC is a PRF on the frame keyed by `mask_key` through HKDF; same keyed-ness and joinability as today (equal source and namespace give equal output within a key).

Non-goals: generation's own draws (no native kernel on its main path; GEN-STREAM-ALL), vault formats, `SEED_PROTOCOL_VERSION` (owner question 2).

## 4. Enumerations

### Exit paths

1. Normal run: count recorded in `quality_metrics["execution"]["native_threads"]`; `auto_chunk["native_thread_clamp"]` reports the Rust clamp.
2. Invalid explicit count: `invalid_native_threads` (`src/decoy_engine/execution/native/_chunked_entry.py:104`), unchanged.
3. Invalid knee env: Rust `DeriveError` (`decoy-engine-native/src/threads.rs:58`), unchanged.
4. S2, S3: `check_pool_size` and the index validation (`src/decoy_engine/generation/pool/_sampler.py:100-115`) apply unchanged; key length errors cannot occur (HKDF output fixed at 32 bytes); a namespace over `u32` length is refused with the existing namespace-overflow code, raised after any `except` closes.

### Routes (where a thread count is consumed)

| Route | Entry | Count before | After S1 |
|---|---|---|---|
| plain run, native route | `run_pipeline` to `_operator_step` | run count, clamped to 4 | run count |
| plain run, Python faker oracle | `_faker_positional.py:64` | 1 | run count |
| pool sampler | `_sampler.py:176`, `:189` | 1 | run count |
| windowed_date | `windowed_date.py:286` | 1 | run count |
| Python FF1 workers | `_fpe.py:353-359` | `os.cpu_count()` | run count, through `map_in_context` |
| chunked public | `_chunked_entry.py:614` | 1 | `None` = run count |
| chunked internals | the `= 1` sites in section 1 | 1 | caller's value, default `None` |
| isolated with memory cap | `run_pipeline_isolated` | 1 | 1 (exception) |
| governed job | `run_job_with_governor` | 1 | 1 (exception) |
| monitor threads | `src/decoy_engine/execution/_isolated_memwatch.py:274`, `src/decoy_engine/execution/_governor_monitor.py:100` | n/a | allowlisted in the executor guard: they read no kernel |

### FK shapes

- S1: N/A, thread count does not reorder rows (A1 covers FK-preserving kernels).
- S2: positional draws are not joinable by design (keyed by position); no FK reads them.
- S3: every deterministic draw that FK preservation relies on (pool index of a key column, date shift of a key) moves in the same slice and release, so a parent and child masked by one engine stay equal. A parent masked by an older engine and a child by a newer one would not join; named in section 10.

### Fields

- S1 changes no field.
- S2 changes faker columns without `deterministic: true` on the mask path (`src/decoy_engine/execution/_strategies/_faker.py:123`, `src/decoy_engine/execution/native/_operator_step.py:176`) and positional categorical (`src/decoy_engine/execution/native/_categorical_ext.py:180` and its oracle twin).
- S3 changes every deterministic column of the sites listed in section 3: faker `deterministic: true`, deterministic categorical, date shift, bucket perturb, windowed date.

### Output surfaces

- Masked bytes: S1 none; S2 and S3 as in Fields.
- `native_thread_clamp`: 4 becomes the host's usable cores.
- `lock/v1` probe digest: changes in S2 or S3 if `run_probe` (`src/decoy_engine/support/_probe.py:128`) covers the moved draw; regenerated in the same PR.
- `run_mask_chunked` default `1` to `None` (signature freeze `tests/unit/execution/test_r3_public_signature_freeze.py:56`).

## 5. Slices and size

- **S1 THREADS (R2).** Rust: knee constant removed; `resolve` clamps to `min(requested, host_available)`, and to the env knee only when set; a rows-per-thread floor (start at 16,384, set from the A6 sweep) (`threads.rs` 662 lines, net about -10). Python: a run budget `ContextVar` set in a `with` at the run entry from `native_threads_for_run`, read by `derive_validated_indices`, the native wrappers and the FF1 pool when no explicit count is passed (`execution/pipeline/_host.py` 238 to about 265; `generation/pool/_sampler.py` 543 to about 550; `execution/native/_index_ext.py` 334 to about 338; `execution/_strategies/_fpe.py` one line); the `= 1` defaults become `None` (`_chunked_entry.py` 689, census ceiling 689: default-value edits only, net 0 lines). Executor guard test (new). Contract and changelog. New module in `execution/`: none.
- **S2 POSITIONAL-PRF (R3).** Python `src/decoy_engine/determinism/_positional_prf.py` (new, about 90: `POSITIONAL_SITES`, key derivation, ECB batch). Rust `decoy-engine-native/src/positional.rs` (new, about 90: `PositionalPrfContext`, `encrypt_blocks` over 8-block groups), `batch/index.rs` (145 to about 180). Callers switch: `_faker_positional.py`, `_operator_step.py:176`, `_categorical_ext.py:180`. Census rows for each new key-handling function. KAT file.
- **S3 ROW-CMAC (R3).** Before code: re-measure HMAC and CMAC per row on the Mac node (ARMv8 SHA2 and AES instructions) and on the Dell (no SHA-NI), at 1 thread and at the default count, end to end on a 10M-row deterministic mask. Expected, stated before measuring: on the Dell the kernel drops from about 580 ns/row to about 40 to 80; on the Mac, where SHA-256 has hardware support, the gain is likely 2x to 4x on the kernel; end to end at default threads the gain is smaller because reads, writes and the Arrow boundary take a large share. Gate: if the Mac end-to-end gain is under 1.3x, S3 stops and reports to the owner before building. Code: Python `src/decoy_engine/determinism/_row_cmac.py` (new, about 80), Rust `decoy-engine-native/src/row_cmac.rs` (new, about 100) with the `cmac` crate (supply-chain review: pinned version, `cargo deny`, license MIT/Apache-2.0), `derive.rs` source-keyed entry points switch (679 to about 650; HMAC stays for `hash`). Census rows. KAT file.

## 6. Placement

| New file | Directory | CODEMAP row | Sits beside |
|---|---|---|---|
| `_positional_prf.py` (S2), `_row_cmac.py` (S3) | `src/decoy_engine/determinism/` (4 modules) | "Determinism and keys" | `_derive.py`, `_hkdf.py` |
| `positional.rs` (S2), `row_cmac.rs` (S3) | `decoy-engine-native/src/` | native companion crate | `derive.rs`, `fpe.rs` |
| `test_thread_invariance.py` (S1) | `tests/unit/execution/native_threads/` | native tests | `test_default.py` |
| `test_executor_context.py` (S1 guard) | `tests/sentry/` | engine sentries | `test_secret_material_census.py` |
| `positional_prf_kat.json`, `row_cmac_kat.json`, `test_positional_prf.py`, `test_row_cmac.py` | `tests/native/` | native parity tests | `test_determinism_goldens.py` |

`execution/` (frozen 103) and `execution/native/` (55) get no module.

## 7. Design notes

- S1 principle: one place per fact. The run's count is resolved once (`native_threads_for_run`) and read through one context-local budget, not passed through ten signatures; the change pain removed is every new kernel site needing a new parameter thread. Pattern: PEP 567 context variables with per-task `copy_context` (existing `map_in_context`).
- S2, S3 principle: key separation by construction (one salt per primitive; length-prefixed `info`); one table of positional site codes. Patterns: AES-CTR-style counter PRF (SP 800-38A), AES-CMAC (SP 800-38B), HKDF (RFC 5869).
- Typed context objects: `PositionalPrfContext` and `RowCmacContext` hold the key schedule per (job or mask key, namespace), built once per batch call; no per-row key setup; no flag argument switching HMAC and CMAC (separate entry points).

## 8. Class table

| # | Class | Where it applies | Structure that closes it | Proof | Mutation that must turn it red |
|---|---|---|---|---|---|
| 1 | Value-bearing output | metrics; PRF and CMAC errors | counts only; codes, never a key, position or source value | A7 | put the derived key in an error (A7 red) |
| 2 | Cleanup missing on an exit path | run budget variable; key material | budget set and reset in one `with`; derived keys held in census-checked form (wiped or boxed) | A4, census | set without reset (A4 red) |
| 3 | State and concurrency | rayon ranges; executor workers; concurrent runs | output by row index; per-task `copy_context`; context-local budget | A1, A4 | submit FF1 tasks without `map_in_context` (A4 red) |
| 4 | Route parity and silent fallback | native vs Python reference; dropped counts | one budget read in `derive_validated_indices`; KATs shared by Rust and Python | A5, A7, A11 | drop the budget read in `_sampler.py` (A5 red) |
| 5 | Referential integrity | S3 deterministic key columns | all sites move in one slice; A12 joins parent and child | A12 | move only the pool-index site (A12 red on a date-shift key) |
| 6 | Untrusted producer | knee env; namespace text | strict env parse; namespace length-prefixed | existing, A8 | drop the length prefix (A8 collision red) |
| 7 | Check then use | host quota read | resolved once per run | A3 | re-read per batch (A3 red under a changing fake quota) |
| 8 | Weak tests | invariance at 1 vs 2 only; uniformity on tiny samples | counts {1, 2, 4, 8, 13, 26, None}; rows {1, 16,383, 16,385, 3,000,001}; chi-square over 10^6 draws at pool 10,000 | A1, A9 | split rows by thread count (A1 red at 13) |
| 9 | Refactor drift | `hash` strategy and vault keys in S3 | stay HMAC; their goldens byte-identical | A13 | route `hash` through CMAC (A13 red) |
| 10 | Frozen contract drift | public default; masked bytes | contract entries and `Breaking:` lines; freeze test updated | A2, A9, A12 | change the default without the entry (freeze test red) |

### Recurring defect catalog (`catalogs/recurring-defects.md`)

| # | Class | Applies | How this plan closes it |
|---|---|---|---|
| 1 | Anchored validation | knee env parse | existing Rust integer parse of the whole value; A-case `"4\n"` refused (existing test kept) |
| 2 | Strict wire and stored types | KAT files | read with a strict model: hex strings of fixed length, ints not bools; a bool `pool_size` is refused |
| 3 | No exception context | PRF, CMAC and namespace-overflow errors | coded errors raised after the `except` block closes; A7 asserts `__cause__ is None and __context__ is None` |
| 4 | Versioned read models | KAT files; the draw itself | KAT files carry `"kat": "positional-prf/v1"` or `"row-cmac/v1"` and an unknown tag is refused; the draw version is in the HKDF salt |
| 5 | Normalized guard scanners | executor guard; kernel-site guard | the walk resolves `from concurrent.futures import ThreadPoolExecutor as T`, `concurrent.futures.ThreadPoolExecutor`, `.submit` and `.map` on a bound executor, and `with ... as ex`; a seeded case per spelling (A5) |
| 6 | No reaching into private modules | `execution/` calling `determinism/_positional_prf.py` | export from `decoy_engine.determinism`'s `__init__`; callers import the package name |
| 7 | No hidden CI failures | KAT runs on three backends | the force-soft and arm64 KAT jobs are required, no `continue-on-error` |
| 8 | One input, one trust class per entry point | namespaces (user-chosen) vs site codes (program constants) | site codes come only from `POSITIONAL_SITES`; namespaces go through the length-prefixed `info`; separate parameters |
| 9 | Mutations on the final head | every slice | slice record names the head of each mutation run |
| 10 | Allowlisted helpers are still checked | the two monitor threads in the executor guard | allowlisted by exact `(path, function)`; a new thread elsewhere is red |
| 11 | No raised caps | `_chunked_entry.py` ceiling 689; `derive.rs` | `_chunked_entry.py` edits are net 0 lines; new code goes in new files; no cap raised |

## 9. Acceptance tests (each fails before its slice, except A1, A8's HMAC half and A13, which are controls)

S1:

- **A1 thread invariance.** For each kernel (index, crypto hash, FF1, raw hex) and a full `run_pipeline` mask of a 6-column table (pooled faker, deterministic faker, categorical, hash, fpe, date shift), digests at counts {1, 2, 4, 8, 13, 26, None} and rows {1, 16,383, 16,385, 3,000,001} are equal. The 26 case runs on the Dell node through `vm-run`.
- **A2 chunked default.** `run_mask_chunked` without `native_threads` records source `auto` and the usable count; output equals explicit 1. Fail-before: `explicit` 1.
- **A3 affinity and quota.** In a child process with affinity of two CPUs, and with a fake cgroup root whose `cpu.max` is `200000 100000` (`detect_usable_cpus(fs_root=...)`), the run records 2 and the kernel spy and the FF1 pool both see 2. Fail-before: the oracle path sees 1 and FF1 sees `os.cpu_count()`.
- **A4 budget scope.** Two threads in one process run `run_pipeline` with explicit 3 and 5, each with an fpe column on the Python path: every kernel call and every FF1 worker task sees its own run's count (worker tasks read the budget inside the task). After a failed run, a library call outside a run sees no budget. Fail-before: no budget.
- **A5 guards.** (a) Every compiled-kernel method call in `src/decoy_engine/` (methods of the wrappers in `execution/native/_*_ext.py`, found by resolving the wrapper classes) takes its count from the budget or an explicit argument, or is allowlisted with a reason. (b) Every executor `submit`/`map` goes through `map_in_context`/`run_in_context`; the two monitor threads are allowlisted by `(path, function)`. Seeded bypasses per class 5 spelling turn each red.
- **A6 speed (vm-run, not unit).** 10M-row mask with a pooled faker column, Parquet to Parquet, at least 1.8x faster than knee 4 at `70881ad79` (8.67 s); index kernel at 26 threads at most 80 ns/row. On the Mac (10 cores), no count is slower than knee 4.

S2:

- **A7 known answers and backends.** Fixed vectors (job seed, namespace, site code 1 and 2, positions 0, 1, 2^32, 2^64-1, pool sizes 1, 7, 10,000, 2^31) give the same indices in Rust and in Python, and in a third computation inside the test built from `cryptography` AES-ECB and HKDF directly. The Rust KAT runs on three backends: x86_64 AES-NI (Dell), aarch64 ARMv8 crypto via `aes` 0.9 (Mac), and a force-soft build (`RUSTFLAGS="--cfg aes_force_soft"`); each run records its backend in the test output. Errors carry no exception context. Fail-before: functions do not exist.
- **A8 key separation.** The PRF key for namespace `foo` differs from the HMAC key for namespace `decoy/positional-prf/v1foo` and for `foo`; the S2 key for `ab` differs from the S2 key for `a` and from the S3 key for `ab` (distinct salts; `info` is `u32_be(2) || "ab"` vs `u32_be(1) || "a"`, so no namespace is a prefix encoding of another); the KAT file holds these vectors. The HMAC half (existing keys unchanged) is a control.
- **A9 positional parity and keyed-ness.** Pool 10,000, seed fixed in the test: native and oracle routes give identical bytes for a positional faker and a positional categorical column; identical across counts and chunk offsets (offset 0 and 4,096 of 10,000 rows equal the whole); a second fixed seed changes at least 99% of indices; a second namespace does the same; chi-square over 10^6 draws into 100 buckets passes at p > 0.001.
- **A10 speed.** Positional draw at 1 thread at most 40 ns/row in Rust and 60 ns/row in the Python reference, recorded per backend (AES-NI, ARMv8, force-soft) with the key schedule built once per (job, namespace).

S3:

- **A11 CMAC known answers.** RFC 4493 test vectors pass in both implementations; Decoy KATs (mask key, namespace, frames of source lengths 0, 1, 15, 16, 17, 1,000, pool sizes 1, 7, 10,000) agree in Rust and Python on the three backends.
- **A12 FK consistency.** A parent and child with a deterministic faker key and a date-shifted key column, masked in one run: every child key equals its parent's masked key; chunked and resident agree. Fail-before: HMAC vectors (the test pins the CMAC KAT values).
- **A13 HMAC controls.** `hash` strategy output, vault per-vault keys, `K_tok`, plan and subset seed goldens are byte-identical.
- **A14 re-measure record.** The Mac and Dell numbers of section 5 are in the slice record before the first code commit; the gate rule (under 1.3x end to end on the Mac stops S3) is checked.

## 10. Frozen contracts and compatibility

S1: `run_mask_chunked(..., native_threads: int | None = None)`, default `1` to `None`; contract entry beside `docs/compatibility-contract.md:866`, and the ENGINE-THREADS-DEFAULT entry (`:1186-1201`) sentence on the knee of 4 is replaced. Freeze test updated with a `Breaking:` line. `native_thread_clamp` values change. No output bytes change.

S2 (`Breaking:`): masked values of positional faker and positional categorical columns change for every seed. Deterministic columns, vaults, tokens and FF1 do not change in S2.

S3 (`Breaking:`): masked values of every deterministic column of the listed sites change. A table masked before S3 does not join a table masked after S3 on those columns; re-mask both. Vault per-vault keys and tokens do not change; a vault that recorded deterministic masked values from before S3 maps old values only (pre-GA: no vaults in the wild, `docs/compatibility-contract.md:600-610`).

Versioning: the HKDF salts `decoy-engine/positional-prf/v1` and `decoy-engine/row-cmac/v1` version each draw on its own; `SEED_PROTOCOL_VERSION` is not bumped, because a bump re-keys generation and every vault too (`docs/compatibility-contract.md:600-610`). Owner question 2.

## 11. Pre-mortem

- A shared 64-core host gets a run on every core. Same as Polars and DuckDB; an explicit count and the knee env lower it; quotas are honored.
- Small batches pay spawn cost: the rows-per-thread floor; A6 on the Mac.
- A library caller outside a run gets the host clamp, not 1. Named in the changelog.
- A new executor site forgets the context: the A5(b) guard fails.
- No AES hardware: the force-soft KAT proves correctness; A10 records the slower speed, still under HMAC.
- S3 gains less than hoped on SHA-capable hosts: the A14 gate stops it before code.
- The `cmac` crate has an advisory: `cargo deny` fails CI; the crate is small and audited by RustCrypto.

## 12. Open questions for the owner

1. Thread cap: none beyond the usable cores and `MAX_NATIVE_THREADS` (recommended), or a fixed default cap such as 32?
2. Versioning S2 and S3: per-draw HKDF salts (recommended; only those draws change) or a `SEED_PROTOCOL_VERSION` bump (also re-keys generation and vaults)?
3. S3 scope (Dennis added it under the owner's "faster and more robust" principle): confirm that deterministic masked values may all change in V1, with the A14 measurement gate. Recommended: yes.
