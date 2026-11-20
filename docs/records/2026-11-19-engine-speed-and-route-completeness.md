Status: proposal

# Engine speed and route completeness: current state, limits, vision, V1 paths

Owner: Cam. Author: Opus 5.5 orchestrator, with four read-only Sonnet research passes. Date:
2026-11-19. Snapshot: engine `origin/main` b2123634f, CLI `origin/main` 4564b745. Scope: engine
and CLI routes for masking and generation. Platform is parked and appears only where it calls the
engine.

Rules consulted: `dev-rules/README.md` (routing), `00-universal.md`, `risk-and-exceptions.md`,
`development-loop.md`, `performance.md`, `documentation.md`; CLI `docs/ROADMAP.md` section 3
(1.0 blocking rule).

Risk: R1 for this document (proposal only, no behaviour change). Each item in sections 5 and 6
gets its own plan and risk level when it becomes a row.

Method: code reading at the snapshot, the existing records and plans, and one toy routing probe
(4 column types, 60 rows, `explain_plan=True`). No new benchmarks. A claim marked "estimate" or
"unmeasured" has no recorded number behind it. Per `performance.md`, every slice that comes out of
this document must record its workload, baseline and target before it optimizes. File references
are relative to `src/decoy_engine/execution/` unless they start with another top directory.

## 1. Summary

1. Masking is fast when a job lands on a native route. A 100M-row single table masks in about
   2 minutes at 4 threads (W2 mix). Foreign-key (FK) jobs on the out-of-core (OOC) route run at
   20k to 40k rows/s with flat memory.
2. Generation is about 10 times slower than masking: about 14k to 15k rows/s, and no generation
   column runs in Rust. One transform, `windowed_date`, uses about 87% of pure generation time.
3. The default route is not always the best route. The largest gap: a single table of 100k rows
   or more that has one integer column with nulls, or one decimal, binary or nested column, runs
   the in-memory pandas oracle with no memory guard. The toy probe confirms the route choice
   (section 2.6).
4. Routing is per table and atomic. One Python-only column (for example a faker `email` column)
   sends every column of that table to pandas. Of 109 `mask:` rules in the shipped disguises,
   58 are faker, and only `person_first_name` and `person_last_name` have native admission.
5. The CLI loads every source table whole through pandas or `pq.read_table`, and a plain
   `pip install decoy` has no Rust companion. Both limit real-world speed more than any kernel.
   RUN-STREAM (row 63a) and REL-PKG/CLI-REL (rows 90/94) already target these.
6. Speed work splits cleanly for release planning. Changes that keep output bytes the same can
   ship in any 1.x release. Changes to output bytes, defaults or refusals must land before the 1.0
   freeze or wait for 2.0 (ROADMAP.md section 3, rule 2).

## 2. Current state

### 2.1 Routes and how `auto` picks one

`decide_route` (`_pipeline_context.py:480`) calls `decide_execution_route` (FK layer) and then
`decide_chunk_route` (single-table layer).

| Route | Entry | Used for | Default reachable |
|---|---|---|---|
| Full-frame pandas oracle | `_pipeline_generate_mask.py:331` | anything no other route admits | yes, as the fallback |
| Unified slice (in-memory native) | `_unified_slice.py:369` | one non-FK mask table under 100k rows | yes |
| Native chunked lane | `_pipeline_auto_chunk.py:439` | one non-FK mask table, 100k rows or more, 50k-row chunks | yes |
| Multi-table split | `_pipeline_multi_table.py:186` | several independent mask tables | yes |
| Sequential (SEQ) | `_sequential.py:225` | FK jobs, table at a time, per-column native seam | yes |
| Out-of-core (OOC, DuckDB) | `out_of_core/_runner.py:108` | FK jobs, bounded memory | yes, preferred for eligible FK jobs |
| Mixed generate and mask | `_mixed_static.py` | generate tables plus masked children | yes |
| Stream | `execution_mode="stream"` | streaming sink | opt-in |
| Governor | `_governor.py` | RSS supervision and reroute | platform only |

Order for FK jobs: OOC, then SEQ when OOC declines, then full-frame when the job is not
bounded-eligible (validators, fidelity report, post-validation, vault, generate plus mask,
cross-table cycle). Full-frame rejects before read when the estimate says it will not fit
(`_pipeline_routing.py:471-510`).

Order for a single non-FK table: chunked lane (100k rows or more), then unified slice, then the
pandas oracle. The reject-before-read guard and the byte-estimate check apply to FK jobs only
(`_pipeline_routing.py:425`, `:524`).

Byte-estimate routing is on by default (`_pipeline_routing.py:293`). Only the capacity probe turns
it off (`capacity.py:384`).

Polars is used only by `subset/` and the parquet adapter. Polars masking was removed on
2026-09-18.

### 2.2 What runs in Rust for masking

The companion exports six kernel families: keyed hash (`derive_batch`), keyed index draw
(`derive_index_batch`), raw hex for `group_key`, FF1 for `fpe`, text span detection, and
`text_mask` detect plus splice for redact and passthrough spans. There is no Rust date parse or
format, and no Rust FK join or resolution kernel.

"Native" therefore covers four different levels of work:

| Level | Operators |
|---|---|
| Rust computes the whole value | hash, group_key, fpe without `checksum:` |
| Rust draws the key, Python or Arrow does the rest | categorical, faker (pool built in Python), bucket_perturb and date_shift (parse and strftime in pandas) |
| Rust finds spans, Python splices | text_redact, text_mask for faker, date_shift spans and non-ASCII cells |
| Arrow kernels, no companion | redact, truncate, passthrough |

Python-only on every route: faker with any provider other than first and last name, fpe with
`checksum:`, code_set, bucketize, top_code, windowed_date, shuffle, formula, derived kinds,
nested, joint_mask, geo_generalize, grouped_series, tokenize and vault, composite and custom
providers, `ner` text_redact.

Route-specific declines that matter:

- OOC declines date_shift, bucketize, `when:` predicates and non-deterministic categorical
  (`out_of_core/_compat.py:75-96`, `:258`, `:350`). Those jobs fall to SEQ.
- The chunked lane sends any table that touches a declared FK to the pandas chunk oracle
  (`native/_dispatch.py:206-262`).
- `date_shift` without an explicit `date_format` blocks chunking and native on every route
  (`_planner.py:425-430`). Ten shipped disguise rules use it that way.
- `large_string` sources decline most exact-string operators (`native/_real_type_admission.py:93-103`).

FK shapes: OOC handles single, chain, diamond, composite group and multi-parent. OOC declines
self-reference, cycles, scalar-masked composite children, composite chains and some key dtypes
(decimal, uint64, timestamp with time zone, dictionary). SEQ handles all of these except cycles.
Cross-table cycles run full-frame only (V1 decision: auto full-frame fallback, first-class in V2).
FK key resolution is pandas on SEQ and full-frame, and DuckDB on OOC.

Subset uses polars, pyarrow and Python. Seeded `count` and `fraction` sampling is a Python
per-row HMAC loop (`subset/_seed.py:~283-298`), and closure holds Python sets of row indices.

### 2.3 Generation

- Core: `generation/_streamed.py:339 run_generation`, 65,536-row batches, per-column streams in
  `_column_streams.py`. A bounded stage-then-rename sink and a `GenerationBudgetLedger` exist.
- Vectorized: `distribution` (uniform family, numpy), `constant`, and pooled faker for an
  allowlist of providers at 50,000 rows or more (`_faker_pool.py:231`).
- Python per row: string and numeric `sequence`, `categorical` (`random.choices`), `reference`
  (FK), the null mask, per-row faker, `windowed_date` (HKDF derive, numpy RNG and pandas per row,
  `transforms/windowed_date.py:328`), unique faker (retry loop), fitted `statistical` sampling
  (reseed per row, `statistical/_sample.py:335-488`), `formula`.
- Admission is per plan (`_admission.py:55-64`). One `statistical`, `formula`, `lookup`,
  `derived`, `derived_aggregate`, `grouped_series` or `group_key` column sends the whole plan to
  the legacy resident generator. Fitted generation therefore never streams.
- FR3, a Rust selection kernel for generation, measured slower than vectorized numpy and was
  shelved on 2026-10-18 (CHANGELOG.md:2827). Any Rust generation work must beat numpy first.
- The `providers_v2` identifier providers (NPI, MRN and others) are used by masking only. Wiring
  them into generation is row 24p.

### 2.4 Threads and memory defaults

- `run_pipeline(native_threads=1)` is the engine default (`_pipeline.py:140`). The CLI passes all
  usable cores (CLI `src/decoy/_resources.py:114-120`). Rust clamps to
  `min(requested, host cores, 4)` (`decoy-engine-native/src/threads.rs:47`), and the knee of 4 was
  measured on one 8-vCPU host class. `DECOY_NATIVE_MASK_THREAD_KNEE` overrides it.
- Thread count is proven not to change output (in-crate tests `thread_count_never_changes_output`
  and siblings, `docs/plans/2026-10-15-gap9-native-thread-grant.md:29`). Raising the default is
  byte-safe.
- Chunks run one after another. Parallelism exists only inside a native batch.
- OOC budget: 25% of the RAM ceiling. Reorder threshold: 2M parent keys. Chunk size: 50k rows,
  not adaptive to row width.
- `PLANNER_ROUTING_ENABLED=False` (`_planner.py:99`) and the job estimator
  (`_job_estimate.py`, `_throughput_calibration.py`) are advisory only. They never change a route.

### 2.5 How the CLI reaches the engine

- Plain `decoy run` calls `run_pipeline` with no `execution_mode` (CLI
  `src/decoy/cli/run/_execute.py:337-374`). The engine picks the route. The CLI passes
  `native_threads`, `out_of_core_threads` and `out_of_core_budget_bytes` from flag, env, settings
  file, then auto (all cores, 25% RAM).
- Sources are loaded whole (CLI `src/decoy/cli/_sources.py:403-425`): CSV through pandas with
  `dtype=str`, parquet through `pq.read_table`, fixed-width through the engine reader. The
  engine's lazy and stream input routes are not reached from the CLI today. RUN-STREAM slices C1l,
  C1a and C1b change this.
- `--chunked` is opt-in and mask-only, uses 100k-row chunks, and ignores the thread and memory
  settings until RUN-STREAM slice C2.
- Database input is `--duckdb-source` only, snapshotted to temp parquet first.
- CLI `pyproject.toml` has no `native` extra. A pip install runs pandas and says so only when the
  user passes `--native` or runs `decoy doctor`. The signed bundle ships the companion. Rows 90
  and 94 are PARTLY MERGED.

### 2.6 Toy routing probe (this research)

One table, `val` hashed and `extra` passthrough, auto-chunk threshold lowered to 10 rows to
stand in for a large table.

| `extra` column | Route chosen | Recorded reason |
|---|---|---|
| int64, no nulls | chunked (native) | none |
| float64 | chunked (native) | none |
| int64 with nulls | `pandas_fallback` | `extra (integer with nulls)` non-chunk-stable |
| decimal128(10,2) | `pandas_fallback` | `extra (decimal128(10, 2))` non-chunk-stable |

The probe ran with a companion built from an older local checkout, so it does not show whether the
unified slice admitted the small-table cases. The large-table results come from the planner gate
in Python and do not depend on the companion. The probe shows the route choice, not memory use at
scale.

### 2.7 Measured speed

| Workload | Route | Rows | Result | Kind | Source |
|---|---|---|---|---|---|
| W2 (3 hash, 3 passthrough, 2 redact, 2 truncate) | native, 1 thread, before cached HKDF | 100M | 1,572 s, RSS 463 MB | measured, n=1 | `docs/plans/native-throughput-phase0-baseline.md` |
| W2 after cached HKDF | native, 1 / 2 / 4 / 8 threads | 100M | 314 / 182 / 117 / 126 s, RSS about 0.5 GB | measured, raw in platform repo | GAP9 plan, bench notes |
| W2 | pandas oracle | 1M / 4M | 22.5k rows/s, RSS 1.4 / 5.0 GB | measured | phase-0 baseline |
| 10M "laptop demo" | native W2 | 10M | 43 to 80 s | extrapolated from 100M plus one devbox run | vault speed-demo note |
| FK chain 20M/35M/45M, keys only masked | OOC batch | 100M | 77 to 86 min, RSS 3.8 GB | measured | `docs/plans/2026-10-15-d4-scale-proof.md` |
| Synthea A-2, 40 columns | OOC | 1M / 10M | 43k / 39k rows/s | measured, record on branch `gate/rwa-scale-docfix` | vault A-2 note |
| Synthea A-2 | OOC | 100M | about 45 min | projected only (owner: no paid run) | same |
| Mixed generate and mask | mixed | 1M / 10M | 174k / 176k rows/s | measured | `docs/records/2026-10-17-f4-mixed-capacity.md` |
| Pure generation (windowed_date heavy) | generate | 1M / 10M | 15.0k / 13.9k rows/s, RSS flat 210 to 226 MB | measured | `docs/records/2026-10-18-f4a-gen-capacity.md` |
| text_redact Rust kernel | native | 1M | 3.0x to 3.7x over Python | measured, needs more reps | `docs/plans/2026-10-28-a7-text-redact-speedup-completion-remote.md` |

Gaps in the evidence: `docs/proof-manifest.json` has `"benchmarks": []`. No numbers exist for
macOS, Windows or arm64. No end-to-end `decoy run` number at scale exists (RUN-STREAM M1 is the
measurement slice). No numbers exist for fitted, formula or lookup generation, and the generation
numbers predate the GEN-TYPES work.

## 3. Limits

1. **Non-FK pandas fall-through with no guard.** A large single table that fails the chunked gate
   runs fully in memory, input and output resident, and is never rejected before read. Triggers:
   one integer column with nulls, or a decimal, binary, dictionary, list or struct column (masked
   or passthrough), `shuffle`, `formula`, other non-chunk-safe strategies, `date_shift` without a
   format, fpe `join_group`. Source: `_planner.py:482-499`, `_pipeline_routing.py:524`. At scale
   the likely result is an out-of-memory kill, not a clean capacity error (inferred from the code
   path, not measured).
2. **Whole-table atomic routing.** The chunked lane and unified slice never mix native and Python
   columns in one table (`native/_dispatch.py:1-30`). One slow column sets the speed of the table.
3. **Narrow faker native surface.** Only first and last name are admitted
   (`_operator_registry.py:214`). Shipped disguises use email (10 rules), phone (11), full name
   (10), street address (3), ipv4 (3) and zip (1) with no native path.
4. **Unified slice domain.** Passthrough admits only string, int64 and bool. Hash admits string and
   int64. The config must list every source column (`_unified_slice_admission.py:316`). A float or
   date passthrough column sends a small table to pandas. A 99,999-row table can be slower than a
   100,000-row table with the same schema.
5. **Python date work inside native operators.** date_shift and bucket_perturb draw the offset in
   Rust but parse and format in pandas.
6. **Checksum FPE in Python.** 28 `checksum:` parameters in the cpni, pc and hipaa presets run in
   Python on every route, although FF1 and a Luhn routine exist in the kernel.
7. **Generation per-row Python.** About 14k rows/s, and 100M takes about 2 hours. Fitted
   generation cannot stream.
8. **Thread ceiling.** The knee of 4 caps native threads on large hosts. Callers other than the
   CLI get 1 thread. Chunks do not run in parallel.
9. **Small FK jobs may take a slower route.** Default routing sends any OOC-compatible FK job to
   OOC at any size. GAP6 measured SEQ at 5.8x to 6.4x faster than full-frame from 50k to 500k
   rows, but OOC was never compared with SEQ on small jobs. Older notes put OOC about 29% slower
   than full-frame at 250k to 1M rows (`_planner.py:128-143`). Unmeasured.
10. **CLI input path.** Whole-table loads and pandas CSV reads bound large-file speed and memory
    before the engine starts.
11. **Install path.** Without the companion every route still works, at pandas speed, and the run
    does not warn.
12. **Scale ceilings by design.** Product target about 100M rows on a 32 GB host. The reorder lane
    memory is O(distinct parent keys). Bounded reorder for large parents is V2. Cross-table FK
    cycles are full-frame only in V1.

## 4. Final vision

The default `auto` run takes the fastest correct route for its input and says why.

1. **Route by column, not by table.** Every table runs on a bounded route. Native columns use Rust
   kernels and the remaining columns use their Python handler in the same pass, with output equal
   to the oracle.
2. **No unguarded in-memory path.** Every route either has bounded memory or rejects before read
   with a capacity error (exit 5). The pandas oracle becomes a parity reference and a small-job
   route, never the large-job fallback.
3. **Rust where the work is per value.** Keyed draws, hash, FPE including checksum schemes, date
   parse and format for the common formats, text splice, the subset sample loop. DuckDB stays the
   join engine for OOC. Python stays for cross-row and dynamic-type operators (shuffle, formula,
   derived kinds, nested, vault callbacks), where Rust gains little.
4. **Generation at masking speed.** Vectorized or keyed-counter RNG for every streamable kind,
   fitted generation admitted to the streaming core, Rust kernels only where they beat numpy.
5. **Input and output stream end to end.** The CLI hands lazy sources to the engine, and the sink
   writes in batches.
6. **The companion is always there.** Every supported install carries it, or the run says clearly
   that it is on the slow path.
7. **Evidence is published.** The proof manifest carries benchmark rows per route and per platform,
   so the website claims and the estimator constants come from the same runs.

## 5. V1 recommended paths

Tiers follow ROADMAP.md section 3, rule 2. "Must" items pass a 1.0 test (freeze, safety or broken
today). "Before freeze" items change output bytes or defaults, so they are V1 or wait for 2.0.
"If capacity" items keep bytes identical, so they can also ship in 1.0.x without breaking the
freeze.

### 5.1 Must (blocks 1.0)

| # | Item | Why it passes a 1.0 test | Where | Size |
|---|---|---|---|---|
| M1 | **Guard and widen the non-FK path.** (a) Let the chunked lane carry integer-with-nulls, decimal, binary and nested columns when they are passthrough. The carried-passthrough path already skips pandas (`native/_chunked_entry.py` docstring). (b) For masked columns of those types, keep ints Arrow-exact (`to_pandas_fk_safe` mapping) so the chunk oracle is stable. (c) Extend the byte-estimate fit check and reject-before-read to non-FK full-frame jobs, so an oversized job exits 5 instead of being killed. | Broken today: a documented `decoy run` on a large ordinary table can be killed for out-of-memory. Part (c) adds a refusal, which is a freeze item, so it lands before 1.0 or not in 1.x at all. | `_planner.py:482-499`, `_unified_slice_admission.py:371-411`, `_pipeline_routing.py:425,524` | M (a, b), S (c) |
| M2 | **Finish RUN-STREAM (row 63a).** E5b, C1l, C1a, C1b, C2, M1. Add two cases to the M1 measurement slice: an end-to-end `decoy run` at 10M rows, and SEQ against OOC for FK jobs from 10k to 1M rows (limit 9). | Already a 1.0 row by owner call. | CLI `src/decoy/cli/_sources.py`, engine lazy sources | in flight |
| M3 | **Companion in every supported install (rows 90/94),** plus a one-line warning on any run that executed no compiled kernel because the companion is missing. | Broken today: a pip install is about 3x slower with no message. The warning is new stderr output; keep it out of the result document so the output contract does not change. | CLI `_native_gate.py`, release workflow | in flight plus S |

### 5.2 Before freeze (byte-changing or default-changing, else 2.0)

| # | Item | Notes | Size |
|---|---|---|---|
| F1 | **Batch the `windowed_date` derive and offsets.** Use the batched derive the pool sampler already uses, and vectorize offsets and formatting. Biggest single generation win (87% of pure generation time, measured). If the batch can keep the per-row HKDF bytes, this moves to 1.x. The plan decides that first. | `transforms/windowed_date.py:328` | M |
| F2 | **Decide the fitted-sampler RNG now.** A keyed counter RNG with vectorized `searchsorted` makes fitted generation faster (5x to 20x, estimate) and is the prerequisite for streaming it. It changes output bytes, so it is 1.0 or 2.0 (see the 2.0-holding entry "re-baselined generation oracle"). Recommendation: hold to 2.0 unless F1 shows generation speed is a launch complaint. | `generation/statistical/_sample.py` | L |
| F3 | **Engine default `native_threads`.** Change `run_pipeline` to auto-detect usable cores (byte-safe, proven). The CLI already does this. Library and SDK callers get the fast path. A public default changes, so it is a freeze item. | `_pipeline.py:140` | S |
| F4 | **date_shift without `date_format`.** Pick the semantics: detect the format from a bounded sample at plan time, or require it at config time with a coded reason. Either one changes behaviour. Needs an owner call (Q4). | `_planner.py:425-430`, `native/_requirements.py:~573-590` | M |

### 5.3 If capacity (byte-preserving, also fine as 1.0.x)

Ranked by expected impact on shipped configs. The impact is estimated from config prevalence, not
measured; each slice benchmarks first.

| # | Item | Why | Size |
|---|---|---|---|
| C1 | Widen the faker native allowlist to the disguise providers (email, phone, full name, street address, ipv4, zip). The index kernel is provider-agnostic. Each provider needs an all-string, byte-stable pool proof. | 58 of 109 shipped disguise rules are faker. Today one such column puts the whole table on pandas. | M |
| C2 | Vectorize generation `sequence`, `reference` and null-mask streams (numpy indices, one RNG call per batch). | 2x to 5x on those columns (estimate). If bytes change, move it to 5.2. | S |
| C3 | text_redact splice in Rust, reusing the `text_mask.rs` detect plus splice. | Free text is the slowest per-row masking. The kernel exists. | S to M |
| C4 | Accept `large_string` in exact-string operators through a boundary cast (as redact and truncate already do), and widen the unified slice passthrough domain to float, date, timestamp and other int widths. | Removes the 100k-row cliff. Polars, DuckDB and Arrow writers often produce `large_string`. | S |
| C5 | Native FPE checksum schemes (Luhn, NPI, GTIN and others) on top of the existing FF1 and Luhn body mode. | 28 regulated-preset parameters. | M |
| C6 | OOC date_shift and bucketize (B1, already planned). | Large FK jobs with dates leave OOC for SEQ. | M, in flight |

## 6. V1.x positioning

Rule for 1.x: same input, same seed, same output. Every 1.x speed release is "faster, byte
identical", proven by the parity suites. The release notes and the proof manifest carry the
before and after numbers.

**1.1: per-column routing.** Mix native and Python columns inside one table on the chunked lane
and the unified slice. This is the largest structural win after 5.3, and it needs parity work on
column order, warnings and `when:` order dependence (L). Ship with SEAM-REASONS so `decoy run`
reports the first decline reason per table.

**1.2: Rust date and text.** Rust parse and format for the common date formats, with pandas kept
for unusual ones (L). Full-Unicode text_redact and text_mask paths. Batch-level work in the hash,
index and group_key kernels, and text kernels that release the GIL and use `native_threads`
(audit items R10 and R11 in `docs/records/2026-11-04-rust-companion-design-audit.md`).

**1.3: throughput scaling.** Chunk-level parallelism (several chunks in flight, bounded by the
memory budget), a thread knee calibrated per host instead of the fixed 4, and chunk size adapted to
row width. Subset: Rust or Arrow for the seeded sample loop, then a streaming closure for 100M+.

**1.x, on demand:** OOC address faker, FPE FK key on OOC, OOC quarantine, VAULT-STREAM,
TOKENIZE-CHUNKED, fixed-width streaming (F05), CLI database and cloud sources (64, 64b, F01, F02,
F07), chunk-level resume, a native single-column hash child on the chunked FK lane. Rust
generation kernels come only after numpy vectorization, and only where a benchmark beats numpy
(FR3 lesson).

**2.0:** byte-changing generation (F2 if held, accelerated or streamed generation oracle),
fitted, lookup, formula and derived kinds admitted to the streaming core, first-class cross-table
FK cycles on a bounded route, bounded reorder for large parents, multi-hop composite FK chains,
Rust FK resolution on SEQ (sized XL, needed only if SEQ becomes the bottleneck).

**V3:** streaming and CDC masking (X-07).

## 7. Doc drift found

These docs disagree with the code at the snapshot. Each needs a doc-only fix, no behaviour change.

1. `docs/execution-backends.md` and `docs/records/2026-10-16-d-audit-compute-matrix.md` say SEQ
   group_key has no native path. It does (`_sequential_native.py:148-158`).
2. `docs/execution-backends.md` says OOC text_mask is a Python per-cell loop. It is native
   (`out_of_core/_text_mask_native.py`, wired at `out_of_core/_mask_group_c.py:217-221`).
3. `docs/records/2026-09-30-rust-coverage-evidence-audit.md` is stale: the chunked dispatcher is
   the default lane, and `CHUNKED_ROUTE_VETOED_STRATEGIES` is empty (`native/_requirements.py:144`).
4. `docs/relationships.md:~268-276` still calls the cycle decision pending. It was decided: auto
   full-frame in V1.
5. `decoy-engine-native/src/lib.rs:1-12` says everything else stays pure Python, and the
   `threads.rs` module docs say the pool is not wired. Both are out of date.
6. CLI `docs/roadmap/groups/generate.md` lists GEN-PROVIDERS, GEN-TYPES and GEN-CATALOG
   (24p, 24q, 24s) as Later (1.x). The 2026-11-08 owner decision says providers, types and catalog
   are V1. One of the two needs to change.
7. Row 63a text still says "today's one native thread". The CLI has passed all cores since C3.

## 8. Questions for the owner

1. **Q1.** Is the non-FK out-of-memory path (M1) a 1.0 blocker? Recommendation: yes. The
   reject-before-read part adds a refusal, so it cannot be added in 1.x.
2. **Q2.** Byte-changing generation speedups (F1 if it changes bytes, F2): before freeze, or hold
   to 2.0? Recommendation: F1 now, F2 held.
3. **Q3.** Faker native widening (C1): V1 if a slot is free, or first 1.0.x? Recommendation:
   V1 if a slot is free, because disguises are the main user path.
4. **Q4.** `date_shift` without a format: detect from a bounded sample, or require the format?
5. **Q5.** Generation roadmap tiers (drift item 6): which is right?
6. **Q6.** pip installs: add a `native` extra (wheels on PyPI), or keep bundle-only and warn?

## 9. Candidate inbox lines

Per ROADMAP.md rule 1, new work enters through `docs/roadmap/inbox.md`. Proposed lines, not yet
added:

- NONFK-OOM: a non-FK table with a nullable int, decimal or nested column runs unguarded pandas
  full-frame at any size (M1).
- NATIVE-MISSING-WARN: warn when a run used no compiled kernel because the companion is missing (M3).
- GEN-WINDOWED-BATCH: batch the windowed_date derive (F1).
- ENGINE-THREADS-DEFAULT: engine `native_threads` default to usable cores (F3).
- FAKER-NATIVE-WIDEN: native admission for disguise faker providers (C1).
- GEN-VECTOR-STREAMS: vectorize sequence, reference and null-mask streams (C2).
- TEXT-REDACT-RUST-SPLICE (C3), LARGE-STRING-CAST and UF-DOMAIN (C4), FPE-CHECKSUM-NATIVE (C5).
- RUN-STREAM M1 scope: add end-to-end `decoy run` at 10M and SEQ against OOC on small FK jobs.
- DOC-DRIFT-ROUTES: section 7 items 1 to 5 and 7.

## 10. Defect classes for the follow-on plans

This document changes no code. Each row it proposes gets its own plan, and that plan carries the
full class table. The classes most likely to apply, so planners start from them:

| # | Class | Applies to | Structure that closes it | Proof |
|---|---|---|---|---|
| 1 | value-bearing output | M3 warning, M1 capacity refusal | messages from registered reason codes only, no values or paths | existing value-free sentry over the new emitters |
| 2 | cleanup on exit path | M1(c) refusal before read | refuse before any staging is opened | exit-path test: refusal leaves no stage directory |
| 3 | state and concurrency | 1.3 chunk-level parallelism | one bounded executor owned by the chunked lane | barrier test on chunk order and first error |
| 4 | route parity and silent fallback | M1, C1 to C6, 1.1 | every widened cell joins the route capability table and the parity matrix; every decline records a registered reason | matrix corpus per route; mutation that drops a reason record turns it red |
| 5 | referential integrity | C6, any FK route change | FK shapes enumerated per plan (section 2.2 list) | relational test per route per shape |
| 6 | untrusted producer | none expected | n/a: no new process or extension boundary | n/a |
| 7 | check then use on a path | M2 lazy sources | open once through the existing single-open seam | existing seam sentry |
| 8 | weak tests and overclaimed evidence | all, especially speed claims | `performance.md`: workload, baseline, warmup, variance recorded before and after | reviewer reruns the baseline on the same node |

## 11. Not verified

- Whether the unified slice admits the small-table probe cases with a current companion.
- Peak memory of the non-FK fall-through at scale (limit 1 is inferred from the code path).
- How the disguise `faker_type` maps to engine provider names (that code is outside the engine).
- Real throughput of the pandas parse and format steps inside native date_shift and bucket_perturb.
- Whether subset-written parquet lands as `large_string` and trips limit 4.
- Every speed-up figure marked "estimate" in sections 5 and 6.
