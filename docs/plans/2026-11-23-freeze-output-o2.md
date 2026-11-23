Status: plan

# FREEZE-OUTPUT O2: a compressed CSV target from a DataFrame gets the frozen codec bytes

Owner: Cam. Author: Opus. Date: 2026-11-23. Revision 1. Roadmap row: FREEZE-OUTPUT, item 2 (O2) (CLI `docs/roadmap/groups/run.md`). Anchors marked `C:` are in the CLI repository (decoy) at `origin/main` `95362d16`; anchors marked `E:` are in this repository (decoy-engine) at `origin/main` `26091c834`.

Where this plan lives: the task put it on the engine branch `plan/freeze-output-o2`. The fix is CLI-only (section 2.3: the engine writes no compressed file). The build slice goes to the CLI repository.

Rules consulted: dev-rules `README.md`, `00-universal.md`, `risk-and-exceptions.md`, `development-loop.md` (PLAN: guarantee, size, choke point, established solutions), `bugfix.md`, `api-and-compatibility.md` (output bytes are an external contract), `catalogs/recurring-defects.md` (11 classes).

Risk: R2. A small change that moves frozen output bytes of an existing command. Plan review: Dennis, then Codex. Code gate: Codex, then Dennis. Full CLI suite before merge: yes (frozen-contract trigger).

## 1. Frame

### 1.1 Symptom

The atomic-output record lists it as V2-LOG: "`.gz` header can store the staging basename" (`C:docs/records/2026-11-07-atomic-output-build.md:48`). A CLI write of a pandas DataFrame to `out.csv.gz` stages to `.out.csv.gz.decoy-<hex>.tmp` and lets pandas compress it. pandas names the gzip member after the file it opens, so the header stores the staging name. It also stores the wall-clock time. Two runs of the same input give different bytes, and the header carries a temp name.

### 1.2 What the probes showed

Probe on the Mac through `vm-run`, CLI `origin/main` `95362d16`, `write_table` and `write_private_table` with `pd.DataFrame({"id": [1, 2], "name": ["a", "b"]})`, each suffix in `COMPRESSION` (`C:src/decoy/cli/io/_compression.py:33-42`), two writes per suffix compared by SHA-256:

| Suffix | Base (DataFrame route) | After the probe fix |
|---|---|---|
| `.gz` | header FLG `0x08` (FNAME set), FNAME `.frame_private0.csv.gz.decoy-af5943afc17f9d23.tmp`, MTIME wall clock, XFL 2 (level 9); two writes differ | header `1f8b08000000000000ff`; two writes equal |
| `.tar.gz` | the same gzip header leak; two writes differ | header `1f8b08000000000000ff`; two writes equal |
| `.zip` | member `date_time` is now; two writes differ | member date 1980-01-01; two writes equal |
| `.zst` | `ImportError` (pandas needs `zstandard`, not installed) | writes; two writes equal |
| `.tar.bz2` | `tarfile.CompressionError: unknown compression type 'z2'` (pandas rejects the tar mode the helper builds) | writes; two writes equal |
| `.bz2`, `.xz`, `.tar`, `.tar.xz` | two writes equal | bytes unchanged |

The Arrow route (`pa.Table`, used by `unmask`, `run` and chunked output) is already deterministic: FLG 0, MTIME 0, XFL 0, no FNAME. It goes through the frozen codec opener `open_csv_sink` (`C:src/decoy/cli/io/_compression.py:146`), frozen by CLI #397 and the goldens in `C:tests/fixtures/cli_fmt/csv_writer/`.

The probe fix (a throwaway worktree, removed) replaced the pandas line with a write into `open_csv_sink`. All nine suffixes became deterministic, the decoded payload was exact (`id,name\n1,a\n2,b\n`) and the file mode of `write_private_table` stayed 0600. Measured SHA-256 prefixes after the fix: `.gz` `c1b1aef9e182706d`, `.zip` `24215ba603682ff4`, `.tar.gz` `701dc1aaa1a9faae`, `.zst` `dbe01b512666432c`, `.tar.bz2` `7c6836ffaf24fffb`; unchanged: `.bz2` `7a16bb86e2aae3af`, `.xz` `8596907e7b10118e`, `.tar` `bb15bc7042e39867`, `.tar.xz` `0e8d659f91fa2c3c`.

### 1.3 Impact

Who reaches it: `decoy detokenize` with a compressed CSV output path. It is the only caller that passes a DataFrame to a whole-table writer (`C:src/decoy/cli/tokenize.py:732`). `unmask` passes a `pa.Table` (`C:src/decoy/cli/unmask.py:268`). The leaked name is an engine-made temp name built from the real output name, so no data value leaks. The harm is non-deterministic bytes on a frozen surface, and two suffixes that fail outright.

## 2. Root cause with evidence

### 2.1 The one DataFrame branch bypasses the frozen codec

`C:src/decoy/cli/io/_targets.py:568-578`, inside `_write_table`:

```python
with stage(path) as tmp:
    if isinstance(data, pd.DataFrame) and fmt == "csv":
        data.to_csv(tmp, index=False, compression=csv_compression(path))
    elif fmt == "csv":
        with (
            open_csv_sink(tmp, path) as sink,
            pacsv.CSVWriter(...) as writer,
        ):
```

The Arrow branch writes into `open_csv_sink`, whose gzip codec is `gzip.GzipFile(fileobj=raw, mode="wb", compresslevel=6, filename="", mtime=0)` (`C:src/decoy/cli/io/_compression.py:90-112`), with fixed zip and tar member headers (`_tar_member`, `_zip_member`). The DataFrame branch hands the staging path and a compression option to pandas (`csv_compression`, `C:src/decoy/cli/io/_compression.py:60-80`). pandas then opens `tmp` by name, so gzip records `tmp`'s basename and the current time, uses level 9, and builds zip and tar members with the current time.

### 2.2 Why two suffixes fail

pandas needs the `zstandard` package for `.zst`; the CLI's zstd codec uses `pa.CompressedOutputStream` instead. For `.tar.bz2`, the mode string `csv_compression` builds is rejected by pandas. Both go away when the branch uses `open_csv_sink`.

### 2.3 Every gzip and archive writer

- CLI: `gzip.GzipFile` only in `_stream_codec` (`C:src/decoy/cli/io/_compression.py:97`); `zipfile.ZipFile` and `tarfile.open` for writing only in `open_csv_sink` (`:163`, `:171`); pandas compression only at `C:src/decoy/cli/io/_targets.py:570`. `C:src/decoy/distribution/installer.py:290` reads a tar.
- Engine: no gzip, zip or tar writer and no compressed CSV writer in `src/`. The only match is the reader helper `E:src/decoy_engine/profile/_csv_reader.py:582`.
- Platform: parked; it has readers and one zip for an evidence download, not a CSV target.

So the root cause is one line in the CLI.

## 3. Established solutions considered

- Search run: RFC 1952 (gzip header fields FNAME, MTIME, XFL), Python `gzip.GzipFile` (`filename`, `mtime`), the Reproducible Builds guidance on archive timestamps (`SOURCE_DATE_EPOCH`, zero or fixed mtime, fixed zip dates), pandas `to_csv` `compression` docs. Found: a reproducible gzip sets MTIME to 0 and leaves out FNAME; zip uses a fixed date (1980-01-01 is the zip epoch); tar uses mtime 0 and fixed owner fields.
- In this repository: `open_csv_sink` already does exactly this for the Arrow route, frozen by CLI #397. pandas `to_csv` accepts an open binary handle and writes into it, so the DataFrame route can reuse the same opener with no new code.
- Rejected: keep pandas compression and pass `{"method": "gzip", "mtime": 0}`. It fixes MTIME only: pandas still opens the staging path by name (FNAME), level 9 stays, and zip, tar, `.zst` and `.tar.bz2` keep their own rules. Two codec rules for one surface.
- Rejected: store the real output name in FNAME. It makes the bytes depend on the output name and differs from the Arrow route. One rule (empty FNAME, MTIME 0) is simpler and already frozen.

## 4. Fix design

### 4.1 Guarantee

1. Every whole-table CSV write, DataFrame or Arrow, wraps its CSV bytes in the codec `open_csv_sink` picks from the real output name. There is one codec rule for CSV targets.
2. A gzip header from the DataFrame route has no FNAME, MTIME 0, XFL 0 (level 6), OS 255: the bytes `1f 8b 08 00 00 00 00 00 00 ff`.
3. Writing the same DataFrame to the same suffix twice gives identical bytes, for all nine suffixes.
4. `.csv.zst` and `.csv.tar.bz2` from the DataFrame route write instead of failing.
5. The CSV text pandas writes does not change; only the codec wrapping does. Plain `.csv` bytes do not change. `write_private_table` keeps mode 0600.

Non-goals:

- G-1. The CSV text difference between the two routes (pandas and Arrow quote and format differently). That is the existing DataFrame contract.
- G-2. Moving `detokenize` to the Arrow route. A bigger change with its own text bytes.
- G-3. ACLs and xattrs of an old output (the other V2-LOG item in the same record).

### 4.2 Design

- `C:src/decoy/cli/io/_targets.py:570` becomes:

  ```python
  with open_csv_sink(tmp, path) as sink:
      data.to_csv(sink, index=False)
  ```

- `csv_compression` (`C:src/decoy/cli/io/_compression.py:60-80`) loses its only caller and is deleted, with its import at `C:src/decoy/cli/io/_targets.py:42` and its test `test_csv_compression_follows_the_real_name` (`C:tests/unit/cli_fmt/test_compression.py:52`). `_archive_name` stays (used by `open_csv_sink`).
- Size: about 3 lines changed in `_targets.py`, about 22 lines deleted in `_compression.py`. No new public name.

### 4.3 Choke point

The CSV codec rule is enforced at one opener, `open_csv_sink`. The existing sentry `test_the_one_dataframe_to_csv_target_call_is_guarded_in_write_table` (`C:tests/sentry/io_policy/test_csv_frame_choke_point.py:146`) already pins one guarded `to_csv` call in `_write_table`. It grows one assertion: that call has no `compression=` keyword and is inside a `with open_csv_sink(...)` block whose target it writes to. Seeded cases: a `compression=` keyword, a `to_csv(tmp, ...)` outside the block. M-1 turns it red. The `file_sinks.toml` row for `_write_table` `to_csv` (`C:tests/sentry/io_policy/file_sinks.toml`) is updated to say it writes into the codec sink.

### 4.4 Placement

No new source file. New goldens in `C:tests/fixtures/cli_fmt/csv_writer/`, beside the Arrow route goldens: `csv-writer-frame.csv.<suffix>` for the nine suffixes. New tests in `C:tests/unit/cli_fmt/test_csv_writer_bytes.py`, beside the Arrow route golden cases.

### 4.5 Design notes

None: no new structure. The change removes a second codec rule.

## 5. Behavior and failure modes

| Input | Before | After |
|---|---|---|
| DataFrame to `.csv.gz`, `.csv.tar.gz` | header holds the staging name and the time; level 9 | frozen header; level 6 |
| DataFrame to `.csv.zip` | member time is now | member date 1980-01-01 |
| DataFrame to `.csv.zst` | `ImportError` without `zstandard` | writes (pyarrow zstd) |
| DataFrame to `.csv.tar.bz2` | `CompressionError` | writes |
| DataFrame to `.csv`, `.bz2`, `.xz`, `.tar`, `.tar.xz` | deterministic | unchanged bytes |
| Arrow table to any suffix | frozen codec | unchanged |
| Write fails mid-way | staging removed, old file kept | unchanged (same `stage` block) |
| Disk full in the archive spool | raises | raises from the same `stage` block |

## 6. Acceptance tests (red-first)

Frame F: `pd.DataFrame({"id": [1, 2], "name": ["a", "b"]})`.

- AT-O1. `write_table(F, "csv", out.csv.gz)` and `write_private_table(...)`: the first 10 bytes equal `1f8b08000000000000ff` and the file contains no `decoy-` substring. Red on base.
- AT-O2. Golden: for each of the nine suffixes, `write_table(F, "csv", tmp/"out.csv<suffix>")` equals `csv-writer-frame.csv<suffix>`. Red on base for `.gz`, `.tar.gz`, `.zip` (bytes), `.zst`, `.tar.bz2` (raise). Green on base on purpose for `.bz2`, `.xz`, `.tar`, `.tar.xz`: they pin that those bytes do not move.
- AT-O3. Two writes of F to the same suffix, written a second apart (patch the clock, not sleep), give equal bytes, for all nine suffixes. Red on base for `.gz`, `.tar.gz`, `.zip`.
- AT-O4. The decoded payload of every suffix equals `F.to_csv(index=False).encode()`. Green on base on purpose for the seven suffixes that write; red for `.zst` and `.tar.bz2`.
- AT-O5. `write_private_table(F, "csv", out.csv.gz)` leaves mode 0600 and no staging file. Green on base on purpose (pins 4.1 item 5).
- AT-O6. CLI e2e: `decoy detokenize` with `-o out.csv.gz` on a tokenize fixture, run twice: the two outputs are byte-equal and start with the frozen header. Red on base.
- AT-O7. Sentry: the extended choke-point assertion in section 4.3 passes on the fix and fails on each seeded case.

The existing `test_whole_table_write_honours_the_compression_the_name_implies` (`C:tests/unit/cli_fmt/test_compression.py:77`) stays green on base and after.

## 7. Mutations

Each alone on the final head; record the head (class 9).

| ID | Mutation | Red |
|---|---|---|
| M-1 | restore `data.to_csv(tmp, index=False, compression=csv_compression(path))` | AT-O1, AT-O2, AT-O3, AT-O6, AT-O7 |
| M-2 | `_stream_codec` gzip with `mtime=None` | AT-O2, AT-O3 (and the Arrow goldens) |
| M-3 | `_stream_codec` gzip without `filename=""` | AT-O1, AT-O2 |
| M-4 | `_zip_member` date set to now | AT-O2 `.zip`, AT-O3 |
| M-5 | `to_csv(sink, index=True)` | AT-O2, AT-O4 |

## 8. Frozen contracts and byte changes

Frozen contract touched: CSV target bytes of `decoy detokenize`. Arrow-route bytes do not change.

Breaking: `decoy detokenize` writing a `.csv.gz`, `.csv.tar.gz` or `.csv.zip` target now writes different bytes. The gzip header has no file name, MTIME 0 and compression level 6 (was: the staging file name, the write time, level 9). A zip member is dated 1980-01-01 (was: the write time). `.csv.zst` and `.csv.tar.bz2` targets now write instead of failing. The decoded CSV text is unchanged. Frozen by the nine `csv-writer-frame.csv.*` goldens (AT-O2).

CLI CHANGELOG entry under the next release with the Breaking line above. The record's V2-LOG line (`C:docs/records/2026-11-07-atomic-output-build.md:48`) is marked resolved with the PR number.

## 9. Class tables

### 9.1 dev-rules catalog (`catalogs/recurring-defects.md`, 11 classes)

| Class | Applies | How |
|---|---|---|
| 1 Anchored validation | no | no regex |
| 2 Strict wire and stored types | no | no model |
| 3 No exception context | no | no new raise |
| 4 Versioned read models | no | no reader |
| 5 Normalized guard scanners | yes | the extended sentry matches `to_csv` as an attribute call inside `_write_table`, as today; seeded cases for the keyword and the out-of-block call |
| 6 No reaching into private modules | no | same package |
| 7 No hidden CI failures | no | no CI change |
| 8 One input, one trust class per entry point | no | no new entry point |
| 9 Mutations on the final head | yes | section 7 |
| 10 Allowlisted helpers are still checked | yes | `file_sinks.toml` row stays exact `(path, function)` |
| 11 No raised caps | yes | no cap moves; `_compression.py` shrinks |

### 9.2 Plan contract catalog (vault `Decoy-Plan-Contract-and-Defect-Catalog.md`, 10 classes)

| # | Class | Structure that closes it | Proof | Mutation |
|---|---|---|---|---|
| 1 | Value-bearing output | the staging name no longer reaches the output file; the codec writes no name | AT-O1 (no `decoy-` substring) | M-1, M-3 |
| 2 | Cleanup missing on an exit path | N/A: the same `stage(path)` block owns the temp file; the archive spool is a `TemporaryFile` closed by the opener's `ExitStack` | AT-O5, existing atomic tests | N/A: no new resource |
| 3 | State machine and concurrency | N/A: a single synchronous write; no shared state | none needed | N/A: no transition |
| 4 | Route parity and silent fallback | one codec opener for the DataFrame and Arrow routes | AT-O2 next to the Arrow goldens; AT-O7 sentry | M-1 |
| 5 | Referential integrity | N/A: codec wrapping only; no rows change | AT-O4 | N/A: no FK path |
| 6 | Untrusted producer | N/A: no child process or extension; pandas writes text into an engine-made sink | none needed | N/A: no boundary |
| 7 | Check then use on a path (TOCTOU) | N/A: `open_csv_sink` opens the staged `tmp` once, as on the Arrow route | existing atomic tests | N/A: no new path consumer |
| 8 | Weak tests and overclaimed evidence | AT-O2 and AT-O3 cells green on base are marked so; red cells record base `95362d16` | builder report with red output | each mutation names its AT |
| 9 | Behavior-preserving refactor drift | the CSV text pandas writes stays the same | AT-O4 | M-5 |
| 10 | Frozen contract drift | section 8 names the change; nine goldens freeze it | AT-O2 | M-2, M-4 |

## 10. Enumerations

### 10.1 Exit paths

- Success: `stage(path)` publishes `tmp` to `path` (`C:src/decoy/cli/io/_targets.py:568`). Unchanged.
- `to_csv` or the codec raises inside the block: `stage` removes `tmp` and keeps the old file. Unchanged; the archive spool closes with the opener's stack.

### 10.2 Routes

- DataFrame, CSV, whole table: `_write_table` (`C:src/decoy/cli/io/_targets.py:569-570`). Changed.
- Arrow table, CSV, whole table: `C:src/decoy/cli/io/_targets.py:571-578`. Unchanged.
- Chunked CSV: `open_csv_sink` at `C:src/decoy/cli/io/_targets.py:753`. Unchanged.
- Parquet and fixed width: no codec. Unchanged.

### 10.3 FK shapes

N/A: the change wraps already-built CSV bytes in a codec; no relationship or key path is involved.

### 10.4 Fields

- gzip header: ID1, ID2, CM, FLG (0), MTIME (0), XFL (0), OS (255); no FNAME.
- zip member: name (the real name, suffix cut), date 1980-01-01, deflate, mode 0644. tar member: name, size, mode 0644, uid and gid 0, empty owner names, mtime 0.

### 10.5 Output surfaces

- Output files: changed as section 8 says.
- stdout, stderr, `--json`, logs, errors: unchanged; `detokenize` messages do not name the codec.
- `.zst` and `.tar.bz2`: the raw pandas error goes away.

## 11. Reuse inventory

- `open_csv_sink` and `_stream_codec` (`C:src/decoy/cli/io/_compression.py:90-146`): the frozen codec, reused as is.
- `stage` and `staged_private_target` (`C:src/decoy/_atomic.py:452`): unchanged staging and mode.
- The golden fixture layout and helpers in `C:tests/unit/cli_fmt/test_csv_writer_bytes.py`.
- The choke-point sentry and `file_sinks.toml`.
- No new machinery.

## 12. Pre-mortem

- A pandas release writes `to_csv` into a binary handle differently (for example, text-mode wrapping or a BOM). AT-O4 and the goldens catch it on the dependency bump.
- Someone relies on the gzip FNAME to recover the file name after `gunzip -N`. The CLI's Arrow route never set it, and the leaked value was a temp name, so no working use is lost.
- A large detokenize to `.zip` or `.tar` now spools through a temp file before the archive is built, as the Arrow route does. Same disk need as the Arrow route.

## 13. Slices and risk

| Slice | Repo | Content | Depends on | Risk | Test depth |
|---|---|---|---|---|---|
| S1 | CLI | the one-line route change, delete `csv_compression` and its test, extend the sentry, nine goldens, AT-O1 to AT-O7, CHANGELOG Breaking entry, record line marked resolved | nothing | R2 | T1 plus the full CLI suite (frozen-bytes trigger) |

One slice, about 25 source lines (most of them deleted). No engine slice.
