# Speed batch: windowed_date batching, engine thread default, date_shift format

Status: plan

Rules consulted: 00-universal, risk-and-exceptions, development-loop (Proportion, PLAN),
profiles/local-operations, performance, testing (Test depth), api-and-compatibility,
cross-cutting-concerns, proportionality, catalogs/recurring-defects, CODEMAP "Where Things Go"

Base: engine `origin/main` 92152f328. Source: record
`docs/records/2026-11-19-engine-speed-and-route-completeness.md` (branch
`docs/speed-route-completeness`), sections 2.3, 2.4, 5.2 (F1, F3, F4) and 10. Owner decisions of
2026-11-19: all three rows are 1.0 rows; F1 may change output bytes before GA if the change is
called out and changelog'd as output-changing; F4 requires the format (Q4: require, do not detect).

Rows: GEN-WINDOWED-BATCH (F1), ENGINE-THREADS-DEFAULT (F3), DATE-SHIFT-FORMAT (F4). Engine only,
plus one named CLI follow-up slice for F4.

## Slices

| Slice | Row | Size | Risk | Depends on | Output bytes |
|---|---|---|---|---|---|
| S1 `feat/gen-windowed-batch` | F1 part 1: proof step, batched derive, vectorized parse, shift and format | 1 day | R1 | none | unchanged (proved) |
| S2 `feat/gen-windowed-offsets` | F1 part 2: offsets from the batched index kernel | 1 day | R2 | S1, and the S1 benchmark gate | change, called out |
| S3 `feat/engine-threads-default` | F3 | 0.5 to 1 day | R2 | none | unchanged (proved) |
| S4 `feat/date-shift-format-required` | F4 engine | 1 day | R2 | none | refusal added |
| C1 (CLI repo) `feat/date-shift-format-cli` | F4 CLI follow-up | 0.5 day | R1 | none; must merge before the CLI re-pins to the engine release that carries S4 | none |

S1, S3 and S4 touch different files and can build in parallel in separate worktrees (never two
writers in one worktree). S3 and S4 both add a `docs/compatibility-contract.md` entry and a
`changelog.d/` fragment: keep both on merge.

Gates (gate roster): R1 slices get Codex. R2 slices get Codex and Dennis. Test depth per
`testing.md`: T0 per edit, T1 impact set per commit, T2 at each gate. Full-suite triggers: S2
(output bytes and goldens move), S3 (frozen public signature), S4 (frozen contract: a new refusal,
a new registered reason, shared fixtures). S1 has no trigger.

## Pinned guarantees and non-goals

- S1: `apply_windowed_date` returns exactly the same list, and raises exactly the same exception
  type and message, as `origin/main` for every input in the parity corpus. It is faster.
- S2: `windowed_date` output dates change for the same seed (mask and generate kinds both). Per
  row, the date stays inside `[anchor + min_days, anchor + max_days]`, null anchors stay null, the
  output stays keyed on the global row number (partitionable), and it stays deterministic across
  runs, batch sizes, routes and thread counts.
- S3: `run_pipeline()` with no `native_threads` uses the usable cores (cgroup and affinity aware).
  Output data bytes are identical to `native_threads=1`.
- S4: every `date_shift` column without a usable `provider_config.date_format` is refused at
  plan compile with one registered, value-free reason, before any source is read. The only
  exemption is a column whose format is owned by a declared-casting contract.

Non-goals: F2 (fitted sampler RNG), C2 (vectorizing sequence, reference and null streams), a Rust
date kernel, `bucket_perturb` format detection (owner question 2), the `text_mask` per-span date
detection (a span is not a column), other entry points' thread defaults (`run_mask_chunked`,
`run_sequential` keep `1`), platform changes (parked; re-pin checklist item only).

## S1. GEN-WINDOWED-BATCH part 1 (byte-identical)

### Current behavior

`transforms/windowed_date.py:277-343` `apply_windowed_date` is the one shared entry point for the
mask strategy (`execution/_strategies/_windowed_date.py:79`), the generation stream
(`generation/_column_streams.py:83-91`) and grouped windowed generation
(`generation/_grouped_windowed_generators.py:111`). Per row it calls:

1. `_is_null_cell`, then `_parse_anchor` (ASCII ISO regex, then `pd.Timestamp`, range check);
2. `derive(seed, namespace, i.to_bytes(8, "big"))`, a full HKDF plus HMAC per row;
3. `np.random.default_rng(first 8 digest bytes)` and `_sample_offset` (1 draw for `uniform`, 2
   for `early` and `late`);
4. `_shift_and_format` (`pd.Timedelta`, range check, `strftime("%Y-%m-%d")`).

The draw site is `mask.windowed_date` (`execution/native/_draw_sites_mask.py:344`), reproduced by
`WindowedDateProvider` (`execution/native/protocol/providers_mask.py:318`).

### Probe (this plan, Dell WSL2 node, 100k rows, ISO anchors, `early`, one warm call then one timed)

| Stage | us/row |
|---|---|
| whole `apply_windowed_date` | 131.9 |
| `derive` per row (HKDF each row) | 15.0 |
| `DeriveContext.derive_sources` (one HKDF, HMAC copy per row) | 3.8 |
| `default_rng` per row | 26.3 |
| `default_rng` + `_sample_offset` | 29.7 |
| `_parse_anchor` per row | 5.4 |
| `_shift_and_format` per row | 16.9 |
| vectorized parse, shift and `dt.strftime` | 1.05 |
| vectorized with `np.datetime_as_string` | 0.60 |

`derive_sources` matched per-row `derive` on 5,004 row numbers (0 to 4,999, 2^31, 2^32-1,
2^40+7, 2^63-1). The stage costs add up to about 67 us, half of the whole loop. The rest is not
attributed yet (likely allocator or GC churn from 100k short-lived Generators interleaved with
Timestamps). Step 0 profiles it. One run, n=1: this is a direction, not a baseline.

### F1 byte-identity expectation (the question the row asks first)

- The pool sampler's batched derive (`generation/pool/_sampler.py:118-166`,
  `derive_index_batch`) does NOT keep the per-row bytes. It canonicalizes the source
  (`generation/pool/_canonicalize.py:45-60`: an int becomes a 4-byte length plus a signed body,
  not the fixed 8-byte big-endian `i.to_bytes(8, "big")`), so the HMAC input differs, and it
  returns `u64 % pool_size`, not the 8-byte seed the PCG64 draw needs. Certain from the code.
  No existing compiled kernel takes raw 8-byte sources (`derive_hex_raw_batch` takes UTF-8 text).
- The Python batched derive (`determinism/_derive.py:241` `DeriveContext.derive_sources`, used by
  date_shift at `_strategies/_date_shift.py:298`) DOES keep the per-row HKDF and HMAC bytes: the
  key depends only on `(seed, namespace)`, and the per-row HMAC input is unchanged. True by
  construction and confirmed by the probe above.
- So S1 keeps output bytes by batching the derive in Python, vectorizing parse, shift and format,
  and keeping the per-row PCG64 draw. The per-row `default_rng` (about 30 us) stays as the floor.
  Removing it means changing bytes. That is S2.

### Step 0: proof first (first commit, before S1 code)

New `tests/unit/generation/test_windowed_date_batch_parity.py`:

- `test_batched_derive_matches_per_row`: on the committed corpus of row numbers (0..4,999,
  2^31, 2^32-1, 2^40+7, 2^63-1, and a non-contiguous `positions` list), with an 8-byte and a
  32-byte seed, `DeriveContext.for_column(...).derive_sources(...)` equals per-row `derive` byte
  for byte. Passes on base (pins the premise).
- `test_pool_index_batch_is_not_byte_identical`: documents the negative. For the same corpus,
  offsets from `derive_index_batch` with `pool_size = span + 1` differ from the per-row PCG64
  offsets in at least one row. Passes on base. It exists so S2 cannot claim byte identity. S2
  deletes it.
- `test_output_digest_pinned`: `apply_windowed_date` over the full parity corpus (below) hashes
  to a sha256 recorded from base 92152f328 and written into the test as a literal. Passes on
  base and must still pass after S1. S2 changes this literal on purpose.

Step 0 also puts the stage profile (cProfile at 150k rows, same corpus) in the S1 PR body, so the
unattributed half is named before code changes.

### Design

All changes are inside `transforms/windowed_date.py`. The current loop moves unchanged into a
private `_apply_reference(config, anchors, row_numbers, seed, namespace)`. A new fast path runs
first:

1. Classify each cell once: null (exactly `_is_null_cell`, no `pd.isna`, so `""` and `"NaT"`
   stay non-null), `str`, or other. A naive `datetime64[ns]` Series is a second admitted shape
   (cells are Timestamps, nulls are NaT). Anything else (object `date` or `datetime` cells, a
   tz-aware dtype, ints) goes to `_apply_reference` for the whole batch.
2. `str` cells: `_ISO_ANCHOR.match` per cell (the same compiled pattern), then
   `pd.to_datetime(values, format="ISO8601")` on the non-null cells.
3. Row numbers for non-null rows (from `positions` or `range(row_offset, ...)`), derived with one
   `DeriveContext` and `derive_sources(namespace, (i.to_bytes(8, "big") for i in rows))`.
4. Per non-null row: `_sample_offset(np.random.default_rng(seed_int), ...)`, unchanged.
5. `shifted = parsed + offsets.astype("timedelta64[D]")`, the range check against
   `SUPPORTED_MIN`/`SUPPORTED_MAX` vectorized, then `shifted.dt.strftime(_DATE_FMT)`.
6. Assemble `list[str | None]` with `None` at null rows.

Error parity by construction: any exception or anomaly in the fast path (a grammar miss, NaT, an
out-of-range anchor or result, overflow, a `to_bytes` overflow) discards the fast-path work and
reruns the batch through `_apply_reference`, which raises the exact first error the old loop
raised. There is no third error behavior. The function is pure, so the rerun has no side effects.
The seed and the `DeriveContext` stay local and are deleted on the exception path (the existing
`except BaseException: del seed` shape; the secret-material census sentry covers this module).

Time-boxed option (2 hours, keep only if the parity corpus stays identical): a cheaper exact
per-row Generator construction. Drop it if it needs numpy internals.

Established solutions: the batched keyed derive is the engine's own `derive_sources` (HMAC state
copied after the fixed prefix, stdlib `hmac.copy`), already used by date_shift. Vectorized date
arithmetic is pandas `to_datetime(format=...)` plus `Series.dt.strftime`. NumPy has no batch
constructor for many seeded Generators (search run: numpy parallel-RNG docs; the documented
pattern is `SeedSequence.spawn`, which gives different streams), so an exact byte-preserving
vectorization of the per-row PCG64 draw would mean reimplementing SeedSequence, PCG64 and the
bounded-integer method by hand. Rejected as hand-rolled machinery; S2 changes the derivation
instead.

Design notes: no new structure. One private helper and one fast path in the same module.

### Parity corpus (committed, `tests/unit/generation/_windowed_date_corpus.py`)

- 2,000 ISO dates from `np.random.default_rng(0)` over 1990 to 2030, 5% nulls mixed as `None`,
  `float("nan")`, `pd.NA`, `pd.NaT`.
- Edge anchors: date only; `T` and space separators; minutes only; seconds; fractions of 1 to 9
  digits; `1700-01-01` and `2200-12-31` (with windows that stay in range); pre-1970 anchors with a
  time of day; `2000-02-29`, `1900-02-28`, `2024-02-29`.
- Windows: `uniform`, `early`, `late`; `min_days == max_days`; negative windows; `-30..90`.
- Row numbering: `row_offset` 0, 65,536, 2^32, `2^63 - 1 - n`; a non-contiguous `positions` list.
- Seeds: 8 bytes and 32 bytes. Anchor shapes: object `str`, `datetime64[ns]` Series, object
  `datetime.date`, object `pd.Timestamp`.
- Error cases, each at a non-first row after good rows: bad grammar, `""`, `"NaT"`, a zone in
  the string, a tz-aware Timestamp, an int cell, an out-of-range anchor, a result past
  `SUPPORTED_MAX`, a row number past 2^64.

### Acceptance tests (S1)

In `test_windowed_date_batch_parity.py`, besides step 0:

1. `test_fast_path_equals_reference_on_corpus`: for every corpus case, the new
   `apply_windowed_date` output equals `_apply_reference` output, list for list.
2. `test_error_parity`: for every error case, same exception type, same `str(exc)`, and
   `__cause__ is None and __context__ is None` (recurring defect 3).
3. `test_fast_path_is_taken`: a spy on `_apply_reference` is not called for an all-`str` batch
   or a `datetime64[ns]` batch, and is called for an object `date` batch.
4. `test_batch_boundaries_do_not_change_output`: the generation stream at batch sizes 1, 7,
   32,768 and 65,536 gives the same column.
5. `test_fast_path_equals_reference_property` (Hypothesis, fixed seed and database): generated
   anchor lists (ISO strings in and out of the grammar, nulls, typed cells), windows, offsets and
   `positions`; the fast path and `_apply_reference` give the same list or the same error.
   A failing example is pinned as a regular case.

Must pass unchanged: `tests/native/test_determinism_goldens.py::TestWindowedDateGolden`,
`tests/native/test_draw_site_providers_golden.py`, `tests/native/test_draw_sites_catalogue_pinned.py`,
`tests/unit/generation/test_fr1_windowed_date.py`, `tests/unit/execution/test_dgrn_windowed_date.py`,
`tests/unit/generation/test_gen_window.py`, `tests/native/test_c8_iii_d2_native_positional_when.py`.
A failure in any of them is a stop and a report, never an edit.

Red-first: the step 0 tests pass on base (they pin the premise and the digest). Acceptance test 3
is red on base (no `_apply_reference`). Tests 1, 2, 4 and 5 are written before the fast path and
run green against the moved reference, so a broken fast path turns them red.

### Mutations (S1, on the final head)

1. Pass a constant namespace to `derive_sources`: digest and parity red.
2. Row number off by one (`row_offset + 1`): red.
3. Ignore `positions`: the `when:` positional case red.
4. Drop the vectorized result range check: error parity red.
5. Re-raise in the fast path instead of falling back: error parity red (message differs).
6. Use `pd.isna` for the null mask: the `""` and `"NaT"` error cases red.
7. `_DATE_FMT` with a time part: red.
8. Skip the second draw for `early`: red.

### Placement (S1)

| File | Change | Directory and CODEMAP line | Sits beside |
|---|---|---|---|
| `src/decoy_engine/transforms/windowed_date.py` | `_apply_reference` (moved loop), fast path | `transforms/` ("Transforms", by transform) | same file, 343 lines today, expect about 440 |
| `tests/unit/generation/test_windowed_date_batch_parity.py` | new | `tests/unit/generation/` ("Generation" tests) | `test_fr1_windowed_date.py` |
| `tests/unit/generation/_windowed_date_corpus.py` | new, shared with S2 | `tests/unit/generation/` | same |
| `tests/perf/test_windowed_date_bench.py` | new, `-m benchmark` | `tests/` row: `perf/` | `test_f4a_gen_capacity.py` |

No new public name. No CODEMAP change. Choke point: `apply_windowed_date` is already the one entry
point for all three callers; the draw-site golden fails if a caller bypasses it.

## F1 benchmark protocol (S1 and S2)

Per `performance.md`: workload, baseline, warmup, variance and tail, recorded before and after.

- Node: the Dell WSL2 Linux node through `vm-run engine` (`VMRUN_LINUX=1`), one slot, node idle
  per `node-watch` before each run. The same node and slot for baseline and candidate. The
  companion is installed (S2 also runs once without it).
- Baseline: `origin/main` 92152f328 measured in the same session, interleaved
  (base, candidate, base, candidate) to cancel drift. No number from the record is the baseline.
- Workload A, column micro-benchmark (`tests/perf/test_windowed_date_bench.py`): 200,000 rows
  from the corpus generator (ISO anchors, 5% nulls), each of `uniform`, `early`, `late`, window
  `-30..90`. Fresh process per configuration. One untimed warm call, then 7 timed calls. Report
  median, min, max and interquartile range in us/row. Scoped as a micro-benchmark; workload B is
  the end-to-end claim.
- Workload B, end to end: `tests/perf/test_f4a_gen_capacity.py` pure-generation 1M tier
  (1M `orders` plus 100k `people`, batch 32,768, 1024 MB budget), 3 runs each. Report wall
  seconds, rows/s and peak RSS (`wait4`). The record's 1M figure (about 15.0k rows/s on a 4-core
  host) is context only.
- Workload C, share: cProfile or py-spy at 150k rows (the record's profile size): the
  `windowed_date` share of pure-generation time, before and after.
- Variance rule: if `(max - min) / median` exceeds 10% on workload A, or the 3 runs of workload B
  spread more than 10%, recheck the node and rerun once. Report the max as the tail, not only the
  median.
- Correctness guard in every run: the workload B output digest is equal across reruns; for S1 it
  also equals the base digest.
- Resource budget: workload B peak RSS at most base +10% and under the F4a 500 MB ceiling.
- Targets. S1: workload A at most 45 us/row (from about 132); workload B at least 2x base rows/s.
  S2: workload A at most 10 us/row with the companion and at most 20 without it; workload B at
  least 4x base.
- Results go to `docs/records/2026-11-xx-gen-windowed-batch-bench.md` (Status: record) with the
  raw JSON under `docs/records/evidence/`.

S2 decision gate (decided by data, recorded in the S1 record): run S2 when, after S1,
`windowed_date` is still over 50% of pure-generation time (workload C) or workload B is under
40k rows/s. Expectation: S2 runs. The per-row PCG64 draw alone (about 30 us) is about three times
the cost of all other generation columns together (about 9 us/row, from the record's 87% share).

## S2. GEN-WINDOWED-BATCH part 2 (output-changing, before freeze)

### Design

Replace step 4 of the S1 fast path, and the reference path with it, by the pool sampler's index
kernel: `derive_index_batch(pa.array(row_numbers, pa.int64()), mask_key=seed,
namespace=namespace, pool_size=span + 1)`, reached through the same lazy loader the sampler uses
(`_compiled_index_kernel()`, with the reference kernel as the byte-identical fallback) and
checked with the sampler's `_validated_index_array`. Reuse them, do not copy them: export the two
helpers from `generation/pool` under public names (they are private today; recurring defect 6).

- `uniform`: `offset = min_days + idx`.
- `early` and `late`: a second call over the same row numbers with namespace
  `f"{namespace}/draw2"`, then `min` or `max` of the two offsets. This keeps the
  "min or max of two uniform draws" distribution the module documents.
- `span == 0`: no call, `offset = min_days` (today's rule).
- Row numbers above int64 (`positions` past 2^63 - 1): the call uses the reference kernel over
  Python ints. Same result as the compiled kernel would give.

The derive envelope does not change, so `SEED_PROTOCOL_VERSION` stays 7. Precedent:
`docs/determinism.md:209` (a change outside the envelope needs no bump). The site's
`provider_version` and family move instead.

### What changes with it

- Draw-site entry `mask.windowed_date` (`execution/native/_draw_sites_mask.py:344`): family,
  `seed_derivation`, `api_operation`, `call_shape`, `provider_version`, notes.
- `WindowedDateProvider` (`execution/native/protocol/providers_mask.py:318`) reproduces the new
  derivation; `row_generator` is replaced by `row_offsets`.
- Re-baselines, each with its new value in the diff: `test_draw_sites_catalogue_pinned.py` (the
  windowed entry only), `test_draw_site_providers_golden.py`,
  `test_determinism_goldens.py::TestWindowedDateGolden` (reproduces through the new provider),
  `test_windowed_date_batch_parity.py::test_output_digest_pinned` (new literal),
  `docs/native/draw-site-inventory.md`. Any other moved golden or digest is a stop: it means a
  second site changed.
- The step 0 negative test is deleted (its premise is now the design).
- Changelog fragment `changelog.d/gen-windowed-offsets.md`, marked output-changing:

```
Breaking (output-changing): windowed_date produces different dates for the same seed.

### Changed (windowed_date offsets, GEN-WINDOWED-BATCH, 2026-11-xx)

windowed_date now draws each row's offset from the keyed index derivation that pooled
sampling uses, in one batch per column, instead of a separate numpy generator per row. It is
about N times faster (see the benchmark record). Dates stay inside the configured window, null
anchors stay null, and output stays the same across runs, batch sizes and routes. Output from
earlier releases does not match: regenerate stored windowed_date output.
```

### Acceptance tests (S2)

New `tests/unit/generation/test_windowed_date_offsets.py`:

1. `test_offsets_in_window`: every non-null row's date minus its anchor is in
   `[min_days, max_days]`, for each distribution, over the corpus.
2. `test_distribution_shape`: 200k rows, `-30..90`. `uniform`: chi-square over the 121 bins,
   p > 0.001. `early`: mean offset below the window midpoint minus 15 days. `late`: above the
   midpoint plus 15 days. Fixed seed, fixed bounds, never edited to pass.
3. `test_compiled_equals_reference`: with the companion, compiled and reference kernels give the
   same offsets on the corpus, including row numbers past int64 (reference only).
4. `test_partitionable` (Hypothesis over split points): any split of the rows into chunks with
   their global row numbers gives the same column; the `positions` path gives each row the value
   of the ungated run.
5. `test_namespace_independence`: two columns with different namespaces differ in at least 99%
   of rows over 10k rows.
6. `test_mask_and_generate_share_the_derivation`: the mask strategy and the generation stream
   give the same dates for the same anchors, seed, namespace and row numbers.
7. Every S1 error-parity case still raises the same error (the error path did not move).

Red-first: tests 1, 2, 4 and 5 pass on S1 too (they pin properties). Test 6 against the new
provider golden and the re-baselined digest are red until the derivation lands.

### Mutations (S2)

1. `pool_size = span` (off by one): the window edge is never drawn, chi-square red.
2. The same namespace for both draws: `early` and `late` collapse to `uniform`, test 2 red.
3. `min` and `max` swapped: test 2 red.
4. Local row number instead of global: test 4 red.
5. Skip `_validated_index_array`: the stub-kernel test (an index past `pool_size`) red.

### Placement (S2)

| File | Change | Directory and CODEMAP line | Sits beside |
|---|---|---|---|
| `src/decoy_engine/transforms/windowed_date.py` | offsets from the index kernel | `transforms/` | same file |
| `src/decoy_engine/generation/pool/__init__.py`, `_sampler.py` | export the loader and validator under public names | `generation/pool/` ("Generation", pools) | `PoolSampler` |
| `src/decoy_engine/execution/native/_draw_sites_mask.py`, `protocol/providers_mask.py` | the site entry and provider | `execution/native/` | the other mask sites |
| `tests/unit/generation/test_windowed_date_offsets.py` | new | `tests/unit/generation/` | the S1 parity test |
| `changelog.d/gen-windowed-offsets.md` | new fragment | "Changelog fragments" | other fragments |

### Failure modes (F1)

- FM1 A fast path that differs subtly from the reference (a pandas parse rule, a null rule).
  Closed by full-corpus and property parity plus the pinned base digest.
- FM2 Error drift: a different first error, or a value in the message. Closed by the
  fall-back-to-reference rule and test 2.
- FM3 A builder edits a golden to pass in S1. Any golden edit in S1 is a stop.
- FM4 S2 claimed as byte-identical. The step 0 negative test shows it cannot be.
- FM5 Absurd windows (a span past 2^56 days) raise the coded `pool_size_overflow` in S2 instead
  of drawing. Value-free, and such windows already fail the date range. Accepted.
- FM6 Benchmark noise passed off as a win. Interleaved baseline, variance rule, max reported.
- FM7 Memory: the fast path holds one batch of anchors, digests and offsets (a few MB at 65,536
  rows). Workload B peak RSS is checked against base.

## S3. ENGINE-THREADS-DEFAULT

### Current behavior

`run_pipeline(native_threads: int = 1)` (`execution/_pipeline.py:140`). The CLI passes the usable
cores from the engine's own `detect_usable_cpus()` (CLI `src/decoy/_resources.py:114-120`).
`detect_usable_cpus()` (`execution/pipeline/_host.py:146`) is `max(1, min(affinity, floor(cgroup
quota)))`, cached per process, and raises `runtime.cpu_detection_failed` on an unreadable cgroup.
Rust clamps to `min(requested, host cores, 4)`. Thread count never changes output (in-crate
`thread_count_never_changes_output`, `docs/plans/2026-10-15-gap9-native-thread-grant.md:29`).
The count also switches lazy-input reads to Arrow threads (`execution/_chunked_input.py:388`,
`use_threads=native_threads > 1`) and stamps `native_thread_clamp` into
`quality_metrics["auto_chunk"]` when it is above 1 (`_pipeline_auto_chunk.py:588`). The
signature is frozen by `tests/unit/execution/test_r3_public_signature_freeze.py:56`
(`"1"`, `"int"`). The platform grants its own thread count (`api/config.py:334`).

### Design

- `native_threads: int | None = None`. `None` means auto. An explicit int keeps today's
  validation (1 to `MAX_NATIVE_THREADS`, bool refused).
- One resolver, `resolve_native_threads(requested: int | None) -> ResolvedThreads`, in
  `execution/pipeline/_host.py` beside `detect_usable_cpus`. Auto is
  `min(detect_usable_cpus(), MAX_NATIVE_THREADS)`. If detection raises `cpu_detection_failed`,
  auto resolves to 1 with source `auto_fallback`: the default must not fail a run that works
  today, and no output byte depends on the count. The source is recorded, so the fallback is not
  silent. An explicit int never falls back.
- Called once, in `_pipeline_context` where the knobs are validated today
  (`_pipeline_context.py:260`). `ctx.native_threads` stays an `int`, so every downstream signature
  is unchanged.
- `quality_metrics["auto_chunk"]` gains `native_threads_source`: `explicit`, `auto` or
  `auto_fallback` (additive, value-free).
- `run_pipeline_isolated` forwards kwargs unchanged; an omitted value resolves in the child,
  under the child's own cgroup and affinity.

Established solutions: Go 1.25 made `GOMAXPROCS` default to the cgroup CPU limit when it is lower
than the logical CPU count ([Go blog](https://go.dev/blog/container-aware-gomaxprocs)). The engine
already follows that rule in `detect_usable_cpus` (affinity, then the floor of the quota), and the
CLI uses it. No new detection code.

### Acceptance tests (S3)

New `tests/unit/execution/test_native_threads_default.py`:

1. `test_default_resolves_to_usable_cpus`: detection patched to 3; a chunked `run_pipeline` with
   no `native_threads` records `native_threads == 3` and `native_threads_source == "auto"`.
2. `test_explicit_value_wins`: `native_threads=1` and `=2` are recorded as given, source
   `explicit`.
3. `test_detection_failure_falls_back_to_one`: detection raises `cpu_detection_failed`; the run
   completes with 1, source `auto_fallback`. With `native_threads=2` and the same failure, 2 is
   used.
4. `test_cap`: detection patched to 5,000; resolved to `MAX_NATIVE_THREADS`.
5. `test_invalid_values_still_refused`: 0, -1, 1,025, `True` and `"4"` raise
   `invalid_execution_knob` before any read.
6. `test_default_output_bytes_equal_single_thread` (needs the companion; runs on a node with 4 or
   more cores): a W2-shaped table above a lowered auto-chunk threshold, as a resident table, a lazy
   CSV source and a lazy Parquet source. Output table bytes and schema with the default equal
   `native_threads=1`. Covers the Arrow `use_threads` input read.
7. The signature freeze row moves to `("native_threads", "KEYWORD_ONLY", "None", "int | None")`.
   The parameter count stays 47.

Benchmark note for the PR (not a gate): gap9 W2 at 1M rows, default against `native_threads=1`,
wall and peak RSS, 3 runs each on the same node. A peak RSS rise over 15% goes to the owner
before merge.

Red-first: tests 1, 3, 4 and 7 are red on base. Tests 2, 5 and 6 pass on base and pin behavior.

### Mutations (S3)

1. The resolver returns 1 for `None`: test 1 red.
2. The fallback also applied to explicit values: the second half of test 3 red.
3. Cap removed: test 4 red.
4. The resolver skipped for an isolated run that passes no value: an isolated variant of test 1
   (the child records the source) red.

### Placement (S3)

| File | Change | Directory and CODEMAP line | Sits beside |
|---|---|---|---|
| `src/decoy_engine/execution/_pipeline.py` | default and docstring | `execution/` ("Pipeline spine and routes") | same file |
| `src/decoy_engine/execution/pipeline/_host.py` | `resolve_native_threads`, `ResolvedThreads` | `execution/pipeline/` | `detect_usable_cpus` (194 lines) |
| `src/decoy_engine/execution/_pipeline_context.py`, `_pipeline_auto_chunk.py` | one call, one record field | `execution/` | same files |
| `tests/unit/execution/test_native_threads_default.py` | new | `tests/unit/execution/` | `test_r3_public_signature_freeze.py` |
| `docs/compatibility-contract.md` | dated pre-GA entry; the 2026-10-01 line that says `native_threads: int = 1` points to it | contract doc | other pre-GA entries |
| `changelog.d/engine-threads-default.md` | new fragment | "Changelog fragments" | other fragments |

Compatibility-contract entry (draft): "Pre-GA default change (ENGINE-THREADS-DEFAULT, 2026-11-xx).
`run_pipeline(..., native_threads: int | None = None)`: `None` uses the usable cores
(`detect_usable_cpus`, capped at 1024; 1 if detection fails). Explicit values are unchanged.
Output data does not depend on the thread count. Default runs now read lazy sources with Arrow
threads and record `native_thread_clamp` and `native_threads_source` in
`quality_metrics.auto_chunk`. Re-pin checklist: the platform passes its own thread grant; check
any platform call that omits `native_threads`."

Changelog fragment: "Changed: `run_pipeline` uses the usable CPU cores for native kernels by
default instead of one thread. Pass `native_threads=1` for the old behavior. Output is the same."

### Failure modes (S3)

- FM1 A thread-dependent byte (Arrow CSV inference, chunk order). Test 6 on lazy CSV and Parquet.
- FM2 An unreadable cgroup makes default runs fail. Fallback to 1, recorded, test 3.
- FM3 More memory from threads in a memory-capped isolated child (thread stacks, Arrow read
  buffers). Rust caps at 4 threads; RSS is reported in the PR; the isolated suite runs in T1.
- FM4 Host-dependent run records: `quality_metrics.auto_chunk.native_threads` now differs by host
  for library callers, as it already does for the CLI. Stated in the contract entry.

## S4. DATE-SHIFT-FORMAT (engine)

### Every place that tolerates a missing format today

| Site | What it does now | After S4 |
|---|---|---|
| `execution/_strategies/_date_shift.py:145` | `cfg.get("date_format") or _detect_format(col)` | no detection. A missing format is allowed only for an already-typed datetime column (declared casting); an object or string column without one raises a registered runtime error, a backstop behind the compile check |
| `execution/_strategies/_date_shift.py:305` | `shifted.astype(str)` when there is no format | kept only for the declared-casting typed column |
| `execution/_planner.py:416-431` | `date_shift_requires_explicit_format` chunk decline | deleted (unreachable); its tests move to the compile refusal |
| `execution/native/_requirements.py:384-402` | `format_detect` prepass | deleted |
| `execution/native/_requirements.py:577-582` | comment: a format-less date_shift is still native with a prepass | rewritten |
| `execution/native/_operator_config_rejections.py:158-164` | `date_shift_requires_date_format` native decline | kept for the declared-casting case, docstring updated |
| `execution/native/_capabilities.py:207`, `execution/physical/_shadow_bindings.py:289`, `execution/out_of_core/_mask_group_c.py:58` | comments on format detection | updated |
| `transforms/date_shift.py` docstring | lists date_shift as a `_detect_format` user | updated; `_detect_format` stays for `bucket_perturb` and `text_mask` |

### The refusal

- New `check_date_shift_date_format(config)` in `src/decoy_engine/plan/checks/_date_shift_format.py`,
  registered in `plan/_compile.py` with the other config-only checks (both compile branches and
  `run_config_only_checks`), so it runs before any profile or read.
- It refuses a `date_shift` column, top level or a `nested` child (`nested_children`, as
  `_checks_date_shift.py:117-129` does), whose `provider_config.date_format` is missing, `None`,
  not a `str`, or blank after strip.
- Exemption: a column with a declared-casting contract. `_checks_declared_casting.py:221` refuses
  `date_format` on such a column ("declare the format once"), so the contract's `parse_format`
  owns it. The check uses the same contract lookup the declared-casting check uses, not a copy.
- Reason: `plan.DATE_SHIFT_DATE_FORMAT_REQUIRED` (`date_shift_date_format_required`), registered
  in `reasons/plan/`. Message: the table and column names (config identifiers, never a cell
  value) and the fix, "add provider_config.date_format, for example %Y-%m-%d". Path
  `tables[i].columns[j].provider_config.date_format`.

Established solutions: pandas made the same move in PDEP-4: one format per column, no silent
switching, and an explicit `format=` is the documented way to parse consistently
([PDEP-4](https://pandas.pydata.org/pdeps/0004-consistent-to-datetime-parsing.html)). The engine
already requires a format for `date_preserve` (`transforms/date_preserve.py:101-105`); S4 applies
the same rule to the whole column.

### Shipped engine configs that would now be refused, and their update

| Item | Today | Update in S4 |
|---|---|---|
| 10 disguise rules: `src/decoy_engine/disguises/{ccpa,cpni,default,ferpa,gdpr,glba,hipaa,pc,pci,sox}.yaml`, one rule each | `detectors: [iso_date, us_date, eu_date]`, `mask: date_shift`, `params: {jitter_days: N}`, no format | split each into three rules, one detector each, with `date_format` `%Y-%m-%d`, `%m/%d/%Y`, `%d/%m/%Y`; `jitter_days` as decided in owner question 1; the builder checks that `FieldRule` validation and `expected_field_groups` accept the split |
| `src/decoy_engine/profiling/recommendations.py`, the `iso_date`, `us_date`, `eu_date` descriptors | `default=("date_shift", {"jitter_days": 15})`; `starter` `provider_config={"min_days": -365, "max_days": 365}` for `iso_date` and `us_date` | add the detector's `date_format` to `default` and `starter`, so the public `profiling.starter_config` builds configs that compile; re-baseline `tests/fixtures/scan_multi/default_strategy_by_detector_base.json` |
| `testflight/jobs/a_healthcare_claims/manifest.yaml` (`dob`) | no format | add the format the fixture data uses (the builder reads the generator) |
| `testflight/jobs/b_retail_m2m/manifest.yaml` (`signup_date`) | no format | same; the nightly testflight goes red without it |
| `examples/` | no `date_shift` | none |
| Docs: `docs/strategies.md` (about line 253, "When no date format is detected..."), `docs/execution-backends.md`, `docs/reasons.md`, `docs/qa/07-mask-dates-and-numbers.md`, `docs/quality/mutation-ledgers/execution_planner.md` | describe detection | describe the requirement |
| Test fixtures | 18 test files use `date_shift` with no `date_format` anywhere in the file (grep at base; more files mix both) | add the format; tests whose subject is detection become refusal tests or are deleted with the code |

The strategy wizard option already defaults `date_format` to `%Y-%m-%d`
(`_strategies/_date_shift.py:100`); the builder confirms a wizard-written config carries it.

### CLI follow-up slice C1 (CLI repo, not engine work)

`decoy init` and `decoy scan` write date_shift columns with no format, and two templates ship
without one (CLI `origin/main` 4564b745):

- `src/decoy/cli/_init_inference.py` (`iso_date`, `us_date`) and
  `src/decoy/cli/project/_columns.py:94-97`: write `date_format` by detector.
- `src/decoy/templates/hipaa.yaml` (`dob`, `admission_date`, `discharge_date`) and
  `src/decoy/templates/pci.yaml` (`transaction_date`): add `date_format: "%Y-%m-%d"`.
- Their tests and docs.

C1 is forward-safe (the format is accepted today), so it merges first, and it must merge before
the CLI re-pins to the engine release that carries S4. Inbox line: DATE-SHIFT-FORMAT-CLI.

### Acceptance tests (S4)

New `tests/unit/plan/checks/test_date_shift_format.py`:

1. `test_missing_format_refused`: missing, `None`, `""`, `"   "`, `5`, `True` each raise
   `PlanCompileError` with `date_shift_date_format_required` and the path, from `compile_plan`
   and from `run_config_only_checks`.
2. `test_refused_before_read`: `run_pipeline` with a `source_loader` that records calls: the
   loader is never called and nothing is staged.
3. `test_nested_child_refused`.
4. `test_declared_casting_column_exempt`: a declared date contract with `parse_format` and a
   date_shift column with no `date_format` compiles and runs.
5. `test_message_value_free`: the message carries no cell value; `__cause__` and `__context__`
   are None.
6. `test_reason_registered`: the code is in the reason registry and the release baseline.
7. `test_shipped_configs_compile`: each disguise rule's mask config (checked by the same function,
   since the expansion lives outside the engine), `starter_config` output for each date detector,
   and both testflight manifests pass the check.
8. `test_handler_guard`: the date_shift handler called directly on a string column with no format
   raises the registered runtime error, not a detection.

Rewritten, not weakened: `test_execution_planner.py:630`, `test_planner_mutation_kills.py:165,182`
and `test_chunked_date_shift_admission.py:486` assert the compile refusal instead of the planner
decline.

Red-first: tests 1, 2, 3, 6, 7 and 8 are red on base. Test 4 passes on base and pins the exempt
case.

### Mutations (S4)

1. Treat a blank string as present: test 1 red.
2. Skip nested children: test 3 red.
3. Drop the declared-casting exemption: test 4 red.
4. Register the check in one compile branch only: the `run_config_only_checks` half of test 1 red.
5. Restore `_detect_format` in the handler: test 8 red.

### Placement (S4)

| File | Change | Directory and CODEMAP line | Sits beside |
|---|---|---|---|
| `src/decoy_engine/plan/checks/_date_shift_format.py` | new check | `plan/checks/` ("Plan compile and checks": new checks in `plan/checks/_<topic>.py`; 8 files today) | `_checks_date_shift.py` (older check, stays) |
| `src/decoy_engine/plan/_compile.py` | register the check | `plan/` | other config-only checks |
| `src/decoy_engine/reasons/plan/_part1.py` (or the part with room) | new reason | `reasons/plan/` | `DATE_SHIFT_GROUP_BY_UNSUPPORTED_IN_NESTED` |
| the tolerance sites in the table above | delete or guard | existing files | |
| disguises, recommendations, testflight, docs, fixtures | as listed | existing files | |
| `tests/unit/plan/checks/test_date_shift_format.py` | new | `tests/unit/plan/` | `test_checks_date_shift.py` |
| `changelog.d/date-shift-format-required.md` | new fragment | "Changelog fragments" | other fragments |
| `docs/compatibility-contract.md` | dated pre-GA entry | contract doc | other pre-GA entries |

Choke point: the compile check is the one place the rule lives. The runtime guard in the handler
is a backstop with its own reason and test (mutation 5), not a second copy of the rule.

Changelog fragment: "Breaking: a `date_shift` column without `provider_config.date_format` is
refused at plan compile (`date_shift_date_format_required`). Add the column's format, for example
`%Y-%m-%d`. The engine no longer guesses the format from a sample. Columns whose format comes from
a declared-casting contract are not affected."

### Failure modes (S4)

- FM1 A shipped config the list misses fails at run time for a user. Test 7 checks every shipped
  config; the full suite runs (shared-fixtures trigger).
- FM2 The declared-casting conflict: requiring a format the other check forbids. Test 4.
- FM3 A builder deletes a detection test without replacing what it guarded. The PR lists each
  deleted test with the test that now covers its case.
- FM4 The CLI re-pins before C1 merges, and `decoy init` output stops compiling. C1 merges first;
  the CLI re-pin checklist gets a line.
- FM5 Reason baselines (`tests/fixtures/f29/*`, `tests/sentry/baselines/f29-*`) drift. Updated in
  the same commit as the reason, by their own regenerator.

## Enumerations

From the code at 92152f328.

### Routes

- windowed_date: the mask strategy handler (`execution/_strategies/_windowed_date.py:79`, used by
  full_frame, sequential and the chunked pandas adapter), the generation stream
  (`generation/_column_streams.py:83-91`), grouped generation
  (`generation/_grouped_windowed_generators.py:111`), and the native protocol reproduction
  (`execution/native/protocol/providers_mask.py:318`, test-side only). All three runtime callers
  pass through `apply_windowed_date`.
- `native_threads`: `_pipeline_context.py:433` into the chunked native lane,
  `_chunked_input.py:388` (lazy Arrow reads), `_pipeline_auto_chunk.py:583-589` (record),
  `_isolated_run.py` (forwarded kwargs). Out-of-core sizes DuckDB threads on its own
  (`out_of_core/_duckdb.py::_threads_for_memory_limit`) and does not read it.
- Missing date_shift format: the S4 site table (handler, planner decline, native prepass, native
  rejection, comments).

### Exit paths

- S1 fast path, success: returns the list; local buffers and the seed copy go out of scope.
- S1 fast path, exception or anomaly: buffers are discarded, the reference loop reruns, and the
  `except BaseException: del seed` shape deletes the seed copy on its error exit.
- S2 to S4: N/A, they open no file and hold no state.

### FK shapes

N/A: no slice reads or writes a key.

### Fields

- `quality_metrics["auto_chunk"]["native_threads_source"]` (S3, new, closed set of three words).
- `quality_metrics["auto_chunk"]["native_threads"]` and `native_thread_clamp` (S3, existing; now
  set on default runs).
- No dataclass field of a public result type changes.

### Output surfaces

- S1 and S2: output column values and `WindowedDateError` messages.
- S3: the run record (`quality_metrics`).
- S4: the `PlanCompileError` message and path, `docs/reasons.md`, the reason baselines, and the
  runtime guard's error message.
- No slice adds a log line, stdout or stderr output.

## Reuse inventory

- `DeriveContext.derive_sources` (`determinism/_derive.py:241`): the batched derive for S1.
- `derive_index_batch`, `_compiled_index_kernel`, `_validated_index_array`
  (`generation/pool/_sampler.py`, `execution/native/_crypto_ext.py`, `_crypto_reference.py`):
  the S2 offset kernel, exported, not copied.
- `detect_usable_cpus` and `MAX_NATIVE_THREADS` (`execution/pipeline/_host.py`): S3.
- `require_lane_knobs` (`_pipeline_auto_chunk.py`): S3 keeps it as the validator.
- Reason registry (`reasons/plan/`), the registry sentry and the f29 baselines: S4.
- `nested_children` and the declared-casting contract lookup (`plan/_checks_declared_casting.py`):
  S4.
- Sentries that must stay green: module size (`tests/sentry/test_module_size.py`; S1 keeps the
  module under 600), the secret-material census, the public import boundary, the plan/ and
  transforms/ fan-out freezes, the physical-seam sentry (no slice adds an `execution/` seam).
- New machinery: one check module (S4) and one resolver (S3). Each is a single function at the
  existing choke point.

## Frozen contracts touched

| Contract | Slice | Kind |
|---|---|---|
| `run_pipeline` signature (`test_r3_public_signature_freeze.py:56`, `docs/compatibility-contract.md:869`) | S3 | breaking default change (pre-GA), additive `None` |
| `quality_metrics.auto_chunk` keys | S3 | additive (`native_threads_source`) |
| windowed_date output bytes, draw-site catalogue, provider goldens | S2 | breaking (output-changing), changelog'd |
| Plan compile refusals and the reason manifest | S4 | breaking (new refusal), additive reason |
| Shipped disguises, `starter_config` output, recommendations fixture | S4 | breaking content change |
| `generation.pool` public names | S2 | additive |
| `SEED_PROTOCOL_VERSION` | S2 | unchanged (7) |

## Pre-mortem

Assume the batch shipped and went wrong. The likely causes, and what stops each:

- S1 merged with a one-row difference on an input outside the corpus (a pandas ISO8601 parse that
  accepts a string the regex also accepts but reads differently). Stopped by the property test,
  the fall-back rule on any NaT, and the per-cell regex kept in front of the vector parse.
- S2 skipped because S1 looked fast enough, and F1 closed at 2.5x. Stopped by the data gate in
  the benchmark protocol; a skip is recorded with its numbers.
- S3 made a customer's container run out of memory with more threads. Stopped by the Rust cap of
  4, the RSS check in the PR and the explicit `native_threads=1` escape.
- S4 broke the nightly testflight or a CLI project because one shipped config was missed. Stopped
  by S4 test 7, the full suite, and C1 merging before the CLI re-pin.
- The disguise split changed how the platform expands rules. Stopped by keeping rule ids stable
  where the expander keys on them; the builder checks the expander's key before splitting and
  reports if a split changes it.

## Class table

| # | Class | Closing structure | Proving test | Mutation that must turn it red |
|---|---|---|---|---|
| 1 | Value-bearing output | S1 and S2: every error is raised by the unchanged reference loop, outside the `except` block, so no anchor value reaches the message or the chain. S4: the refusal names config identifiers only. S3: `native_threads_source` is a closed three-word set | S1 test 2 (`str`, `__cause__`, `__context__`), S4 test 5 | S1 mutation 5 (raise from the fast path); format the column value into the S4 message: test 5 red |
| 2 | Cleanup missing on an exit path | S1: the seed and `DeriveContext` are deleted on the exception path (existing `del seed` shape), covered by the secret-material census sentry. S2 to S4: N/A, no resource is opened | the census sentry on `transforms/windowed_date.py` | drop the `del` on the fast path: the sentry red |
| 3 | State machine and concurrency | S3: thread count changes scheduling only; Rust kernels are proved thread-count independent in-crate. S1, S2, S4: N/A, pure functions | S3 test 6 (default against 1 thread, resident, lazy CSV, lazy Parquet) | S3 mutation 1 hides the default; a thread-dependent Arrow read turns test 6 red |
| 4 | Route parity and silent fallback | S1: one entry point (`apply_windowed_date`) for mask, generation and grouped callers; the fast path falls back to the reference only by rerunning it, never by a different answer. S2: mask and generation share one derivation. S4: one compile check before any route; the planner decline and native prepass are deleted, not left as a second route. S3: the fallback to 1 is recorded, not silent | S1 tests 1, 3, 5; S2 test 6; S4 tests 1, 2, 8; S3 test 3 | S1 mutation 5; S4 mutations 4 and 5; S3 mutation 2 |
| 5 | Referential integrity | N/A: no FK is read or written by any slice | | |
| 6 | Untrusted producer | S4: config is the untrusted input; a missing, blank or non-string format is refused at the boundary with one registered reason. S1: anchor cells outside the admitted shapes go to the reference loop, which keeps today's validation | S4 test 1 (missing, `None`, `""`, blank, int, bool); S1 error-parity corpus | S4 mutation 1 (blank accepted) |
| 7 | TOCTOU on a path | N/A: no slice opens or checks a path | | |
| 8 | Weak tests and overclaimed evidence | S1 pins the base digest from 92152f328 and adds a negative test that S2 is not byte-identical; red-first lists label which tests pass on base; benchmark claims need the interleaved baseline and the variance rule; S2 distribution bounds are fixed and never edited to pass | step 0 tests; the benchmark record | edit a golden in S1: stop rule; loosen the chi-square bound: review refusal |
| 9 | Behavior-preserving refactor drift | S1 moves the loop unchanged into `_apply_reference` and proves the fast path against it on the corpus and by property test | S1 tests 1 and 5, the unchanged goldens list | S1 mutations 1 to 8 |
| 10 | Frozen contract drift | S2: draw-site entry, provider version and goldens move together with a Breaking changelog line. S3: the freeze row and the contract entry move in the same commit. S4: the reason is registered through the reason registry and baselines; changelog and contract entry | S3 test 7; S4 test 6; the catalogue pinned test in S2 | spell the S4 code as a literal: the registry sentry red; change the S3 default without the freeze row: test 7 red |

## Size

- S1: one source file (about +100 lines), three new test files, one bench file, one record. No
  public name.
- S2: four source files, two public names in `generation.pool`, one test file, re-baselines, one
  fragment, one record update.
- S3: four source files, one helper in `execution.pipeline` (not root-exported), one test file,
  a contract entry, a fragment.
- S4: one new check module, one reason, about eight source files edited (mostly deletions), ten
  disguise YAMLs, two testflight manifests, docs, 18 or more test files, a contract entry, a
  fragment.

A build well past these sizes stops and reports before review.

## Owner questions

1. The disguise rules pass `jitter_days: N`, but the date_shift handler reads only `min_days` and
   `max_days` (default -365 to 365). So the disguises can shift dates by up to a year, not the
   plus or minus N days their `why` text promises (HIPAA: "plus/minus 30d"). Fix it in S4 while
   those lines are open (`min_days: -N, max_days: N`; output changes, before freeze), or as its
   own row? Recommendation: fix it in S4 and call it out in the same changelog fragment.
2. `bucket_perturb` also detects a missing `date_format` from a whole-series sample
   (`transforms/bucket_perturb.py:165`), the same class S4 removes from date_shift. Apply the same
   requirement before freeze, or leave it? Recommendation: an inbox line now
   (BUCKET-PERTURB-FORMAT), decided before freeze.

Neither question blocks S1, S2 or S3. Question 1 only changes the S4 disguise edit.
