# DATE-SHIFT-TYPED S1: round 3 acceptance tests

Status: plan

This note extends `docs/plans/2026-11-22-date-shift-typed.md` (on `plan/date-shift-typed`, rev 6)
for PR #790. Round 3 of the gate hit the cap, so each case below was named here before its code
was written. Section 14 of the main plan puts the source-read choke point in S1b (#799). Until
#790 rebases on S1b-2, #790 carries a smaller fix: one `profile_frame` in `profile/arrow/_frame.py`.
That function is dropped in the rebase and its callers take the S1b calls.

## Rule

A source value pandas cannot hold (a date past year 9999, a time with sub-microsecond digits) must
not raise pandas' value-quoting error from any profile read, and must not reach any statistic or
report. `profile_frame` reads such a value as null. It replaces only the failing column on the
original table, so a stored pandas index and the schema metadata stay.

## Acceptance cases (each fails before the change)

| Id | Case | File |
|---|---|---|
| A1 | `run_mask_chunked` with a `date_shift` target and one year-10000 date in the first chunk raises the row-error refusal (`RowErrorsFailedError`), not `ValueError`, and its text holds no date | `tests/native/test_date_shift_typed_out_of_range_chunked.py` |
| A2 | The same date in a later chunk gives the same refusal (control: green before the change, kept as a guard) | same file |
| A3 | S3 Parquet reader with `residency="full"`: `to_frame` on a year-10000 file does not raise and holds no date text | `tests/unit/profile/test_profile_frame_unrepresentable.py` |
| A4 | GCS Parquet reader, same case | same file |
| A5 | Scan of a local Parquet file with one and with 20 identical year-10000 dates: `scan_set_to_dict(detail=True)`, `ColumnProfile.to_dict()` and `profile_document` hold neither `10000-01` nor the day number | same file |
| A6 | A table with a stored pandas index `stored_id` and one out-of-range date gives the same data columns as the in-range table (`['d']`) | same file |
| A7 | In-range dates next to an out-of-range one keep their values (only the failing value is null) | same file |
| D1 | `native_date_shapes` composed outside `declared_casting/` fails the sentry whether the parts are positional, keyword or nested | `tests/sentry/test_typed_date_shapes_one_set.py` |
| D2 | An aliased, relative or from-package import of the private `_canonicalize` module fails the sentry | `tests/sentry/test_public_import_boundary.py` |
| D3 | `when_native_rejection` returns the shared rule's verdict for a known target type (probe by monkeypatching `when_target_rejection`) | `tests/native/test_date_shift_typed_declines.py` |

## Placement

`profile/` stays at 19 direct modules: the conversion lives in the existing `profile/arrow/`
subpackage (`_frame.py`) and is exposed through `decoy_engine.profile.arrow`; `profile/_frame.py`
is deleted. The readers and the chunked caller import the public name. `_readers.py` stays under
its size goal.

## Deferred (V2-LOG)

`__context__` on the coded pandas-route error: see the section-14.9 split. The choke point in S1b
clears it by raising after the handler closes.
