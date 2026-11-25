# F25 G7-1: bounded cloud reads, acceptance cases

Status: plan

Rules consulted: 00-universal, risk-and-exceptions, development-loop, feature-dev, security,
testing, cross-cutting-concerns, catalogs/recurring-defects, Decoy plan contract (vault
`Decoy-Plan-Contract-and-Defect-Catalog`).

Risk: R2. Slice: engine PR 789, branch `feat/f25-g7-1-bounded-cloud`. Covers the S3 and GCS
profile readers (`profile/_cloud_readers.py`) for CSV and Parquet. Revision 2 closes Dennis plan
round 1 (4 BLOCKER, 2 HIGH, 4 MEDIUM, 2 LOW); the finding map is at the end.

**Guarantee.** A cloud read of one object stays bounded per request and per read (caps table
below) and pinned to the version seen at open. Every ranged response is checked for status,
range and length before its body is read, on both providers. Every failure that leaves a strict
read is value-free: no data cell, no input bytes, in the message, `args`, `repr`, notes, cause
chain or logs. A read that `main` completes still completes, with the same frame.

**Non-goals:** SFTP reads; Azure (there is no Azure profile reader in `profile/`); changing the
sample window caps; a `to_frame` working set below `main`'s (the bound is "no worse than
`main`", case 14; streaming the Arrow-to-pandas conversion is V2-LOG); refusing a stored
`Content-Encoding` on S3 (S3 never transcodes; V2-LOG).

## Caps per read and format

| Read | Format | Request size cap | Total bytes | Constant |
|---|---|---|---|---|
| `row_count`, `schema` | CSV | one request for the first window | at most 1 MiB | `_CSV_SAMPLE_WINDOW_BYTES` (`_cloud_readers.py:48`) |
| `sample_frame` | CSV | pieces of at most 8 MiB | window starts at 1 MiB, doubles, stops at 64 MiB, then `sample_window_exceeded` | `_CSV_SAMPLE_WINDOW_BYTES`, `_RANGE_PIECE_BYTES` (`:55`), `_CSV_SAMPLE_MAX_BYTES` (`:53`) |
| `to_frame` | CSV | pieces of at most 1 MiB, streamed | the whole object, never held as one buffer | `_CSV_STREAM_PIECE_BYTES` (`:57`) |
| `row_count`, `schema` | Parquet | pieces of at most 8 MiB | the footer bytes pyarrow asks for; no request overlaps a column chunk | `_RANGE_PIECE_BYTES` |
| `sample_frame` | Parquet | pieces of at most 8 MiB | footer plus the column chunks of the row groups that hold the sample | `_RANGE_PIECE_BYTES` |
| `to_frame` | Parquet | pieces of at most 8 MiB | the whole object as column chunks, never one unsized body | `_RANGE_PIECE_BYTES` |

No read issues an unsized body read, and every response body is closed. Case 1 asserts each row.

## Choke points

| Choke point | Where | Callers | Guard mutation (test that must go red) |
|---|---|---|---|
| Ranged response check: status 206, `Content-Range` exactly `bytes <start>-<end>/<size>`, `Content-Length` (when sent) equal to the asked length, all before the body is read; refused as `_classified(provider, "unexpected")` | new `_clients.check_ranged_response` in `connectors/_clients.py` | `_clients._ranged_body` (GCS; today's inline check at `_clients.py:283-286` moves here) and `_cloud_readers._s3_range` (`_cloud_readers.py:330`) | M1 remove the status test: case 2b red on S3 and GCS. M2 drop the call in `_s3_range`: case 2b red on S3 |
| Exact body read: read at most the asked length; a short read is `source_changed` | `_exact` (`_cloud_readers.py:75`), `_ranged_body` (`_clients.py:287-296`) | every ranged fetch | M3 return the short body: case 2 red |
| Version pin: S3 `IfMatch=<ETag>`, GCS `ifGenerationMatch` | `_s3_range`, `gcs_download` (`_clients.py:254`) | every ranged fetch | M4 remove `IfMatch` or `ifGenerationMatch`: case 2 red |
| GCS size and generation from one metadata view: always one `gcs_reload` (as `gcs.py:171` does today; the profile copy's skip when both are set goes, and a fresh `bucket().blob()` never has them, so no extra call); a missing value is `source_changed` | new `_clients.gcs_pinned_version(blob) -> (size, generation)` | `connectors/gcs.py:_stream_blob` (`gcs.py:171`) and `_cloud_readers._gcs_version` (`:431`), both replaced | M5 drop the `None` test: case 12 red for both callers |
| Library failures under a strict handle | `fileaccess._errors.guarded`, reached from `profile/` only through `fileaccess.adapters.arrow` (new `table_from_pandas(display, frame)`); `profile/` no longer imports `fileaccess._errors` | `_csv_schema_from_window` (`:232`), `collect_batches` | M6 restore `from decoy_engine.fileaccess._errors import guarded` in `_cloud_readers.py`: case 13 red |
| Memory-failure text predicate: one `_memory_text(message) -> bool` | `fileaccess/_errors.py` | `is_memory_failure` (`_errors.py:171`) and `resurface_scrubbed` (`_errors.py:196`) | M7 change the marker test in one caller only: case 8b red |
| Fixed-text rebuild: a recognised memory failure is rebuilt around `MEMORY_TEXT` only, never the library's text (it can carry a cell next to an OpenSSL marker) | `_fixed_text_rebuild` (`_errors.py`) | `resurface_scrubbed` | M8 rebuild around `str(exc)`: cases 5 and 8 red |
| CSV window parse: one function shared by both providers, with `main`'s parser settings (no `low_memory=False`); drops a torn last line on a prefix | `_csv_sample_from_window` (`:205`) | `sample_frame`, the proof read, `schema` | M9 remove the `rsplit` of the last line: case 9 red. M11 set `low_memory=False`: case 10 red |
| CSV schema type resolution: after the parse, an object column whose non-null values are not all `str` becomes text; then the guarded Arrow conversion | `_csv_schema_from_window` | `schema` on S3 and GCS | M10 drop the resolution: case 6 red |
| Parquet frame parity with `pd.read_parquet`: the `to_pandas` arguments pandas passes for the default dtype backend, then `attrs` from `PANDAS_ATTRS` | new `arrow_adapter.parquet_table_to_pandas(table)` | `_read_parquet_frame` (`:174`) | M12 drop the `attrs` step: case 11 red |
| Sample window cap | `_CSV_SAMPLE_MAX_BYTES` in `_csv_rows_from_ranges` | `sample_frame` | M13 remove the cap test: case 1 red |
| Decode error scrub | `_csv_sample_from_window` (`:224-229`) | `sample_frame`, `schema`, proof read | M14 re-raise the original `UnicodeDecodeError`: case 7 red |

The forwarding helpers in `fileaccess/adapters/arrow.py` stay listed in
`tests/sentry/file_access_registry.toml` and stay checked by the file-access sentry; the registry
row count may only go down.

## Established solutions

Searches run: web search for boto3 `get_object` Range responses and status (AWS botocore
`get_object` reference, AWS re:Post on short and 206 responses), s3fs `version_aware`, and
pandas `read_parquet` `PANDAS_ATTRS` handling (pandas `io/parquet.py`, pyarrow
`tests/parquet/test_pandas.py`); codebase search of `connectors/_clients.py` (the GCS
`_ranged_body` check already in tree) and `origin/main` `_cloud_readers.py`.

| Option | What it gives | Decision |
|---|---|---|
| `pyarrow.fs.S3FileSystem`, `GcsFileSystem` | ranged random-access files for `ParquetFile` | not used: no per-request ETag or generation pin in the Python API; bypasses the engine's client factory (`_clients.s3_client`, `gcs_client`), its retry and its reason codes |
| fsspec `s3fs` / `gcsfs` with `version_aware=True` | ranged readers pinned to a version id or generation | not used: new dependencies; S3 pinning needs a versioned bucket (`VersionId`), ETag pinning is not offered; same factory and reason-code bypass |
| `pq.ParquetFile(pre_buffer=True)` | coalesced column-chunk ranges | not used now: coalesced ranges can exceed the 8 MiB piece cap; V2-LOG to measure |
| RFC 9110 sections 13.1.1 (`If-Match`), 14.2 (a server may ignore `Range` and send 200), 14.4 (`Content-Range`), 15.3.7 (206); GCS `ifGenerationMatch` precondition | the response contract | followed: `check_ranged_response` enforces 206 plus exact `Content-Range` before the body, as `_clients._ranged_body` already does for GCS |
| pandas `PyArrowImpl.read` post-processing (`attrs` from `PANDAS_ATTRS` JSON) | `read_parquet` output from an Arrow table | followed and cited in `parquet_table_to_pandas`; case 11 compares against the installed `pd.read_parquet` |

The hand-written `_RangeFileReader` stays: it is the only option that pins every request to the
version seen at open on both providers through the existing client factory, with no new
dependency. Finding 1 (S3 range check) is the gap those libraries close; case 2b makes this
reader close it too.

## Design notes

- One place per fact: the ranged response contract lives in `check_ranged_response`; GCS version
  metadata in `gcs_pinned_version`; the memory-text test in `_memory_text`; pandas parity in
  `parquet_table_to_pandas`. Each replaces a copy (Dennis finding 6) and has a guard (cases 2b,
  12, 8b, 11).
- Dependency rule: `profile/` reaches file-access guarding through the public adapter, never a
  private `fileaccess._*` module (recurring-defect R6, case 13).
- No flag arguments: the check takes the asked range and size, not a provider switch; the GCS
  stored-encoding test stays in `_ranged_body` because only GCS transcodes.

## Failure modes

| Failure | Detected at | Result (reason code or type) | Value-free | Case |
|---|---|---|---|---|
| Object replaced between open and a range (412; GCS 404) | `_s3_range`, `_ranged_body` | `source_changed` | fixed text | 2 |
| Short body | `_exact`, `_ranged_body` | `source_changed` | fixed text | 2 |
| Range ignored (200), wrong `Content-Range`, wrong `Content-Length` | `check_ranged_response` | `ConnectorError` kind `unexpected`, body unread | fixed text | 2b |
| GCS stored gzip or transcoded body | `_ranged_body` | `stored_content_encoding` | fixed text | 2 |
| Missing ETag or generation | `_s3_bind`, `gcs_pinned_version` | `source_changed` | fixed text | 12 |
| CSV sample rows past 64 MiB | `_csv_rows_from_ranges` | `sample_window_exceeded` | fixed text | 1 |
| Malformed CSV, Parquet footer or body | `guarded` | `FileAccessReadError` `file could not be read: <PROVIDER>` | fixed text | 3 |
| Arrow cell conversion failure | `guarded` | `FileAccessReadError`, or a memory-classifiable error from fixed text | no cell | 4, 5, 6 |
| Invalid UTF-8 in a CSV window | `_csv_sample_from_window` | `UnicodeDecodeError` with no input bytes, no cause or context | no bytes | 7 |
| Memory exhaustion | `guarded` with `passes_by_type` | a typed memory error passes; a text-recognised one is rebuilt from `MEMORY_TEXT` | no cell | 5, 8 |

## Acceptance tests, red first

Each case runs on S3 and GCS, where the case names a read, for each read named. Every case runs
in the base environment through `tests/_cloud_fakes.py`, with no cloud extras installed; none
skips on a missing SDK. Each case has a non-vacuity check (the fake records the request, or the
canary is present in the input).

1. Transport bounds: each row of the caps table holds, asserted from the fake's ledger: no unsized
   body read, no CSV `to_frame` piece over 1 MiB, no other piece over 8 MiB, CSV `row_count` and
   `schema` read at most 1 MiB, total CSV sample bytes at most 64 MiB (`sample_window_exceeded`
   past it), every body closed, including refused ones.
2. Version pin: ETag `IfMatch` and generation `ifGenerationMatch` on every ranged read; a replaced
   object is `source_changed`; a short body is `source_changed`; GCS refuses a stored-gzip object
   before reading the body.
2b. Range response contract, both providers, for `to_frame`, `sample_frame` and `schema` (CSV and
   Parquet): the fake answers (a) 200 with the whole object, (b) 206 with a `Content-Range` that
   names other bytes, (c) 206 with a `Content-Range` total that differs from the size at open,
   (d) 206 with a `Content-Length` other than the asked length. Each is refused with kind
   `unexpected`, and the fake's ledger shows zero body bytes read from that response. The S3 fake
   shapes its response as botocore does (`ResponseMetadata.HTTPStatusCode`, `ContentRange`,
   `ContentLength`).
3. Malformed CSV, Parquet footer and Parquet body leave as `FileAccessReadError` with the fixed
   text `file could not be read: <PROVIDER>`.
4. Parquet cell conversion failure, Arrow `Wrapping <cell> failed` shape: `sample_frame` and
   `to_frame` raise a memory-classifiable error whose text, `args`, cause and context hold no cell.
5. Parquet cell conversion failure, other shape: a pandas metadata `int64[pyarrow]` conversion
   fails with a message that holds a data cell and an OpenSSL marker. `sample_frame` and
   `to_frame` raise a memory-classifiable error built from fixed text; the canary is absent from
   `str`, `repr`, `args`, `__notes__`, `__cause__`, `__context__` and captured logs.
6. CSV `schema()` over a window that mixes numeric and text values in one column (more columns
   than one parser chunk): returns a schema in which the mixed column is `pa.string()` and an
   all-integer column is `pa.int64()` (types asserted, not only the column count). A conversion
   failure that still occurs is a `FileAccessReadError` with `__cause__` and `__context__` both
   `None` and no canary anywhere.
7. CSV invalid UTF-8 in `sample_frame()` and `schema()`: the raised decode error holds no input
   bytes (`args`, `repr`) and no `__context__` or `__cause__`. The proof read
   `profile._readers.has_row_beyond(read_sample, n)` returns `True` when the bad bytes sit in
   row `n + 1` and the first `n` rows decode.
8. Guard test: `resurface_scrubbed` output for every memory-marker shape contains none of the
   input text beyond the fixed marker.
8b. Predicate agreement: over the marker and pattern corpus plus non-memory strings,
   `is_memory_failure(e)` and `resurface_scrubbed(e) is not None` agree for every untyped `e`.
9. Torn last line: a CSV whose first window ends mid-row with a canary in the cut fragment; the
   `sample_frame` and `schema` results never hold the partial row, and the column count is
   unchanged.
10. Wide-sample non-regression: an 8,000 x 1,050 numeric CSV. In fresh Linux subprocesses under
   the same `RLIMIT_AS` (address space after imports plus a calibrated margin): `main`'s parse
   (`pd.read_csv(io.BytesIO(window), nrows=n)`, origin/main `_cloud_readers.py:145`) succeeds;
   head's `sample_frame` and `schema` succeed; a control parse with `low_memory=False` fails. The
   control proves the limit catches the regression; the `main` run proves the limit is not too
   tight. Skipped only on macOS, where `RLIMIT_AS` is not enforced, with that reason.
11. Parity: S3 and GCS Parquet `to_frame` equal `pd.read_parquet` on the same bytes
   (`pd.testing.assert_frame_equal` plus `attrs` equality) for a named index and a range index,
   categoricals, tz-aware timestamps, a nullable integer column, non-empty `attrs`, and a file
   with zero row groups. CSV `to_frame` equals `pandas_adapter.read_csv` on the same bytes, with
   and without lexeme columns.
12. Pinned version helper: a blob with `size` or `generation` missing after reload is
   `source_changed` from both `gcs.py` `_stream_blob` and the profile reader; both reach
   `gcs_pinned_version` (call-recording fake).
13. Import guard: an AST walk of `profile/_cloud_readers.py` (resolving `import` and
   `from ... import` forms) finds no private `fileaccess._*` module, only `fileaccess.adapters.*`.
   Seeded bypass: a scratch copy with the old import makes it fail.
14. Working set: `scripts/audit/cloud_to_frame_rss.sh` measures, in fresh processes on the same
   256 MiB object, head's S3 Parquet `to_frame` and `main`'s route (whole-object download plus
   `pd.read_parquet`, origin/main `_cloud_readers.py:268-270`). It prints both peaks and exits 1
   when head's peak growth exceeds `main`'s by more than 10%. The `object/2` target is removed.
   The gate runs it on the final head and records both numbers; head worse than `main` is V1.

GCS acceptance framing (`tests/acceptance/test_f06_csv_framing.py:135`) drops its
`importorskip("google.cloud.storage")` and runs on the fakes, as it did before this slice.

## Enumerations

### Exit paths

- `_exact` short read to `source_changed` (`src/decoy_engine/profile/_cloud_readers.py:75`).
- `_s3_range` 412 to `source_changed`; body closed by `with` (`src/decoy_engine/profile/_cloud_readers.py:346`).
- `_ranged_body` 404/412, non-2xx, stored encoding, inexact range, short body; response closed in `finally` (`src/decoy_engine/connectors/_clients.py:262`, `:272-296`).
- `_csv_rows_from_ranges` raises `SampleWindowExceeded` (`src/decoy_engine/profile/_cloud_readers.py:241`).
- `_csv_sample_from_window` rebuilds the decode error (`src/decoy_engine/profile/_cloud_readers.py:224`).
- `_with_gcs_reads` closes the client on every exit (`src/decoy_engine/profile/_cloud_readers.py:440`).

### Routes

- S3 Parquet and CSV: `row_count`, `schema`, `sample_frame`, `to_frame` (`src/decoy_engine/profile/_cloud_readers.py:352`, `:373`).
- GCS Parquet and CSV: the same four reads (`src/decoy_engine/profile/_cloud_readers.py:458`, `:479`).
- GCS connector object stream `_stream_blob` (`src/decoy_engine/connectors/gcs.py:164`).
- Azure: no profile reader exists; out of scope.

### FK shapes

N/A: these readers profile one object; no relational data crosses them.

### Fields

- `RowCount.count`, `RowCount.exact` (`src/decoy_engine/profile/_readers.py:64`).
- `SampleWindowExceeded.code`, `.kind` (`src/decoy_engine/profile/_cloud_readers.py:62`).
- `ConnectorError` kind and reason code; `FileAccessReadError` fixed text (`src/decoy_engine/fileaccess/_types.py:117`).

### Output surfaces

- Exception `str`, `repr`, `args`, `__notes__`, `__cause__`, `__context__` (cases 3 to 8).
- Captured logs (case 5).
- Returned frames and schemas (cases 6, 9, 11).
- Audit script stdout: sizes, counts and peaks only, no data (case 14).

## Class table (plan contract catalog)

| # | Class | Closing structure | Proof | Mutation |
|---|---|---|---|---|
| 1 | Value-bearing output | `guarded` plus fixed-text rebuild; decode error rebuilt empty | cases 3 to 8, seeded canary per surface | M8, M14 |
| 2 | Cleanup missing on an exit path | `with response["Body"]`, `finally: response.close()`, `with gcs_client()` | case 1 "every body closed", including the refused responses of case 2b | remove the GCS `finally` close: case 1 red |
| 3 | State machine and concurrency | N/A: no shared state; each read binds its own client and version | n/a | n/a |
| 4 | Route parity and silent fallback | one range check and one version helper for both providers | cases 2b and 12 on both providers | M2, M5 |
| 5 | Referential integrity | N/A: single-object readers, no FK data | n/a | n/a |
| 6 | Untrusted producer (store responses, library errors) | exact range-response check before the body; bounded pieces; errors rebuilt from fixed text | cases 1, 2b, 4, 5 | M1, M13 |
| 7 | Check then use (TOCTOU) on the object | version pin on every request (`If-Match`, `ifGenerationMatch`) | case 2 | M4 (drop `IfMatch` or `ifGenerationMatch`) |
| 8 | Weak tests and overclaimed evidence | non-vacuity per case; case 10 control parse; case 14 measures `main` too | cases 10, 14 | M11 |
| 9 | Behavior-preserving refactor drift | parity against `pd.read_parquet` and `read_csv`; wide-sample non-regression | cases 10, 11 | M12 |
| 10 | Frozen contract drift | reason codes additive only (`sample_window_exceeded`, `stored_content_encoding`) | `tests/unit/reasons/test_connector_outcomes.py` | remove a code: that test red |

## Recurring defects (dev-rules catalog)

| Class | Status |
|---|---|
| R1 anchored validation | n/a: no pattern validation added |
| R2 strict wire and stored types | n/a: no persisted model |
| R3 no exception context | cases 4 to 7 assert `__cause__` and `__context__` are `None` |
| R4 versioned read models | n/a: no persisted format read |
| R5 normalized guard scanners | case 13 walks the AST and resolves both import forms; seeded bypass |
| R6 no reaching into private modules | closed by case 13, M6 |
| R7 no hidden CI failures | case 14 exits 1 on breach; case 10 skips only on macOS with its reason |
| R8 one input, one trust class per entry point | n/a: one trust class (store responses) |
| R9 mutations on the final head | M1 to M14 rerun on the final head; the gate records each |
| R10 allowlisted helpers are still checked | arrow forwarding helpers stay in the file-access registry and sentry |
| R11 no raised caps | none raised; `test_signed_evidence_file_access.py` pin went down |

## Reuse inventory

- `_clients.s3_call`, `s3_client`, `gcs_client`, `gcs_retry`, `_classified`, `source_changed`.
- `fileaccess.adapters.arrow` guarded entry points; `fileaccess._errors` stays behind them.
- `profile._readers.has_row_beyond`, `PROOF_READ_ERRORS`, `head_frame_from_batches`, `estimate_csv_rows`.
- `tests/_cloud_fakes.py` (`FakeS3`, `FakeGcsSession`, ledger) for every case.
- Sentries: `test_module_size.py`, `test_file_access_boundary.py`, `file_access_registry.toml`.

New public-in-package names: `check_ranged_response`, `gcs_pinned_version` (`_clients`),
`table_from_pandas`, `parquet_table_to_pandas` (arrow adapter), `_memory_text` (`_errors`). Each
replaces a copy or a private import; none is speculative.

## Frozen contracts

- Reason codes in `reasons/connector/_part1.py`: additive only.
- `ProfileSource` read signatures: unchanged.
- `to_frame` output: equal to `main`'s (case 11), so no contract change.

## Placement and expected sizes

| Path | Change | CODEMAP line | Beside | Lines now | Expected |
|---|---|---|---|---|---|
| `src/decoy_engine/connectors/_clients.py` | `check_ranged_response`, `gcs_pinned_version` | `CODEMAP.md:283` | `gcs.py` | 525 | about 565 |
| `src/decoy_engine/connectors/gcs.py` | `_stream_blob` uses `gcs_pinned_version` | `CODEMAP.md:283` | `_clients.py` | 247 | about 243 |
| `src/decoy_engine/profile/_cloud_readers.py` | S3 calls the check; schema type resolution; drop private import | `CODEMAP.md:281` | `_readers.py` | 545 | about 560 |
| `src/decoy_engine/fileaccess/_errors.py` | `_memory_text` | `CODEMAP.md:288` | `adapters/` | 341 | about 336 |
| `src/decoy_engine/fileaccess/adapters/arrow.py` | `table_from_pandas`, `parquet_table_to_pandas` | `CODEMAP.md:288` | `adapters/pandas.py` | 352 | about 380 |
| `scripts/audit/cloud_to_frame_rss.sh` | head vs `main` comparison, exit 1 on breach | `CODEMAP.md:298` | other `scripts/audit/` tools | 70 | about 90 |
| `tests/_cloud_fakes.py` | 200, wrong range and length responses; body-read ledger | `CODEMAP.md:303` | `tests/_changelog.py` | 367 | about 420 |
| `tests/unit/profile/test_cloud_to_frame_bounded.py` | cases 1, 2 | `CODEMAP.md:307` | profile unit tests | 463 | about 480 |
| `tests/unit/profile/test_cloud_range_contract.py` (new) | case 2b | `CODEMAP.md:307` | `test_cloud_to_frame_bounded.py` | 0 | about 120 |
| `tests/unit/profile/test_cloud_to_frame_parity.py` (new) | case 11 | `CODEMAP.md:307` | `test_cloud_to_frame_bounded.py` | 0 | about 110 |
| `tests/unit/profile/test_cloud_read_value_free.py` | cases 6, 7, 9 | `CODEMAP.md:307` | profile unit tests | 135 | about 200 |
| `tests/unit/profile/test_cloud_wide_sample.py` (new) | case 10 | `CODEMAP.md:307` | profile unit tests | 0 | about 80 |
| `tests/unit/fileaccess/test_memory_text.py` (new) | case 8b | `CODEMAP.md:307` | fileaccess unit tests | 0 | about 50 |
| `tests/connectors/test_gcs_pinned_version.py` (new) | case 12 | `CODEMAP.md:283` | `test_gcs.py` | 0 | about 60 |
| `tests/sentry/profiling/test_cloud_reads_bounded.py` | case 13 | `CODEMAP.md:295` | profiling sentries | 126 | about 150 |
| `tests/acceptance/test_f06_csv_framing.py` | drop the GCS `importorskip` | acceptance suite | `_f06_support.py` | 188 | about 187 |

Every module stays under 600 lines, so no census entry. `profile/` gets no new source module.

## Slices

One slice, engine repo, PR 789, about +700 / -60 lines over the current head (most of it the new
tests). Order: red tests for 2b, 6, 9, 10, 11, 12, 13 and 8b first, then the code.

## Pre-mortem

- The 2b fake does not model botocore's response, so the S3 check passes on the fake and fails on
  a real store: the fake builds the response the way botocore does (case 2b).
- The `RLIMIT_AS` margin flakes across runners: the control parse makes a too-loose limit fail
  loudly instead of passing quietly.
- pandas changes its `read_parquet` post-processing: case 11 compares against the installed
  `pd.read_parquet`, so drift turns it red.

## V2-LOG

- Stream the Parquet Arrow-to-pandas conversion per row group, so the decoded table leaves the
  `to_frame` working set.
- Measure `ParquetFile(pre_buffer=True)` request coalescing against the 8 MiB piece cap.
- S3 objects with a stored `Content-Encoding`: refuse as `stored_content_encoding`, as GCS does.

## Finding map (Dennis round 1)

| # | Severity | Plan change |
|---|---|---|
| 1 | BLOCKER | choke point `check_ranged_response` for both providers; case 2b; M1, M2 |
| 2 | BLOCKER | case 10 wide non-regression under `RLIMIT_AS`; sample parse keeps `main`'s settings; schema type resolution choke point; case 6 asserts types; M10, M11 |
| 3 | BLOCKER | case 11 parity incl. `attrs` and zero row groups; `parquet_table_to_pandas` choke point; M12 |
| 4 | BLOCKER | working set below `main` is a non-goal; case 14 measures head against `main` and exits 1 on breach; `object/2` target removed |
| 5 | HIGH | caps table with constant names; case 1 asserts each row |
| 6 | HIGH | `gcs_pinned_version` (a), `table_from_pandas` through the arrow adapter (b), `_memory_text` (c); cases 12, 13, 8b; M5, M6, M7 |
| 7 | MEDIUM | guard mutation column in the choke-point table, M1 to M14; case 9 for the torn line |
| 8 | MEDIUM | Placement and expected sizes table with CODEMAP lines |
| 9 | MEDIUM | Established solutions section |
| 10 | MEDIUM | GCS framing cases run on the fakes without extras |
| 11 | LOW | case 7 names `has_row_beyond` and asserts `True` |
| 12 | LOW | Failure modes table |
