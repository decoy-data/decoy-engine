Status: plan

# PREFLIGHT-ARROW-PROFILE | Bounded Parquet profiles for unrepresentable dates and times

Owner: Cam. Revision 6, 2026-11-25. Engine PR #805 at `04459013f`. The behavior oracle is engine `9f7bb1f4a`, which already contains the S1a move. This revision replaces the S1b design, acceptance criteria and mutation gate. The implementation and release gates are pending.

Rules consulted: dev-rules README, 00-universal, risk-and-exceptions, development-loop, bugfix, reuse-first, proportionality, architecture, cross-cutting-concerns, testing, api-and-compatibility and catalogs/recurring-defects. Placement follows engine CODEMAP at the oracle commit.

## 1. Scope and guarantee

A valid Parquet file can contain a time with a fractional microsecond or a date outside Python's year range. Arrow reads the file. Conversion of the bounded sample to pandas fails before the CLI can select a route that handles the value. Capacity samples the first 10,000 rows by default. The first execution chunk is a separate read.

S1b fixes this preflight failure for the flat Parquet schemas in §4. Every bounded profile that succeeds on base must still succeed and yield the same complete table profile with the same ordered columns. This includes supplied resident tables, pandas-written files, the active pandas options and supported dependency versions. Base failures can become successes only in the specified Parquet recovery. A conversion failure that still escapes the profile boundary has value-free public text. There is no promise of equivalent raw exception messages.

This is a compatibility fix, with a bounded conversion cost. It withdraws the earlier zero-pandas guarantee for ordinary successful samples, the resident length exception and the proposed new refusals. General Arrow-native profiling is a separate optimization. No dependency floor or wire contract change is needed. Risk is R2 because routing and pricing share this input.

## 2. Established solutions and callers

The original investigation compared PyArrow, pandas, DuckDB and Polars. PyArrow documents the restoration of pandas indexes and the conversion of Arrow dates and times to Python objects. Delegate those decisions to the existing reader. Use Arrow's exact counts on the original temporal array only when the reference conversion fails. [Arrow pandas integration](https://arrow.apache.org/docs/python/pandas.html) and [Arrow compute](https://arrow.apache.org/docs/python/compute.html).

Read the following anchors with `git show`. Paths below `profile/`, `execution/` and `safe_output/` start in `src/decoy_engine/`.

| Mechanism | Existing owner | S1b decision |
|---|---|---|
| Bounded sample, total and shape input | Base `profile/_source.py:217`, `profile/_readers.py:408,477`, `profile/_cloud_readers.py:109,264,383` | Keep one bounded sample. Local, S3 and GCS expose the same batch collector already added in #805. |
| Resident conversion | Base `profile/_readers_resident.py:16` | Use the entire base operation, including its second conversion after a failed first attempt. |
| pandas column statistics and Arrow statistics | Base `profile/_walk.py:41,157,242` and `profile/arrow/_walk_arrow.py:27` | Reuse both walks. The latter already serves the chunked path. |
| Key flags and duplicate messages | Head `profile/_types.py:172` and `_field_names.py:23`, used by `execution/_guards.py:49` | Keep one key rule and one duplicate formatter. Run duplicate checks at the same logical stage as base. |
| Metadata reconstruction | Head `_pandas_meta/_columns.py:92,133,147` | Remove the S1b hint interpreter and its redundant entry walk. Preserve S1a helpers and estimator/output consumers. |
| Error rendering | Base `safe_output/_exception.py:79`, `execution/capacity.py:324` | Use the public safe-output label API. Capacity can interpolate only the already-safe profile exception for this failure. |

The production callers are capacity, job estimate, pipeline routing facts and physical snapshot. CLI preflight calls capacity. A plain execution that cannot ingest the value still raises the existing coded full-frame error. Scan, init, the full-residency profile and the first-chunk profiler keep their own contracts.

## 3. The base frame is the compatibility boundary

1. Preserve descriptor precedence, source format, seed, relationships, bounded cap, row-count exactness, and the proof read for estimated counts. Keep full residency, CSV and fixed-width on their existing routes.
2. For a resident table, call `sample_frame(n)` once. Its first operation converts the entire slice with metadata. On the exceptions it handles, base tries each physical column, casts failures to text, rebuilds the **whole** table by physical names without metadata and converts that table. Pass the actual resulting frame to the base walk with the original Arrow schema. This is the only resident fallback. Running a schema probe or an Arrow walk before this call can reject a successful profile. Splicing a converted column into the original logical layout changes the oracle.
3. For local, S3 and GCS Parquet, obtain the same sliced table the base reader converts. Factor the existing collector once for both sample APIs. For a nonempty stream infer the table schema from the collected batches exactly as base does. Use the reader schema for an empty stream. Preserve range reads, policy-bound handles, requested batch size, and slice before conversion. Decide from the sampled bytes, including their metadata. A separately fetched schema must never be imposed on a nonempty batch. Preserve the base shape-schema input to the pandas walk.
4. First try the actual whole-sample Parquet conversion, including any pandas metadata. If it succeeds, pass that frame to the existing walk and finish. An error in the walk is never permission to try temporal recovery. This ordering preserves successful results without predicates for footer layout, dictionary decoding, pandas options, dependency versions or extension dtype construction.
5. Only a ValueError (including ArrowInvalid) or OverflowError from whole-sample conversion may enter §4. Other failures take §5. Leave the handler before trying recovery. Save only the safe label needed for a possible error. Do not cache a partial profile or publish a result until every column has completed. For a table that cannot recover, use §5.

## 4. Narrow Parquet recovery

Use one recovery decision in the bounded profile dispatch. The closed recovery schema has unique physical names, **no** pandas schema metadata key (including empty or malformed bytes), and only these physical types: date32, time64[ns], plain UTF-8 string and ordinary signed or unsigned integers. Require at least one date32 or time64[ns]. Exclude extension and dictionary types, even when their storage matches. The scope covers the roadmapped time/date with email and the FK pricing fixture. Decimal and nested companions take the safe failure on a failed conversion. A successful conversion of any schema has already returned in §3.

Work from the same bounded table, in physical order. For each field use a one-column projection with PyArrow's ordinary table conversion. Pass each successful projection through the existing pandas walk with its base arguments, the true total and source shape. This preserves per-column string inference, null widening and length rules. A failed companion conversion ends recovery. Never rebuild or recast a sibling column.

For a failed temporal projection, verify that the physical values explain the failure. Inspect integer storage with Arrow, including all chunks, ignoring nulls. For time64[ns] require all valid times in the civil day (0 inclusive, 86,400,000,000,000 exclusive), with at least one count not divisible by 1,000. For date32 require a day outside Python's representable range, measured from 1970-01-01 using the standard library's date bounds. Accept only a date/time conversion error (ValueError, including ArrowInvalid, or OverflowError) at that conversion site. Other failures go to §5. Require at least one such failed projection before emitting any recovered profile.

Use the S1a `arrow_column_profile` on that original temporal column. Its profile has the ordinary temporal object label, counts distinct non-null physical values, and has no string lengths. Apply the same table total, sampled flag, shape and shared key rule as the pandas columns. Assemble exactly one profile per field in original order. This column-local recovery runs only after whole-table base failure. There is no per-column dictionary combine, no schema-hint decode and no speculative extension probe anywhere in S1b. Preserve the S1a chunked caller and its tests.

## 5. Public errors

At the common bounded resident/Parquet profile boundary, protect sample acquisition, schema access, conversion, recovery and the walk, including the base branch. Preserve file-access exceptions whose class the existing file-access policy requires and existing trusted coded failures. For a data/metadata failure return only a closed label from `safe_error_type(exc).value` to the caller of the guarded operation. Catch ordinary exceptions at this narrow boundary, including KeyError, TypeError, overflow and Arrow errors. Do not catch process-control exceptions. Raise a fresh ValueError after leaving **all** active handlers with exactly `bounded source profile failed (<label>)`. Neither the class name supplied by a producer nor its exception text belongs in the message. Check that legitimate file-access decisions still propagate. Preserve the existing shared duplicate-name message for a confirmed duplicate of the base frame's rendered labels. A duplicate physical name alone cannot preempt a successful metadata conversion.

This protects direct callers and capacity, which catches ValueError and currently embeds its text and chains it. Assert the inner exception has no context or cause. The outer capacity error may chain the sanitized error. Keep the PR's full-frame change that raises the coded error after the handler. G-5, broader capacity and CLI exception plumbing outside this profile operation, remains separate.

## 6. Acceptance oracle and reader matrix

Build the reference from pinned base behavior, independent of PR dispatch, table assembly and key helpers. In particular a call to a modified reader from both sides cannot prove sample parity. Use an isolated base run on the same fixture bytes/options or a golden from it with the full table profile. For the catalogue record reader, versions, actual sample schema including metadata, writer outcome, base conversion/walk outcome and expected candidate outcome before testing the candidate. Compare every dataclass field and column position, including names, both length fields, shape, total, exactness, nulls, distincts, sampled/candidate, PK, FK target and PII. Ignore only the outer Profile creation timestamp. Use equal seeds. Test full samples, a capped prefix and zero rows.

| ID | Reader and input | Required result |
|---|---|---|
| AT-1/2 | Local Parquet, S3 and GCS range fakes. Four rows with temporal values 0, 1, 2 and 3,000,000 days (also -1,000,000), or 0, 1000, 2000 and 3,600,987,654,321 ns, plus an email field. Repeat with one null among five rows. | Base conversion fails. Recovered temporal column has object dtype, four distinct, respectively zero or one null, no lengths. Compare every other field with a representable, equally distinct control. Assert base-equal companions and order with the bad field first, middle and last, including two bad temporals. Local capacity returns NOT_APPLICABLE. FK price and needed_bytes equal the good parent/child control. |
| AT-3 | Both readers over the type catalogue, with/without nulls, multi-chunk inputs, list/struct/map, scalar and empty sources. | Successful base profile always compares equal. Pin resident time64[ns] counts [1,2,3,4,5] as a base success with text recovery. Parquet base raises on those values and §4 recovers. Add representable [1000,2000,3000,4000,5000] for successful Parquet parity. Resident date64 uses base; Parquet written from date64 reads back as date32, so test its actual days. Out-of-day times follow the reader's base outcome without recovery. |
| AT-3b | Probe E nullable, categorical, timezone, period and interval corpus with range, named and filtered indexes, full and empty. Separate one-field string fixtures with nulls. | On the review stack assert `pd.array(..., dtype="string[pyarrow]")` writes (object,string), and `pd.ArrowDtype(pa.string())` writes (unicode,string[pyarrow]). Check actual bytes and whole-profile equality for each. Both use base conversion. |
| AT-3c | Start with DataFrame column "01". Keep pandas_type unicode and change only column_indexes[0].numpy_type to int64. Separately delete index_columns. Include reordered/dropped fields, bad hints, non-object entries and malformed blobs. | On the review stack the first profile reports "1". The missing required key fails conversion and reaches §5. Test local and resident from the damaged input itself. Verify the clean control reports "01". No metadata-bearing input enters recovery, including a bad temporal with an otherwise ordinary pandas footer. |
| AT-4 | Instrument dispatch through _profile_one_source on a resident success, Parquet success, recoverable Parquet, and ineligible Parquet failure. | One bounded sample. Success calls the base conversion, then the pandas walk. Only the failed eligible Parquet conversion may run the Arrow profiler, once per proven bad temporal. Count zero Arrow calls on companions. Compare RNG state. |
| AT-5 | Actual Parquet time64[ns]=[123456789] plus decimal128. Also truncated and wrong-format files. | Temporal/decimal base raises and recovery declines. Direct error matches §5, with neither cause nor context. Actual estimate_job_capacity raises capacity_source_unprofilable. Assert the marker absent from str, repr and formatted chain on both public calls. Corrupt files retain the public capacity code. |
| AT-6/9/10 | Bad row 0, 9999, 10000 or 80000 in 80,001 rows. Local, S3 and GCS bounded reads, multiple batches and empty sources. | True count 80,001, exact, sampled, statistics from exactly the first 10,000. No RNG draw or whole-object download API call. A range may cover all bytes of a small file. Check schema metadata and exact prefix against base, including a batch with different metadata from the separately supplied schema. Exercise None-cap behavior, text-reader proof reads and full residency controls. |
| AT-7 | Plain pipeline, supplied resident and lazy Parquet, bad date/time. | Existing full_frame_value_unrepresentable with no original value in text or formatted traceback, cause and context both None. Verify CLI chunked/default and no-native behavior in S3. |
| AT-8 | Resident supplied table made from pandas Int64 v=[2**53,2**53+1,None] with physical stored index k=[1,2,3]. Replace t in place with time64[ns]=[1,2000,3000], retaining metadata. | Compare entire table with base. Columns v,t,k in order. v is float64 with one null and one distinct, t has mean and maximum string lengths 18, k is exposed with three distinct. On a good-time twin v is Int64 with two distinct and k is hidden. Include good and bad temporal with nulls and no footer. |
| AT-11 | S1a schema/import guard, native rev9 profile/catalogue, import-linter, shape and reader sentries. | Existing caller results and access contracts hold. Matrix covers each actual sample_table implementation. Seed an ordinary missing reader and check the guard fails. |
| AT-12 | Footerless pandas.period with BAD-CANARY frequency and storage [1,2]. Write/read a real Parquet twin. Repeat with unknown timezone in data and on stored index. | Resident period returns the base profile of strings "1","2", dtype object, two distinct, lengths 1 on the review stack. Parquet period conversion fails and §5 hides the canary, including through capacity. For timezone pin the outcome at the actual reader stage, sanitize any in-scope failure and compare every successful profile. No schema-only refusal. |
| AT-12f | Footerless float64 [inf,1.0]. Set mode.use_inf_as_na True and False in a restoring option context on pandas 2.3.3. | True gives one null, one distinct, no candidate key. False gives zero nulls, two distinct and a candidate. Both local and resident profiles equal base. |
| AT-13 | Footerless string, large_string, dictionary of each text width. For dictionaries cover signed int8/16/32/64, an unsigned width and a non-text dictionary. Include nulls and repeated values. | Test each against its own reader with inference off and on. On 2.3.3 use the real option with a distinguishing plain-text null cell. On 2.2.3 use that version's base results even when the option exists. On a floor lacking the option compare in its native state. There is no version/option classifier to emulate. Assert the exact recovery schema predicate separately with one type changed per cell, including dictionary, decimal, date64, float, missing temporal, duplicate names and pandas metadata. |
| AT-14 | Resident: indices [0,1] over ["a",None], then [1,0] over ["c","d"], both int32. Also a single null dictionary, repeated dictionary values, narrow indices with 200 categories across chunks, and positive/negative out-of-day times. | Resident uses the base reader for every fixture. On the review stack the two-chunk result is object with one null and three distinct. Do not unify, widen or decode the input before that reader. Parquet cannot write the null dictionary on this stack: assert the writer failure separately. For repeated values assert the written/read-back dictionary deduplicates and compare that read-back profile to Parquet base. Pin actual storage for the other writable cells. |

AT-4 also injects a KeyError at the whole-table conversion of an otherwise recoverable temporal sample. Assert the safe label and zero recovery calls. AT-5 covers duplicate rendered names and existing keep-class file-access cases. Preserve a duplicate message only from the actual shared duplicate check. Test a conversion exception carrying those words plus a marker.

For the previous AT-12 regressions also keep the legacy-name truncate compile outcome, footerless period/interval, masked Float64 and ArrowDtype NaN payloads, signed zeros, period-min NaT, large binary, dictionary tokens, 1e999 and the 1,000-digit footer integer at interpreter limits 640, 4300 and 0. Compare each reader with base under the identical option/limit and restore process state. No blanket family-level exception exemption, no oracle substitution with an undamaged input and no skip for a writer failure that a resident fixture can exercise.

## 7. Reachable mutations and final-head gate

Each row describes an edit to code exercised by its named test. Apply edits individually to the clean final implementation SHA. Record the failing assertion and restore the head after each. A surviving or unexecuted edit fails the gate. These rows replace the rev-5 M-1 through M-45 ledger. There is no gate on code deleted by the redesign.

| Mutate | Test that observes the changed result |
|---|---|
| Route a resident table through plain Parquet conversion, bypassing _frame_of. | AT-8 fails to return v,t,k. AT-12 loses the successful period profile. |
| Call the recovery decision on whole-frame success. | AT-4 counts one decision on the successful Parquet sample where zero is required. |
| Delete only the pandas-key exclusion. | AT-3c: use the bad flat time64[ns] + email fixture with a valid pandas blob from its representable twin. Assert base conversion fails on the temporal value and read-back metadata is present. The mutant returns a profile where §5 requires an error. |
| Drop the decimal exclusion on failed conversion. | AT-5 would return a recovered profile. |
| Remove date32 or time64[ns] from eligibility, separately. | AT-1/2 fail to recover the corresponding actual file. |
| Use a bad column's text representation for its statistics, or send its email companion through the temporal profiler. | AT-2 lengths and AT-4 per-field call identities. |
| Accept out-of-day times on a failed projection. | A real failed Parquet time64[ns] projection containing both a fractional civil time and an out-of-day time must give §5. Pin the read-back counts before the test. |
| M-4 replacement: change distinct == row_count to distinct <= row_count in the shared candidate-key rule. | AT-12f True, or a complete nonempty [7,7] integer profile, would become a candidate. No capped-sample identity is required. |
| Remove the cap slice; swap sample and true total; lose a PK or FK target, one at a time. | AT-6 oversized terminal batch passed directly to collector, AT-6 capped table and AT-1 FK profile control, respectively. |
| M-10: remove the ArrowNotImplementedError handler around count_distinct. | Direct S1a arrow_column_profile on a dense union with int/string children: first assert the real Arrow kernel lacks a handler on the test stack, then require a returned column with distinct_count None. This caller reaches the kernel without bounded admission. |
| M-23 replacement: call the recovery dispatcher twice with the same failed sample. | Count from _profile_one_source in AT-4, including a table with several columns: one recovery decision per failed eligible sample and zero per successful sample. A direct Arrow column call has no metadata decode. |
| Use raw exception text, or raise the sanitized error inside the conversion handler. | AT-5 and AT-12 marker and chain checks; AT-7 for the separate full-frame raise. |
| Use the separate schema to relabel nonempty batches, or skip a Parquet implementation in the existing sentry. | AT-9 mismatch control and AT-11 seeded conformance guard. |

Run the final-head targeted regressions, reader/shape/import/error-text sentries, then the full engine suite. Exercise supported pandas floor behavior with the real reader where feasible and record versions and unrun environments. Do not claim kill credit for changing an algorithm in the oracle itself. Record known fixture write limits separately from passing reader tests.

## 8. Placement and delivery

| File relative to the engine | Placement at base CODEMAP.md | Neighbor or reuse |
|---|---|---|
| Existing PR profile sample and walk code in profile/arrow/ | Line 281, source readers and profile types | _arrow_sample.py beside _walk_arrow.py. Keep cross-package imports on the package facade. Put dispatch and the ordinary pandas walk in profile, their existing owner. |
| Existing PR tests under tests/unit/profile/ and tests/unit/execution/ | Lines 281 and 307, unit tests mirror the package | Extend the bounded profile, metadata, reader contract and capacity tests. Use existing files. |
| changelog.d/preflight-arrow-profile.md | Line 302, changelog fragments | Describe the narrow Parquet recovery and sanitized failures. |

Build on S1a. Rework PR #805 in place. Expect one bounded recovery operation, the existing three Parquet sample methods and collector, and the shared error boundary. Remove resident Arrow dispatch, bounded metadata decoding, version/option predicates and the associated PR-only kernel extensions. Compare the resulting changes against both pinned commits. Keep shared S1a APIs for other consumers. Remove the PR-only resident sample_table method. Preserve S1a estimator, output sanitization and first-chunk behavior. For the full-frame change, bind both lossless-int census entries and the F29 producer inventory to the actual owners and verify the registered runtime reason. Keep the _read_parquet_sample file-access entry. Patch the collector at its lookup site in the one-batch read test. Add no public product API, flat package, persistence format, reason registry or dependency pin. Update CODEMAP and existing sentry inventories only for actual owners and call sites. Respect import layers, existing ceilings and normalized scanner coverage. Do not raise caps.

The prior D7 pandas-floor proposal remains a separate owner decision. S2 releases the tested engine through the normal fragment/stamp process. S3 repins the CLI after engine release and CLI #399. Through real CLI commands verify that the three eligible date/time fixtures pass validate preflight, chunked execution on the native default publishes the original values, no-native reports its existing coded failure, and plain execution reports full_frame_value_unrepresentable without a value or output file. Keep truncated-file refusal coverage and the sample boundary at row 10,000. Update CLI docs for exactly the supported schema. G-1 (plain-route passthrough), G-4 (scan/init and first chunk), G-5 and broader Arrow acceleration remain separate.

## 9. Review disposition

Base probes with pandas 2.3.3 and PyArrow 24.0.0 confirmed the resident companion and index result, restored label, missing-key failure, period and dictionary outcomes, float-option counts and both string footer pairs. Real profile and capacity calls exposed the frequency and numeric canaries on base. The direct S1a dense-union column call returned distinct_count None. The fractional/out-of-day time sample survived Parquet round trip and failed conversion. These probes establish reachability. Implementation and release gates remain pending.

| Closed finding | Design and acceptance |
|---|---|
| V1 | Resident whole-frame metadata loss and stored index: §3, AT-8. |
| V1 | Invalid period, resident success and safe Parquet failure: §§3, 5, AT-12. |
| V1 | Restored label and required index descriptor: §3, AT-3c. |
| V1 | Infinity option and false candidate key: §3, AT-12f. |
| V1 | Two dictionary chunks with a null category: §§3, 4, AT-14. |
| V1 | Decimal companion and leaked time value in capacity: §§4, 5, AT-5. |
| DESIGN | Reader-specific catalogue and read-back schemas: §6, AT-3/13/14. |
| DESIGN | String footer tokens and inference versions: §6, AT-3b/13. |
| DESIGN | Dictionary widths and text inference states: §6, AT-13. |
| DESIGN | Reachable M-4/M-10/M-23 and final-head gate: §7. |
