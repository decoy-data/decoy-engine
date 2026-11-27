# Output publication

How the engine creates, stages and binds an output directory, and what it promises about the
result. This page grows with the F22 publication work (plan
`docs/plans/2026-10-30-f22-publication-replan.md`); each section says what is in place today.
The reference sink commits through `publish_unit` on every route that uses it, and so does
the isolated route (`run_pipeline_isolated`, both modes; below). A unit published with a vault
is bound only after its vault is durable (vault before output, below).

Platforms: Linux and macOS, on both the ambient policy (`LocalFileAccess`, the CLI default) and
the strict policies (`RootedFileAccess`, `PreopenedFileAccess`). Windows keeps its plain path
calls until the Windows arm is built.

## Directories the engine creates

Every directory the engine creates on an output chain comes from one creation core with two
entry points (`src/decoy_engine/fileaccess/_output.py`):

| Entry point | Creates | Mode |
|---|---|---|
| `make_parent_dir_at` | missing parents of an output target, and the target of `ensure_dir`, at their real names | the born permission bits with the owner bits forced on: `(born & 0o777) \| 0o700`, plus an inherited set-group-ID bit |
| `make_stage_dir_at` | the private stage beside the target, and every subdirectory made inside a stage (`create_dir`) | exactly `0700` |

"Born" is the mode the filesystem gave the new directory: the umask, or a default ACL, decides
it. The engine observes it and repairs only the owner bits, so:

- under the ordinary umask `022`, a new parent is `0755`, as before;
- under a umask that strips owner bits (for example `0477`), a new parent is `0700` and the
  first attempt still publishes, where a plain `mkdir` would leave a directory the engine
  itself cannot open;
- in a set-group-ID parent, a new parent keeps the bit on Linux (a stage never does); on macOS it
  takes the parent's group without the bit.

The engine never reads or sets the process umask.

A parent is opened as it is created: each missing component is made under an open descriptor
of the directory above it, never by a path walk after the fact. When a parent appears between
the engine's check and its own `mkdir` (another attempt or another process made it), the engine
continues through the existing directory. It never changes the mode of a directory it did not
create.

On the ambient policy the user's path keeps its usual meaning: components with spaces, a
leading `.` or `_`, or non-ASCII characters are created as written, and an existing symlinked
ancestor is followed. On the strict policies every component is validated and no link is
followed.

## Durable publish: the `publication` label

An output transaction begun with `label="publication"` stages a directory (a file stage is
refused) beside the leaf under the name `._decoy_publication_pending_<token>`, which it keeps for
its whole life. Files created in it are `0600` and its directories `0700` on both POSIX
policies, whatever the umask: owner bits the umask stripped are restored before anything else
touches the file.

`publish()` is durable. In order:

1. every regular file and every directory in the stage is fsynced, deepest first, without
   following a link;
2. the stage is renamed onto the leaf, which must be absent or an empty directory;
3. the leaf's parent is fsynced: this is the commit point;
4. each directory above the parent is fsynced, deepest first, up to and including the anchor,
   whoever created it and whether or not it existed before.

The anchor is the capability root on the strict policies. On the ambient policy it is the mount
boundary: the walk goes up from the leaf's parent and stops below the first directory on another
device (`/` ends it). A failure in steps 1 or 2 raises an `OSError` with the errno only and leaves
the stage for `abort()`. A failure in steps 3 or 4 raises `CommitUncertain` (errno name only):
the unit is bound and visible, never removed, but not confirmed durable.

Unreadable directories on the chain: the leaf's parent, every parent this attempt created and
the directory above the topmost one must open and sync, or the publish fails. Above those, on the
ambient policy, a directory the engine cannot open ends the walk only when another uid owns it
(a home directory reached through `0711`, for example); one the engine's own uid owns but cannot
read is refused, because it may be the remains of an earlier attempt (named limit L1u). The
operator restores its owner bits.

### Stage liveness lock and stage marker (F26 E1)

Before a `publication` stage is handed to its caller, both POSIX policies:

- take `flock(LOCK_SH)` on the stage's own directory descriptor and hold it until the stage is
  bound, its `abort()` has removed the name, or the transaction is collected. The call blocks
  (a cleaner holding the exclusive lock is waited for) and retries `EINTR`; any other `OSError`
  leaves the stage unlocked and the run carries on, publishing the same unit;
- write `.decoy-publication-stage`, a `0600` regular file holding `decoy-publication-stage-v1:`,
  the stage name's 12-hex token and a newline, and read it back through the one proof reader.
  A marker that does not prove fails the `begin` and the stage is removed.

The marker is reserved metadata: it stays inside the bound unit, is fsynced with it, and is not
listed in the descriptor (a file left in the stage but not named is bound without being described,
above). Its leading dot keeps Arrow and pandas directory reads from treating it as a table. A
later `decoy cleanup` (F26) needs both: a stage whose lock it cannot take exclusively is live, and
only a stage with a valid marker can be removed. The win32 arm takes no lock and writes no marker.

Other labels (`table_sink`, `hold`, `quarantine` and the rest) publish as before.

## Destination lock and reading a bound unit

`OutputDir.lock(timeout_s)` is a context manager holding an exclusive `flock(2)` on
`.<leaf>.decoy-lock` in the leaf's parent (created `0600`, opened read-write because NFS emulates
`flock` with byte-range locks, and never unlinked). It polls until the deadline and then raises
`LockTimeout`. Where `flock` is not supported, or the lock file cannot be opened, it raises
`LockUnavailable`; there is no lock-free fallback. The kernel releases the lock when the holder
exits for any reason, SIGKILL included. The parent must exist: the lock creates nothing.

A publication destination leaf is at most 243 bytes, so that `.<leaf>.decoy-lock` fits one
255-byte name component (see the named limit below). `lock()` and `begin(...,
label="publication")` refuse a longer leaf with the policy's denial before any I/O: no parent is
created, no lock file and no stage. Other labels keep the 255-byte component limit.

`OutputDir.read_member(component, limit=...)` reads one regular file inside a bound directory
leaf through the same capability, at most `limit` bytes (`LeafTooLarge` beyond), and returns
`None` when the parent, the leaf or the member is absent. No link is followed at the leaf or the
member, and a FIFO or other special file is refused without blocking.

`OutputDir.sync_chain()` re-runs steps 1, 3 and 4 over a bound leaf (its whole tree, then its
parent and each directory up to the anchor), so state found on disk can be made durable before
it is trusted. On the ambient policy only the leaf and its parent are strict here: nothing was
created by this call.

`OutputDir.adopt_file(limit=...)` reads a vault-style file leaf for adoption: it opens the leaf
read-only (so a `0400` file opens) and never through a link, refuses anything but a regular file,
reads at most `limit` bytes (`LeafTooLarge` beyond), fsyncs that same descriptor and then the
chain, and only then returns the bytes, so the bytes returned are the bytes made durable. It
returns `None` when the parent or the leaf is absent. A directory fsync that the filesystem
reports as unsupported (`EINVAL`, `EBADF`, `ENOTSUP`) does not fail a chain walk.

On the strict policies all of these go through descriptors opened from the capability root, so a
symlink on the way to the leaf is refused, never followed out of the root. Windows has no arm yet:
`lock` raises `LockUnavailable`, the others raise `FileAccessUnavailable`, and a `publication`
publish there keeps the plain rename until the Windows arm is built.

All errors these paths raise carry an errno name and no path, file name or operating-system text.

## The managed pointer

`CurrentPointer(store, lock)` reads and swaps one small pointer file (`out/<name>/LATEST`) under
the F22 lock, with a compare-and-swap on raw bytes. `store` is a `PointerStore`; `LocalPointerStore(leaf)`
is the local one, and `lock` is the same leaf `OutputDir`, so `lock.lock(timeout_s)` takes
`.LATEST.decoy-lock`. The constructor refuses a store whose `locator()` differs from the lock's leaf.

- `read()` returns `PointerState(raw, version)`, or `PointerState(None, None)` when the file is
  absent. A link, a special file, a file over 4 KiB, a policy denial or an I/O error raises
  `PointerUnreadable`, a fixed message with no path or byte.
- `locked(timeout_s)` yields a `HeldPointer`. `HeldPointer.swap(expected, new)` writes
  `f"{new}\n"` (ASCII) only if the file still holds `expected.raw`. It returns `replaced`,
  `stale` (the pointer moved), `uncertain` (the new bytes are visible, not confirmed durable),
  `failed` (the replace did not happen) or `conflict`. A store answer of `unknown` gets one
  outcome-check read. A `HeldPointer` used after its context exits raises `RuntimeError`.
- `read_value(raw, accept)` returns the stripped value, or `None` and one value-free warning for a
  value that is over 4096 bytes, not ASCII, has no single trailing newline or is rejected by `accept`.

The write goes through the private file-access label `pointer`: a `0600` stage, fsync of the
stage, rename over the leaf (a link at the leaf is replaced, never written through), then fsync of
the parent. A parent fsync failure after the rename raises `CommitUncertain`, which the store maps
to `uncertain`. `publish_replace_durable` fsyncs the file and its immediate parent only. No pointer
path calls `sync_chain`: the run folder already exists from the chain-synced unit publish, so only
the pointer's own file and parent are new. A crash can leave a private pointer stage beside
`LATEST`; sweeping it is a named limit (V2-LOG). Only `publication/_current.py` may name the label
(`tests/sentry/test_pointer_label_caller.py`).

## The delivery stage

`DeliveryStage` makes one run folder (`out/<name>/<run-id>/`) and the pointer move together. The
stage reads only plain data, so `publication` never imports `delivery`: the caller passes
`StageDecision(deliver, delivered)`, the tables the decision delivers.

- `DeliveryStage.open(out, pointer, run_id, operation_id)` first checks the destination: the
  output leaf must be exactly the run id, and its parent folder must be the pointer's parent
  folder (compared by device and inode, so under the ambient policy a symlinked spelling of the
  parent opens, and a strict root refuses a link beneath it). A mismatch is a `ValueError`
  before any pointer read, lock or stage. Then it reads the pointer, opens a `publication`
  unit stage and a `delivery_slots` stage beside the run folder, and probes that the target
  can claim files (see "Named limits"). An unreadable pointer (a link, a special file, over
  4 KiB), a stage that cannot open, or a failed probe raises `PublicationFailed`
  (`publication_failed`) before a writer runs. `run_id` must be a value the pointer reader
  accepts.
- `reserve(table, relpath, role="table")` returns a `StagedMember`. `table` is the table the
  file belongs to; `None` (the post-scan report) is always delivered. Nothing exists at the
  member's `path`: the unit's folders are made (a folder this stage already made is reused by
  its exact name) and the writer's slot is a numbered folder `s<n>/` in the slots stage, so the
  writer sees the file's real name, extension and any 255-byte basename. The writer writes to
  `path`, closes the file, then calls `complete()`, which claims the file into the unit with a
  no-clobber hard link: the target file system decides whether the name is taken. The claimed
  file is mode `0600` with one link. A zero-byte file is a valid member. `fail()` marks the
  member unusable. `omit()` drops an optional member that was never written (a quarantine run
  with no rows). `staged_path(table)` is the reserved destination in the unit stage, whatever
  the completion state; the quarantine alias guard compares it with the sidecar's destination.
  `stage_dir()` is the slots stage root, for spill and temporary files; it is always discarded.
  A duplicate path or a file/folder clash is a `ValueError`; a name the target treats as taken
  (for example `D` after `d` on a case-insensitive volume) is `PublicationFailed` with errno
  `EEXIST`. A failed `reserve` removes only the folders it made.
- `set_vault(VaultBinding)` has `publish_unit` publish the vault create-only before the bind
  (rule V).
- `deliver(decision, before_visible, reconcile=None)` first prunes: a claimed file of a table
  the decision does not deliver is removed from the unit, then folders left empty. Only a
  claimed file is ever removed; a failed, omitted or pending reservation never authorizes a
  removal. A member of a delivered table that was never completed gives `nothing`. Then it takes
  the pointer lock, compares the pointer with the state read at `open`, checks that every
  claimed member is still the same inode (one link, mode `0600`, no two members the same
  inode), calls `before_visible()`, binds the unit with `publish_unit`, then swaps the pointer
  with that same state. `reconcile(receipt)` runs under the lock with the final receipt and must
  not raise. An exception or interrupt after the lock is held is judged by one pointer re-read
  (`LATEST` names this run: `uncertain`), reconciled once, and only then is the lock released
  and the error raised again. An interrupt before the lock settles with no read.
- The stage writes local paths, so a member's `path` needs the ambient policy; a strict policy
  refuses `local_stage_path` at `reserve`. The stage makes no file-system call of its own: it
  goes through `StageDir`, `OutputTxn` and `OutputDir` only.
- A second interrupt while `deliver` settles a receipt can leave the stage state `delivering`; the
  pointer, not the state, says whether the run is visible.
- `abort()` removes both stages and never touches the pointer; it is a no-op after `delivered`. A
  `deliver` after `abort` raises `RuntimeError`.

`DeliveryReceipt(state, cause)` has state `delivered`, `uncertain` (visible, durability unknown;
counts as delivered) or `nothing`. Every F22 outcome and every pointer result maps to one state:

| Source | Value | State | Cause |
|---|---|---|---|
| bind | `published`, `already_committed` | go on to the swap | none |
| bind | `commit_uncertain` | go on to the swap; at most `uncertain` | `publication_commit_uncertain` |
| bind | `refused` | `nothing` | F22's code (target occupied, lock timeout or unavailable, vault mismatch or conflict) |
| bind | `operation_conflict` | `nothing` | `publication_operation_conflict` |
| bind | `failed` | `nothing` | `publication_failed` |
| compare, before the bind | pointer moved | `nothing`, nothing bound | `delivery_pointer_moved` |
| swap | `replaced` | `delivered` | none |
| swap | `stale` | `nothing`; the bound run folder stays, not current | `delivery_pointer_moved` |
| swap | `uncertain`, `unknown` | `uncertain` | `publication_commit_uncertain` |
| swap | `failed`, `conflict` | `nothing` | `publication_failed` |

A vault published for a run that then does not deliver stays on disk. The next run that names
the same `--vault` path refuses until it is deleted.

## The vault commit

`VaultWriter.publish(out)` writes the vault as `write` does (private stage, file fsync, exclusive
`link`, directory fsync) and then fsyncs the vault's whole chain up to the anchor, with the same
rules as the output chain. It returns a `VaultCommit(sha256, size, entry_count, adopted=False)`.
Only the vault module issues one, so a holder knows the leaf and its chain were fsynced in that
call. `write` fsyncs the chain too. When the leaf already exists (`vault_exists`),
`publication._vault_order.adopt_vault(out, writer)` adopts it durably or refuses: `adopt_file`
fsyncs the leaf and its chain, then `same_rows` opens the bytes under the writer's key
(`BytesHandle`, constant display `<vault>`) and compares the rows and the dropped-key count.
Equal rows give `VaultCommit(..., adopted=True)` and the leaf is never rewritten. A leaf that
cannot be read or made durable (an fsync failure, or a leaf deleted out of band) raises
`VaultError` with `vault_commit_failed`; other rows, another key's data, a leaf over twice this
vault's size plus 64 KiB, or a leaf that is not an adoptable file (`ELOOP`, `EINVAL`, `ENOTDIR`,
`EISDIR`) returns a `VaultConflict`
(never `None`, which `adopt_file` uses for an absent leaf), and `publish_unit` refuses with
`publication_vault_conflict`. No error text carries a path, key or row.

## The `decoy-publication/v1` descriptor

Package `decoy_engine.publication` (`_descriptor.py`) defines the descriptor a published unit
carries as `_decoy_publication.json` at its root; `publish_unit` (below) writes it. This section
is the format.

The bytes are the engine's one canonical JSON form (`decoy_engine._canonical.canonical_json_bytes`):
keys sorted, separators `,` and `:` with no whitespace, UTF-8 with text written as-is (no `\u`
escapes), no NaN or infinity. Equal content therefore has equal bytes, and `descriptor_digest` is
the SHA-256 of the bytes. A value with no UTF-8 form (an unpaired surrogate, as an undecodable
filename gives) is refused as `not_canonical` by the writer and the reader.

| Field | Type |
|---|---|
| `schema` | exactly `"decoy-publication/v1"` |
| `unit` | `"immutable_directory/v1"` |
| `operation_id` | the caller's id, `[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}` |
| `result_id` | 64 lowercase hex digits |
| `artifacts` | array sorted by `path`, paths unique; each `{path, role, rows, sha256, size}` |
| `vault` | `null`, or `{sha256, size, entry_count}` |
| `engine_version` | the writing engine's version |

An artifact `path` is relative to the unit root, `/`-separated; no component is empty, `.` or
`..` or holds NUL, a path has at most 8 components, no two paths are equal, no path is a folder
of another (`a` beside `a/b`), and the path is never a reserved name (the descriptor's own name
or the stage marker, compared without case). `role` is `"table"`, `"quarantine"` or `"report"`.
`rows` is the Parquet footer count for a `table` whose path ends in `.parquet`, and `null` for
every other member; the key is always present, and a `.parquet` table with `null` or any other
member with a number is refused. `size` and `entry_count` are JSON integers from 0 to 2^63 - 1. Digests are 64 lowercase hex
digits.

`result_id` is the SHA-256 of `decoy-publication-result/v1`, a NUL byte, and the canonical JSON
of the sorted artifact array. It names the output content only: it leaves out `operation_id` and
the vault, so two attempts that produced the same files have the same `result_id`, and a vault is
judged by its rows, not by a digest stored here.

`operation_id` contract: one `operation_id` names one intended result for one destination.
Reusing it for a different result is an `operation_conflict`, and a matching `operation_id` is
never taken as evidence of an equal result; only an equal `result_id` is.

One field declaration drives the writer and the reader, so the engine cannot write a descriptor
it would refuse to read. The reader refuses a stored descriptor when any of these holds: over
1 MiB; not UTF-8 JSON; a duplicate key; a non-finite number; not an object; `schema` missing or
not exactly `decoy-publication/v1`; a field missing or unknown, at any level; a value of the wrong
JSON type (a `true` is never a count, `"640"` is never a number); a count out of range; a token
outside its closed set; a digest, `operation_id` or version that does not match its shape in full
(a trailing newline included); an unsafe path; artifacts out of order or repeated; a `result_id`
that does not recompute; bytes that are not the canonical encoding. The refusal is a `ValueError`
whose text is `descriptor_refused:<check>`, a closed token, with nothing from the bytes.
`publish_unit` turns any refusal into `publication_target_occupied`, so a malformed record never
drives a judge or an adoption.

The request and receipt types (`_types.py`) are checked when built: `PublicationRequest`
(`operation_id`, `unit`, `overwrite` = `"refuse_different"`, `vault`, `lock_timeout_s`, default
30 seconds), and `CommitReceipt` (`outcome`, `operation_id`, `reason_code`, `result_id`,
`descriptor_digest`, `vault_digest`, `artifacts`, `visible`, `durable`, `os_error`), whose
`ArtifactSummary` entries hold `role`, `size`, `rows` and `sha256`, never a name or a path.

## Judge and bind: `publish_unit`

`publish_unit(out, txn, request, tables=[...])` binds one `immutable_directory/v1` unit: `txn` is
a `publication` stage of `out` holding exactly the Parquet tables named in `tables`, each a file
directly in the stage. `publish_tables(out, {name: table}, request)` is the resident entry: it
stages each table under its name and calls `publish_unit`. The caller names the files; the
publisher measures every one itself through the stage (size, SHA-256, row count from the Parquet
footer), never taking a number from the producer.

`publish_unit(out, txn, request, members=[Member(path, role), ...])` takes members that are not
flat Parquet tables: nested paths such as `masked/customers.csv`, a CSV or fixed-width table, the
quarantine file (`quarantine`) and the post-scan report (`report`). Pass `tables` or `members`,
never both. Every path passes one rule before the lock is taken (`check_unit_path` for each,
`check_unit_paths` for the set), the same rule the descriptor reader applies. The stage is
closed: the publisher walks it through `StageDir.entries` and `StageDir.open_subdir` and refuses
(`publication_failed`, nothing bound) any entry no member names, a link, a special file, a
folder that is not a prefix of a member, or a member of the wrong kind. Only the stage's own
marker at the root is allowed. An empty file is hashed as the empty string with size 0.

A reader older than this change that meets a unit with `rows: null`, a `quarantine` or `report`
member or a nested path cannot load its descriptor and treats the leaf as occupied
(`publication_target_occupied`); it never overwrites the unit. A rerun of the same run id on
such a reader therefore refuses, and a new run id is unaffected.

Under the destination lock, held from the first read to the bind:

1. the bound descriptor is read (at most 1 MiB) and this attempt's tables are measured into a
   new descriptor and its `result_id`;
2. the two are judged:

| At the leaf | Same `result_id` | Same `operation_id` | Outcome |
|---|---|---|---|
| nothing, or an empty directory | - | - | bind |
| a valid descriptor | yes | any | `already_committed`, after the vault check (below) and after the unit tree and its chain to the anchor are fsynced |
| a valid descriptor | no | yes | `operation_conflict` |
| a valid descriptor | no | no | refused, `publication_target_occupied` |
| anything else: files without a descriptor, a descriptor that is unreadable, over 1 MiB or refused by the reader, a file or link at the leaf | - | - | refused, `publication_target_occupied` |

3. only a bind verdict commits the request's vault (below), then writes the descriptor into the
   stage and publishes it durably (the steps of the `publication` label above).

The engine never replaces or merges into a bound unit: a different result is refused and the
unit, its bytes and its inode numbers are unchanged. A zero-table publish binds a unit holding
only its descriptor, so an empty unit is never silently replaced either. Every exit but a bind
aborts the stage.

Every exit is a `CommitReceipt`, except two. Each raises after the stage is aborted, with nothing
bound: a `VaultError` (below), or a file-access error from the vault's `OutputDir` before anything
is linked:

| Exit | `outcome` | `reason_code` | `visible` | `durable` |
|---|---|---|---|---|
| bound | `published` | - | yes | yes |
| the same result already bound, chain fsynced | `already_committed` | - | yes | yes |
| the same result already bound, an fsync of its chain failed | `commit_uncertain` | `publication_commit_uncertain` | yes | no |
| bound, an fsync of the chain after the rename failed | `commit_uncertain` | `publication_commit_uncertain` | yes | no |
| same `operation_id`, different result | `operation_conflict` | `publication_operation_conflict` | no | no |
| a different result, or anything else at the leaf | `refused` | `publication_target_occupied` | no | no |
| the same result bound, its vault not this request's (presence, digest or rows; below) | `refused` | `publication_vault_mismatch` | no | no |
| a bind verdict, and the vault at the request's vault leaf holds other rows | `refused` | `publication_vault_conflict` | no | no |
| `flock` unsupported or the lock file cannot be opened | `refused` | `publication_lock_unavailable` | no | no |
| the lock held past `lock_timeout_s` | `refused` | `publication_lock_timeout` | no | no |
| a staged table unreadable or not Parquet, the descriptor write, the stage fsync walk or the rename failed | `failed` | `publication_failed` | no | no |

`os_error` carries the errno name where an operating-system call failed. `result_id`,
`descriptor_digest` and `artifacts` describe the bound unit for `published`, `already_committed`
and `commit_uncertain`, and this attempt's measured result otherwise. `vault_digest` is the
bound vault's SHA-256 when the unit has one.

### Vault before output

A `PublicationRequest` may carry `vault=VaultBinding(writer, out)`: the `VaultWriter` and the
vault's own `OutputDir`. `publish_unit` then orders the vault before the output (rule V; the
write-ahead order of PostgreSQL's WAL), all under the destination lock and after a bind verdict:

1. `writer.publish(out)` writes the vault durably and returns a `VaultCommit` (above).
2. When a vault is already at the leaf (`vault_exists`, for example one a killed attempt linked),
   `adopt_vault` fsyncs it and its chain and adopts it in place when it holds this writer's rows;
   other rows are refused with `publication_vault_conflict`, and the vault is untouched.
3. Any other vault failure, `vault_commit_failed` included, is raised as the vault module raises
   it (`VaultError`, fixed text) after the stage is aborted: nothing is bound, and a vault that
   was linked is kept, so the retry adopts it at step 2.
4. Only then is the descriptor written, with `vault` = the commit's `{sha256, size,
   entry_count}`, and the unit bound.

The bind needs the `VaultCommit`, which only the vault module issues after the vault's chain was
fsynced, so the order is by construction: a crash at any step leaves either no bound unit or a
bound unit whose descriptor names a durable vault. A bound unit whose vault is gone can come
only from an out-of-band delete, and a republish reports it.

A republish (the same `result_id` already bound) checks the vault before reporting
`already_committed`, and writes nothing: the request and the descriptor must both have a vault
or both have none; the vault leaf is read through `adopt_file` (fsynced with its chain first), and
its size and SHA-256 must be the descriptor's and its rows this writer's (equal output can carry
a different reverse map). Absent, larger, another digest, other rows or another key's data:
`publication_vault_mismatch`, as is a leaf that is not an adoptable file (`ELOOP`, `EINVAL`,
`ENOTDIR`, `EISDIR`). An fsync failure: `commit_uncertain`. One reader,
`publication._vault_order.read_vault_leaf`, classifies the leaf for both this check and adoption. `writer.publish` is never
called on a republish, so a retry makes no second vault.

Engine sinks still refuse a request with a vault (rule B0): a vault job publishes resident output
through `publish_tables(..., request)` with `request.vault` set.

A caller that wants an exception passes the receipt to `raise_for_outcome`, which returns it for
`published` and `already_committed` and otherwise raises `PublicationRefused` (`refused`,
`operation_conflict`), `PublicationFailed` (`failed`) or `CommitUncertain`. Each maps to its
registered reason through `reason_from_exception`. Receipts, error text and reason records carry
codes, errno names, digests and counts only: never a path, a file or table name, or
operating-system message text. Table names live only in the descriptor, which is data.

The reason codes are in the `decoy` namespace of the reason registry (`docs/reasons.md`).

## The reference sink's state table

`ParquetTransactionalSink` (`execution/_transactional_sink.py`) is two parts:
`StagedParquetWriter`, its write half, which only stages each table as `<table>.parquet` in an
output stage (it never publishes, locks or writes a descriptor), and the sink itself, which owns
the stage and moves every call through one state table (`publication/_sink_state.py`). The
table is literal data: one cell per state and call, one per in-flight state and exit. A
transition is taken under one lock; the write, rename or check it admits runs outside the lock,
so a call that arrives while another is in flight answers at once.

| State | `write` | `commit` | `reconcile` | `abort` |
|---|---|---|---|---|
| open | writing | committing | nothing, returns `None` | aborted, stage removed |
| writing | busy, `publication_write_in_progress` | busy | busy | pending |
| committing | busy, `publication_commit_in_progress` | busy | busy | pending |
| recovering | busy, `publication_recovery_in_progress` | busy | busy | pending |
| sealed | refused, `publication_attempt_sealed` | returns the sealed result | returns the sealed result | nothing |
| uncertain | refused, `publication_commit_uncertain` | refused, `publication_commit_uncertain` | recovering | nothing |
| refused, failed | refused with the code the attempt ended with | refused | refused | aborted, stage removed |
| aborted | refused, `publication_attempt_aborted` | refused | refused | nothing |

| In flight | Ends | State after |
|---|---|---|
| writing | normally | open |
| writing | with an exception | failed (`publication_failed`) |
| committing | published or already committed | sealed |
| committing | operation conflict or refused | refused (the refusal's code) |
| committing | commit uncertain | uncertain |
| committing | any other error before the rename | failed (`publication_failed`) |
| recovering | the destination holds this result and its chain is fsynced | sealed |
| recovering | the destination holds this result, an fsync failed | uncertain |
| recovering | absent, or a different result | refused, `publication_commit_not_visible` |

A pending abort is applied when the in-flight call ends, unless it ends sealed or uncertain:
then the result is bound and the abort does nothing. Busy and refused calls raise
`PublicationRefused` with the registered code and a value-free receipt; a refusal changes
nothing. `abort()` never raises. A table name that is not one path component is refused with
`ValueError` before the state moves.

What the sink does: every call goes through the table above. Its commit is `publish_unit`
(next section), so it ends sealed (`published`, `already_committed`), refused, failed or
uncertain, and a second `commit()` on a sealed sink returns the same receipt without any I/O.
After a failed write or commit, or a refusal, every call but `abort()` is refused, and after
an abort every call is.

## The reference sink on `publish_unit`

`ParquetTransactionalSink(target, request=PublicationRequest(...))` stages each table as
`<table>.parquet` in a `publication` stage beside the target and, on `commit()`, hands the stage
and its own full staged set, `staged_components()`, to `publish_unit`; no caller picks a subset, so
the bound descriptor describes every file the sink staged. A streamed route's publish session
(`OutputPublish` in `execution/_chunked_output_sink.py`) reports the same set through its own
`staged_components()`. `staged_tables()` is the post-scan gate's read-back (table to opener)
while the stage is open, and is empty after publish or discard. Without a `request` the sink is its own
attempt: a fresh random `operation_id`, still judged by its measured result. A request carrying
a vault is refused with `ValueError` when the sink is built: an engine sink never binds a vault
(vault jobs publish through `publish_tables`).

`commit()` returns the `CommitReceipt` for `published` and `already_committed` and raises the
typed error for every other outcome (`raise_for_outcome`); the receipt is also on
`sink.receipt`. With no `write()` the unit holds only its descriptor.

| Commit ends | `commit()` | State after |
|---|---|---|
| bound | returns the receipt (`published`) | sealed |
| the same result already bound, chain fsynced | returns the receipt (`already_committed`) | sealed |
| bound, or found bound, and a chain fsync failed | raises `CommitUncertain` | uncertain |
| the same `operation_id` bound with another result | raises `PublicationRefused` (`publication_operation_conflict`) | refused |
| another result bound, or anything else at the target, or the lock refused | raises `PublicationRefused` (its code) | refused |
| a staged table unreadable, the descriptor write, the stage fsync walk or the rename failed | raises `PublicationFailed` (`publication_failed`) | failed |

On every outcome but a bind the stage is already removed when `commit()` returns or raises.

**Restart.** A job rerun after a crash builds a fresh sink with the same `operation_id`,
writes its tables again and calls `commit()`. The judge compares measured results: the same
result is `already_committed` once the bound unit and its chain to the anchor are fsynced; a
different result under the same `operation_id` is `operation_conflict` and the bound unit is
untouched. A matching `operation_id` alone never seals anything.

**`reconcile()`.** On a sink that has not committed it does nothing and returns `None`. On an
uncertain sink it reads the bound descriptor: this sink's own measured `result_id` there, with
the unit tree and every directory up to the anchor fsynced, seals the sink and returns a
receipt with `outcome` `already_committed` and `durable` true; an fsync failure, or a read
that cannot tell, leaves it uncertain (`CommitUncertain` again); an absent unit or a different
result refuses it (`publication_commit_not_visible`). On a sealed sink it returns the sealed
receipt. Routes do not call it; it is for a caller holding an uncertain sink.

**Evidence.** The sink's F29 publication evidence follows its state: sealed is `published`,
uncertain `unknown` (bound, not confirmed durable), refused, failed and aborted
`not_published`. A bound unit needs no cleanup; after a refusal or failure the cleanup state
is what the sink observed of its removed stage (`confirmed` on the ambient policy, `attempted`
on the strict ones).

**Routes.** Every engine route that publishes through the sink returns its receipt:
`run_sequential` and `run_fk_out_of_core` on `ExecutionResult.publication_receipt`,
`run_pipeline`'s full-frame streamed and mixed routes on the same field, and streamed
generation on `GenerationResult.publication_receipt`. On `run_pipeline`'s sequential and
out-of-core routes the pipeline rebuilds the route's result and the field is `None`; the
receipt is on the sink the caller passed (`sink.receipt`). A route whose commit raises fails
the run with that error, and nothing of this attempt is bound.

**On disk.** Every unit the reference sink publishes holds `_decoy_publication.json` and the reserved
stage marker `.decoy-publication-stage` beside its Parquet files, and the target's parent holds
the empty lock file `.<leaf>.decoy-lock` (never removed). A consumer that lists every file of
an output directory sees all of these. Unit
files are `0600` and unit directories `0700`.

## The isolated route on `publish_unit`

`run_pipeline_isolated(..., output_dir=..., request=PublicationRequest(...))` publishes through
`publish_unit` in both modes; the receipt is `IsolatedRunResult.publication_receipt`. Without a
`request` the run is its own attempt.

- **Isolated (`isolate=True`).** The parent opens a `publication` stage beside `output_dir` before
  it spawns the child and hands it the path. The child stages plain Parquet files there,
  `<table>.parquet`, owner-only from creation, and nothing else: no descriptor, no lock file, no
  rename, no nested unit. Its row errors travel in its result envelope. When the child reports
  `completed`, the parent decides what is staged: the envelope's table names must each be one path
  component (no separator, no `..`, no repeat), and the stage must hold exactly those files, each a
  regular file, besides the reserved `.decoy-publication-stage` marker the parent wrote. A
  child-written `_decoy_publication.json`, an extra file, a directory, a link or a missing table is
  refused (`failed`, `publication_failed`) and nothing is bound. The parent sets the stage to `0700`
  and each admitted file to `0600` through the entry's own descriptor (no link followed) before
  reading it; a file its owner cannot read is refused, not repaired. `publish_unit` then measures
  every size, SHA-256 and row count and writes the descriptor. The payload's source copies are
  owner-only from creation, so the route works under a umask that strips owner bits (`0o477`).
- **In-process fallback (`isolate=False`).** The tables are staged as `<table>.parquet` in a
  `publication` stage beside `output_dir` and bound by `publish_unit`, as `publish_tables` does.

| Publication ends | `outcome` | `committed_output_dir` | `reason` |
|---|---|---|---|
| `published` or `already_committed` | `completed` | `output_dir` | none |
| refused (another result, anything else at the target, the lock), `operation_conflict` | `crashed` | none | the receipt's code |
| the stage refused, a staging write, the descriptor write or the rename failed | `crashed` | none | `publication_failed` |
| bound, but a chain fsync failed (`commit_uncertain`) | `crashed` | none | `publication_commit_uncertain`, publication state `unknown` |
| a memory error from just before `publish_unit` or `publish_resident` through final cleanup, in either mode | `crashed` | none | `process_out_of_memory`, publication state `unknown`, no receipt. The target may exist: repeat the call with the same `operation_id` and destination, and a bound unit returns `already_committed` |
| a memory error before that point, once the child's output is being read (or the run has returned in process) | `crashed` | none | `process_out_of_memory`, publication state `not_published` |

`error` is then `publication <outcome>: <code>`, with ` (errno=<name>)` when an operating-system
call failed: never a path, table name or operating-system message text. On every outcome but a bind
the stage is gone when the call returns, and a killed child leaves nothing at `output_dir`. Without
an `output_dir` the child stages into scratch, the parent reads the tables back the same way, and
nothing is published.

## Named limits

- **DL1, `delivery_links_unsupported`.** A delivery claims each member with a hard link and
  tightens it to `0600` on its own descriptor. A target that cannot hard-link (errno `EPERM`,
  `EOPNOTSUPP`, `ENOTSUP`, `ENOSYS` or `EXDEV`), or that ignores `chmod`, fails at `open` with
  `publication_failed`, before any writer runs. The probe makes a file, sets `0644` and reads
  `0644` back, claims it, and must read `0600` back. A late write through a descriptor the writer
  kept open after `complete()`, and NFS silly-rename names, are not caught (V2-LOG).

- **L1u, a crash during parent creation under a narrowing umask.** If the process is killed
  between creating a parent and repairing its owner bits, under a umask that strips one, the
  parent is left under its real name with a mode the engine cannot open. A retry refuses it with
  the errno only and binds nothing; the operator restores the owner bits (`chmod u+rwx`) and the
  next retry publishes. Under umask `022` a new parent is born `0755` and there is no window.
- **macOS, owner-unreadable new parents.** Linux observes the born mode of a directory that the
  umask left unreadable through an `O_PATH` descriptor. macOS has no such descriptor, so there
  the repair sets such a directory to `0700` (owner only) and drops any group and other bits
  the umask had left. Only a umask that strips owner read reaches this.
- **L1, the filesystem and the anchor.** Durability holds where the filesystem honours
  `fsync(2)` and `flock(2)`, and the anchor itself (the strict capability root, the ambient mount
  root) is durable by deployment, as is a directory another uid owns and left unsynced. No macOS
  CI row runs these paths yet.
- **L2, stages left by a killed attempt.** A SIGKILL leaves the attempt's
  `._decoy_publication_pending_<token>` stage beside the destination. It is never read as output
  and never bound, and each attempt uses a fresh token, so it blocks nothing. A caller can find it
  with `fileaccess.reclaim_stages` (F26, below the file-access policy's "Reclaiming dead stages");
  `publish_unit` itself never reclaims.
- **The destination lock.** The lock name adds 12 bytes to the leaf (`.` before it,
  `.decoy-lock` after it), so a publication destination leaf longer than 243 bytes
  (`MAX_PUBLICATION_LEAF_BYTES` in `fileaccess/_component.py`, 255 less those 12) is refused up
  front with a value-free denial rather than failing at the lock with `ENAMETOOLONG`. The lock is
  an advisory `flock(2)`: it binds only writers that take it. On NFS it does not exclude two
  holders in one process. A forked child keeps the lock its parent took.
- **Errors.** A failure while creating or opening a directory on an output chain carries no path
  and no operating-system message text: the strict policies refuse with their usual denial, and
  the ambient policy raises an `OSError` with the errno only.
