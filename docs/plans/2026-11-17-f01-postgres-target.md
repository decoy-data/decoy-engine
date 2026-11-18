Status: plan (revision 6, 2026-11-18)

# F01: PostgreSQL application-ready write target and the type-mapping report (roadmap row 86)

Roadmap row 86: PostgreSQL application-ready write target (staging, constraint, index and
sequence restore, atomic publish) and the type-mapping report. Owner 2026-11-06: in CLI V1. The
row comes after the Phase 2 rows and F22 (row 59). In practice it builds on three plans: F22
publication (receipts, `result_id`, outcome tokens, merged), DELIV (row 61: the CLI delivery sink
and its `SinkStage` protocol) and CLI-DB-SRC (row 64b, engine branch `origin/plan/cli-db-src` at `6adca7e7b` (was `59343ebd` before the rewrite): the shared
`connectors/_postgres_session.py`, the Postgres secret reference, registry-derived exit classes,
the `pg-gate` CI lane and `decoy setup --postgres`).

Rules consulted: dev-rules `README.md` (routing), `00-universal.md`, `risk-and-exceptions.md` (R1, R2), `development-loop.md` (PLAN: proportion, guarantee, size, design notes, choke point, placement, established solutions; REMEDIATE), `destructive-operations.md` (truncate and overwrite of a database target), `data-and-migrations.md`, `security.md`, `config-secrets-and-supply-chain.md` (secret sourcing, redaction, no new dependency), `cross-cutting-concerns.md` (choke points), `architecture.md` (layout, fan-out, layers), `api-and-compatibility.md` (additive union member, frozen surfaces), `testing.md` (test depth T0 to T4, escalation triggers), `observability-and-resilience.md` (timeouts, reconcile), `reuse-first.md`, `workspace-and-vcs.md` (commit messages), `catalogs/recurring-defects.md` (classes 1 to 11); engine and CLI `CODEMAP.md` "Where Things Go"; CLI `docs/ROADMAP.md` rows 59, 61, 62, 64b, 85 and 86; engine plans `2026-10-29-f22-atomic-idempotent-publication.md` (database adapter contract, its line 124), `2026-10-30-f22-publication-replan.md` (rev 11), `plan/deliv:2026-11-12-deliv.md` (rev 3.5) and `plan/cli-db-src:2026-11-17-cli-db-src.md` (engine branch `origin/plan/cli-db-src`, head `6adca7e7b`); vault notes `10_Projects/decoy/v2/duckdb/12-database-writeback.md` (earlier V2 proposal, superseded here) and the MASTER F01 section. Revision 4 also read: the E0 record `docs/records/2026-11-18-f01-e0-spike.md` and test file on `feat/f01-e0` (PR #667, head `d9522ce03`), `pg-gate` run 44238850218, and `origin/plan/capped-worker-fixes:docs/plans/2026-11-18-capped-worker-fixes.md` section 2 (S2, head `bc836eb6d`); `_postgres_session.py` re-read from `origin/main` `2c869dce6`. Code read from `origin/main` on 2026-11-17 (engine `902968682`, tag `v0.27.0`; CLI `5b49510`, pin `decoy-engine==0.27.0`).

Anchors: a path with no prefix is in decoy-engine; a path with the prefix `C:` is in the CLI
repository (decoy).

Re-anchor (2026-11-18, after the history rewrite; old SHAs map through the rewrite's
`sha-map.tsv`): engine `origin/main` `84cc7d798`, CLI `origin/main` `9023c606`. Codex round 3 gave
GO on `6bfc358a4`. Since then 64b E1 MERGED (engine #624, `9180a7985`): `_postgres_session.py`
and `postgres_catalog.py` exist, and the citations below now point at the merged names
(`quote_ident` and `sql_literal`, not `_q` and `_lit`; `raise_for_interrupt` for interrupt
mapping; `POSTGRES_SOURCE_USAGE_CODES` derived
from the registry). 64b E1 added no session sentry, so AT-E4's sentry is new. 64b E2
(`POSTGRES_DSN_V1`), E3, C1 and C2 are not merged; F01 E1 still waits on 64b E2. F22 b2 (#622)
moved `publish_unit` and `publish_tables`. No design changes.

Risk: R2 overall (data handling, a destructive write to a database, credentials, value leaks).
The destructive write is the product doing what the user configured at run time, not a
development-time side effect, so it is not an R3 action for this work. The
`destructive-operations.md` controls become product behaviour: exact target resolution and a
read-only preview on every run (4.3), an explicit per-table authorization word (`mode:
replace`), bounded execution (timeouts, one transaction) and reconcile (4.4). The engine half
ships in engine **0.29.0**, the release after the 0.28.0 that carries the CLI-DB-SRC engine
half. If the daily release train cuts 0.29.0 before slice E3c merges, the engine half ships in
the first engine release cut after E3c merges, and the CLI repin in C1 names that version.

## Revision 2 (Dennis round 1 on `b0dd9085`: GO-WITH-FIXES, 2 BLOCKER, 9 HIGH, 5 MED, 4 LOW)

The approach (one in-place transaction) stands. Every finding is applied in place.

| Finding | Ruling applied | Where |
|---|---|---|
| B1 `setval` is not transactional | Sequences and identities reset with `ALTER SEQUENCE ... RESTART WITH` and `ALTER TABLE ... ALTER COLUMN ... RESTART WITH` (transactional since PostgreSQL 10), value computed in a server-side `DO` block; each sequence's own `last_value` and `is_called` join the AT-E9 digest; fault cells at `write_marker` and `commit`; mutation "back to `setval`" | 4.4 step 10, AT-E9, Q7 |
| B2 reader guarantee too wide | Guarantee 3 narrowed to statement-level READ COMMITTED readers; the TRUNCATE MVCC caveat goes in the guide; AT-E10 is one statement returning all counts plus a REPEATABLE READ recording cell | 1.1 item 3, AT-E10, Q1 |
| H1 reconcile by bookkeeping row is unsound | Reconcile by `pg_current_xact_id()` and `pg_backend_pid()` captured at `begin`, then `pg_xact_status(xid)` on a new connection with a connect timeout; minimum server PostgreSQL 13 | 4.4 reconcile, AT-E13, Q17 |
| H2 pandas-route Parquet types | Wider int to narrower int, `timestamp[ns]` to `timestamp`, `float64` to integer are `normalized` with value-free range, no-sub-microsecond and integral guards; pandas-route cells in AT-C1 | 4.5, AT-E3, AT-E6, AT-C1 |
| H3 two-step classification misses DuckDB | Classify on Arrow, DuckDB attached type and PostgreSQL type; numeric without typmod and precision over 38 are `unsupported` in V1 (V2-LOG: varchar transport); one round-trip cell per `exact` row | 4.5, AT-E3, AT-E16 |
| H4 check-then-lock | Lock first, then compare structure and capture definitions under `ACCESS EXCLUSIVE` | 4.4 steps 4 and 5 |
| H5 definitions captured outside the lock | Capture inside the locked publish transaction under `search_path = pg_catalog`; inspection uses the same capture function and search path; pre-mortem fixed | 4.3, 4.4 step 5, section 15 |
| H6 (design ruling) | Drop only foreign keys; keep primary key, unique, exclusion constraints and every index during the load (pg_restore data-only style). Index dropping is a V2-LOG speed-up. Index property capture removed | 4.4 steps 6 and 9, AT-E8, Q18 |
| H7 same-database check after source read | A read-only, catalog-only fingerprint probe of the source runs inside `open_postgres_target`, before any source row is read | 4.7, AT-E7 |
| H8 session module and exit set duplicated | 64b E1 owns `connectors/_postgres_session.py`; F01 E1 only adds `open_write_session`. `POSTGRES_TARGET_USAGE_CODES` and the CLI arm are dropped: each new reason spec carries its outcome and the exit class derives from the registry, as 64b does | 4.7, 4.8, 6, AT-C6, slices |
| H9 spike must come first | Spike is its own slice E0 with Dennis's cells; step 8 count from `INSERT` affected rows; no DuckDB-side read of target tables through the pool; Q15 is an owner decision if E0 fails | E0, AT-E0, Q15 |
| M1 timeouts | Per-step `SET LOCAL statement_timeout` = min(3600 s, remaining deadline); `idle_in_transaction_session_timeout`; AT-E11 bounds lock-release time | 4.4, AT-E11 |
| M2 trigger state | Restore by `tgenabled` (`O`, `D`, `R`, `A`); AT-E8 cells for `R`, `A`, `D` | 4.4 step 9, AT-E8 |
| M3 unusual sequences | Non-owned `nextval` defaults, shared sequences, negative increment and out-of-range restart detected through `pg_attrdef` and `pg_depend`; coded refusal; cells | 4.3, 4.4 step 10, AT-E5, AT-E9 |
| M4 `--resume` | Refused with a Postgres target in V1, matching 64b; test | 4.8, AT-C10, Q19 |
| M5 bookkeeping creation race and privileges | One global advisory key around `decoy_meta` creation; privilege check covers `SELECT`, `INSERT`, `UPDATE` on an existing publications table. Revision 5 removed the lookup-table privilege check | 4.3, 4.4 step 3, AT-E5 |
| LOW | Two-int advisory key from SHA-256 in Python (no `hashtext`); `NOT VALID` foreign keys re-created as they were; partial-index and check text kept out of errors and logs with a marker literal in AT-E14; `pg_debug_show_queries` forced off; `duckdb_databases().path` holds the DSN and is never read; AT-C7 adds `report fidelity --config` and every other non-run target reader | 4.4, AT-E8, AT-E14, AT-C7 |

Nothing was left unapplied.

## Revision 3 (Codex on `89a3d564`: NO-GO on two V1 findings, no design findings)

| Finding | Fix | Where |
|---|---|---|
| 1 `pg_sequences` has no `is_called` | AT-E9 reads `last_value` and `is_called` from each sequence relation (`SELECT last_value, is_called FROM <schema>.<sequence>`, identifiers quoted through the identifier rule). The transactional `RESTART WITH` and the `setval` mutation stay | Revision 2 table B1 row, AT-E9 |
| 2 bookkeeping privilege check wrong when only the table is absent | Three cases: schema absent needs database `CREATE` (the role then owns the schema); schema present and table absent needs `CREATE` on schema `decoy_meta`; table present needs `SELECT`, `INSERT`, `UPDATE`. Each refused with `target_privilege_missing`; AT-E5 has a refusing and a passing cell per case | 4.3, 4.4 step 3, section 7, AT-E5, Q11 |
| V2-LOG sibling citation | `plan/cli-db-src` cited as the engine branch `origin/plan/cli-db-src` at `59343ebd` | header, Rules consulted |
| Codex on `1a4e5076` (orchestrator, round cap): schema `USAGE` missing | Both schema-present cases also need `USAGE` on `decoy_meta`; AT-E5 adds two refusing cells (schema `CREATE` without `USAGE`; table rights without schema `USAGE`); the pre-mortem line names every case | 3, 11 AT-E5, pre-mortem |

## Revision 6 (Dennis round 2 on revision 5)

| Finding | Fix | Where |
|---|---|---|
| V1: kept lookup FKs can queue one deferred trigger per row, defer failure to `COMMIT`, and take conflicting row locks | Step 1 makes every constraint immediate. Step 8 loads at most 1,000,000 rows per statement and sums affected counts. A load failure after `lock_timeout_s` maps to `target_busy`. Tests cover a deferred lookup-FK violation and a multi-million-row load with bounded backend memory | 4.4 steps 1 and 8; 4.4.3; 5.3; AT-E9 |
| Wait windows drift or overrun their budgets | Each wait is `min(budget, time left in the current window)`. Every window starts at the trigger time. The single reopen follows the same rule | 4.4.2; AT-E17 cell 5 |
| SIGINT recording starts after the first trigger | On the main thread, `run_supervised` installs the record-only handler at entry, keeps it through reconcile, treats a recorded press as the trigger, and restores it in `finally` | 4.4.2; AT-E18 cell 7 |
| An overrun control call leaves a session eligible for reuse | The first overrun marks the control session dead. The next required call uses the one allowed reopen | 4.4.2; AT-E17 cell 5 |
| The existing deadline arm calls `conn.interrupt()` | `Deadline` gains the named `arm_expiry_only` entry point on its existing timer core. The publish uses only that entry point, which sets `expired` and never calls `conn.interrupt()` | 3; 4.4.1; 4.4.2; AT-E17 |
| AT-E18 cell 4 claims server cleanup and process exit that its proxy cannot prove | The cell proves only that the supervisor stops waiting. The CLI fallback is `os._exit` after flushing and closing the run `ExitStack`, and only on the CLI path | 4.4.2; 7; AT-E18 cell 4; 17 |
| Sequence ownership is missing from inspection | Inspection checks ownership of every sequence that the publish will restart | 4.3; AT-E5 |
| The write-session open lacks a hard open budget | `write_open_budget_s` bounds the worker open and ends `target_unreachable` before `begin` | 1.1 item 9; 4.3; 4.4.1; 4.4.2; AT-E18 |

Slice sizes remain E3a about 360 source lines, E3b about 580, and E3c about 250. None grows.

## Revision 5 (Dennis review of revision 4 at `1cd21fb44`: GO-WITH-FIXES, 4 HIGH, 5 MEDIUM, 3 LOW)

The core design stands (per-statement `SET LOCAL` bounds, same-role cancel without superuser,
the PostgreSQL 13 `xid8` floor, the `stop` and `committing` lock, no silent reconnect after a
terminate). Each finding and where it is fixed:

| # | Finding | Fix | Where |
|---|---|---|---|
| 1 | HIGH: dropping a target-to-lookup FK takes `ACCESS EXCLUSIVE` on the lookup table | Only FKs with both ends in target tables are dropped; FKs to lookup tables stay and the server checks each row (`target_load_failed`); no lookup lock in `lock_tables` | 4.4 steps 4, 6, 8; 5.3; 7; AT-E9 lookup cells and mutation; 15 |
| 2 | HIGH: `SHARE ROW EXCLUSIVE` on a lookup needs more than `REFERENCES` | The lookup table lock is gone (finding 1); inspection asks no right on lookup tables. Revision 6 strengthens the cell to a role with no application privilege on the lookup table | 4.3; 5.3; 7; AT-E5; AT-E9 |
| 3 | HIGH: item 9 does not hold while the supervisor blocks in DuckDB calls, on a dead network, per-address connect or DNS | Every control call on its own daemon thread under a hard budget (`control_call_s`, `control_open_budget_s`, `reconcile_budget_s`); item 9 written from those budgets; keepalives and `tcp_user_timeout` through S2's one helper; the worker owns the write connection and the supervisor never closes it; a TCP-proxy subprocess cell | 1.1 item 9; 4.3; 4.4 intro; 4.4.1; 4.4.2; AT-E18 cell 4; 12 E1 |
| 4 | HIGH: a second Ctrl-C can escape with exit 130 while `COMMIT` may have landed | `stop` set first inside `try`/`finally`; further SIGINT deferred on the main thread for the bounded sequence; undecided while committing is `target_commit_unknown` (exit 3), never 130 | 4.4.2; 4.4.3 row 1; 7; AT-E17 cells 1 and 8; AT-E18 cell 3 |
| 5 | MEDIUM: the write ATTACH defaults to REPEATABLE READ, so step 1's snapshot predates the locks | `ISOLATION_LEVEL 'READ COMMITTED'` on the write ATTACH; triggers disabled and restored by name from the capture, not `DISABLE TRIGGER USER`; AT-E12 trigger-added-while-waiting cell; AT-E0 cell e3.5 records the option | 4.4 intro, steps 5, 6, 9; AT-E0; AT-E4; AT-E12 |
| 6 | MEDIUM: stop check and `SET LOCAL` only per step | Before every statement | 4.4 intro; AT-E9 second-statement cap cell |
| 7 | MEDIUM: no single step-to-code mapping | One failure-code registry over all thirteen steps, with privilege re-check marks; AT-E9 asserts the code per injected step and revoked-right cells | 4.4.3; 10; AT-E9 |
| 8 | MEDIUM: duckdb-postgres connect errors carry the DSN | Every worker and control-call thread body catches `BaseException` and keeps the type name; AT-E14 excepthook spy, abandoned-worker and failed-reopen marker cases | 4.4 failure handling; 4.4.2; 7; 10; AT-E14 |
| 9 | MEDIUM: control session use and transaction mode unstated | Only the supervisor uses it; autocommit; one statement per call | 4.4.2; AT-E17 cell 9 |
| 10 | LOW: AT-E17 cell 2 does not prove nothing was written | Spies on the write-session opener and the write SQL | AT-E17 cell 2 |
| 11 | LOW: AT-E17 cell 3 passes on the server bound alone; the lookup row-lock cell expectation is wrong | Cell 3 seam lifts the server bound; the lookup cell uses a non-key `UPDATE` and now expects success (finding 1) | AT-E17 cell 3; AT-E9 |
| 12 | LOW: one changelog fragment for E3; platform notes missing | E3 split into E3a, E3b, E3c, each with its own fragment; `docs/postgres-target.md` notes `pg-gate` Linux only, `tcp_user_timeout` Linux only, Windows scratch tolerance | 9; 12; C2 |

Slice sizes after the fixes: the old E3a (about 770 source lines) would pass 800 with the
per-call threads and the registry, so it is split: E3a control and supervision (about 360),
E3b write path (about 580), E3c pipeline and public surface (about 250). New AT-E18 holds the
publish-level supervision cells; AT-E17 tests the control module alone.

## Revision 4 (E0 spike, PR #667, `pg-gate` run 44238850218: cell e failed)

E0 disproved one assumption: DuckDB `conn.interrupt()` neither returns control nor cancels the
server statement on any postgres-extension path (`postgres_query`, `postgres_execute`, the same
in a transaction, a `TRUNCATE` waiting on a lock). Cell e2 passed: `pg_cancel_backend(<pid>)`
from a second session stops the statement and `ROLLBACK` works. Cell h: a libpq
`connect_timeout` bounds a blackhole connect; `interrupt()` does not. Cells a, b, c, d, f, g, i
and j passed, so the one-transaction design stands and Q15 (psycopg) is not triggered.

| Change | Where |
|---|---|
| The deadline no longer relies on `interrupt()`. Three layers bound every step: server-side `SET LOCAL statement_timeout` and `lock_timeout` per step (primary); a control session that sends a guarded `pg_cancel_backend`, then `pg_terminate_backend`, at the deadline or on Ctrl-C; and a supervisor that stops waiting for a worker that still does not return. `COMMIT` is never sent after a trigger | 1.1 item 9, 4.4.1, 4.4.2 |
| Connect bound: S2's `with_connect_timeout` and `connect_timeout_s` (`origin/plan/capped-worker-fixes`), one copy, on the write, control and reconcile sessions. `PGCONNECT_TIMEOUT` rejected (process-global, S2 2.3). F01's own `connect_timeout_s=15` field is dropped. E1 orders after S2 | 3, 4.3, 4.4.1, 12 |
| The write session leaves `pg_statement_timeout_millis` and `pg_idle_in_transaction_timeout_millis` unset: when set, the extension issues a plain session `SET statement_timeout` on scan connections (`postgres_scanner.cpp`), which would override the per-step `SET LOCAL` | 4.4.1, AT-E4 |
| Lock waits were moved into named steps. Revision 5 removed the planned lookup-table lock. Revision 6 recognizes lookup-row waits during `load`. The old step 10 is split into `check_sequences` and `sequences`. Thirteen steps | 4.4 steps 4, 8, 10, 11 |
| Reason-code mapping for every timeout and cancel, value-free (no error text read), and the state of the half-done transaction in each case | 4.4.3 |
| Failure rows for the control session (cannot connect, lost, pid reused, cancel races commit, cancel between statements) and the abandoned worker | 7 |
| AT-E0 cell e becomes a strict recording cell (interrupt does not cancel); new cell e3 proves the new mechanism; #667 needs both before it merges as the spike record. AT-E9 deadline cells rewritten; new AT-E17 for the control session and supervisor | 8.1 |
| New private module `connectors/_postgres_control.py` (control session, guarded cancel and terminate, supervisor), reusable by the read side. E3 split into E3a (write path) and E3b (pipeline and public surface) to stay under 800 lines | 9, 11, 12 |
| Owner question Q20: the 64b read side has the same `interrupt()` gap | 16 |

## 1. Guarantee and non-goals

### 1.1 What this change promises

1. A pipeline may declare Postgres targets, one per table:
   `targets.<table>: {type: postgres, connection_ref: <secret ref>, schema: <ident>, table:
   <ident>, mode: replace}`. The config holds no host, user, password or database name; the
   whole libpq connection string is behind `connection_ref` (an F13 `env:` or `file:` reference,
   the `postgres-dsn-v1` requirement from row 64b). `mode` is required and V1 accepts only
   `replace`. The target server must be PostgreSQL 13 or later.
2. **All or nothing.** A `decoy run` with Postgres targets either replaces the contents of every
   target table and commits, or leaves every target table, index, constraint, trigger, sequence
   and the bookkeeping row exactly as they were. This holds for a refusal, a constraint failure,
   a load failure, a deadline, a lost connection before `COMMIT`, Ctrl-C and SIGKILL of the
   process. All target writes, including sequence and identity resets, happen in **one**
   PostgreSQL transaction (pg_restore `--single-transaction`); no non-transactional function
   such as `setval` is used.
3. **Statement-level readers never see a mix.** A reader statement under READ COMMITTED (the
   PostgreSQL default) sees the complete old contents or the complete new contents of the target
   tables, never an empty or half-loaded table: the publisher holds `ACCESS EXCLUSIVE` locks on
   every target table from before the truncate to the commit, so the statement waits. Not
   promised: a REPEATABLE READ or SERIALIZABLE transaction whose snapshot was taken before the
   commit and that reads a target table after the commit sees it empty, because `TRUNCATE` is not
   MVCC-safe (PostgreSQL `TRUNCATE` docs). The guide states this; AT-E10 records it.
4. **Application-ready.** After a publish, the structure the application created is in place and
   working: every primary key, unique, exclusion, check and foreign key constraint (a `NOT
   VALID` foreign key stays `NOT VALID`), every index (never dropped), every user trigger in its
   prior `tgenabled` state, every identity column with its `ALWAYS` or `BY DEFAULT` kind, every
   generated column (recomputed by the server), and every sequence owned by a target column
   restarted so the next default value is above the loaded maximum. The first application
   insert that relies on a default key succeeds.
5. **Type-mapping report.** Before any write to the target, the engine maps each column of the
   staged masked Parquet through three steps (Arrow type, the DuckDB type of the attached
   target column, the PostgreSQL type) and classes the column `exact`, `normalized`, `lossy`,
   `unsupported` or `generated`. Any `lossy` or `unsupported` column, a missing column or an
   extra column refuses the run before the target is touched; every `normalized` column runs a
   value-free guard. The report is a versioned, value-free document (`decoy-pg-type-map/v1`)
   shown on the run card and in `--json`.
6. **Retry and race safety.** The publication is recorded in the same transaction in
   `decoy_meta.publications` (one row per target schema: `operation_id`, `result_id`, engine
   version). A retry of a committed operation with the same result returns `already_committed`
   and writes nothing; the same `operation_id` with a different result is
   `publication_operation_conflict`; a different writer that published between this run's
   inspection and its commit makes this run fail with `delivery_pointer_moved` and roll back
   (F22 database adapter contract, `2026-10-29` plan line 124). A lost `COMMIT`
   acknowledgement is reconciled by the server's own transaction status
   (`pg_xact_status`) on a new connection.
7. **Safe before writing.** The target is inspected read-only before any source row is read:
   the server version, the relations, the privileges, unsupported objects and sequences, no
   table outside the declared set references a target table, and the target database is not the
   database of any Postgres source (a catalog-only probe of the source, no source row read).
8. **Value-free.** The connection string, the password, the host and every data value never
   appear in an error, a log line, the run card, `--json`, the run folder, the type-mapping
   report, a receipt, telemetry or an exception chain (`__cause__` and `__context__` are `None`
   on every refusal). PostgreSQL error text (which can carry `Key (id)=(42)`) is never read.
   Constraint and index definition text (a partial-index predicate or a check can hold a
   literal) is executed but never logged or shown. Errors carry a registered code and a location
   (`targets.<table>.<field>`, `schema.table`, `schema.table.column` or
   `schema.table.constraint`).
9. **Bounded.** The supervisor (4.4.2) never makes a blocking call itself: every DuckDB call
   it needs runs on its own daemon thread under a hard wait budget, so its schedule depends only
   on its clock. `publish_target` returns or raises (a) within `control_open_budget_s` when the
   control session cannot be opened, or within `write_open_budget_s` when the write session
   cannot be opened, before anything is written; (b) within
   `deadline_s + 2 * cancel_grace_s + 2` seconds of its start, or `2 * cancel_grace_s + 2`
   seconds after the first Ctrl-C, when `COMMIT` has not been sent; (c) within a further
   `commit_grace_s + reconcile_budget_s` when a trigger finds `COMMIT` in flight. This holds
   whatever DuckDB, DNS or the network does (a dead network, a hung `getaddrinfo`, a multi-host
   DSN). No lock wait lasts longer than `lock_timeout_s`. A timeout or a cancel before `COMMIT`
   leaves the target as it was, and `COMMIT` is never sent after `stop` is set. A `COMMIT`
   already sent is never cancelled; reconcile reads its outcome, and an undecided commit is
   `target_commit_unknown` (exit 3), never exit 130.

### 1.2 Non-goals (findings here become follow-ups, not blockers)

- `create`, `append` and `upsert` modes (V2). V1 needs the target structure to exist: created by
  the application's migrations or by `pg_dump --schema-only | psql` (documented recipe).
- Creating, altering or migrating target structure. A target column type is never changed and
  no table is created except the bookkeeping table.
- Dropping and re-creating indexes or primary key, unique and exclusion constraints for load
  speed (V2-LOG, Q18).
- A staging-schema rename swap (readers that never wait), and the REPEATABLE READ caveat of
  item 3 (Q1).
- `numeric` without a typmod and `numeric` with precision over 38 (V2-LOG: varchar transport).
- Partitioned tables, inheritance, rules, `FORCE ROW LEVEL SECURITY`, foreign keys from tables
  outside the declared set, and unusual sequence wiring: refused before writing (Q9).
- Refreshing materialized views that read the target tables (documented: refresh after a run).
- More than one target schema or connection per pipeline, and Postgres targets mixed with file
  or cloud targets in one pipeline (Q3).
- `delivery.mode: best_effort` and `--resume` with Postgres targets (Q4, Q19).
- PostgreSQL 12 and earlier (Q17).
- A backup of the previous target contents, an interactive confirmation prompt and a separate
  preview command (Q10).
- An approval mechanism for lossy conversions (Q8).
- Other databases (MySQL, SQL Server, warehouses), the platform surface, and F02.
- Hostile in-process attackers or a hostile database server (V1 threat model: accidental leaks
  only).

## 2. Established solutions

Searches run 2026-11-17: the web (DuckDB, PostgreSQL and pgloader documentation), both
repositories, the vault (`qmd search "F01 postgres target"`, also in `decoy-engine-archive`: no
hit there; one V2 proposal in the wiki, `12-database-writeback.md`). Revision 6 rechecked the
official PostgreSQL 14.4.4, `SET CONSTRAINTS`, and explicit-locking documentation on 2026-11-18.

| Source | Pattern | Taken |
|---|---|---|
| PostgreSQL `pg_restore` (postgresql.org/docs/current/app-pgrestore.html): `--single-transaction`, `--data-only`, `--disable-triggers` | One `BEGIN`/`COMMIT` so "either all the commands complete successfully, or no changes are applied". A data-only restore loads into existing tables with their indexes and constraints in place; triggers are disabled during the load | One transaction for every target write. Indexes and primary key, unique and exclusion constraints stay in place during the load (data-only style, H6). Foreign keys between target tables are dropped and re-created so load order and cycles do not matter. User triggers are disabled during the load and restored before commit (Q6) |
| pgloader (pgloader.readthedocs.io/en/latest/ref/pgsql.html): `truncate`, `disable triggers`, `foreign keys`, `reset sequences` | Truncate before load; re-create foreign keys after; reset sequences to the current maximum column value after loading | Same steps inside our one transaction. pgloader's `setval` is replaced by the transactional `ALTER SEQUENCE ... RESTART WITH` (B1), so a rollback also undoes the reset |
| PostgreSQL `ALTER SEQUENCE` docs (changes are transactional since version 10; `RESTART WITH`) and `ALTER TABLE ... ALTER COLUMN ... RESTART WITH` for identities; `setval` docs ("never rolled back") | A sequence reset inside a transaction is undone by rollback only through `ALTER SEQUENCE` | Step 10 uses `RESTART WITH` in a server-side `DO` block (Q7) |
| PostgreSQL `TRUNCATE` docs: "not MVCC-safe"; takes `ACCESS EXCLUSIVE` | A rolled-back `TRUNCATE` leaves nothing behind; a session that dies before `COMMIT` is aborted by the server; an older snapshot sees the table empty after commit | Rollback is the recovery path; guarantee 3 is statement-level READ COMMITTED (B2) |
| PostgreSQL `pg_current_xact_id()`, `pg_xact_status(xid8)` (version 13+), `pg_terminate_backend` | The status of a transaction whose commit acknowledgement was lost is read from the server by its id: `committed`, `aborted`, `in progress` or null | Reconcile (H1); minimum server 13 (Q17) |
| DuckDB postgres extension (duckdb.org/docs/2.0/core_extensions/postgres/overview.html) | Read-write `ATTACH`; `INSERT` and `COPY` "directly modify the PostgreSQL database" over the binary wire; `BEGIN ... ROLLBACK` example; `postgres_execute(db, sql, use_transaction := true)`; `pg_clear_cache()`; `pg_debug_show_queries`. Not stated: whether every statement shares one PostgreSQL connection and transaction | Spike slice E0 proves each behaviour the design needs before any product code (H9, Q15). No new dependency; the extension is the one row 64b installs |
| F22 database adapter contract (engine `docs/plans/2026-10-29-f22-atomic-idempotent-publication.md:124`) | Publish all rows and a unique `(destination, operation_id)` record in one database transaction; on retry read that row and compare content; serialize conflicts by a lock plus isolation | `decoy_meta.publications` row written in the publish transaction, under a transaction advisory lock, read `FOR UPDATE`, compared by `result_id` (never by `operation_id` alone, F22 rule D) |
| git `update-ref <ref> <new> <old>` (DELIV 3, the `LATEST` compare-and-swap) | Write last with the expected old state | The publish refuses when the bookkeeping row differs from what the read-only inspection saw (`delivery_pointer_moved`) |
| pg_dump (search path set to `pg_catalog` since CVE-2018-1058) | Catalog definition text is captured and executed with an empty search path so every name is schema-qualified | Capture and re-create both run under `SET LOCAL search_path = pg_catalog` in the locked transaction (H5) |
| PostgreSQL docs, "Populating a Database" (14.4) | Run `ANALYZE` after a bulk load | `ANALYZE` of the target tables after commit; a failure is a warning (Q14) |
| PostgreSQL docs, "Populating a Database" 14.4.4 | Loading many rows with foreign keys can queue one trigger event per row and overflow memory; drop and restore FKs for a bulk load when possible | Target-to-target FKs are dropped. Lookup FKs must stay, so step 1 makes them immediate and step 8 limits each insert to 1,000,000 rows. AT-E9 measures backend memory on more than 3,000,000 rows |
| PostgreSQL `SET CONSTRAINTS` docs | Immediate constraints are checked at the end of each statement; deferred constraints wait until commit | Step 1 runs `SET CONSTRAINTS ALL IMMEDIATE`. Each bounded insert flushes its lookup-FK checks before the next batch, and a violation belongs to `load` |
| PostgreSQL explicit-locking docs, row-level modes | `FOR KEY SHARE` blocks delete, key-changing update and `SELECT FOR UPDATE`, but not plain reads or non-key updates | Section 5.3 states the exact lookup-row effects. A conflicting lock that reaches `lock_timeout_s` maps to `target_busy` |
| In-repo: 64b's `connectors/_postgres_session.py` (`open_connection` `:177`, `load_postgres_extension` `:211`, `attach_read_only` `:235`) and the constant catalog SQL in `connectors/postgres_catalog.py:34` | Offline extension load, DuckDB connection with auto-install off, constant catalog SQL, coded value-free errors | Reused: F01 adds `open_write_session` beside 64b's `open_read_session` |

Bounding a running statement (revision 4, searches run 2026-11-18: PostgreSQL, libpq, psycopg
and PgBouncer docs, the duckdb-postgres source, and the S2 plan):

| Source | Pattern | Taken |
|---|---|---|
| PostgreSQL runtime config, `statement_timeout` (postgresql.org/docs/current/runtime-config-client.html) | "Abort any statement that takes more than the specified amount of time", timed "from the time the command arrives at the server until it is completed by the server"; settable per transaction with `SET LOCAL`; not recommended in `postgresql.conf` | Primary bound: before each step `SET LOCAL statement_timeout` = min(step cap, remaining deadline). Server-side, so it holds whatever the client does; a `COPY FROM STDIN` that waits on a slow client counts too |
| Same page, `lock_timeout` | "Abort any statement that waits longer than the specified amount of time while attempting to acquire a lock", per lock attempt; pointless if not below `statement_timeout` | `SET LOCAL lock_timeout = lock_timeout_s` at `begin`; every lock wait is moved into a lock step so a lock timeout maps to one code |
| Same page, `idle_in_transaction_session_timeout`, `client_connection_check_interval` | The server ends a session idle inside a transaction, and checks for a dead client during long queries | Already in step 1 (M1); covers a client that stalls between statements |
| libpq `PQcancel` / `PQcancelBlocking` (postgresql.org/docs/current/libpq-cancel.html) | A cancel is a request sent over a separate connection; "successful dispatch is no guarantee that the request will have any effect"; if the server already finished the command "there will be no visible result at all" | The control session is the separate connection. A cancel is advisory: the supervisor re-sends it, checks a stop flag before each step, and escalates. A cancel that arrives after the command finished is a no-op, so the commit race is handled by never cancelling after `COMMIT` is sent |
| psycopg 3 `Connection.cancel()` and `cancel_safe(timeout=30.0)` (psycopg.org/psycopg3/docs/api/connections.html); psycopg's article "Cancelling PostgreSQL statements from Python" (2014) | Ctrl-C or a timer in another thread calls cancel on a second connection; the blocked call then returns with `QueryCanceled`; `cancel_safe` bounds the cancel itself with a timeout | Same shape: a supervisor thread (the main thread, which also receives `KeyboardInterrupt`) cancels while a worker thread is blocked; the cancel runs on a session with its own connect and statement bounds |
| PgBouncer `query_timeout`, `server_connect_timeout` (pgbouncer.org/config.html) | A pooler bounds a query by cancelling it from outside and bounds a server connect separately | Same two bounds; F01 has no pooler of its own |
| `pg_cancel_backend`, `pg_terminate_backend` (postgresql.org/docs/current/functions-admin.html) | SQL-level cancel and terminate by pid; allowed on backends of the same role without superuser | DuckDB does not expose the libpq cancel key, so the control session uses these, guarded by `pid` and `backend_xid` against pid reuse. E0 cell e2 proved the cancel |
| duckdb-postgres `src/postgres_scanner.cpp` (`pg_statement_timeout_millis` handling) | When the DuckDB setting is set, each scan connection runs a plain `SET statement_timeout` (session level) | The write session never sets it, so the extension cannot override the per-step `SET LOCAL` (AT-E0 e3, AT-E4) |
| S2 of `plan/capped-worker-fixes` (libpq `connect_timeout` appended by `with_connect_timeout`; `PGCONNECT_TIMEOUT` rejected as process-global) | Bound a connect in the DSN text, one helper | Reused as is for the write, control and reconcile sessions |

Rejected for the deadline: DuckDB `conn.interrupt()` (E0 cell e: no effect on extension
statements; it stays only for local DuckDB work, where it is harmless), `PGCONNECT_TIMEOUT`
(S2 2.3), and psycopg 3 for the publish (Q15 is not triggered; no new dependency is needed for
a cancel).

Rejected: a staging schema plus `ALTER SCHEMA ... RENAME` swap (the V2 proposal in the wiki and
dbt's table swap). It needs every index, constraint, sequence, trigger, grant and owner rebuilt
from catalog text in a new schema, and the rename leaves views, functions and cached plans that
reference the old tables by OID pointing at the old schema. The in-place transaction keeps every
OID, grant and dependent object. Its cost is that readers wait for the load (Q1).

Custom code left: the catalog reads (constant SQL), the type-map rules table, the value guards,
the ordered publish steps and reconcile. Everything else is reuse.

## 3. Reuse inventory

| Need | Existing mechanism (reused, not copied) | Anchor |
|---|---|---|
| DuckDB connection with offline extension load, identifier rule | `open_read_session`, `validate_identifier`, `quote_ident`, `sql_literal` in `connectors/_postgres_session.py` (64b E1, merged #624) | `src/decoy_engine/connectors/_postgres_session.py:253`, `:98`, `:106`, `:111` |
| Connect bound for every session | `with_connect_timeout`, `connect_timeout_s` in `_postgres_session.py` (capped-worker S2, not merged yet; F01 E1 waits for it) and S2's single ATTACH site | `origin/plan/capped-worker-fixes` plan 2.4, 2.6 |
| Deadline timer and interrupt mapping | `Deadline` gains `arm_expiry_only` beside its interrupting read-side arm, on the same timer core; `raise_for_interrupt` maps the result | `src/decoy_engine/connectors/_postgres_session.py:116`, `:141` |
| Coded value-free error | `PostgresSnapshotError` (the target error subclasses it, so the existing CLI arm and code owner hold) | `src/decoy_engine/connectors/_postgres_session.py:59` |
| Type classes of the source side | `_PLAIN_TYPES`, `_classify` (the type map reads the same lists) | `src/decoy_engine/connectors/postgres_snapshot.py:119`, `:210` |
| Secret reference and `postgres-dsn-v1` | `prepare_secret`, `POSTGRES_DSN_V1` (64b E2, not merged yet; a `SecretRequirement` beside the existing ones) | `src/decoy_engine/secret_providers/_preflight.py:259`, `_requirements.py:42` |
| Catalog reads of a source | `connectors/postgres_catalog.py` (64b E1, merged #624); F01 E3b adds the public `server_fingerprint` beside `relation_columns` | `src/decoy_engine/connectors/postgres_catalog.py:95` |
| Exit class of connector codes | Registry outcome per spec (`CONFIGURATION` or `EXECUTION`) and the set 64b derives from the registry at import (`POSTGRES_SOURCE_USAGE_CODES`) | `src/decoy_engine/connectors/postgres_snapshot.py:93`, `:104` |
| Result identity of the staged Parquet | `Artifact`, `compute_result_id` | `src/decoy_engine/publication/_descriptor.py:122`, `:224` |
| Receipt and outcome tokens | `CommitReceipt`, `Outcome`, `raise_for_outcome`, `PublicationRefused` | `src/decoy_engine/publication/_types.py:58`, `:128`, `:223` |
| Publication reason codes | `publication_operation_conflict`, `publication_commit_not_visible`, `publication_target_occupied`, `delivery_pointer_moved` | `src/decoy_engine/reasons/decoy/_core.py:213`, `:220`, `:227`; `src/decoy_engine/reasons/decoy/_delivery.py:37` |
| Delivery decision and target set | `plan_delivery`, `DELIVERABLE_TARGET_TYPES` | `src/decoy_engine/delivery/_plan.py:24`, `:106` |
| Destination identity and the two-tables-one-destination refusal | `_target_identity` (engine #592) | `src/decoy_engine/config/_targets.py:141` |
| Canonical JSON for the report document | `decoy_engine._canonical.canonical_json_bytes` | `src/decoy_engine/publication/_descriptor.py:5` |
| Row-holding scratch, removed on exit | `protected_scratch_dir`; CLI `library/_scratch.allocate` | `src/decoy_engine/fileaccess/_protected_dir.py:268`; `C:src/decoy/cli/library/_scratch.py:122` |
| CLI delivery sink and stage protocol | `DeliverySink`, `SinkStage` (`abort`, `deliver(decision, before_visible)`), `PublishedOutput`, `PreVisible` (DELIV C2a) | DELIV plan 4.6 |
| CLI exception-to-exit map | `exit_code_for` and 64b's registry-derived arm for `PostgresSnapshotError` | `C:src/decoy/cli/exit_codes.py:163` |
| `--resume` refusal for Postgres endpoints | 64b's flag refusal (Q13 of that plan), extended to targets | 64b plan 4.4 |
| Postgres CI lane, fixtures, zero-skip guard | `pg-gate` job, `pg_dsn`, `ext_dir`, `PgAdmin`, `DECOY_REQUIRE_PG`, `junit_ran.py` (64b E1, merged #624) | `tests/connectors/conftest.py:74`, `:87`, `:101`; `.github/workflows/ci.yml:388` |
| Extension install | `decoy setup --postgres` (64b C2) | 64b plan 4.4 |

No second copy of the connection setup, the identifier rule, the secret resolution, the result
identity, the outcome tokens, the exit classification or the scratch allocator.

## 4. Behaviour

### 4.1 Config

```yaml
sources:
  customers: {type: postgres, connection_ref: env:DECOY_PG_SRC, schema: public, table: customers}
  orders:    {type: postgres, connection_ref: env:DECOY_PG_SRC, schema: public, table: orders}
targets:
  customers: {type: postgres, connection_ref: env:DECOY_PG_DST, schema: app, table: customers, mode: replace}
  orders:    {type: postgres, connection_ref: env:DECOY_PG_DST, schema: app, table: orders, mode: replace}
```

`PostgresTarget` (new member of `TargetDescriptor`, `src/decoy_engine/config/_targets.py:135`):
`type: Literal["postgres"]`, `connection_ref: str` (required, `x-decoy-locator`),
`schema: str`, `table: str`, `mode: Literal["replace"]` (required, no default: the explicit word
is the authorization, Q10). `destination_field = "table"`. `extra="forbid"`, strict strings,
`hide_input_in_errors=True`. `_target_identity` gains the arm
`("postgres", connection_ref, schema, table)`, so two tables on one target relation hit the
existing refusal. Sources can be any type (file, cloud, Postgres or generated).

### 4.2 Compile-time check (`decoy validate`, compile layer)

New `plan/checks/_postgres_targets.py` raises the first of (config namespace codes, location
`targets.<t>.<field>`):

- `target_postgres.identifier_invalid` (`schema`, `table`): fails `validate_identifier`.
- `target_postgres.multiple_connections` (`connection_ref`): two Postgres targets with different
  reference text.
- `target_postgres.multiple_schemas` (`schema`): two Postgres targets in different schemas.
- `target_postgres.mixed_targets` (`type`): a Postgres target and a non-Postgres target in one
  pipeline.
- `target_postgres.best_effort_unsupported` (`delivery.mode`): `best_effort` with a Postgres
  target.
- `target_postgres.target_is_source` (`connection_ref`): the target reference text equals a
  Postgres source's reference text.
- the existing bad-reference and unknown-provider refusals for `connection_ref` (64b, F13).

No secret is read and no connection is opened at compile time (64b Q4 holds).

### 4.3 Engine: inspection (read-only)

`connectors/postgres_target.py`, public:

- `PostgresTargetConfig` (frozen, strict): `dsn: SecretStr`, `extension_directory`,
  `temp_directory`, `memory_limit`, `threads`, `statement_timeout_s=3600`, `deadline_s=21600`,
  `lock_timeout_s=30`, `idle_in_transaction_timeout_s=60`, `cancel_grace_s=10`,
  `commit_grace_s=30`, `control_call_s=5`. No connect field: every session's connect bound is
  S2's `connect_timeout_s(deadline_s)` (10 s at the default deadline). Derived, not fields:
  `control_open_budget_s = connect_timeout_s(deadline_s) + control_call_s`,
  `write_open_budget_s = connect_timeout_s(deadline_s) + control_call_s`, and
  `reconcile_budget_s = control_open_budget_s + 3 * control_call_s + lock_timeout_s`.
- `TargetRelation(schema_name, table)`, validated by `validate_identifier`.
- `read_target(config, relations) -> TargetCatalog`. One read-only session (64b
  `open_read_session`), constant catalog SQL in `connectors/postgres_target_catalog.py`, no data
  row read. It sets `pg_debug_show_queries = false` and never reads `duckdb_databases()` (its
  `path` column holds the DSN). The structure is read by `capture_structure(session,
  relations)`, the one capture function, under `SET LOCAL search_path = pg_catalog` in a
  read-only transaction; the publish calls the same function under its locks (4.4 step 5). It
  collects, per relation: columns (name, `format_type`, `attnotnull`, `attgenerated`,
  `attidentity`, enum labels), the DuckDB type DuckDB reports for each attached column, foreign
  keys (`pg_get_constraintdef`, `convalidated`, both ends), the names and definitions of other
  constraints and of indexes (for the digest only), user triggers and `tgenabled`, sequences
  (owned through `pg_depend`, and every `nextval` default through `pg_attrdef`, with increment,
  minimum, maximum and current-role ownership), privileges, the server version number, the bookkeeping row for the
  target schema (or its absence) and a structure digest over all of it. It also reads the
  server fingerprint (SHA-256 of `current_database()`, `pg_postmaster_start_time()` and
  `inet_server_port()`, never shown). It refuses (connector namespace, location `schema.table`
  unless stated):
  - `target_server_unsupported`: server version below 13 (location: the target schema);
  - `relation_not_found` (existing code);
  - `target_object_unsupported`: partitioned table, inheritance parent or child, a rewrite
    rule, `FORCE ROW LEVEL SECURITY`;
  - `target_external_reference`: a foreign key from a table outside the declared set to a
    target table (a `TRUNCATE` would need `CASCADE`, which would delete rows Decoy was not asked
    to touch);
  - `target_sequence_unsupported` (at `schema.table.column`): a column default calls `nextval`
    on a sequence the column does not own, one sequence feeds more than one column, or an owned
    sequence has a negative increment;
  - `target_privilege_missing`: no `TRUNCATE` or `INSERT` on a target table; not the owner (or
    a member of the owning role) of a target table or each sequence the publish restarts; or the bookkeeping rights for the case found: schema `decoy_meta` absent
    and no `CREATE` on the database (the role then owns the schema it creates); schema present
    and table `decoy_meta.publications` absent and no `USAGE` plus `CREATE` on schema
    `decoy_meta`; table present without `USAGE` on schema `decoy_meta` and `SELECT`, `INSERT`
    and `UPDATE` on the table;
  - `target_unreachable`, `catalog_read_failed`, `extension_unavailable`,
    `extension_untrusted_location`, `duckdb_unavailable`, `deadline_exceeded`.
  The catalog read decodes the bookkeeping row strictly (4.6); an unreadable row refuses with
  `publication_target_occupied` (existing decoy code).
- `plan_target(catalog, staged: Mapping[str, Path]) -> TargetPlan`. Builds the type-mapping
  report from each staged Parquet footer and the catalog (4.5), refuses
  `target_column_mismatch` (a target column missing from the Parquet or a Parquet column missing
  from the target, generated columns excepted) and `target_type_blocked` (any `lossy` or
  `unsupported` column), then runs the value guards on the staged Parquet through a local DuckDB
  connection (no target session): string length for `varchar(n)`, enum label membership, no
  null in a `NOT NULL` column, numeric and integer range, no sub-microsecond part for a
  nanosecond timestamp, integral values for a float to integer column. A guard failure is
  `value_guard_failed` (existing code) at `schema.table.column`. The guards return counts only;
  no value is read into Python. `TargetPlan` also carries the artifact list and `result_id`
  (`compute_result_id` over the staged files, role `table`).

### 4.4 Engine: publish (one transaction)

`connectors/postgres_target_publish.py`: `publish_target(config, plan, operation_id) ->
CommitReceipt`. One DuckDB connection from `open_write_session`: a read-write `ATTACH` built
through S2's single ATTACH site and its DSN helper (connect and keepalive keywords, 4.4.1), with
`ISOLATION_LEVEL 'READ COMMITTED'` (the extension's default for a read-write attach is
REPEATABLE READ, `postgres_storage.cpp`, whose snapshot at step 1 would predate the locks of
steps 2 to 4 and hide catalog changes from `capture`), `pg_debug_show_queries = false`, and
`pg_statement_timeout_millis` and `pg_idle_in_transaction_timeout_millis` left unset. One DuckDB
transaction is one PostgreSQL transaction (E0 cell a). Every target statement goes through
`postgres_execute(..., use_transaction := true)` or an `INSERT` into the attached table; no
DuckDB-side `SELECT` reads a target table through the connection pool (E0 cell c).

The worker thread of 4.4.2 owns the write connection: it opens it, runs every statement, rolls
back and closes it. Nothing else touches it; the supervisor never calls `close()` or
`interrupt()` on it (DuckDB's `Close` takes the connection lock that a blocked call holds, so a
close from another thread would block the supervisor too). Before every statement (not every
step) the worker checks `stop` and runs `SET LOCAL statement_timeout` to
min(`statement_timeout_s`, remaining deadline) in milliseconds; when the remaining deadline is
zero or less the statement does not start and the publish ends `deadline_exceeded` (4.4.3).
Steps, in order; each has a fixed name used for the error location, the failure-code registry
(4.4.3) and the test fault seam:

1. `begin`: `BEGIN`; `SET CONSTRAINTS ALL IMMEDIATE`; `SET LOCAL search_path = pg_catalog`,
   `lock_timeout`, `idle_in_transaction_session_timeout`, and on servers 14 and later
   `client_connection_check_interval = 10s`; capture `pg_current_xact_id()` and
   `pg_backend_pid()` (ids, not data) for reconcile and for the control session's guard
   (4.4.2). Reading `pg_current_xact_id()` assigns the transaction id, so `backend_xid` is set
   from here on (E0 cell j).
2. `lock_writer`: `pg_advisory_xact_lock(k1, k2)`, the two `int4` halves of the first 8 bytes
   of SHA-256 over `decoy-pg-target:` plus the schema name, computed in Python (no
   `hashtext`).
3. `check_marker`: if inspection found the schema or the table absent, take the global
   advisory key (SHA-256 of `decoy-pg-target:decoy_meta`), then `CREATE SCHEMA IF NOT EXISTS
   decoy_meta` (only when the schema was absent) and `CREATE TABLE IF NOT EXISTS
   decoy_meta.publications`; the rights each needs were checked at inspection (4.3). Read the
   row for the schema `FOR UPDATE`. Same `operation_id` and same `result_id`: roll back and
   return `already_committed` (nothing written). Same `operation_id`, other `result_id`: roll
   back, `operation_conflict` with `publication_operation_conflict`. Row differs from
   `catalog.marker`: roll back, `refused` with `delivery_pointer_moved`.
4. `lock_tables`: `LOCK TABLE ... IN ACCESS EXCLUSIVE MODE` on every target table, in sorted
   order. No table lock is taken on a non-target table. Kept lookup FKs take row-level
   `FOR KEY SHARE` locks as step 8 checks rows.
5. `capture`: `capture_structure` under the locks and `search_path = pg_catalog`, read under
   READ COMMITTED after the locks, so it sees every change committed before them; a digest
   different from `catalog` is `target_changed`. The definitions and the trigger names used in
   steps 6 and 9 come from this capture, never from the inspection.
6. `drop_foreign_keys`: drop every foreign key whose both ends are target tables (dropping a
   foreign key takes `ACCESS EXCLUSIVE` on the referenced table too, which for target tables we
   already hold). Foreign keys from a target table to a non-target lookup table are kept: the
   server checks each loaded row against the untouched lookup table, and dropping them would
   take `ACCESS EXCLUSIVE` on the lookup table and stop the application's reads of it.
   `ALTER TABLE ... DISABLE TRIGGER <name>` for each user trigger named in the capture (not
   `DISABLE TRIGGER USER`, so a trigger the capture did not see can never be left disabled);
   identity columns declared `ALWAYS` become `BY DEFAULT` so the load can write them. Indexes
   and primary key, unique, exclusion, check and not-null constraints stay (H6).
7. `truncate`: one `TRUNCATE` of every target table.
8. `load`: per table, run bounded `INSERT INTO <pg>.<schema>.<table> (<columns except
   generated>) SELECT <same columns> FROM read_parquet(<staged path>)` statements. Each
   statement selects at most 1,000,000 rows by a half-open `file_row_number` range. If that
   metadata is unavailable, each statement selects one Parquet row group and refuses a row
   group above 1,000,000 rows before writing. Sum the affected-row counts and compare the sum
   with the Parquet footer. `SET CONSTRAINTS ALL IMMEDIATE` makes a deferred lookup FK fail in
   this step, not in `commit`. A load statement that fails after at least `lock_timeout_s` is `target_busy`.
   Any earlier constraint, type or count failure is `target_load_failed` at `schema.table`.
9. `restore`: re-create every dropped foreign key from its captured definition text (a `NOT
   VALID` key as `NOT VALID`, a validated key validated; `DEFERRABLE` kept); a failure is
   `target_constraint_failed` at `schema.table.constraint`. Restore each captured user trigger
   by name to its captured `tgenabled`: `O` `ENABLE TRIGGER`, `D` `DISABLE TRIGGER`, `R` `ENABLE
   REPLICA TRIGGER`, `A` `ENABLE ALWAYS TRIGGER`. Restore identity kinds.
10. `check_sequences`: one server-side `DO` block per sequence, given only identifiers: it
    computes the restart value, `max(col) + 1` (or the sequence start value when the table is
    empty, or when `max(col) + 1` is below the sequence minimum), and raises when it is above
    the sequence maximum. It reads the sequence's parameters from `pg_sequence` and takes no
    lock that an application's `nextval` holds. No value reaches Python.
11. `sequences`: one server-side `DO` block per sequence, computing the same value and running
    `ALTER SEQUENCE ... RESTART WITH` (owned serial) or `ALTER TABLE ... ALTER COLUMN ...
    RESTART WITH` (identity). Its possible waits are the sequence lock an open application
    transaction that called `nextval` holds. `setval` is never used.
12. `write_marker`: upsert the bookkeeping row (format tag, schema, `operation_id`, `result_id`,
    engine version, `now()`).
13. `commit`: under the supervisor lock, the worker checks `stop` and, if it is clear, sets
    `committing`; then `COMMIT`. The visibility point.

After a successful commit: `ANALYZE` each target table in its own transaction with `SET LOCAL
statement_timeout`; a failure is a warning on the receipt path (logged with the step name
only), never a failed publish.

Failure handling, the same for every statement: the worker catches `BaseException`, keeps only
`type(exc).__name__`, runs DuckDB `ROLLBACK` and closes the connection (the server aborts the
transaction either way), and hands `(step, type name)` to the supervisor. It never raises out of
its thread body, so no exception, and no DSN that a duckdb-postgres connect error can carry
(`postgres_utils.cpp`), reaches `threading.excepthook` or a log. The supervisor, outside any
`except` block, decides the code by 4.4.3, probing on the control session where 4.4.3 says so.
PostgreSQL error text and definition text are never read into an error or a log.

Reconcile after `commit` raises, or after a trigger while `committing` is set and the worker
has not returned within `commit_grace_s` (H1): the supervisor runs, on the control session (or,
if it is gone, a new one opened under `control_open_budget_s`), `pg_xact_status(<xid>)`, each
call under `control_call_s`:

- `committed`: `published`.
- `aborted`: `failed` with `publication_commit_not_visible`; the target is the old one.
- `in progress`: the guarded terminate of 4.4.2 on our own backend, poll the status each second
  up to `lock_timeout_s`, then decide again; still in progress is `target_commit_unknown`.
- null (status unavailable), no connection, or `reconcile_budget_s` used up:
  `PostgresTargetError(target_commit_unknown)`; the CLI exits 3, says the outcome is unknown
  and names the schema to check.

The engine never retries a commit.

#### 4.4.1 Bounding every step

E0 cell e showed that DuckDB `interrupt()` does nothing to a postgres-extension statement, so
the deadline cannot rest on it. Each part of the write path has its own bound:

| Part | Primary bound | Backstop |
|---|---|---|
| Write session connect and `ATTACH` (worker) | libpq `connect_timeout` from S2's helper (per address) | a hard wait of `write_open_budget_s` on its own thread; overrun is `target_unreachable` before `begin` |
| Control session open and reopen (supervisor) | the same libpq bounds through `open_read_session` | a hard wait of `control_open_budget_s` on its own thread |
| Each control statement (cancel, terminate, probe, `pg_xact_status`) | its session's `statement_timeout` (`control_call_s`) | a hard wait of `control_call_s` on its own thread |
| Any statement of steps 1 to 12, including each bounded `INSERT ... SELECT FROM read_parquet` | server `statement_timeout` set by `SET LOCAL` before the statement: min(`statement_timeout_s`, remaining deadline) | control-session cancel, then terminate; then the supervisor stops waiting |
| A lock wait (steps 2, 3, 4, 8, 11) | `lock_timeout` set at `begin` | `statement_timeout` |
| A dead network while the client waits on the server | TCP keepalives (`keepalives=1`, `keepalives_idle=30`, `keepalives_interval=10`, `keepalives_count=3`) and `tcp_user_timeout=60000` (Linux; libpq ignores it where the socket option is missing) appended by S2's helper on every session; libpq has no read timeout of its own | the supervisor stops waiting |
| The client stalls between statements (SIGSTOP, a hung host) | server `idle_in_transaction_session_timeout` ends the session (M1) | none needed: `COMMIT` is never sent after `stop` |
| The client dies during a long statement | server `client_connection_check_interval` (14 and later) | `statement_timeout` |
| `COMMIT` | not cancelled (4.4.2) | `commit_grace_s`, then reconcile under `reconcile_budget_s` |
| `ANALYZE` after commit | `SET LOCAL statement_timeout` in its own transaction | the supervisor; any failure is a warning |

The DSN helper: E1 extends S2's one helper in place so it appends the connect timeout and the
keepalive keywords together, with S2's URI and key/value append rule; there is still one
function and one ATTACH site, the read side gets the keepalives too, and S2's AT-B2 expected
strings gain the keepalive suffix in E1 (same cells, stricter output).

`SET LOCAL` holds only if nothing in the session runs a plain `SET statement_timeout` later in
the transaction. The extension does so on scan connections when `pg_statement_timeout_millis`
is set, so the write session never sets it (AT-E4 spy cell), and AT-E0 cell e3 proves that a
later `postgres_execute` and an `INSERT ... SELECT FROM read_parquet` in the same transaction
obey the `SET LOCAL` value.

#### 4.4.2 Control session and supervisor

New private module `connectors/_postgres_control.py` (reusable by the read side, Q20). Only
the supervisor uses the control session; the worker never does.

- `ControlSession`: a read-only session from `open_read_session` (S2 helper, its own
  `statement_timeout_s = control_call_s`), opened by `run_supervised` before the worker starts. Autocommit only:
  it never runs `BEGIN`, and each call is one statement, so each `pg_stat_activity` read is a
  fresh snapshot. If it cannot be opened within `control_open_budget_s` the publish stops with
  `target_unreachable` and `open_write_session` is never called: the cancel path exists before
  a lock is taken.
- `cancel(pid, xid)` and `terminate(pid, xid)`: the only callers of `pg_cancel_backend` and
  `pg_terminate_backend` in `src/` (AT-E17 sentry). Each is one statement, `SELECT
  pg_cancel_backend(pid) FROM pg_stat_activity WHERE pid = <pid> AND backend_xid =
  xid('<xid>'::xid8)`, with both values program-built integers. The `backend_xid` match is the
  pid-reuse guard: once our transaction has ended, or the pid belongs to another backend, no
  row matches and nothing is signalled. The functions need no superuser: the control session
  uses the same role as the write session.
- `probe(pid, relations)`: reachable or not; whether `pid` still exists; and, for the steps
  4.4.3 marks, the inspection's privilege and ownership query re-run (constant catalog SQL).
- Every control call (open, reopen, cancel, terminate, probe, status) runs on its own daemon
  thread with a hard wait budget (`control_open_budget_s` for an open, `control_call_s` for a
  statement). The thread body catches `BaseException` and keeps only the type name. A call that
  overruns is treated as failed and its thread is abandoned. The first overrun marks that
  control session dead. The next required control call uses the single allowed reopen. A
  reopened session is never reopened again. The supervisor never blocks on an abandoned call.
- `run_supervised(steps, deadline_s, open_control) -> result`: the worker runs the steps; the
  calling thread waits on it in at most 0.25 s slices. At entry, when it runs on the main
  thread, it installs a SIGINT handler that only records a press. The handler stays installed
  through control open, write open, the worker, and reconcile. A recorded press is the Ctrl-C
  trigger. `run_supervised` restores the previous handler in `finally` for every return and
  error. The publish calls `Deadline.arm_expiry_only`, which uses the existing timer core only
  to set `expired`. It never calls the interrupting arm or `conn.interrupt()`.
- On the first trigger, it records `trigger_at` and sets `stop` before anything else. Thus, an
  exception between the trigger and the lock still leaves `stop` set. Every wait is
  `min(the wait budget, time left in the current window)`. Window ends are calculated from
  `trigger_at`, never from the end of a prior call: cancel ends at `trigger_at +
  cancel_grace_s`; terminate ends at `trigger_at + 2 * cancel_grace_s`; commit wait ends at
  `trigger_at + commit_grace_s`; reconcile ends at `trigger_at + commit_grace_s +
  reconcile_budget_s`. If reconcile starts after a commit error with no earlier trigger, its
  window starts at reconcile entry and ends after `reconcile_budget_s`. A later Ctrl-C records
  the trigger but cannot restart or extend that reconcile window. Then, under the supervisor
  lock, it reads `committing`:
  - `committing` not set: `cancel` once per second until the worker returns or
    `cancel_grace_s` passes; then `terminate` once and wait up to `cancel_grace_s` more; then
    stop waiting (the worker is a daemon and is abandoned, its connection left referenced and
    unclosed). Because `stop` is checked before every statement and under the lock before
    `COMMIT`, an abandoned worker that wakes later rolls back and never commits.
  - `committing` set: never cancel. Wait `commit_grace_s` for the worker; if it returns, use
    its result; else reconcile. The result is `published`, `publication_commit_not_visible` or
    `target_commit_unknown`, never `KeyboardInterrupt`.
  - The control session fails or is marked dead during a trigger: the next required call
    reopens it once. That reopen waits for `min(control_open_budget_s, time left in the current
    window)`. If it fails, keep waiting on the same trigger-anchored schedule. The server
    `statement_timeout` still ends the statement.

The worker's write-session open also runs under supervision. If it does not finish within
`write_open_budget_s`, `run_supervised` sets `stop`, abandons that daemon thread, and returns
`target_unreachable`. No `begin` statement has run. A late open closes its connection without
starting a transaction.

After the trigger the result is `deadline_exceeded` (deadline) or `KeyboardInterrupt` (Ctrl-C,
exit 130), mapped through the existing `raise_for_interrupt`, unless reconcile decided it. An
abandoned worker leaves one daemon thread and one DuckDB connection in the process until the
blocked call returns or the process exits; the server ends the transaction by its own timeouts.
AT-E18 cell 4 proves only that the supervisor stops waiting when a userspace proxy keeps
acknowledging the client socket. It does not prove server cleanup or plain interpreter exit.
A long-lived host process (the platform) keeps an abandoned thread. On the CLI path only, if
normal interpreter shutdown is held by that thread, flush user-visible output and server-admin
logs, close the run `ExitStack`, then call `os._exit` with the already selected exit code.

#### 4.4.3 Reason codes and the half-done transaction

No PostgreSQL error text or SQLSTATE is read. The code comes from what the supervisor knows
(trigger, step, elapsed time against the statement's applied timeout) and the probe. First
match wins:

| # | Condition | Code | Transaction afterwards |
|---|---|---|---|
| 1 | Trigger or failure while `committing` | reconcile: `published`, `publication_commit_not_visible` or `target_commit_unknown` (exit 3, also after a Ctrl-C) | committed or aborted, read from `pg_xact_status` |
| 2 | Ctrl-C trigger | `KeyboardInterrupt` (exit 130) | the cancelled statement leaves it aborted; the worker sends `ROLLBACK` and closes; after a terminate or an abandoned worker the server aborts it when the backend ends or a server timeout passes. Never committed |
| 3 | Deadline trigger, or a statement not started because the remaining deadline is zero or less | `deadline_exceeded` | as row 2 |
| 4 | Control session or write session not opened within its open budget, before `begin` | `target_unreachable` | none started |
| 5 | A step fails and the probe cannot reach the server, or our `pid` is gone and we did not terminate it (connection lost, idle-in-transaction timeout, an administrator's terminate) | `target_unreachable` | aborted by the server when the backend ended |
| 6 | The failing `load` statement ran for at least `lock_timeout_s` | `target_busy` at `schema.table` | a lookup-row lock wait can have reached the lock timeout; the worker rolls back |
| 7 | A statement fails after running at least its applied `statement_timeout` (the per-statement cap, with the deadline not yet passed) | `deadline_exceeded` at the step | the server cancelled it; the worker rolls back |
| 8 | A step marked "privilege re-check" fails and the probe finds a right or an ownership missing | `target_privilege_missing` at the step's location | aborted; the worker rolls back |
| 9 | Any other step failure | the step's code in the registry below | aborted; the worker rolls back |

Failure-code registry: one table in `postgres_target_publish.py`, keyed by step name, the only
source of a step's code (AT-E9 asserts the code for an injected fault at each step).

| Step | Code | Privilege re-check |
|---|---|---|
| `begin` | `target_unreachable` | no |
| `lock_writer` | `target_busy` | no |
| `check_marker` | `target_busy` | yes (bookkeeping rights) |
| `lock_tables` | `target_busy` | yes (ownership) |
| `capture` | `catalog_read_failed`; a digest difference is `target_changed` | no |
| `drop_foreign_keys` | `target_changed` | yes (ownership) |
| `truncate` | `target_changed` | yes (`TRUNCATE`) |
| `load` | `target_load_failed` | yes (`INSERT`) |
| `restore` | `target_constraint_failed` | yes (ownership) |
| `check_sequences` | `target_sequence_failed` | no |
| `sequences` | `target_busy` | yes (sequence ownership) |
| `write_marker` | `target_changed` | yes (bookkeeping rights) |
| `commit` | reconcile (row 1) | no |

In every row before `COMMIT` the target, its sequences and the bookkeeping row are unchanged,
because every write is inside the one transaction and nothing sends `COMMIT` after `stop`.
AT-E9, AT-E17 and AT-E18 prove it per row with the catalog, row, sequence and bookkeeping
digests and with `pg_locks` empty for our pid within the stated bound.

### 4.5 Type-mapping rules

Each column passes three steps: the Arrow type in the staged Parquet footer, the DuckDB type of
the attached target column (as the extension maps it), and the PostgreSQL type
(`format_type(atttypid, atttypmod)`). Each step pair is classed and the column takes the worst
class (`unsupported` > `lossy` > `normalized` > `exact`). The table below gives the result per
Arrow and PostgreSQL pair; the middle DuckDB type is checked by the same table in
`postgres_typemap.py`.

| Arrow | Target | Class | Guard |
|---|---|---|---|
| int16, int32, int64 | smallint, integer, bigint of equal or wider width | exact | none |
| int wider than the target | narrower integer | normalized (pandas route widens) | range |
| float32 / float64 | real / double precision | exact | none |
| float64 | smallint, integer, bigint | normalized (pandas route: nullable ints become float64) | integral and range |
| float64 | real | lossy | n/a |
| bool | boolean | exact | none |
| decimal128(p, s), p <= 38 | numeric(p2, s) with 38 >= p2 >= p | exact | none |
| decimal128(p, s) | numeric(p2, s) with p2 < p | normalized | range |
| decimal128(p, s) | numeric(p2, s2) with s2 != s | lossy | n/a |
| any | numeric without typmod, or numeric(p2, s) with p2 > 38 | unsupported (DuckDB maps it to double or cannot hold it; V2-LOG varchar transport) | n/a |
| string | text, json | exact | none |
| string | character varying(n) | normalized | length |
| string | character varying (no n) | exact | none |
| string | jsonb, uuid | normalized (server re-serializes, parse refuses bad input in `load`) | none |
| string | an enum type | normalized | enum labels |
| string | character(n) | lossy (blank padding) | n/a |
| date32 | date | exact | none |
| timestamp[us] | timestamp without time zone | exact | none |
| timestamp[ns] | timestamp without time zone | normalized (pandas route) | no sub-microsecond part |
| timestamp[us, tz] | timestamp with time zone | normalized (instant kept, shown as UTC) | none |
| timestamp[ns, tz] | timestamp with time zone | normalized | no sub-microsecond part |
| time64[us] | time without time zone | exact | none |
| binary | bytea | exact | none |
| list<T> | T[] where T maps exact | exact | none |
| any | a stored generated column | generated (left out of the load, recomputed) | none |
| anything else | anything else | unsupported | n/a |

`NOT NULL` adds the null-count guard to any row. Every `exact` row has a round-trip cell
(AT-E16). The report document: `schema: decoy-pg-type-map/v1`, `target_schema`, and per column
`table`, `column`, `arrow_type`, `duckdb_type`, `target_type`, `class`, `guard`; canonical JSON,
sorted by table then column. It holds names and type text only.

### 4.6 The bookkeeping row (persisted read model)

`decoy_meta.publications(target_schema name primary key, format text, operation_id text,
result_id text, engine_version text, published_at timestamptz)`. The writer and the strict
reader share one declaration in `postgres_target_catalog.py`: `format` must equal
`decoy-pg-publication/v1` exactly (an unknown or missing tag refuses), `operation_id` is
`fullmatch`ed against `OPERATION_ID_PATTERN`, `result_id` is 64 lowercase hex, `engine_version`
against the descriptor's version pattern; a row failing any check is
`publication_target_occupied`. Value-free: no data value is stored.

### 4.7 Pipeline level (engine)

`execution/pipeline/_postgres_target.py`, public through `decoy_engine`:

- `PostgresTargetSettings` (frozen, strict): `extension_directory`, `scratch_parent`,
  `memory_limit`, `threads`, and the timeouts of 4.3.
- `open_postgres_target(config, settings) -> ContextManager[PostgresTargetHandle | None]`: `None`
  when the config has no Postgres target. Resolves the target `connection_ref` once with
  `prepare_secret(..., requirements=(POSTGRES_DSN_V1,))`, builds the relations, calls
  `read_target`. If the config also has Postgres sources, it resolves the source reference the
  same way, calls the public `server_fingerprint(config)` in 64b's
  `connectors/postgres_catalog.py` (catalog-only, read-only session, no relation read), closes
  that secret, and refuses `target_same_database` on equality. All of this runs before
  `stage_postgres_sources`, so no source row is read on a refusal (H7).
- `PostgresTargetHandle.plan(staged)` and `.publish(plan, operation_id)`.

Exit classification (H8): each new connector code carries its outcome on its spec.
`CONFIGURATION` with `RetryClass.CONFIGURATION_REPAIR`: `target_server_unsupported`,
`target_object_unsupported`, `target_external_reference`, `target_privilege_missing`,
`target_sequence_unsupported`, `target_column_mismatch`, `target_type_blocked`,
`target_same_database`. `EXECUTION`: `target_unreachable`, `target_changed`, `target_busy`,
`target_load_failed`, `target_constraint_failed`, `target_sequence_failed`,
`target_commit_unknown`. 64b derives its usage set from the registry by outcome at import, and
the CLI arm maps a `PostgresSnapshotError` (so also `PostgresTargetError`) by that set. F01
adds no set, no literal list and no CLI arm.

`DELIVERABLE_TARGET_TYPES` (`src/decoy_engine/delivery/_plan.py:24`) gains `"postgres"`, so
`plan_delivery` expects an outcome for every Postgres target table.

### 4.8 CLI

- `prepare` (`C:src/decoy/cli/run/_prepare.py`): after the static gate and before any source is
  staged or read, enter `open_postgres_target` on the run `ExitStack`. A refusal here exits
  before any row is read. The run card prints the target schema, the table list and the
  operation id. `--resume` with a Postgres target is refused here with 64b's flag refusal, exit
  1, before any connection (M4, Q19).
- `io/_postgres_target.py`: `PostgresTargetStage`, a `SinkStage` (DELIV 4.6). At open it
  allocates protected scratch (`library/_scratch.allocate`) and places each Postgres target
  table at `<scratch>/<table>.parquet` through the sink's `Placer`, so every route (plain,
  `--chunked`, isolated) writes Parquet there with the existing writers. `deliver(decision,
  before_visible)`: if `decision.deliver` is false, abort. Else `handle.plan(staged)`, then
  `before_visible()` (DELIV vault and evidence order), then `handle.publish(plan,
  operation_id)`; the visibility point is a `published` or `already_committed` receipt. `abort`
  removes the scratch. The scratch is removed on every exit.
- `operation_id`: the run's existing F22 operation id (DELIV 7.1).
- `PublishedOutput` gains `PostgresOutput(schema, table)`; `display()` is `postgres:<schema>.<table>`
  (no reference, no host).
- Card and `--json`: a type-map summary (counts per class and every blocking row by
  `table.column`) on the card; `--json` gains `postgres_target: {schema, tables, outcome,
  type_map}` where `type_map` is the engine document (shape changelog entry).
- Exit codes: no new arm. 64b's registry-derived arm covers every new connector code;
  `target_postgres.*` config codes take the existing config arm (1); `PublicationRefused` with
  `publication_operation_conflict` or `delivery_pointer_moved` takes the existing publication arm
  (3). AT-C6 walks every new code.
- Ctrl-C: before the visibility point the engine rolls back and the run exits 130 with nothing
  delivered; after it the run is delivered (DELIV 4.6 rule).

## 5. Enumerations

### 5.1 Exit paths

- 0: published or `already_committed`; scratch removed (`C:src/decoy/cli/exit_codes.py:163`).
- 1: compile refusals (`target_postgres.*`, bad or unknown reference); secret not resolvable;
  `--resume` with a Postgres target; every `CONFIGURATION` code from `read_target`,
  `plan_target` or `open_postgres_target` (before any target write and any source row).
- 3: every `EXECUTION` target code (`target_unreachable`, `target_busy`, `target_changed`,
  `target_load_failed`, `target_constraint_failed`, `target_sequence_failed`,
  `target_commit_unknown`), `catalog_read_failed`, `deadline_exceeded`, `duckdb_unavailable`,
  `publication_operation_conflict`, `delivery_pointer_moved`,
  `publication_commit_not_visible`, `publication_target_occupied`.
- 4: a post-scan block withholds the run (DELIV 4.2 step 4); the target is not opened for write.
- 5: capacity refusal from the gate, before any target write.
- 130: Ctrl-C before the commit (rolled back, the `raise_for_interrupt` mapping in `src/decoy_engine/connectors/_postgres_session.py:141`).

### 5.2 Routes

- Plain `decoy run` (resident `run_pipeline`, pandas mask route by default): writes staged
  Parquet through the sink's placer; its widened ints, float64 nullable ints and nanosecond
  timestamps meet the `normalized` rows of 4.5.
- `--chunked` and the automatic streaming route: chunked Parquet writer into the same placed
  path (`C:src/decoy/cli/io/_targets.py:466`).
- Isolated subprocess and out-of-core FK routes: the placed paths sit in the parent's scratch,
  entered on the parent `ExitStack`; the child writes there.
- `--resume`: refused with a Postgres target (4.8).
- Non-run callers with a Postgres target (`decoy.mask()`, `demo`, `tokenize`, `subset`,
  `report fidelity --config` and every other command that reads `targets:`): refused at the
  CLI I/O choke point `_require_local_io_endpoints` (`C:src/decoy/cli/run/_execute.py:238`)
  with `target_postgres.unsupported_command`, exit 1. Engine callers that pass a Postgres target
  descriptor to a file writer meet the refusal in the engine target writer dispatch (E1).
- `publish_unit` and `publish_tables` (`src/decoy_engine/publication/_publish.py:221`, `:419`):
  never reached for a Postgres target; the CLI stage calls the handle instead.

### 5.3 FK shapes

- Scalar FK between two target tables: dropped in `drop_foreign_keys`, re-created in `restore`
  after both tables load; a masked child that breaks it fails the run with
  `target_constraint_failed`, rolled back.
- Composite FK: same path; `pg_get_constraintdef` carries the column list and match type.
- Self-referencing FK: one table, dropped and re-created like any other.
- FK cycle between target tables: handled, because no FK exists during the load.
- FK from a non-target table to a target table: `target_external_reference` at inspection.
- FK from a target table to a non-target table (a lookup table not in the pipeline): kept in
  place during the load. `SET CONSTRAINTS ALL IMMEDIATE` makes the server check each bounded
  insert rather than queue deferred checks until commit. A violation is `target_load_failed`
  at `schema.table`, rolled back. The check takes a row-level `FOR KEY SHARE` lock. Plain reads
  and non-key updates continue. A delete or referenced-key update waits behind that lock. An
  application `SELECT FOR UPDATE` can make the load wait. A load failure after
  `lock_timeout_s` is `target_busy`. No lookup-table privilege is required because PostgreSQL
  checks the FK through its internal trigger.
- `NOT VALID` FK between target tables: re-created `NOT VALID`, not validated (as it was). A
  kept `NOT VALID` FK to a lookup table still checks new rows, as PostgreSQL does for any insert.
- Deferrable FKs: re-created with their `DEFERRABLE` clause intact (constraint definition text).

### 5.4 Descriptor fields

- `type`: `"postgres"`, the discriminator (`src/decoy_engine/config/_targets.py:135`).
- `connection_ref`: F13 reference; locator field; never echoed; resolved once per run.
- `schema`, `table`: identifiers under the one rule; exact case.
- `mode`: `"replace"`, required.
- No `format`, `path`, `columns`, `truncate` or `if_exists` field (`extra="forbid"`).

### 5.5 Output surfaces

- stderr error line and `--json` error object (`decoy-error-v1`): code plus location only.
- Run card: target schema, table names, operation id, type-map class counts and blocking
  `table.column` names; no reference, host, value or definition text.
- `--json` success document: `postgres_target` key with the type-map document.
- Run folder records (RESULT document, run record): built from the declared config; outputs as
  `postgres:<schema>.<table>`.
- Engine log lines: `postgres_target step=<name> code=<code> location=<loc>` and
  `postgres_target published relations=<n>`; nothing else (`src/decoy_engine/connectors/postgres_snapshot.py:408` style).
- Receipt (`CommitReceipt`): outcome, operation id, reason code, `result_id`, artifact
  summaries (role, size, rows, digest); no path in the receipt.
- The target database: `decoy_meta.publications` row (4.6).
- OTel telemetry: codes and counts only (existing CLI redaction sentries).

## 6. Frozen contracts

- Exit integers 0 to 6 and 130 keep their meaning; no new exit code.
- `TargetDescriptor` gets one more union member: additive; existing configs parse and hash as
  before.
- `DELIVERABLE_TARGET_TYPES` grows by one token; the delivery decision for existing target types
  is unchanged.
- F22 `CommitReceipt`, `Outcome`, `decoy-publication/v1` descriptor and its schema snapshot:
  unchanged. The Postgres path builds receipts with the existing tokens and no new unit token.
- New persisted formats: `decoy-pg-publication/v1` (database row) and `decoy-pg-type-map/v1`
  (report document), each with a schema snapshot test added in the slice that writes it.
- Reason codes, all `since=UNRELEASED`, each with its outcome on the spec (4.7): config
  `target_postgres.identifier_invalid`, `.multiple_connections`, `.multiple_schemas`,
  `.mixed_targets`, `.best_effort_unsupported`, `.target_is_source`, `.unsupported_command`;
  connector `target_server_unsupported`, `target_unreachable`, `target_object_unsupported`,
  `target_external_reference`, `target_privilege_missing`, `target_sequence_unsupported`,
  `target_column_mismatch`, `target_type_blocked`, `target_same_database`, `target_changed`,
  `target_busy`, `target_load_failed`, `target_constraint_failed`, `target_sequence_failed`,
  `target_commit_unknown`. Existing code specs are unchanged. `REGISTRY_VERSION` and the reason
  manifests are not touched; the release stamps them.
- 64b's `connectors/postgres_catalog.py` gains the public `server_fingerprint` (additive).
- `decoy-error-v1` schema unchanged; the `--json` success shapes snapshot gains the
  `postgres_target` key (shape changelog entry in C2).
- New public engine names go on the frozen-surface map in the slice that adds them:
  `PostgresTarget`, `PostgresTargetConfig`, `TargetRelation`, `TargetCatalog`, `TargetPlan`,
  `PostgresTargetError`, `read_target`, `plan_target`, `publish_target`, `TypeMapEntry`,
  `TypeMapReport`, `map_types`, `server_fingerprint`, `PostgresTargetSettings`,
  `PostgresTargetHandle`, `open_postgres_target`.
- No cap, pin ceiling, ratchet, sentry baseline or allowlist count is raised (class 11).

## 7. Failure modes and partial failure

| Case | What happens | Target afterwards | Test |
|---|---|---|---|
| Target reference unset or invalid material | existing secret refusal, exit 1, at prepare | untouched, never connected | AT-C3 |
| Server older than PostgreSQL 13 | `target_server_unsupported`, exit 1 | untouched | AT-E5 |
| Target relation missing, partitioned, with a rule, FORCE RLS | inspection refusal, exit 1, before any row read | untouched | AT-E5, AT-C8 |
| Non-target table references a target table | `target_external_reference`, exit 1 | untouched | AT-E5 |
| Non-owned `nextval` default, shared sequence, negative increment | `target_sequence_unsupported`, exit 1 | untouched | AT-E5 |
| Missing TRUNCATE, INSERT, target-table ownership, sequence ownership, or the bookkeeping right for the case found | `target_privilege_missing`, exit 1 | untouched | AT-E5 |
| Target is the source database | `target_same_database` (or compile `target_is_source`), exit 1, before any source row | untouched | AT-E7, AT-E2 |
| Lossy or unsupported type, missing or extra column | `target_type_blocked` / `target_column_mismatch`, exit 1, report shows the rows | untouched | AT-E3, AT-E6 |
| Guard fails (length, enum, null, range, sub-microsecond, non-integral) | `value_guard_failed` at `table.column`, exit 1 | untouched | AT-E6 |
| Another Decoy publish holds the target | `target_busy` after `lock_timeout_s`, exit 3 | untouched | AT-E12 |
| An application transaction holds a table lock | `target_busy`, exit 3 | untouched | AT-E12 |
| Index, constraint or column changed after inspection (even just before the lock) | `target_changed` under the lock, rolled back, exit 3 | old contents | AT-E12 |
| Another writer published after inspection | `delivery_pointer_moved`, rolled back, exit 3 | other writer's contents | AT-E12 |
| Masked rows break a unique, exclusion, check or not-null constraint, or row count differs | `target_load_failed` at `schema.table`, rolled back, exit 3 | old contents | AT-E9 |
| Masked rows break a FK between target tables | `target_constraint_failed` at the constraint, rolled back, exit 3 | old contents | AT-E9 |
| Masked rows break a kept FK to a lookup table | `target_load_failed` at `schema.table`, rolled back, exit 3 | old contents | AT-E9 |
| An application reads or updates a non-key lookup column during the publish | continues; the FK check takes only `FOR KEY SHARE` on referenced rows | n/a | AT-E9 |
| An application deletes or changes a referenced lookup key during the load | waits behind the FK check; it continues after commit or rollback | n/a | AT-E9 |
| An application holds `SELECT FOR UPDATE` on a referenced lookup row | the load waits and then returns `target_busy` at `lock_timeout_s` | old contents | AT-E9 |
| A right or an ownership is revoked between inspection and a step | probe re-check, `target_privilege_missing` at the step, rolled back, exit 3 | old contents | AT-E9 |
| A trigger is added while `lock_writer` waits | `capture` (READ COMMITTED, after the locks) sees it, `target_changed`, rolled back; the new trigger is still enabled | old contents | AT-E12 |
| Restart value above a sequence maximum | `target_sequence_failed`, rolled back, exit 3 | old contents, old sequence state | AT-E9 |
| Failure in any step 1 to 12 | rolled back by the transaction | old contents, sequences unchanged | AT-E9 |
| Connection lost before COMMIT | server aborts; `target_unreachable`, exit 3 | old contents | AT-E9, AT-E13 |
| COMMIT sent, acknowledgement lost | reconcile by `pg_xact_status`: `published` (exit 0) or `publication_commit_not_visible` (exit 3) | new or old, reported correctly | AT-E13 |
| Our backend still in progress at reconcile | terminate own pid, re-check | old contents (aborted) | AT-E13 |
| Reconcile cannot connect or status null | `target_commit_unknown`, exit 3, message names the schema to check | unknown, never retried | AT-E13 |
| Deadline passes during a statement | server `statement_timeout` (set to the remaining deadline) or the control-session cancel ends it, rollback, `deadline_exceeded`, exit 3 | old contents | AT-E9, AT-E17, AT-E0 e3 |
| A step runs past its per-step cap with deadline left | server `statement_timeout`, rollback, `deadline_exceeded` at the step, exit 3 | old contents | AT-E9 |
| Lock wait on a target table or an owned sequence | `lock_timeout` in `lock_tables` or `sequences`, `target_busy`, exit 3 | old contents | AT-E9 |
| Ctrl-C before commit | supervisor cancels through the control session, rollback, exit 130, scratch removed | old contents | AT-E18, AT-C5 |
| Ctrl-C or deadline while `COMMIT` is in flight, including a second Ctrl-C | no cancel; the whole-call handler records SIGINT; wait `commit_grace_s`, then reconcile; undecided is `target_commit_unknown`, exit 3, never 130 | new or old, reported correctly | AT-E18 |
| A second Ctrl-C during the cancel sequence | recorded only; the sequence runs to its end, then one `KeyboardInterrupt` | old contents | AT-E17 |
| A control call (cancel, terminate, probe, reopen, status) blocks on a dead network or DNS | its own thread overruns its budget and is abandoned; the supervisor keeps its schedule | old contents, or reconcile's answer | AT-E17, AT-E18 |
| A userspace proxy keeps ACKing but stops forwarding mid-load | the supervisor stops waiting on schedule; this cell does not prove process exit or server cleanup | server outcome checked separately after the proxy releases | AT-E18 |
| Control session cannot connect at publish start | `target_unreachable` within `control_open_budget_s`, exit 3; `open_write_session` never called | untouched, no lock taken | AT-E17 |
| Write session open does not return | `target_unreachable` within `write_open_budget_s`, exit 3; a late open closes without `BEGIN` | untouched, no lock taken | AT-E18 |
| Control session lost during the publish, then a trigger | the next required call reopens once within the current trigger-anchored window; if it fails, server `statement_timeout` ends the statement | old contents | AT-E17 |
| Our pid reused by another backend, or our transaction already ended, when a cancel is sent | the `backend_xid` guard matches no row; nothing is signalled | unchanged by the cancel | AT-E17 |
| Cancel arrives between two statements (no effect) | `stop` is checked before each step and re-sent each second during the grace | old contents | AT-E17 |
| Worker blocked and deaf to cancel and terminate (network dead) | supervisor stops waiting after `2 * cancel_grace_s`, `deadline_exceeded` or 130; the abandoned worker can never send `COMMIT` | old contents (server aborts on its timeouts) | AT-E18 |
| A connect error carries the DSN (duckdb-postgres) in a worker or control thread | thread bodies catch `BaseException` and keep only the type name; nothing reaches `threading.excepthook` | n/a | AT-E14 |
| Session killed by `idle_in_transaction_session_timeout` or by an administrator | probe finds our pid gone, `target_unreachable`, exit 3 | old contents | AT-E17 |
| SIGKILL of the CLI mid-load | server aborts on disconnect | old contents, no litter | AT-E11 |
| CLI stopped (SIGSTOP) inside the transaction | locks released after `idle_in_transaction_timeout_s` | old contents | AT-E11 |
| Retry of a committed operation, same result | `already_committed`, exit 0, nothing written | unchanged | AT-E12 |
| Same operation id, different result | `publication_operation_conflict`, exit 3 | unchanged | AT-E12 |
| `ANALYZE` fails after commit | warning, exit 0 | new contents | AT-E8 |
| Post-scan blocks the run | target never opened for write, exit 4 | untouched | AT-C1 |
| `--resume` with a Postgres target | flag refusal, exit 1, no connection | untouched | AT-C10 |
| A row error text or a definition carries a value | text never read into errors or logs | n/a | AT-E14 |

## 8. Acceptance tests (red first)

Each test is written first and fails on `origin/main` (or on the slice base) for the stated
reason, then passes on the slice head. `pg_integration` tests run in `pg-gate`
(`DECOY_REQUIRE_PG=1`, zero skips); the others run in the default suites. Each named mutation
must turn its test red on the final slice head (class 9).

### 8.1 Engine

| Id | Test | Red because | Mutation that must turn it red | Slice |
|---|---|---|---|---|
| AT-E0 | `tests/connectors/test_postgres_write_spike.py` (pg), raw DuckDB calls only. Cells: (a) in one DuckDB transaction over a read-write ATTACH, `postgres_execute(..., use_transaction := true)` DDL, a `TRUNCATE` and an `INSERT ... SELECT FROM read_parquet` are invisible to a second libpq session before `COMMIT` and undone by `ROLLBACK`; (b) closing the connection mid-transaction aborts it and releases its locks; (c) a DuckDB-side `SELECT` of a locked, truncated table inside the transaction returns at once with the in-transaction state (no hang, no stale read), recorded either way and the design keeps such reads out; (d) `pg_clear_cache()` after a DDL shows the changed catalog; (e) recording cell, strict (revision 4): `interrupt()` does NOT return control or cancel the server statement on the four paths of the record (`postgres_query`, `postgres_execute`, the same in a transaction, a `TRUNCATE` waiting on a lock); asserted as observed, so a DuckDB change that fixes it turns the cell red and is noticed; the worker is released afterwards by `pg_cancel_backend` so the cell ends; (e2) `pg_cancel_backend(<pid>)` from a second session stops a running `postgres_execute` in the transaction, the call returns with an error, `ROLLBACK` works; (e3, new in revision 4, `serial`) the new mechanism: (e3.1) `SET LOCAL statement_timeout = '2s'` through `postgres_execute` in the transaction bounds a later `postgres_execute` of `pg_sleep(30)` and an `INSERT ... SELECT FROM read_parquet` slowed by a `BEFORE INSERT` trigger that sleeps: each call returns with an error within 2 s plus 3 s slack, `ROLLBACK` works, and the target's catalog and row digests are unchanged; with `pg_statement_timeout_millis` unset, `current_setting('statement_timeout')` read in the transaction after the `INSERT` still equals the `SET LOCAL` value; (e3.2) `SET LOCAL lock_timeout = '1s'` bounds a `LOCK TABLE` behind a peer's lock and a `TRUNCATE` behind it, both return within 1 s plus 3 s, `ROLLBACK` works; (e3.3) a second, `READ_ONLY` attached session runs the guarded `SELECT pg_cancel_backend(pid) FROM pg_stat_activity WHERE pid = <pid> AND backend_xid = xid('<xid>'::xid8)` through `postgres_query`: with the right xid it returns true and the blocked call returns within 5 s; with a wrong xid it matches no row and the statement keeps running; the guarded `pg_terminate_backend` works the same way and the peer sees our locks gone within 5 s; (e3.4) a read-write `ATTACH` whose DSN ends in ` connect_timeout=2` (key/value) or `?connect_timeout=2` (URI) fails against a blackhole address within 2 s plus 3 s (cell h covered the read path); (e3.5, revision 5) a read-write `ATTACH` with `ISOLATION_LEVEL 'READ COMMITTED'`: `current_setting('transaction_isolation')` inside the DuckDB transaction is `read committed`, and a second session's committed change to a catalog row is visible to a later statement of the same transaction; without the option it reads `repeatable read` (recorded); (f) `INSERT` with a column list into a table with a stored generated column, an identity switched to `BY DEFAULT`, and enum, jsonb, uuid and array columns succeeds; (g) the `INSERT` affected-row count is returned; (h) a connect-timeout mechanism bounds a connection to a blackhole address; (i) `postgres_execute` with a `DO` block running `ALTER SEQUENCE ... RESTART` is undone by `ROLLBACK`; (j) `pg_current_xact_id()` and `pg_backend_pid()` read inside the transaction equal what a second session sees in `pg_stat_activity`. Cell a checks invisibility with catalog reads (`relfilenode`, `to_regclass`), because the `TRUNCATE` lock blocks a second-session `count(*)`. Timing-bound cells (b, e, e2, e3, h) carry the `serial` mark | no evidence of the transaction behaviour; e3: no evidence that the new bound works | run cell (a) with `use_transaction := false`; e3: drop the `SET LOCAL statement_timeout` (e3.1 red: the call does not return in time); e3: drop the `backend_xid` condition (e3.3 wrong-xid cell red) | E0 |
| AT-E1 | `tests/unit/config/test_postgres_target.py`: a `type: postgres` target parses; missing `mode`, `mode: append`, extra keys, empty strings, a bool and an int in each string field are refused with input hidden; `connection_ref` is a locator field; two tables on one `(ref, schema, table)` hit the duplicate-destination refusal | no variant | drop the postgres arm of `_target_identity` | E1 |
| AT-E2 | `tests/unit/plan/test_postgres_target_check.py`: identifier cells including `"ok\n"`, two refs, two schemas, a postgres plus a file target, `best_effort`, target ref equal to a source ref, `vault://x` are each refused with their code and location; the text never holds the ref | no check | replace `fullmatch` with `match` and `$` in `validate_identifier` | E1 |
| AT-E3 | `tests/unit/connectors/test_postgres_typemap.py`: one cell per row of 4.5 across all three steps, including the pandas-route rows (int64 to integer, float64 to bigint, `timestamp[ns]`), numeric without typmod and numeric(40, 2) as `unsupported`, float64 to real and `character(n)` as `lossy`, decimal scale change, generated column, and a DuckDB middle type that downgrades an otherwise exact pair; missing and extra columns; the document is canonical bytes, sorted, tagged `decoy-pg-type-map/v1`, and its schema snapshot matches | no module | drop the DuckDB step from the worst-class fold | E1 |
| AT-E4 | `tests/sentry/test_postgres_session_choke_point.py` (new; 64b E1 merged no session sentry): in `connectors/`, `open_write_session` is called only from `postgres_target_publish.py`, and an `ATTACH` without `READ_ONLY` appears only in `_postgres_session.py`; seeded cells for each fail. Spy cell (a fake connection records executed text): the write session's `ATTACH` carries `connect_timeout=<connect_timeout_s(deadline_s)>`, the keepalive keywords and `tcp_user_timeout` (4.4.1) for both DSN forms and `ISOLATION_LEVEL 'READ COMMITTED'`, and the session never sets `pg_statement_timeout_millis` or `pg_idle_in_transaction_timeout_millis`. S2's `test_type_postgres_attach_has_one_site` stays green with the write mode added. Existing snapshot and 64b tests pass unchanged (negative control) | no write session | call `open_write_session` from `postgres_target.py`; set `pg_statement_timeout_millis` on the write session (spy cell red); drop the isolation option (spy cell red) | E1 |
| AT-E16 | `tests/connectors/test_postgres_typemap_roundtrip.py` (pg): for every `exact` row of 4.5, a Parquet value goes through `open_write_session` `INSERT` into a column of that PostgreSQL type in a rolled-back transaction and is read back by libpq equal to the source | no write session | map `timestamp[us, tz]` as `exact` to `timestamp without time zone` | E1 |
| AT-E5 | `tests/connectors/test_postgres_target_inspect.py` (pg): server version faked below 13 (catalog stub cell), missing relation, partitioned table, inheritance child, rule, FORCE RLS, external FK, non-owned `nextval` default, shared sequence, negative increment, a role that owns the target table but not its owned sequence, a role without TRUNCATE, a non-owner role, and the three bookkeeping cases (schema `decoy_meta` absent and no database `CREATE`; schema present, table absent and no `CREATE` on the schema while the role has database `CREATE`; schema present, table absent, schema `CREATE` granted but no schema `USAGE`; table present without `UPDATE`; table present with table rights but no schema `USAGE`) all refuse with their codes. A role that holds no application privilege on a lookup table that a target FK points at passes inspection because FK checks use an internal trigger. Each sequence and bookkeeping refusal has a passing cell with ownership or the required right granted. `pg_stat_user_tables` counters, `pg_namespace` and the catalog digest are unchanged afterwards | no `read_target` | skip the external-reference query; skip the sequence-owner check | E2 |
| AT-E6 | `tests/connectors/test_postgres_target_plan.py` (pg): over-length varchar, unknown enum label, null into NOT NULL, numeric overflow, an int64 above the integer range, a float64 `1.5` into bigint, and a `timestamp[ns]` with a nanosecond part each refuse with `value_guard_failed` at `schema.table.column`; a blocked type refuses with `target_type_blocked`; no target write session opens (spy) | no `plan_target` | drop the sub-microsecond guard | E2 |
| AT-E15 | `tests/unit/publication/test_pg_publication_row.py`: the bookkeeping row reader refuses a missing or unknown `format`, `"op\n"` as operation id, uppercase hex, a 63-character `result_id` and a bool in a text column; the writer's row round-trips; schema snapshot | no reader | read `format` with `startswith` | E2 |
| AT-E7 | `tests/connectors/test_postgres_target_pipeline.py` (pg): a pipeline whose source and target references name the same database refuses `target_same_database` from `open_postgres_target`, and a spy on `stage_postgres_sources` and on the snapshot shows no call; a second database on the same server passes (negative control) | no probe | run the fingerprint compare after `stage_postgres_sources` || E3c |
| AT-E8 | `tests/connectors/test_postgres_target_publish.py` (pg): three tables with an FK chain, a `NOT VALID` FK, a deferrable FK, a serial key, an `ALWAYS` identity, a stored generated column, an enum, a partial index, an expression index, a unique, a check, and triggers in states `O` (audit), `D`, `R` and `A`. After publish: Arrow readback equals the staged Parquet for every non-generated column; generated values match the server's recomputation; FK definitions and `convalidated` equal the pre-run values exactly; index and other constraint OIDs are unchanged (never dropped); every trigger's `tgenabled` equals its pre-run value; the audit table is empty; identity kinds are unchanged; an `INSERT` with default keys succeeds on every table; `ANALYZE` ran; an injected `ANALYZE` failure still returns `published` | no publish | skip `sequences` (the default-key insert hits a duplicate key) || E3b |
| AT-E9 | same file (pg, timing cells `serial`): inject a fault at each of the thirteen steps and assert the failure-code registry result. Revoke a right while `truncate`, `load` and `sequences` are held and expect `target_privilege_missing`. Constraint cells cover a broken target-to-target FK (`target_constraint_failed`), a kept lookup FK (`target_load_failed`), and a `DEFERRABLE INITIALLY DEFERRED` lookup FK whose bad row fails during `load`, not `commit`. A duplicate key, a server-refused value and a sequence overflow get their registered codes. A load of more than 3,000,000 rows into a table with a lookup FK uses multiple statements of at most 1,000,000 rows, sums their affected counts, and succeeds. A test-only statement on the same writer backend records `sum(total_bytes)` from `pg_backend_memory_contexts` after each batch. Later samples must stay within 64 MiB of the first sample, so memory does not grow with the total row count. The PostgreSQL 16 test role gets `pg_read_all_stats` only in this cell. Deadline cells cover the whole deadline, the server-only bound, and the second bounded load statement. Lock cells cover an owned sequence lock and `SELECT FOR UPDATE` on a referenced lookup row. Both fail `target_busy` within `lock_timeout_s` plus 3 s. Plain lookup `SELECT` and non-key `UPDATE` continue during load. A server-side terminate before `COMMIT` gives `target_unreachable`. After every deadline and lock cell, our pid holds no lock within the bound. Each failure leaves every catalog, row, sequence and bookkeeping digest equal to its pre-run value | no publish | reset sequences with `setval`; remove `SET CONSTRAINTS ALL IMMEDIATE` (the deferred-FK cell reaches commit); remove the 1,000,000-row predicate (the statement-count and memory cells fail); map a load statement that reaches the lock timeout to `target_load_failed`; drop lookup FKs; set the statement cap once per step; map every step to one code | E3b |
| AT-E10 | same file (pg): during a publish a reader runs, in a loop under READ COMMITTED, one statement returning the counts of all three tables; every observed triple is the old triple or the new triple. Recording cell: a REPEATABLE READ transaction that took its snapshot before the commit and reads after it sees empty tables (asserted, so a change in PostgreSQL behaviour is noticed) | no publish | `TRUNCATE` and `COMMIT` before the load || E3b |
| AT-E11 | same file (pg): a subprocess publisher is SIGKILLed after the first table loads; within 5 s the target equals the pre-run state, its locks are gone and no `decoy_meta` row changed. A second publisher is SIGSTOPped inside the transaction with `idle_in_transaction_timeout_s=2`; its locks are gone within 2 s plus 3 s slack | no publish | omit `idle_in_transaction_session_timeout` || E3b |
| AT-E12 | same file (pg): retry with the same operation and result returns `already_committed` with no write (`n_tup_ins` unchanged); same operation, other result: `publication_operation_conflict`; a bookkeeping row changed after `read_target`: `delivery_pointer_moved`; an index added after `read_target`, and one added by a hook that runs between `check_marker` and `lock_tables`: `target_changed`; a second publisher holding the advisory lock and an application transaction holding a row lock: `target_busy` within `lock_timeout_s + 2` s; two first publishes into two schemas with `decoy_meta` absent both succeed (global creation key). A trigger created on a target table by a peer while our `lock_writer` waits behind a second publisher's advisory lock: `target_changed` from `capture`, the target unchanged, and the new trigger's `tgenabled` still `O` afterwards. Every refusal leaves the target unchanged | no publish | capture the structure before `lock_tables`; drop `ISOLATION_LEVEL 'READ COMMITTED'` from the write `ATTACH` (trigger cell red: the capture misses the trigger); use `DISABLE TRIGGER USER` (trigger cell red when the capture is also stale) || E3b |
| AT-E13 | same file (pg): the commit wrapper raises after a real `COMMIT` (`pg_xact_status` committed: `published`); raises instead of committing (aborted: `publication_commit_not_visible`, target unchanged); raises while the backend is held in progress (terminated through the guarded `terminate` of `_postgres_control.py`, then aborted: `publication_commit_not_visible`); raises and the reconcile connection times out against a blackhole address within `connect_timeout_s + 2` s (`target_commit_unknown`); the commit is attempted exactly once in every case | no reconcile | reconcile by reading the bookkeeping row || E3b |
| AT-E14 | same file (pg): a DSN with a marker password, a wrong host, a staged row carrying a marker string that breaks a unique constraint, a partial-index predicate and a check constraint that each contain a marker literal and fail during the run: the markers are absent from the error `str`, `repr`, formatted traceback with chains, every log record captured at DEBUG, the receipt and the type-map document; `pg_debug_show_queries` reads `false` on the session; every raised error has `__cause__` and `__context__` `None`; a `threading.excepthook` spy records nothing from any worker or control thread; two more marker-password cases: a worker abandoned while its connect hangs (seam), then failing later with the DSN-bearing connect error, and a control-session reopen that fails with it: the marker is absent from every channel above and the spy | no publish | raise `PostgresTargetError` inside the `except` block in one step; let the worker thread body re-raise (excepthook spy red) || E3b |
| AT-E17 | `tests/connectors/test_postgres_control.py` (pg, `serial`). Drives `run_supervised` with raw step lists and fault seams: (1) Ctrl-C during a held statement triggers cancellation; a second press is recorded, not raised, and exactly one `KeyboardInterrupt` follows. (2) A blocked initial control open gives `target_unreachable` within `control_open_budget_s`, with no write open or SQL. (3) After the server bound is lifted and a peer kills the control session, the deadline causes one reopen and cancellation. If reopen blocks, the server bound ends the statement on schedule. (4) Wrong-xid and ended-transaction signals match no backend. (5) For blocked cancel, terminate, probe and status calls, the first overrun marks the session dead, the next required call uses the single reopen, and no later call reopens. Each wait equals `min(budget, time left in its trigger-anchored window)`. The reopen cannot extend the cancel, terminate or reconcile window. (6) A cancel between statements stops the next statement. (7) A peer terminate gives `target_unreachable`. (8) An exception after the trigger still leaves `stop` set. (9) Sentries restrict backend signals to `_postgres_control.py`, restrict `ControlSession` to the supervisor, and permit only `Deadline.arm_expiry_only` on the publish path. A spy proves that this arm sets `expired` without calling `conn.interrupt()` | no control module | drop the xid guard; open control after write; reuse a timed-out session; start a reopen window after the failed call; call control inline; set `stop` after the lock; call the interrupting deadline arm | E3a |
| AT-E18 | `tests/connectors/test_postgres_target_supervised.py` (pg, `serial`), the publish under the supervisor: (1) Ctrl-C during a slowed `load` raises `KeyboardInterrupt` within the bound, with unchanged digests and no lock from our pid. (2) A trigger during `COMMIT` sends no backend signal and uses reconcile. (3) Two Ctrl-C presses during `COMMIT` never raise `KeyboardInterrupt`; the second is recorded. (4) A userspace TCP proxy keeps ACKing client traffic but stops forwarding during `load`. `publish_target` returns `deadline_exceeded` within the item 9 bound. The cell asserts only that the supervisor stops waiting. It does not assert child-process exit, server cleanup or target state until the proxy releases. A separate CLI seam holds an abandoned daemon at shutdown and proves the CLI flushes output and logs, closes its run `ExitStack`, then uses `os._exit` with the selected code. (5) A worker that ignores cancel and terminate returns on schedule, then rolls back without commit when released. (6) The write `ATTACH` carries READ COMMITTED and keepalives. (7) With no prior deadline or Ctrl-C trigger, hold reconcile after a commit error, press Ctrl-C, and prove the entry-installed handler records it as the trigger. The result comes from reconcile, never an escaping `KeyboardInterrupt`, the press does not extend the original reconcile window, and the old handler is restored. (8) A blocked write-session open gives `target_unreachable` within `write_open_budget_s`; a late open closes without `BEGIN`, and no target SQL or lock exists | no supervised publish | skip the stop check before commit; signal while committing; install the SIGINT handler only after a trigger; restart the reconcile window on Ctrl-C; omit the write-open budget; claim normal interpreter shutdown for an abandoned daemon | E3b |

### 8.2 CLI

| Id | Test | Red because | Mutation that must turn it red | Slice |
|---|---|---|---|---|
| AT-C1 | `tests/e2e/postgres_target/test_run_postgres_target.py` (pg): `decoy run` from CSV sources and from Postgres sources into a Postgres target exits 0; the target rows equal the Parquet of the same run with file targets; pandas-route cells: a nullable integer column (float64 in Parquet) into `bigint`, a timestamp column (`timestamp[ns]`) into `timestamp`, an int64 into `integer` all publish; no `decoy-*` scratch remains; the card shows the type-map summary; `--json` carries `postgres_target`; a post-scan block exits 4 and the target is unchanged | no stage | publish before the post-scan verdict | C1 |
| AT-C2 | same folder (pg): `--chunked` gives target rows equal to the plain run | no stage | place the chunked writer at a non-scratch path | C1 |
| AT-C3 | same folder (pg): unset reference env var (1), missing privilege (1), blocked type (1), guard failure (1), unreachable host (3), constraint failure (3), busy (3): each with its code; the target is unchanged; stderr, `--json`, the run folder and captured logs hold no DSN marker, no reference text and no data marker | no wiring | map `PostgresTargetError` through `str(exc)` into the error line | C1 |
| AT-C4 | `tests/e2e/postgres_target/test_compile_refusals.py`: `best_effort`, mixed targets and two schemas exit 1 from `decoy validate` and `decoy run` with their codes; `decoy validate` opens no socket (socket spy) | no check wiring | open the target in `validate` | C1 |
| AT-C5 | same folder (pg): SIGINT during `load` exits 130 with the target unchanged and no scratch; a SIGINT injected right after the commit records the run as delivered | no stage | treat a post-commit interrupt as not delivered | C2 |
| AT-C6 | `tests/unit/test_exit_code_for.py`: walks every new connector target code from the registry; each `CONFIGURATION` code on a `PostgresTargetError` maps to 1 and each `EXECUTION` code to 3; `PublicationRefused(delivery_pointer_moved)` maps to 3; the run classifier agrees; no target code string appears in the CLI source (grep cell) | outcomes not on the specs | set `target_type_blocked` to `EXECUTION` | C1 |
| AT-C7 | `tests/e2e/postgres_target/test_non_run_callers.py`: `decoy.mask()`, `demo`, `tokenize`, `subset`, `report fidelity --config` and each other command the C1 builder finds reading `targets:` (listed in the test) exit 1 with `target_postgres.unsupported_command` and never connect | no refusal | remove the postgres arm in `_require_local_io_endpoints` | C1 |
| AT-C8 | same folder (pg): a missing target relation refuses at prepare and a spy on the source reader shows no row read | no prepare call | open the target after the run | C1 |
| AT-C9 | `tests/e2e/release_freeze/test_json_shapes.py` (snapshot updated) and the shape changelog check: the `postgres_target` key is recorded | key not in snapshot | drop the shape changelog entry | C2 |
| AT-C10 | `tests/e2e/postgres_target/test_flag_refusals.py`: `--resume` with a Postgres target whose DSN points at a closed port exits 1 with the flag refusal, and a socket spy sees no connection attempt | no refusal | drop the target arm of the refusal | C1 |

## 9. Placement

Engine (rows of `CODEMAP.md` "Where Things Go"; `execution/` gets no new top-level file; the
package root is at its fan-out cap and gets no new module):

| File | New or changed | CODEMAP row | Sits beside |
|---|---|---|---|
| `src/decoy_engine/config/_targets.py` | changed (`PostgresTarget`, union, identity arm) | Config models | `S3Target`, `GCSTarget` |
| `src/decoy_engine/plan/checks/_postgres_targets.py` | new | Plan compile and checks: `plan/checks/_<topic>.py` | 64b `plan/checks/_postgres_sources.py` |
| `src/decoy_engine/connectors/_postgres_session.py` | changed (adds `open_write_session` and `Deadline.arm_expiry_only`; module created by 64b E1, merged #624) | Connectors (private helper of the package) | `postgres_snapshot.py` |
| `src/decoy_engine/connectors/postgres_catalog.py` | changed (adds `server_fingerprint`; module created by 64b E1, merged #624) | Connectors | `postgres_snapshot.py` |
| `src/decoy_engine/connectors/postgres_typemap.py` | new | Connectors: `connectors/<name>.py` | `postgres_snapshot.py` |
| `src/decoy_engine/connectors/postgres_target_catalog.py` | new (catalog SQL, `capture_structure`, bookkeeping row declaration) | Connectors | `postgres_catalog.py` |
| `src/decoy_engine/connectors/postgres_target.py` | new (config, error, `read_target`, `plan_target`, guards) | Connectors | `postgres_snapshot.py` |
| `src/decoy_engine/connectors/postgres_target_publish.py` | new (step table, `publish_target`, reconcile) | Connectors | `postgres_target.py` |
| `src/decoy_engine/connectors/_postgres_control.py` | new (revision 4: `ControlSession`, guarded `cancel` and `terminate`, `probe`, `run_supervised`) | Connectors (private helper of the package) | `_postgres_session.py` |
| `src/decoy_engine/connectors/__init__.py` | changed (exports) | Connectors | itself |
| `src/decoy_engine/execution/pipeline/_postgres_target.py` | new | Pipeline spine: `execution/pipeline/` | 64b `execution/pipeline/_postgres_source.py` |
| `src/decoy_engine/delivery/_plan.py` | changed (one token) | (delivery package, DELIV E1a) | itself |
| `src/decoy_engine/reasons/config/_part2.py`, `src/decoy_engine/reasons/connector/_part1.py` | changed (new codes with outcomes) | Reason codes | existing catalogs |
| `src/decoy_engine/__init__.py` | changed (exports, frozen-surface rows) | Public API | facade list |
| `tests/connectors/test_postgres_write_spike.py`, `test_postgres_typemap_roundtrip.py`, `test_postgres_target_inspect.py`, `test_postgres_target_plan.py`, `test_postgres_target_pipeline.py`, `test_postgres_target_publish.py`, `test_postgres_control.py`, `test_postgres_target_supervised.py` | new | `tests/connectors/` (listed exception) | snapshot suites |
| `tests/unit/config/test_postgres_target.py`, `tests/unit/plan/test_postgres_target_check.py`, `tests/unit/connectors/test_postgres_typemap.py`, `tests/unit/publication/test_pg_publication_row.py` | new | Unit tests mirroring `src/` | owning package tests |
| `tests/sentry/test_postgres_session_choke_point.py` | new (64b E1 merged no session sentry) | Sentry test | `tests/sentry/test_file_access_boundary.py` |
| `.github/workflows/ci.yml` (`pg-gate` file list), `tests/sentry/file_access_modules.toml`, `tests/sentry/file_access_registry.toml`, physical-seam allowlist | changed (new marked files; one exact `(path, name)` row per new module) | CI lane registries; sentry registries | existing rows |
| `docs/postgres-target.md`, `docs/index.md`, `changelog.d/f01-e1.md`, `changelog.d/f01-e2.md`, `changelog.d/f01-e3a.md`, `changelog.d/f01-e3b.md`, `changelog.d/f01-e3c.md` | new or changed | Feature docs; changelog fragments | `docs/publication.md`, 64b `docs/postgres-source.md` |

`connectors/` holds 7 modules today plus 64b's two or three; six new modules (five plus
`_postgres_control.py`) keep it under any fan-out concern. A connectors sub-package was considered and rejected: the map names
`connectors/<name>.py`.

CLI (flat `src/decoy/cli/` gets no new file):

| File | New or changed | CODEMAP row | Sits beside |
|---|---|---|---|
| `src/decoy/cli/io/_postgres_target.py` | new (`PostgresTargetStage`, `PostgresOutput`) | Source readers and target writers: `src/decoy/cli/io/` | DELIV `io/_delivery.py`, 64b `io/_postgres.py` |
| `src/decoy/cli/io/__init__.py`, `src/decoy/cli/io/_delivery.py` | changed (export; stage construction for the postgres kind; `PublishedOutput` arm) | same | facade |
| `src/decoy/cli/run/_prepare.py` | changed (open the target on the `ExitStack`; `--resume` target arm) | `decoy run` internals | 64b staging block |
| `src/decoy/cli/run/_execute.py` | changed (`_require_local_io_endpoints` arm) | `decoy run` internals | cloud refusal |
| `src/decoy/ui/summary.py` | changed (type-map card lines) | Terminal output | run card extras |
| `pyproject.toml` (pin), `.github/workflows/ci.yml` (`pg-gate` file list) | changed | CI and lane policy | 64b rows |
| `tests/e2e/postgres_target/` (conftest reusing 64b's `pg_dsn`, `ext_dir`, `DECOY_REQUIRE_PG`) | new folder | map change in C1: add it to the tests cell of the Source readers and target writers row | `tests/e2e/postgres_source/` |
| `docs/guides/postgres-target/README.md`, README target list, CHANGELOG, shape changelog, `docs/ROADMAP.md` row 86 and shipped log, `docs/qa/cli-v1-checklist.md` rows | new or changed | User guides; roadmap; QA checklists | `docs/guides/postgres-source/` |

## 10. Design notes

- Principles. One place per fact: the identifier rule and session setup in
  `_postgres_session.py` (64b); the structure read in `capture_structure`, used by inspection and
  publish alike; the type rules in `postgres_typemap.py`; the bookkeeping row declaration in
  `postgres_target_catalog.py`; the exit class on each reason spec; the exit map in
  `exit_code_for`. Dependency direction by layer: `config` stays shape-only; `connectors` takes
  a resolved `SecretStr` and knows nothing of pipelines; `execution/pipeline` resolves
  references; the CLI calls only public names. Typed context objects (`PostgresTargetConfig`,
  `TargetCatalog`, `TargetPlan`) instead of long parameter lists. No flag argument: read-only
  and read-write sessions are two named functions.
- Pattern followed: pg_restore data-only single transaction, pgloader's truncate,
  foreign-key and sequence steps with a transactional restart (section 2). Publish steps are a
  fixed ordered table of named steps, each with its own failure code, so the order is a visible
  table edit and the fault seam addresses steps by name.
- New structure: one target adapter. A second database later adds its own adapter beside it;
  nothing generic is built now (the DELIV `SinkStage` protocol is already the seam).
- Choke points.
  - Database writes. Only `postgres_target_publish.py` calls `open_write_session`, the only
    read-write `ATTACH`. Guard AT-E4; mutation: call it from `postgres_target.py`.
  - Pre-write inspection. `open_postgres_target` is the only way to a `PostgresTargetHandle`, and
    `publish` takes a `TargetPlan` that only `plan_target` builds from a `TargetCatalog`. Guard
    AT-E6, AT-C8; mutation: run the guards after the write session opens.
  - Structure capture. `capture_structure` is the one reader; the publish re-runs it under the
    locks. Guard AT-E12; mutation: capture before `lock_tables`.
  - Non-run callers. `_require_local_io_endpoints` (CLI I/O choke point). Guard AT-C7; mutation:
    drop the postgres arm.
  - Value-free errors. Every step raises after its `except` block closes and reads only the
    exception type. Guard AT-E14; mutation: raise inside the block.
  - Backend signals. Only `_postgres_control.py` calls `pg_cancel_backend` or
    `pg_terminate_backend`, and only through the `pid` plus `backend_xid` guard. Guard AT-E17
    cell 9 and cell 4; mutation: drop the `backend_xid` condition.
  - Session bounds. Every session's ATTACH goes through S2's one ATTACH site and its one DSN
    helper (connect timeout, keepalives, `tcp_user_timeout`). Guard S2's
    `test_type_postgres_attach_has_one_site` plus the AT-E4 spy cell; mutation: build the write
    ATTACH from the raw DSN.
  - Step failure codes. One registry keyed by step name in `postgres_target_publish.py`; no
    code literal elsewhere in the module. Guard AT-E9 per-step code cells; mutation: map every
    step to one code.
  - Thread bodies. Every worker and control-call thread body catches `BaseException` and keeps
    only the type name. Guard AT-E14 excepthook spy; mutation: let the worker body re-raise.
- Supervisor pattern (revision 4): psycopg 3's cancel from a second connection while the
  calling thread waits, plus PgBouncer-style outside cancellation (section 2). The worker and
  supervisor share one small state object (`stop`, `committing`, one lock), not loose flags.

## 11. Size

Engine: 6 new modules (`postgres_typemap.py` about 330, `postgres_target_catalog.py` about 420,
`postgres_target.py` about 330, `postgres_target_publish.py` about 580 (step table, failure-code
registry, worker body, reconcile), `_postgres_control.py` about 360 (control session, guarded
signals, per-call budget threads, supervisor, whole-call SIGINT recording), `execution/pipeline/_postgres_target.py`
about 170), 7 changed modules (about 240 lines, including `open_write_session` about 60,
`Deadline.arm_expiry_only` in the existing timer core, the S2 helper's keepalive keywords about
15 and `server_fingerprint` about 30), 12 new test files
(about 2,400 lines), one doc page. New public names: the sixteen in section 6.

CLI: 1 new module (about 220), 5 changed modules (about 110), one test folder (about 750 lines),
one guide.

Module size (engine `tests/sentry/test_module_size.py`, aim 600, hard 700; CLI cap 800): every
new engine module stays under 600. A build more than 30 percent over these numbers stops and
explains before review.

## 12. Slices

Fewer, larger, behaviour-changing slices. The spike is first and alone; prep goes in E1;
engine docs in E3c; CLI docs in C2. Source lines below are product source only; tests are
listed separately.

| Slice | Repo | Content | Risk | Src lines | Test lines | Acceptance tests | Depends on | Test depth notes |
|---|---|---|---|---|---|---|---|---|
| E0 | engine | Spike (PR #667): `test_postgres_write_spike.py` with raw DuckDB calls, `pg-gate` file list row, a record of each cell's result in `docs/records/2026-11-18-f01-e0-spike.md`. Revision 4 adds to the open PR: cell e as a strict recording cell, cell e3 (five sub-cells, e3.5 added in revision 5), the record's verdict updated to the new mechanism. No product code | R1 (test only; result gates E1) | 0 | ~300 plus ~150 | AT-E0 | 64b E1 merged (lane, extension in CI) | `pg-gate` green with zero skips on the final head (cell e no longer red); the cell-a and e3 mutations run on CI and are recorded; if e3 fails, E1 does not start and the deadline design goes back to the planner |
| E1 | engine | `open_write_session` in 64b's `_postgres_session.py`, its ATTACH built through S2's single site and helper with `ISOLATION_LEVEL 'READ COMMITTED'`; S2's helper extended in place with the keepalive and `tcp_user_timeout` keywords (S2's AT-B2 expected strings updated); `PostgresTarget` and the identity arm; `plan/checks/_postgres_targets.py`; `postgres_typemap.py` with the three-step fold and the report document; config and connector codes with outcomes (`since=UNRELEASED`); `DELIVERABLE_TARGET_TYPES` token; engine target writer dispatch refusal (`target_postgres.unsupported_command`); choke-point sentry; `pg-gate` file list; changelog fragment | R2 (shared connector code, config union, codes) | ~620 | ~650 | AT-E1, AT-E2, AT-E3, AT-E4, AT-E16 | E0 (#667) merged with e3 green; capped-worker S2 merged; 64b E1 and E2 merged; DELIV E1a (merged) | config serializer and shared connector module: full suite once on the slice head, diffed against the saved main baseline; `pg-gate` green |
| E2 | engine | Read-only half: `postgres_target_catalog.py` (catalog SQL, `capture_structure`, digest, sequence and privilege checks, bookkeeping row declaration and strict reader with its snapshot), `postgres_target.py` (`read_target`, `plan_target`, value guards); changelog fragment | R2 (data handling, secrets) | ~760 | ~550 | AT-E5, AT-E6, AT-E15 | E1 | T1 plus `pg-gate`; mutations on the reader and the guards |
| E3a | engine | Control and supervision: `_postgres_control.py` (control session, guarded cancel and terminate, probe with the privilege re-check query, per-call budget threads, `run_supervised` with `stop`, `committing`, whole-call SIGINT recording); `_postgres_session.py` adds `Deadline.arm_expiry_only` on the existing timer core; file-access and physical-seam registry rows; `pg-gate` file list; changelog fragment `changelog.d/f01-e3a.md`. 2 production modules plus registries | R2 (concurrency, signals to database backends, value leaks) | ~360 | ~550 | AT-E17 | E2 | sentry registries and CI lane list (test config trigger): full suite once on the slice head against the saved baseline; `pg-gate` green; every AT-E17 mutation re-run on the final head |
| E3b | engine | Write path: `postgres_target_publish.py` (thirteen steps, per-statement `SET LOCAL` bounds, failure-code registry, worker body, rollback, `pg_xact_status` reconcile, `ANALYZE`); `pg-gate` file list; changelog fragment `changelog.d/f01-e3b.md`. 1 production module | R2 (destructive database write, publication, value leaks) | ~580 | ~1,250 | AT-E8, AT-E9, AT-E10, AT-E11, AT-E12, AT-E13, AT-E14, AT-E18 | E3a | CI lane list (test config trigger): full suite once on the slice head against the saved baseline; `pg-gate` green; every E3b mutation in section 8 re-run on the final head |
| E3c | engine | Pipeline and public surface: `server_fingerprint`; `execution/pipeline/_postgres_target.py`; `connectors/__init__.py` and `decoy_engine/__init__.py` exports and frozen-surface rows; `docs/postgres-target.md` (the abandoned-worker note of 4.4.2; `pg-gate` runs on Linux only; `tcp_user_timeout` is Linux only, keepalives elsewhere; on Windows an abandoned worker can hold a staged Parquet file open, so scratch removal tolerates it), `docs/index.md`; changelog fragment `changelog.d/f01-e3c.md` | R2 (frozen surface, source-before-target ordering) | ~250 plus docs | ~200 | AT-E7 | E3b | frozen surface: full suite once on the slice head against the saved baseline; `pg-gate` green |
| REL | engine | Engine release 0.29.0 through the daily release train; the release commit stamps the new codes, `REGISTRY_VERSION` and the manifests | R1 | small | none | release checks | E3c; 0.28.0 (64b) cut | release train rules |
| C1 | CLI | Repin to 0.29.0 (engine repin checklist); `io/_postgres_target.py` stage and `PostgresOutput`; `_delivery.py` stage construction; prepare-time `open_postgres_target` and the `--resume` target arm; non-run refusal arm; card summary and `--json` key; `pg-gate` file list; CODEMAP tests cell | R2 (data handling, version pin, CI) | ~330 | ~650 | AT-C1, AT-C2, AT-C3, AT-C4, AT-C6, AT-C7, AT-C8, AT-C10 | REL; DELIV C2a merged (`SinkStage`, `PublishedOutput`, placer); 64b C1 and C2 merged | version pin and test config: full suite on the slice head against the saved main baseline; `pg-gate` green |
| C2 | CLI | Interrupt handling at the visibility point and `target_commit_unknown` message; scratch removal on Windows tolerates a staged Parquet file still held by an abandoned worker (warning with the path kind only, removed on the next run's scratch sweep); shape changelog and snapshot; user guide `docs/guides/postgres-target/` (target preparation with `pg_dump --schema-only`, PostgreSQL 13 minimum, privileges, `decoy_meta` SQL for a DBA, what READ COMMITTED and REPEATABLE READ readers see, refreshing materialized views, WAL size), README, CHANGELOG, QA checklist rows, roadmap row 86 to DONE and shipped log | R2 (interrupt semantics on a destructive write) | ~120 plus docs | ~150 | AT-C5, AT-C9 | C1 | T1 plus `pg-gate` |

Every slice is under about 800 source lines and 10 production files. Order: E0 (#667 with e3),
capped-worker S2, E1, E2, E3a, E3b, E3c, REL, C1, C2. If the release train cuts 0.29.0 before
E3c merges, the engine half ships in the first release after E3c. One writer per
worktree, never two. C1 merges after the DELIV CLI slices that edit `io/_delivery.py`,
`run/_prepare.py` and `run/_execute.py` (DELIV writer table, section 10) and after 64b C1 and C2
(they edit `run/_prepare.py` too).

Each slice: T0 per edit, T1 per commit, T2 at the gate with the slice's mutations re-run on the
final head (class 9). Reviews: R2 slices get Dennis then Codex; E0 and REL get Codex only.
Commit subjects follow Conventional Commits with the final line `cam` and no other trailer.

## 13. Recurring-defect class check

| Class | Recurring defect | Plan evidence |
|---|---|---|
| 1 | Anchored validation | identifiers through the one `fullmatch` rule; bookkeeping reader `fullmatch`es every field; AT-E2 and AT-E15 have `"\n"` cells |
| 2 | Strict wire and stored types | `PostgresTarget`, `PostgresTargetConfig`, settings and the bookkeeping row use strict types; AT-E1 and AT-E15 feed bools and ints |
| 3 | No exception context | every step raises after its `except` closes; AT-E14 asserts `__context__ is None` |
| 4 | Versioned read models | `decoy-pg-publication/v1` row: exact tag, unknown tag refused, one declaration for writer and reader (AT-E15); `decoy-pg-type-map/v1` is write-only with a schema snapshot (AT-E3) |
| 5 | Normalized guard scanners | AT-E4 scans source text for `open_write_session` calls and `ATTACH` without `READ_ONLY`, with seeded cells for single and double quotes and an f-string; deliberate evasion is V2-LOG |
| 6 | No private-module imports | the CLI imports only `decoy_engine` public names and the `decoy.cli.io` facade; `_postgres_session` is imported only inside `connectors` |
| 7 | No hidden CI failures | `pg-gate` from 64b (no `continue-on-error`, `junit_ran.py`); the new marked files join its file list, so the scope guard fails if one is left out |
| 8 | One input, one trust class per entry point | user-chosen relation names go through the identifier rule; staged Parquet paths are program-built and never user input; SQL literals for paths go through `sql_literal`; definition text comes only from the target's own catalog |
| 9 | Mutations on the final head | every slice reruns its section 8 mutations after its last change and records the head |
| 10 | Allowlisted helpers are still checked | new modules get exact `(path, name)` rows in the file-access and physical-seam registries; their callers stay checked |
| 11 | No raised caps | no cap, pin ceiling, ratchet or baseline is raised; a module near its size cap is split |

## 14. Plan defect catalog classes

| Class | Defect | Closing structure | Sentry or property test | Seeded mutation | Slice |
|---|---|---|---|---|---|
| 1 | Value exposure (DSN, row values in server error text, literals in definition text, reference text) | exception type only, raise outside `except`, guards return counts, definitions never logged, `pg_debug_show_queries` off, report holds names and types | AT-E14, AT-C3 | raise inside the `except` block; forward `str(exc)` | E3b, C1 |
| 2 | Cleanup on every exit (target and scratch) | one transaction with transactional sequence restarts, rollback on any failure, idle-in-transaction timeout; server-side per-statement timeouts and the control-session cancel bound every exit, and `COMMIT` is never sent after a trigger; scratch on the run `ExitStack` | AT-E9, AT-E11, AT-E17, AT-E18, AT-C5 | reset sequences with `setval`; skip the `stop` check before `COMMIT`; allocate scratch without a scope | E3a, E3b, C2 |
| 3 | State completeness (every step and every outcome covered) | fixed step table; every step has a fault cell; every reconcile status has a cell; every row of the 4.4.3 code table and every supervisor state (`stop`, `committing`) has a cell | AT-E9, AT-E12, AT-E13, AT-E17, AT-E18 | delete one step's fault handler; cancel without checking `committing` | E3a, E3b |
| 4 | Route coverage | all routes write through the sink placer into the same scratch; pandas-route types classed; `--resume` and non-run callers refused | AT-C1, AT-C2, AT-C7, AT-C10 | place only on the plain route | C1 |
| 5 | Referential integrity across target tables | FKs between target tables dropped before and re-created as they were after the load in one transaction; FKs to lookup tables kept and checked row by row during the load; external FKs refused | AT-E8, AT-E9, AT-E5 | skip FK re-creation; skip the external-reference check | E2, E3b |
| 6 | Untrusted input (relation names, secret material, catalog text) | the one identifier rule; `postgres-dsn-v1`; captured definitions executed only under `search_path = pg_catalog` | AT-E2, AT-E8 | allow `.` in identifiers; drop `SET LOCAL search_path` | E1, E3b |
| 7 | TOCTOU check-then-use between inspection and publish | locks taken first, then structure captured and compared under the locks; bookkeeping row read `FOR UPDATE` | AT-E12 | capture before `lock_tables` | E3b |
| 8 | Weak proof of "nothing written" and "all restored" | catalog digest, row digests, sequence state and `pg_stat_user_tables` counters, not only a code; FK, index OID and trigger state compared before and after | AT-E5, AT-E8, AT-E9 | assert only the error code | E2, E3b |
| 9 | Refactor drift (second copy of the connection or identifier code) | session helpers live once in 64b's `_postgres_session.py`; F01 adds only `open_write_session`; exit class derived from the registry | AT-E4, AT-C6 | keep a literal target code list in the CLI | E1, C1 |
| 10 | Frozen contract drift | additive union member; existing receipt tokens; schema snapshots for the two new formats; exit map derived and walked | AT-E3, AT-E15, AT-C6, AT-C9 | add a receipt outcome token; change an exit integer | E1, E2, C1 |

## 15. Pre-mortem

- DuckDB runs some statement on a pooled connection outside the open transaction, so a
  `TRUNCATE` or a sequence restart commits on its own. E0 is its own slice before any product
  code; a failed design cell stops the row and goes to the owner (Q15).
- A captured definition text resolves to a different object when re-executed: the capture runs
  inside the locked publish transaction under `SET LOCAL search_path = pg_catalog`, and the
  re-create runs in the same transaction with the same search path, so every name is
  schema-qualified as pg_dump writes it (H5). The inspection reads with the same function and
  search path, so the digests compare like with like.
- A publish holds `ACCESS EXCLUSIVE` for minutes and the application queues behind it. That is
  the stated V1 trade (Q1); the guide says so, and `lock_timeout_s` stops the publisher from
  queuing behind a long application transaction.
- Loading with unique indexes in place is slower than drop and re-create on very large tables:
  accepted for V1 (H6); index dropping is a V2-LOG speed-up.
- Large loads fill WAL inside one transaction. Documented capacity note in the guide.
- The masked data breaks a target FK to an untouched lookup table. Step 1 makes the constraint
  immediate, so the bounded insert fails in `load` with `target_load_failed` and rolls back.
  If the check waits at least `lock_timeout_s`, it fails `target_busy`. The guide tells the user
  to add the lookup table to the pipeline as passthrough.
- A builder reads the PostgreSQL error message to classify a failure "more precisely": AT-E14
  plants values in a unique violation, a partial index and a check and fails on any leak; the
  reviewer checks that only exception type names are read.
- A builder weakens AT-E9 to check one table or skips the sequence state: the gate checks that
  the catalog digest, every table's row digest, every owned sequence's state and the
  bookkeeping row are compared for every step.
- A builder reaches for `setval` because it is simpler: AT-E9's mutation turns it red.
- A builder trusts `Deadline`'s `interrupt()` for the write path because the read side does:
  E0 cell e records that it does nothing to an extension statement, and AT-E9's
  cancel-disabled deadline cell and AT-E17 fail without the server-side bounds and the control
  session.
- The cancel lands on someone else's backend after a pid is reused: the `backend_xid` guard
  matches only our open transaction (AT-E17 cell 4).
- A cancel or terminate arrives while `COMMIT` is in flight and the outcome is guessed: the
  supervisor never signals once `committing` is set, and reconcile reads `pg_xact_status`
  (AT-E17 cell 5).
- A builder reads the SQLSTATE out of the DuckDB error text to tell a lock timeout from a
  statement timeout: the 4.4.3 table decides from the step and the elapsed time instead, every
  lock wait is moved into a lock step so the step alone names it, and the reviewer checks that
  only exception type names are read.
- The pandas mask route writes types the first draft classed lossy: AT-C1 runs the default route
  end to end.
- DELIV C2a slips: C1 cannot merge without the `SinkStage` protocol. The engine half still ships
  in 0.29.0 and the CLI half waits; no interim CLI path is built.
- 64b E1 changes the session module's names during review: resolved. 64b E1 merged (#624) and
  this plan cites the merged names. E0 can start; E1 waits on 64b E2 for `POSTGRES_DSN_V1`.
- `decoy_meta` is absent and the role has no `CREATE` on the database (or it is present and the
  role lacks `USAGE`, or `CREATE` on it when the table is absent): refused at inspection, and the
  guide gives the DBA the statements to create the schema and table once and grant the rights.

## 16. Owner questions (each taken on the recommended answer and recorded)

| # | Question | Recommended answer, taken |
|---|---|---|
| Q1 | Publish method: one transaction in place, or a staging schema with a rename swap? | One transaction in place (pg_restore `--single-transaction`, pgloader steps). "Staging" in V1 is the locally staged masked Parquet plus the uncommitted transaction. Readers wait during the load. The guarantee covers statement-level READ COMMITTED readers; a REPEATABLE READ or SERIALIZABLE snapshot taken before the commit sees empty tables after it (`TRUNCATE` is not MVCC-safe), stated in the guide (B2). The schema swap is V2 |
| Q2 | Which write modes in V1? | `replace` only, required and explicit in each target. The target structure must exist (migrations or `pg_dump --schema-only`). `create`, `append` and `upsert` are V2 |
| Q3 | How many target connections and schemas per pipeline, and can Postgres targets mix with file or cloud targets? | One connection, one schema, no mixing in V1, because one transaction is the atomic unit |
| Q4 | `best_effort` delivery with a Postgres target? | Refused at compile time; strict only |
| Q5 | Same-database guard | Refuse when the target and any Postgres source are the same database (same reference text at compile time; same server fingerprint from a catalog-only probe before any source row at run time). A second database on the same server is allowed |
| Q6 | User triggers during the load | Disabled by name from the capture (revision 5; was `DISABLE TRIGGER USER`) and restored to their exact prior `tgenabled` state before commit, inside the transaction; needs table ownership, not superuser |
| Q7 | Sequence values after the load | Owned sequences and identities restart at `max(column) + 1` (the start value when the table is empty or `max + 1` is below the minimum) with the transactional `ALTER SEQUENCE ... RESTART WITH` or `ALTER TABLE ... ALTER COLUMN ... RESTART WITH`, computed in a server-side `DO` block; never `setval` (B1). A restart above the maximum fails the run. Non-owned `nextval` defaults, shared sequences and negative increments are refused at inspection |
| Q8 | Lossy conversions | Always block in V1. No approval list; a later row can add one |
| Q9 | Unsupported target objects in V1 | Partitioned tables, inheritance, rewrite rules, FORCE RLS, foreign keys from non-target tables and the unusual sequences of Q7 are refused before writing. Views keep working (OIDs unchanged). Materialized views are not refreshed |
| Q10 | Backup, confirmation and preview before a destructive write | No automatic backup, no prompt, no separate preview command. The explicit `mode: replace` per table is the authorization; the read-only inspection runs on every run before any row is read and the card names the target. A preview command is a follow-up row |
| Q11 | Where the publication record lives | `decoy_meta.publications` in the target database, created on first publish under a global advisory key when the role may (database `CREATE` if the schema is absent, `CREATE` on `decoy_meta` if only the table is absent); otherwise a DBA creates it once from the guide's SQL. Fixed schema name in V1 |
| Q12 | Where the type-mapping report goes | Run card summary, `--json` key `postgres_target.type_map` with the engine document `decoy-pg-type-map/v1`; no new file in the run folder |
| Q13 | Which engine release carries the engine half | 0.29.0, the release after 64b's 0.28.0, or the first release cut after E3c merges |
| Q14 | `ANALYZE` after the publish | Yes, after commit; a failure is a warning, never a failed run |
| Q15 | If E0 shows DuckDB cannot hold every step in one PostgreSQL transaction | E1 does not start. Switching to psycopg 3 is an **owner decision**: it adds a dependency (supply-chain approval), re-costs E3 (a different session, cursor and error model) and re-derives the type map (the middle DuckDB step goes away and psycopg adaptation replaces it). The plan is amended only after that decision; no silent fallback. Revision 4: not triggered. E0 cells a, b, d, f, g, i and j hold the one-transaction design; only the deadline assumption (cell e) failed, and it is replaced with in-repo mechanisms that need no new dependency (4.4.1, 4.4.2). If cell e3 fails, the deadline design returns to the planner before this question is reopened |
| Q16 | Timeouts | Statement 3600 s capped per statement by the remaining deadline, whole publish 21600 s, lock wait 30 s, idle in transaction 60 s, libpq connect 10 s, control and write open budgets 15 s, cancel grace 10 s, commit grace 30 s, control statements 5 s. Every post-trigger wait is capped by its trigger-anchored window. No config override in V1 |
| Q17 | Minimum target server | PostgreSQL 13 (`pg_current_xact_id` and `pg_xact_status` with `xid8`); refused below. `client_connection_check_interval` is set only on 14 and later |
| Q18 | Drop and re-create indexes for load speed? | No in V1 (H6 ruling): only foreign keys are dropped; indexes and primary key, unique and exclusion constraints stay in place. Index dropping is a V2-LOG speed-up |
| Q19 | `--resume` with a Postgres target | Refused in V1, exit 1, matching 64b; the same landing rule as 64b (whichever of F01 C1 and the F23 `--resume` CLI half lands second adds the refusal and test) |
| Q20 | **Open, owner.** The 64b read side (`snapshot_tables_to_parquet`, `read_target` inspection) also uses `Deadline`'s `interrupt()`, which E0 cell e shows does nothing to an extension statement. Its statements are bounded only by `pg_statement_timeout_millis` (the per-statement cap, not the session deadline), and a Ctrl-C during a long source scan waits for that cap. Fix it now or later? | Recommended: a separate V1 fix row after F01 E3a merges, moving the read session onto `_postgres_control.run_supervised` (one cancel mechanism, no copy) and setting `pg_statement_timeout_millis` to min(cap, remaining deadline). Not folded into F01: it changes 64b's tested read path and has its own acceptance cells. Until then the read-side deadline is the per-statement cap plus S2's connect bound |

## 17. Unresolved

- E0 (revision 4): cells a, b, c, d, f, g, i and j passed on `pg-gate` run 44238850218; cell e
  failed and is now a recording cell; cell e3 (the new deadline mechanism, five sub-cells with e3.5 from revision 5) is not yet run.
  E1 starts only after #667 merges with e3 green and S2 has merged.
- The connect-timeout mechanism (E0 cell h): settled. S2's `with_connect_timeout` appends
  libpq `connect_timeout` to the DSN text at the one ATTACH site; `PGCONNECT_TIMEOUT` is
  rejected (S2 2.3). If S2's AT-B3 user-value cell fails (the extension keeps the first
  `connect_timeout`), S2's fallback applies to F01 unchanged.
- Q20 (read-side deadline) is open for the owner.
- Process exit with an abandoned worker: AT-E18 cell 4 proves only that the supervisor stops
  waiting. The CLI-only shutdown cell proves the fallback. The CLI flushes output and logs,
  closes its run `ExitStack`, and then calls `os._exit` with the selected code. The platform
  does not use this fallback.
- S2's AT-B2 expected strings gain the keepalive suffix in E1. If S2 has not merged when E1
  starts, the keepalive keywords go into S2 instead, and E1 only uses them.
- Whether the CLI install policy needs a row for anything new: nothing new is installed beyond
  64b's `postgres:16` service; the C1 builder confirms with the sentry.
- The exact `Placer` call DELIV C2a lands for non-file kinds. C1 follows what C2a merges; if C2a
  keeps the placer file-only, C1 adds the postgres arm inside `_delivery.py` (already in its
  touch list) and nothing outside it.
- The final names 64b E1 merges for the session and catalog modules: settled by #624 (see the
  re-anchor note at the top).
- The platform surface for Postgres targets: out of scope (platform parked); the engine names
  are public so it can reuse them.
