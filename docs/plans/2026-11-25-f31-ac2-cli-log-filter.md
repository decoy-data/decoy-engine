# F31 AC2: SafeRecordFilter on every CLI log path

Status: plan

Rules consulted: README routing table, 00-universal, risk-and-exceptions, development-loop (PLAN,
proportion), cross-cutting-concerns (choke point, guard, seeded bypass), security, testing (test
depth), catalogs/recurring-defects, and the plan contract
(`30_Resources/Decoy-Plan-Contract-and-Defect-Catalog.md`).

Parent plan: `docs/plans/2026-11-24-f31-audit.md` (rev 3 on main; rev 2.2 behavior items 4 and
5, acceptance test 4 "red first for AC2", and the AC2 slice row, on `plan/f31-audit`). Row: CLI
`docs/roadmap/groups/health.md`, F31-AUDIT.

Risk: R1. About 80 changed lines plus one sentry. No output text changes on a clean run; a
logged exception prints its type label instead of its text. One reviewer (Codex). No full-suite
trigger: no shared fixture, lock or frozen contract moves.

Bases: CLI main `d6b9e4c7`. Engine name from the AC0 pin: `SafeRecordFilter`
(`decoy_engine.safe_output`, AE3).

## Defect class

A CLI log record carries an exception or a value in `msg`, `args` or `exc_info`, and a handler
prints it. The engine attaches `SafeRecordFilter` to its own handlers (AE3). The CLI's own
handlers and loggers do not have it: the detector handler `_ErrConsoleHandler`
(`ui/output.py:275`) prints `record.getMessage()`, and the notify logger (`notify.py:62`) has no
handler, so its warnings reach stderr through the stdlib `logging.lastResort` handler.

## Guarantee and non-goals

Guarantee:

1. Every handler the CLI attaches is built by one function, `safe_handler(handler)`, which adds
   `SafeRecordFilter` once.
2. Every CLI-owned logger that may log without a CLI handler (and so reach `lastResort`) is
   made by `safe_logger(name)`, which adds `SafeRecordFilter` to the logger. A logger filter
   runs for records created on that logger, before any handler, `lastResort` included.
3. A webhook password never appears in a notify warning, `target_host`, stdout, stderr or the
   `--json` document. Today `_host_only` (`notify.py:456`) already drops userinfo (CL4); AC2
   adds the guard that keeps it so.

Non-goals: the sanctioned raw sink `--unsafe-debug-log` (`ci/debug.py`, `cli/ci.py:137`), which
is unsafe by name and opt-in; the engine's own handlers (AE3); interpolated text built before
the log call (`log.info(f"x {exc}")`), a documented gap guarded by the engine's interpolation
test and AC3's literal sentry; error sinks (AC1).

## Established solutions

Search run: Python logging cookbook (filters on handlers and loggers), the stdlib rule that a
logger filter applies only to records created on that logger and a handler filter to every
record the handler sees, OpenSSF secure-coding guide pyscg-0019 (sanitize with
`logging.Filter`), OWASP Logging Cheat Sheet (sanitize at the logging layer, not per call),
Django ticket 23951 (a filter on the admin email handler to strip sensitive data). The design
uses the stdlib filter the engine already ships. Nothing new is built.

## Choke point

`src/decoy/_safe_logging.py`, two functions:

- `safe_handler(h: logging.Handler) -> logging.Handler` adds one `SafeRecordFilter` when `h` has
  none, and returns `h`.
- `safe_logger(name: str) -> logging.Logger` returns `logging.getLogger(name)` with one
  `SafeRecordFilter` on the logger.

Guard: `tests/sentry/io_policy/test_log_handlers_filtered.py`, two halves.

- Static: an AST walk of `src/decoy` finds every `.addHandler(` call and every
  `logging.getLogger(` call. An `addHandler` argument must be a direct `safe_handler(...)` call.
  A `getLogger` call is allowed only inside `_safe_logging.py`. Keys are exact
  `(path, function)`; there is no allow list.
- Runtime: after importing every module under `decoy` (the `pkgutil.walk_packages` list, not a
  hand list), every logger in `logging.root.manager.loggerDict` whose name starts with `decoy.`
  carries a `SafeRecordFilter`, and so does every handler on such a logger.

Self-test: a scratch tree with a bare `addHandler(StreamHandler())` and a bare `getLogger` is
flagged; a scratch logger created without `safe_logger` fails the runtime half.

## Class table

| # | Class | Applies | Structure that closes it | Proof | Mutation |
|---|---|---|---|---|---|
| 1 | value-bearing output | yes: the defect class | `safe_handler` and `safe_logger` are the only ways to attach a handler or make a CLI logger | AT-1, AT-2, AT-3 | M1: drop `addFilter` in `safe_handler` |
| 2 | cleanup on an exit path | yes, narrow: `detector_log` removes its handler in `finally` | the filtered handler is removed the same way; the filter holds no resource | AT-2 checks the logger's handler list after the context exits | N/A: no new cleanup |
| 3 | state and concurrency | yes: loggers are process-global | `safe_handler` and `safe_logger` are idempotent (one filter, checked by type) | AT-4 (two calls add one filter) | M2: add a filter on every call |
| 4 | route parity and fallback | yes: handler route, `lastResort` route, `-v` detector route | logger-level filter covers `lastResort`; handler filter covers the detector console | AT-1 (`lastResort`), AT-2 (detector) | M3: filter only the handler, not the notify logger |
| 5 | referential integrity | N/A: no table data | | | |
| 6 | untrusted producer | yes: exception text in `args` and `exc_info` | the engine filter rewrites exceptions to labels before any formatter | AT-1, AT-2 with the canary | M1 |
| 7 | check then use on a path | N/A: no path is checked or opened | | | |
| 8 | weak tests and overclaimed evidence | yes: the password case is green on main | red-first by mutation (M4), stated as such | AT-3 | M4: `_host_only` returns `netloc` |
| 9 | refactor drift | N/A: no refactor; `getLogger` at `notify.py:62` becomes `safe_logger` with the same name | | | |
| 10 | frozen contract drift | yes: `target_host` in the `--json` `notify` entry | value kept as `host:port` (open item 1) | `tests/e2e/test_notify_live_webhook.py:152` unchanged | |

## Enumerations

Read from CLI `d6b9e4c7`.

### Exit paths

- Notify delivery failure: warning, run exit unchanged (`notify.py:283`, `:289`, `:297`,
  `:300`), result `delivered=false` (`notify.py:448`).
- Notify channel crash: `notify.py:445`, run exit unchanged.
- Detector context exit: `ui/output.py:298` removes the handler in `finally`.

### Routes

- Handler on a CLI logger: `ui/output.py:296` (`_ErrConsoleHandler` on
  `decoy_engine.detectors`).
- `lastResort`: the notify logger `notify.py:62` has no handler.
- NullHandlers that write nothing: `ci/engine_logging.py:38`, `telemetry.py:143`. They are
  wrapped so the guard has no exception.
- Re-attached handlers: `ci/engine_logging.py:45` restores the handlers that were on the engine
  logger before; those are engine handlers (filtered by AE3) or host handlers. They are wrapped
  too, which is a no-op for an already filtered handler.

### FK shapes

N/A: no table data.

### Fields

- `LogRecord.msg`, `LogRecord.args`, `LogRecord.exc_info`, `LogRecord.exc_text` (rewritten by
  the engine filter).
- `NotifyResult.target_host` (`notify.py:448`) and the host in every notify warning, both from
  `_host_only` (`notify.py:456`).

### Output surfaces

- stderr under `-v` (detector lines).
- stderr through `lastResort` (notify warnings at WARNING and above).
- the `--json` `notify` entry (`target_host`).

## Reuse inventory

- Engine `SafeRecordFilter` (AE3) and its documented gaps.
- `_host_only` and `_redact_email` (`notify.py:456`, `:472`), kept.
- `tests/sentry/test_notify_redaction.py` (extended), `tests/e2e/test_notify_live_webhook.py`
  (its local HTTP server pattern, reused for AT-3).
- The AST walk style of `tests/sentry/io_policy/test_environment_reads.py`.

## Frozen contracts touched

`target_host` in the `--json` `notify` entry: unchanged (`host:port`). No exit code, key or
command changes.

## Behavior changes

1. A notify warning that logs an exception object prints its type label. Today's notify warnings
   already pass `type(exc).__name__` or a code, so their text is unchanged.
2. A detector record under `-v` that carries an exception prints its label. Detector records
   hold ids and counts today, so their text is unchanged.

## Acceptance tests

| Id | Test | Red-first or mutation |
|---|---|---|
| AT-1 | `tests/unit/test_safe_logging.py` (new): log `logger.warning("x %s", exc)` on the notify logger with the canary `DECOY_CANARY_F31_7Q4Z` in `exc`, no handlers configured; capture `lastResort` output; assert the label and no canary; also with `exc_info=True` | red on main (no filter on the notify logger). M1, M3 |
| AT-2 | same file: inside `detector_log(state, on=True)`, a detector record with the canary in `args` and in `exc_info`; assert stderr has the label and no canary; after exit the handler is gone | red on main. M1 |
| AT-3 | `tests/sentry/test_notify_redaction.py` (extend): a failing webhook run whose URL is `http://user:DECOY_CANARY_F31_7Q4Z@127.0.0.1:<port>/hook`; the test server returns HTTP 400; assert the canary is absent from stdout, stderr, the whole `--json` document, the POST body and the warning log; `delivered == false`; `target_host == "127.0.0.1:<port>"`; the run's exit code is unchanged | green on main (CL4); red by M4 |
| AT-4 | same unit file: `safe_handler` twice on one handler and `safe_logger` twice on one name leave exactly one `SafeRecordFilter` | M2 |
| AT-5 | `tests/sentry/io_policy/test_log_handlers_filtered.py` (new): the guard and its self-test | M5: delete one `safe_handler(...)` wrapper; M6: restore `logging.getLogger(__name__)` in `notify.py` |

Mutations M1 to M6 run on the final head; the PR body records that head.

## Mutations

| Id | Mutation | Killed by |
|---|---|---|
| M1 | drop `addFilter` in `safe_handler` and `safe_logger` | AT-1, AT-2 |
| M2 | add a filter on every call | AT-4 |
| M3 | filter the detector handler only; plain `getLogger` for notify | AT-1, AT-5 runtime |
| M4 | `_host_only` returns `parts.netloc` | AT-3 |
| M5 | unwrap one `addHandler` argument | AT-5 static |
| M6 | restore `logging.getLogger(__name__)` in `notify.py` | AT-5 static and runtime |

## Failure modes

| Failure | Detected by |
|---|---|
| A new module adds a bare handler | AT-5 static |
| A new module makes a logger with `getLogger` and logs an exception | AT-5 static (no `getLogger` outside `_safe_logging.py`) and runtime |
| A child logger (`decoy.notify.x`) logs without its own filter | runtime half: every `decoy.` logger must carry one |
| The engine filter raises | AE3 contract: the filter falls back to labels and never raises; the CLI adds no code in the path |
| Interpolated text before the call (`f"{exc}"`) | out of scope; AC3 literal sentry and the engine interpolation test |
| A host configures `basicConfig` around an embedded CLI call | records on `decoy.` loggers still pass the logger filter first; root handlers see the rewritten record |

## Design notes

1. A logger filter is the only stdlib place that covers `lastResort`, because `lastResort` is a
   module global the CLI must not change. A logger filter does not run for records that
   propagate from child loggers, so the runtime half checks every `decoy.` logger.
2. `ci/engine_logging.py:45` re-adds earlier handlers. Wrapping them adds a filter to a handler
   the CLI did not create. The filter only rewrites exception text, so a host handler loses
   nothing it may legally print. Recorded for the reviewer.

## Placement

| New file | Directory | CODEMAP line | Sits beside |
|---|---|---|---|
| `_safe_logging.py` | CLI `src/decoy/` | "Private shared filesystem or process primitives used by more than one package: `src/decoy/_<noun>.py`" | `_env_flags.py` |
| `test_safe_logging.py` | CLI `tests/unit/` | same row: `tests/unit/test_<noun>.py` | `test_env_flags.py` |
| `test_log_handlers_filtered.py` | CLI `tests/sentry/io_policy/` | same row, sentry column: `tests/sentry/io_policy/test_environment_reads.py` | `test_environment_reads.py` |

Each new sentry is registered in `tests/sentry/test_sentry_manifest.py` (`SENTRIES`) and `scripts/dev/sentry_registry.toml`.

`src/decoy/` holds 20 modules; with AC1's two, 23, under the 25 cap.

## Size

About 80 changed source lines in five files (`_safe_logging.py`, `ui/output.py`,
`ci/engine_logging.py`, `telemetry.py`, `notify.py`), about 200 test lines.

## Slices

One slice, R1. Depends on AC0 (pin with `SafeRecordFilter`). It edits `ui/output.py` lines
`:285` to `:302`, which AC1a also edits (lines `:217` to `:256`); whichever merges second
rebases. It does not depend on AC1.

## Test depth

T0 on the touched test files per edit; T1 impact selection per commit; T2 gate on the head: T1
plus AT-1 to AT-5 and M1 to M6. No full-suite trigger. Tests run on the gate nodes, never the
devbox.

## Recurring defect checks (dev-rules catalog)

| Id | Class | Applies | Check |
|---|---|---|---|
| D1 | anchored validation | no | no regex |
| D2 | strict types | yes | `safe_handler` and `safe_logger` typed; mypy on the new module |
| D3 | exception context | no | no new raise |
| D4 | versioned read models | no | |
| D5 | normalized scanners | yes | the static half lists its shapes (`x.addHandler(...)`, `logging.getLogger(...)`, `getLogger` imported by name) and its known limit (an aliased `addHandler` bound method) |
| D6 | private-module imports | yes | imports only `decoy_engine.safe_output.SafeRecordFilter` |
| D7 | hidden CI failures | yes | no skip or `xfail` added; the guard is in the default sentry run |
| D8 | one trust class per entry | yes | one rule: every CLI handler and logger carries the filter |
| D9 | mutations on final head | yes | M1 to M6 on the final head, recorded |
| D10 | allowlisted helpers | yes | `_safe_logging.py` is the one exempt module, keyed by exact path |
| D11 | no raised caps | yes | no baseline or cap moves |

## Pre-mortem

1. The runtime half imports every module and one import has side effects: it imports through
   `pkgutil.walk_packages` with `onerror` failing the test, the same as the existing import
   surface sentry.
2. A builder satisfies AT-5 by wrapping a handler at a site that never logs exceptions and
   leaves the notify logger plain: AT-1 catches the notify route.
3. The owner chooses the bare hostname: one change in `_host_only` and one assert in
   `test_notify_live_webhook.py:152`; AT-3 changes its expected `target_host`.

## Docs and changelog

CLI `CHANGELOG.md`: logged exceptions print type labels. CODEMAP row for `_safe_logging.py` and
the guard.

## Open items

1. Audit rev 2.2 asks for the bare hostname (`urlsplit(url).hostname`) and a change at
   `tests/e2e/test_notify_live_webhook.py:152`. CL4 (#406) already removed userinfo and chose
   `host:port`; its AT-2 expects `hooks.example.com:8443`. The port is not a secret. Recommended:
   keep `host:port`. Owner call.
2. Wrapping re-attached host handlers in `ci/engine_logging.py:45` (design note 2).

## Unverified

- Whether any `decoy.` logger besides `decoy.notify` exists after import; the runtime half
  lists them on its first run.

## V2-LOG

None.
