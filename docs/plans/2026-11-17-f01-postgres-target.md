Status: plan (revision 3, 2026-11-17)

# F01: PostgreSQL application-ready write target and the type-mapping report (roadmap row 86)

Roadmap row 86: PostgreSQL application-ready write target (staging, constraint, index and
sequence restore, atomic publish) and the type-mapping report. Owner 2026-11-06: in CLI V1. The
row comes after the Phase 2 rows and F22 (row 59). In practice it builds on three plans: F22
publication (receipts, `result_id`, outcome tokens, merged), DELIV (row 61: the CLI delivery sink
and its `SinkStage` protocol) and CLI-DB-SRC (row 64b, engine branch `origin/plan/cli-db-src` at `59343ebd`: the shared
`connectors/_postgres_session.py`, the Postgres secret reference, registry-derived exit classes,
the `pg-gate` CI lane and `decoy setup --postgres`).

Rules consulted: dev-rules `README.md` (routing), `00-universal.md`, `risk-and-exceptions.md` (R1, R2), `development-loop.md` (PLAN: proportion, guarantee, size, design notes, choke point, placement, established solutions; REMEDIATE), `destructive-operations.md` (truncate and overwrite of a database target), `data-and-migrations.md`, `security.md`, `config-secrets-and-supply-chain.md` (secret sourcing, redaction, no new dependency), `cross-cutting-concerns.md` (choke points), `architecture.md` (layout, fan-out, layers), `api-and-compatibility.md` (additive union member, frozen surfaces), `testing.md` (test depth T0 to T4, escalation triggers), `observability-and-resilience.md` (timeouts, reconcile), `reuse-first.md`, `workspace-and-vcs.md` (commit messages), `catalogs/recurring-defects.md` (classes 1 to 11); engine and CLI `CODEMAP.md` "Where Things Go"; CLI `docs/ROADMAP.md` rows 59, 61, 62, 64b, 85 and 86; engine plans `2026-10-29-f22-atomic-idempotent-publication.md` (database adapter contract, its line 124), `2026-10-30-f22-publication-replan.md` (rev 11), `plan/deliv:2026-11-12-deliv.md` (rev 3.5) and `plan/cli-db-src:2026-11-17-cli-db-src.md` (engine branch `origin/plan/cli-db-src`, head `59343ebd`); vault notes `10_Projects/decoy/v2/duckdb/12-database-writeback.md` (earlier V2 proposal, superseded here) and the MASTER F01 section. Code read from `origin/main` on 2026-11-17 (engine `902968682`, tag `v0.27.0`; CLI `5b49510`, pin `decoy-engine==0.27.0`).

Anchors: a path with no prefix is in decoy-engine; a path with the prefix `C:` is in the CLI
repository (decoy).

Risk: R2 overall (data handling, a destructive write to a database, credentials, value leaks).
The destructive write is the product doing what the user configured at run time, not a
development-time side effect, so it is not an R3 action for this work. The
`destructive-operations.md` controls become product behaviour: exact target resolution and a
read-only preview on every run (4.3), an explicit per-table authorization word (`mode:
replace`), bounded execution (timeouts, one transaction) and reconcile (4.4). The engine half
ships in engine **0.29.0**, the release after the 0.28.0 that carries the CLI-DB-SRC engine
half. If the daily release train cuts 0.29.0 before slice E3 merges, the engine half ships in
the first engine release cut after E3 merges, and the CLI repin in C1 names that version.

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
| M5 bookkeeping creation race and privileges | One global advisory key around `decoy_meta` creation; privilege check covers `SELECT`, `INSERT`, `UPDATE` on an existing publications table and `REFERENCES` on non-target lookup tables | 4.3, 4.4 step 3, AT-E5 |
| LOW | Two-int advisory key from SHA-256 in Python (no `hashtext`); `NOT VALID` foreign keys re-created as they were; partial-index and check text kept out of errors and logs with a marker literal in AT-E14; `pg_debug_show_queries` forced off; `duckdb_databases().path` holds the DSN and is never read; AT-C7 adds `report fidelity --config` and every other non-run target reader | 4.4, AT-E8, AT-E14, AT-C7 |

Nothing was left unapplied.

## Revision 3 (Codex on `89a3d564`: NO-GO on two V1 findings, no design findings)

| Finding | Fix | Where |
|---|---|---|
| 1 `pg_sequences` has no `is_called` | AT-E9 reads `last_value` and `is_called` from each sequence relation (`SELECT last_value, is_called FROM <schema>.<sequence>`, identifiers quoted through the identifier rule). The transactional `RESTART WITH` and the `setval` mutation stay | Revision 2 table B1 row, AT-E9 |
| 2 bookkeeping privilege check wrong when only the table is absent | Three cases: schema absent needs database `CREATE` (the role then owns the schema); schema present and table absent needs `CREATE` on schema `decoy_meta`; table present needs `SELECT`, `INSERT`, `UPDATE`. Each refused with `target_privilege_missing`; AT-E5 has a refusing and a passing cell per case | 4.3, 4.4 step 3, section 7, AT-E5, Q11 |
| V2-LOG sibling citation | `plan/cli-db-src` cited as the engine branch `origin/plan/cli-db-src` at `59343ebd` | header, Rules consulted |

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
hit there; one V2 proposal in the wiki, `12-database-writeback.md`).

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
| In-repo: `postgres_snapshot` (`src/decoy_engine/connectors/postgres_snapshot.py:217`, `:246`, `:271`) and 64b's `connectors/_postgres_session.py` | Offline extension load, DuckDB connection with auto-install off, constant catalog SQL, coded value-free errors | Reused: F01 adds `open_write_session` beside 64b's `open_read_session` |

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
| DuckDB connection with offline extension load, identifier rule | `open_read_session`, `validate_identifier`, `_q`, `_lit` in `connectors/_postgres_session.py` (64b E1 moves them out of the snapshot module) | `src/decoy_engine/connectors/postgres_snapshot.py:74`, `:136`, `:204`, `:217`, `:246` (origin today) |
| Coded value-free error | `PostgresSnapshotError` (the target error subclasses it, so the existing CLI arm and code owner hold) | `src/decoy_engine/connectors/postgres_snapshot.py:116` |
| Type classes of the source side | `_PLAIN_TYPES`, `_classify` (the type map reads the same lists) | `src/decoy_engine/connectors/postgres_snapshot.py:92`, `:285` |
| Secret reference and `postgres-dsn-v1` | `prepare_secret`, `POSTGRES_DSN_V1` (64b E1) | `src/decoy_engine/secret_providers/_requirements.py:42` |
| Catalog reads of a source | `connectors/postgres_catalog.py` (64b E1); F01 E3 adds the public `server_fingerprint` beside `relation_columns` | 64b plan 4.3 step 4 |
| Exit class of connector codes | Registry outcome per spec (`CONFIGURATION` or `EXECUTION`) and the set 64b derives from the registry at import | 64b plan 4.3 "Exit classification" |
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
| Postgres CI lane, fixtures, zero-skip guard | `pg-gate` job, `pg_dsn`, `ext_dir`, `PgAdmin`, `DECOY_REQUIRE_PG`, `junit_ran.py` (64b E1) | `tests/connectors/conftest.py:52` |
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
  `lock_timeout_s=30`, `idle_in_transaction_timeout_s=60`, `connect_timeout_s=15`.
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
  minimum and maximum), privileges, the server version number, the bookkeeping row for the
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
    a member of the owning role); no `REFERENCES` on a non-target table that a target foreign
    key points at; or the bookkeeping rights for the case found: schema `decoy_meta` absent
    and no `CREATE` on the database (the role then owns the schema it creates); schema present
    and table `decoy_meta.publications` absent and no `CREATE` on schema `decoy_meta`; table
    present without `SELECT`, `INSERT` and `UPDATE` on it;
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
CommitReceipt`. One DuckDB connection from `open_write_session` (read-write `ATTACH`,
`pg_debug_show_queries = false`), one DuckDB transaction that is one PostgreSQL transaction
(proved in E0). Every target statement goes through `postgres_execute(..., use_transaction :=
true)` or an `INSERT` into the attached table; no DuckDB-side `SELECT` reads a target table
through the connection pool (E0 cell c). Before each step the publisher runs `SET LOCAL
statement_timeout` to min(`statement_timeout_s`, remaining deadline). Steps, in order; each has
a fixed name used for the error location and the test fault seam:

1. `begin`: `BEGIN`; `SET LOCAL search_path = pg_catalog`, `lock_timeout`,
   `idle_in_transaction_session_timeout`, and on servers 14 and later
   `client_connection_check_interval = 10s`; capture `pg_current_xact_id()` and
   `pg_backend_pid()` (ids, not data) for reconcile.
2. `lock_writer`: `pg_advisory_xact_lock(k1, k2)`, the two `int4` halves of the first 8 bytes
   of SHA-256 over `decoy-pg-target:` plus the schema name, computed in Python (no
   `hashtext`). A timeout is `target_busy`.
3. `check_marker`: if inspection found the schema or the table absent, take the global
   advisory key (SHA-256 of `decoy-pg-target:decoy_meta`), then `CREATE SCHEMA IF NOT EXISTS
   decoy_meta` (only when the schema was absent) and `CREATE TABLE IF NOT EXISTS
   decoy_meta.publications`; the rights each needs were checked at inspection (4.3). Read the row for the schema `FOR UPDATE`. Same `operation_id` and same
   `result_id`: roll back and return `already_committed` (nothing written). Same `operation_id`,
   other `result_id`: roll back, `operation_conflict` with `publication_operation_conflict`.
   Row differs from `catalog.marker`: roll back, `refused` with `delivery_pointer_moved`.
4. `lock_tables`: `LOCK TABLE ... IN ACCESS EXCLUSIVE MODE` on every target table, in sorted
   order (`target_busy` on timeout).
5. `capture`: `capture_structure` under the locks and `search_path = pg_catalog`; a digest
   different from `catalog` is `target_changed`. The definitions used in steps 6 and 9 come from
   this capture, never from the inspection.
6. `drop_foreign_keys`: drop every foreign key with either end in the set;
   `DISABLE TRIGGER USER` on each table; identity columns declared `ALWAYS` become `BY DEFAULT`
   so the load can write them. Indexes and primary key, unique, exclusion, check and not-null
   constraints stay (H6).
7. `truncate`: one `TRUNCATE` of every target table.
8. `load`: per table, `INSERT INTO <pg>.<schema>.<table> (<columns except generated>) SELECT
   <same columns> FROM read_parquet(<staged path>)`; the affected-row count of the `INSERT` is
   compared with the Parquet footer. A failure (including a unique, exclusion, check or not-null
   violation by the masked rows) or a count difference is `target_load_failed` at
   `schema.table`.
9. `restore`: re-create every captured foreign key from its definition text (a `NOT VALID` key
   as `NOT VALID`, a validated key validated; `DEFERRABLE` kept); a failure is
   `target_constraint_failed` at `schema.table.constraint`. Restore each user trigger by its
   captured `tgenabled`: `O` `ENABLE TRIGGER`, `D` `DISABLE TRIGGER`, `R` `ENABLE REPLICA
   TRIGGER`, `A` `ENABLE ALWAYS TRIGGER`. Restore identity kinds.
10. `sequences`: one server-side `DO` block per sequence, given only identifiers: it computes
    `max(col) + 1` (or the sequence start value when the table is empty, or when `max(col) + 1`
    is below the sequence minimum) and runs `ALTER SEQUENCE ... RESTART WITH` (owned serial) or
    `ALTER TABLE ... ALTER COLUMN ... RESTART WITH` (identity). A restart value above the
    sequence maximum raises in the block: `target_sequence_failed` at `schema.table.column`. No
    value reaches Python. `setval` is never used.
11. `write_marker`: upsert the bookkeeping row (format tag, schema, `operation_id`, `result_id`,
    engine version, `now()`).
12. `commit`: `COMMIT`. The visibility point.

After a successful commit: `ANALYZE` each target table on a fresh statement; a failure is a
warning on the receipt path (logged with code only), never a failed publish.

Failure handling, the same for every step: the error is caught, only `type(exc).__name__` is
kept, DuckDB `ROLLBACK` runs and the connection closes (the server aborts the transaction either
way), and then, outside the `except` block, a probe on a new connection decides the code: if
the server cannot be reached the code is `target_unreachable`, else the step's code. PostgreSQL
error text and definition text are never read into an error or a log.

Reconcile after `commit` raises (H1): a new read-only session, opened under
`connect_timeout_s` (mechanism fixed by E0 cell h), runs `pg_xact_status(<xid>)`:

- `committed`: `published`.
- `aborted`: `failed` with `publication_commit_not_visible`; the target is the old one.
- `in progress`: `pg_terminate_backend(<pid>)` on our own backend, wait up to
  `lock_timeout_s` for the status to leave `in progress`, then decide again; still in progress
  is `target_commit_unknown`.
- null (status unavailable) or no connection: `PostgresTargetError(target_commit_unknown)`; the
  CLI exits 3, says the outcome is unknown and names the schema to check.

The engine never retries a commit.

Deadline: a timer interrupts DuckDB at `deadline_s`, as the snapshot does
(`src/decoy_engine/connectors/postgres_snapshot.py:470`); E0 cell e proves the server query is
cancelled; the transaction rolls back; `deadline_exceeded`. A client that stops responding
inside the transaction (SIGSTOP, a hung host) releases its locks after
`idle_in_transaction_timeout_s` (M1).

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
- 130: Ctrl-C before the commit (rolled back, `src/decoy_engine/connectors/postgres_snapshot.py:470` interrupt pattern).

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
- `publish_tables` and `publish_unit` (`src/decoy_engine/publication/_publish.py:199`, `:338`):
  never reached for a Postgres target; the CLI stage calls the handle instead.

### 5.3 FK shapes

- Scalar FK between two target tables: dropped in `drop_foreign_keys`, re-created in `restore`
  after both tables load; a masked child that breaks it fails the run with
  `target_constraint_failed`, rolled back.
- Composite FK: same path; `pg_get_constraintdef` carries the column list and match type.
- Self-referencing FK: one table, dropped and re-created like any other.
- FK cycle between target tables: handled, because no FK exists during the load.
- FK from a non-target table to a target table: `target_external_reference` at inspection.
- FK from a target table to a non-target table (a lookup table not in the pipeline): dropped
  and re-created; the re-create validates the masked rows against the untouched lookup table;
  needs `REFERENCES` on the lookup table (checked at inspection).
- `NOT VALID` FK: re-created `NOT VALID`, not validated (as it was).
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
  `postgres_target published relations=<n>`; nothing else (`src/decoy_engine/connectors/postgres_snapshot.py:522` style).
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
| Missing TRUNCATE, INSERT, ownership, REFERENCES on a lookup table, or the `CREATE` or table rights for the bookkeeping case found | `target_privilege_missing`, exit 1 | untouched | AT-E5 |
| Target is the source database | `target_same_database` (or compile `target_is_source`), exit 1, before any source row | untouched | AT-E7, AT-E2 |
| Lossy or unsupported type, missing or extra column | `target_type_blocked` / `target_column_mismatch`, exit 1, report shows the rows | untouched | AT-E3, AT-E6 |
| Guard fails (length, enum, null, range, sub-microsecond, non-integral) | `value_guard_failed` at `table.column`, exit 1 | untouched | AT-E6 |
| Another Decoy publish holds the target | `target_busy` after `lock_timeout_s`, exit 3 | untouched | AT-E12 |
| An application transaction holds a table lock | `target_busy`, exit 3 | untouched | AT-E12 |
| Index, constraint or column changed after inspection (even just before the lock) | `target_changed` under the lock, rolled back, exit 3 | old contents | AT-E12 |
| Another writer published after inspection | `delivery_pointer_moved`, rolled back, exit 3 | other writer's contents | AT-E12 |
| Masked rows break a unique, exclusion, check or not-null constraint, or row count differs | `target_load_failed` at `schema.table`, rolled back, exit 3 | old contents | AT-E9 |
| Masked rows break a FK | `target_constraint_failed` at the constraint, rolled back, exit 3 | old contents | AT-E9 |
| Restart value above a sequence maximum | `target_sequence_failed`, rolled back, exit 3 | old contents, old sequence state | AT-E9 |
| Failure in any step 1 to 11 | rolled back by the transaction | old contents, sequences unchanged | AT-E9 |
| Connection lost before COMMIT | server aborts; `target_unreachable`, exit 3 | old contents | AT-E9, AT-E13 |
| COMMIT sent, acknowledgement lost | reconcile by `pg_xact_status`: `published` (exit 0) or `publication_commit_not_visible` (exit 3) | new or old, reported correctly | AT-E13 |
| Our backend still in progress at reconcile | terminate own pid, re-check | old contents (aborted) | AT-E13 |
| Reconcile cannot connect or status null | `target_commit_unknown`, exit 3, message names the schema to check | unknown, never retried | AT-E13 |
| Deadline passes | interrupt cancels the server query, rollback, `deadline_exceeded`, exit 3 | old contents | AT-E9, AT-E0 |
| Ctrl-C before commit | rollback, exit 130, scratch removed | old contents | AT-C5 |
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
| AT-E0 | `tests/connectors/test_postgres_write_spike.py` (pg), raw DuckDB calls only. Cells: (a) in one DuckDB transaction over a read-write ATTACH, `postgres_execute(..., use_transaction := true)` DDL, a `TRUNCATE` and an `INSERT ... SELECT FROM read_parquet` are invisible to a second libpq session before `COMMIT` and undone by `ROLLBACK`; (b) closing the connection mid-transaction aborts it and releases its locks; (c) a DuckDB-side `SELECT` of a locked, truncated table inside the transaction returns at once with the in-transaction state (no hang, no stale read), recorded either way and the design keeps such reads out; (d) `pg_clear_cache()` after a DDL shows the changed catalog; (e) `interrupt()` cancels the server query (`pg_stat_activity` shows it gone within 5 s); (f) `INSERT` with a column list into a table with a stored generated column, an identity switched to `BY DEFAULT`, and enum, jsonb, uuid and array columns succeeds; (g) the `INSERT` affected-row count is returned; (h) a connect-timeout mechanism bounds a connection to a blackhole address; (i) `postgres_execute` with a `DO` block running `ALTER SEQUENCE ... RESTART` is undone by `ROLLBACK`; (j) `pg_current_xact_id()` and `pg_backend_pid()` read inside the transaction equal what a second session sees in `pg_stat_activity` | no evidence of the transaction behaviour | run cell (a) with `use_transaction := false` | E0 |
| AT-E1 | `tests/unit/config/test_postgres_target.py`: a `type: postgres` target parses; missing `mode`, `mode: append`, extra keys, empty strings, a bool and an int in each string field are refused with input hidden; `connection_ref` is a locator field; two tables on one `(ref, schema, table)` hit the duplicate-destination refusal | no variant | drop the postgres arm of `_target_identity` | E1 |
| AT-E2 | `tests/unit/plan/test_postgres_target_check.py`: identifier cells including `"ok\n"`, two refs, two schemas, a postgres plus a file target, `best_effort`, target ref equal to a source ref, `vault://x` are each refused with their code and location; the text never holds the ref | no check | replace `fullmatch` with `match` and `$` in `validate_identifier` | E1 |
| AT-E3 | `tests/unit/connectors/test_postgres_typemap.py`: one cell per row of 4.5 across all three steps, including the pandas-route rows (int64 to integer, float64 to bigint, `timestamp[ns]`), numeric without typmod and numeric(40, 2) as `unsupported`, float64 to real and `character(n)` as `lossy`, decimal scale change, generated column, and a DuckDB middle type that downgrades an otherwise exact pair; missing and extra columns; the document is canonical bytes, sorted, tagged `decoy-pg-type-map/v1`, and its schema snapshot matches | no module | drop the DuckDB step from the worst-class fold | E1 |
| AT-E4 | `tests/sentry/test_postgres_session_choke_point.py` (extends 64b's session sentry): in `connectors/`, `open_write_session` is called only from `postgres_target_publish.py`, and an `ATTACH` without `READ_ONLY` appears only in `_postgres_session.py`; seeded cells for each fail. Existing snapshot and 64b tests pass unchanged (negative control) | no write session | call `open_write_session` from `postgres_target.py` | E1 |
| AT-E16 | `tests/connectors/test_postgres_typemap_roundtrip.py` (pg): for every `exact` row of 4.5, a Parquet value goes through `open_write_session` `INSERT` into a column of that PostgreSQL type in a rolled-back transaction and is read back by libpq equal to the source | no write session | map `timestamp[us, tz]` as `exact` to `timestamp without time zone` | E1 |
| AT-E5 | `tests/connectors/test_postgres_target_inspect.py` (pg): server version faked below 13 (catalog stub cell), missing relation, partitioned table, inheritance child, rule, FORCE RLS, external FK, non-owned `nextval` default, shared sequence, negative increment, a role without TRUNCATE, a non-owner role, no `REFERENCES` on a lookup table, and the three bookkeeping cases (schema `decoy_meta` absent and no database `CREATE`; schema present, table absent and no `CREATE` on the schema while the role has database `CREATE`; table present without `UPDATE`) all refuse with their codes, `target_privilege_missing` for the three; each bookkeeping case also has a passing cell with the right granted; `pg_stat_user_tables` counters, `pg_namespace` and the catalog digest are unchanged afterwards | no `read_target` | skip the external-reference query | E2 |
| AT-E6 | `tests/connectors/test_postgres_target_plan.py` (pg): over-length varchar, unknown enum label, null into NOT NULL, numeric overflow, an int64 above the integer range, a float64 `1.5` into bigint, and a `timestamp[ns]` with a nanosecond part each refuse with `value_guard_failed` at `schema.table.column`; a blocked type refuses with `target_type_blocked`; no target write session opens (spy) | no `plan_target` | drop the sub-microsecond guard | E2 |
| AT-E15 | `tests/unit/publication/test_pg_publication_row.py`: the bookkeeping row reader refuses a missing or unknown `format`, `"op\n"` as operation id, uppercase hex, a 63-character `result_id` and a bool in a text column; the writer's row round-trips; schema snapshot | no reader | read `format` with `startswith` | E2 |
| AT-E7 | `tests/connectors/test_postgres_target_pipeline.py` (pg): a pipeline whose source and target references name the same database refuses `target_same_database` from `open_postgres_target`, and a spy on `stage_postgres_sources` and on the snapshot shows no call; a second database on the same server passes (negative control) | no probe | run the fingerprint compare after `stage_postgres_sources` | E3 |
| AT-E8 | `tests/connectors/test_postgres_target_publish.py` (pg): three tables with an FK chain, a `NOT VALID` FK, a deferrable FK, a serial key, an `ALWAYS` identity, a stored generated column, an enum, a partial index, an expression index, a unique, a check, and triggers in states `O` (audit), `D`, `R` and `A`. After publish: Arrow readback equals the staged Parquet for every non-generated column; generated values match the server's recomputation; FK definitions and `convalidated` equal the pre-run values exactly; index and other constraint OIDs are unchanged (never dropped); every trigger's `tgenabled` equals its pre-run value; the audit table is empty; identity kinds are unchanged; an `INSERT` with default keys succeeds on every table; `ANALYZE` ran; an injected `ANALYZE` failure still returns `published` | no publish | skip `sequences` (the default-key insert hits a duplicate key) | E3 |
| AT-E9 | same file (pg): a fault injected at each of the twelve steps (test seam), including `write_marker` and `commit`; a masked child row that breaks an FK; a duplicate key against a kept unique index; a value the server refuses in `load`; a restart value above a `smallint` sequence maximum; a 1 s deadline on a slow load; a server-side `pg_terminate_backend` before `COMMIT`. Each leaves the catalog digest, the row digests of every target table, `last_value` and `is_called` of every owned sequence read from the sequence relation itself (`SELECT last_value, is_called FROM <schema>.<sequence>`, both quoted through the identifier rule; `pg_sequences` has no `is_called`), and the bookkeeping row equal to their pre-run values, with the expected code | no publish | reset sequences with `setval` instead of `RESTART WITH` | E3 |
| AT-E10 | same file (pg): during a publish a reader runs, in a loop under READ COMMITTED, one statement returning the counts of all three tables; every observed triple is the old triple or the new triple. Recording cell: a REPEATABLE READ transaction that took its snapshot before the commit and reads after it sees empty tables (asserted, so a change in PostgreSQL behaviour is noticed) | no publish | `TRUNCATE` and `COMMIT` before the load | E3 |
| AT-E11 | same file (pg): a subprocess publisher is SIGKILLed after the first table loads; within 5 s the target equals the pre-run state, its locks are gone and no `decoy_meta` row changed. A second publisher is SIGSTOPped inside the transaction with `idle_in_transaction_timeout_s=2`; its locks are gone within 2 s plus 3 s slack | no publish | omit `idle_in_transaction_session_timeout` | E3 |
| AT-E12 | same file (pg): retry with the same operation and result returns `already_committed` with no write (`n_tup_ins` unchanged); same operation, other result: `publication_operation_conflict`; a bookkeeping row changed after `read_target`: `delivery_pointer_moved`; an index added after `read_target`, and one added by a hook that runs between `check_marker` and `lock_tables`: `target_changed`; a second publisher holding the advisory lock and an application transaction holding a row lock: `target_busy` within `lock_timeout_s + 2` s; two first publishes into two schemas with `decoy_meta` absent both succeed (global creation key). Every refusal leaves the target unchanged | no publish | capture the structure before `lock_tables` | E3 |
| AT-E13 | same file (pg): the commit wrapper raises after a real `COMMIT` (`pg_xact_status` committed: `published`); raises instead of committing (aborted: `publication_commit_not_visible`, target unchanged); raises while the backend is held in progress (terminated, then aborted: `publication_commit_not_visible`); raises and the reconcile connection times out against a blackhole address within `connect_timeout_s + 2` s (`target_commit_unknown`); the commit is attempted exactly once in every case | no reconcile | reconcile by reading the bookkeeping row | E3 |
| AT-E14 | same file (pg): a DSN with a marker password, a wrong host, a staged row carrying a marker string that breaks a unique constraint, a partial-index predicate and a check constraint that each contain a marker literal and fail during the run: the markers are absent from the error `str`, `repr`, formatted traceback with chains, every log record captured at DEBUG, the receipt and the type-map document; `pg_debug_show_queries` reads `false` on the session; every raised error has `__cause__` and `__context__` `None` | no publish | raise `PostgresTargetError` inside the `except` block in one step | E3 |

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
| `src/decoy_engine/connectors/_postgres_session.py` | changed (adds `open_write_session`; module created by 64b E1) | Connectors (private helper of the package) | `postgres_snapshot.py` |
| `src/decoy_engine/connectors/postgres_catalog.py` | changed (adds `server_fingerprint`; module created by 64b E1) | Connectors | `postgres_snapshot.py` |
| `src/decoy_engine/connectors/postgres_typemap.py` | new | Connectors: `connectors/<name>.py` | `postgres_snapshot.py` |
| `src/decoy_engine/connectors/postgres_target_catalog.py` | new (catalog SQL, `capture_structure`, bookkeeping row declaration) | Connectors | `postgres_catalog.py` |
| `src/decoy_engine/connectors/postgres_target.py` | new (config, error, `read_target`, `plan_target`, guards) | Connectors | `postgres_snapshot.py` |
| `src/decoy_engine/connectors/postgres_target_publish.py` | new (step table, `publish_target`, reconcile) | Connectors | `postgres_target.py` |
| `src/decoy_engine/connectors/__init__.py` | changed (exports) | Connectors | itself |
| `src/decoy_engine/execution/pipeline/_postgres_target.py` | new | Pipeline spine: `execution/pipeline/` | 64b `execution/pipeline/_postgres_source.py` |
| `src/decoy_engine/delivery/_plan.py` | changed (one token) | (delivery package, DELIV E1a) | itself |
| `src/decoy_engine/reasons/config/_part2.py`, `src/decoy_engine/reasons/connector/_part1.py` | changed (new codes with outcomes) | Reason codes | existing catalogs |
| `src/decoy_engine/__init__.py` | changed (exports, frozen-surface rows) | Public API | facade list |
| `tests/connectors/test_postgres_write_spike.py`, `test_postgres_typemap_roundtrip.py`, `test_postgres_target_inspect.py`, `test_postgres_target_plan.py`, `test_postgres_target_pipeline.py`, `test_postgres_target_publish.py` | new | `tests/connectors/` (listed exception) | snapshot suites |
| `tests/unit/config/test_postgres_target.py`, `tests/unit/plan/test_postgres_target_check.py`, `tests/unit/connectors/test_postgres_typemap.py`, `tests/unit/publication/test_pg_publication_row.py` | new | Unit tests mirroring `src/` | owning package tests |
| `tests/sentry/test_postgres_session_choke_point.py` | changed or new (extends 64b's session sentry) | Sentry test | 64b sentry |
| `.github/workflows/ci.yml` (`pg-gate` file list), `tests/sentry/file_access_modules.toml`, `tests/sentry/file_access_registry.toml`, physical-seam allowlist | changed (new marked files; one exact `(path, name)` row per new module) | CI lane registries; sentry registries | existing rows |
| `docs/postgres-target.md`, `docs/index.md`, `changelog.d/f01-e1.md`, `changelog.d/f01-e2.md`, `changelog.d/f01-e3.md` | new or changed | Feature docs; changelog fragments | `docs/publication.md`, 64b `docs/postgres-source.md` |

`connectors/` holds 7 modules today plus 64b's two or three; five new modules keep it under
any fan-out concern. A connectors sub-package was considered and rejected: the map names
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

## 11. Size

Engine: 5 new modules (`postgres_typemap.py` about 330, `postgres_target_catalog.py` about 420,
`postgres_target.py` about 330, `postgres_target_publish.py` about 520,
`execution/pipeline/_postgres_target.py` about 170), 7 changed modules (about 220 lines,
including `open_write_session` about 60 and `server_fingerprint` about 30), 10 new test files
(about 1,700 lines), one doc page. New public names: the sixteen in section 6.

CLI: 1 new module (about 220), 5 changed modules (about 110), one test folder (about 750 lines),
one guide.

Module size (engine `tests/sentry/test_module_size.py`, aim 600, hard 700; CLI cap 800): every
new engine module stays under 600. A build more than 30 percent over these numbers stops and
explains before review.

## 12. Slices

Fewer, larger, behaviour-changing slices. The spike is first and alone; prep goes in E1;
engine docs in E3; CLI docs in C2. Source lines below are product source only; tests are
listed separately.

| Slice | Repo | Content | Risk | Src lines | Test lines | Acceptance tests | Depends on | Test depth notes |
|---|---|---|---|---|---|---|---|---|
| E0 | engine | Spike: `test_postgres_write_spike.py` with raw DuckDB calls, `pg-gate` file list row, a record of each cell's result in `docs/records/2026-11-xx-f01-e0-spike.md`. No product code | R1 (test only; result gates E1) | 0 | ~300 | AT-E0 | 64b E1 merged (lane, extension in CI) | `pg-gate` green; if any design cell fails, E1 does not start (Q15) |
| E1 | engine | `open_write_session` in 64b's `_postgres_session.py`; `PostgresTarget` and the identity arm; `plan/checks/_postgres_targets.py`; `postgres_typemap.py` with the three-step fold and the report document; config and connector codes with outcomes (`since=UNRELEASED`); `DELIVERABLE_TARGET_TYPES` token; engine target writer dispatch refusal (`target_postgres.unsupported_command`); choke-point sentry; `pg-gate` file list; changelog fragment | R2 (shared connector code, config union, codes) | ~620 | ~650 | AT-E1, AT-E2, AT-E3, AT-E4, AT-E16 | E0 green; 64b E1 and E2 merged; DELIV E1a (merged) | config serializer and shared connector module: full suite once on the slice head, diffed against the saved main baseline; `pg-gate` green |
| E2 | engine | Read-only half: `postgres_target_catalog.py` (catalog SQL, `capture_structure`, digest, sequence and privilege checks, bookkeeping row declaration and strict reader with its snapshot), `postgres_target.py` (`read_target`, `plan_target`, value guards); changelog fragment | R2 (data handling, secrets) | ~760 | ~550 | AT-E5, AT-E6, AT-E15 | E1 | T1 plus `pg-gate`; mutations on the reader and the guards |
| E3 | engine | Write half and pipeline: `postgres_target_publish.py` (twelve steps, rollback, probe, `pg_xact_status` reconcile, deadline, `ANALYZE`); `server_fingerprint`; `execution/pipeline/_postgres_target.py`; public exports and frozen-surface rows; `docs/postgres-target.md`, `docs/index.md`; changelog fragment | R2 (destructive database write, publication, value leaks) | ~780 | ~900 | AT-E7, AT-E8, AT-E9, AT-E10, AT-E11, AT-E12, AT-E13, AT-E14 | E2 | frozen surface: full suite once on the slice head against the saved baseline; `pg-gate` green; every E3 mutation in section 8 re-run on the final head |
| REL | engine | Engine release 0.29.0 through the daily release train; the release commit stamps the new codes, `REGISTRY_VERSION` and the manifests | R1 | small | none | release checks | E3; 0.28.0 (64b) cut | release train rules |
| C1 | CLI | Repin to 0.29.0 (engine repin checklist); `io/_postgres_target.py` stage and `PostgresOutput`; `_delivery.py` stage construction; prepare-time `open_postgres_target` and the `--resume` target arm; non-run refusal arm; card summary and `--json` key; `pg-gate` file list; CODEMAP tests cell | R2 (data handling, version pin, CI) | ~330 | ~650 | AT-C1, AT-C2, AT-C3, AT-C4, AT-C6, AT-C7, AT-C8, AT-C10 | REL; DELIV C2a merged (`SinkStage`, `PublishedOutput`, placer); 64b C1 and C2 merged | version pin and test config: full suite on the slice head against the saved main baseline; `pg-gate` green |
| C2 | CLI | Interrupt handling at the visibility point and `target_commit_unknown` message; shape changelog and snapshot; user guide `docs/guides/postgres-target/` (target preparation with `pg_dump --schema-only`, PostgreSQL 13 minimum, privileges, `decoy_meta` SQL for a DBA, what READ COMMITTED and REPEATABLE READ readers see, refreshing materialized views, WAL size), README, CHANGELOG, QA checklist rows, roadmap row 86 to DONE and shipped log | R2 (interrupt semantics on a destructive write) | ~120 plus docs | ~150 | AT-C5, AT-C9 | C1 | T1 plus `pg-gate` |

Every slice is under about 800 source lines. Order: E0, E1, E2, E3, REL, C1, C2. One writer per
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
| 8 | One input, one trust class per entry point | user-chosen relation names go through the identifier rule; staged Parquet paths are program-built and never user input; SQL literals for paths go through `_lit`; definition text comes only from the target's own catalog |
| 9 | Mutations on the final head | every slice reruns its section 8 mutations after its last change and records the head |
| 10 | Allowlisted helpers are still checked | new modules get exact `(path, name)` rows in the file-access and physical-seam registries; their callers stay checked |
| 11 | No raised caps | no cap, pin ceiling, ratchet or baseline is raised; a module near its size cap is split |

## 14. Plan defect catalog classes

| Class | Defect | Closing structure | Sentry or property test | Seeded mutation | Slice |
|---|---|---|---|---|---|
| 1 | Value exposure (DSN, row values in server error text, literals in definition text, reference text) | exception type only, raise outside `except`, guards return counts, definitions never logged, `pg_debug_show_queries` off, report holds names and types | AT-E14, AT-C3 | raise inside the `except` block; forward `str(exc)` | E3, C1 |
| 2 | Cleanup on every exit (target and scratch) | one transaction with transactional sequence restarts, rollback on any failure, idle-in-transaction timeout; scratch on the run `ExitStack` | AT-E9, AT-E11, AT-C5 | reset sequences with `setval`; allocate scratch without a scope | E3, C2 |
| 3 | State completeness (every step and every outcome covered) | fixed step table; every step has a fault cell; every reconcile status has a cell | AT-E9, AT-E12, AT-E13 | delete one step's fault handler | E3 |
| 4 | Route coverage | all routes write through the sink placer into the same scratch; pandas-route types classed; `--resume` and non-run callers refused | AT-C1, AT-C2, AT-C7, AT-C10 | place only on the plain route | C1 |
| 5 | Referential integrity across target tables | FKs dropped before and re-created as they were after the load in one transaction; external FKs refused | AT-E8, AT-E9, AT-E5 | skip FK re-creation; skip the external-reference check | E2, E3 |
| 6 | Untrusted input (relation names, secret material, catalog text) | the one identifier rule; `postgres-dsn-v1`; captured definitions executed only under `search_path = pg_catalog` | AT-E2, AT-E8 | allow `.` in identifiers; drop `SET LOCAL search_path` | E1, E3 |
| 7 | TOCTOU check-then-use between inspection and publish | locks taken first, then structure captured and compared under the locks; bookkeeping row read `FOR UPDATE` | AT-E12 | capture before `lock_tables` | E3 |
| 8 | Weak proof of "nothing written" and "all restored" | catalog digest, row digests, sequence state and `pg_stat_user_tables` counters, not only a code; FK, index OID and trigger state compared before and after | AT-E5, AT-E8, AT-E9 | assert only the error code | E2, E3 |
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
- The masked data breaks a target FK to an untouched lookup table. The run fails with
  `target_constraint_failed` at that constraint and rolls back; the guide tells the user to add
  the lookup table to the pipeline as passthrough.
- A builder reads the PostgreSQL error message to classify a failure "more precisely": AT-E14
  plants values in a unique violation, a partial index and a check and fails on any leak; the
  reviewer checks that only exception type names are read.
- A builder weakens AT-E9 to check one table or skips the sequence state: the gate checks that
  the catalog digest, every table's row digest, every owned sequence's state and the
  bookkeeping row are compared for every step.
- A builder reaches for `setval` because it is simpler: AT-E9's mutation turns it red.
- The pandas mask route writes types the first draft classed lossy: AT-C1 runs the default route
  end to end.
- DELIV C2a slips: C1 cannot merge without the `SinkStage` protocol. The engine half still ships
  in 0.29.0 and the CLI half waits; no interim CLI path is built.
- 64b E1 changes the session module's names during review: E0 and E1 start only after 64b E1
  merges and use what merged.
- `decoy_meta` is created by a role without `CREATE` on the database: refused at inspection, and
  the guide gives the DBA the statements to create it once.

## 16. Owner questions (each taken on the recommended answer and recorded)

| # | Question | Recommended answer, taken |
|---|---|---|
| Q1 | Publish method: one transaction in place, or a staging schema with a rename swap? | One transaction in place (pg_restore `--single-transaction`, pgloader steps). "Staging" in V1 is the locally staged masked Parquet plus the uncommitted transaction. Readers wait during the load. The guarantee covers statement-level READ COMMITTED readers; a REPEATABLE READ or SERIALIZABLE snapshot taken before the commit sees empty tables after it (`TRUNCATE` is not MVCC-safe), stated in the guide (B2). The schema swap is V2 |
| Q2 | Which write modes in V1? | `replace` only, required and explicit in each target. The target structure must exist (migrations or `pg_dump --schema-only`). `create`, `append` and `upsert` are V2 |
| Q3 | How many target connections and schemas per pipeline, and can Postgres targets mix with file or cloud targets? | One connection, one schema, no mixing in V1, because one transaction is the atomic unit |
| Q4 | `best_effort` delivery with a Postgres target? | Refused at compile time; strict only |
| Q5 | Same-database guard | Refuse when the target and any Postgres source are the same database (same reference text at compile time; same server fingerprint from a catalog-only probe before any source row at run time). A second database on the same server is allowed |
| Q6 | User triggers during the load | Disabled (`DISABLE TRIGGER USER`) and restored to their exact prior `tgenabled` state before commit, inside the transaction; needs table ownership, not superuser |
| Q7 | Sequence values after the load | Owned sequences and identities restart at `max(column) + 1` (the start value when the table is empty or `max + 1` is below the minimum) with the transactional `ALTER SEQUENCE ... RESTART WITH` or `ALTER TABLE ... ALTER COLUMN ... RESTART WITH`, computed in a server-side `DO` block; never `setval` (B1). A restart above the maximum fails the run. Non-owned `nextval` defaults, shared sequences and negative increments are refused at inspection |
| Q8 | Lossy conversions | Always block in V1. No approval list; a later row can add one |
| Q9 | Unsupported target objects in V1 | Partitioned tables, inheritance, rewrite rules, FORCE RLS, foreign keys from non-target tables and the unusual sequences of Q7 are refused before writing. Views keep working (OIDs unchanged). Materialized views are not refreshed |
| Q10 | Backup, confirmation and preview before a destructive write | No automatic backup, no prompt, no separate preview command. The explicit `mode: replace` per table is the authorization; the read-only inspection runs on every run before any row is read and the card names the target. A preview command is a follow-up row |
| Q11 | Where the publication record lives | `decoy_meta.publications` in the target database, created on first publish under a global advisory key when the role may (database `CREATE` if the schema is absent, `CREATE` on `decoy_meta` if only the table is absent); otherwise a DBA creates it once from the guide's SQL. Fixed schema name in V1 |
| Q12 | Where the type-mapping report goes | Run card summary, `--json` key `postgres_target.type_map` with the engine document `decoy-pg-type-map/v1`; no new file in the run folder |
| Q13 | Which engine release carries the engine half | 0.29.0, the release after 64b's 0.28.0, or the first release cut after E3 merges |
| Q14 | `ANALYZE` after the publish | Yes, after commit; a failure is a warning, never a failed run |
| Q15 | If E0 shows DuckDB cannot hold every step in one PostgreSQL transaction | E1 does not start. Switching to psycopg 3 is an **owner decision**: it adds a dependency (supply-chain approval), re-costs E3 (a different session, cursor and error model) and re-derives the type map (the middle DuckDB step goes away and psycopg adaptation replaces it). The plan is amended only after that decision; no silent fallback |
| Q16 | Timeouts | Statement 3600 s capped per step by the remaining deadline, whole publish 21600 s, lock wait 30 s, idle in transaction 60 s, reconcile connect 15 s; no config override in V1 |
| Q17 | Minimum target server | PostgreSQL 13 (`pg_current_xact_id` and `pg_xact_status` with `xid8`); refused below. `client_connection_check_interval` is set only on 14 and later |
| Q18 | Drop and re-create indexes for load speed? | No in V1 (H6 ruling): only foreign keys are dropped; indexes and primary key, unique and exclusion constraints stay in place. Index dropping is a V2-LOG speed-up |
| Q19 | `--resume` with a Postgres target | Refused in V1, exit 1, matching 64b; the same landing rule as 64b (whichever of F01 C1 and the F23 `--resume` CLI half lands second adds the refusal and test) |

## 17. Unresolved

- E0's outcome (Q15). Everything after E0 assumes its design cells pass. Cell c (a DuckDB-side
  read of a locked table) is recorded either way; the design does not depend on it.
- The connect-timeout mechanism for reconcile (E0 cell h): a libpq `connect_timeout` the
  session helper can set without editing the user's DSN text, or the wall-clock interrupt timer.
- Whether the CLI install policy needs a row for anything new: nothing new is installed beyond
  64b's `postgres:16` service; the C1 builder confirms with the sentry.
- The exact `Placer` call DELIV C2a lands for non-file kinds. C1 follows what C2a merges; if C2a
  keeps the placer file-only, C1 adds the postgres arm inside `_delivery.py` (already in its
  touch list) and nothing outside it.
- The final names 64b E1 merges for the session and catalog modules; F01 uses what merged.
- The platform surface for Postgres targets: out of scope (platform parked); the engine names
  are public so it can reuse them.
