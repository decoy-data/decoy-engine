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

Base: engine `origin/main` `2c869dce63833f90b50fee216b2b71f057e37a1e`, with PR #666
(`fix/main-red-1118`) merged. All three slices build on its `CAPPED_ENV` (with
`OPENBLAS_NUM_THREADS`, `OMP_NUM_THREADS` and `MKL_NUM_THREADS` set to `"1"`), its guard test
`tests/unit/execution/test_isolated_run_env_flag.py:61`
`test_the_spawned_child_starts_no_blas_thread_pool`, and its `closing_port` fixture
(`tests/connectors/test_postgres_snapshot_unit.py:213`). Each builder branches from `origin/main`.
Every `path:line` in this plan was re-checked against `2c869dce`; between `84cc7d798` and it only
`_isolated_common.py`, `_isolated_run.py` and the two test files above changed, which moved the
spawn env from `_isolated_run.py:454` to `:455`. The probe call is cited at `_probe.py:256`, where
`run_isolated(` starts (r2 said `:257`).

Source: the root cause of the red main on 2026-11-18 (gate-selfhosted run 44221036975, Dell
runners, 26 cores) and the two V2-LOG items Codex left on #666.

Revision 2 (2026-11-18): applies Dennis r1 on `bc836eb6` (GO-WITH-FIXES: 4 MAJOR, 7 MINOR, 3 LOW),
all in place. D1: the child computes its own out-of-core budget (3.3 item 1, AT-A3, AT-A8, M-A1).
D2: the routing probe's capped children are listed and get a parity AT (3.1, AT-A9, 3.9, 5.3). D3:
`native_threads` leaves `child_pool_threads` (3.3 item 2, AT-A4, speed trade-off). D4: AT-B3 runs
the connect in a thread with a bounded join (2.8, M-B3). D5: DSN edge cases (2.4, AT-B2 to B5). D6:
multi-address row (2.2, 2.5). D7: guard shapes (2.6, AT-B6). D8: sentry by constant equality (1.4,
AT-C2). D9: RLIMIT setter copies and a setrlimit shape (1.1 to 1.4). D10: registration (1.4). D11:
AT-A6 host-independent. D12: AT-A3 fail-before wording. D13: no new test file in the flat
directory (3.5). D14: the 128 MiB figure is an estimate (3.3 item 2). S3's changelog says that it
restores the Arrow parallelism that #666 removed.

Revision 3 (2026-11-18): applies Codex on `b3f9492` (GO-WITH-FIXES; agrees with the quarter-of-cap
pool rule). V1-1: `with_connect_timeout` never changes existing DSN bytes; a malformed key/value DSN
is left for libpq to reject (2.4, AT-B2, AT-B7, M-B5). V1-2: a remainder under the budget floor is
a classified memory failure before DuckDB opens, not an overcommit (3.3 item 1, 3.4, AT-A10,
AT-A11, M-A7). DESIGN: S1's guarantee is narrowed to deduplication plus a guard, and the sentry
gains a spawn-site rule (1.2 to 1.4, AT-C2, M-C6). V2-LOG items done now: the S2 guarantee covers
one attempted address (2.2); AT-C4, AT-A7, AT-A8 and AT-A9 are marked as supporting evidence;
named mutations for AT-C5, AT-B4 and AT-B6 (M-C7, M-B7, M-B6); the base is `2c869dce` and every
cited line is re-checked.

## 0. Slices

| Slice | Row | Risk | Prod files | Est. lines (prod / tests) | Reviewers | Depends on |
|---|---|---|---|---|---|---|
| S1 CAPPED-ENV-ONE | (c) one capped env and one RLIMIT setter, sentry with a spawn-site rule, guard asserts all three BLAS knobs | R1 | 0 src, 4 scripts | about -60 / +260 | Codex | #666 (merged) |
| S2 PG-CONNECT-TIMEOUT | (b) libpq `connect_timeout` below the session deadline | R2 (credential text, value-leak area) | 2 | about +65 / +240 | Dennis, then Codex | #666 (`closing_port`, merged) |
| S3 CHILD-THREADS | (a) size DuckDB and per-core pools in the capped child | R2 (resource limits, execution path) | 4 | about +90 / +280 | Dennis, then Codex | #666 (merged); rebases on S1 |

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

Two scripts also keep their own RLIMIT setter instead of `_isolated_common.apply_mem_cap`:
- `scripts/fk-scale/bench_worker_fk.py:192-196` `_apply_mem_cap(cap_mb)` (RLIMIT_DATA). Its driver
  spawns the capped worker at `:321` with `{**os.environ, "TMPDIR": ..., "ARROW_DEFAULT_MEMORY_POOL":
  "system"}`, so that worker gets neither the arena pin nor the BLAS knobs.
- `scripts/fk_memory_probe.py:269` `_apply_mem_cap(cap_mb, rlimit_kind)` with its own `_RLIMITS`
  dict at `:146`. `scripts/build_floor_probe.py:52` imports it and calls it at `:183`.

S1 converts both setters and the bench driver's spawn env (1.3).

Spawn sites that start a capped child, at `2c869dce` (the recognition rule is in 1.4, rule 4):
- `src/decoy_engine/execution/_isolated_run.py:456` (`Popen`, env built at `:455` from
  `CAPPED_ENV`): already correct.
- The seven copy modules: `scripts/fk_memory_probe.py:859` (and its uncapped sweep at `:754`, no
  env), `scripts/route_reorder_vs_batchjoin_ab.py:301`,
  `tests/perf/test_out_of_core_reorder_memory.py:323`,
  `tests/perf/test_out_of_core_reorder_multi_edge_memory.py:371`,
  `tests/perf/test_out_of_core_reorder_wide_raw_memory.py:306`,
  `tests/perf/test_ooc_external_sort_memory.py:258`,
  `tests/perf/test_out_of_core_relation_dedup_memory.py:272`: env from the local copy.
- `scripts/fk-scale/bench_worker_fk.py:323` (`run_worker`, env from `:321`): no `CAPPED_ENV`.
- Tests that spawn a script with `--mem-cap-mb` and no env:
  `tests/perf/test_out_of_core_memory_sentinel.py:122`, `:185`, `:188`, `:229`;
  `tests/unit/test_fk_memory_probe_strategy.py:49`, `:92`; `tests/unit/scripts/test_fk_scale_infra.py:215`.

### 1.2 Guarantee and non-goals

Guarantee (deduplication plus a guard, deliberately narrow): there is one capped env,
`CAPPED_ENV`, and one RLIMIT_DATA or RLIMIT_AS setter, `apply_mem_cap`, both in
`_isolated_common.py`. CI fails on a new occurrence of the constant `"MALLOC_ARENA_MAX"` (or a
keyword of that name), or on a `setrlimit` call that can set RLIMIT_DATA or RLIMIT_AS, anywhere
else. CI also fails when a spawn site that the sentry recognizes as capped (1.4, rule 4) does not
pass an env built from `CAPPED_ENV`. The plan does not claim that every capped spawn is
recognized: a spawn in a module with none of rule 4's markers is outside the guard. The #666 guard
test asserts that all three BLAS knobs reach the child as `"1"`, also when the parent sets them to
`"8"`.

Non-goals: no change to `CAPPED_ENV` values. No change to the perf tests' jobs or thresholds. The
uncapped fk-scale bench runs keep their env, so bench numbers stay comparable (the bench env still
names `CAPPED_ENV` in a conditional, 1.3). Spawns in modules with no rule-4 marker, and an alias
such as `from ... import CAPPED_ENV as X`, are V2-LOG. `setrlimit` calls on
other limits (`RLIMIT_CORE`, `RLIMIT_NOFILE`) and `setrlimit` text inside string literals (child
scripts such as `tests/unit/execution/test_isolated_memwatch_run.py:201`) are out of scope.
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

The RLIMIT setters:
- `fk_memory_probe.py`: delete `_apply_mem_cap` and `_RLIMITS`; call
  `apply_mem_cap(args.mem_cap_mb * _MIB, args.rlimit_kind)` at `:1036`, and take the argparse
  `choices` from `sorted(RLIMIT_KINDS)`.
- `build_floor_probe.py`: import `apply_mem_cap` from `_isolated_common` instead of the probe's
  private helper, and call `apply_mem_cap(args.rlimit_mib * _MIB, "data")`.
- `bench_worker_fk.py`: delete `_apply_mem_cap`; `run_child` calls
  `apply_mem_cap(args.mem_cap_mb * _MIB, "data")`. In `_one_run`, when `args.mem_cap_mb` is set,
  the spawn env is `{**os.environ, **(CAPPED_ENV if args.mem_cap_mb else {}), "TMPDIR": ...,
  "ARROW_DEFAULT_MEMORY_POOL": "system"}`, so uncapped runs keep today's env and the site still
  passes rule 4.

The spawn sites in 1.1 that lack `CAPPED_ENV` get `env={**os.environ, **CAPPED_ENV}`: the
fk_memory_probe sweep at `:754` (it runs the same worker command as the capped run at `:859`, so the
two measurements become comparable), and the seven test calls that pass `--mem-cap-mb`.
`CAPPED_ENV` sets no cap; it only pins allocator and BLAS threads, as every production isolated
child already has since #666.

`scripts/fk_memory_probe.py` is a pinned over-max legacy file (`tests/sentry/test_module_size.py:151`
and `tests/sentry/baselines/module-size.json`, both 1056). It shrinks, so both pins move down to the
new exact count. Class 11 allows a pin to move down; list the moved pin in the report.

### 1.4 Choke point and sentry

Choke points: `CAPPED_ENV` and `apply_mem_cap` in `_isolated_common.py`. Guard:
`tests/sentry/test_one_capped_env.py`, modelled on `tests/sentry/test_one_memory_limit_parser.py`.
It parses (AST, not regex) every `*.py` under `src/`, `tests/`, `scripts/`, `testflight/` and `ci/`,
and reports `path:line` for each of these outside `src/decoy_engine/execution/_isolated_common.py`:

1. any `ast.Constant` whose value equals `"MALLOC_ARENA_MAX"` (equality, not substring, so prose in
   a comment or docstring is not a finding). This one rule covers a dict key, a subscript store,
   `.setdefault(...)`, `monkeypatch.setenv(...)`, `os.putenv(...)` and any other call that names
   the var.
2. any `ast.keyword` whose `arg` equals `"MALLOC_ARENA_MAX"` (covers `dict(MALLOC_ARENA_MAX=...)`
   and `env.update(MALLOC_ARENA_MAX=...)`).
3. any call to `setrlimit` (an attribute `x.setrlimit` or a bare name) whose first argument is not
   a name or attribute ending in an RLIMIT other than `RLIMIT_DATA` and `RLIMIT_AS`. So
   `RLIMIT_DATA`, `RLIMIT_AS` and any computed first argument (`_RLIMITS[kind]`) are findings, and
   `RLIMIT_CORE` is not.
4. a recognized capped spawn site whose env is not built from `CAPPED_ENV`. A module is capped when
   it calls `apply_mem_cap` or `setrlimit`, passes a keyword `mem_cap_bytes` or `mem_cap_mb`, holds a
   string constant that starts with `--mem-cap`, or references the name `CAPPED_ENV`. In a capped
   module, a spawn site is a call to `subprocess.Popen`, `subprocess.run`, `subprocess.call`,
   `subprocess.check_call`, `subprocess.check_output`, or the fk-scale helper `run_worker`. The site
   passes when its `env=` value references the name `CAPPED_ENV`, or is a local name whose
   assignment in the same function references it. A site with no `env=`, or with an env that does
   not reference `CAPPED_ENV`, is a finding. At `2c869dce` the rule finds the sites listed in 1.1
   except `_isolated_run.py:456`.

The one exemption: a constant of rule 1 that is the first positional argument of a call whose
function is an attribute named `get` or a name or attribute named `getenv` (`os.environ.get(...)`,
`env.get(...)`, `os.getenv(...)`). Reads only; nothing else is exempt. The sentry docstring lists
the covered shapes; other spellings are V2-LOG. There is no allowlist.

Registration: add the file to the manifest in `tests/sentry/test_sentry_manifest.py:57`, the same
way `test_one_memory_limit_parser.py` is listed. `scripts/dev/sentry_registry.toml` binds only
sentries that own a baseline file under `tests/sentry/baselines/`; this sentry has none, so it gets
no row there.

### 1.5 Placement

| File | Directory | CODEMAP line | Sits beside |
|---|---|---|---|
| `test_one_capped_env.py` (new) | `tests/sentry/` | "Sentry test: existing rules in `tests/sentry/`" | `test_one_memory_limit_parser.py` |

No other new file.

### 1.6 Acceptance tests (write first)

- AT-C1 `test_one_capped_env.py::test_no_capped_env_copy_outside_isolated_common`. Fail-before: on
  `2c869dce` it lists the seven env copies, the two setters (`bench_worker_fk.py:196`,
  `fk_memory_probe.py:272`) and the spawn sites in 1.1 without `CAPPED_ENV`. After the build the list
  is empty.
- AT-C2 seeded source strings, one parametrized test. Found, one cell each: a dict literal key;
  `dict(MALLOC_ARENA_MAX="2")`; `env["MALLOC_ARENA_MAX"] = "2"`; `env.setdefault(...)`;
  `env.update(MALLOC_ARENA_MAX="2")`; `monkeypatch.setenv("MALLOC_ARENA_MAX", "2")`;
  `os.putenv("MALLOC_ARENA_MAX", "2")`; `resource.setrlimit(resource.RLIMIT_DATA, ...)`;
  `setrlimit(RLIMIT_AS, ...)` after a from-import; `resource.setrlimit(_RLIMITS[kind], ...)`. Not
  found: `os.environ.get("MALLOC_ARENA_MAX")`; `os.getenv("MALLOC_ARENA_MAX")`; a docstring that
  mentions MALLOC_ARENA_MAX in a sentence; `resource.setrlimit(resource.RLIMIT_CORE, ...)`; a
  string literal that contains `resource.setrlimit(resource.RLIMIT_DATA, ...)`.
  Rule 4 cells, each in a seeded module that holds a `--mem-cap-mb` constant. Found:
  `subprocess.Popen(cmd)` with no env; `subprocess.run(cmd, env={**os.environ})`;
  `env = {**os.environ}` then `subprocess.run(cmd, env=env)`; `run_worker(cmd, env=env, ...)` with
  `env` not from `CAPPED_ENV`. Not found: `subprocess.run(cmd, env={**os.environ, **CAPPED_ENV})`;
  `env = {**os.environ, **CAPPED_ENV}` then `Popen(cmd, env=env)`; the conditional form
  `**(CAPPED_ENV if capped else {})`; and `subprocess.run(cmd)` in a module with no rule-4 marker.
- AT-C3 edit `tests/unit/execution/test_isolated_run_env_flag.py::test_the_spawned_child_starts_no_blas_thread_pool`:
  the parent sets all three knobs to `"8"` with `monkeypatch.setenv`, and the test asserts
  `{k: seen[k] for k in BLAS_KNOBS} == dict.fromkeys(BLAS_KNOBS, "1")` before the thread-count
  check. `BLAS_KNOBS` is a tuple in the test file, not exported from src.
- AT-C4 (supporting evidence, regression only; it may pass before the build) the converted perf
  tests collect (`pytest --collect-only` on the five files), and `--help`
  exits 0 for `scripts/fk_memory_probe.py`, `scripts/route_reorder_vs_batchjoin_ab.py`,
  `scripts/build_floor_probe.py` and `scripts/fk-scale/bench_worker_fk.py`.
- AT-C5 the bench driver's env: a unit cell calls the env builder of `bench_worker_fk._one_run`
  (extracted as a small `_worker_env(scratch, capped)` if needed) and asserts that a capped run's
  env contains `CAPPED_ENV` and an uncapped run's env does not contain `MALLOC_ARENA_MAX`.

### 1.7 Mutations

- M-C1 re-add a local `_CAPPED_ENV = {"MALLOC_ARENA_MAX": "2", ...}` to one perf test: AT-C1 red.
- M-C2 drop `MKL_NUM_THREADS` from `CAPPED_ENV`: AT-C3 red. (#666's guard stayed green on this
  mutant, which is the Codex finding.)
- M-C3 change rule 1 from equality to a substring test: the docstring cell of AT-C2 red.
- M-C4 widen the exemption to any call (not only `get` and `getenv`): the `monkeypatch.setenv` and
  `os.putenv` cells of AT-C2 red.
- M-C5 drop rule 3's computed-argument case: the `_RLIMITS[kind]` cell of AT-C2 red.
- M-C6 accept any `env=` in rule 4 (drop the `CAPPED_ENV` reference check): the
  `env={**os.environ}` cells of AT-C2 red, and AT-C1 stays red on any unconverted site.
- M-C7 build the bench env without `CAPPED_ENV` in the capped branch: AT-C5 red.

### 1.8 Test scope

T0 and T1. Named: `tests/sentry/test_one_capped_env.py`,
`tests/unit/execution/test_isolated_run_env_flag.py`, `tests/sentry/test_module_size.py`,
`tests/sentry/test_sentry_manifest.py`, `tests/perf/test_out_of_core_memory_sentinel.py`,
`tests/unit/test_fk_memory_probe_strategy.py`, `tests/unit/scripts/test_fk_scale_infra.py`. Run the
five converted perf tests once on the Dell with
their perf marker, and record peak memory and wall time before and after. The BLAS knobs lower
VmData, so the memory thresholds only get easier. Wall time can move, because `OMP_NUM_THREADS=1`
also pins Arrow's CPU pool (see 3.1). Record it; do not gate on it.

Full-suite triggers: none (no shared fixture, test config, tooling, or moved test). T3 at merge as
usual.

Size: 0 src files, 4 scripts (all shrink or stay flat), 5 perf tests, 3 more tests that gain an
env (sentinel, probe strategy, fk-scale infra), 1 new sentry, 1 manifest edit, 1 guard-test edit,
2 pin edits. Under 10 production files and 800 lines. Add
`scripts/fk-scale/` and `scripts/build_floor_probe.py` to the T1 set: run their `--help` (AT-C4) and
AT-C5.

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
the session deadline when `deadline_s >= 4`. For a well-formed DSN whose connect makes a single
attempt (one host that resolves to one address), a host that drops SYNs, or a server that never
answers the startup packet, then fails as `source_unreachable` before the deadline. More attempts
are bounded per attempt only (non-goals). Errors stay value-free:
no DSN, host, port, user, database, password or timeout figure in the message, the logs,
`__cause__` or `__context__`.

Non-goals:
- The engine never changes the bytes of the user's DSN; it only appends. A key/value DSN that ends
  in an unpaired backslash escapes the separator space, so libpq reads the appended keyword as part
  of the last value and accepts the string. That DSN gets no engine connect timeout and keeps
  today's behavior (the session deadline). A DSN that libpq rejects (an unterminated quote) fails
  as `source_unreachable` before any connect (AT-B7).
- A `connect_timeout` that the user put in the DSN is replaced by the engine value (the later value
  wins, see 2.3). Keeping a smaller user value would need a DSN parser. V2-LOG.
- A DNS lookup that hangs (`getaddrinfo`) is not covered by `connect_timeout`. It stays
  `deadline_exceeded`.
- The timeout applies per resolved address ("This timeout applies separately to each host name or
  IP address"). A multi-host DSN, or one host name that resolves to several addresses (for example
  an IPv6 and an IPv4 record), can try k black-holed addresses in turn. When k times the timeout
  passes the deadline, the result stays `deadline_exceeded` (2.5). Accepted; per-address budgeting
  would need the engine to resolve names itself.
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
  - URI form (libpq's rule: the text starts with `postgresql://` or `postgres://`): when the text
    ends in `?` or `&`, append `connect_timeout=N` with no separator; else append
    `&connect_timeout=N` when the text has a `?`, else `?connect_timeout=N`.
  - Key/value form, including the empty DSN (connect from `PG*` env vars): append
    ` connect_timeout=N`.
  - Existing DSN bytes are never changed, stripped or re-quoted. Malformed key/value input is left
    for libpq: an unterminated quote stays unterminated, libpq rejects the string, and the ATTACH
    fails as `source_unreachable` with no connect (AT-B7). An unpaired trailing backslash is the
    one malformed shape libpq accepts; 2.2 records what it does.
- `attach_read_only` gains a `connect_timeout_s: int` parameter and builds the ATTACH from
  `sql_literal(with_connect_timeout(dsn.get_secret_value(), connect_timeout_s))`.
  `open_read_session` passes `connect_timeout_s(config.deadline_s)`. The composed text exists only
  as a local in `attach_read_only`.

The existing leak rule stays: the `except` block records only `type(exc).__name__`, and the coded
error is raised after the block has closed (class 3). Nothing new is logged.

Size: `_postgres_session.py` goes from 299 to about 350 lines. One `changelog.d/` fragment. Two
production files.

### 2.5 Reason-code mapping

| Case | Before | After |
|---|---|---|
| Refused or reset (RST), DNS NXDOMAIN, bad password | `source_unreachable` | `source_unreachable` |
| SYN dropped, or a server that accepts and never answers, `deadline_s >= 4` | `deadline_exceeded` | `source_unreachable` after about `connect_timeout_s(deadline_s)` |
| Same, `deadline_s` from 1 to 3 | `deadline_exceeded` | either code; the timers coincide, and both are true |
| DNS lookup hangs | `deadline_exceeded` | `deadline_exceeded` |
| Several resolved addresses (multi-host DSN, or one name with several records) all black-holed, k x `connect_timeout_s` past the deadline | `deadline_exceeded` | `deadline_exceeded` |
| Same, k x `connect_timeout_s` under the deadline | `deadline_exceeded` | `source_unreachable` |
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
`tests/connectors/test_postgres_session.py`. It walks the AST of `src/decoy_engine/**/*.py`, takes
every string constant (f-string parts included), and matches these patterns case-insensitively:

1. `type\s+postgres\b` (the ATTACH option, any case, for example lowercase `type postgres`);
2. `attach\s+'postgres(ql)?:` (DuckDB's prefixed-DSN form `ATTACH 'postgres:dbname=...'`);
3. `postgres_attach\s*\(`;
4. `postgres_scan(_pushdown)?\s*\(` (a table function that takes a DSN as its first argument).

Allowed: one hit, shape 1, in `_postgres_session.py`. Any other hit fails with `path:line`. The
check runs over the scanner function with seeded sources too (AT-B6). Mutation M-B1 proves that the
wrap itself is not bypassed.

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
  `"postgresql://u@h/d?"` -> `"postgresql://u@h/d?connect_timeout=7"`;
  `"postgresql://u@h/d?sslmode=require&"` -> `"postgresql://u@h/d?sslmode=require&connect_timeout=7"`;
  `"host=h password=a\\"` (one trailing backslash) -> `"host=h password=a\\ connect_timeout=7"`
  (the backslash is kept; the input is a prefix of the output);
  `"host=h password=a\\\\"` (two) -> the same two backslashes, then ` connect_timeout=7`;
  for every cell, `out.startswith(dsn)` holds (no existing byte changes);
  a key/value DSN with a quoted value that contains `?` stays in key/value form.

Behaviour against the bundled extension (in `test_postgres_snapshot_unit.py`, which already has
`ext_dir` and #666's `closing_port`). Each cell below runs in both DSN forms, key/value
(`host=127.0.0.1 port=<n> user=u dbname=d password=PW_SECRET`) and URI
(`postgresql://u:PW_SECRET@127.0.0.1:<n>/d`):
- AT-B3 a `silent_port` fixture: a loopback listener whose accept thread holds each accepted
  socket open and sends nothing. Its teardown closes the listener and every accepted socket, also
  when the test failed or the join below timed out; the close sends FIN, so a blocked libpq read
  returns. libpq blocks in C, where pytest-timeout cannot preempt it, so the test runs
  `snapshot_tables_to_parquet` (with `deadline_s=6`) in a daemon thread that stores its exception,
  and joins it with a 15 s bound. Assert: the thread finished within the bound, the stored error is
  a `PostgresSnapshotError` with `code == "source_unreachable"`, and the elapsed time is under 6 s.
  A thread still alive at 15 s fails the test with "connect did not return", never a hang. The
  user-value cell puts `connect_timeout=600` in the DSN (key/value: ` connect_timeout=600`; URI:
  `?connect_timeout=600`) and gets the same result. That proves on the bundled extension that the
  later value wins for repeated keys in both forms. Fail-before: on main the call gives
  `deadline_exceeded`, or the join times out.
- AT-B4 leak cells on AT-B3's error, both forms: the rendered traceback, `str`, `repr` and every
  caplog message contain none of `PW_SECRET`, `127.0.0.1`, the port number, `user=u`, `u:`,
  `dbname`, `connect_timeout`; and `err.__cause__ is None and err.__context__ is None`.
- AT-B5 spy cell, both forms: a fake connection records the executed ATTACH text. It contains
  `connect_timeout=<connect_timeout_s(deadline_s)>` exactly once after the user's text, with the
  separator that 2.4 names for that form.
- AT-B6 `test_type_postgres_attach_has_one_site` (2.6) on the real tree, plus seeded sources, one
  cell per shape: `"ATTACH '...' AS x (type postgres)"`; `"attach 'postgres:dbname=d' AS x"`;
  `"CALL postgres_attach('dbname=d')"`; `"SELECT * FROM postgres_scan('dbname=d', 'public', 't')"`.
  A negative cell: the `'postgres_scanner'` extension-name query at `_postgres_session.py:219` is
  not a hit.
- AT-B7 rejection cell on the bundled extension: the key/value DSN
  `host=127.0.0.1 port=<closing_port> user=u dbname=d password='PW_SECRET` (unterminated quote)
  raises `PostgresSnapshotError` with `code == "source_unreachable"`, run under the same 15 s bounded
  join as AT-B3. The AT-B4 leak checks apply to it: no `PW_SECRET`, host, port, `user=u`, `dbname`
  or `connect_timeout` in the traceback, `str`, `repr` or caplog, and no `__cause__` or
  `__context__`. Before the build the same DSN gives the same code; the cell pins that the append
  keeps a rejected DSN rejected and value-free.
- Existing `test_connect_failure_leaks_no_dsn` (#666's `closing_port`) stays green.

Host evidence (PR, not CI): on the Dell, the old DSN `host=127.0.0.1 port=1` with `deadline_s=20`
gives `source_unreachable` in about 10 s. WSL2 mirrored networking black-holes closed loopback
ports, so the Dell reproduces a SYN-dropping host with no extra setup. Record the time.

### 2.9 Mutations

- M-B1 build the ATTACH from the raw DSN (skip `with_connect_timeout`): AT-B3 and AT-B5 red.
- M-B2 return `PG_CONNECT_TIMEOUT_S` without the deadline clamp: AT-B1 cell 6 -> 4 red, and AT-B3
  runs past 6 s.
- M-B3 put the keyword first instead of last: the AT-B3 user-value cell red, by the 15 s join bound
  (the user's 600 s wins), not by a hang.
- M-B4 raise the coded error inside the `except` block: the AT-B4 context cell red.
- M-B5 strip or rewrite any existing DSN byte (for example strip a trailing backslash), or drop
  the `?`/`&` ending case: the matching AT-B2 cell and its `startswith` check red.
- M-B7 put the exception text (or `str(exc)`) into the coded error's message: the AT-B4 and AT-B7
  `PW_SECRET` cells red.
- M-B6 make the guard case-sensitive: the lowercase `type postgres` cell of AT-B6 red.

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

Who spawns a capped child:
- The governor, `run_job_with_governor`, forwards its slot budget as an explicit
  `out_of_core_budget_bytes` (`_governor.py:336`, `_isolated_kwargs_with_budget` at `:459`). That
  budget is explicit, so S3 does not change it.
- The routing probe. `_pipeline_routing_signals.py:491` and `_transforms_admission.py:286` both
  pass `mem_cap_bytes=budget.budget_bytes` into the probe, and `_probe.py:256` calls
  `run_isolated(..., mem_cap_bytes=..., execution_mode="full_frame")` with no
  `out_of_core_budget_bytes`. These are production callers: the probe's measured peak feeds
  `probe_fits` and so `resolve_execution_route`. S3 changes the probe child's pools, so S3 must
  show that the routing verdict does not move (AT-A9).
- Direct `run_pipeline_isolated(..., mem_cap_bytes=...)` callers: the b6b low-cap test,
  `TestMemCapOom`, and any caller that caps without the governor. These hit the bug.

The governor path is not fully right either: it hands DuckDB the whole slot budget and does not
subtract what the child already holds. That is out of scope here (an explicit budget is never
overridden, 3.4).

Other per-core pools in the child:
- Arrow's CPU pool: "The number of threads is determined at startup by inspecting the
  OMP_NUM_THREADS and OMP_THREAD_LIMIT environment variables. If neither is present, it will default
  to the number of hardware threads on the system" (pyarrow `cpu_count` docs). #666 sets
  `OMP_NUM_THREADS=1`, and `_isolated_run.py:455` applies `CAPPED_ENV` to every isolated child,
  capped or not. So since #666 every isolated child runs Arrow's pool at one thread. #666's
  changelog says speed does not change. That holds for the native kernels, not for Arrow work such
  as `to_pandas` or threaded Parquet reads.
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
  are outside it, and so is everything the child allocated before DuckDB opened.
- DuckDB performance guide, Environment
  (https://duckdb.org/docs/2.0/guides/performance/environment.html): "As a rule of thumb, DuckDB
  requires a minimum of 125 MB of memory per thread"; "Aim for 1-4 GB memory per thread"; "If you
  are working in a memory-constrained environment, consider limiting the number of threads". The
  existing 2 GiB-per-thread term in `_duckdb.py` follows the 1-4 GB guidance.
- Arrow and Polars read their env vars at start (cited in 3.1). `pyarrow.set_cpu_count` resizes
  Arrow's pool at run time.
- In-repo: `resolve_ooc_memory_limit` already subtracts a reserve from a host-derived ceiling
  (`out_of_core/_budget.py:480-483`), but skips it for an explicit budget. `scripts/fk_memory_probe.py:591`
  already sizes DuckDB from a fraction of a cap. `_isolated_memwatch.read_vm_fields` reads `VmData`
  and `VmSize` from `/proc`. `detect_usable_cpus` honours affinity and the cgroup CPU quota.

The design reuses these: measure what the child holds with the existing reader, hand DuckDB only
the rest, keep DuckDB's documented per-thread guidance as the thread term, and set the two pool
knobs that the libraries document.

### 3.3 Design

1. **The capped child sizes its own out-of-core budget.** In `_isolated_worker._run`, after
   `apply_mem_cap` (`_isolated_worker.py:161`) and as the first step inside the existing `try`
   (before `_load_sources` at `:166`), when `mem_cap_bytes` is set and the payload kwargs have no
   `out_of_core_budget_bytes`:
   - read the baseline with `read_vm_fields(os.getpid(), ...)`: `VmData` for `rlimit_kind="data"`,
     `VmSize` for `"as"` (the field the kernel checks against that limit);
   - set `kwargs["out_of_core_budget_bytes"] = child_ooc_budget(cap, baseline, pool_threads)`.

   `child_ooc_budget` is a new pure function in `_isolated_common.py`. It computes the remainder
   first, `remainder = cap - baseline - pool_threads * CHILD_THREAD_RESERVE_BYTES`. When
   `remainder < _MIN_BUDGET_BYTES` it raises a bare `MemoryError()` (no message, so nothing
   value-bearing). Otherwise it returns `remainder` unchanged; it never rounds up to the floor, so
   the budget never promises memory the child does not have. `_MIN_BUDGET_BYTES` is imported from
   `out_of_core/_budget.py` (one floor, not a copy). Because the call sits inside the worker's
   `try`, the existing `except BaseException` path classifies it: `is_memory_failure` gives outcome
   `oom_killed`, and `reason_from_exception` maps `MemoryError` to the existing
   `process_out_of_memory` (`reason_adapter.py:111`, fixed message "The process ran out of
   memory."). No new reason code. Sources are not loaded and DuckDB never opens. It never
   overrides an explicit budget, so governed jobs and any caller that passes a budget keep today's
   behavior. `resolve_ooc_memory_limit` then divides this budget across the co-live instances as
   it does for the governor, and `_threads_for_memory_limit` gives one thread for any per-instance
   limit under 2 GiB. Worked case, after #666 (Dennis measured about 0.5 GiB after imports): cap
   768 MiB, baseline about 500 MiB, one pool thread, budget about 140 MiB, so DuckDB spills early
   instead of the child dying. When the remainder is under the floor, the job cannot fit, and it
   fails at once as a classified, value-free memory failure instead of handing DuckDB a limit
   larger than the memory left.
2. **Arrow and Polars pools follow the cap.** A new pure function in `_isolated_common.py`:
   `child_pool_threads(mem_cap_bytes, usable_cpus) -> int` returns
   `max(1, min(usable_cpus, mem_cap_bytes // (4 * CHILD_THREAD_RESERVE_BYTES)))`, with the cap
   term only when capped; uncapped it returns `usable_cpus`. The factor 4 holds the pools' reserve
   to at most a quarter of the cap. Without it (`cap // reserve`, as r1 suggested) the reserve in
   item 1 would equal the whole cap and DuckDB would always get the floor. `CHILD_THREAD_RESERVE_BYTES = 128 MiB` is an
   engineering estimate, not a DuckDB figure: #666 measured about 40 MiB per thread for OpenBLAS
   arenas and buffers, plus an 8 MiB stack, plus headroom for Arrow and Polars per-thread scratch.
   The constant's comment says so and points to the step-0 census as its evidence. The driver
   computes `n = child_pool_threads(mem_cap_bytes, detect_usable_cpus())`, puts
   `POLARS_MAX_THREADS=str(n)` in the spawn env next to `CAPPED_ENV`, and `"pool_threads": n` in the
   payload. The worker calls `pyarrow.set_cpu_count(n)` right after `apply_mem_cap` and before it
   loads sources, and passes `n` to `child_ooc_budget`. `OMP_NUM_THREADS` stays `"1"` (S1's guard),
   so OpenMP builds of BLAS stay off. `native_threads` is not a term: it is the native kernels'
   knob (default 1), and tying Arrow and Polars to it would keep #666's single-thread Arrow pool in
   every default run.
3. **DuckDB is not clamped to `native_threads`.** The row asked to size DuckDB "to the cap and to
   native_threads". `native_threads` defaults to 1. Clamping DuckDB to it would make every capped
   out-of-core join single-threaded by default, including large-cap governed jobs that run several
   DuckDB threads today. DuckDB keeps its own knob, `out_of_core_threads`, plus the memory term,
   which the child's budget now drives. Under a small cap the result is 1 thread in any case.

Speed trade-off:
- DuckDB: a cap whose remaining budget is under about 2 GiB per co-live instance gives 1 thread per
  connection. Out-of-core joins and dedups then run single-threaded and spill sooner. DuckDB's
  guidance recommends exactly this for a memory-constrained process, and the alternative is a
  SIGSEGV. Governed jobs see no change. Large caps keep their parallelism through the memory term.
- Arrow and Polars: every isolated child gets back the per-core pools that #666 removed, up to the
  cap term. An uncapped isolated child returns to its pre-#666 Arrow pool size. A capped child gets
  `cap // 512 MiB` threads at most (1 at 768 MiB, 8 at 4 GiB). The S3 changelog fragment says that it restores
  the Arrow parallelism that #666 removed.
- Recommended answer: items 1 to 3 as written. The builder records Dell wall time, before and
  after, for: the b6b low-cap job; one out-of-core FK job at 768 MiB and at 4 GiB caps; and one
  uncapped Parquet-heavy isolated job (Arrow pool 1 before, usable CPUs after). Workload, baseline
  and three runs each (performance rulebook), in the PR. Evidence, not a gate.

Size: `_isolated_common.py` about +45 (about 510 after #666; stays under 600). `_isolated_run.py`
about +6 (591 after #666; must end at 600 or less, so trim its module docstring item 2 if needed;
no census entry). `_isolated_worker.py` about +20. `_governor.py` unchanged. One `changelog.d/`
fragment. Four production files. All three execution modules are already on the physical-seam
sentry's allowlist, and none imports `execution.physical`. The new import of
`out_of_core._budget._MIN_BUDGET_BYTES` into `_isolated_common.py` is inside `execution` (class 6
check: if the import linter flags the private name, re-export it as a public constant in
`_budget.py` instead of copying it).

### 3.4 Guarantee and non-goals

Guarantee: in a child that `run_pipeline_isolated` spawns with `mem_cap_bytes` and no explicit
`out_of_core_budget_bytes`, every DuckDB connection opened through `connect_duckdb` takes its
`memory_limit` from a budget of at most `cap - baseline - reserve`, where the baseline is the
child's own measured usage after the cap is set. When that remainder is under
`_MIN_BUDGET_BYTES`, the child returns outcome `oom_killed` with reason `process_out_of_memory`
before it loads sources or opens DuckDB; it never overcommits. Its thread count is
`max(1, min(usable CPUs, out_of_core_threads, memory_limit // 2 GiB))`. Arrow's CPU pool and
Polars' pool hold at most `child_pool_threads(...)` threads. Once the cap term is the smallest,
none of these counts grows with the host's core count.

Non-goals:
- An explicit `out_of_core_budget_bytes` (the governor's) is never changed, including its missing
  baseline subtraction. V2-LOG.
- `detect_effective_memory_bytes` does not learn about RLIMIT, so an operator who runs the CLI
  under `ulimit -v` keeps today's sizing. V2-LOG: it would change routing for every uncapped
  in-process run.
- The `connect_duckdb` fallback when host RAM detection fails (`memory_limit=None`, DuckDB default
  threads) is unchanged. With the computed budget the capped child does not reach it.
- `data_discovery`'s untrusted sessions and the Postgres session (`config.threads`) do not run in
  the capped child. Unchanged.
- Arrow's IO pool (a fixed 8 threads, not per core) is unchanged.

### 3.5 Placement

No new src file and no new file in the flat `tests/unit/execution/` directory:

| Tests | Existing file | Why there |
|---|---|---|
| Pure cells (AT-A4, AT-A5, AT-A10), payload and env spy (AT-A1, AT-A2, AT-A6, AT-A11) | `tests/unit/execution/test_isolated_run_env_flag.py` (85 lines at `2c869dce`) | it holds the spawn-env and thread-pool guard that these extend |
| Real-spawn out-of-core cells (AT-A3, AT-A8) | `tests/unit/execution/test_isolated_run.py`, new class `TestCappedChildSizing` beside `TestMemCapOom` (`:285`) | same real-spawn fixtures and `serial` marker |
| Probe verdict parity (AT-A9) | `tests/unit/execution/test_probe_routing.py` | it already drives `probe_peak_bytes` and the route verdict |

`_threads_for_memory_limit` cells (AT-A5) go in the existing `_duckdb.py` thread tests under
`tests/unit/execution/out_of_core/` if that file has them; the builder names the file in the PR.

### 3.6 Build step 0: thread census on the Dell, before any code

Run the b6b low-cap test and `TestMemCapOom` on the Dell through `~/bin/vm-run`. Poll the child
through `on_spawn` for `/proc/<pid>/task/*/comm` and `VmData` at peak, and record `VmData` right
after the cap is set (the baseline that item 1 subtracts). Record the thread groups by name (DuckDB,
Arrow, Polars, rayon, other) and the peak. Repeat after the build. If a thread group that grows with
cores remains and 3.3 does not cover it, stop and report. If the measured per-thread cost of the
Arrow and Polars pools is above 128 MiB, raise `CHILD_THREAD_RESERVE_BYTES` to the measured value
and note it in the PR.

### 3.7 Acceptance tests (write first)

- AT-A1 spy the worker's call into `run_pipeline` (a fake `run_pipeline` in a real spawned child is
  not possible, so this cell calls `_isolated_worker._run` in-process with a payload, an
  `apply_mem_cap` stub, and `read_vm_fields` patched to a fixed baseline of 500 MiB): with
  `mem_cap_bytes=768 MiB`, `pool_threads=1` and no budget in the kwargs, `run_pipeline` receives
  `out_of_core_budget_bytes == 768 - 500 - 128 MiB`. Fail-before on main (no budget key).
- AT-A2 an explicit `out_of_core_budget_bytes` in the payload kwargs reaches `run_pipeline`
  unchanged; no cap gives no budget key; `rlimit_kind="as"` reads `VmSize`, not `VmData`. The
  governor's existing budget tests (`tests/unit/execution/test_governor*.py`) stay green.
- AT-A3 real spawn, 768 MiB cap, `rlimit_kind="data"`, `execution_mode="out_of_core"`, a small
  two-table FK job. With `oc = result.quality_metrics["resources"]["out_of_core"]`: `oc["applied"]`
  is not empty; every entry has `threads == 1` and `memory_limit_bytes <= oc["memory_cap_bytes"]`;
  and `oc["memory_cap_bytes"] <= cap - CHILD_THREAD_RESERVE_BYTES * pool_threads - 200 MiB`. The
  200 MiB is a floor under the measured import baseline (about 500 MiB after #666), so the cell
  proves the baseline was subtracted: the sum of per-instance limits, which the resolver carves from
  `memory_cap_bytes`, stays under `cap - baseline`. Fail-before on main: `memory_cap_bytes` is
  `None` (no budget forwarded), so the memory clause fails on every host. The threads clause fails
  only where the host-derived limit reaches 4 GiB per instance; on an 8 GiB host it may already be
  1, so the fail-before proof rests on the memory clause.
- AT-A4 `child_pool_threads` cells: (768 MiB, 26) -> 1; (768 MiB, 64) -> 1; (2 GiB, 26) -> 4;
  (8 GiB, 26) -> 16; (8 GiB, 4) -> 4; (None, 64) -> 64; (64 MiB, 64) -> 1.
- AT-A5 `_threads_for_memory_limit` cells with `detect_usable_cpus` patched to 64: `"192MB"` -> 1,
  `"4096MB"` -> 2, `"192MB"` with cap 8 -> 1. This covers the 64-core case without a 64-core host.
- AT-A6 real spawn, 1 GiB cap. Expected `n = child_pool_threads(1 GiB, detect_usable_cpus())`,
  computed in the test, so the cell holds on any host. A probe in the spawned env (the same pattern
  as #666's guard) shows `POLARS_MAX_THREADS == str(n)`, and a worker-side check shows
  `pyarrow.cpu_count() == n` after setup. A second cell sets `POLARS_MAX_THREADS=64` in the parent
  with `monkeypatch.setenv` and still sees `str(n)` in the child (the driver's value wins over the
  parent's). An uncapped cell sees `detect_usable_cpus()`.
- AT-A7 (supporting evidence, regression only) #666's guard and S1's AT-C3 stay green (BLAS knobs
  still `"1"`).
- AT-A8 (supporting evidence: it may pass before the build on hosts where the host-derived limit
  stays under the cap) spill-forced out-of-core job under a 768 MiB data cap, modelled on
  `tests/perf/test_ooc_external_sort_memory.py`: a two-table FK job whose parent side is larger than
  the child's computed budget (a few hundred thousand rows of wide text), `execution_mode=
  "out_of_core"`. The run completes with the expected row count, and a sampler thread that polls
  the child's DuckDB temp directory through `on_spawn` sees a peak size above 0 (it spilled).
  Fail-before on main: the child is killed or fails as a memory failure on hosts where the
  host-derived limit lets DuckDB grow past the cap; on hosts where it completes, the cell still
  pins the behavior after the change.
- AT-A9 (supporting evidence, regression only: it passes before the build by construction)
  routing verdict parity: on a fixture that `test_probe_routing.py` already routes, call
  `probe_peak_bytes` and `resolve_execution_route` with the probe's capped child and record the
  verdict (`fits` and the chosen route) before the change (expected values written into the test
  from a run on main on the Dell) and after. The verdicts are equal. The peak itself may move; the
  test asserts the verdict, and the PR records both peaks.
- AT-A10 `child_ooc_budget` cells (cap, baseline, pool threads): (768 MiB, 500 MiB, 1) -> 140 MiB;
  (4 GiB, 500 MiB, 8) -> 2572 MiB; exact floor (692 MiB, 500 MiB, 1) -> 64 MiB, which equals
  `_MIN_BUDGET_BYTES`; just below the floor (692 MiB - 1, 500 MiB, 1) raises `MemoryError` with
  empty `args`; (768 MiB, 500 MiB, 6) and (600 MiB, 700 MiB, 1) raise `MemoryError`.
- AT-A11 in-process `_isolated_worker._run` with `apply_mem_cap` stubbed and `read_vm_fields`
  patched to a 700 MiB baseline, cap 768 MiB: the envelope has outcome `oom_killed` and reason
  code `process_out_of_memory`; spies show `_load_sources` and `run_pipeline` were never called;
  the error text contains neither size (`768`, `700`). Fail-before on main: `run_pipeline` is
  called.
- Host evidence (PR, not CI): the step-0 census before and after, the measured baseline, the b6b
  low-cap peak VmData on the Dell well under the 722 MiB seen on 2026-11-18, and the wall times in
  3.3.

### 3.8 Mutations

- M-A1 drop the baseline subtraction in `child_ooc_budget` (budget = cap minus reserve): AT-A10
  and AT-A1 red, and AT-A3's `memory_cap_bytes` clause red.
- M-A2 let the worker override an explicit budget: AT-A2 red.
- M-A3 `min` to `max` in `child_pool_threads`, drop its cap term, or drop the factor 4: AT-A4 red
  (the 768 MiB cell gives 6).
- M-A4 remove the worker's `set_cpu_count` call, or the `POLARS_MAX_THREADS` env entry: AT-A6 red.
- M-A5 read `VmData` for `rlimit_kind="as"`: the AT-A2 kind cell red.
- M-A6 compute the budget before `apply_mem_cap` or skip it when the kwargs are empty: AT-A1 red.
- M-A7 restore `max(remainder, _MIN_BUDGET_BYTES)` instead of raising: the below-floor cells of
  AT-A10 and AT-A11 red.
- M-A8 move the budget step outside the worker's `try`: AT-A11 red (the child crashes instead of
  returning a classified envelope).

### 3.9 Test scope

T0, T1. Named: `tests/unit/execution/test_isolated_run_env_flag.py`, `test_isolated_run.py`,
`test_b6b_modes.py`, `test_governor*.py`, every `tests/unit/execution/test_probe*.py`
(`test_probe.py`, `test_probe_routing.py`, `test_probe_scale.py`, `test_probe_fits_run_kills.py`,
`test_probe_peak_kills.py`, `test_probe_scale_kills.py`), the routing-signal tests
(`test_mem_estimate_routing_wiring.py`, `test_pipeline_routing_masktable_kills.py`,
`test_engine_transforms_admission.py`), the `_duckdb.py` thread tests under
`tests/unit/execution/out_of_core/`, `tests/sentry/test_module_size.py`,
`tests/sentry/test_physical_seam_disconnection.py`, plus every test file that imports
`_isolated_run`, `_isolated_worker` or `_isolated_common` (impact selection).
Full-suite triggers: none from the list. The change alters the kwargs of every directly capped
spawn and the pools of every isolated child, and the probe's result feeds routing, so the T2 gate
set includes the `serial`-marked isolated tests and the probe tests on the Dell. T3 at merge as
usual. Reviewers: Dennis, then Codex.

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

- A memory-capped child's allocator and thread env comes from one constant, `CAPPED_ENV`, and its
  RLIMIT_DATA or RLIMIT_AS cap from one function, `apply_mem_cap`.
- A capped child without an explicit budget hands DuckDB only what is left after its own measured
  baseline and its pools' reserve, and fails as a classified memory failure when that is under the
  floor.
- No thread pool in a capped child grows with the host core count once the cap is the smallest
  term.
- Every engine Postgres ATTACH carries a connect timeout below the session deadline (per
  attempted address), the user's DSN bytes are never changed, and no failure path carries DSN
  text.

### 5.2 Class table

| # | Class | Closing structure | Sentry or test | Mutation |
|---|---|---|---|---|
| 1 | Value-bearing output (DSN text in S2) | `attach_read_only` keeps the composed DSN local; coded error raised after the `except` closes | AT-B4 and AT-B7 leak cells over traceback, str, repr, caplog, cause and context | M-B4 raise inside the `except`, M-B7 put exception text in the message |
| 2 | Cleanup on exit paths | N/A: no slice adds a resource owner; S2 reuses `connected_session`, which closes the connection and cancels the deadline on every exit | existing `test_postgres_snapshot_unit.py` staged-file and close cells stay green | N/A, no new disposal code |
| 3 | State and concurrency (deadline timer vs connect timeout) | 2 s gap between the two timers; `raise_for_interrupt` checks the deadline flag first | AT-B1 clamp cells, AT-B3 timing | M-B2 remove the clamp |
| 4 | Route parity and silent fallback (capped child vs governed spawn; probe verdict) | the worker computes the budget only when none is explicit; the governor's explicit budget is untouched; the probe's verdict is pinned | AT-A1, AT-A2, AT-A3, AT-A9, AT-A10, AT-A11 | M-A1 drop the baseline subtraction, M-A2 override an explicit budget, M-A7 restore the floor `max()` |
| 5 | Referential integrity | N/A: no FK handling changes; AT-A3 uses an FK job only to open DuckDB connections | none needed | none |
| 6 | Untrusted producer (user DSN text into libpq) | `with_connect_timeout` only appends one keyword (with the `?`/`&` ending handled), never changes existing bytes, and never parses or echoes the DSN; libpq rejects malformed input | AT-B2 edge and prefix cells, AT-B3 user-value cell in both forms, AT-B7 rejection | M-B3 prepend instead of append, M-B5 rewrite a byte |
| 7 | Check then use on a path (TOCTOU) | N/A: no slice reads or opens a path by name | none needed | none |
| 8 | Weak tests and overclaimed evidence | fail-before proof per AT; AT-B3 bounded by a 15 s join so a hang fails instead of stalling; AT-A6 expected value computed on the host; Dell census and timings recorded with the head they ran on | AT-C1, AT-B3, AT-A1, AT-A3 red on main | M-C2, M-A3, M-B3 |
| 9 | Refactor drift (seven env copies, two RLIMIT setters, one budget floor) | one constant, one setter, one floor, imported, never copied | S1 sentry `test_one_capped_env.py` (constant, keyword, setrlimit and spawn-site rules) | M-C1 re-add a copy, M-C5 drop the computed-argument rule, M-C6 accept any env |
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

#### Callers that spawn a capped child

- `src/decoy_engine/execution/_probe.py:256` `run_isolated(..., mem_cap_bytes=...)`, reached from
  `src/decoy_engine/execution/_pipeline_routing_signals.py:491` and
  `src/decoy_engine/execution/_transforms_admission.py:286` (routing probe; verdict pinned by AT-A9).
- `src/decoy_engine/execution/_governor.py:336` explicit budget, unchanged.
- Direct `run_pipeline_isolated` callers (tests, `TestMemCapOom`, b6b): the fixed path.
- Scripts: `scripts/fk_memory_probe.py:1036`, `scripts/build_floor_probe.py:183`,
  `scripts/fk-scale/bench_worker_fk.py:215` (S1 moves their caps to `apply_mem_cap`).

#### FK shapes

N/A: no FK behavior changes in any slice. AT-A3 needs one single-column FK only to open
connections.

#### Fields

- `src/decoy_engine/connectors/postgres_snapshot.py:158` `threads` and `:161` `deadline_s` are read; no field is added.
- `src/decoy_engine/execution/out_of_core/_duckdb.py:37` `AppliedConnection` fields read by AT-A3.

#### Output surfaces

- Errors: `PostgresSnapshotError` message (code, location, cause type only).
- Logs: `postgres_snapshot failed code=%s location=%s`; no new log call in any slice.
- Run result: `quality_metrics["resources"]["out_of_core"]` `memory_cap_bytes` and `applied` (existing fields; values change under a cap).

### 5.4 Reuse inventory

- `CAPPED_ENV`, `apply_mem_cap`, `RLIMIT_KINDS` in `_isolated_common.py`.
- `read_vm_fields` in `_isolated_memwatch.py` for the child's baseline.
- `resolve_ooc_memory_limit` and `_MIN_BUDGET_BYTES` in `out_of_core/_budget.py`.
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
- S3: the child's computed budget changes routing for a directly capped test that relied on
  host-sized routing. That test moves to an explicit `out_of_core_budget_bytes`; the AT stays.
- S3: AT-A9 shows the probe verdict moving, because restored Arrow threads raise the probe child's
  peak. The builder stops and reports with both peaks; the fallback is to pass `pool_threads=1` from
  the probe until the route's price model is re-fit, an owner-visible change.
- S3: the measured import baseline differs between hosts (Mac vs Dell). AT-A3 uses a 200 MiB
  floor, not the 500 MiB figure, so it holds on both; the PR records each host's baseline.
- S1: a perf test's wall time grows past a timing assertion because Arrow runs single-threaded.
  Record it and report; do not widen the threshold. S3 restores the pool.
- S1: a test that gains `CAPPED_ENV` under rule 4 (sentinel, probe strategy, fk-scale infra)
  asserts on its child's env or memory and moves. Record it; the env change is the fix, so update
  the expectation only if it named the old allocator env, and say so in the PR.
- S2: AT-B3's join times out on a slow runner because the extension load is slow. The bound is
  15 s against a 6 s deadline; if it is still tight, load the extension in the fixture before the
  timed call, and never raise the bound past 30 s.
