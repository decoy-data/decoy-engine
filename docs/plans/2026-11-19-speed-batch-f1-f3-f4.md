# Speed batch: windowed_date batching, engine thread default, date_shift format

Status: plan

Rules consulted: 00-universal, risk-and-exceptions, development-loop (Proportion, PLAN),
profiles/local-operations, performance, testing (Test depth), api-and-compatibility,
cross-cutting-concerns, proportionality, catalogs/recurring-defects, CODEMAP "Where Things Go"

Base: engine `origin/main` 75fba3d855d71e3980a62afc3ce7f1187b72073d. Source: record
`docs/records/2026-11-19-engine-speed-and-route-completeness.md` (branch
`docs/speed-route-completeness`), sections 2.3, 2.4, 5.2 (F1, F3, F4) and 10. Owner decisions of
2026-11-19: all three rows are 1.0 rows; F1 may change output bytes before GA if the change is
called out and changelog'd as output-changing; F4 requires the format (Q4: require, do not detect).

Rows: GEN-WINDOWED-BATCH (F1), ENGINE-THREADS-DEFAULT (F3), DATE-SHIFT-FORMAT (F4). Engine only,
plus one CLI follow-up slice and one platform follow-up row for F4.

Revision 2 (Dennis plan review round 1 on b1cd9bd67, GO-WITH-FIXES). The response to each finding
is at the end of this plan.

## Decided (2026-11-19, after review round 1)

- D1. date_shift honours `jitter_days` before freeze. `jitter_days: N` means the window
  `[-N, N]`. One resolver serves every route (slice S4a).
- D2. `bucket_perturb` format guessing (`transforms/bucket_perturb.py:165`) is its own inbox row,
  BUCKET-PERTURB-FORMAT. It is out of scope here.

## Slices

| Slice | Row | Size | Risk | Depends on | Output bytes |
|---|---|---|---|---|---|
| S1 `feat/gen-windowed-batch` | F1 part 1: proof step, batched derive, vectorized parse, shift and format | 1 day | R1 | none | unchanged (proved) |
| S2 `feat/gen-windowed-offsets` | F1 part 2: offsets from the batched index kernel | 1 day | R2 | S1, and the S1 benchmark gate | change, called out |
| S3 `feat/engine-threads-default` | F3 | 1 day | R2 | none | unchanged (proved per route) |
| S4a `feat/date-shift-jitter` | F4 part 1: `jitter_days` resolver on every route (D1) | 1 day | R2 | none | change for configs with `jitter_days`, called out |
| S4b `feat/date-shift-format-required` | F4 part 2: refuse a missing format; detected format in the starter | 1 day | R2 | S4a (same files) | refusal added |
| C1 (CLI repo) `feat/date-shift-format-cli` | F4 CLI follow-up | 0.5 day | R1 | none; must merge before the CLI re-pins to the engine release that carries S4b | none |
| P1 (platform, parked) PLATFORM-DISGUISE-DATE-FORMAT | F4 platform follow-up row, not built in this batch | 0.5 day | R1 | S4b | none |

S1, S3 and S4a touch different files and can build in parallel in separate worktrees (never two
writers in one worktree). S3, S4a and S4b each add a `docs/compatibility-contract.md` entry and a
`changelog.d/` fragment: keep all on merge.

Gates (gate roster): R1 slices get Codex. R2 slices get Dennis and Codex. Test depth per
`testing.md`: T0 per edit, T1 impact set per commit, T2 at each gate. Full-suite triggers: S2
(output bytes and goldens move), S3 (frozen public signature), S4a (output change on a frozen
contract), S4b (a new refusal, a new registered reason, shared fixtures). S1 has no trigger.

## Pinned guarantees and non-goals

- S1: `apply_windowed_date` returns exactly the same list, and raises exactly the same exception
  type and message, as `origin/main` for every input in the parity corpus and the property test.
  It emits no warning. It is faster.
- S2: `windowed_date` output dates change for the same seed (mask and generate kinds both). Per
  row, the date stays inside `[anchor + min_days, anchor + max_days]`, null anchors stay null, the
  output stays keyed on the global row number (partitionable), and it stays deterministic across
  runs, batch sizes, routes and thread counts.
- S3: `run_pipeline()` with no `native_threads` uses the usable cores (cgroup and affinity aware).
  On every route that receives the count, output data bytes are identical to `native_threads=1`.
- S4a: a date_shift column with `jitter_days: N` shifts inside `[-N, N]` on every route, with the
  same bytes as `min_days: -N, max_days: N`. `jitter_days` together with `min_days` or `max_days`
  is refused at compile.
- S4b: every `date_shift` column without a usable `provider_config.date_format` is refused at
  plan compile with one registered, value-free reason, before any source is read. The only
  exemption is a top-level `date_shift` column whose own declared date contract supplies its
  parse format. A nested `date_shift` child never inherits a declared contract from its parent.
  Where the engine writes a date_shift suggestion from a scan, it writes the detected format
  only when every detector hit parses with that format under the runtime date_shift parser.

Non-goals: F2 (fitted sampler RNG), C2 (vectorizing sequence, reference and null streams), a Rust
date kernel, `bucket_perturb` (D2), `text_mask` per-span dates (a span is not a column, and
text_mask takes no `jitter_days`), other entry points' thread defaults (`run_mask_chunked`,
`run_sequential` keep `1`), platform code changes (parked; follow-up row P1 and re-pin lines).

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

The draw site is `mask.windowed_date` (`execution/native/_draw_sites_mask.py:344`, call site
`transforms/windowed_date.py::apply_windowed_date`), reproduced by `WindowedDateProvider`
(`execution/native/protocol/providers_mask.py:318`).

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

### F1 byte-identity expectation

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
  to a sha256 recorded from base 75fba3d855d71e3980a62afc3ce7f1187b72073d and written into the test as a literal. Passes on
  base and must still pass after S1. S2 changes this literal on purpose.

Step 0 also puts the stage profile (cProfile at 150k rows, same corpus) in the S1 PR body, so the
unattributed half is named before code changes.

### Design

All changes are inside `transforms/windowed_date.py`. The current per-row loop stays inline in
`apply_windowed_date` as the reference path, unchanged. A fast path runs first:

1. Admission, by exact type and never by `isinstance`:
   - a batch whose non-null cells are all `type(v) is str`;
   - all `type(v) is datetime.date` (dob anchors, masked `date32` cells);
   - all `type(v) is datetime.datetime` with `tzinfo is None`, or all `type(v) is pd.Timestamp`
     with `tz is None` (fitted anchors);
   - a naive `datetime64[ns]` Series.
   Nulls are exactly `_is_null_cell` (no `pd.isna`, so `""` and `"NaT"` stay non-null). Mixed
   types, subclasses, tz-aware values and anything else take the reference path for the whole
   batch. A `positions` list whose length differs from the batch takes the reference path, which
   raises its own `zip(strict=True)` `ValueError`.
2. `str` cells: `_ISO_ANCHOR.fullmatch` per cell (the existing pattern is already bounded by
   `\A` and `\Z`, so this is byte-for-byte equivalent and follows the anchored-validation rule), then
   `pd.to_datetime(values, format="ISO8601")` on the non-null cells. Typed cells convert with
   `np.array(..., dtype="datetime64[ns]")`.
3. Row numbers for non-null rows (from `positions` or `range(row_offset, ...)`), derived with one
   `DeriveContext` and `derive_sources(namespace, (i.to_bytes(8, "big") for i in rows))`. No
   context is built for an all-null batch, as today.
4. Per non-null row: `_sample_offset(np.random.default_rng(seed_bytes_to_int(d[:8])), ...)`.
   `seed_bytes_to_int` (`determinism/_seeds.py:34`) gives the same integer as the base
   `int.from_bytes(d[:8], "big")`, so bytes do not move, and `tests/.../test_rng_construction.py`
   stays green with no allowlist entry. This draw loop is in the body of `apply_windowed_date`,
   so the draw-site entry's call site, the draw-site inventory and the pinned catalogue hash do
   not move. The vector parse and format are helpers that draw nothing.
5. Overflow guard before any vector arithmetic: offsets and results are checked in integer days.
   If any `|offset|` exceeds 106,751 days (the ns `timedelta64` range), or any result falls
   outside `SUPPORTED_MIN`/`SUPPORTED_MAX`, the batch takes the reference path. NumPy datetime
   addition wraps silently, so this check comes first, not after.
6. `shifted = parsed + offsets.astype("timedelta64[D]")`, then `shifted.dt.strftime(_DATE_FMT)`.
7. Assemble `list[str | None]` with `None` at null rows.

Error parity by construction: any `Exception` or anomaly in the fast path (a grammar miss, NaT,
an out-of-range anchor or result, overflow, a `to_bytes` overflow on a negative or too-large row
number) discards the fast-path work and reruns the batch through the reference path, which raises
the exact first error the old loop raised. The fallback catches `Exception`, not `BaseException`,
so `KeyboardInterrupt` and `SystemExit` propagate. The function is pure, so the rerun has no side
effects. The seed and the `DeriveContext` stay local and are deleted on the exception path (the
existing `except BaseException: del seed` shape, which re-raises; the secret-material census
sentry covers this module).

Time-boxed option (2 hours, keep only if the parity corpus stays identical): a cheaper exact
per-row Generator construction. Drop it if it needs numpy internals.

Established solutions: the batched keyed derive is the engine's own `derive_sources` (HMAC state
copied after the fixed prefix, stdlib `hmac.copy`), already used by date_shift. Vectorized date
arithmetic is pandas `to_datetime(format=...)` plus `Series.dt.strftime`. NumPy has no batch
constructor for many seeded Generators (numpy parallel-RNG docs; the documented pattern is
`SeedSequence.spawn`, which gives different streams), so an exact byte-preserving vectorization of
the per-row PCG64 draw would mean reimplementing SeedSequence, PCG64 and the bounded-integer
method by hand. Rejected as hand-rolled machinery; S2 changes the derivation instead.

### Parity corpus (committed, `tests/unit/generation/_windowed_date_corpus.py`)

- 2,000 ISO dates from `np.random.default_rng(0)` over 1990 to 2030, 5% nulls mixed as `None`,
  `float("nan")`, `pd.NA`, `pd.NaT`.
- Edge anchors: date only; `T` and space separators; minutes only; seconds; fractions of 1 to 9
  digits; `1700-01-01` and `2200-12-31` (with windows that stay in range); pre-1970 anchors with a
  time of day; `2000-02-29`, `1900-02-28`, `2024-02-29`.
- Windows: `uniform`, `early`, `late`; `min_days == max_days`; negative windows; `-30..90`;
  windows past the ns `timedelta` range (`max_days = 106,752` and `200,000`).
- Row numbering: `row_offset` 0, 65,536, 2^32, `2^63 - 1 - n`; a non-contiguous `positions` list;
  negative `positions`; a `positions` list one shorter and one longer than the batch.
- Seeds: 8 bytes and 32 bytes. Namespaces: normal, and `""` with an all-null batch and with a
  non-null batch.
- Anchor shapes: object `str`, `datetime64[ns]` Series, object `datetime.date`, object naive
  `datetime.datetime`, object naive `pd.Timestamp`, a `date` subclass, a mixed `str` and `date`
  batch.
- Error cases, each at a non-first row after good rows: bad grammar, `""`, `"NaT"`, a zone in
  the string, a tz-aware Timestamp, an int cell, an out-of-range anchor, a result past
  `SUPPORTED_MAX`, a row number past 2^64, a negative position.

### Acceptance tests (S1)

In `test_windowed_date_batch_parity.py`, besides step 0. "Reference" below means the base loop,
kept as a test oracle copied verbatim from 75fba3d855d71e3980a62afc3ce7f1187b72073d into the corpus module.

1. `test_fast_path_equals_reference_on_corpus`: for every corpus case, `apply_windowed_date`
   output equals the reference output, list for list.
2. `test_error_parity`: for every error case, same exception type, same `str(exc)`, and
   `__cause__ is None and __context__ is None` (recurring defect 3). The positions length
   mismatch raises the same `ValueError`.
3. `test_fast_path_is_taken`: a spy on `_parse_anchor` (called only by the reference path) is not
   called for each admitted shape, and is called for a `date` subclass batch and a mixed batch.
4. `test_batch_boundaries_do_not_change_output`: the generation stream at batch sizes 1, 7,
   32,768 and 65,536 gives the same column.
5. `test_fast_path_equals_reference_property` (Hypothesis, fixed seed and database): generated
   anchor lists (ISO strings in and out of the grammar, nulls, typed cells), windows, offsets and
   `positions`; same list or same error. A failing example is pinned as a regular case.
6. `test_fast_path_emits_no_warning`: run the corpus inside `warnings.catch_warnings(record=True)`
   with `warnings.simplefilter("always")`, then assert the recorded list is empty. Warnings stay
   warnings during the call, so this test does not change control flow or turn a warning into the
   fast-path fallback exception it is meant to detect.
7. `test_interrupt_propagates`: a `KeyboardInterrupt` raised inside the fast path (patched
   helper) propagates and does not trigger the reference rerun.

Must pass unchanged: `tests/native/test_determinism_goldens.py::TestWindowedDateGolden`,
`tests/native/test_draw_site_providers_golden.py`, `tests/native/test_draw_sites_catalogue_pinned.py`,
`test_rng_construction.py`, `tests/unit/generation/test_fr1_windowed_date.py`,
`tests/unit/execution/test_dgrn_windowed_date.py`, `tests/unit/generation/test_gen_window.py`,
`tests/native/test_c8_iii_d2_native_positional_when.py`. A failure in any of them is a stop and a
report, never an edit.

Red-first: the step 0 tests pass on base (they pin the premise and the digest). Test 3 is red on
base (the spy is called for every shape). Test 7 is red against a fallback that catches
`BaseException`. Tests 1, 2, 4, 5 and 6 are written before the fast path and run green against
base, so a broken fast path turns them red.

### Mutations (S1, on the final head)

1. Pass a constant namespace to `derive_sources`: digest and parity red.
2. Row number off by one (`row_offset + 1`): red.
3. Ignore `positions`: the `when:` positional case red.
4. Drop the overflow guard: the past-range window cases red.
5. Re-raise in the fast path instead of falling back: error parity red (message differs).
6. Use `pd.isna` for the null mask: the `""` and `"NaT"` error cases red.
7. `_DATE_FMT` with a time part: red.
8. Skip the second draw for `early`: red.
9. Admit by `isinstance` instead of exact type: the `date` subclass case red.
10. Catch `BaseException` in the fallback: test 7 red.
11. Emit a warning in the fast path: test 6 records it and turns red.

### Placement (S1)

| File | Change | Directory and CODEMAP line | Sits beside |
|---|---|---|---|
| `src/decoy_engine/transforms/windowed_date.py` | fast path and two draw-free helpers; reference loop stays inline | `transforms/` ("Transforms", by transform) | same file, 343 lines today, expect about 450 |
| `tests/unit/generation/test_windowed_date_batch_parity.py` | new | `tests/unit/generation/` ("Generation" tests) | `test_fr1_windowed_date.py` |
| `tests/unit/generation/_windowed_date_corpus.py` | new, holds the corpus and the reference oracle, shared with S2 | `tests/unit/generation/` | same |
| `tests/perf/test_windowed_date_bench.py` | new, `-m benchmark` | `tests/` row: `perf/` | `test_f4a_gen_capacity.py` |

No new public name. No CODEMAP change. Choke point: `apply_windowed_date` is already the one entry
point for all three callers; the draw-site golden fails if a caller bypasses it.

## F1 benchmark protocol (S1 and S2)

Per `performance.md`: workload, baseline, warmup, variance and tail, recorded before and after.

- Node: the Dell WSL2 Linux node through `vm-run engine` (`VMRUN_LINUX=1`), one slot, node idle
  per `node-watch` before each run. The same node and slot for baseline and candidate. The
  companion is installed (S2 also runs once without it).
- Baseline: `origin/main` 75fba3d855d71e3980a62afc3ce7f1187b72073d measured in the same session, interleaved
  (base, candidate, base, candidate) to cancel drift. No number from the record is the baseline.
- Workload A, column micro-benchmark (`tests/perf/test_windowed_date_bench.py`): 200,000 rows,
  5% nulls, each of `uniform`, `early`, `late`, window `-30..90`, in two anchor shapes: ISO
  strings and object `datetime.date` cells (the dob and masked-`date32` shape). Fresh process per
  configuration. One untimed warm call, then 7 timed calls. Report median, min, max and
  interquartile range in us/row. Scoped as a micro-benchmark; workload B is the end-to-end claim.
- Workload B, end to end: `tests/perf/test_f4a_gen_capacity.py` pure-generation 1M tier
  (1M `orders` plus 100k `people`, batch 32,768, 1024 MB budget), 3 runs each. Report wall
  seconds, rows/s and peak RSS (`wait4`). The record's 1M figure (about 15.0k rows/s on a 4-core
  host) is context only. The builder records which anchor shape this workload feeds windowed_date.
- Workload C, share: cProfile or py-spy at 150k rows (the record's profile size): the
  `windowed_date` share of pure-generation time, before and after.
- Variance rule: if `(max - min) / median` exceeds 10% on workload A, or the 3 runs of workload B
  spread more than 10%, recheck the node and rerun once. Report the max as the tail, not only the
  median.
- Correctness guard in every run: the workload B output digest is equal across reruns; for S1 it
  also equals the base digest.
- Resource budget: workload B peak RSS at most base +10% and under the F4a 500 MB ceiling.
- Targets. S1: workload A at most 45 us/row (from about 132) for both anchor shapes; workload B
  at least 2x base rows/s. S2: workload A at most 10 us/row with the companion and at most 20
  without it; workload B at least 4x base.
- Results go to `docs/records/2026-11-xx-gen-windowed-batch-bench.md` (Status: record) with the
  raw JSON under `docs/records/evidence/`.

S2 decision gate (decided by data, recorded in the S1 record): run S2 when, after S1,
`windowed_date` is still over 50% of pure-generation time (workload C) or workload B is under
40k rows/s. Expectation: S2 runs. The per-row PCG64 draw alone (about 30 us) is about three times
the cost of all other generation columns together (about 9 us/row, from the record's 87% share).

## S2. GEN-WINDOWED-BATCH part 2 (output-changing, before freeze)

### Design

Replace the per-row draw (S1 step 4) on both paths with the pool sampler's index kernel, reached
through the same lazy loader the sampler uses (`_compiled_index_kernel()`, with the reference
kernel as the byte-identical fallback) and checked with the sampler's `_validated_index_array`.
Reuse them, do not copy them: export the two helpers from `generation/pool` under public names
(they are private today; recurring defect 6).

- The draw index is part of the source, not the namespace. For global row number `r` and draw
  `k` (0 for the first draw, 1 for the second), the source is the int64 `2 * r + k`, under the
  column's own namespace unchanged. The map `(r, k) -> 2r + k` is injective, so no two
  (row, draw) pairs share a source, and a column named `x/draw2` cannot collide with anything,
  because no namespace is built from a suffix.
- Domain check before the call, in `windowed_date.py`: every `r` must satisfy
  `0 <= r < 2**62`, so `2r + 1` fits int64 and stays in the range where `_encode_int` (signed
  big-endian body) gives the same bytes on the compiled and the reference kernel. A negative or
  too-large row number raises a registered value-free error
  (`runtime.WINDOWED_DATE_ROW_NUMBER_OUT_OF_RANGE`), raised outside any `except` block.
- `uniform`: `offset = min_days + idx(k=0)`. `early` and `late`: `min` or `max` of the k=0 and
  k=1 offsets, two calls over the same rows. This keeps the "min or max of two uniform draws"
  distribution the module documents.
- `pool_size = span + 1`. `span == 0`: no call, `offset = min_days` (today's rule).

`SEED_PROTOCOL_VERSION` stays 7. The reason: the engine is pre-GA, and a bump would rekey every
keyed column and every vault, far more than this one site needs. The derive envelope itself does
not change; the change is scoped to the `mask.windowed_date` site and is recorded through its
`provider_version`, the draw-site entry and the Breaking changelog line. This decision is written
into the S2 PR and the changelog fragment.

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

Changed (windowed_date offsets, GEN-WINDOWED-BATCH, 2026-11-xx): windowed_date now draws each
row's offset from the keyed index derivation that pooled sampling uses, in one batch per
column, instead of a separate numpy generator per row. It is about N times faster (see the
benchmark record). Dates stay inside the configured window, null anchors stay null, and output
stays the same across runs, batch sizes and routes. Output from earlier releases does not
match: regenerate stored windowed_date output. Global row numbers must now be below 2^62
(before: below 2^64); a larger or negative row number raises
windowed_date_row_number_out_of_range. SEED_PROTOCOL_VERSION does not change: a bump
would rekey every keyed column and vault before GA, and only this site moves.
```

### Acceptance tests (S2)

New `tests/unit/generation/test_windowed_date_offsets.py`:

1. `test_offsets_in_window`: every non-null row's date minus its anchor is in
   `[min_days, max_days]`, for each distribution, over the corpus.
2. `test_distribution_shape`: 200k rows, `-30..90`. `uniform`: chi-square over the 121 bins,
   p > 0.001. `early`: mean offset below the window midpoint minus 15 days. `late`: above the
   midpoint plus 15 days. Fixed seed, fixed bounds, never edited to pass.
3. `test_compiled_equals_reference`: with the companion, compiled and reference kernels give the
   same offsets on the corpus, including `r = 2**62 - 1`.
4. `test_partitionable` (Hypothesis over split points): any split of the rows into chunks with
   their global row numbers gives the same column; the `positions` path gives each row the value
   of the ungated run.
5. `test_namespace_independence`: two columns with different namespaces differ in at least 99%
   of rows over 10k rows; a column named `x` and one named `x/draw2` differ in at least 99%.
6. `test_mask_and_generate_share_the_derivation`: the mask strategy and the generation stream
   give the same dates for the same anchors, seed, namespace and row numbers.
7. `test_row_number_domain`: `r = -1` and `r = 2**62` raise the registered error, value-free,
   with no `__cause__` or `__context__`.
8. The S1 error-parity cases that do not involve row numbers still raise the same errors. The
   S1 success case `row_offset = 2**63 - 1 - n` becomes an error in S2: the domain narrows from
   below 2^64 to below 2^62. The test asserts the new registered error for it, and the S2 PR
   names the change.

Red-first: tests 1, 2, 4 and 5 pass on S1 too (they pin properties). Tests 6 and 7, the new
provider golden and the re-baselined digest are red until the derivation lands.

### Mutations (S2)

1. `pool_size = span` (off by one): the window edge is never drawn, chi-square red.
2. The same source for both draws (`2r` for k=1): `early` and `late` collapse to `uniform`,
   test 2 red.
3. `min` and `max` swapped: test 2 red.
4. Local row number instead of global: test 4 red.
5. Skip `_validated_index_array`: the stub-kernel test (an index past `pool_size`) red.
6. Domain check bound `2**63`: test 7 red.

### Placement (S2)

| File | Change | Directory and CODEMAP line | Sits beside |
|---|---|---|---|
| `src/decoy_engine/transforms/windowed_date.py` | offsets from the index kernel, domain check | `transforms/` | same file |
| `src/decoy_engine/generation/pool/__init__.py`, `_sampler.py` | export the loader and validator under public names | `generation/pool/` ("Generation", pools) | `PoolSampler` |
| `src/decoy_engine/execution/native/_draw_sites_mask.py`, `protocol/providers_mask.py` | the site entry and provider | `execution/native/` | the other mask sites |
| `src/decoy_engine/reasons/runtime/` (the part with room) | `WINDOWED_DATE_ROW_NUMBER_OUT_OF_RANGE` | `reasons/runtime/` | other runtime reasons |
| `tests/unit/generation/test_windowed_date_offsets.py` | new | `tests/unit/generation/` | the S1 parity test |
| `docs/compatibility-contract.md` | record the pre-GA output and row-number-domain change | "Feature and contract docs" | other pre-GA entries |
| `changelog.d/gen-windowed-offsets.md` | new fragment | "Changelog fragments" | other fragments |

### Failure modes (F1)

- FM1 A fast path that differs subtly from the reference (a pandas parse rule, a null rule, a
  typed-cell conversion). Closed by full-corpus and property parity plus the pinned base digest.
- FM2 Error drift: a different first error, or a value in the message. Closed by the
  fall-back-to-reference rule and test 2.
- FM3 A builder edits a golden to pass in S1. Any golden edit in S1 is a stop.
- FM4 S2 claimed as byte-identical. The step 0 negative test shows it cannot be.
- FM5 Silent datetime overflow in the vector add. The integer-day guard runs before it; corpus
  cases past 106,751 days.
- FM6 Absurd windows (a span past 2^56 days) raise the coded `pool_size_overflow` in S2 instead
  of drawing. Value-free, and such windows already fail the date range. Accepted.
- FM7 Benchmark noise passed off as a win. Interleaved baseline, variance rule, max reported.
- FM8 The speed claim holds only for strings while real anchors are `date` objects. Typed-cell
  admission plus the `date` workload in workload A.
- FM9 Memory: the fast path holds one batch of anchors, digests and offsets (a few MB at 65,536
  rows). Workload B peak RSS is checked against base.

## S3. ENGINE-THREADS-DEFAULT

### Current behavior

`run_pipeline(native_threads: int = 1)` (`execution/_pipeline.py:140`). The CLI passes the usable
cores from the engine's own `detect_usable_cpus()` (CLI `src/decoy/_resources.py:114-120`).
`detect_usable_cpus()` (`execution/pipeline/_host.py:146`) is `max(1, min(affinity, floor(cgroup
quota)))`, cached per process, and raises `runtime.cpu_detection_failed` on an unreadable cgroup.
Rust clamps to `min(requested, host cores, 4)`. Thread count never changes output in-crate
(`thread_count_never_changes_output`, `docs/plans/2026-10-15-gap9-native-thread-grant.md:29`).
`ctx.native_threads` reaches every route listed in Enumerations, Routes. It also switches lazy
Parquet reads to Arrow threads (`execution/_chunked_input.py:388`); the lazy CSV and fixed-width
readers ignore `use_threads` (`profile/_lazy_csv.py:211`, `profile/_lazy_fixed_width.py:211`).
It stamps `native_thread_clamp` into `quality_metrics["auto_chunk"]` when above 1
(`_pipeline_auto_chunk.py:588`). The signature is frozen by
`tests/unit/execution/test_r3_public_signature_freeze.py:56` (`"1"`, `"int"`). The platform
grants its own thread count.

### Design

- `native_threads: int | None = None`. `None` means auto. An explicit int keeps today's
  validation (1 to `MAX_NATIVE_THREADS`, bool refused).
- One resolver, `native_threads_for_run(requested: int | None) -> RunThreads`, in
  `execution/pipeline/_host.py` beside `detect_usable_cpus`. The name does not shadow the
  companion's `_kernel.resolve_native_threads` used at `_host.py:184`. Auto is
  `min(detect_usable_cpus(), MAX_NATIVE_THREADS)`. If detection raises `cpu_detection_failed`,
  auto resolves to 1 with source `auto_fallback`: the default must not fail a run that works
  today, and no output byte depends on the count. The source is recorded, so the fallback is not
  silent. An explicit int never falls back.
- Called once, in `_pipeline_context` where the knobs are validated today
  (`_pipeline_context.py:260`). The context keeps `ctx.native_threads` and the closed
  `ctx.native_threads_source`; downstream executor signatures stay unchanged.
- Stamp the source after the selected executor returns in
  `execution/_pipeline_route_dispatch.py::execute_route`, the all-route result choke point. Do
  not use route-local `stamp_execution_metrics`. Acceptance test 7 forces every branch through
  the choke point using test 6's route parametrization. The field is additive and value-free.
- `run_pipeline_isolated` forwards kwargs unchanged; an omitted value resolves in the child,
  under the child's own cgroup and affinity.

Established solutions: Go 1.25 made `GOMAXPROCS` default to the cgroup CPU limit when it is lower
than the logical CPU count ([Go blog](https://go.dev/blog/container-aware-gomaxprocs)). The engine
already follows that rule in `detect_usable_cpus` (affinity, then the floor of the quota), and the
CLI uses it. No new detection code.

### Acceptance tests (S3)

New `tests/unit/execution/test_native_threads_default.py`:

1. `test_default_resolves_to_usable_cpus`: detection patched to 3; a `run_pipeline` with no
   `native_threads` records 3 and source `auto` in the execution metrics.
2. `test_explicit_value_wins`: `native_threads=1` and `=2` are recorded as given, source
   `explicit`.
3. `test_detection_failure_falls_back_to_one`: detection raises `cpu_detection_failed`; the run
   completes with 1, source `auto_fallback`. With `native_threads=2` and the same failure, 2 is
   used.
4. `test_cap`: detection patched to 5,000; resolved to `MAX_NATIVE_THREADS`.
5. `test_invalid_values_still_refused`: 0, -1, 1,025, `True` and `"4"` raise
   `invalid_execution_knob` before any read.
6. `test_default_output_bytes_equal_single_thread_per_route` (needs the companion; runs on a node
   with 4 or more cores): one parametrized case per route in Enumerations, Routes (full_frame,
   sequential, out_of_core, mixed, multi-table, generate-mask, unified slice, the chunked native
   lane), each forced onto its route. Output table bytes and schema with the default equal
   `native_threads=1`. Input kinds: resident tables, and a lazy Parquet source on the chunked
   lane (the one reader that honours `use_threads`). A lazy CSV cell is kept as a
   CHARACTERIZATION (its reader ignores the flag), not counted as thread evidence.
7. `test_source_on_every_route`: reuse test 6's parametrization, force and verify every branch,
   then require the source after `execute_route` returns. Include pure-generate full_frame
   (`has_mask_table` false) as well as every named mask route.
8. `test_out_of_core_rss_under_memory_limit`: out_of_core with `memory_limit` set, default
   against `native_threads=1`, 3 runs each on the same node; peak RSS of the default run stays
   under the limit and at most +15% over the 1-thread run. Marked `benchmark`, run at the gate.
9. The signature freeze row moves to `("native_threads", "KEYWORD_ONLY", "None", "int | None")`.
   The parameter count stays 47.

Benchmark note for the PR (not a gate): gap9 W2 at 1M rows, default against `native_threads=1`,
wall and peak RSS, 3 runs each on the same node. A peak RSS rise over 15% goes to the owner
before merge.

Red-first: tests 1, 3, 4, 7 and 9 are red on base; test 7 also stays red for a route-local stamp.
Tests 2, 5, 6 and 8 pass on base (the default is 1 there) and pin behavior.

### Mutations (S3)

1. The resolver returns 1 for `None`: test 1 red.
2. The fallback also applied to explicit values: the second half of test 3 red.
3. Cap removed: test 4 red.
4. The resolver skipped for an isolated run that passes no value: an isolated variant of test 1
   (the child records the source) red.
5. Move the source stamp from `execute_route` into any route-local finalizer or under
   `auto_chunk` only: test 7 red on the other forced branches.

### Placement (S3)

| File | Change | Directory and CODEMAP line | Sits beside |
|---|---|---|---|
| `src/decoy_engine/execution/_pipeline.py` | default and docstring | `execution/` ("Pipeline spine and routes") | same file |
| `src/decoy_engine/execution/pipeline/_host.py` | `native_threads_for_run`, `RunThreads` | `execution/pipeline/` | `detect_usable_cpus` (194 lines) |
| `src/decoy_engine/execution/_pipeline_context.py` | one resolver call and the closed source token on the context | `execution/` | same file |
| `src/decoy_engine/execution/_pipeline_route_dispatch.py` | stamp the source once after the route result returns | `execution/` ("Pipeline spine and routes") | `execute_route`, the existing all-route dispatch |
| `tests/unit/execution/test_native_threads_default.py` | new | `tests/unit/execution/` | `test_r3_public_signature_freeze.py` |
| `docs/compatibility-contract.md` | dated pre-GA entry; the 2026-10-01 line that says `native_threads: int = 1` points to it | contract doc | other pre-GA entries |
| `changelog.d/engine-threads-default.md` | new fragment | "Changelog fragments" | other fragments |

Compatibility-contract entry (draft): "Pre-GA default change (ENGINE-THREADS-DEFAULT, 2026-11-xx).
`run_pipeline(..., native_threads: int | None = None)`: `None` uses the usable cores
(`detect_usable_cpus`, capped at 1024; 1 if detection fails). Explicit values are unchanged.
Output data does not depend on the thread count. Default runs now read lazy Parquet sources with
Arrow threads, record the thread source in the execution metrics, and record
`native_thread_clamp` under `auto_chunk`. Re-pin checklist: the platform passes its own thread
grant; check any platform call that omits `native_threads`."

Changelog fragment: "Changed: `run_pipeline` uses the usable CPU cores for native kernels by
default instead of one thread. Pass `native_threads=1` for the old behavior. Output is the same."

### Failure modes (S3)

- FM1 A thread-dependent byte on one route (chunk order, Arrow Parquet reads). Test 6 per route.
- FM2 An unreadable cgroup makes default runs fail. Fallback to 1, recorded, test 3.
- FM3 More memory from threads in a memory-capped run (thread stacks, Arrow read buffers,
  out_of_core hash runs). Rust caps at 4 threads; test 8 under `memory_limit`; RSS in the PR.
- FM4 Host-dependent run records: the thread count now differs by host for library callers, as
  it already does for the CLI. Stated in the contract entry.
- FM5 A route missing from the parity list. The Routes enumeration is a grep census of
  `native_threads=ctx.native_threads` and of every function taking `native_threads`; the builder
  re-runs it on the head and adds any new route to test 6.
- FM6 A later route bypasses the source stamp. All return through `execute_route`; test 7 forces
  every branch and fails if the stamp moves into one branch.

## S4a. DATE-SHIFT jitter_days on every route (D1)

### Current behavior

`jitter_days` is accepted but read by no date_shift route. The date_shift window is resolved by
hand in four places (the Rust crate holds no copy; it receives the resolved bounds):

- the handler, `execution/_strategies/_date_shift.py:118-121` (defaults -365 and 365, swap when
  reversed);
- `execution/native/_operator_params.py:293-299` (`DateShiftParams`, which the shadow bindings
  read at `physical/_shadow_bindings.py:397`);
- `execution/native/_date_shift_ext.py:58-75` (`DEFAULT_MIN_DAYS`, `DEFAULT_MAX_DAYS`,
  `resolve_shift_range` with its swap, called at `:167`);
- `execution/native/_operator_config_rejections.py:186` (bounds admission against
  `MAX_ABS_SHIFT_DAYS`).

So every shipped disguise (`jitter_days: 15` to `30`) and the recommendations default
(`jitter_days: 15`) shift by up to a year.

Not date_shift readers, and left alone: `_operator_params.py:250`, `_kernels_scalar.py:249-252`
and `out_of_core/_mask_group_c.py:238` read text_mask per-span date bounds, where a present but
null bound has its own parity rule (`_strategies/_text_mask.py:145`, `transforms/text_mask.py:502`).
Routing them through `shift_window` would give text_mask jitter behavior and break that parity.
V2-LOG line: TEXT-MASK-DATE-BOUNDS, the text_mask per-span bounds are read in five places and
want their own resolver.

### Design

- One resolver and one validator in `transforms/date_shift.py` (the transform module both the
  handler and the native lane already import), side by side:
  - one private core returns either resolved bounds or a fixed problem word. For the non-jitter
    form it applies today's exact `int()` conversion and reversed-bound swap. Thus strings,
    floats (including truncation), bools, numpy integers and every other `int()`-accepted object
    keep the same window. Both public functions consume this core result;
  - `shift_window_problem(cfg) -> str | None` returns a fixed problem word, or `None`. It
    refuses `jitter_days` together with `min_days` or `max_days`; a `jitter_days` that is not an
    `int`, is a `bool`, or is negative; and a resolved window whose bound exceeds
    `MAX_ABS_SHIFT_DAYS` (106,751, `pd.Timedelta.max.days`). A non-jitter conversion failure gets
    a fixed problem instead of its exception text;
  - `shift_window(cfg) -> tuple[int, int]`: `jitter_days: N` gives `(-N, N)`; otherwise
    `min_days` and `max_days` with defaults -365 and 365, swapped when reversed. It raises the
    registered error when `shift_window_problem` returns a problem, so a bad `jitter_days`
    never falls through to `min_days`/`max_days`.
- `MAX_ABS_SHIFT_DAYS`, `DEFAULT_MIN_DAYS` and `DEFAULT_MAX_DAYS` move beside the resolver;
  `_date_shift_ext.py` imports them. `resolve_shift_range` keeps only the `range_size`
  arithmetic on bounds that `shift_window` resolved.
- The four readers above call `shift_window`. None keeps its own default or swap.
- Both refusal points call `shift_window_problem` and nothing else: the compile refusal in the
  existing `plan/_checks_date_shift.py` (top level and nested; reason
  `plan.DATE_SHIFT_WINDOW_INVALID`, fixed message per problem word) and the native admission at
  `_operator_config_rejections.py:186`.
- Guard test (cross-cutting rule, choke point plus fitness function):
  `tests/sentry/test_date_shift_window_reader.py` walks the syntax tree of `src/decoy_engine` and
  fails on a `"min_days"`, `"max_days"` or `"jitter_days"` string read outside an exact-file
  allowlist. The allowlist is a census at the S4a head and may only shrink. Each entry names its
  reason:
  - date_shift resolver and validator: `transforms/date_shift.py`;
  - not a window read: the wizard option defaults (`_strategies/_date_shift.py:98-99`), the
    recommendations descriptors (`profiling/recommendations.py:158-187`);
  - other strategies: windowed_date (`generation/_column_streams.py:66`,
    `_window_admission.py:308-309`, `transforms/windowed_date.py`), text_mask
    (`_strategies/_text_mask.py:145`, `transforms/text_mask.py`, `out_of_core/_text_mask_native.py:49`,
    `_operator_params.py`, `_kernels_scalar.py`, `out_of_core/_mask_group_c.py`), generate options
    (`config/_generate_options.py`, `plan/checks/_generate_columns.py`).
  The builder fills the final list from the census and puts it in the PR. Files that hold both a
  text_mask read and a date_shift read (`_operator_params.py`) are allowlisted per function, not
  per file. A self-test plants `cfg.get("min_days")` in a temporary date_shift module and asserts
  the sentry fails.

### Acceptance tests (S4a)

New `tests/unit/transforms/test_date_shift_window.py` and a route test:

1. `test_shift_window_rules`: `jitter_days` 0, 1, 30, 106,751; min/max given, reversed,
   defaulted; and every bad `jitter_days`. Non-jitter parity covers `"7"`, `" -8 "`, `7.0`,
   `7.9`, `True`, `False`, numpy integers and a small generated set, comparing with today's
   `int(cfg.get(...))` plus swap. Conversion failures get the registered value-free problem.
2. `test_jitter_route_parity`: one config with `jitter_days: 7`, one cell per route: full_frame,
   sequential (pandas), the sequential native lane (`_sequential_native.py:512`, companion), the
   chunked native lane (companion), the shadow binding, and a nested date_shift child. Each cell
   asserts, from the run evidence (the routing record and lane fields in `quality_metrics`), the
   route it actually took, so a silent fallback fails the cell. out_of_core refuses date_shift
   (`out_of_core/_compat.py:84-89`): that cell asserts the registered decline, not output. Output
   bytes are equal on every taken route and equal to the same config with
   `min_days: -7, max_days: 7`. Every shift is inside `[-7, 7]`.
3. `test_window_invalid_refused`: `jitter_days` with `min_days`, with `max_days`; `"7"`, `True`,
   `-1`, `106,752`; and int-coerced `min_days: -106752` or `max_days: 106752`. Each raises
   `PlanCompileError` before any read, top level and nested, and native admission agrees. Add
   non-jitter conversion failures and assert no `__cause__` or `__context__`.
4. `test_reader_sentry`: the guard test above, plus its planted-read self-test.

Red-first: tests 1, 2 and 3 are red on base (no resolver; `jitter_days` ignored). The legacy
min/max parity cells are green against a reference function copied from the base handler before
the resolver lands, then guard the new core. Test 4 is red on base (four readers outside the
resolver).

### Mutations (S4a)

1. `shift_window` ignores `jitter_days`: tests 1 and 2 red.
2. One route keeps its own `cfg.get("min_days", -365)`: test 2 red on that route, test 4 red.
3. Conflict refusal removed from `shift_window_problem`: test 3 red at compile and native.
4. `bool` accepted as `jitter_days`: test 3 red.
5. `MAX_ABS_SHIFT_DAYS` check dropped: the `106,752` case red.
6. Native admission keeps its own bounds check instead of calling `shift_window_problem`: the
   native half of test 3 red on `jitter_days: 106,752`.
7. Replace legacy `int()` coercion with an exact-type integer check: test 1 red on numeric
   strings, floats, bools and numpy integers.

### Changelog (S4a, output-changing)

`changelog.d/date-shift-jitter.md`: "Breaking (output-changing): date_shift now honours
`jitter_days: N` as the window `[-N, N]`; before, it was ignored and shifts used -365 to 365.
`jitter_days` together with `min_days` or `max_days` is refused. Affected: the shipped disguises
(ccpa, cpni, default, ferpa, gdpr, glba, hipaa, pc, pci, sox) when a client applies them; the
recommendations default for iso_date, us_date and eu_date (`jitter_days: 15`); platform fixtures
that use `jitter_days` (`fixtures/build_hr.py`, `build_logistics.py`, `build_retail.py`,
`build_energy.py`, `build_mortgage_credit.py`, `build_insurance.py`). Configs that set
`min_days` and `max_days` keep today's `int()` coercion and resulting window. New refusals are a
`jitter_days` combined with either bound, a non-integer or negative `jitter_days`, and any
int-coerced bound outside [-106751, 106751]. No min_days or max_days value that today's handler
successfully coerces is refused for its type."

### Placement (S4a)

| File | Change | Directory and CODEMAP line | Sits beside |
|---|---|---|---|
| `src/decoy_engine/transforms/date_shift.py` | `shift_window`, `shift_window_problem`, the moved constants | `transforms/` | `_detect_format` |
| the four readers listed above | call `shift_window`; native admission calls `shift_window_problem` | existing files | |
| `src/decoy_engine/plan/_checks_date_shift.py` | the window refusal through `shift_window_problem` | `plan/` | existing date_shift checks |
| `src/decoy_engine/reasons/plan/` (the part with room) | `DATE_SHIFT_WINDOW_INVALID` | `reasons/plan/` | `DATE_SHIFT_GROUP_BY_UNSUPPORTED_IN_NESTED` |
| `tests/unit/transforms/test_date_shift_window.py`, `tests/sentry/test_date_shift_window_reader.py` | new | `tests/unit/transforms/`, `tests/sentry/` | other date_shift tests, other sentries |
| `changelog.d/date-shift-jitter.md`, `docs/compatibility-contract.md` | fragment, dated entry | | |

## S4b. DATE-SHIFT-FORMAT required

### Every place that tolerates a missing format today

| Site | What it does now | After S4b |
|---|---|---|
| `execution/_strategies/_date_shift.py:145` | `cfg.get("date_format") or _detect_format(col)` | no detection; a missing format is allowed only for a top-level date_shift column with its own declared-casting contract; otherwise a registered runtime error (backstop behind the compile check) |
| `execution/_strategies/_date_shift.py:305` | `shifted.astype(str)` when there is no format | kept only for that top-level declared-casting column, never a nested child |
| `execution/_planner.py:416-431` | `date_shift_requires_explicit_format` chunk decline | deleted (unreachable); its tests move to the compile refusal |
| `execution/native/_requirements.py:384-402` | `format_detect` prepass | deleted |
| `execution/native/_requirements.py:577-582` | comment: a format-less date_shift is still native with a prepass | rewritten |
| `execution/native/_operator_config_rejections.py:158-164` | `date_shift_requires_date_format` native decline | kept for the top-level declared-casting case, docstring updated |
| `execution/native/_capabilities.py:207`, `execution/physical/_shadow_bindings.py:289`, `execution/out_of_core/_mask_group_c.py:58` | comments on format detection | updated |
| `transforms/date_shift.py` docstring | lists date_shift as a `_detect_format` user | updated; `_detect_format` stays for `bucket_perturb` and `text_mask` |

### The refusal, through the strategy requirements registry

No new check module. The rule is one more descriptor in the registry that already holds every
required strategy setting:

- `contracts/strategy_requirements.py:58` `REQUIREMENTS_BY_STRATEGY["date_shift"]` gains
  `StrategyRequirement(("provider_config", "date_format"),
  reasons.plan.DATE_SHIFT_REQUIRES_DATE_FORMAT, "date_shift needs provider_config.date_format,
  for example %Y-%m-%d.")`, next to its namespace descriptor. The registry's `_missing` already
  treats a non-string or blank value as missing.
- `plan/checks/_required_settings.py::check_required_strategy_settings` runs it in both compile
  entry points, with two changes:
  - Declared-casting skip, written the way the `coherent_with` namespace skip is (`:50-64`): the
    check calls one ownership predicate. It returns true only for top-level `date_shift` on the
    exact `(table, column)` with its own declared date parse format, never for a nested child. The
    handler backstop calls it too.
  - The walk extends to `nested` children (`nested_children`) for `provider_config`-rooted
    descriptors only, re-rooted onto the child's `provider_config.strategy_config`
    (`_nested_json/_rules.py:47` holds the child's config there). Today that is only the
    date_format descriptor. Root-level descriptors (namespace) never apply to a child, because a
    child takes its parent's namespace (`execution/_strategies/nested/_handler.py:193-194`). Paths use the registry's
    style for the parent plus the nested form the existing nested checks use for the child.
- Reason `plan.DATE_SHIFT_REQUIRES_DATE_FORMAT` (`date_shift_requires_date_format`, following the
  `<STRATEGY>_REQUIRES_NAMESPACE` naming) in `reasons/plan/`. The message carries table and
  column names (config identifiers, never a cell value).

Handler backstop: key the shared predicate on plan strategy location, not dtype, because declared
dates arrive as `date32` objects. Missing-format nested children still raise. If the handler lacks
table and nested-location context, put the backstop at the plan-aware dispatch point and name it
in the PR.

Established solutions: pandas made the same move in PDEP-4: one format per column, no silent
switching, and an explicit `format=` is the documented way to parse consistently
([PDEP-4](https://pandas.pydata.org/pdeps/0004-consistent-to-datetime-parsing.html)). The engine
already requires a format for `date_preserve` (`transforms/date_preserve.py:101-105`).

### Where a suggestion is written, it carries the detected variant

The date detectors have several variants each (`detection/detectors.py:245-262`):

- `iso_date`: `%Y-%m-%dT%H:%M:%SZ`, `%Y-%m-%dT%H:%M:%S`, `%Y-%m-%d %H:%M:%S`, `%Y-%m-%dT%H:%M`,
  `%Y-%m-%d %H:%M`, `%Y-%m-%d`, `%Y%m%d`;
- `us_date`: `%m/%d/%Y`, `%m/%d/%y`;
- `eu_date`: `%d.%m.%Y`, `%d.%m.%y`, `%d-%m-%Y` (never slashes; `detection/_patterns.py:43`).

The winning variant is `DetectorMatch.format_pattern` (`detection/types.py:94`), surfaced on
`FieldStats.format_pattern` (`profiling/types.py:105`, `profiling/profiler.py:117`). One fixed
format per detector is wrong, so no writer uses one:

- A winning variant is not enough. `_ISO_DATE_RE` accepts shapes no variant matches (for
  example `T..HH:MMZ` and ` HH:MM:SSZ`), and `_dominant_variant` (`detection/_scoring.py:152-180`)
  returns the largest variant even when it covers only part of the detector's hits. Shape
  coverage alone is also insufficient: `31.02.2024` matches a date variant but is not a date.
  Set additive `format_pattern_complete: bool = False` true only when every detector hit has the
  winning shape and every raw hit, including whitespace, survives runtime-equivalent
  `pd.to_datetime(raw_hits, format=chosen_format, errors="coerce")`. Any `NaT` is false. Surface
  the bool on `FieldStats` with the same false default and in the value-free field list. The
  default keeps old profiles readable and cannot opt them into date_shift.
- Engine starter: `profiling/_starter_inference.py::infer_starter_strategy` takes the top
  confident match. When its descriptor's strategy is date_shift and the match has
  a non-None `format_pattern` and `format_pattern_complete` is true, the decision's
  `provider_config` gains
  `date_format = match.format_pattern`. Otherwise (no variant, or a variant that covers only
  part of the hits, or any hit that does not parse), the decision is `_FALLBACK` (redact with the
  louder review), because a date_shift with a wrong or missing format would fail rows or not
  compile. Public
  `starter_config` therefore only writes configs that compile and fit the whole column.
- Starter review uses the same format-bearing `StarterDecision`. CONFIRM copies its entry and
  SKIP preserves it. `column_entry` refuses date_shift EDIT without `date_format`; valid EDIT
  still goes through `build_entry`. Give descriptor-only `detector_entry` (`:248-264`) the same
  dynamic-decision path for date detectors and emit no date_shift when it is absent. Rewrite
  `test_starter_review.py:570-595` for static and dynamic parity, plus CONFIRM, SKIP and EDIT.
- Recommendations: `profiling/recommendations.py` descriptors keep their params
  (`jitter_days: 15`, now honoured by S4a); iso_date and us_date starter choices lose fixed
  min/max. Add eu_date's missing date_shift starter choice, so all three date detectors use the
  guarded dynamic format. Name the new eu_date output in compatibility docs and re-baseline
  `tests/fixtures/scan_multi/default_strategy_by_detector_base.json`.
- Disguises: the ten rules in `src/decoy_engine/disguises/*.yaml` stay as they are (one rule over
  `iso_date`, `us_date`, `eu_date`; no format; no split). A disguise is applied to a column by a
  client that knows the column's detection, and that client writes the format.

Where the disguise expander is:

- The platform frontend applies disguises: `api/disguises/router.py:90-97` returns a bundle's
  `field_rules`, and `web/src/pipelines/hifi/MaskInspector.tsx` (around `:1786`) applies each
  rule's mask and params to columns whose detected kind matches. The same file already reads the
  detected `format_pattern` for its format field (`:1628-1674`). The platform is parked, so
  follow-up row P1 (PLATFORM-DISGUISE-DATE-FORMAT): when a date_shift rule is applied, write the
  column's detected `format_pattern` as `provider_config.date_format`, and do not apply the rule
  when there is none. Plus a re-pin checklist line.
- The engine's `config/policy/expand_policy` takes disguise decisions through an injected
  `classification_default` callable (`config/policy/_expand.py:145-150, :347-351`). At base it has
  no caller in the engine, the CLI or the platform. A classification-level decision has no
  detected format, so a date_shift decision from it is refused by S4b at compile with the column
  path. That is the intended behavior (require, do not detect); the docstring says so.
- The CLI does not expand disguises. It lists disguise ids (`cli/reference.py`,
  `cli/completers.py`, `cli/explain.py`) and uses its own templates and `decoy init` inference
  (C1).

### Other shipped engine configs that would now be refused, and their update

| Item | Today | Update in S4b |
|---|---|---|
| `testflight/jobs/a_healthcare_claims/manifest.yaml` (`dob`) | no format | the format the fixture data uses (the builder reads the generator) |
| `testflight/jobs/b_retail_m2m/manifest.yaml` (`signup_date`) | no format | same; the nightly testflight goes red without it |
| `scripts/gen_proof_manifest.py:459` (the date_shift proof, `min_days: 30, max_days: 90`) | no format | `date_format: "%Y-%m-%d"` (its inputs are ISO); regenerate the proof page per the proof-page rule |
| `examples/` | no `date_shift` | none |
| Docs: `docs/strategies.md` (about line 253), `docs/execution-backends.md`, `docs/reasons.md`, `docs/qa/07-mask-dates-and-numbers.md`, `docs/quality/mutation-ledgers/execution_planner.md` | describe detection | describe the requirement and the detected-variant rule |
| Test fixtures | 18 test files use `date_shift` with no `date_format` anywhere in the file (grep at base; more files mix both) | add the format; tests whose subject is detection become refusal tests or are deleted with the code |

The strategy wizard option already defaults `date_format` to `%Y-%m-%d`
(`_strategies/_date_shift.py:100`); the builder confirms a wizard-written config carries it.

Platform re-pin checklist lines (no platform code in this batch): the `api/storm` disguise
application path and the P1 row; `api/templates/upload_csv_mask_to_s3.yaml` (date_shift with
`min_days`, no format); the platform fixtures with date_shift (`fixtures/build_*.py`); any
platform-built config that omits `date_format`.

### CLI follow-up slice C1 (CLI repo, not engine work)

At CLI `origin/main` 4564b745:

- `src/decoy/cli/_init_inference.py:99-118` (extend the current `iso_date`, `us_date` branch to
  `eu_date`) and the writer in
  `src/decoy/cli/init.py` (around `:193-220`, which writes only `min_days`/`max_days`): write
  `date_format` from the top match's `format_pattern`, only when `format_pattern_complete` is
  true. That engine field means every detector hit has the winning shape and every raw hit parses
  through the runtime-equivalent `pd.to_datetime(..., format=..., errors="coerce")`, including
  its whitespace behavior. Otherwise do not suggest date_shift (fall back the way the CLI does
  for an unknown column). Same rule as the engine starter; the CLI does not recalculate it.
- `src/decoy/templates/hipaa.yaml` (`dob`, `admission_date`, `discharge_date`) and
  `src/decoy/templates/pci.yaml` (`transaction_date`): add `date_format: "%Y-%m-%d"` (templates
  are fixed sample schemas with no scan).
- Tests per detector variant (one ISO datetime, `%Y%m%d`, `%m/%d/%y`, `%d.%m.%Y`, `%d-%m-%Y`), a
  mixed column (two variants), an invalid-calendar column (`31.02.2024`), a valid column with
  surrounding whitespace, and the docs. Invalid-calendar and padded raw values both fall back to
  redact because runtime `pd.to_datetime(..., format=...)` coerces them to `NaT`. The CLI uses
  `format_pattern_complete` from the engine and never reimplements the rule.

C1 is forward-safe (the format is accepted today), so it merges first, and it must merge before
the CLI re-pins to the engine release that carries S4b. Inbox line: DATE-SHIFT-FORMAT-CLI.

### Acceptance tests (S4b)

New `tests/unit/plan/checks/test_date_shift_format.py`:

1. `test_missing_format_refused`: missing, `None`, `""`, `"   "`, `5`, `True`: each raises
   `PlanCompileError` with `date_shift_requires_date_format` and the registry path, from
   `compile_plan` and from `run_config_only_checks`.
2. `test_refused_before_read`: `run_pipeline` with a `source_loader` that records calls: the
   loader is never called and nothing is staged.
3. `test_nested_child_refused`: a nested date_shift child with no
   `provider_config.strategy_config.date_format` is refused with the child path.
3b. `test_nested_hash_child_without_namespace_compiles`: a nested hash child with no namespace
   compiles (it takes the parent's namespace).
4. `test_declared_casting_column_exempt`: end to end through `run_pipeline` and the
   declared-casting boundary: a declared top-level date_shift without `date_format` completes on
   `date32` objects. A paired nested date_shift under that declared parent is refused with its
   child path, and its direct dispatch-level backstop raises the registered runtime error.
5. `test_message_value_free`: the message carries no cell value; `__cause__` and `__context__`
   are None.
6. `test_reason_registered`: the code is in the reason registry and the release baseline, and the
   descriptor is in `REQUIREMENTS_BY_STRATEGY["date_shift"]`.
7. `test_shipped_configs_compile`: both testflight manifests and the `gen_proof_manifest` date
   proof pass `check_required_strategy_settings`.
8. `test_starter_writes_detected_variant`: for a column of each variant above, `starter_config`
   writes it. No variant, mixed variants, `T..HH:MMZ`, shape-valid `31.02.2024`, and otherwise
   valid dates padded with leading or trailing whitespace get redact. Every output compiles, and
   every date_shift output parses all detector hits under its written format.
9. `test_handler_backstop`: the date_shift handler called on a string column with no format and
   no declared contract raises the registered runtime error, not a detection; the same top-level
   column with its own declared contract does not; a nested date_shift location under that
   declared parent still raises.
10. `test_starter_review_keeps_required_format`: a complete date detector decision produces the
    same entry through `starter_config` and dynamic `detector_entry`; CONFIRM and SKIP preserve
    it. EDIT without `date_format` is refused, valid EDIT passes config-only checks, and static
    `detector_entry` without a dynamic decision emits no invalid date_shift.

Rewritten, not weakened: `test_execution_planner.py:630`, `test_planner_mutation_kills.py:165,182`
and `test_chunked_date_shift_admission.py:486` assert the compile refusal instead of the planner
decline.

Red-first: tests 1, 2, 3, 6 to 10 are red on base. Test 4's top-level half passes and pins the
exemption; its nested and backstop halves are red.

### Mutations (S4b)

1. Treat a blank string as present: test 1 red.
2. Skip nested children: test 3 red.
3. Drop the declared-casting skip: test 4 red.
4. Let a nested child inherit its parent's declared-casting exemption: the paired case in test 4
   and the nested half of test 9 red.
5. Key the backstop on dtype: test 4 red (date32 object cells).
6. Restore `_detect_format` in the handler: test 9 red.
7. Starter writes a fixed `%Y-%m-%d` per detector: test 8 red on every non-ISO-date variant.
8. Mark completeness from shape coverage without parsing: the `31.02.2024` case in test 8 red.
9. Parse stripped shape labels instead of the raw padded hits with the runtime operation: the
   whitespace case in test 8 red.
10. Nested walk applies the namespace descriptor to children: test 3b red.
11. Let `detector_entry` rebuild date_shift from the static descriptor: test 10 red because the
    entry lacks `date_format` and fails the requirement.

### Placement (S4b)

| File | Change | Directory and CODEMAP line | Sits beside |
|---|---|---|---|
| `src/decoy_engine/contracts/strategy_requirements.py` | the date_format descriptor | `contracts/` | the namespace descriptors |
| `src/decoy_engine/contracts/declared_casting.py` | the pure top-level format-ownership predicate used by compile and the handler backstop; callers supply contract presence and strategy location, so this leaf imports no plan or execution module | `contracts/` ("Versioned contracts") | existing declared contract |
| `src/decoy_engine/plan/checks/_required_settings.py` | shared declared-casting predicate, nested walk without inherited exemption | `plan/checks/` | the `coherent_with` skip |
| `src/decoy_engine/reasons/plan/` (the part with room) | `DATE_SHIFT_REQUIRES_DATE_FORMAT` | `reasons/plan/` | the `*_REQUIRES_NAMESPACE` reasons |
| `src/decoy_engine/profiling/_starter_inference.py`, `_starter_config.py`, `recommendations.py` | parseable detected variant in the starter and dynamic review entry | `profiling/` | same files |
| `src/decoy_engine/detection/types.py`, `_scoring.py`, `profiling/types.py`, `profiling/profiler.py`, `profiling/_value_redaction.py` | `format_pattern_complete` | `detection/`, `profiling/` | `format_pattern` |
| the tolerance sites in the table above | delete or guard | existing files | |
| testflight, `scripts/gen_proof_manifest.py`, docs, fixtures | as listed | existing files | |
| `tests/unit/plan/checks/test_date_shift_format.py`, `tests/unit/validation/test_starter_review.py` | new format cases; dynamic review-path parity | owning existing test directories | `test_checks_date_shift.py`, existing starter review tests |
| `changelog.d/date-shift-format-required.md`, `docs/compatibility-contract.md` | fragment, dated entry | | |

Choke points: the strategy requirements registry is the one place the format requirement is held;
the declared-casting contract owner holds the one top-level exemption predicate used at compile
and at the handler backstop. The backstop has its own reason and test (mutations 4 to 6); it does
not redefine the exemption.

Changelog fragment: "Breaking: a `date_shift` column without `provider_config.date_format` is
refused at plan compile (`date_shift_requires_date_format`). Add the column's format, for example
`%Y-%m-%d`. The engine no longer guesses the format from a sample. Top-level date_shift columns
whose own format comes from a declared-casting contract are not affected; nested date_shift
children do not inherit that exemption. Starter configs write a detected variant only when every
detector hit parses with it under the runtime parser; otherwise they fall back to redact. The
starter now offers the same guarded date_shift choice for eu_date that the platform descriptor
already carries."

### Failure modes (S4)

- FM1 A shipped config the list misses fails at run time for a user. Test 7 and the full suite
  (shared-fixtures trigger).
- FM2 The declared-casting conflict: requiring a format the other check forbids. Test 4, end to
  end.
- FM3 A builder deletes a detection test without replacing what it guarded. The PR lists each
  deleted test with the test that now covers its case.
- FM4 The CLI re-pins before C1 merges, and `decoy init` output stops compiling. C1 merges first;
  the CLI re-pin checklist gets a line.
- FM5 Reason baselines (`tests/fixtures/f29/*`, `tests/sentry/baselines/f29-*`) drift. Updated in
  the same commit as the reason, by their own regenerator.
- FM6 A wrong fixed format written for a detector (for example slashes for `eu_date`). No writer
  uses a fixed format; test 8 per variant.
- FM7 A route keeps reading the window by hand after S4a. The reader sentry.
- FM8 The nested walk refuses existing nested children for a missing namespace. Only
  `provider_config`-rooted descriptors are re-rooted onto children; test 3b.
- FM9 A starter writes the largest variant for a column that mixes shapes, and rows fail at run
  time. `format_pattern_complete` gate; the mixed, invalid-calendar and padded cases of test 8.
- FM10 A declared parent accidentally exempts its nested date_shift child. The shared ownership
  predicate requires a top-level strategy location; tests 4 and 9 plus mutation 4.
- FM11 Starter review reconstructs a descriptor-only date_shift and drops the data-derived
  format. Test 10 covers `detector_entry`, `column_entry`, CONFIRM, SKIP and EDIT.

## Enumerations

From the code at 75fba3d855d71e3980a62afc3ce7f1187b72073d.

### Routes

- windowed_date: the mask strategy handler (`execution/_strategies/_windowed_date.py:79`, used by
  full_frame, sequential and the chunked pandas adapter), the generation stream
  (`generation/_column_streams.py:83-91`), grouped generation
  (`generation/_grouped_windowed_generators.py:111`), and the native protocol reproduction
  (`execution/native/protocol/providers_mask.py:318`, test-side only). All three runtime callers
  pass through `apply_windowed_date`.
- `ctx.native_threads` (S3):
  - full_frame: `_pipeline_full_frame.py:207`;
  - sequential and out_of_core through `_pipeline_route_dispatch.py:145` and `:202`, then
    `out_of_core/_runner.py:125, :243` (`OocHashRun`);
  - mixed: `_pipeline_mixed_route.py:233`;
  - multi-table: `_pipeline_multi_table.py:315, :385`;
  - generate-mask: `_pipeline_generate_mask.py:99, :268, :303`;
  - unified slice: `_unified_slice.py:154, :240, :459`;
  - the chunked native lane: `_pipeline_context.py:433`;
  - lazy input reads: `_chunked_input.py:388` (Parquet honours it; CSV and fixed-width ignore it);
  - records: `_pipeline_auto_chunk.py:583-589`, `_pipeline_finalize.py:138`;
  - isolation: `_isolated_run.py`, `_isolated_common.py` (forwarded kwargs).
- date_shift window (S4a): the four readers in the S4a section (text_mask bounds excluded).
- Missing date_shift format (S4b): the S4b site table.

### Exit paths

- S1 fast path, success: returns the list; local buffers and the seed copy go out of scope.
- S1 fast path, `Exception` or anomaly: buffers are discarded, the reference path reruns, and the
  `except BaseException: del seed` shape deletes the seed copy on its error exit and re-raises.
- S1 fast path, `KeyboardInterrupt` or `SystemExit`: propagates; the same `del seed` shape runs.
- S2 to S4b: N/A, they open no file and hold no state.

### FK shapes

N/A: no slice reads or writes a key.

### Fields

- The thread source in the execution metrics stamped after the result returns through
  `execute_route` (S3, new, closed set of three words).
- `quality_metrics["auto_chunk"]["native_threads"]` and `native_thread_clamp` (S3, existing; now
  set on default runs).
- `StarterDecision.provider_config` for date detectors now carries `date_format` (S4b).
- `DetectorMatch.format_pattern_complete` and `FieldStats.format_pattern_complete` (S4b, new,
  additive, a bool, value-free).
- No other dataclass field of a public result type is added or removed.

### Output surfaces

- S1 and S2: output column values and `WindowedDateError` messages; S2 adds one registered
  runtime error.
- S3: the run record (`quality_metrics`).
- S4a: output column values for `jitter_days` configs; one plan refusal.
- S4b: the `PlanCompileError` message and path, `docs/reasons.md`, the reason baselines, the
  backstop's error message, and `starter_config` output.
- No slice adds a log line, stdout or stderr output.

## Reuse inventory

- `DeriveContext.derive_sources` (`determinism/_derive.py:241`) and `seed_bytes_to_int`
  (`determinism/_seeds.py:34`): S1.
- `derive_index_batch`, `_compiled_index_kernel`, `_validated_index_array`
  (`generation/pool/_sampler.py`, `execution/native/_crypto_ext.py`, `_crypto_reference.py`):
  the S2 offset kernel, exported, not copied.
- `detect_usable_cpus`, `MAX_NATIVE_THREADS` (`execution/pipeline/_host.py`) and the existing
  all-route `execute_route` result choke point (`_pipeline_route_dispatch.py:59-100`): S3.
- `require_lane_knobs` (`_pipeline_auto_chunk.py`): S3 keeps it as the validator.
- `REQUIREMENTS_BY_STRATEGY` and `check_required_strategy_settings`: S4b, instead of a new check.
- The declared-casting contract lookup and `nested_children`: S4b.
- `DetectorMatch.format_pattern` and `FieldStats.format_pattern`: S4b and C1.
- The existing `plan/_checks_date_shift.py`: the S4a refusal.
- Reason registry (`reasons/plan/`, `reasons/runtime/`), the registry sentry and the f29
  baselines: S2, S4a, S4b.
- Sentries that must stay green: module size (`tests/sentry/test_module_size.py`; S1 keeps the
  module under 600), `test_rng_construction.py`, the secret-material census, the public import
  boundary, the plan/ and transforms/ fan-out freezes, the physical-seam sentry (no slice adds an
  `execution/` seam).
- New machinery: the S3 resolver, the S4a resolver and its reader sentry. Each is one function at
  an existing choke point.

## Frozen contracts touched

| Contract | Slice | Kind |
|---|---|---|
| `run_pipeline` signature (`test_r3_public_signature_freeze.py:56`, `docs/compatibility-contract.md:869`) | S3 | breaking default change (pre-GA), additive `None` |
| Execution metrics keys | S3 | additive (thread source) |
| windowed_date output bytes, draw-site catalogue, provider goldens | S2 | breaking (output-changing), changelog'd |
| date_shift output for `jitter_days` configs | S4a | breaking (output-changing), changelog'd |
| Plan compile refusals and the reason manifest | S2, S4a, S4b | additive reasons; S4a and S4b add refusals (breaking) |
| `starter_config` output, recommendations fixture | S4b | breaking content change |
| `DetectorMatch` and `FieldStats` fields | S4b | additive (`format_pattern_complete`) |
| `generation.pool` public names | S2 | additive |
| `SEED_PROTOCOL_VERSION` | S2 | unchanged (7), pre-GA decision recorded |
| Disguise YAML content | none | unchanged |

## Pre-mortem

Assume the batch shipped and went wrong. The likely causes, and what stops each:

- S1 merged with a one-row difference on an input outside the corpus (a pandas ISO8601 parse that
  accepts a string the regex also accepts but reads differently, or a typed cell converted
  differently). Stopped by the property test, the fall-back rule on any NaT, the per-cell regex in
  front of the vector parse, and exact-type admission.
- S2 skipped because S1 looked fast enough on strings while real anchors are dates. Stopped by the
  `date` workload and the data gate; a skip is recorded with its numbers.
- S3 made a container run out of memory with more threads on out_of_core. Stopped by the Rust cap
  of 4, test 8 under `memory_limit`, and the `native_threads=1` escape.
- S4a fixed jitter on the pandas route only. Stopped by the route parity test and the reader
  sentry.
- S4b broke the nightly testflight, the proof page or a CLI project. Stopped by test 7, the full
  suite, and C1 merging before the CLI re-pin.
- A starter wrote `%d/%m/%Y` for an `eu_date` column that uses dots. Stopped by writing the
  detected variant only, test 8 per variant.

## Class table

| # | Class | Closing structure | Proving test | Mutation that must turn it red |
|---|---|---|---|---|
| 1 | Value-bearing output | S1: every error comes from the unchanged reference path, raised outside `except`. S2: the row-number error is registered and value-free. S4a and S4b: refusals name config identifiers only. S3: the thread source is a closed three-word set | S1 test 2, S2 test 7, S4b test 5 | S1 mutation 5; format a value into the S4b message: test 5 red |
| 2 | Cleanup missing on an exit path | S1: the seed and `DeriveContext` are deleted on every exit, including interrupts (existing `del seed` shape), covered by the secret-material census sentry. S2 to S4b: N/A, no resource is opened | the census sentry on `transforms/windowed_date.py`; S1 test 7 | drop the `del` on the fast path: the sentry red |
| 3 | State machine and concurrency | S3: thread count changes scheduling only; Rust kernels are proved thread-count independent in-crate; per-route byte parity. Others: N/A, pure functions | S3 test 6 | a thread-dependent route turns its test 6 cell red |
| 4 | Route parity and silent fallback | S1: one entry point for mask, generation and grouped callers; the fast path falls back only by rerunning the reference. S2: mask and generation share one derivation. S3: parity on every route; the fallback to 1 is recorded. S4a: one window resolver for every route plus the reader sentry. S4b: one registry descriptor before any route; the planner decline and native prepass are deleted | S1 tests 1, 3, 5; S2 test 6; S3 tests 3, 6, 7; S4a tests 2, 4; S4b tests 1, 2, 9 | S1 mutation 5; S3 mutations 2, 5; S4a mutation 2; S4b mutations 4, 6 |
| 5 | Referential integrity | N/A: no FK is read or written by any slice | | |
| 6 | Untrusted producer | S4a and S4b: config is the untrusted input; bad `jitter_days`, conflicts, and missing, blank or non-string formats are refused at compile. S1: cells outside the exact admitted types go to the reference path, which keeps today's validation. S2: row numbers outside the domain are refused | S4a test 3; S4b test 1; S1 corpus; S2 test 7 | S4a mutation 4; S4b mutation 1; S1 mutation 9; S2 mutation 6 |
| 7 | TOCTOU on a path | N/A: no slice opens or checks a path | | |
| 8 | Weak tests and overclaimed evidence | S1 pins the base digest from 75fba3d855d71e3980a62afc3ce7f1187b72073d and adds a negative test that S2 is not byte-identical; red-first lists label which tests pass on base; the lazy CSV thread cell is labelled CHARACTERIZATION; benchmark claims need the interleaved baseline, the variance rule and both anchor shapes; S2 distribution bounds are fixed and never edited to pass | step 0 tests; the benchmark record; S3 test 6 labels | edit a golden in S1: stop rule; loosen the chi-square bound: review refusal |
| 9 | Behavior-preserving refactor drift | S1 keeps the reference loop inline and proves the fast path against a verbatim copy of the base loop on the corpus and by property test; `test_rng_construction.py` and the draw-site catalogue stay green with no allowlist change | S1 tests 1 and 5, the unchanged goldens list | S1 mutations 1 to 11 |
| 10 | Frozen contract drift | S2: draw-site entry, provider version and goldens move together with a Breaking changelog line; SEED_PROTOCOL_VERSION decision recorded. S3: the freeze row and the contract entry move in one commit. S4a and S4b: reasons registered through the registry and baselines; changelog lines list what changes | S3 test 9; S4b test 6; the catalogue pinned test in S2 | spell a code as a literal: the registry sentry red; change the S3 default without the freeze row: test 9 red |

## Size

- S1: one source file (about +110 lines), three new test files, one bench file, one record. No
  public name.
- S2: four source files, two public names in `generation.pool`, one reason, one test file,
  re-baselines, one fragment, one compatibility-contract entry, one record update.
- S3: four source files, one helper in `execution.pipeline` (not root-exported), one test file
  with per-route cases, a contract entry, a fragment.
- S4a: one resolver and one validator, four readers switched, one refusal in an existing check, one reason, two
  test files including one sentry, a fragment, a contract entry.
- S4b: one registry descriptor, the required-settings walk, one shared exemption predicate, one
  reason, the starter and review writer, about ten
  source files edited (mostly deletions), two testflight manifests, the proof script, docs, 18 or
  more test files, a contract entry, a fragment.
- C1: three CLI source files, two templates, tests, docs.

A build well past these sizes stops and reports before review.

## Review round 1 response (Dennis on b1cd9bd67)

| # | Finding | Change in this revision |
|---|---|---|
| 1 | BLOCKER: one format per detector is wrong | Three-format split dropped. Every writer uses the detected `format_pattern`; `None` falls back. Disguise YAML unchanged; the expander is the platform frontend (`MaskInspector.tsx`), so follow-up row P1 and a re-pin line; the engine's `expand_policy` has no caller and refuses at compile; the CLI does not expand disguises. Per-variant tests in S4b test 8 and C1 |
| 2 | HIGH: jitter_days on native and shadow | New slice S4a: one `shift_window` resolver for all four readers, conflict refusal, route parity test, reader sentry, changelog list including the platform fixtures |
| 3 | HIGH: S3 routes | Routes enumeration rewritten per route; per-route byte parity (test 6); out_of_core RSS under `memory_limit` (test 8) |
| 4 | MEDIUM: source via stamp_execution_metrics | Superseded by the Codex DESIGN finding: the source is now stamped after every result in `execute_route`; test 7 and mutation 5 cover every branch |
| 5 | DESIGN HIGH: no new check module | Descriptor in `REQUIREMENTS_BY_STRATEGY`, checked by `check_required_strategy_settings`, declared-casting skip in the `coherent_with` style, nested walk, registry path style. Reason renamed `DATE_SHIFT_REQUIRES_DATE_FORMAT` |
| 6 | MEDIUM: seed_bytes_to_int and draw token | Both in S1 design step 4; `test_rng_construction.py` on the must-pass list |
| 7 | MEDIUM: date objects | Exact-type admission of `date`, naive `datetime` and naive `Timestamp`; `date` workload in workload A; targets apply to both shapes |
| 8 | MEDIUM: corpus | Past-ns windows, negative positions, length mismatch, empty namespace with all-null and non-null batches added; overflow guard added to the design |
| 9 | MEDIUM: no-bump reason | Rewritten: pre-GA, a bump would rekey every keyed column and vault |
| 10 | MEDIUM: draw2 namespace collision | Draw index in the source (`2r + k`); explicit domain check `0 <= r < 2**62` with a registered error; tests 5 and 7 |
| 11 | MEDIUM: guard keyed on dtype | Backstop keyed on the declared column; test 4 end to end through the cast boundary |
| 12 | MEDIUM: coverage | `scripts/gen_proof_manifest.py:459` added; platform re-pin lines for `api/storm`, the upload template and fixtures |
| 13 | LOW: lazy CSV ignores use_threads | Claim corrected; the CSV cell is a CHARACTERIZATION |
| 14 | LOW: resolver name | Renamed `native_threads_for_run` |
| 15 | LOW: Exception and warnings | Fallback catches `Exception`; tests 6 and 7 |

On 5, round 1 noted a concern that the nested walk would apply the namespace descriptor to
children. Round 2 resolved it: only `provider_config`-rooted descriptors are re-rooted onto
children (below).

## Review round 2 response (Dennis on 24025e868, final Dennis round)

| # | Finding | Change in this revision |
|---|---|---|
| 1 | HIGH: S4a reader list | List is now the handler, `_operator_params.py:293-299`, `_date_shift_ext.py:58-75` and `_operator_config_rejections.py:186`. The three text_mask per-span readers are excluded, with V2-LOG line TEXT-MASK-DATE-BOUNDS. The Rust crate holds no copy |
| 2 | HIGH: S4b nested walk | Only `provider_config`-rooted descriptors are re-rooted onto `provider_config.strategy_config`; namespace never applies to a child. Test 3b (nested hash child without a namespace compiles), mutation 10. Census-and-stop step dropped |
| 3 | MEDIUM: one validator | `shift_window_problem` beside `shift_window`, called by the compile refusal and the native admission; checks `MAX_ABS_SHIFT_DAYS`; `shift_window` raises on a bad `jitter_days`. Test 3 and mutations 5, 6 |
| 4 | MEDIUM: sentry allowlist | Exact-file (per function where mixed) allowlist from a census at the S4a head, shrink-only, each entry classified; planted-read self-test |
| 5 | MEDIUM: parity cells | Each cell asserts its taken route from run evidence; out_of_core asserts its decline; sequential native lane and a nested child cell added |
| 6 | MEDIUM: starter on mixed columns | New additive `format_pattern_complete`; date_shift is written only when every hit has the winning shape and parses with that format; mixed, no-variant, invalid-calendar and padded cases are in test 8 and C1 |
| 7 | LOW: S2 row-number domain | S2 test 8 and the changelog name the narrowing from below 2^64 to below 2^62 |

## Codex round response

| # | Label | Finding | Change in this revision |
|---|---|---|---|
| 1 | V1 | S4b declared-casting exemption was broad enough to cover a nested child under a declared parent | The guarantee, compile check and handler backstop now use one ownership predicate that exempts only the exact top-level date_shift column. S4b tests 4 and 9 cover a nested child under a declared parent; mutation 4 makes inheritance turn them red |
| 2 | V1 | S4b and C1 treated complete format shape as proof that the chosen format parses every hit | `format_pattern_complete` now requires full winning-shape coverage and a successful runtime-equivalent `pd.to_datetime` parse of every raw hit. S4b test 8 and C1 make `31.02.2024` and padded raw dates fall back to redact; mutations 8 and 9 separate parseability from shape and whitespace behavior |
| 3 | V1 | S4a would replace today's `int()` coercion for min_days and max_days with strict types | The one resolver core preserves exact `int()` results for all non-jitter bounds. S4a test 1 has explicit and generated parity cases; mutation 7 turns strict coercion red. The changelog lists every new refusal and states that type alone refuses no previously coercible bound |
| 4 | DESIGN | S3 stamped the thread source in a route-local finalization mechanism instead of the all-route result choke point | The stamp moved to `execution/_pipeline_route_dispatch.py::execute_route` after the selected executor returns. Test 7 forces every branch, including pure generation, and mutation 5 moves the stamp off the choke point to prove the guard |
| 5 | V2-LOG | S1 converted warnings to exceptions, so the fallback could hide a warning | Test 6 records warnings under the `always` filter and asserts the list is empty without changing control flow; mutation 11 emits one |
| 6 | V2-LOG | The new dynamic date format was not reconciled with `detector_entry`, `column_entry` and `apply_review` | S4b design and test 10 keep one format-bearing `StarterDecision`, prevent descriptor-only date_shift output, require the format on EDIT, and prove CONFIRM and SKIP preserve it |
| 7 | V2-LOG | Placement and base citations were stale | S2 now places `docs/compatibility-contract.md`; every base citation uses `origin/main` `75fba3d855d71e3980a62afc3ce7f1187b72073d` |

Final verdict: GO
