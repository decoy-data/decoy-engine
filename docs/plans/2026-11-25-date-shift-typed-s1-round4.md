# DATE-SHIFT-TYPED S1: round 4 rule and acceptance tests

Status: plan

Rules consulted: 00-universal, development-loop, bugfix, cross-cutting-concerns, testing,
architecture, recurring-defects catalog.

This note replaces the rule in `2026-11-25-date-shift-typed-s1-round3.md` for PR #790. Round 3
read an unrepresentable temporal value as null only after pandas failed to convert it. Codex
round 4 found two holes in that order of work:

1. With pandas `date32[day][pyarrow]` metadata, `to_pandas()` does not fail, so the check never
   runs. The year-10000 value stays non-null and a full scan raises `ScanSourceError` wrapping
   `OverflowError`.
2. The fallback asks Arrow for the year. The year kernel wraps on a large day count, so the
   check misses the bad cell and then nulls the whole column, valid neighbours included
   (date32 `[0, 23936616, 1]`). A `time64[ns]` column with one sub-microsecond value
   (`[1000, 1001, 2000]`) also lost all three values.

## Rule

Every temporal Arrow column that enters a profile or scan frame is bounds-checked per cell on
its physical integer, before any pandas conversion and whatever the pandas metadata says. Only
an out-of-range cell becomes null; its valid neighbours keep their values. No error or
statistic carries the value.

Non-goals: masking routes (they keep their own coded refusals), temporal values nested inside
lists or structs, and `duration` columns (pandas holds every duration).

The bounds come from one table, `temporal_bounds` in `decoy_engine/_arrow_types.py`. That module
is in the bottom import tier, so `profile/` can import it; `transforms/` cannot be imported from
`profile/`.

| Arrow type | Physical bound (inclusive) | Why |
|---|---|---|
| `date32` | day `DATE32_MIN_DAY` to `DATE32_MAX_DAY` | years 1 to 9999, `datetime.date` |
| `date64` | the same days, in milliseconds | same |
| `timestamp[unit]` | the same days, in `unit`, clamped to int64; one day less at each end with a time zone | the local wall time must also stay in years 1 to 9999 |
| `time32[unit]`, `time64[unit]` | 0 to one day less one tick, and a whole microsecond for `ns` | `datetime.time` holds microseconds within one day |

The existing physical-day check, `date32_in_range`, moves to `_arrow_types.py` with its two
constants and reads the same table. `transforms/date_shift.py` re-exports the three names, so its
callers do not change and the date_shift kernel and the profile read cannot drift apart. The
per-column fallback in `profile_frame` stays only for a type with no per-cell bound (a nested
column), where nulling the column is the only option.

## Choke point

`profile_frame` (public `decoy_engine.profile.arrow`) stays the one Arrow-to-pandas conversion
for profile reads. Section 14 of the main plan moves it into the S1b source-read choke point
(#799), and the guard test that fails on a direct `to_pandas()` in a reader belongs there. This
PR does not add a second guard that #799 would have to delete.

## Acceptance tests (each new case fails on c45292e78)

| Id | Case | File |
|---|---|---|
| R1 | A local Parquet file whose pandas metadata names `date32[day][pyarrow]`, one year-10000 date and two valid ones: `scan_sources(strategy="full")` returns, and no output holds the value | `tests/unit/profile/test_profile_frame_unrepresentable.py` |
| R2 | `profile_frame` on a table with the same pandas metadata nulls the year-10000 cell and keeps the two valid values | same file |
| R3 | date32 day counts `[0, 23936616, 1]`: only the middle cell is null | same file |
| R4 | `time64[ns]` `[1000, 1001, 2000]`: only the middle cell is null | same file |
| R5 | date64, `timestamp[s]` (naive and with a time zone) and `time32[s]` with one out-of-range cell each: only that cell is null | same file |
| R6 | `temporal_bounds(date32)` is `(DATE32_MIN_DAY, DATE32_MAX_DAY, 1)` and `date32_in_range` agrees at each edge | same file |
| A1-A7 | Round 3 cases, kept green unchanged | round 3 files |
| D1, D2 | Round 3 sentry cases, kept green | round 3 files |
| D3 | The `when:` probe fixture carries a namespace and an explicit `date_format`, so the verdict reaches the shared rule and returns `probe:d` (fails today: the namespace check declines first) | `tests/native/test_date_shift_typed_declines.py` |

Mutation for R3 and R4: restore the whole-column fallback for temporal types; both go red.

## Defect classes (plan contract catalog)

| # | Class | Structure that closes it | Proof | Mutation |
|---|---|---|---|---|
| 1 | Value-bearing output | the bad cell is nulled on Arrow before pandas sees it, so no pandas error and no statistic can carry it | R1, A3-A5 literal checks | drop the bound for date32: R1 and R2 go red |
| 2 | Cleanup missing on an exit path | N/A: no resource is opened; `profile_frame` is a pure function | none needed | N/A |
| 3 | State machine and concurrency | N/A: no shared state | none needed | N/A |
| 4 | Route parity and silent fallback | every profile reader (local, S3, GCS, resident, chunked first chunk) calls the one `profile_frame`; the date_shift kernel and the profile read share `temporal_bounds` | A3-A5, R1, R6 | change `DATE32_MAX_DAY` in one place only: impossible, one table |
| 5 | Referential integrity | N/A: no key path changes | none needed | N/A |
| 6 | Untrusted producer | the pandas metadata in the file is ignored for the bound decision; the physical integer decides | R1, R2 | check only after a failed `to_pandas`: R1, R2 red |
| 7 | Check then use on a path (TOCTOU) | N/A: no path is opened | none needed | N/A |
| 8 | Weak tests and overclaimed evidence | every R case and D3 records red on `c45292e78` | builder report | restore the whole-column temporal fallback: R3, R4 red |
| 9 | Behavior-preserving refactor drift | `date32_in_range` and the two constants move with the same values; `transforms.date_shift` re-exports them | existing kernel and canonical-key tests stay green | change a constant: `test_date_shift_typed_kernel` edge cases red |
| 10 | Frozen contract drift | no frozen name changes; the section-9 pinned-types tick is marked as a documented exception in the PR body | compat-preflight | N/A |

## Enumerations

### Fields

- date32, date64
- timestamp (s, ms, us, ns; naive and zoned)
- time32 (s, ms), time64 (us, ns)
- duration: no bound, pandas holds every value

### Routes

Every caller of `profile_frame`:

- `src/decoy_engine/profile/_readers.py:415` (local Parquet, full), `:496` (empty schema), `:500` (sample)
- `src/decoy_engine/profile/_cloud_readers.py:271` (S3), `:392` (GCS)
- `src/decoy_engine/profile/_readers_resident.py:34` and `:37` (resident table)
- `src/decoy_engine/execution/_chunked_profile.py:42` (chunked first chunk)

### Exit paths

- normal return: every temporal cell checked, the frame built once
- fallback return: a non-temporal column fails `to_pandas` and is nulled whole
- raise: none expected; a conversion failure outside both is pandas' own and holds no resource

### FK shapes

N/A: profiling reads key columns as data; no FK logic changes.

### Output surfaces

- `ColumnProfile.to_dict` (A5, R1)
- `scan_set_to_dict(detail=True)` (A5, R1)
- `profile_document` (A5, R1)

## Reuse inventory

`date32_in_range`, `DATE32_MIN_DAY`, `DATE32_MAX_DAY` (moved, not copied); `pyarrow.compute`
comparison and `if_else` kernels for the per-cell null.

## Frozen contracts

None changed. `transforms.date_shift` keeps its names through the re-export.

## Slices

One commit on #790: bounds table and move, `profile_frame` rewrite, reader import, tests, D3
fixture.

## Pre-mortem

- `if_else` lacks a kernel for a time type: R4 and R5 catch it.
- A zoned timestamp at the last day shifts into year 10000 local: the one-day margin covers
  every real offset (under 24 hours).
- A nested temporal column still fails whole: recorded as deferred.

## Size

Touched: `_arrow_types.py` (about +40), `transforms/date_shift.py` (about -10),
`profile/arrow/_frame.py` (rewritten, about the same size), `profile/_readers.py` (one import),
two test files. New public names: `temporal_bounds`; `DATE32_MIN_DAY`, `DATE32_MAX_DAY` and
`date32_in_range` move. No new files beyond this plan.

## Other changes

- `profile/_readers.py` imports `profile_frame` from the public `decoy_engine.profile.arrow`, as
  the cloud and chunked readers do.
- The section-9 checklist tick for `run_mask_chunked` pinned types is marked in the PR body as a
  documented exception: the `date32` pin is recorded in the dated contract entry and section 3.4
  of `docs/compatibility-contract.md`.

## Deferred (V2-LOG)

- Temporal values inside nested types (a list of dates) still null the whole column on failure.
- `__context__` on the coded pandas-route error, as in round 3.
