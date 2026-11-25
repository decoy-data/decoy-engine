# F25 G7-1: bounded cloud reads, acceptance cases

Status: plan

Rules consulted: 00-universal, cross-cutting-concerns, testing, catalogs/recurring-defects.

Slice: engine PR 789, branch `feat/f25-g7-1-bounded-cloud`. Covers the S3 and GCS profile readers
(`profile/_cloud_readers.py`) for CSV and Parquet.

**Guarantee.** A cloud read of one object stays bounded (footer plus one row group for Parquet,
1 MiB pieces for CSV, 64 MiB total for a CSV sample) and pinned to the version seen at open.
Every failure that leaves a strict read is value-free: no data cell, no input bytes, in the
message, `args`, `repr`, notes, cause chain or logs.

**Non-goals:** SFTP reads; changing the sample window caps.

## Choke points

- Library failures under a strict handle: `fileaccess._errors.guarded` (with `resurface_scrubbed`
  for failures the caller must still classify by text). A recognised memory failure is rebuilt
  around fixed text only. It is never rebuilt around the library's text, because that text can
  carry a cell (an Arrow conversion error that also contains an OpenSSL marker).
- CSV window parse: one function, `_csv_sample_from_window`, shared by both providers.

## Acceptance cases

Each case runs on S3 and GCS, where the case names a read, for each read named.

1. Transport bounds: no unsized body read, no piece over 8 MiB, every body closed, total CSV
   sample bytes at most 64 MiB (`SAMPLE_WINDOW_EXCEEDED` past it).
2. Version pin: ETag `IfMatch` and generation `ifGenerationMatch` on every ranged read; a
   replaced object is `source_changed`; GCS refuses an ignored range, an inexact 206 and a
   stored-gzip object before reading the body.
3. Malformed CSV, Parquet footer and Parquet body leave as `FileAccessReadError` with the fixed
   text `file could not be read: <PROVIDER>`.
4. Parquet cell conversion failure, Arrow `Wrapping <cell> failed` shape: `sample_frame` and
   `to_frame` raise a memory-classifiable error whose text, `args`, cause and context hold no cell.
5. Parquet cell conversion failure, other shape: a pandas metadata `int64[pyarrow]` conversion
   fails with a message that holds a data cell and an OpenSSL marker. `sample_frame` and
   `to_frame` raise a memory-classifiable error built from fixed text; the canary is absent from
   `str`, `repr`, `args`, `__notes__`, `__cause__`, `__context__` and captured logs.
6. CSV `schema()` over a window that mixes numeric and text values in one column (more columns
   than one parser chunk): returns a schema (a column that is not all numeric is text). A
   conversion failure that still occurs is a `FileAccessReadError`, with no canary anywhere.
7. CSV invalid UTF-8 in `sample_frame()` and `schema()`: the raised decode error holds no input
   bytes (`args`, `repr`) and no `__context__` or `__cause__`. The proof read still treats it as
   "a row exists".
8. Guard test: `resurface_scrubbed` output for every memory-marker shape contains none of the
   input text beyond the fixed marker.
