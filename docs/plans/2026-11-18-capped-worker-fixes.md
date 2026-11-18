Status: plan

# Capped-worker fixes: one capped env, Postgres connect timeout, child thread sizing

Owner: Cam. Author: Opus plan agent. Date: 2026-11-18. Scope: engine only, V1 fix rows.

Rules consulted: `dev-rules/README.md` (routing), `00-universal.md`, `risk-and-exceptions.md`,
`development-loop.md` (Proportion; PLAN: guarantee, size, design notes, choke point, Placement,
Established solutions), `profiles/local-operations.md`, `bugfix.md`, `testing.md` (Test depth,
full-suite triggers), `cross-cutting-concerns.md`, `architecture.md` (layout, size),
`security.md`, `observability-and-resilience.md` (timeouts, value-free errors), `performance.md`
(speed trade-off evidence), `catalogs/recurring-defects.md` (classes 3, 5, 6, 7, 9, 11),
`workspace-and-vcs.md` (Commit messages); engine `CLAUDE.md` (cite the method; modules aim for
600 lines, hard max 700); engine `CODEMAP.md` "Where Things Go" (rows Pipeline spine, Connectors,
Sentry test, Dev tooling).

Base: engine `origin/main` `84cc7d798`. **PR #666 (`fix/main-red-1118`) must merge first.** All
three slices build on its `CAPPED_ENV` (with `OPENBLAS_NUM_THREADS`, `OMP_NUM_THREADS` and
`MKL_NUM_THREADS` set to `"1"`), its guard test
`test_the_spawned_child_starts_no_blas_thread_pool`, and its `closing_port` fixture. Each builder
branches from `origin/main` after #666 lands.

Source: the root cause of the red main on 2026-11-18 (gate-selfhosted run 44221036975, Dell
runners, 26 cores) and the two V2-LOG items Codex left on #666.

## 0. Slices

| Slice | Row | Risk | Prod files | Est. lines (prod / tests) | Reviewers | Depends on |
|---|---|---|---|---|---|---|
| S1 CAPPED-ENV-ONE | (c) one capped env, sentry, guard asserts all three BLAS knobs | R1 | 0 src, 2 scripts | about -40 / +150 | Codex | #666 |
| S2 PG-CONNECT-TIMEOUT | (b) libpq `connect_timeout` below the session deadline | R2 (credential text, value-leak area) | 2 | about +60 / +170 | Dennis, then Codex | #666 (`closing_port`) |
| S3 CHILD-THREADS | (a) size DuckDB and per-core pools in the capped child | R2 (resource limits, execution path) | 5 | about +70 net / +220 | Dennis, then Codex | #666; rebases on S1 |

The slices are independent in code. S3 edits a test file that S1 also edits, so S3 rebases after
S1. S1 and S2 can build in parallel in separate worktrees. Merge order: S1, S2, S3.

No owner question. One design call (S3: DuckDB threads are not clamped to `native_threads`) is
made in 3.3 with its reason. A reviewer may challenge it.

## 1. S1 CAPPED-ENV-ONE (row c)

### 1.1 Problem

The capped spawn env is defined once in
`src/decoy_engine/execution/_isolated_common.py::CAPPED_ENV`. Seven other files keep their own
`_CAPPED_ENV` copy with only `ARROW_DEFAULT_MEMORY_POOL` and `MALLOC_ARENA_MAX`, so none of them got
#666's BLAS knobs:

- `scripts/fk_memory_probe.py:221` (the original that the engine copy was ported from)
- `scripts/route_reorder_vs_batchjoin_ab.py:37`
- `tests/perf/test_out_of_core_reorder_memory.py:39`
- `tests/perf/test_out_of_core_reorder_multi_edge_memory.py:74`
- `tests/perf/test_out_of_core_reorder_wide_raw_memory.py:41`
- `tests/perf/test_ooc_external_sort_memory.py:48`
- `tests/perf/test_out_of_core_relation_dedup_memory.py:55`

The row named the three `reorder*` files and the probe. The other three copies are the same class,
and the sentry in 1.4 fails on them, so S1 converts all seven.

### 1.2 Guarantee and non-goals

Guarantee: every spawn of a memory-capped Python child in this repo (src, tests, scripts) takes its
allocator and thread env from `CAPPED_ENV`. A new dict that carries `MALLOC_ARENA_MAX` anywhere
other than `_isolated_common.py` fails CI. The #666 guard test asserts that all three BLAS knobs
reach the child as `"1"`, also when the parent sets them to `"8"`.

Non-goals: no change to `CAPPED_ENV` values. No change to the perf tests' jobs or thresholds.
Deliberate evasion of the sentry (built strings, `eval`, env files) is V2-LOG (class 5 scope rule).

### 1.3 Design

Each copy becomes `from decoy_engine.execution._isolated_common import CAPPED_ENV`, and each spawn
reads `{**os.environ, **CAPPED_ENV, ...}` (the wide-raw test keeps its extra secret key after
`CAPPED_ENV`). Tests and scripts already import from `_isolated_common` (for example
`tests/unit/execution/test_isolated_memwatch.py` and `scripts/mem_telemetry_records.py`), so this
adds no new reach into another package's private module (class 6). The per-copy comments that
justify the two allocator vars are deleted. The comment in `_isolated_common.py` stays the one
source; its line "Ported verbatim from fk_memory_probe._CAPPED_ENV" changes to say that the probe
now imports this constant.

`scripts/fk_memory_probe.py` is a pinned over-max legacy file (`tests/sentry/test_module_size.py:151`
and `tests/sentry/baselines/module-size.json`, both 1056). It shrinks, so both pins move down to the
new exact count. Class 11 allows a pin to move down; list the moved pin in the report.

### 1.4 Choke point and sentry

Choke point: `CAPPED_ENV` in `_isolated_common.py` is the one definition. Guard:
`tests/sentry/test_one_capped_env.py`, modelled on `tests/sentry/test_one_memory_limit_parser.py`.
It parses (AST, not regex) every `*.py` under `src/`, `tests/`, `scripts/`, `testflight/` and `ci/`,
and reports `path:line` for each of these shapes outside
`src/decoy_engine/execution/_isolated_common.py`:

1. a dict literal with the string-constant key `"MALLOC_ARENA_MAX"`;
2. a `dict(...)` call with the keyword `MALLOC_ARENA_MAX=`;
3. a subscript store `x["MALLOC_ARENA_MAX"] = ...` (covers `os.environ[...]` and `env[...]`);
4. a `.setdefault("MALLOC_ARENA_MAX", ...)` call.

Reads such as `os.environ.get("MALLOC_ARENA_MAX")` are not findings. The sentry docstring lists the
covered shapes; other spellings are V2-LOG. There is no allowlist. Register the file in
`tests/sentry/test_sentry_manifest.py` and `scripts/dev/sentry_registry.toml` the same way
`test_one_memory_limit_parser.py` is registered.

### 1.5 Placement

| File | Directory | CODEMAP line | Sits beside |
|---|---|---|---|
| `test_one_capped_env.py` (new) | `tests/sentry/` | "Sentry test: existing rules in `tests/sentry/`" | `test_one_memory_limit_parser.py` |

No other new file.

### 1.6 Acceptance tests (write first)

- AT-C1 `test_one_capped_env.py::test_no_capped_env_copy_outside_isolated_common`. Fail-before: on
  main after #666 it lists the seven files above. After the build the list is empty.
- AT-C2 seeded source strings, one per shape 1 to 4, each found; the `os.environ.get` string not
  found. One parametrized test.
- AT-C3 edit `tests/unit/execution/test_isolated_run_env_flag.py::test_the_spawned_child_starts_no_blas_thread_pool`:
  the parent sets all three knobs to `"8"` with `monkeypatch.setenv`, and the test asserts
  `{k: seen[k] for k in BLAS_KNOBS} == dict.fromkeys(BLAS_KNOBS, "1")` before the thread-count
  check. `BLAS_KNOBS` is a tuple in the test file, not exported from src.
- AT-C4 the converted perf tests collect (`pytest --collect-only` on the five files), and
  `python scripts/fk_memory_probe.py --help` and `python scripts/route_reorder_vs_batchjoin_ab.py --help`
  exit 0.

### 1.7 Mutations

- M-C1 re-add a local `_CAPPED_ENV = {"MALLOC_ARENA_MAX": "2", ...}` to one perf test: AT-C1 red.
- M-C2 drop `MKL_NUM_THREADS` from `CAPPED_ENV`: AT-C3 red. (#666's guard stayed green on this
  mutant, which is the Codex finding.)
- M-C3 remove the subscript-store handling from the sentry: the shape-3 cell of AT-C2 red.

### 1.8 Test scope

T0 and T1. Named: `tests/sentry/test_one_capped_env.py`,
`tests/unit/execution/test_isolated_run_env_flag.py`, `tests/sentry/test_module_size.py`,
`tests/sentry/test_sentry_manifest.py`. Run the five converted perf tests once on the Dell with
their perf marker, and record peak memory and wall time before and after. The BLAS knobs lower
VmData, so the memory thresholds only get easier. Wall time can move, because `OMP_NUM_THREADS=1`
also pins Arrow's CPU pool (see 3.1). Record it; do not gate on it.

Full-suite triggers: none (no shared fixture, test config, tooling, or moved test). T3 at merge as
usual.

Size: 0 src files, 2 scripts, 5 perf tests, 1 new sentry, 2 registry edits, 1 guard-test edit,
2 pin edits.

## 2. S2 PG-CONNECT-TIMEOUT (row b)

### 2.1 Problem

Every engine Postgres connection goes through one statement in
`src/decoy_engine/connectors/_postgres_session.py::attach_read_only`:
`ATTACH '<dsn>' AS decoy_pg_src (TYPE postgres, READ_ONLY)`. Its callers are `open_read_session`,
then `connected_session`, then `postgres_snapshot.read_session`, which serves
`snapshot_tables_to_parquet` and `postgres_catalog.relation_columns`. The text `TYPE postgres`
appears nowhere else in `src/`.

No `connect_timeout` is set, so libpq waits for a host that drops SYNs until the OS gives up
(about 30 s with WSL2 mirrored networking, about 127 s on stock Linux with `tcp_syn_retries=6`).
The session `Deadline` is armed in `on_connect`, just before the ATTACH. When it fires first,
`raise_for_interrupt` reports `deadline_exceeded`. #666 showed this on the Dell: a connect to a
closed loopback port got no RST, libpq waited about 30 s, and the 20 s deadline gave
`deadline_exceeded`. The user's real problem is a host the engine cannot reach, which is
`source_unreachable`.

### 2.2 Guarantee and non-goals

Guarantee: every ATTACH the engine issues carries a libpq `connect_timeout` that is shorter than
the session deadline when `deadline_s >= 4`. A host that drops SYNs, or a server that never answers
the startup packet, then fails as `source_unreachable` before the deadline. Errors stay value-free:
no DSN, host, port, user, database, password or timeout figure in the message, the logs,
`__cause__` or `__context__`.

Non-goals:
- A `connect_timeout` that the user put in the DSN is replaced by the engine value (the later value
  wins, see 2.3). Keeping a smaller user value would need a DSN parser. V2-LOG.
- A DNS lookup that hangs (`getaddrinfo`) is not covered by `connect_timeout`. It stays
  `deadline_exceeded`.
- A multi-host DSN gets the timeout per host ("This timeout applies separately to each host name or
  IP address"), so k black-holed hosts can still reach the deadline. Accepted.
- No new reason code (2.5).
- The planned Postgres target `open_write_session` is not built here. When it is, it must use the
  same ATTACH helper; the guard in 2.6 fails otherwise.

### 2.3 Established solutions

Search run: libpq connection parameters
(https://www.postgresql.org/docs/current/libpq-connect.html), the DuckDB postgres extension
settings (https://duckdb.org/docs/2.0/core_extensions/postgres/overview.html), and the engine's
own outbound clients (`connectors/_clients.py`).

- libpq `connect_timeout`: "Maximum time to wait while connecting, in seconds (write as a decimal
  integer, e.g., 10). Zero, negative, or not specified means wait indefinitely. This timeout
  applies separately to each host name or IP address." It bounds the whole connection
  establishment, including the startup and authentication exchange.
- The DuckDB postgres extension has `pg_statement_timeout_millis` and
  `pg_idle_in_transaction_timeout_millis`, but no connect-timeout setting. "The ATTACH command takes
  as input either a libpq connection string or a PostgreSQL URI." So the connection string is the
  only place to set it.
- `PGCONNECT_TIMEOUT` (the libpq env default) is rejected. It is process-global, a library must not
  call `setenv` while other threads can call `getenv`, and an explicit DSN value overrides it.
- In-repo precedent: S3 `Config(connect_timeout=5, read_timeout=60)` and the GCS `(connect, read)`
  timeout in `connectors/_clients.py`, enforced by `tests/sentry/test_outbound_clients.py`.
- libpq stores a repeated keyword over the earlier value (`conninfo_storeval` in
  `src/interfaces/libpq/fe-connect.c`), for key/value strings and for URI query parameters. AT-B3
  proves this against the bundled extension instead of trusting this reading.

Custom code left: one small function that appends the keyword in the right syntax.

### 2.4 Design

In `_postgres_session.py`:

- `PG_CONNECT_TIMEOUT_S: Final = 10`. This is the same order as the 5 s S3 and GCS connect
  timeouts, a little longer because libpq also covers TLS and authentication.
- `connect_timeout_s(deadline_s: int) -> int` returns
  `max(2, min(PG_CONNECT_TIMEOUT_S, deadline_s - 2))`. The floor of 2 matches older libpq
  releases, which documented a 2 s minimum. The 2 s gap keeps the connect failure clear of the
  deadline timer.
- `with_connect_timeout(dsn_text: str, seconds: int) -> str`. Pure; it never raises and never logs.
  - URI form (libpq's rule: the text starts with `postgresql://` or `postgres://`): append
    `&connect_timeout=N` when the text has a `?`, else `?connect_timeout=N`.
  - Key/value form, including the empty DSN (connect from `PG*` env vars): append
    ` connect_timeout=N`.
- `attach_read_only` gains a `connect_timeout_s: int` parameter and builds the ATTACH from
  `sql_literal(with_connect_timeout(dsn.get_secret_value(), connect_timeout_s))`.
  `open_read_session` passes `connect_timeout_s(config.deadline_s)`. The composed text exists only
  as a local in `attach_read_only`.

The existing leak rule stays: the `except` block records only `type(exc).__name__`, and the coded
error is raised after the block has closed (class 3). Nothing new is logged.

Size: `_postgres_session.py` goes from 299 to about 340 lines. One `changelog.d/` fragment. Two
production files.

### 2.5 Reason-code mapping

| Case | Before | After |
|---|---|---|
| Refused or reset (RST), DNS NXDOMAIN, bad password | `source_unreachable` | `source_unreachable` |
| SYN dropped, or a server that accepts and never answers, `deadline_s >= 4` | `deadline_exceeded` | `source_unreachable` after about `connect_timeout_s(deadline_s)` |
| Same, `deadline_s` from 1 to 3 | `deadline_exceeded` | either code; the timers coincide, and both are true |
| DNS lookup hangs | `deadline_exceeded` | `deadline_exceeded` |
| Every host of a multi-host DSN black-holed, sum past the deadline | `deadline_exceeded` | `deadline_exceeded` |
| Slow query after the connect | `deadline_exceeded` | `deadline_exceeded` |

Decision: reuse `source_unreachable`. A connect timeout is a host the engine could not reach, and
the user's fix is the same (address, firewall, network). A new code would add a registry entry and
a CLI mapping with no different action. `raise_for_interrupt` already checks the deadline flag
first, so when both fire the result is still one of the two true codes.

To confirm on the Dell and record in the PR: whether `conn.interrupt()` ends a blocking libpq
connect. #666's timing (deadline 20 s, result after about 30 s) suggests that it does not. In that
case `connect_timeout` is the only real bound on a hung connect.

### 2.6 Choke point and guard

Choke point: `attach_read_only` holds the only ATTACH, and the DSN reaches it only through
`with_connect_timeout`. Guard: `test_type_postgres_attach_has_one_site` in
`tests/connectors/test_postgres_session.py`, an AST walk of `src/decoy_engine/**/*.py` that finds
string constants containing `TYPE postgres` only in `_postgres_session.py`. Mutation M-B1 proves
that the wrap itself is not bypassed.

### 2.7 Placement

No new file. Tests go in the existing `tests/connectors/test_postgres_session.py` and
`tests/connectors/test_postgres_snapshot_unit.py` (CODEMAP Connectors row: tests in
`tests/connectors/`).

### 2.8 Acceptance tests (write first)

Pure functions (fast):
- AT-B1 `connect_timeout_s` cells: 1 -> 2, 3 -> 2, 4 -> 2, 6 -> 4, 12 -> 10, 3600 -> 10.
- AT-B2 `with_connect_timeout` cells: `"host=h dbname=d"` -> `"host=h dbname=d connect_timeout=7"`;
  `""` -> `" connect_timeout=7"`; `"postgresql://u@h/d"` -> `"postgresql://u@h/d?connect_timeout=7"`;
  `"postgres://u@h/d?sslmode=require"` -> `"postgres://u@h/d?sslmode=require&connect_timeout=7"`;
  a key/value DSN with a quoted value that contains `?` stays in key/value form.

Behaviour against the bundled extension (in `test_postgres_snapshot_unit.py`, which already has
`ext_dir` and #666's `closing_port`):
- AT-B3 a `silent_port` fixture (a loopback listener that accepts each connection and holds it
  open, sending nothing) with `deadline_s=6`: `snapshot_tables_to_parquet` raises
  `PostgresSnapshotError` with `code == "source_unreachable"` in under 6 s. A second cell puts
  `connect_timeout=600` in the user DSN and gets the same result (proves that the later value
  wins). Fail-before: on main the same call gives `deadline_exceeded`, or waits past the deadline.
- AT-B4 leak cells on AT-B3's error: the rendered traceback, `str`, `repr` and every caplog message
  contain none of `PW_SECRET`, `127.0.0.1`, `port=<n>`, `user=u`, `dbname`, `connect_timeout`; and
  `err.__cause__ is None and err.__context__ is None`.
- AT-B5 spy cell: a fake connection records the executed ATTACH text. It contains
  `connect_timeout=<connect_timeout_s(deadline_s)>` for both DSN forms.
- AT-B6 `test_type_postgres_attach_has_one_site` (2.6).
- Existing `test_connect_failure_leaks_no_dsn` (#666's `closing_port`) stays green.

Host evidence (PR, not CI): on the Dell, the old DSN `host=127.0.0.1 port=1` with `deadline_s=20`
gives `source_unreachable` in about 10 s. WSL2 mirrored networking black-holes closed loopback
ports, so the Dell reproduces a SYN-dropping host with no extra setup. Record the time.

### 2.9 Mutations

- M-B1 build the ATTACH from the raw DSN (skip `with_connect_timeout`): AT-B3 and AT-B5 red.
- M-B2 return `PG_CONNECT_TIMEOUT_S` without the deadline clamp: AT-B1 cell 6 -> 4 red, and AT-B3
  runs past 6 s.
- M-B3 put the keyword first instead of last: the AT-B3 user-value cell red.
- M-B4 raise the coded error inside the `except` block: the AT-B4 context cell red.

### 2.10 Test scope

T0, T1. Named: `tests/connectors/test_postgres_session.py`,
`tests/connectors/test_postgres_snapshot_unit.py`, `tests/connectors/test_postgres_snapshot.py`
(its real-database cells run where `require_pg` allows), `tests/sentry/test_log_interpolation.py`.
Full-suite triggers: none (no reason code, serialization, contract or auth-check change). T3 at
merge as usual. Reviewers: Dennis, then Codex, because credential text is in the change.

## 3. S3 CHILD-THREADS (row a)

### 3.1 Problem, from the code

Inside the capped child, DuckDB's thread count comes from `_threads_for_memory_limit` in
`execution/out_of_core/_duckdb.py`:
`max(1, min(usable CPUs, out_of_core_threads, memory_limit // 2 GiB))`. The `memory_limit` comes
from `resolve_ooc_memory_limit(out_of_core_budget_bytes)` in `_pipeline_route_exec.py:364`. When
the caller sets `mem_cap_bytes` but no `out_of_core_budget_bytes`, the budget is `None`, and
`resolve_ooc_memory_limit` sizes from `detect_effective_memory_bytes()`: the cgroup limit, else
host RAM. It never reads the child's own `RLIMIT_DATA` or `RLIMIT_AS`. So a 768 MiB child on a
large host gets a multi-GiB `memory_limit` per connection and a thread count that follows the core
count. Each DuckDB worker thread maps a stack (8 MiB by default) that RLIMIT_DATA counts. That is
the about 215 MiB seen on 26 cores. On 64 cores it is about 512 MiB of a 768 MiB cap.

The governor path does not have this bug: `run_job_with_governor` forwards its `budget_bytes` as
`out_of_core_budget_bytes` (`_governor.py::_isolated_kwargs_with_budget`). Direct
`run_pipeline_isolated(..., mem_cap_bytes=...)` callers do not: the b6b low-cap test,
`TestMemCapOom`, and any caller that caps without the governor.

Other per-core pools in the child:
- Arrow's CPU pool: "The number of threads is determined at startup by inspecting the
  OMP_NUM_THREADS and OMP_THREAD_LIMIT environment variables. If neither is present, it will default
  to the number of hardware threads on the system" (pyarrow `cpu_count` docs). #666 sets
  `OMP_NUM_THREADS=1`, so since #666 every isolated child, capped or not, runs Arrow's pool at one
  thread. #666's changelog says speed does not change. That holds for the native kernels, not for
  Arrow work such as `to_pandas` or threaded Parquet reads.
- Polars' pool: "The thread pool size can be overridden by setting the POLARS_MAX_THREADS
  environment variable before process start" (Polars `thread_pool_size` docs). Otherwise it is
  sized from the core count.
- The native companion's rayon pool is sized from `native_threads`
  (`decoy-engine-native/src/threads.rs`). Not a per-core risk.
- OpenBLAS and MKL: pinned to 1 by #666. glibc arenas and Arrow's allocator: pinned by `CAPPED_ENV`.

Not checked here (no code runs on this devbox): which DuckDB connection the b6b job opens. The job
is single-table, so it may not take the out-of-core route. Build step 0 (3.6) is a thread census on
the Dell that names each thread group at peak. The design below covers every DuckDB connection
that the child opens through `connect_duckdb`. If the census shows a source that it does not
cover, the builder stops and the plan is amended.

### 3.2 Established solutions

Search run: the DuckDB configuration reference and performance guide, the pyarrow and Polars
thread-pool docs, and the in-repo sizing code.

- DuckDB `threads`: "The number of total background threads used by the system", default
  "# CPU cores". `memory_limit`: "The maximum memory of the system (e.g., 1GB)", default "80% of
  RAM" (https://duckdb.org/docs/2.0/configuration/overview.html). The limits page notes about the
  memory limit: "This limit only applies to the buffer manager"
  (https://duckdb.org/docs/2.0/operations_manual/limits.html). Thread stacks and per-thread state
  are outside it.
- DuckDB performance guide, Environment
  (https://duckdb.org/docs/2.0/guides/performance/environment.html): "As a rule of thumb, DuckDB
  requires a minimum of 125 MB of memory per thread"; "Aim for 1-4 GB memory per thread"; "If you
  are working in a memory-constrained environment, consider limiting the number of threads". The
  existing 2 GiB-per-thread term in `_duckdb.py` follows the 1-4 GB guidance.
- Arrow and Polars read their env vars at start (cited in 3.1). `pyarrow.set_cpu_count` resizes
  Arrow's pool at run time.
- In-repo: the governor already forwards the slot budget (TB-1 fix #3), and `detect_usable_cpus`
  honours affinity and the cgroup CPU quota.

The design reuses these: forward the cap the way the governor does, keep DuckDB's documented
per-thread guidance as the thread term, and set the two pool knobs that the libraries document.

### 3.3 Design

1. **The cap becomes the out-of-core budget (DuckDB memory and threads).** Move
   `_governor._isolated_kwargs_with_budget` to `_isolated_common.py` as
   `kwargs_with_budget(budget_bytes, kwargs)`, with the same rule: it never overrides an explicit
   `out_of_core_budget_bytes`. `run_pipeline_isolated` calls it with `mem_cap_bytes` when a cap is
   set; the governor calls the moved function. Every DuckDB connection the child opens through
   `connect_duckdb` then takes its `memory_limit` from the cap, and `_threads_for_memory_limit`
   gives one thread for any per-connection limit under 2 GiB. At 768 MiB the limit is about 192 MB
   per instance and 1 thread. Governed jobs already run this way in production, so this adds no
   new routing state. It removes the difference between governed and directly capped runs.
2. **Arrow and Polars pools follow `native_threads` and the cap.** A new pure function in
   `_isolated_common.py`: `child_pool_threads(mem_cap_bytes, native_threads, usable_cpus) -> int`
   returns `max(1, min(native_threads, usable_cpus, mem_cap_bytes // 128 MiB))`, with the cap term
   only when capped. 128 MiB per thread is DuckDB's documented 125 MB minimum, rounded up. It is a
   conservative charge that also covers the about 40 MiB per thread that #666 measured for
   OpenBLAS. The driver puts `POLARS_MAX_THREADS=str(n)` in the spawn env next to `CAPPED_ENV`, and
   `"pool_threads": n` in the payload. The worker calls `pyarrow.set_cpu_count(n)` right after
   `apply_mem_cap` and before it loads sources. `OMP_NUM_THREADS` stays `"1"` (S1's guard), so
   OpenMP builds of BLAS stay off.
3. **DuckDB is not clamped to `native_threads`.** The row asked to size DuckDB "to the cap and to
   native_threads". `native_threads` is the native kernels' knob and defaults to 1. Clamping DuckDB
   to it would make every capped out-of-core join single-threaded by default, including large-cap
   governed jobs that run several DuckDB threads today. DuckDB keeps its own knob,
   `out_of_core_threads`, plus the memory term, which the cap now drives. Under a small cap the
   result is 1 thread in any case.

Speed trade-off:
- DuckDB: a cap under about 2 GiB per co-live instance gives 1 thread per connection. Out-of-core
  joins and dedups then run single-threaded and spill sooner. DuckDB's guidance recommends exactly
  this for a memory-constrained process, and the alternative is a SIGSEGV. Governed jobs see no
  change. Large caps keep their parallelism through the memory term.
- Arrow and Polars: with the default `native_threads=1`, nothing changes from #666 (already 1). A
  caller that raises `native_threads` gets back the Arrow and Polars parallelism that #666 removed,
  up to the cap term.
- Recommended answer: items 1 to 3 as written. The builder records Dell wall time for the b6b
  low-cap job and for one out-of-core FK job at 768 MiB and 4 GiB caps, before and after, for the
  PR (performance rulebook: workload, baseline, three runs). It is evidence, not a gate.

Size: `_isolated_common.py` about +45 (about 510 after #666; stays under 600). `_isolated_run.py`
about +6 (591 after #666; must end at 600 or less, so trim its module docstring item 2 if needed;
no census entry). `_isolated_worker.py` about +6. `_governor.py` about -22 (600 today). One
`changelog.d/` fragment. Five production files. All four execution modules are already on the
physical-seam sentry's allowlist, and none imports `execution.physical`.

### 3.4 Guarantee and non-goals

Guarantee: in a child that `run_pipeline_isolated` spawns with `mem_cap_bytes`, every DuckDB
connection opened through `connect_duckdb` applies a `memory_limit` derived from the cap (or from an
explicit `out_of_core_budget_bytes`) and a thread count of
`max(1, min(usable CPUs, out_of_core_threads, memory_limit // 2 GiB))`. Arrow's CPU pool and
Polars' pool hold at most `child_pool_threads(...)` threads. Once the cap term is the smallest,
none of these counts grows with the host's core count.

Non-goals:
- `detect_effective_memory_bytes` does not learn about RLIMIT, so an operator who runs the CLI
  under `ulimit -v` keeps today's sizing. V2-LOG: it would change routing for every uncapped
  in-process run.
- The `connect_duckdb` fallback when host RAM detection fails (`memory_limit=None`, DuckDB default
  threads) is unchanged. With the forwarded budget the capped child does not reach it.
- `data_discovery`'s untrusted sessions and the Postgres session (`config.threads`) do not run in
  the capped child. Unchanged.
- Arrow's IO pool (a fixed 8 threads, not per core) is unchanged.

### 3.5 Placement

No new src file. One new test file:

| File | Directory | CODEMAP line | Sits beside |
|---|---|---|---|
| `test_isolated_child_threads.py` (new) | `tests/unit/execution/` | "Pipeline spine and routes ... execution tests" | `test_isolated_run_env_flag.py`, `test_isolated_run.py` |

### 3.6 Build step 0: thread census on the Dell, before any code

Run the b6b low-cap test and `TestMemCapOom` on the Dell through `~/bin/vm-run`. Poll the child
through `on_spawn` for `/proc/<pid>/task/*/comm` and `VmData` at peak. Record the thread groups by
name (DuckDB, Arrow, Polars, rayon, other) and the peak. Repeat after the build. If a thread group
that grows with cores remains and 3.3 does not cover it, stop and report.

### 3.7 Acceptance tests (write first)

- AT-A1 spy `subprocess.Popen` and read the payload: `run_pipeline_isolated(...,
  mem_cap_bytes=768 MiB)` with no budget puts `out_of_core_budget_bytes == 768 MiB` in the child's
  kwargs. Fail-before on main.
- AT-A2 an explicit `out_of_core_budget_bytes` is kept; no cap gives no budget key; the governor's
  existing budget tests (`tests/unit/execution/test_governor*.py`) stay green on the moved
  function.
- AT-A3 real spawn, 768 MiB cap, `rlimit_kind="data"`, `execution_mode="out_of_core"`, a small
  two-table FK job: `result.quality_metrics["resources"]["out_of_core"]["applied"]` is not empty,
  and every entry has `threads == 1` and `memory_limit_bytes <= 768 MiB`. Fail-before on any host
  with at least 3 cores and 8 GiB RAM (the host-derived limit gives 2 or more threads), so it bites
  on the 8-core GCP runners and on the Dell.
- AT-A4 `child_pool_threads` cells: (768 MiB, 1, 26) -> 1; (768 MiB, 8, 26) -> 6; (768 MiB, 8, 64)
  -> 6; (8 GiB, 8, 26) -> 8; (8 GiB, 8, 4) -> 4; (None, 4, 64) -> 4; (64 MiB, 8, 64) -> 1.
- AT-A5 `_threads_for_memory_limit` cells with `detect_usable_cpus` patched to 64: `"192MB"` -> 1,
  `"4096MB"` -> 2, `"192MB"` with cap 8 -> 1. This covers the 64-core case without a 64-core host.
- AT-A6 real spawn, 1 GiB cap, `native_threads=4`: a probe in the spawned env (the same pattern as
  #666's guard) shows `POLARS_MAX_THREADS == "4"`, and a worker-side check shows
  `pyarrow.cpu_count() == 4` after setup. With `native_threads=1` both are 1.
- AT-A7 #666's guard and S1's AT-C3 stay green (BLAS knobs still `"1"`).
- Host evidence (PR, not CI): the step-0 census before and after, and the b6b low-cap peak VmData
  on the Dell well under the 722 MiB seen on 2026-11-18.

### 3.8 Mutations

- M-A1 remove the `kwargs_with_budget` call in `run_pipeline_isolated`: AT-A1 and AT-A3 red.
- M-A2 let `kwargs_with_budget` override an explicit budget: AT-A2 red.
- M-A3 `min` to `max` in `child_pool_threads`, or drop its cap term: AT-A4 red.
- M-A4 remove the worker's `set_cpu_count` call, or the `POLARS_MAX_THREADS` env entry: AT-A6 red.

### 3.9 Test scope

T0, T1. Named: `tests/unit/execution/test_isolated_child_threads.py`,
`test_isolated_run_env_flag.py`, `test_isolated_run.py`, `test_b6b_modes.py`, `test_governor*.py`,
the `_duckdb.py` thread tests under `tests/unit/execution/out_of_core/`,
`tests/sentry/test_module_size.py`, `tests/sentry/test_physical_seam_disconnection.py`, plus every
test file that imports `_isolated_run`, `_isolated_worker` or `_governor` (impact selection).
Full-suite triggers: none from the list. The change alters the kwargs of every directly capped
spawn, which routing reads, so the T2 gate set includes the `serial`-marked isolated tests on the
Dell. T3 at merge as usual. Reviewers: Dennis, then Codex.

## 4. Builder brief notes (all slices)

- Commit messages: Conventional Commits, subject 72 chars or fewer, no body unless it explains
  why, final line `cam`, author `ckeep <decoy@trydecoy.com>`, no other trailers.
- Test depth: T0 per edit, T1 per commit and at the slice head. Tests run on the Dell or the Mac
  through `~/bin/vm-run`, never on the .55 devbox.
- Defect classes to self-check by name: 3 (no exception context; S2), 5 (normalized scanner; the
  S1 shapes are listed), 6 (no new cross-package private import), 7 (no hidden CI failure; the S1
  sentry has no allowlist), 9 (mutations on the final head; record the head), 11 (pins move only
  down; S1 moves the probe's pin).
- Comments explain why, one line unless an invariant needs more, with no task or PR references.

## 5. Plan contract

### 5.1 Invariants

- A memory-capped child's allocator and thread env comes from one constant, `CAPPED_ENV`.
- No thread pool in a capped child grows with the host core count once the cap is the smallest
  term.
- Every engine Postgres connect is bounded by a connect timeout below the session deadline, and
  no failure path carries DSN text.

### 5.2 Class table

| # | Class | Closing structure | Sentry or test | Mutation |
|---|---|---|---|---|
| 1 | Value-bearing output (DSN text in S2) | `attach_read_only` keeps the composed DSN local; coded error raised after the `except` closes | AT-B4 leak cells over traceback, str, repr, caplog, cause and context | M-B4 raise inside the `except` |
| 2 | Cleanup on exit paths | N/A: no slice adds a resource owner; S2 reuses `connected_session`, which closes the connection and cancels the deadline on every exit | existing `test_postgres_snapshot_unit.py` staged-file and close cells stay green | N/A, no new disposal code |
| 3 | State and concurrency (deadline timer vs connect timeout) | 2 s gap between the two timers; `raise_for_interrupt` checks the deadline flag first | AT-B1 clamp cells, AT-B3 timing | M-B2 remove the clamp |
| 4 | Route parity and silent fallback (capped vs governed spawn) | `kwargs_with_budget` shared by `run_pipeline_isolated` and the governor | AT-A1, AT-A2, AT-A3 | M-A1 drop the call |
| 5 | Referential integrity | N/A: no FK handling changes; AT-A3 uses an FK job only to open DuckDB connections | none needed | none |
| 6 | Untrusted producer (user DSN text into libpq) | `with_connect_timeout` appends one keyword and never parses or echoes the DSN | AT-B2 cells per DSN form, AT-B3 user-value cell | M-B3 prepend instead of append |
| 7 | Check then use on a path (TOCTOU) | N/A: no slice reads or opens a path by name | none needed | none |
| 8 | Weak tests and overclaimed evidence | fail-before proof per AT; Dell census and timings recorded with the head they ran on | AT-C1, AT-B3, AT-A1, AT-A3 red on main | M-C2, M-A3 |
| 9 | Refactor drift (moved governor helper, seven env copies) | one constant and one helper, imported, never copied | S1 sentry `test_one_capped_env.py`; governor budget tests | M-C1 re-add a copy |
| 10 | Frozen contract drift | N/A: no reason code, artifact, CLI or public name changes (5.5) | `test_reason_baseline_frozen.py` stays green | none |

### 5.3 Enumerations

#### Exit paths of the Postgres session

- `src/decoy_engine/connectors/_postgres_session.py:250` ATTACH failure, `source_unreachable`.
- `src/decoy_engine/connectors/_postgres_session.py:148` deadline passed, `deadline_exceeded`.
- `src/decoy_engine/connectors/_postgres_session.py:207` DuckDB connect failure, `duckdb_unavailable`.
- `src/decoy_engine/connectors/_postgres_session.py:225` extension load failure.

#### Routes that open DuckDB in a capped child

- `src/decoy_engine/execution/_pipeline_route_exec.py:364` out-of-core route budget.
- `src/decoy_engine/execution/pipeline/_post_scan.py:152` post-scan key scan, capped at 512MB.
- `src/decoy_engine/execution/native/_pool_quality.py:246` pool-quality measurement.

#### FK shapes

N/A: no FK behavior changes in any slice. AT-A3 needs one single-column FK only to open
connections.

#### Fields

- `src/decoy_engine/connectors/postgres_snapshot.py:158` `threads` and `:161` `deadline_s` are read; no field is added.
- `src/decoy_engine/execution/out_of_core/_duckdb.py:37` `AppliedConnection` fields read by AT-A3.

#### Output surfaces

- Errors: `PostgresSnapshotError` message (code, location, cause type only).
- Logs: `postgres_snapshot failed code=%s location=%s`; no new log call in any slice.
- Run result: `quality_metrics["resources"]["out_of_core"]["applied"]` (existing field, values change under a cap).

### 5.4 Reuse inventory

- `CAPPED_ENV`, `apply_mem_cap`, `RLIMIT_KINDS` in `_isolated_common.py`.
- The governor's budget forwarding (moved, not copied).
- `_threads_for_memory_limit`, `bind_duckdb_run` and `AppliedConnection` in `out_of_core/_duckdb.py`.
- `detect_usable_cpus` in `execution/pipeline/_host.py`.
- `raise_for_interrupt`, `raise_for_setup_interrupt`, `sql_literal` in `_postgres_session.py`.
- Sentries: `test_module_size.py`, `test_physical_seam_disconnection.py`, `test_log_interpolation.py`,
  `test_sentry_manifest.py`; the `test_one_memory_limit_parser.py` pattern for the new sentry.

### 5.5 Frozen contracts

None touched. Reason codes are unchanged (S2 reuses `source_unreachable`). No public name, CLI flag,
artifact shape or determinism baseline changes. The capped spawn env gains `POLARS_MAX_THREADS`
(S3), which is internal.

### 5.6 Pre-mortem

- S2: the bundled extension does not apply a repeated `connect_timeout` (AT-B3 user-value cell
  fails). Fallback: refuse a user DSN that already sets `connect_timeout` with a value-free code,
  after an owner call. The AT finds this before review.
- S3: the census shows the b6b DuckDB threads come from a connection outside `connect_duckdb`.
  The builder stops; the plan gets an amendment.
- S3: forwarding the cap as the budget changes routing for a directly capped test that relied on
  host-sized routing. That test moves to an explicit `out_of_core_budget_bytes`; the AT stays.
- S1: a perf test's wall time grows past a timing assertion because Arrow runs single-threaded.
  Record it and report; do not widen the threshold.
