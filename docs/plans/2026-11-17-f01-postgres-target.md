Status: plan (revision 1, 2026-11-17)

# F01: PostgreSQL application-ready write target and the type-mapping report (roadmap row 86)

Roadmap row 86: PostgreSQL application-ready write target (staging, constraint, index and
sequence restore, atomic publish) and the type-mapping report. Owner 2026-11-06: in CLI V1. The
row comes after the Phase 2 rows and F22 (row 59). In practice it builds on three plans: F22
publication (receipts, `result_id`, outcome tokens, merged), DELIV (row 61: the CLI delivery sink
and its `SinkStage` protocol) and CLI-DB-SRC (row 64b: the Postgres secret reference, the
`pg-gate` CI lane and `decoy setup --postgres`).

Rules consulted: dev-rules `README.md` (routing), `00-universal.md`, `risk-and-exceptions.md` (R1, R2), `development-loop.md` (PLAN: proportion, guarantee, size, design notes, choke point, placement, established solutions), `destructive-operations.md` (truncate and overwrite of a database target), `data-and-migrations.md`, `security.md`, `config-secrets-and-supply-chain.md` (secret sourcing, redaction, no new dependency), `cross-cutting-concerns.md` (choke points), `architecture.md` (layout, fan-out, layers), `api-and-compatibility.md` (additive union member, frozen surfaces), `testing.md` (test depth T0 to T4, escalation triggers), `observability-and-resilience.md` (timeouts, reconcile), `reuse-first.md`, `workspace-and-vcs.md` (commit messages), `catalogs/recurring-defects.md` (classes 1 to 11); engine and CLI `CODEMAP.md` "Where Things Go"; CLI `docs/ROADMAP.md` rows 59, 61, 62, 64b, 85 and 86; engine plans `2026-10-29-f22-atomic-idempotent-publication.md` (database adapter contract, its line 124), `2026-10-30-f22-publication-replan.md` (rev 11), `plan/deliv:2026-11-12-deliv.md` (rev 3.5) and `plan/cli-db-src:2026-11-17-cli-db-src.md` (rev 1); vault notes `10_Projects/decoy/v2/duckdb/12-database-writeback.md` (earlier V2 proposal, superseded here) and the MASTER F01 section. Code read from `origin/main` on 2026-11-17 (engine `902968682`, tag `v0.27.0`; CLI `5b49510`, pin `decoy-engine==0.27.0`).

Anchors: a path with no prefix is in decoy-engine; a path with the prefix `C:` is in the CLI
repository (decoy).

Risk: R2 overall (data handling, a destructive write to a database, credentials, value leaks).
The destructive write is the product doing what the user configured at run time, not a
development-time side effect, so it is not an R3 action for this work; the
`destructive-operations.md` controls become product behaviour instead: exact target resolution
and a read-only preview on every run (4.3), an explicit per-table authorization word (`mode:
replace`), bounded execution (timeouts, one transaction) and reconcile (4.4). The engine half
ships in engine **0.29.0**, the release after the 0.28.0 that carries the CLI-DB-SRC engine
half. If the daily release train cuts 0.29.0 before slice E3 merges, the engine half ships in
the first engine release cut after E3 merges, and the CLI repin in C1 names that version.

## 1. Guarantee and non-goals

### 1.1 What this change promises

1. A pipeline may declare Postgres targets, one per table:
   `targets.<table>: {type: postgres, connection_ref: <secret ref>, schema: <ident>, table:
   <ident>, mode: replace}`. The config holds no host, user, password or database name; the
   whole libpq connection string is behind `connection_ref` (an F13 `env:` or `file:` reference,
   the `postgres-dsn-v1` requirement from row 64b). `mode` is required and V1 accepts only
   `replace`.
2. **All or nothing.** A `decoy run` with Postgres targets either replaces the contents of every
   target table and commits, or leaves every target table, index, constraint, trigger, sequence
   and the bookkeeping row exactly as they were. This holds for a refusal, a constraint failure,
   a load failure, a deadline, a lost connection before `COMMIT`, Ctrl-C and SIGKILL of the
   process. All target writes happen in **one** PostgreSQL transaction (pg_restore
   `--single-transaction`).
3. **Readers never see a mix.** A concurrent reader of the target tables sees the complete old
   contents or the complete new contents, never an empty or half-loaded table. The publisher
   holds `ACCESS EXCLUSIVE` locks on every target table from the truncate to the commit, so a
   reader waits instead.
4. **Application-ready.** After a publish, the structure the application created is in place and
   working: every primary key, unique, exclusion, check and foreign key constraint, every index
   (including partial and expression indexes), every user trigger (enabled as before), every
   identity column with its `ALWAYS` or `BY DEFAULT` kind, every generated column (recomputed by
   the server), and every sequence owned by a target column set so the next default value is
   above the loaded maximum. The first application insert that relies on a default key succeeds.
5. **Type-mapping report.** Before any write to the target, the engine maps each column of the
   staged masked Parquet (canonical Arrow type) to the target column type and classes the pair
   `exact`, `normalized`, `lossy`, `unsupported` or `generated`. Any `lossy` or `unsupported`
   pair, a missing column or an extra column refuses the run before the target is touched. The
   report is a versioned, value-free document (`decoy-pg-type-map/v1`) shown on the run card
   and in `--json`.
6. **Retry and race safety.** The publication is recorded in the same transaction in
   `decoy_meta.publications` (one row per target schema: `operation_id`, `result_id`, engine
   version). A retry of a committed operation with the same result returns `already_committed`
   and writes nothing; the same `operation_id` with a different result is
   `publication_operation_conflict`; a different writer that published between this run's check
   and its commit makes this run fail with `delivery_pointer_moved` and roll back (F22 database
   adapter contract, `2026-10-29` plan line 124). A lost `COMMIT` acknowledgement is reconciled by
   reading that row on a new connection.
7. **Safe before writing.** The target is inspected read-only before any source row is read:
   the relations exist, the role has the privileges it needs, no unsupported object is attached,
   no table outside the declared set references a target table, and the target database is not
   the database of any Postgres source.
8. **Value-free.** The connection string, the password, the host and every data value never
   appear in an error, a log line, the run card, `--json`, the run folder, the type-mapping
   report, a receipt, telemetry or an exception chain (`__cause__` and `__context__` are `None`
   on every refusal). PostgreSQL error text (which can carry `Key (id)=(42)`) is never read.
   Errors carry a registered code and a location (`targets.<table>.<field>`, `schema.table`,
   `schema.table.column` or `schema.table.constraint`).

### 1.2 Non-goals (findings here become follow-ups, not blockers)

- `create`, `append` and `upsert` modes (V2). V1 needs the target structure to exist: created by
  the application's migrations or by `pg_dump --schema-only | psql` (documented recipe).
- Creating, altering or migrating target structure. A target column type is never changed and
  no table is created except the bookkeeping table.
- A staging-schema rename swap (readers that never wait). Recorded as the V2 option (Q1).
- Partitioned tables, inheritance, rules, `FORCE ROW LEVEL SECURITY` and foreign keys from tables
  outside the declared set: refused before writing (Q9).
- Refreshing materialized views that read the target tables (documented: refresh after a run).
- More than one target schema or connection per pipeline, and Postgres targets mixed with file
  or cloud targets in one pipeline (Q3).
- `delivery.mode: best_effort` with Postgres targets (Q4).
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
| PostgreSQL `pg_restore` (postgresql.org/docs/current/app-pgrestore.html): `--single-transaction`, `--section=pre-data,data,post-data`, `--disable-triggers` | One `BEGIN`/`COMMIT` so "either all the commands complete successfully, or no changes are applied". Data loads before post-data items (indexes, triggers, rules, constraints other than validated check constraints). Triggers are disabled during a data-only restore | One transaction for every target write. Load order follows the sections: drop post-data items, load data, re-create post-data items in pg_dump order (primary key and unique, then other indexes, then foreign keys). User triggers are disabled during the load and re-enabled before commit (Q6). Check and NOT NULL constraints stay in place, as pg_restore keeps validated check constraints in pre-data |
| pgloader (pgloader.readthedocs.io/en/latest/ref/pgsql.html): `truncate`, `disable triggers`, `drop indexes`, `create indexes`, `foreign keys`, `reset sequences` | Truncate before load; drop indexes before load and re-create them "at the end of the data copy"; re-create foreign keys; reset sequences "to the current maximum column value" after loading and after the indexes are created | Same steps in the same order, inside our one transaction. Sequences owned by a target column go to `max(column)`; an empty table resets to the sequence start (Q7) |
| PostgreSQL transactional DDL and `TRUNCATE` (MVCC docs: `TRUNCATE` is transaction-safe, takes `ACCESS EXCLUSIVE`) | A rolled-back `TRUNCATE`, `DROP INDEX` or `ALTER TABLE` leaves nothing behind; a session that dies before `COMMIT` is aborted by the server | Rollback is the recovery path. No litter on the target: a killed attempt leaves nothing to reclaim |
| DuckDB postgres extension (duckdb.org/docs/2.0/core_extensions/postgres/overview.html) | Read-write `ATTACH`; `INSERT`, `CREATE TABLE` and `COPY` "directly modify the PostgreSQL database"; `COPY` uses "PostgreSQL binary wire encoding"; a `BEGIN ... ROLLBACK` example undoes an insert; `postgres_execute` runs arbitrary statements. Not stated: whether `postgres_execute` joins the open transaction | Loads run as `INSERT INTO <pg>.<schema>.<table> SELECT ... FROM read_parquet(...)` inside one DuckDB transaction. AT-E0 pins that DDL through `postgres_execute`, `TRUNCATE` and the inserts share one PostgreSQL transaction before anything else is built (Q15). No new dependency; the extension is the one row 64b installs |
| F22 database adapter contract (engine `docs/plans/2026-10-29-f22-atomic-idempotent-publication.md:124`) | Publish all rows and a unique `(destination, operation_id)` record in one database transaction; on retry read that row and compare content; serialize conflicts by a lock plus isolation | `decoy_meta.publications` row written in the publish transaction, under `pg_advisory_xact_lock`, read `FOR UPDATE`, compared by `result_id` (never by `operation_id` alone, F22 rule D) |
| git `update-ref <ref> <new> <old>` (DELIV 3, the `LATEST` compare-and-swap) | Write last with the expected old state | The publish refuses when the bookkeeping row differs from what the read-only inspection saw (`delivery_pointer_moved`) |
| PostgreSQL docs, "Populating a Database" (14.4) | Remove indexes and foreign keys before a bulk load, re-create after; run `ANALYZE` afterwards | Same; `ANALYZE` of the target tables after commit, a failure is a warning (Q14) |
| In-repo: `postgres_snapshot` (`src/decoy_engine/connectors/postgres_snapshot.py:217`, `:246`, `:271`) | Offline extension load, DuckDB connection with auto-install off, constant catalog SQL, coded value-free errors | Reused by moving the connection and extension helpers into one private session module (E1); the target opens the same way and differs only in a read-write `ATTACH` |

Rejected: a staging schema plus `ALTER SCHEMA ... RENAME` swap (the V2 proposal in the wiki and
dbt's table swap). It needs every index, constraint, sequence, trigger, grant and owner rebuilt
from catalog text in a new schema, and the rename leaves views, functions and cached plans that
reference the old tables by OID pointing at the old schema. The in-place transaction keeps every
OID, grant and dependent object, so "application-ready" holds by construction. Its cost is that
readers wait for the load (Q1).

Custom code left: the catalog reads (constant SQL), the type-map rules table, the value guards,
the ordered publish steps and reconcile. Everything else is reuse.

## 3. Reuse inventory

| Need | Existing mechanism (reused, not copied) | Anchor |
|---|---|---|
| DuckDB connection with offline extension load | `_open_connection`, `_load_postgres_extension` (moved, not copied, in E1) | `src/decoy_engine/connectors/postgres_snapshot.py:217`, `:246` |
| Identifier rule and quoting | `_IDENT_RE`, `_validate_ident`, `_q`, `_lit` (moved with the session helpers) | `src/decoy_engine/connectors/postgres_snapshot.py:74`, `:136`, `:204` |
| Coded value-free error | `PostgresSnapshotError` (the target error subclasses it, so the existing CLI arm and code owner hold) | `src/decoy_engine/connectors/postgres_snapshot.py:116` |
| Type classes of the source side | `_PLAIN_TYPES`, `_classify` (the type map reads the same lists, so source and target agree on what is lossless) | `src/decoy_engine/connectors/postgres_snapshot.py:92`, `:285` |
| Secret reference and `postgres-dsn-v1` | `prepare_secret`, `POSTGRES_DSN_V1` (row 64b E1) | `src/decoy_engine/secret_providers/_requirements.py:42` |
| Pipeline-level staging pattern and settings | `stage_postgres_sources`, `PostgresSourceSettings` (row 64b E2) | engine `execution/pipeline/_postgres_source.py` (64b, not yet merged) |
| Result identity of the staged Parquet | `Artifact`, `compute_result_id` | `src/decoy_engine/publication/_descriptor.py:122`, `:224` |
| Receipt and outcome tokens | `CommitReceipt`, `Outcome`, `raise_for_outcome`, `PublicationRefused` | `src/decoy_engine/publication/_types.py:58`, `:128`, `:223` |
| Publication reason codes | `publication_operation_conflict`, `publication_commit_not_visible`, `publication_target_occupied`, `delivery_pointer_moved` | `src/decoy_engine/reasons/decoy/_core.py:213`, `:220`, `:227`; `src/decoy_engine/reasons/decoy/_delivery.py:37` |
| Delivery decision and target set | `plan_delivery`, `DELIVERABLE_TARGET_TYPES` | `src/decoy_engine/delivery/_plan.py:24`, `:106` |
| Destination identity and the two-tables-one-destination refusal | `_target_identity` (engine #592) | `src/decoy_engine/config/_targets.py:141` |
| Canonical JSON for the report document | `decoy_engine._canonical.canonical_json_bytes` | `src/decoy_engine/publication/_descriptor.py:5` |
| Row-holding scratch, removed on exit | `protected_scratch_dir`; CLI `library/_scratch.allocate` | `src/decoy_engine/fileaccess/_protected_dir.py:268`; `C:src/decoy/cli/library/_scratch.py:122` |
| CLI delivery sink and stage protocol | `DeliverySink`, `SinkStage` (`abort`, `deliver(decision, before_visible)`), `PublishedOutput`, `PreVisible` (DELIV C2a) | DELIV plan 4.6 |
| CLI exception-to-exit map | `exit_code_for` | `C:src/decoy/cli/exit_codes.py:163` |
| Postgres CI lane, fixtures, zero-skip guard | `pg-gate` job, `pg_dsn`, `ext_dir`, `PgAdmin`, `DECOY_REQUIRE_PG`, `junit_ran.py` (row 64b E1) | `tests/connectors/conftest.py:52` |
| Extension install | `decoy setup --postgres` (row 64b C2) | 64b plan 4.4 |

No second copy of the connection setup, the identifier rule, the secret resolution, the result
identity, the outcome tokens, the exit map or the scratch allocator.

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

- `target_postgres.identifier_invalid` (`schema`, `table`): fails the one identifier rule.
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
  `lock_timeout_s=30`.
- `TargetRelation(schema_name, table)`, validated by the one identifier rule.
- `read_target(config, relations) -> TargetCatalog`. One read-only `ATTACH`, constant catalog
  SQL in `connectors/postgres_target_catalog.py`, no data row read. It collects, per relation:
  columns (name, `format_type`, `attnotnull`, `attgenerated`, `attidentity`, enum labels for
  enum types), indexes (`pg_get_indexdef`, constraint-backed or not), constraints
  (`pg_get_constraintdef`, kind), user triggers and their enabled state, owned sequences
  (`pg_depend` auto or internal dependency on a column), privileges (`TRUNCATE`, `INSERT`,
  ownership for `ALTER TABLE`), the server fingerprint digest (SHA-256 of `current_database()`,
  `pg_postmaster_start_time()` and `inet_server_port()`, never shown), the bookkeeping row for
  the target schema (or its absence) and a structure digest over everything above. It refuses
  (connector namespace, location `schema.table`):
  - `relation_not_found` (existing code);
  - `target_object_unsupported`: partitioned table, inheritance parent or child, a rewrite
    rule, `FORCE ROW LEVEL SECURITY`;
  - `target_external_reference`: a foreign key from a table outside the declared set to a
    target table (a `TRUNCATE` would need `CASCADE`, which would delete rows Decoy was not asked
    to touch);
  - `target_privilege_missing`: no `TRUNCATE` or `INSERT`, not the owner (or a member of the
    owning role), or `decoy_meta.publications` absent and no `CREATE` on the database;
  - `target_unreachable`, `catalog_read_failed`, `extension_unavailable`,
    `extension_untrusted_location`, `duckdb_unavailable`, `deadline_exceeded`.
  The catalog read decodes the bookkeeping row strictly (4.6); an unreadable row refuses with
  `publication_target_occupied` (existing decoy code).
- `plan_target(catalog, staged: Mapping[str, Path]) -> TargetPlan`. Builds the type-mapping
  report from each staged Parquet footer (4.5), refuses `target_column_mismatch` (a target
  column missing from the Parquet or a Parquet column missing from the target, generated columns
  excepted) and `target_type_blocked` (any `lossy` or `unsupported` pair), then runs the value
  guards on the staged Parquet through DuckDB: string length for `varchar(n)`, enum label
  membership, no null in a `NOT NULL` column, numeric range when the Arrow decimal is wider than
  the target. A guard failure is `value_guard_failed` (existing code) at `schema.table.column`.
  The guards return counts only; no value is read into Python. `TargetPlan` also carries the
  artifact list and `result_id` (`compute_result_id` over the staged files, role `table`).

### 4.4 Engine: publish (one transaction)

`publish_target(config, plan, operation_id) -> CommitReceipt`. One DuckDB connection, one
read-write `ATTACH`, one DuckDB transaction that is one PostgreSQL transaction (AT-E0). Steps,
in order; each step has a fixed name used for the error location and the test fault seam:

1. `begin`: `BEGIN`; `SET LOCAL search_path = pg_catalog` (captured definitions are fully
   qualified, as pg_dump writes them); `SET LOCAL lock_timeout` and `statement_timeout`.
2. `lock_writer`: `pg_advisory_xact_lock` on a key derived from the target schema name, under
   `lock_timeout`. A timeout is `target_busy`.
3. `check_marker`: create `decoy_meta` and `decoy_meta.publications` if absent; read the row for
   the schema `FOR UPDATE`. Same `operation_id` and same `result_id`: roll back and return
   `already_committed` (nothing written). Same `operation_id`, other `result_id`: roll back,
   `operation_conflict` with `publication_operation_conflict`. Row differs from
   `catalog.marker`: roll back, `refused` with `delivery_pointer_moved`.
4. `check_structure`: re-read the structure digest; a difference from `catalog` (an index,
   constraint, column, trigger or privilege changed since inspection) is `target_changed`.
5. `lock_tables`: `LOCK TABLE ... IN ACCESS EXCLUSIVE MODE` on every target table, in sorted
   order, under `lock_timeout` (`target_busy`).
6. `drop_post_data`: drop every foreign key with either end in the set, then every
   constraint-backed index (primary key, unique, exclusion) through `ALTER TABLE ... DROP
   CONSTRAINT`, then every other index; `DISABLE TRIGGER USER` on each table; identity columns
   declared `ALWAYS` become `BY DEFAULT` so the load can write them.
7. `truncate`: one `TRUNCATE` of every target table.
8. `load`: per table, `INSERT INTO <pg>.<schema>.<table> (<columns except generated>) SELECT
   <same columns> FROM read_parquet(<staged path>)`, then a row count in the transaction compared
   with the Parquet footer (`target_load_failed` at `schema.table` on any failure or difference).
9. `restore_post_data`: re-create, from the definitions captured in `catalog`, primary key and
   unique and exclusion constraints, then the other indexes, then foreign keys (validated); a
   failure is `target_constraint_failed` at `schema.table.constraint` (or `.index`). Re-enable
   triggers exactly as they were; restore identity kinds.
10. `sequences`: for each sequence owned by a target column, `setval(seq, max(col))`, or
    `setval(seq, start, false)` when the table is empty. Executed in SQL on the server; no value
    reaches Python. Sequences not owned by a target column are not touched.
11. `write_marker`: upsert the bookkeeping row (format tag, schema, `operation_id`, `result_id`,
    engine version, `now()`).
12. `commit`: `COMMIT`. The visibility point.

After a successful commit: `ANALYZE` each target table on a fresh statement; a failure is a
warning on the receipt path (logged with code only), never a failed publish.

Failure handling, the same for every step: the error is caught, only `type(exc).__name__` is
kept, DuckDB `ROLLBACK` runs and the connection closes (the server aborts the transaction either
way), and then, outside the `except` block, a probe on a new connection decides the code: if
the server cannot be reached the code is `target_unreachable`, else the step's code. PostgreSQL
error text is never read.

Reconcile after `commit` raises: a new read-only connection reads the bookkeeping row. This
`operation_id` and `result_id`: `published` (the commit landed). Anything else:
`failed` with `publication_commit_not_visible` (the commit did not land; the target is the old
one). No connection within `lock_timeout_s`: `PostgresTargetError(target_commit_unknown)`; the
CLI exits 3 and says the outcome is unknown and names the schema to check. The engine never
retries a commit.

Deadline: a timer interrupts DuckDB at `deadline_s`, as the snapshot does
(`src/decoy_engine/connectors/postgres_snapshot.py:470`); the transaction rolls back;
`deadline_exceeded`.

### 4.5 Type-mapping rules

Canonical type is the Arrow type in the staged Parquet footer. Target type is
`format_type(atttypid, atttypmod)` from the target catalog.

| Arrow | Target | Class | Guard |
|---|---|---|---|
| int16, int32, int64 | smallint, integer, bigint of equal or wider width | exact | none |
| int of wider width than the target | narrower integer | lossy | n/a |
| float32 / float64 | real / double precision | exact | none |
| float64 | real | lossy | n/a |
| bool | boolean | exact | none |
| decimal128(p, s) | numeric(p2, s) with p2 >= p, or numeric with no typmod | exact | none |
| decimal128(p, s) | numeric(p2, s) with p2 < p | normalized | range |
| decimal128(p, s) | numeric(p2, s2) with s2 != s | lossy | n/a |
| string | text, json | exact | none |
| string | character varying(n) | normalized | length |
| string | character varying (no n) | exact | none |
| string | jsonb, uuid | normalized (server re-serializes, parse refuses bad input in `load`) | none |
| string | an enum type | normalized | enum labels |
| string | character(n) | lossy (blank padding) | n/a |
| date32 | date | exact | none |
| timestamp[us] | timestamp without time zone | exact | none |
| timestamp[us, tz] | timestamp with time zone | normalized (instant kept, zone shown as UTC) | none |
| timestamp[ns] (any zone) | any timestamp | lossy (truncation) | n/a |
| time64[us] | time without time zone | exact | none |
| binary | bytea | exact | none |
| list<T> | T[] where T maps exact | exact | none |
| any | a stored generated column | generated (left out of the load, recomputed) | none |
| anything else | anything else | unsupported | n/a |

`NOT NULL` adds the null-count guard to any row. The report document: `schema:
decoy-pg-type-map/v1`, `target_schema`, and per column `table`, `column`, `arrow_type`,
`target_type`, `class`, `guard`; canonical JSON, sorted by table then column. It holds names and
type text only.

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
  `memory_limit`, `threads`, and the three timeouts.
- `open_postgres_target(config, settings) -> ContextManager[PostgresTargetHandle | None]`: `None`
  when the config has no Postgres target. Resolves `connection_ref` once with
  `prepare_secret(..., requirements=(POSTGRES_DSN_V1,))`, builds the relations, calls
  `read_target`. If the config also has Postgres sources, it compares the target fingerprint with
  the source fingerprint (64b's `StagedSources` gains a `server_fingerprint` digest field in E2,
  additive) and refuses `target_same_database` on equality.
- `PostgresTargetHandle.plan(staged)` and `.publish(plan, operation_id)`.
- `POSTGRES_TARGET_USAGE_CODES`: the codes that mean "fix the config, the target objects, the
  privileges or the data" (`relation_not_found`, `target_object_unsupported`,
  `target_external_reference`, `target_privilege_missing`, `target_column_mismatch`,
  `target_type_blocked`, `value_guard_failed`, `target_same_database`, `extension_unavailable`,
  `extension_untrusted_location`). The CLI maps these to exit 1 and every other target code to
  exit 3. The engine owns the classification; the CLI copies no code string.

`DELIVERABLE_TARGET_TYPES` (`src/decoy_engine/delivery/_plan.py:24`) gains `"postgres"`, so
`plan_delivery` expects an outcome for every Postgres target table.

### 4.8 CLI

- `prepare` (`C:src/decoy/cli/run/_prepare.py`): after the static gate and before any source is
  staged or read, enter `open_postgres_target` on the run `ExitStack`. A refusal here exits
  before any row is read. The run card prints the target schema, the table list and the
  operation id.
- `io/_postgres_target.py`: `PostgresTargetStage`, a `SinkStage` (DELIV 4.6). At open it
  allocates protected scratch (`library/_scratch.allocate`) and places each Postgres target
  table at `<scratch>/<table>.parquet` through the sink's `Placer`, so every route (plain,
  `--chunked`, isolated) writes Parquet there with the existing writers. `deliver(decision,
  before_visible)`: if `decision.deliver` is false, abort. Else `handle.plan(staged)`, then
  `before_visible()` (DELIV vault and evidence order), then `handle.publish(plan,
  operation_id)`; the visibility point is a `published` or `already_committed` receipt. `abort`
  removes the scratch. The scratch is removed on every exit.
- `operation_id`: the run's existing F22 operation id (DELIV 7.1), so an F23 resume of a run that
  already committed gets `already_committed`.
- `PublishedOutput` gains `PostgresOutput(schema, table)`; `display()` is `postgres:<schema>.<table>`
  (no reference, no host).
- Card and `--json`: a type-map summary (counts per class and every blocking row by
  `table.column`) on the card; `--json` gains `postgres_target: {schema, tables, outcome,
  type_map}` where `type_map` is the engine document (shape changelog entry).
- Exit codes: `exit_code_for` maps `PostgresSnapshotError` (and so `PostgresTargetError`) by
  `POSTGRES_SOURCE_USAGE_CODES | POSTGRES_TARGET_USAGE_CODES` to 1, otherwise 3;
  `target_postgres.*` config codes are 1; `PublicationRefused` with
  `publication_operation_conflict` or `delivery_pointer_moved` is 3 (retry after checking);
  the run classifier in `run/_errors.py` gets the same arm (held equal by
  `tests/unit/test_exit_code_for.py`).
- Ctrl-C: before the visibility point the engine rolls back and the run exits 130 with nothing
  delivered; after it the run is delivered (DELIV 4.6 rule).

## 5. Enumerations

### 5.1 Exit paths

- 0: published or `already_committed`; scratch removed (`C:src/decoy/cli/exit_codes.py:163`).
- 1: compile refusals (`target_postgres.*`, bad or unknown reference); secret not resolvable;
  any code in `POSTGRES_TARGET_USAGE_CODES` from `read_target` or `plan_target` (before any
  target write).
- 3: `target_unreachable`, `catalog_read_failed`, `target_busy`, `target_changed`,
  `target_load_failed`, `target_constraint_failed`, `target_commit_unknown`,
  `deadline_exceeded`, `duckdb_unavailable`, `publication_operation_conflict`,
  `delivery_pointer_moved`, `publication_commit_not_visible`, `publication_target_occupied`.
- 4: a post-scan block withholds the run (DELIV 4.2 step 4); the target is not opened for write.
- 5: capacity refusal from the gate, before any target write.
- 130: Ctrl-C before the commit (rolled back, `src/decoy_engine/connectors/postgres_snapshot.py:470` interrupt pattern).

### 5.2 Routes

- Plain `decoy run` (resident `run_pipeline`): writes staged Parquet through the sink's placer.
- `--chunked` and the automatic streaming route: chunked Parquet writer into the same placed
  path (`C:src/decoy/cli/io/_targets.py:466`).
- Isolated subprocess and out-of-core FK routes: the placed paths sit in the parent's scratch,
  entered on the parent `ExitStack`; the child writes there.
- Non-run callers with a Postgres target (`decoy.mask()`, `demo`, `tokenize`, `subset`): refused
  at the CLI I/O choke point `_require_local_io_endpoints` (`C:src/decoy/cli/run/_execute.py:238`)
  with `target_postgres.unsupported_command`, exit 1. Engine callers that pass a Postgres target
  descriptor to a file writer meet the refusal in the engine target writer dispatch (E1).
- `publish_tables` and `publish_unit` (`src/decoy_engine/publication/_publish.py:199`, `:338`):
  never reached for a Postgres target; the CLI stage calls the handle instead.

### 5.3 FK shapes

- Scalar FK between two target tables: dropped in `drop_post_data`, re-created and validated in
  `restore_post_data` after both tables load; a masked child that breaks it fails the run with
  `target_constraint_failed`, rolled back.
- Composite FK: same path; `pg_get_constraintdef` carries the column list and match type.
- Self-referencing FK: one table, dropped and re-created like any other.
- FK cycle between target tables: handled, because no FK exists during the load.
- FK from a non-target table to a target table: `target_external_reference` at inspection.
- FK from a target table to a non-target table (a lookup table not in the pipeline): dropped
  and re-created; the re-create validates the masked rows against the untouched lookup table.
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
  `table.column` names; no reference, host or value.
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
- Reason codes, all `since=UNRELEASED`: config `target_postgres.identifier_invalid`,
  `.multiple_connections`, `.multiple_schemas`, `.mixed_targets`, `.best_effort_unsupported`,
  `.target_is_source`, `.unsupported_command`; connector `target_unreachable`,
  `target_object_unsupported`, `target_external_reference`, `target_privilege_missing`,
  `target_column_mismatch`, `target_type_blocked`, `target_same_database`, `target_changed`,
  `target_busy`, `target_load_failed`, `target_constraint_failed`, `target_commit_unknown`.
  Existing code specs are unchanged. `REGISTRY_VERSION` and the reason manifests are not
  touched; the release stamps them.
- 64b's `StagedSources` gains `server_fingerprint` (additive field with a default).
- `decoy-error-v1` schema unchanged; the `--json` success shapes snapshot gains the
  `postgres_target` key (shape changelog entry in C2).
- New public engine names go on the frozen-surface map in the slice that adds them:
  `PostgresTarget`, `PostgresTargetConfig`, `TargetRelation`, `TargetCatalog`, `TargetPlan`,
  `PostgresTargetError`, `read_target`, `plan_target`, `publish_target`, `TypeMapEntry`,
  `TypeMapReport`, `map_types`, `PostgresTargetSettings`, `PostgresTargetHandle`,
  `open_postgres_target`, `POSTGRES_TARGET_USAGE_CODES`.
- No cap, pin ceiling, ratchet, sentry baseline or allowlist count is raised (class 11).

## 7. Failure modes and partial failure

| Case | What happens | Target afterwards | Test |
|---|---|---|---|
| Target reference unset or invalid material | existing secret refusal, exit 1, at prepare | untouched, never connected | AT-C3 |
| Target relation missing, partitioned, with a rule, FORCE RLS | inspection refusal, exit 1, before any row read | untouched | AT-E5, AT-C8 |
| Non-target table references a target table | `target_external_reference`, exit 1 | untouched | AT-E5 |
| Role lacks TRUNCATE, INSERT, ownership or CREATE for `decoy_meta` | `target_privilege_missing`, exit 1 | untouched | AT-E5 |
| Target is the source database | `target_same_database` (or compile `target_is_source`), exit 1 | untouched | AT-E7, AT-E2 |
| Lossy or unsupported type pair, missing or extra column | `target_type_blocked` / `target_column_mismatch`, exit 1, report shows the rows | untouched | AT-E3, AT-E6 |
| String longer than varchar(n), unknown enum label, null in NOT NULL | `value_guard_failed` at `table.column`, exit 1 | untouched | AT-E6 |
| Another Decoy publish holds the target | `target_busy` after `lock_timeout_s`, exit 3 | untouched | AT-E12 |
| An application transaction holds a table lock | `target_busy`, exit 3 | untouched | AT-E12 |
| Index or column changed after inspection | `target_changed`, rolled back, exit 3 | old contents | AT-E12 |
| Another writer published after inspection | `delivery_pointer_moved`, rolled back, exit 3 | other writer's contents | AT-E12 |
| Load fails or row count differs | `target_load_failed`, rolled back, exit 3 | old contents, old indexes | AT-E9 |
| Masked rows break a FK or unique constraint | `target_constraint_failed` at the constraint, rolled back, exit 3 | old contents | AT-E9 |
| Failure in any step 1 to 11 | rolled back by the transaction | old contents | AT-E9 |
| Connection lost before COMMIT | server aborts; `target_unreachable`, exit 3 | old contents | AT-E9, AT-E13 |
| COMMIT sent, acknowledgement lost | reconcile: `published` (exit 0) or `publication_commit_not_visible` (exit 3) | new or old, reported correctly | AT-E13 |
| Reconcile cannot connect | `target_commit_unknown`, exit 3, message names the schema to check | unknown, never retried | AT-E13 |
| Deadline passes | interrupt, rollback, `deadline_exceeded`, exit 3 | old contents | AT-E9 |
| Ctrl-C before commit | rollback, exit 130, scratch removed | old contents | AT-C5 |
| SIGKILL of the CLI mid-load | server aborts on disconnect | old contents, no litter | AT-E11 |
| Retry of a committed operation, same result | `already_committed`, exit 0, nothing written | unchanged | AT-E12 |
| Same operation id, different result | `publication_operation_conflict`, exit 3 | unchanged | AT-E12 |
| `ANALYZE` fails after commit | warning, exit 0 | new contents | AT-E8 |
| Post-scan blocks the run | target never opened for write, exit 4 | untouched | AT-C1 |
| A row error text carries a value | text never read; code and location only | n/a | AT-E14 |

## 8. Acceptance tests (red first)

Each test is written first and fails on `origin/main` (or on the slice base) for the stated
reason, then passes on the slice head. `pg_integration` tests run in `pg-gate`
(`DECOY_REQUIRE_PG=1`, zero skips); the others run in the default suites. Each named mutation
must turn its test red on the final slice head (class 9).

### 8.1 Engine

| Id | Test | Red because | Mutation that must turn it red | Slice |
|---|---|---|---|---|
| AT-E0 | `tests/connectors/test_postgres_write_session.py` (pg): in one DuckDB transaction over a read-write ATTACH, a `postgres_execute` DDL, a `TRUNCATE` and an `INSERT ... SELECT FROM read_parquet` are invisible to a second libpq session before `COMMIT`, and all three are undone by `ROLLBACK` and by closing the connection | no write session | open the write session without `BEGIN` (autocommit) | E1 |
| AT-E1 | `tests/unit/config/test_postgres_target.py`: a `type: postgres` target parses; missing `mode`, `mode: append`, extra keys, empty strings, a bool and an int in each string field are refused with input hidden; `connection_ref` is a locator field; two tables on one `(ref, schema, table)` hit the duplicate-destination refusal | no variant | drop the postgres arm of `_target_identity` | E1 |
| AT-E2 | `tests/unit/plan/test_postgres_target_check.py`: identifier cells including `"ok\n"`, two refs, two schemas, a postgres plus a file target, `best_effort`, target ref equal to a source ref, `vault://x` are each refused with their code and location; the text never holds the ref | no check | replace `fullmatch` with `match` and `$` in the shared rule | E1 |
| AT-E3 | `tests/unit/connectors/test_postgres_typemap.py`: one cell per row of 4.5, including int narrowing, float64 to real, `timestamp[ns]`, decimal scale change, `character(n)`, generated column; missing and extra columns; the document is canonical bytes, sorted, tagged `decoy-pg-type-map/v1`, and its schema snapshot matches | no module | class `timestamp[ns]` to `timestamp` as `exact` | E1 |
| AT-E4 | `tests/sentry/test_postgres_session_choke_point.py`: in `connectors/`, `connect_internal` and `LOAD postgres` appear only in `_postgres_session.py`, and an `ATTACH` without `READ_ONLY` appears only in `postgres_target.py`; seeded cells for each fail. Existing `test_postgres_snapshot*` pass unchanged (negative control) | helpers live in the snapshot module | add a read-write ATTACH to `postgres_snapshot.py` | E1 |
| AT-E5 | `tests/connectors/test_postgres_target_inspect.py` (pg): missing relation, partitioned table, inheritance child, rule, FORCE RLS, external FK, a role without TRUNCATE, a non-owner role and absent `decoy_meta` without CREATE all refuse with their codes at `schema.table`; `pg_stat_user_tables` counters, `pg_namespace` and the catalog digest are unchanged afterwards | no `read_target` | skip the external-reference query | E2 |
| AT-E6 | same folder, `test_postgres_target_plan.py` (pg): over-length varchar, unknown enum label, null into NOT NULL, numeric overflow each refuse with `value_guard_failed` at `schema.table.column`; a blocked type refuses with `target_type_blocked`; no target statement runs (spy on the write session: never opened) | no `plan_target` | run the guards after `publish_target` opens its session | E2 |
| AT-E7 | `test_postgres_target_inspect.py` (pg): a pipeline whose source and target references name the same database refuses `target_same_database` from `open_postgres_target`; a second database on the same server passes (negative control) | no fingerprint | compare by reference text only | E2 |
| AT-E8 | `tests/connectors/test_postgres_target_publish.py` (pg): three tables with an FK chain, a serial key, an `ALWAYS` identity, a stored generated column, an enum, a partial index, an expression index, a unique, a check, a deferrable FK and an audit trigger. After publish: Arrow readback equals the staged Parquet for every non-generated column; generated values match the server's recomputation; the sets of `pg_get_indexdef` and `pg_get_constraintdef` and trigger enabled states equal the pre-run sets; identity kinds are unchanged; the audit table is empty (trigger did not fire during load); an `INSERT` with default keys succeeds on every table; `ANALYZE` ran (`last_analyze` set); an injected `ANALYZE` failure still returns `published` | no publish | skip `sequences` (the default-key insert hits a duplicate key) | E3 |
| AT-E9 | same file (pg): a fault injected at each of the twelve steps (test seam), a masked child row that breaks an FK, a value the server refuses in `load`, a 1 s deadline on a slow load and a server-side `pg_terminate_backend` before `COMMIT` each leave the catalog digest, the row digests of every target table and the bookkeeping row equal to their pre-run values, with the expected code | no publish | commit after `load` and open a second transaction for `restore_post_data` | E3 |
| AT-E10 | same file (pg): a reader thread loops `SELECT count(*)` over the three tables in one REPEATABLE READ transaction per iteration during a publish; every observed triple is the old triple or the new triple | no publish | `TRUNCATE` and `COMMIT` before the load | E3 |
| AT-E11 | same file (pg): a subprocess publisher is SIGKILLed after the first table loads; once the server reaps the backend the target equals the pre-run state and no `decoy_meta` row changed | no publish | autocommit the `TRUNCATE` | E3 |
| AT-E12 | same file (pg): retry with the same operation and result returns `already_committed` with no write (`n_tup_ins` unchanged); same operation, other result: `publication_operation_conflict`; a bookkeeping row changed after `read_target`: `delivery_pointer_moved`; an index added after `read_target`: `target_changed`; a second publisher holding the advisory lock and an application transaction holding a row lock: `target_busy` within `lock_timeout_s + 2` s. Every case leaves the target unchanged | no publish | judge the retry by `operation_id` alone | E3 |
| AT-E13 | same file (pg): the commit wrapper raises after a real `COMMIT` (reconcile finds the row: `published`); raises instead of committing (`publication_commit_not_visible`, target unchanged); raises and the reconcile connection is refused (`target_commit_unknown`); the commit is attempted exactly once in every case | no reconcile | retry the commit on error | E3 |
| AT-E14 | same file (pg): a DSN with a marker password, a wrong host, and a staged row carrying a marker string that breaks a unique constraint: the marker is absent from the error `str`, `repr`, formatted traceback with chains, every log record captured at DEBUG, the receipt and the type-map document; every raised error has `__cause__` and `__context__` `None` | no publish | raise `PostgresTargetError` inside the `except` block in one step | E3 |
| AT-E15 | `tests/unit/publication/test_pg_publication_row.py`: the bookkeeping row reader refuses a missing or unknown `format`, `"op\n"` as operation id, uppercase hex, a 63-character `result_id` and a bool in a text column; the writer's row round-trips; schema snapshot | no reader | read `format` with `startswith` | E2 |

### 8.2 CLI

| Id | Test | Red because | Mutation that must turn it red | Slice |
|---|---|---|---|---|
| AT-C1 | `tests/e2e/postgres_target/test_run_postgres_target.py` (pg): `decoy run` from CSV sources and from Postgres sources into a Postgres target exits 0; the target rows equal the Parquet of the same run with file targets; no `decoy-*` scratch remains; the card shows the type-map summary; `--json` carries `postgres_target`; a post-scan block exits 4 and the target is unchanged | no stage | publish before the post-scan verdict | C1 |
| AT-C2 | same folder (pg): `--chunked` gives target rows equal to the plain run | no stage | place the chunked writer at a non-scratch path | C1 |
| AT-C3 | same folder (pg): unset reference env var (1), missing privilege (1), blocked type (1), guard failure (1), unreachable host (3), constraint failure (3), busy (3): each with its code; the target is unchanged; stderr, `--json`, the run folder and captured logs hold no DSN marker, no reference text and no data marker | no wiring | map `PostgresTargetError` through `str(exc)` into the error line | C1 |
| AT-C4 | `tests/e2e/postgres_target/test_compile_refusals.py`: `best_effort`, mixed targets and two schemas exit 1 from `decoy validate` and `decoy run` with their codes; `decoy validate` opens no socket (socket spy) | no check wiring | open the target in `validate` | C1 |
| AT-C5 | same folder (pg): SIGINT during `load` exits 130 with the target unchanged and no scratch; a SIGINT injected right after the commit records the run as delivered | no stage | treat a post-commit interrupt as not delivered | C2 |
| AT-C6 | `tests/unit/test_exit_code_for.py`: `PostgresTargetError` with each code in `POSTGRES_TARGET_USAGE_CODES` maps to 1, `target_busy` and `target_commit_unknown` to 3, `PublicationRefused(delivery_pointer_moved)` to 3; the run classifier agrees | no arm | drop the target usage set from the arm | C1 |
| AT-C7 | `tests/e2e/postgres_target/test_non_run_callers.py`: `decoy.mask()`, `demo`, `tokenize` and `subset` with a Postgres target exit 1 with `target_postgres.unsupported_command` and never connect | no refusal | remove the postgres arm in `_require_local_io_endpoints` | C1 |
| AT-C8 | same folder (pg): a missing target relation refuses at prepare and a spy on the source reader shows no row read | no prepare call | open the target after the run | C1 |
| AT-C9 | `tests/e2e/release_freeze/test_json_shapes.py` (snapshot updated) and the shape changelog check: the `postgres_target` key is recorded | key not in snapshot | drop the shape changelog entry | C2 |

## 9. Placement

Engine (rows of `CODEMAP.md` "Where Things Go"; `execution/` gets no new top-level file; the
package root is at its fan-out cap and gets no new module):

| File | New or changed | CODEMAP row | Sits beside |
|---|---|---|---|
| `src/decoy_engine/config/_targets.py` | changed (`PostgresTarget`, union, identity arm) | Config models | `S3Target`, `GCSTarget` |
| `src/decoy_engine/plan/checks/_postgres_targets.py` | new | Plan compile and checks: `plan/checks/_<topic>.py` | 64b `plan/checks/_postgres_sources.py` |
| `src/decoy_engine/connectors/_postgres_session.py` | new (moved helpers plus the write session) | Connectors (private helper of the package) | `postgres_snapshot.py` |
| `src/decoy_engine/connectors/postgres_snapshot.py` | changed (imports the moved helpers; no behaviour change) | Connectors | itself |
| `src/decoy_engine/connectors/postgres_typemap.py` | new | Connectors: `connectors/<name>.py` | `postgres_snapshot.py` |
| `src/decoy_engine/connectors/postgres_target_catalog.py` | new | Connectors | `postgres_typemap.py` |
| `src/decoy_engine/connectors/postgres_target.py` | new | Connectors | `postgres_snapshot.py` |
| `src/decoy_engine/connectors/__init__.py` | changed (exports) | Connectors | itself |
| `src/decoy_engine/execution/pipeline/_postgres_target.py` | new | Pipeline spine: `execution/pipeline/` | 64b `execution/pipeline/_postgres_source.py` |
| `src/decoy_engine/delivery/_plan.py` | changed (one token) | (delivery package, DELIV E1a) | itself |
| `src/decoy_engine/reasons/config/_part2.py`, `src/decoy_engine/reasons/connector/_part1.py` | changed (new codes) | Reason codes | existing catalogs |
| `src/decoy_engine/__init__.py` | changed (exports, frozen-surface rows) | Public API | facade list |
| `tests/connectors/test_postgres_write_session.py`, `test_postgres_target_inspect.py`, `test_postgres_target_plan.py`, `test_postgres_target_publish.py` | new | `tests/connectors/` (listed exception) | snapshot suites |
| `tests/unit/config/test_postgres_target.py`, `tests/unit/plan/test_postgres_target_check.py`, `tests/unit/connectors/test_postgres_typemap.py`, `tests/unit/publication/test_pg_publication_row.py` | new | Unit tests mirroring `src/` | owning package tests |
| `tests/sentry/test_postgres_session_choke_point.py` | new | Sentry test (existing rules folder) | `tests/sentry/test_support_no_network.py` |
| `.github/workflows/ci.yml` (`pg-gate` file list), `tests/sentry/file_access_modules.toml`, `tests/sentry/file_access_registry.toml`, physical-seam allowlist | changed (new marked files; one exact `(path, name)` row per new module) | CI lane registries; sentry registries | existing rows |
| `docs/postgres-target.md`, `docs/index.md`, `changelog.d/f01-e1.md`, `changelog.d/f01-e2.md`, `changelog.d/f01-e3.md` | new or changed | Feature docs; changelog fragments | `docs/publication.md`, 64b `docs/postgres-source.md` |

`connectors/` holds 7 modules today plus 64b's one or two; four new modules keep it far under
any fan-out concern. A connectors sub-package was considered and rejected: the map names
`connectors/<name>.py` and moving `postgres_snapshot.py` is churn.

CLI (flat `src/decoy/cli/` gets no new file):

| File | New or changed | CODEMAP row | Sits beside |
|---|---|---|---|
| `src/decoy/cli/io/_postgres_target.py` | new (`PostgresTargetStage`, `PostgresOutput`) | Source readers and target writers: `src/decoy/cli/io/` | DELIV `io/_delivery.py`, 64b `io/_postgres.py` |
| `src/decoy/cli/io/__init__.py`, `src/decoy/cli/io/_delivery.py` | changed (export; stage construction for the postgres kind; `PublishedOutput` arm) | same | facade |
| `src/decoy/cli/run/_prepare.py` | changed (open the target on the `ExitStack`) | `decoy run` internals | 64b staging block |
| `src/decoy/cli/run/_execute.py` | changed (`_require_local_io_endpoints` arm) | `decoy run` internals | cloud refusal |
| `src/decoy/cli/exit_codes.py`, `src/decoy/cli/run/_errors.py` | changed (one arm each) | Exit codes | itself |
| `src/decoy/ui/summary.py` | changed (type-map card lines) | Terminal output | run card extras |
| `pyproject.toml` (pin), `.github/workflows/ci.yml` (`pg-gate` file list) | changed | CI and lane policy | 64b rows |
| `tests/e2e/postgres_target/` (conftest reusing 64b's `pg_dsn`, `ext_dir`, `DECOY_REQUIRE_PG`) | new folder | map change in C1: add it to the tests cell of the Source readers and target writers row | `tests/e2e/postgres_source/` |
| `docs/guides/postgres-target/README.md`, README target list, CHANGELOG, shape changelog, `docs/ROADMAP.md` row 86 and shipped log, `docs/qa/cli-v1-checklist.md` rows | new or changed | User guides; roadmap; QA checklists | `docs/guides/postgres-source/` |

## 10. Design notes

- Principles. One place per fact: the identifier rule and the connection setup in
  `_postgres_session.py`; the type rules in `postgres_typemap.py`; the catalog SQL and the
  bookkeeping row declaration in `postgres_target_catalog.py`; code classification in the engine
  (`POSTGRES_TARGET_USAGE_CODES`); the exit map in `exit_code_for`. Dependency direction by layer:
  `config` stays shape-only; `connectors` takes a resolved `SecretStr` and knows nothing of
  pipelines; `execution/pipeline` resolves references; the CLI calls only public names. Typed
  context objects (`PostgresTargetConfig`, `TargetCatalog`, `TargetPlan`) instead of long
  parameter lists. No flag argument: read-only and read-write sessions are two named functions.
- Pattern followed: pg_restore single transaction with section ordering, and pgloader's
  truncate, drop-index, re-create and reset-sequence steps (section 2). Publish steps are a
  fixed ordered table of named steps, each with its own failure code, so the order is a visible
  table edit and the fault seam addresses steps by name.
- New structure: one target adapter. A second database later adds its own adapter beside it;
  nothing generic is built now (the DELIV `SinkStage` protocol is already the seam).
- Choke points.
  - Database writes. Only `postgres_target.py` opens a read-write `ATTACH`, through
    `_postgres_session.open_write_session`. Guard AT-E4; mutation: a read-write ATTACH in
    `postgres_snapshot.py`.
  - Pre-write inspection. `open_postgres_target` is the only way to a `PostgresTargetHandle`, and
    `publish` takes a `TargetPlan` that only `plan_target` builds from a `TargetCatalog`. Guard
    AT-E6, AT-C8; mutation: run the guards after the write session opens.
  - Non-run callers. `_require_local_io_endpoints` (CLI I/O choke point). Guard AT-C7; mutation:
    drop the postgres arm.
  - Value-free errors. Every step raises after its `except` block closes and reads only the
    exception type. Guard AT-E14; mutation: raise inside the block.

## 11. Size

Engine: 5 new modules (`_postgres_session.py` about 140 with the moved helpers,
`postgres_typemap.py` about 260, `postgres_target_catalog.py` about 380, `postgres_target.py`
about 480, `execution/pipeline/_postgres_target.py` about 170), 6 changed modules (about 160
lines, `postgres_snapshot.py` shrinks by about 70), 8 new test files (about 1,300 lines), one doc
page. New public names: the sixteen in section 6.

CLI: 1 new module (about 220), 6 changed modules (about 150), one test folder (about 650 lines),
one guide.

Module size (engine `tests/sentry/test_module_size.py`, aim 600, hard 700; CLI cap 800):
every new engine module stays under 600. If `postgres_target.py` passes 600, the reconcile and
the step table move to `connectors/postgres_target_publish.py` (same CODEMAP row) instead of a
census entry. A build more than 30 percent over these numbers stops and explains before review.

## 12. Slices

Fewer, larger, behaviour-changing slices. Prep goes in E1; engine docs in E3; CLI docs in C2.

| Slice | Repo | Content | Risk | Src lines | Acceptance tests | Depends on | Test depth notes |
|---|---|---|---|---|---|---|---|
| E1 | engine | Prep and pure parts: move the session helpers into `_postgres_session.py` and add `open_write_session`; `PostgresTarget` and the identity arm; `plan/checks/_postgres_targets.py`; `postgres_typemap.py` with the report document and its snapshot; the config and connector codes (`since=UNRELEASED`); `DELIVERABLE_TARGET_TYPES` token; the engine target writer dispatch refuses a postgres descriptor (`target_postgres.unsupported_command`); choke-point sentry; `pg-gate` file list; changelog fragment | R2 (shared connector code, config union, transaction semantics) | ~480 | AT-E0, AT-E1, AT-E2, AT-E3, AT-E4 | 64b E1 and E2 merged (lane, `POSTGRES_DSN_V1`, `PostgresSource`, primitive fixes); DELIV E1a (merged) | config serializer and shared connector module: full suite once on the slice head, diffed against the saved main baseline; `pg-gate` green |
| E2 | engine | Read-only half: `postgres_target_catalog.py` (catalog SQL, structure digest, fingerprint, bookkeeping row declaration and strict reader with its snapshot), `read_target`, `plan_target` with value guards, `execution/pipeline/_postgres_target.py` (`open_postgres_target`, settings, `POSTGRES_TARGET_USAGE_CODES`), 64b `StagedSources.server_fingerprint`; changelog fragment | R2 (data handling, secrets) | ~620 | AT-E5, AT-E6, AT-E7, AT-E15 | E1 | T1 plus `pg-gate`; mutations on the reader and the guards |
| E3 | engine | Write half: `publish_target` (twelve steps, rollback, probe, reconcile, deadline, `ANALYZE`), public exports and frozen-surface rows, `docs/postgres-target.md`, `docs/index.md`, changelog fragment | R2 (destructive database write, publication, value leaks) | ~520 | AT-E8, AT-E9, AT-E10, AT-E11, AT-E12, AT-E13, AT-E14 | E2 | frozen surface: full suite once on the slice head against the saved baseline; `pg-gate` green; mutations on every step-order and reconcile mutation in section 8 |
| REL | engine | Engine release 0.29.0 through the daily release train; the release commit stamps the new codes, `REGISTRY_VERSION` and the manifests | R1 | small | release checks | E3; 0.28.0 (64b) cut | release train rules |
| C1 | CLI | Repin to 0.29.0 (engine repin checklist); `io/_postgres_target.py` stage and `PostgresOutput`; `_delivery.py` stage construction; prepare-time `open_postgres_target`; non-run refusal arm; exit arms; card summary and `--json` key; `pg-gate` file list; CODEMAP tests cell | R2 (data handling, version pin, CI) | ~370 | AT-C1, AT-C2, AT-C3, AT-C4, AT-C6, AT-C7, AT-C8 | REL; DELIV C2a merged (`SinkStage`, `PublishedOutput`, placer); 64b C1 and C2 merged | version pin and test config: full suite on the slice head against the saved main baseline; `pg-gate` green |
| C2 | CLI | Interrupt handling at the visibility point and `target_commit_unknown` message; shape changelog and snapshot; user guide `docs/guides/postgres-target/` (target preparation with `pg_dump --schema-only`, privileges, `decoy_meta` SQL for a DBA, what readers see, refreshing materialized views), README, CHANGELOG, QA checklist rows, roadmap row 86 to DONE and shipped log | R2 (interrupt semantics on a destructive write) | ~150 plus docs | AT-C5, AT-C9 | C1 | T1 plus `pg-gate` |

E2 is about 620 source lines, under the 800 bound; its tests are larger. Order: E1, E2, E3,
REL, C1, C2. One writer per worktree, never two. C1 merges after the DELIV CLI slices that edit
`io/_delivery.py`, `run/_prepare.py` and `run/_execute.py` (DELIV writer table, section 10) and
after 64b C1 (it edits `run/_prepare.py` too).

Each slice: T0 per edit, T1 per commit, T2 at the gate with the slice's mutations re-run on the
final head (class 9). Reviews: R2 slices get Dennis then Codex; REL gets Codex only. Commit
subjects follow Conventional Commits with the final line `cam` and no other trailer.

## 13. Recurring-defect class check

| Class | Recurring defect | Plan evidence |
|---|---|---|
| 1 | Anchored validation | identifiers through the one `fullmatch` rule; bookkeeping reader `fullmatch`es every field; AT-E2 and AT-E15 have `"\n"` cells |
| 2 | Strict wire and stored types | `PostgresTarget`, `PostgresTargetConfig`, settings and the bookkeeping row use strict types; AT-E1 and AT-E15 feed bools and ints |
| 3 | No exception context | every step raises after its `except` closes; AT-E14 asserts `__context__ is None` |
| 4 | Versioned read models | `decoy-pg-publication/v1` row: exact tag, unknown tag refused, one declaration for writer and reader (AT-E15); `decoy-pg-type-map/v1` is write-only with a schema snapshot (AT-E3) |
| 5 | Normalized guard scanners | AT-E4 scans source text for `connect_internal`, `LOAD postgres` and `ATTACH` without `READ_ONLY`, with seeded cells for single and double quotes and an f-string; deliberate evasion is V2-LOG |
| 6 | No private-module imports | the CLI imports only `decoy_engine` public names and the `decoy.cli.io` facade; the target adapter imports `_postgres_session` inside its own package only |
| 7 | No hidden CI failures | `pg-gate` from 64b (no `continue-on-error`, `junit_ran.py`); the new marked files join its file list, so the scope guard fails if one is left out |
| 8 | One input, one trust class per entry point | user-chosen relation names go through the identifier rule; staged Parquet paths are program-built and never user input; SQL literals for paths go through `_lit` |
| 9 | Mutations on the final head | every slice reruns its section 8 mutations after its last change and records the head |
| 10 | Allowlisted helpers are still checked | new modules get exact `(path, name)` rows in the file-access and physical-seam registries; their callers stay checked |
| 11 | No raised caps | no cap, pin ceiling, ratchet or baseline is raised; a module near its size cap is split |

## 14. Plan defect catalog classes

| Class | Defect | Closing structure | Sentry or property test | Seeded mutation | Slice |
|---|---|---|---|---|---|
| 1 | Value exposure (DSN, row values in server error text, reference text) | exception type only, raise outside `except`, guards return counts, report holds names and types | AT-E14, AT-C3 | raise inside the `except` block; forward `str(exc)` | E3, C1 |
| 2 | Cleanup on every exit (target and scratch) | one transaction, rollback on any failure; scratch on the run `ExitStack` | AT-E9, AT-E11, AT-C5 | commit between `load` and `restore_post_data`; allocate scratch without a scope | E3, C2 |
| 3 | State completeness (every step and every outcome covered) | fixed step table; every step has a fault cell; every outcome token has a test | AT-E9, AT-E12, AT-E13 | delete one step's fault handler | E3 |
| 4 | Route coverage | all routes write through the sink placer into the same scratch; non-run callers refused | AT-C1, AT-C2, AT-C7 | place only on the plain route | C1 |
| 5 | Referential integrity across target tables | FKs dropped before and validated after the load in one transaction; external FKs refused | AT-E8, AT-E9, AT-E5 | skip FK re-creation; skip the external-reference check | E2, E3 |
| 6 | Untrusted input (relation names, secret material, catalog text) | the one identifier rule; `postgres-dsn-v1`; captured definitions executed only under `search_path = pg_catalog` | AT-E2, AT-E8 | allow `.` in identifiers; drop `SET LOCAL search_path` | E1, E3 |
| 7 | TOCTOU check-then-use between inspection and publish | structure digest and bookkeeping row re-read under the advisory lock and `FOR UPDATE` in the publish transaction | AT-E12 | skip `check_structure` | E3 |
| 8 | Weak proof of "nothing written" and "all restored" | catalog digest plus row digests plus `pg_stat_user_tables` counters, not only a code; definition sets compared before and after | AT-E5, AT-E8, AT-E9 | assert only the error code | E2, E3 |
| 9 | Refactor drift (second copy of the connection or identifier code) | helpers moved once into `_postgres_session.py`; snapshot imports them | AT-E4 | keep a copy of `_open_connection` in the snapshot | E1 |
| 10 | Frozen contract drift | additive union member; existing receipt tokens; schema snapshots for the two new formats; exit map held equal | AT-E3, AT-E15, AT-C6, AT-C9 | add a receipt outcome token; change an exit integer | E1, E2, C1 |

## 15. Pre-mortem

- DuckDB runs `postgres_execute` on a pooled connection outside the open transaction, so the
  `TRUNCATE` commits on its own. AT-E0 is the first test of E1 and fails red on that behaviour;
  E1 stops and the plan returns for amendment (Q15). Nothing else is built on an unproven
  transaction.
- A captured `pg_get_indexdef` text resolves to a different object when re-executed: capture
  and re-create both run under `SET LOCAL search_path = pg_catalog` in the same transaction, so
  every name is schema-qualified (pg_dump practice since CVE-2018-1058).
- A load of tens of millions of rows holds `ACCESS EXCLUSIVE` for minutes and the application
  queues behind it. That is the stated V1 trade (Q1); the guide says so, and `lock_timeout_s`
  stops the publisher from queuing behind a long application transaction instead of hanging.
- Large loads fill WAL inside one transaction. Documented capacity note in the guide; the
  transaction size is the target data size, the same as pg_restore `--single-transaction`.
- The masked data breaks a target FK to an untouched lookup table (masking changed a lookup
  key). The run fails with `target_constraint_failed` at that constraint and rolls back; the
  guide tells the user to add the lookup table to the pipeline as passthrough.
- A builder reads the PostgreSQL error message to classify a failure "more precisely": AT-E14
  plants a value in a unique-violation and fails on any leak; the reviewer checks that only
  exception type names are read.
- A builder weakens AT-E9 to check one table: the gate checks that the catalog digest, every
  table's row digest and the bookkeeping row are compared for every step.
- Sequences set from `max(col)` overflow a `smallint` serial: the server refuses `setval`, the
  step fails, rollback; the code is the step's `target_load_failed`.
- DELIV C2a slips: C1 cannot merge without the `SinkStage` protocol. The engine half still ships
  in 0.29.0 and the CLI half waits; no interim CLI path is built.
- `decoy_meta` is created by a role without `CREATE` on the database: refused at inspection, and
  the guide gives the DBA the two statements to create it once.
- A materialized view over a target table shows old data after the run: documented, not a
  failure (non-goal).

## 16. Owner questions (each taken on the recommended answer and recorded)

| # | Question | Recommended answer, taken |
|---|---|---|
| Q1 | Publish method: one transaction in place, or a staging schema with a rename swap? | One transaction in place (pg_restore `--single-transaction`, pgloader steps). "Staging" in V1 is the locally staged masked Parquet plus the uncommitted transaction. Readers wait during the load. The schema swap is V2, for targets that cannot block readers |
| Q2 | Which write modes in V1? | `replace` only, required and explicit in each target. The target structure must exist (migrations or `pg_dump --schema-only`). `create`, `append` and `upsert` are V2 |
| Q3 | How many target connections and schemas per pipeline, and can Postgres targets mix with file or cloud targets? | One connection, one schema, no mixing in V1, because one transaction is the atomic unit |
| Q4 | `best_effort` delivery with a Postgres target? | Refused at compile time; strict only. A partial replace of an application database is not application-ready |
| Q5 | Same-database guard | Refuse when the target and any Postgres source are the same database (same reference text at compile time; same server fingerprint at run time). A second database on the same server is allowed |
| Q6 | User triggers during the load | Disabled (`DISABLE TRIGGER USER`) and re-enabled to their exact prior state before commit, inside the transaction; needs table ownership, not superuser |
| Q7 | Sequence values after the load | Owned sequences to `max(column)`, empty table to the start value with `is_called = false` (pgloader `reset sequences`). Sequences not owned by a target column are untouched |
| Q8 | Lossy conversions | Always block in V1. No approval list; a later row can add one |
| Q9 | Unsupported target objects in V1 | Partitioned tables, inheritance, rewrite rules, FORCE RLS and foreign keys from non-target tables are refused before writing. Views keep working (OIDs unchanged). Materialized views are not refreshed |
| Q10 | Backup, confirmation and preview before a destructive write | No automatic backup, no prompt, no separate preview command. The explicit `mode: replace` per table is the authorization; the read-only inspection runs on every run before any row is read and the card names the target. A preview command is a follow-up row |
| Q11 | Where the publication record lives | `decoy_meta.publications` in the target database, created on first publish when the role may; otherwise a DBA creates it once from the guide's SQL. Fixed schema name in V1 |
| Q12 | Where the type-mapping report goes | Run card summary, `--json` key `postgres_target.type_map` with the engine document `decoy-pg-type-map/v1`; no new file in the run folder |
| Q13 | Which engine release carries the engine half | 0.29.0, the release after 64b's 0.28.0, or the first release cut after E3 merges |
| Q14 | `ANALYZE` after the publish | Yes, after commit; a failure is a warning, never a failed run |
| Q15 | If DuckDB cannot hold DDL, `TRUNCATE` and the load in one PostgreSQL transaction (AT-E0 red) | E1 stops and the plan is amended to use psycopg 3 behind a new optional extra; no silent fallback and no new dependency without that amendment |
| Q16 | Timeouts | Statement 3600 s, whole publish 21600 s, lock wait 30 s; no config override in V1 (64b Q7 values) |

## 17. Unresolved

- AT-E0's outcome (Q15). Everything after E1 assumes it passes.
- Whether the CLI install policy needs a row for anything new: nothing new is installed beyond
  64b's `postgres:16` service; the C1 builder confirms with the sentry.
- The exact `Placer` call DELIV C2a lands for non-file kinds. C1 follows what C2a merges; if C2a
  keeps the placer file-only, C1 adds the postgres arm inside `_delivery.py` (already in its
  touch list) and nothing outside it.
- The platform surface for Postgres targets: out of scope (platform parked); the engine names
  are public so it can reuse them.
