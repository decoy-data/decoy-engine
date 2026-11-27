# F25 G7-2: bounded SFTP reads

Status: plan

Rules consulted: 00-universal, risk-and-exceptions, development-loop, feature-dev, testing,
security, cross-cutting-concerns, catalogs/recurring-defects, V1 bar preamble, Decoy plan
contract (vault `Decoy-Plan-Contract-and-Defect-Catalog`). Model plan: G7-1
(`docs/plans/2026-11-25-f25-g7-1-bounded-cloud-reads.md` on `feat/f25-g7-1-bounded-cloud`,
engine PR 789, open).

Risk: R2. Repo: decoy-engine. Plan branch `plan/f25-g7-2`. Build branch
`feat/f25-g7-2-bounded-sftp` (one slice). Row 58 (F25) acceptance item G7, owner 2026-11-24 and
2026-11-27: harden the existing engine SFTP read code for 1.0. No new CLI surface. The
user-facing SFTP features (rows 64 and 87, plan F02) stay 1.x.

## Where the engine reads SFTP today

`grep -rn -i "paramiko\|sftp" src` on `origin/main` (`6d6e1aca3`) finds one reader:
`SFTPFileSource` in `src/decoy_engine/connectors/sftp.py` (the public SDK connector). Its reads
are `open` (`sftp.py:321`), `head` (`sftp.py:303`), `list` (`sftp.py:279`) and `check`
(`sftp.py:272`). No other engine path reads SFTP:

- profile: `build_profile_source` refuses `type: sftp` (`profile/_readers.py:545-549`).
- run: the config source union has only `file`, `s3` and `gcs` (`config/_sources.py:99`, `:269`,
  `:326`). `tests/unit/test_v2_cloud_sources.py:94` pins the refusal.
- subset: an `sftp` source is accepted only as a local copy that the caller made
  (`subset/_api.py:351-385`). The engine never opens the remote file.
- No engine module calls `SFTPFileSource.open`. Its callers are SDK users and, in 1.x, F02.

Today `open` calls `remote_fp.read(1 MiB)` until a read returns nothing (`sftp.py:330-334`). Gaps:

1. No total bound. The loop reads until the server says EOF. A file that grows during the read,
   or a non-regular file (a FIFO, a device), is read without end.
2. No pin. Nothing records the file seen at open, so an in-place rewrite, an append or a
   truncation during the read comes back as if it were one file.
3. Not value-free. A failure inside the read loop (`sftp.py:331`) leaves as the raw paramiko or
   `OSError` exception, with server text. The wrapped errors copy SDK text (`sftp.py:81-87`), and
   every wrapped raise chains the SDK error (`raise ... from exc`, `sftp.py:165`, `:301`, `:309`,
   `:327`).
4. No time bound on one request. The channel has no read timeout, so a black-holed server stops
   a read for ever. `timeout=15` (`sftp.py:149`) bounds only the TCP connect.

## Guarantee and non-goals

**Guarantee.** A read through `SFTPFileSource.open` is bounded per request and in total, and is
pinned to the file seen at open:

- Per request: each piece asks for at most 1 MiB and never more than the bytes left. paramiko
  sends each piece as SFTP READ requests of at most 32 KiB (`MAX_REQUEST_SIZE`, paramiko 5.0.0
  `sftp_file.py:59`). Each request ends within the channel timeout (60 s, OQ-2).
- In total: the read returns exactly the size seen at open, never more.
- Pinned: size, mtime and file type come once from the open handle (`fstat`). Before each piece
  is yielded, a new `fstat` of the same handle must match them. If not, the read fails with kind
  `source_changed` and that piece is not yielded.
- Value-free: every failure that leaves `SFTPFileSource` (read, `head`, `list`, `check`, and the
  shared connect) is a `ConnectorError` subclass with fixed text and a `kind`. It holds no data
  bytes, no server or SDK text and no secret, in `str`, `repr`, `args` or `__notes__`. Its
  `__cause__` and `__context__` are `None`.
- Parity: a read of an unchanged regular file that `main` completes still completes, with the
  same bytes in the same chunk sequence (1 MiB chunks, the last one shorter). The connector yields
  bytes, not a frame, so "same frame" here means same bytes and same chunks.

**What SFTP can and cannot detect.** SFTP v3, the version paramiko and OpenSSH speak, gives a
64-bit size, a permissions and type field, uid and gid, and atime and mtime as uint32 seconds
(draft-ietf-secsh-filexfer-02, section 5). It has no inode, no change time, no version id and no
content hash. OpenSSH does not serve the `check-file` extension. So:

- Detected: an append, a truncation, any rewrite that changes the size, and any rewrite that
  moves mtime by at least one second.
- Not detected: a same-size rewrite inside the same second as the open, and a rewrite that sets
  mtime back (for example `touch -d`). Accepted under the V1 threat model (accidental changes
  only). F02 states the same limit for its resume rule.
- Not a change: a replace by rename after open. On a POSIX server the open handle keeps reading
  the old file, so the read returns one consistent file, the one seen at open. The pin comes from
  the handle, not from a path `stat`, so the read does not refuse in this case.

**Non-goals.**

- Resume after a dropped transport, retry of SFTP reads, the session factory, agent and
  `identity_file` auth, the typed unknown-host error, and the SFTP CI lane. These are F02-E3 and
  F02-E4 (plan `docs/plans/2026-11-17-f02-sftp-cloud.md` on `plan/f02-sftp-cloud`, row 87, 1.x).
  This slice builds the read and classify pieces that F02 names (`iter_sftp_file`, `sftp_error`
  in `connectors/_sftp_client.py`), so E3 adds the session and resume around them without moving
  code.
- The SFTP sink (`SFTPFileSink.write`, stage then rename): F02-E4. Its error text becomes
  value-free here only because it shares the one classifier.
- A configured byte limit on SFTP reads. The total bound is the size at open. A new cap would
  refuse reads that `main` completes. Byte quotas are row 58b (1.x).
- The platform's own SFTP reader (`api/cloud/reader.py` in decoy-platform): platform is parked.
- A profile, run or subset SFTP table reader. None exists; adding one is F02-E5.

## Behaviour

`SFTPFileSource.open(path)` becomes a thin call: connect as today (`_connect`, `sftp.py:212`),
then `yield from iter_sftp_file(sftp, full_path)`. `iter_sftp_file` lives in the new module
`connectors/_sftp_client.py` and does this:

1. Open the handle with `sftp.file(full_path, "rb")`. paramiko defines `SFTPClient.file = open`
   (`sftp_client.py:385`). The `file` spelling keeps the call out of the outbound sentry's GCS
   name set, as F02 4.4 decided.
2. `fstat` the handle (`SFTPFile.stat`, paramiko `sftp_file.py:274`). The pin is
   `(st_size, st_mtime, st_mode)`. A missing `st_size` or `st_mtime` is `source_changed`, the
   G7-1 rule for a missing ETag or generation. A present `st_mode` that is not a regular file is
   refused before any byte is read (kind per OQ-1). A missing `st_mode` reads as today.
3. While bytes are left: read `min(1 MiB, left)`. An empty or short result before `left` reaches
   zero means the file was truncated: `source_changed`. Then `fstat` the handle. Any difference
   from the pin is `source_changed`. Only then yield the piece.
4. After `size` bytes the loop ends. It never asks past the size, so a file that grew, or a
   device that never ends, cannot make it read more.
5. The handle is closed in `finally` on every exit, including a consumer that stops early
   (`GeneratorExit`). A failure of `close` itself is still swallowed, as today
   (`sftp.py:336-339`): the bytes were already checked.

Every paramiko or OS failure in steps 1 to 3, and in `_open_sftp`, `list`, `head` and the sink,
goes through one classifier `sftp_error(exc) -> ConnectorError`. The caller raises its result
after the `except` block closes (the `_clients._call` rule, `connectors/_clients.py:150-162`).
Kinds, by exact type, follow the F02 4.4 table:

| Exception | Class | Kind |
|---|---|---|
| a `ConnectorError` already raised by engine code | same class (`refreshed_error`, `_clients.py:78`) | same kind |
| `paramiko.BadHostKeyException` | `PermanentError` | `host_key_rejected` |
| `paramiko.BadAuthenticationType`, `AuthenticationException`, `PasswordRequiredException` | `PermanentError` | `credentials` |
| other `paramiko.SSHException` | `TransientError` | `transient` |
| `FileNotFoundError` (paramiko turns `SFTP_NO_SUCH_FILE` into `OSError(ENOENT)`) | `PermanentError` | `not_found` |
| `PermissionError` | `PermanentError` | `access_denied` |
| `socket.timeout`, `EOFError`, `ConnectionResetError`, other `OSError` | `TransientError` | `transient` |
| `paramiko.SFTPError` (protocol: "Expected data", "Garbage packet") and anything else | `PermanentError` | `unexpected` |

The classifier reads paramiko from `sys.modules` and never imports it: when paramiko was never
imported, no paramiko exception can exist. So the module and its non-paramiko cells run in the
base environment. The text test `"No such file" in str(exc)` (`sftp.py:80`) goes.

Classes stay as today for every case that today's tests pin: a bad host key and a bad auth type
stay `PermanentError` (`test_sftp.py:174-217`); a missing path stays `PermanentError`
(`test_sftp.py:169`). `_parse_private_key` (`sftp.py:189`) drops `{last_exc}` from its message.
`CheckResult.detail` keeps `str(exc)`, which is now fixed text.

`_open_sftp` calls `sftp.get_channel().settimeout(60)` after `open_sftp()`, so one request ends
within 60 s (the F02 4.4 bound, OQ-2).

`SFTPFileSource.open` and `SFTPFileSink.write` stop calling `sftp.open`. The sink moves to
`sftp.file(full_path, "wb")` too, so both rows leave `tests/sentry/baselines/gcs-call-kwargs.json`.

## Design notes

- New structure: one private module, `connectors/_sftp_client.py`, with two functions. Pain it
  addresses: F02-E3 and E5 add a second and third SFTP reader (resume, table reads). With one
  read function and one classifier, those readers wrap the pinned read instead of copying it.
- Established pattern: the S3 and GCS connectors' one classifier per provider with fixed text
  (`_clients._s3_kind`, `_gcs_kind`, `_classified`), and F02 4.4 for names and the kind table.
- One place per fact: the pin rule and the read bounds sit in `iter_sftp_file`; the
  exception-to-kind table sits in `sftp_error`; fixed words stay in `_clients._PHRASE`.
- No flag arguments: the read takes the client and the path; the piece size is the module
  constant `_DEFAULT_CHUNK_BYTES` (`sftp.py:46`), moved, not a parameter.

## Failure modes

| Failure | Detected at | Result (kind) | Value-free | Test |
|---|---|---|---|---|
| File grew (append) during the read | `fstat` after the piece, step 3 | `PermanentError` `source_changed`; the piece read after the change is not yielded | fixed text, nothing chained | 4 |
| File truncated during the read | short or empty read before `left` is zero, step 3 | `source_changed` | fixed text | 5 |
| Same-size rewrite, mtime moved | `fstat` after the piece | `source_changed` | fixed text | 6 |
| Open `fstat` lacks size or mtime | step 2 | `source_changed`, zero bytes read | fixed text | 7 |
| Not a regular file (FIFO, device, directory) | step 2 | refused before any read; kind per OQ-1 | fixed text | 8 |
| Server would send data past the size seen at open | never asked: step 4 stops at `size` | read completes with `size` bytes | n/a | 3 |
| Path missing or denied at open | `sftp.file` | `not_found` or `access_denied` | fixed text | 10 |
| Transport drop, timeout or reset mid-read | piece read or `fstat` | `TransientError` `transient` | fixed text | 10 |
| Server stalls a request | channel timeout (60 s) | `transient` | fixed text | 12 |
| SFTP protocol error | piece read, `fstat` | `unexpected` | fixed text | 10 |
| Host key, auth failures | `_open_sftp` | `host_key_rejected`, `credentials` | fixed text | 10, 14 |
| Consumer stops early | generator close | handle closed, nothing raised | n/a | 11 |
| `close` fails after a full read | `finally` | swallowed, as today | n/a | 11 |

## Acceptance tests, red first

Cases 1 to 13 run in the base environment (no paramiko) on a fake SFTP client and handle in the
new `tests/connectors/_sftp_fakes.py`. The fake records a ledger of every call (`file`,
`read(n)` with `n`, `stat`, `close`) and raises on `prefetch`, `readv`, `getfo` and `get`. Each
case has a non-vacuity check: the ledger shows the call, or the canary is present in the input.
"Red on `main`" says why the case fails today. "Mutation" names the guard change that must turn
it red again on the final head.

1. Parity (property test). Hypothesis, fixed seed, body sizes from 0 to 5 MiB with the boundary
   values 0 B, 1 B, 1 MiB - 1 B, 1 MiB, 1 MiB + 1 B and 3.5 MiB pinned as examples: the chunk
   list from `SFTPFileSource.open` equals the chunk list of `main`'s loop (`read(1 MiB)` until
   empty) on the same bytes, chunk by chunk. Green on `main` by design (non-regression).
   Mutation: read the whole `left` in one call: red on the chunk boundaries.
2. Per-request bound. Every `read(n)` in the ledger has `n <= 1 MiB` and `n <=` bytes left; the
   sum of asks equals the size; no `prefetch`, `readv`, `getfo` or `get`. Red on `main`: its last
   ask goes past the end, and it makes one more read at EOF. Mutation: always ask 1 MiB.
3. Total bound. A handle whose `fstat` says N bytes but whose reads never end (a `/dev/zero`
   shape; the fake fails the test after 2N bytes so `main` cannot hang the run): exactly N bytes
   are yielded and the read completes. Red on `main`. Mutation: loop until an empty read.
4. Append during the read. The fake grows the file and moves mtime after piece k is read: the
   read raises `source_changed`, and the consumer received pieces 0 to k-1 only. Red on `main`,
   which returns the grown bytes. Mutation: check the pin only after the last piece: red, piece k
   was yielded.
5. Truncation. The file shrinks after piece k: `source_changed`. Red on `main` (a silent short
   body). Mutation: treat an early empty read as the end.
6. Same-size rewrite with a new mtime: `source_changed`. Red on `main`. Mutation: compare size
   only.
7. Open `fstat` with `st_size` or `st_mtime` `None`: `source_changed`, zero `read` calls in the
   ledger. Red on `main` (no `fstat`). Mutation: default a missing value to 0.
8. `st_mode` of a FIFO, a character device and a directory: refused with the OQ-1 kind, zero
   `read` calls. A `None` `st_mode` reads as today. Red on `main`. Mutation: drop the file-type
   test.
9. Pin source. The fake replaces the path by rename after open: a path `stat` shows another size
   and mtime, and the handle keeps the old bytes. The read completes with the old bytes, and the
   ledger shows no `stat(full_path)` call inside `iter_sftp_file` (the liveness probe `stat(".")`
   in `_connect` is told apart by its argument). Mutation: take the pin from
   `sftp.stat(full_path)`: red on both checks.
10. Value-free classification. A corpus of failures, each with a data, path, host and user
   canary in its message: `FileNotFoundError`, `PermissionError`, `OSError(ECONNRESET)`,
   `socket.timeout`, `EOFError`, `RuntimeError`, and a `ConnectorError` that carries a canary.
   The fake raises each one at each point: `file` (open), the k-th `read`, the k-th `fstat`,
   `listdir_attr` (`list`), `stat` (`head`), connect, and the sink's `write`. The error that leaves
   `SFTPFileSource` or `SFTPFileSink` has the class and kind of the Behaviour table. The canary is
   absent from `str`, `repr`, `args` and `__notes__`; `__cause__` and `__context__` are `None`;
   captured logs hold no canary; `check().detail` equals the fixed text. Red on `main`: `{exc}` in
   the message, `from exc`, and the raw exception from the read loop. Mutations: restore
   `from exc` at a caller; restore `f"SFTP path not found: {exc}"`; remove the classifier around
   the piece read.
11. Cleanup. The handle is closed exactly once on: a full read, a consumer that stops after the
   first chunk (`gen.close()`), each refusal of cases 4 to 8, and each mid-read failure of case
   10. A `close` that raises after a full read does not fail it. Red on `main` for the refusals
   (they do not exist). Mutation: drop the `finally`.
12. Request timeout. `_open_sftp` with a fake SSH client: the channel's `settimeout` was called
   with 60 after `open_sftp()`. Red on `main`. Mutation: drop the call.
13. Read-primitive sentry `tests/sentry/test_sftp_read_primitives.py`. It parses the AST of
   `connectors/sftp.py` and `connectors/_sftp_client.py` and flags attribute calls on any
   receiver: `.prefetch(`, `.readv(`, `.getfo(`, `.get(`, `.open(`, and `.read()` or `.read(-1)`;
   a `.file(` call with a read mode is allowed only in `iter_sftp_file`, by exact
   `(path, function)`. Covered spellings: plain and chained attribute calls, `getattr` with a
   literal name. Not covered: names built at run time (V2-LOG). Seeded scratch modules with each
   form are flagged. Mutation: add `fp.prefetch()` to `iter_sftp_file`: red.
14. Real paramiko (runs where paramiko is installed; where is OQ-3). An in-process paramiko SFTP
   server (`paramiko.SFTPServer` with a `SFTPServerInterface` stub over a socket pair, the pattern
   of paramiko's own test suite) serves a temporary directory. Case 1 parity on fixed sizes with
   the real client; case 4 with a real append between pieces (the test appends after the first
   chunk is received); the open handle's `stat()` carries `st_size`, `st_mtime` and `st_mode`;
   the paramiko-typed rows of case 10 (`BadHostKeyException`, `AuthenticationException`,
   `BadAuthenticationType`, `PasswordRequiredException`, other `SSHException`, `SFTPError`)
   classify as the table says, with no canary. Mutation: as case 4.

Existing tests: `tests/connectors/test_sftp.py` and `test_sftp_stale_session.py` pass unchanged,
except that `_FakeSFTPFile` gains `stat()` and `_FakeSFTPClient` gains `file`. These are fixture
changes, not assertion changes. They still skip without paramiko; OQ-3 says where they run.

## Choke points

| Choke point | Where | Callers | Guard mutation (test that must go red) |
|---|---|---|---|
| Pinned bounded SFTP read | new `_sftp_client.iter_sftp_file(sftp, path)` | `SFTPFileSource.open` (`sftp.py:321`); later F02-E3 resume and E5 table readers | M1 always ask 1 MiB: case 2. M2 loop to an empty read: case 3. M3 check the pin only at the end: case 4. M4 early EOF as the end: case 5 |
| Pin from the handle | `iter_sftp_file` step 2, `fp.stat()` | the read above | M5 pin from `sftp.stat(path)`: case 9. M6 size-only compare: case 6. M7 missing value as 0: case 7. M8 drop the file-type test: case 8 |
| One SFTP classifier, raised after the handler | new `_sftp_client.sftp_error(exc)` on `_clients._classified` and `refreshed_error` | `_open_sftp`, `list`, `head`, `iter_sftp_file`, `SFTPFileSink.write` (replaces `_wrap_sftp_error`, `sftp.py:49-87`) | M9 `raise ... from exc`: case 10. M10 restore `{exc}` text: case 10 |
| Handle cleanup | `finally` in `iter_sftp_file` | every exit | M11 drop the `finally`: case 11 |
| Request time bound | channel `settimeout(60)` in `_open_sftp` | every SFTP operation | M12 drop the call: case 12 |
| No unbounded paramiko read primitive | sentry case 13 | `connectors/sftp.py`, `connectors/_sftp_client.py` | M13 add `prefetch()`: case 13 |

## Established solutions

Searches run: web search for paramiko `SFTPFile.prefetch` and `getfo` memory on large files
(paramiko 5.0 SFTP API docs at docs.paramiko.org; Jadaptive technical report "Analysis and
mitigation of Paramiko's unbounded SFTP prefetching"; a public gist of a bounded paramiko
downloader that uses private API); web search for the SFTP v3 attributes
(draft-ietf-secsh-filexfer-02 on datatracker.ietf.org, and the `pkg/sftp` Go library's
`filexfer/attrs.go`, which encodes size as uint64 and atime and mtime as uint32 per section 5).
Codebase: paramiko 5.0.0 source in a locked venv: `sftp_file.py` `_read` (`:179`) caps each
request at 32768 bytes, `stat` (`:274`) is FSTAT on the handle, `prefetch` (`:438`) and `readv`
(`:484`) request whole spans and buffer replies; `file.py:156` `read(n)` returns at most `n`
bytes, fewer only at EOF; `sftp.py:211-218` refuses a packet whose length has the high byte set,
so one reply is under 16 MiB. Also the F02 plan (sections 2 and 4.4) and the G7-1 plan.

| Option | What it gives | Decision |
|---|---|---|
| paramiko `SFTPFile.prefetch`, `readv`, `SFTPClient.get` and `getfo` | pipelined, faster reads | not used: `get` and `getfo` call `prefetch`, which sends a READ for every 32 KiB of the file with no concurrency limit by default and buffers the replies (Jadaptive report; paramiko docs show `max_concurrent_prefetch_requests` defaults to none). That loses the per-request and total bound. Case 13 keeps them out. V2-LOG: a bounded prefetch window |
| fsspec `sftp` (`SFTPFileSystem`) | file-system API over paramiko | not used: a thin paramiko wrapper with no pin, a new dependency, and it bypasses the classifier |
| rclone SFTP | size check after transfer; optional hash by running `md5sum` over an SSH shell | size check followed (per piece). The shell hash is not: SFTP-only accounts have no shell |
| asyncssh | SFTP v4 to v6, with sub-second times when the server offers them | not used: OpenSSH serves v3 only, and a second SSH stack adds an event loop (F02 made the same call) |
| SFTP `check-file` extension (`SFTPFile.check`) | server-side hash | not used: OpenSSH does not serve it |
| F02 4.4 resume rule (size and mtime from the first `stat`) | the pin fields | followed, with the pin taken from the handle `fstat`, so a rename after open is not a false change |
| G7-1 `check_ranged_response`, `_exact`, `guarded`, `_memory_text` | HTTP range checks, short-body test, library error guard, memory text test | not reused. SFTP has no HTTP status or `Content-Range`. `_exact` takes a ranged `fetch` and sits in `profile/`, which connectors must not import. The SFTP read parses nothing, so there is no library parse to guard and no memory text. The rules carry over: a short read is `source_changed`, fixed text, nothing chained |

Custom code left: the read loop with the per-piece `fstat` (about 40 lines) and the kind table
(about 40 lines). No library offers a pinned SFTP read.

## Enumerations

### Exit paths

- Normal end after `size` bytes; handle closed in `finally` (`src/decoy_engine/connectors/sftp.py:335`).
- Open failure from `sftp.file` (today `sftp.open`, `src/decoy_engine/connectors/sftp.py:325`).
- Piece read failure, short read, `fstat` mismatch inside the loop (`src/decoy_engine/connectors/sftp.py:330`).
- Consumer close (`GeneratorExit`) at a `yield`.
- Connect failure in `_open_sftp` (`src/decoy_engine/connectors/sftp.py:164`).

### Routes

- `SFTPFileSource.open`, `head`, `list`, `check` (`src/decoy_engine/connectors/sftp.py:321`, `:303`, `:279`, `:272`).
- `SFTPFileSink.write` and `check`, error text only (`src/decoy_engine/connectors/sftp.py:358`, `:351`).
- Profile, run and subset: no SFTP reader (`src/decoy_engine/profile/_readers.py:545`, `src/decoy_engine/subset/_api.py:351`).

### FK shapes

N/A: the connector yields the bytes of one file; no relational data crosses it.

### Fields

- Pin: `SFTPAttributes.st_size`, `st_mtime`, `st_mode` from the handle `fstat`.
- `ConnectorError.kind` and fixed text from `_clients._text` (`src/decoy_engine/connectors/_clients.py:66`).
- `CheckResult.detail` (`src/decoy_engine/connectors/sftp.py:276`).

### Output surfaces

- Exception `str`, `repr`, `args`, `__notes__`, `__cause__`, `__context__` (case 10).
- `CheckResult.detail` (case 10).
- Captured logs (case 10). paramiko's own logger is not forwarded by the engine (unchanged).
- Yielded chunks (cases 1 to 9).

## Class table (plan contract catalog)

| # | Class | Closing structure | Proof | Mutation |
|---|---|---|---|---|
| 1 | Value-bearing output | one `sftp_error` with fixed text, raised after the handler | case 10 canary per surface | M9, M10 |
| 2 | Cleanup missing on an exit path | `finally: fp.close()` in `iter_sftp_file` | case 11 on every exit | M11 |
| 3 | State machine and concurrency | N/A: one handle per read and no new shared state; the cached session is unchanged (`test_sftp_stale_session.py`) | n/a | n/a |
| 4 | Route parity and silent fallback | one read function and one classifier for every SFTP route | cases 1, 10 | M1, M9 |
| 5 | Referential integrity | N/A: the bytes of one file, no FK data | n/a | n/a |
| 6 | Untrusted producer (SFTP server replies) | never ask past the size; per-piece `fstat` check; no unbounded paramiko primitive; request timeout | cases 2, 3, 12, 13 | M1, M2, M12, M13 |
| 7 | Check then use (TOCTOU) on the file | pin from the open handle, checked again before each piece is yielded | cases 4, 5, 6, 9 | M3, M5, M6 |
| 8 | Weak tests and overclaimed evidence | ledger non-vacuity per case; case 14 with a real paramiko client and server | cases 2, 14 | M4 (early EOF as the end) |
| 9 | Behavior-preserving refactor drift | chunk-by-chunk property parity with `main`'s loop; existing tests unchanged except fixture methods | case 1, `test_sftp.py` | M1 (always ask 1 MiB) |
| 10 | Frozen contract drift | public SDK names, the `FileSource.open` signature and the error classes unchanged; kinds from the existing closed set | case 10 asserts class and kind | change a class: case 10 red |

## Recurring defects (dev-rules catalog)

| Class | Status |
|---|---|
| R1 anchored validation | n/a: no pattern validation added |
| R2 strict wire and stored types | n/a: no persisted model |
| R3 no exception context | case 10 asserts `__cause__` and `__context__` are `None` |
| R4 versioned read models | n/a: no persisted format |
| R5 normalized guard scanners | case 13 walks the AST for attribute calls on any receiver, covered spellings listed, seeded cases |
| R6 no reaching into private modules | `sftp.py` imports its sibling `_sftp_client` in the same package; nothing outside `connectors/` imports it |
| R7 no hidden CI failures | cases 1 to 13 run in every lane; the paramiko cases are OQ-3 |
| R8 one trust class per entry point | one trust class: SFTP server replies |
| R9 mutations on the final head | M1 to M13 rerun on the final head; the gate records each |
| R10 allowlisted helpers are still checked | `iter_sftp_file` is the one allowed `.file(` read call, by exact `(path, function)`, and the sentry still scans its body |
| R11 no raised caps | none raised; the exception-text and outbound baselines go down |

## Reuse inventory

- `_clients._classified`, `refreshed_error`, `source_changed`, `_text` and the `_PHRASE` table
  (`connectors/_clients.py:46-91`). The kinds `host_key_rejected` and `source_changed` already
  exist (`_error_base.py:13-27`).
- The raise-after-handler rule of `_clients._call` (`connectors/_clients.py:150`).
- `_DEFAULT_CHUNK_BYTES` (`sftp.py:46`) as the piece size, so the chunks match `main`.
- `_SFTPMixin._connect` and its liveness probe (`sftp.py:212-245`), unchanged.
- F02's module and function names (`_sftp_client.py`, `iter_sftp_file`, `sftp_error`), so F02-E3
  wraps them instead of moving them.

New names: module `connectors/_sftp_client.py`; functions `iter_sftp_file` and `sftp_error`.
Each replaces code in `sftp.py`; none is speculative.

## Frozen contracts

- `decoy_engine.sdk` and `decoy_engine.connectors` public names: unchanged.
- `FileSource.open(path) -> Iterator[bytes]`: unchanged. It is still a generator and still opens
  on the first `next`.
- Error classes per case: unchanged where today's tests pin them. Texts become fixed; the text was
  never a contract, and the F31 audit triage lists these sites
  (`docs/plans/evidence/2026-11-24-f31-audit/engine-triage.tsv`).
- `ConnectorErrorKind`: unchanged unless OQ-1 picks option (b).
- Baselines: `tests/sentry/baselines/engine-exception-text-copies.json` loses the
  `_wrap_sftp_error` and `_parse_private_key` rows; `gcs-call-kwargs.json` loses the two `sftp.py`
  `open` rows. Both only go down.

## Placement and expected sizes

| Path | Change | CODEMAP line | Beside | Lines now | Expected |
|---|---|---|---|---|---|
| `src/decoy_engine/connectors/_sftp_client.py` (new) | `iter_sftp_file`, `sftp_error` | `CODEMAP.md:286` | `sftp.py`, `_clients.py` | 0 | about 150 |
| `src/decoy_engine/connectors/sftp.py` | `open` delegates; classifier moves out; `.file(`; channel timeout | `CODEMAP.md:286` | `_sftp_client.py` | 388 | about 330 |
| `tests/connectors/_sftp_fakes.py` (new) | paramiko-free fake client and handle with a ledger | `CODEMAP.md:286` | `test_sftp.py` | 0 | about 140 |
| `tests/connectors/test_sftp_bounded_read.py` (new) | cases 1 to 9, 11 | `CODEMAP.md:286` | `test_sftp.py` | 0 | about 260 |
| `tests/connectors/test_sftp_error_text.py` (new) | cases 10, 12 | `CODEMAP.md:286` | `test_s3_error_text.py` | 0 | about 150 |
| `tests/connectors/test_sftp_real_server.py` (new) | case 14 | `CODEMAP.md:286` | `test_sftp.py` | 0 | about 170 |
| `tests/connectors/test_sftp.py` | fake gains `stat()` and `file` | `CODEMAP.md:286` | `test_sftp_stale_session.py` | 351 | about 362 |
| `tests/sentry/test_sftp_read_primitives.py` (new) | case 13 | `CODEMAP.md:164` | `test_outbound_clients.py` | 0 | about 90 |
| `tests/sentry/baselines/engine-exception-text-copies.json`, `gcs-call-kwargs.json` | rows removed | `CODEMAP.md:164` | other sentry baselines | n/a | smaller |

`connectors/` goes from 10 to 11 modules. Every file stays under 600 lines, so no census entry.

## Slices

One slice, engine repo, branch `feat/f25-g7-2-bounded-sftp`, about +1,000 / -80 lines, most of
it tests. Order: the fakes, then red tests 2 to 13, then `_sftp_client.py`, then the `sftp.py`
changes and the baseline removals, then case 14 and its run per OQ-3. Test depth per
`testing.md`: T0 the touched test files per edit; T1 impact-selected per commit; T2 gate on the
exact head with M1 to M13. No full-suite trigger is hit unless OQ-3 picks (b), which changes CI
configuration.

## Pre-mortem

- The fake does not behave like paramiko (for example `read(n)` returning more than `n`, or a
  handle `stat()` that lacks fields), so the bounds hold on the fake only. Case 14 runs the same
  parity and append cases on a real paramiko client and server.
- A server whose `fstat` mtime moves on every read (some network file systems update times
  oddly) refuses every read. Case 14 shows OpenSSH does not. The refusal names
  `source_changed`, so an SDK user sees the cause. V2-LOG: collect reports.
- The per-piece `fstat` adds one round trip per 1 MiB, about 3% over the 32 reads per MiB. The
  gate records a case 14 timing on a 64 MiB file for head and `main`.
- A later google-cloud-storage release adds `file` or `stat` to the outbound sentry name set: the
  baseline row comes back with the same reason text, and the gate notes it.
- A green base lane hides the paramiko cases (R7). OQ-3 decides where case 14 and `test_sftp.py`
  run, and the gate record names the run.

## V2-LOG

- A bounded prefetch window (at most k outstanding 32 KiB requests) for SFTP throughput.
- Unknown host key classified by type (`_UnknownHostKey`), not as `transient`: F02-E3.
- Resume after a dropped transport under the same pin: F02-E3 (`iter_sftp_file` is its place).
- Bound the paramiko reply size per request to the asked length. paramiko accepts up to 16 MiB
  per packet; this needs a paramiko change or a private hook.
- `CheckResult.detail` built from the kind instead of `str(exc)` (fixed text either way).
- Case 13 spellings built at run time.

## Owner questions

**OQ-1. Kind for a non-regular file (FIFO, device, directory) at open.**
(a) `unexpected`, text "Unexpected SFTP error": no contract change.
(b) A new kind, for example `not_a_file`: clearer to SDK users; an additive change to the public
closed set `ConnectorErrorKind`.
(c) `rejected`, text "SFTP rejected the request": no contract change, but the text says the
server refused, which it did not.
Recommended: (a) for 1.0, and (b) with F02.

**OQ-2. The 60 s per-request timeout.**
(a) Add it in this slice (F02 4.4 already chose 60 s): a request that stalls 60 s fails as
`transient` where `main` waits for ever.
(b) Leave it to F02-E3.
Recommended: (a). Without it, "bounded per request" holds for bytes but not for time.

**OQ-3. Where the paramiko cases run (case 14 and the existing `test_sftp.py`).** No CI lane
installs the `sftp` extra today, so they skip everywhere.
(a) The G7-2 gate runs them once in a deps-only `.venv-sftp` on the gate host (the F02
`gates.sh` command) and records the result. The CI lane stays F02-E3.
(b) Pull F02-E3's `sftp-gate` CI job and the `DECOY_REQUIRE_SFTP` helper into this slice (a CI
configuration change and a full-suite trigger).
Recommended: (a) for 1.0, since no 1.0 route reads SFTP; the gate record is the evidence.
