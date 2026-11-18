# LARGE-STRING-FAST: `redact` and `truncate` take the fast path on `large_string` input

Status: plan

Rules consulted: 00-universal, risk-and-exceptions, development-loop, performance, testing,
architecture, cross-cutting-concerns, proportionality, documentation; engine CLAUDE.md
(established methodology, comments explain why).

Base reviewed against engine `origin/main` `9a2b3e8`. Roadmap row 24zy (CLI repo
`docs/ROADMAP.md`). One slice, engine
only. No public API, config, registry or output change.

## Goal

A text column stored as Arrow `large_string` is masked by `redact` and `truncate` as fast as the
same column stored as `string`, with byte-identical output.

Guarantee: for every input the fast path accepts today, output is unchanged. For a `large_string`
array (or chunked array of one) whose values fit in 32-bit offsets, `redact_array` and
`truncate_array` return exactly what `_redact_array_reference` and `_truncate_array_reference`
return (same values, null mask, container and Arrow type), without the per-row loop. Truncate output
is `string`; redact output is `string` when populated and `null` when empty or all-null.

Non-goals: `string_view`, dictionary-encoded strings, `hash_array` (always per row in Python; the
native hash kernel already admits `large_utf8`), the pandas oracle handlers, the native admission
rules in `execution/native/_requirements.py`, and arrays over 2 GiB of text.

## Why it matters

`large_string` is what several common writers produce, so the slow path is not rare:

| Source | Arrow type the engine sees |
|---|---|
| Polars `write_parquet`, read with `pq.read_table` | `large_string` |
| pandas `string[pyarrow]` column through `pa.Table.from_pandas` | `large_string` |
| pandas `string[pyarrow]` written to Parquet, read back | `large_string` |
| Polars `DataFrame.to_arrow()` | `large_string` |
| `pyarrow.csv.read_csv` | `string` |

(polars 1.42.0, pandas 2.3.3, pyarrow 24.0.0; `large-string-evidence/source_types.py`.) Parquet
keeps the writer's Arrow type in its schema metadata, so a file written by Polars or by a pandas
frame with `string[pyarrow]` reads back as `large_string` on every engine route that reads Parquet
through pyarrow, including the CLI's plain `decoy run` and the RUN-STREAM lazy source.

## Current behavior

- `src/decoy_engine/kernel/_scalar.py:82` `redact_array` and `:155` `truncate_array` are guarded
  dispatchers. The guard admits only `v.type == pa.string()` (`:103`, `:190`); anything else,
  `large_string` included (named in the `truncate_array` docstring, `:174`), falls back to the
  frozen per-row reference (`_redact_array_reference` `:65`, `_truncate_array_reference` `:120`),
  which round-trips every value through `to_pylist()` and Python.
- Callers that hand these kernels Arrow arrays straight from the source: the out-of-core route
  (`execution/out_of_core/_mask.py:216`, `:221`) and native scalar wrappers
  (`execution/native/_kernels_scalar.py:98`, `:141`). The auto-chunk dispatcher reaches those native
  wrappers through `execution.native.run_mask_chunked`. This is the route that produced the measured
  100M-row gap, so changing the shared guards closes that gap. The pandas handlers also call the same
  kernels (`_strategies/_redact.py:59`, `_strategies/_truncate.py:115`); they reach the new branch when
  their pandas column converts to `large_string`, while an Arrow-to-pandas round trip may already have
  normalized it to `string`.
- `tests/unit/kernel/test_scalar_vectorized_parity.py` pins today's behavior: `large_string`
  is in the dtype sweeps (`:221`) and in the route-spy cases that must take the reference
  (`:387`, `:432`).
- 2026-09-21 deferred this as a "defensive add" (`2026-09-21-phase5-native-operator-expansion.md`,
  update at the top). The source-type table above shows it is a common input, not an edge case.

## Measurements (before)

Host: this cloud container, 4 vCPU, Python 3.11.18, pyarrow 24.0.0, no native companion. Indicative,
not reference-host numbers.

Kernel only (`large-string-evidence/kernel_bench.py`): 2,000,000 rows of `user{i}@example.com`, 10%
null, one warm-up then five timed runs, median (min to max):

| Call | `string` | `large_string` | Slowdown |
|---|---|---|---|
| `redact_array(redact_with="X")` | 0.026 s (0.025 to 0.027) | 1.420 s (1.351 to 1.528) | 55x |
| `truncate_array(length=4, keep="head")` | 0.043 s (0.042 to 0.045) | 1.806 s (1.542 to 1.913) | 42x |
| `truncate_array(length=4, keep="tail", mask_char="*")` | 0.239 s (0.237 to 0.261) | 1.989 s (1.852 to 2.450) | 8x |
| `large_string` to `string` cast | | 0.001 s (0.001 to 0.002) | |

End to end (`large-string-evidence/run_probe.py`): `run_pipeline`, one table, `redact` on one column
and `truncate` on another, 2,000,000 rows, Parquet source; two single runs each:

| Cell | `string` | `large_string` | Reference calls (redact, truncate) |
|---|---|---|---|
| resident `pq.read_table`, no sink | 0.35 s, 0.22 s | 3.23 s, 3.88 s | 0, 0 vs 40, 40 |
| `LazySource` + `ParquetTransactionalSink` | 0.49 s, 0.49 s | 3.64 s, 4.23 s | 0, 0 vs 40, 40 |

Both cells ran the auto-chunk lane (`auto_chunk.mode == "chunked"`). With `large_string` the per-row
reference ran on every chunk, and the whole job was about 8 to 17 times slower. The 2026-09-21 note
recorded the same gap at 100M rows on the native chunked route: about 97 s for a `large_string`
source against about 1.4 s (`redact`) and 3.6 s (`truncate`) for `string`.

## Established solutions

- Arrow defines `string` and `large_string` as the same logical type (UTF-8 values) with 32-bit or
  64-bit offsets (Arrow columnar format, "Variable-size Binary Layout"). A cast between them copies
  offsets only and leaves the value bytes unchanged. pyarrow's safe cast from `large_string` to
  `string` raises `ArrowInvalid` when the data does not fit 32-bit offsets; it never truncates.
- The engine already treats the two as one text type (`src/decoy_engine/_arrow_types.py`,
  `is_text`; module docstring: "a parquet read keeps whichever the file declared, so every check for
  'text' must accept both").
- Converting to one string layout at the boundary, then running one kernel, is the common pattern:
  Polars and DuckDB each keep a single internal string representation and convert Arrow input at
  the edge, rather than keeping a kernel per offset width.

## Reuse inventory

- `src/decoy_engine/_arrow_types.py` owns the `string`/`large_string` rules; `narrow_text` goes there, next to `is_text`.
- The existing fast paths and frozen references in `src/decoy_engine/kernel/_scalar.py` are reused as they are.
- The differential harness and route spies in `tests/unit/kernel/test_scalar_vectorized_parity.py` are extended, not copied.

## Recurring defect classes

| Class | Applicability | Closing structure | Sentry or property test | Mutation |
|---|---|---|---|---|
| 1 | Anchored value validation | N/A: no regex or token validator changes. | N/A | N/A |
| 2 | Strict wire and stored types; cleanup | N/A: no wire or stored model changes. | N/A | N/A |
| 3 | No exception context or leaked state | N/A: no new raised error or error surface. | N/A | N/A |
| 4 | Versioned read models and routes | N/A: no persisted format or reader changes. | N/A | N/A |
| 5 | Normalized guard scanners and referential checks | N/A: no scanner changes. | N/A | N/A |
| 6 | No private-module imports for untrusted boundaries | N/A: no cross-package import changes. | N/A | N/A |
| 7 | No hidden CI failures or TOCTOU checks | N/A: no CI or check-then-use changes. | N/A | N/A |
| 8 | One input trust class per entry point; no weak split | N/A: no entry point or trust split changes. | N/A | N/A |
| 9 | Mutations on the final head after refactor | Required | Record the final HEAD. | Rerun the central-helper mutation. | Remove either guard call; the guard test must fail. |
| 10 | Checked allowlisted helpers and frozen sentries | N/A: no sentry allowlist changes. | N/A | N/A |
| 11 | No raised caps | Required | Keep `_scalar.py` at or below 235 lines. | Run the size gate. | Raising the ceiling is rejected. |

## Design

Add `narrow_text(array)` to `src/decoy_engine/_arrow_types.py`, the existing owner of the
`string`/`large_string` equivalence rule. It returns `string` unchanged, safely casts
`large_string` to `string`, and raises for any other type. Both guards call it at the top of their
existing `try` after `combine_chunks()`:

```python
v = values.combine_chunks() if isinstance(values, pa.ChunkedArray) else values
if is_text(v.type):
    v = narrow_text(v)
    v.validate(full=True)
    ...
```

Everything after normalization is unchanged. `_arrow_types.py` is a bottom leaf, so importing its
public helper into `kernel/_scalar.py` respects the layer contract. No other kernel has the same
string-only fast-path guard: these are the only two `v.type == pa.string()` guards under
`src/decoy_engine/kernel`.

Why this is safe:

1. **Same output.** The reference turns every value into a Python `str` and builds
   `pa.array(..., type=pa.string())` for truncate, or an inferred array (string for a string
   `redact_with`, `null` when all values are missing) for redact. The fast path already matches that
   for `string` input. After the cast the input is a `string` array with the same values and null
   mask, so the existing parity proof covers it. `source_types.py` checks this for all three calls
   on 2M rows (`cast-parity True`).
2. **Invalid UTF-8 still matches.** The cast does not validate UTF-8 (checked: a `large_string`
   holding `b"\xff\xfe"` casts without error); `validate(full=True)` runs after it, raises
   `ArrowInvalid`, and the `except Exception` sends the call to the reference, which raises the
   same error class as today.
3. **Over 2 GiB still matches.** The cast raises `ArrowInvalid`, which is caught, and the reference
   runs as today. Engine batches are about 1M rows, so in practice this does not happen. The
   reference's own `pa.array(..., type=pa.string())` has the same 2 GiB limit, so the fast path is
   no narrower than the reference.
4. **Sliced arrays and chunked arrays.** `combine_chunks()` already runs first; a cast of a sliced
   array keeps the slice's values. Both are covered by the existing sliced and multi-chunk tests,
   which gain `large_string` versions.
5. **Frozen references stay frozen.** Only the guard changes; `_redact_array_reference` and
   `_truncate_array_reference` are not touched.

Rejected:
- **Run the compute functions on `large_string` and cast the result.** pyarrow's `utf8_*` and
  `if_else` accept `large_string`, but the output would then need its own cast back to `string`,
  with the same 2 GiB limit, and every compute call would need a parity check for both widths.
  One input cast is smaller and keeps one tested path.
- **Cast at each caller** (out-of-core `_mask.py`, native `_kernels_scalar.py`, the auto-chunk lane).
  Three places to keep in step, and a new caller would miss it. The kernel guard is the one entry
  point.
- **Cast at source read** (`LazySource`, CLI reader). That changes the source schema seen by
  passthrough columns, profiling and the post-scan, so it is a much larger change in behavior.

## Acceptance tests (land the assertions first, red, then the fix)

The scalar parity and route-spy cases live in
`tests/unit/kernel/test_scalar_vectorized_parity.py`; helper and route tests stay with their owning
modules:

1. Move the `large_string` cases out of `test_route_spy_redact_excluded_inputs_take_reference`
   (`:387`) and `test_route_spy_truncate_excluded_inputs_take_reference` (`:432`) into the
   fast-path spy tests, asserting the reference is not called. These two are the red tests before the
   fix.
2. Add `large_string` cases to the differential harness for: the full `truncate` matrix
   (`test_truncate_matrix`, every `length`, `keep`, `mask_char`), the redact sweep, sliced arrays,
   multi-chunk chunked arrays, all-null, empty and empty-chunk inputs, the Unicode NFC, NFD and NUL
   case, and invalid UTF-8 bytes (built with `pa.Array.from_buffers` on `large_string`) that must
   still raise like the reference.
3. Unit-test `narrow_text` for identity on `string`, value/null/slice parity on `large_string`, and
   rejection of a non-text array. For the over-2-GiB fallback seam, monkeypatch
   `_scalar.narrow_text` to raise `pa.ArrowInvalid`, then assert each dispatcher calls its reference
   exactly once and matches today's result. Do not build a real 2 GiB array in unit tests.
4. End to end (`tests/unit/execution/`, small): `run_pipeline` over a Parquet file written with
   `large_string` columns, `redact` and `truncate`, output equal to the same run over a `string` file,
   and the reference spy shows no calls. Assert route evidence says `chunked` so this proves the
   measured native auto-chunk lane, rather than a pandas decline.
5. Add a central-mechanism guard test that wraps `_scalar.narrow_text`, calls both dispatchers with
   `large_string`, and asserts the helper was called once by each. Mutating either guard back to an
   inline cast or omitting normalization makes it red.

Speed is checked once, by hand, with `large-string-evidence/kernel_bench.py` before and after; no
timing assertion goes into CI.

## Acceptance

- [ ] Tests 1 to 5 pass; the full `tests/unit/kernel` and `tests/native` suites pass unchanged.
- [ ] `kernel_bench.py` shows `large_string` within 1.5 times the `string` time for all three calls,
  recorded in the PR description with host and versions.
- [ ] `run_probe.py` shows zero reference calls for the `large_string` cells.
- [ ] Docstrings of both dispatchers and the test module say `large_string` is admitted via a
  cast; the 2026-09-21 plan's deferred note is marked done.
- [ ] `_scalar.py` stays under the module size ceiling (235 lines today).

## Placement

| Change | Location | CODEMAP placement | Existing neighbor |
|---|---|---|---|
| Shared text narrowing rule | `src/decoy_engine/_arrow_types.py` | Shared Arrow type rules | `is_text` |
| Guard calls | `src/decoy_engine/kernel/_scalar.py` | Pure Arrow masking kernels | `redact_array`, `truncate_array` |
| Parity and guard tests | `tests/unit/kernel/test_scalar_vectorized_parity.py` and `tests/unit/test_arrow_types.py` | Unit tests mirror source ownership | Existing scalar/type predicate tests |
| Route proof | Existing file under `tests/unit/execution/` beside auto-chunk route tests | Execution route tests | Existing `run_pipeline` auto-chunk tests |

## Enumerations

### Exit paths

- Text narrowing succeeds, then the existing fast path returns from `src/decoy_engine/kernel/_scalar.py:82` or `src/decoy_engine/kernel/_scalar.py:155`.
- Narrowing, validation or compute failure reaches the existing reference fallback in the same dispatcher.

### Routes

- Out-of-core calls the shared guards at `src/decoy_engine/execution/out_of_core/_mask.py:216` and `src/decoy_engine/execution/out_of_core/_mask.py:221`.
- Native scalar and auto-chunk call them through `src/decoy_engine/execution/native/_kernels_scalar.py:98` and `src/decoy_engine/execution/native/_kernels_scalar.py:141`.

### FK shapes

- N/A: this change does not read or write foreign keys.

### Fields

- N/A: this change adds no wire, stored or record fields.

### Output surfaces

- Kernel return values retain the existing values, null mask, container and Arrow type contract.
- Benchmark timings and reference-call counts appear only in the PR evidence, not product output.

## Slices

One slice, one PR: the `narrow_text` helper, both dispatcher guards, the tests and the changelog fragment. About 30 production lines.

## Pre-mortem

- The cast hides a real difference: a value that differs only in offset width. Arrow defines none, and the differential harness compares every case byte for byte against the reference.
- A caller hands the kernel a type the plan did not list (for example `string_view`). `narrow_text` leaves it alone, so it keeps today's reference path; a test pins that.
- The flipped route-spy tests are deleted instead of moved, so the slow path could come back unseen. The handoff says move, and the gate checks the diff.
- Timing varies by machine. The 1.5 times check is manual evidence in the PR, never a CI assertion.

## Frozen contracts

None change. Output bytes, digests, reason codes, record shapes and the frozen references `_redact_array_reference` and `_truncate_array_reference` stay as they are. No golden or snapshot update. The PR still carries the compatibility contract section 9 checklist.

## Risk

R1. One added branch in a guard that is already total and non-raising: any failure in it lands on
the reference, which is today's behavior. No output change, so no golden or snapshot update.

## Evidence files

`docs/plans/large-string-evidence/`: `source_types.py` (writer table and cast parity),
`kernel_bench.py` (kernel timings), `run_probe.py` (end-to-end timings and reference-call counts).
