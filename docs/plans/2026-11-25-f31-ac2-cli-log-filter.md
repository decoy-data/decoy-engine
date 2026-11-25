# F31 AC2: SafeRecordFilter on every CLI log path

Status: plan

Rules consulted: README routing table, 00-universal, risk-and-exceptions, development-loop (PLAN,
proportion), cross-cutting-concerns (choke point, guard, seeded bypass), security, testing (test
depth), catalogs/recurring-defects, and the plan contract
(`30_Resources/Decoy-Plan-Contract-and-Defect-Catalog.md`).

Parent plan: `docs/plans/2026-11-24-f31-audit.md` (rev 3 on main; rev 2.2 behavior items 4 and
5, acceptance test 4 "red first for AC2", the bare-hostname contract at `:601` to `:610`, and
the AC2 slice row, on `plan/f31-audit`). Row: CLI `docs/roadmap/groups/health.md`, F31-AUDIT.

Risk: R2. It is a privacy boundary on every CLI log path, it changes the `target_host` value of
the notify result, and it fixes the webhook 4xx route. About 120 changed source lines plus one
sentry. Two reviewers (Dennis, then Codex) and a T2 gate on the exact head. The test-depth
decision on `target_host` is in "Test depth".

Bases: CLI main `d6b9e4c7`. Engine name from the AC0 pin: `SafeRecordFilter`
(`decoy_engine.safe_output`, AE3).

## Defect class

A CLI log record carries an exception or a value in `msg`, `args` or `exc_info`, and a handler
prints it. The engine attaches `SafeRecordFilter` to its own handlers (AE3). The CLI's own
handlers and loggers do not have it: the detector handler `_ErrConsoleHandler`
(`ui/output.py:275`) prints `record.getMessage()` (`:280` to `:281`), and the notify logger
(`notify.py:62`) has no handler, so its warnings reach stderr through the stdlib
`logging.lastResort` handler. Separately, `_host_only` (`notify.py:456`) shows `host:port`, and
the parent contract asks for the bare hostname.

## Guarantee and non-goals

Guarantee:

1. Every handler the CLI creates and attaches is built by one function, `safe_handler(handler)`,
   which adds one deferred `SafeRecordFilter` (Choke point).
2. Every CLI-owned logger (`decoy` and `decoy.*`) is made by `safe_logger(name)`, which adds
   the deferred `SafeRecordFilter` to the logger. A logger filter runs for records created on that logger,
   before any handler, `lastResort` included.
3. The CLI never adds a filter to a handler it did not create. `ci/engine_logging.py:44` to `:47`
   restores the caller's exact handler objects, unchanged, so a host handler keeps its own
   filters and formatting after the CLI returns.
4. The notify warning and `target_host` show the bare hostname (`urlsplit(url).hostname`, IPv6
   in brackets), never userinfo, port, path or query.

Non-goals: the sanctioned raw sink `--unsafe-debug-log` (`ci/debug.py`, `cli/ci.py:137`), which
is unsafe by name and opt-in; the engine's own handlers (AE3); error sinks (AC1). Text built
before the log call (`log.info(f"x {exc}")`) is not covered by a filter. AE3's interpolation
sentry scans only `src/decoy_engine` (`test_log_interpolation.py:28`), and the parent's AC3
literal sentry (`:400` to `:404`) looks at `SafeText` calls, so neither covers it. AC2 owns the
CLI check: rule 3 of the guard below. A scan of CLI `src/` on `d6b9e4c7` finds no logging call
with a built first argument, so the check starts at zero with no baseline.

## Established solutions

Search run: Python logging cookbook (filters on handlers and loggers), the stdlib rule that a
logger filter applies only to records created on that logger and a handler filter to every
record the handler sees, OpenSSF secure-coding guide pyscg-0019 (sanitize with
`logging.Filter`), OWASP Logging Cheat Sheet (sanitize at the logging layer, not per call),
Django ticket 23951 (a filter on the admin email handler to strip sensitive data). The design
uses the stdlib filter the engine already ships. Nothing new is built.

## Choke point

`src/decoy/_safe_logging.py`, two functions and one private filter class:

- `_DeferredSafeFilter(logging.Filter)` imports `decoy_engine.safe_output.SafeRecordFilter` on
  its first `filter()` call and delegates to one instance of it. `src/decoy/__main__.py:51`
  imports `ui/output.py` on every start, and `notify.py:62` makes its logger at import, so an
  eager import would load the engine during CLI startup, before `decoy ci` sets its logging
  policy. The deferred class keeps the startup contract.
- `safe_handler(h: logging.Handler) -> logging.Handler` adds one `_DeferredSafeFilter` when `h`
  has none, and returns `h`. Only for handlers the CLI constructs.
- `safe_logger(name: str) -> logging.Logger` returns `logging.getLogger(name)` with one
  `_DeferredSafeFilter` on the logger. It refuses a name outside `decoy` and `decoy.*`.

Layer map: the module joins the exhaustive CLI layer contract in `.importlinter:21` to `:32`
and its snapshot in `tests/sentry/layout/test_import_layers.py:44`, in a tier below tier 6, so
`notify` and `ui` can both import it and the `notify` relocation test at `:340` still passes.
`lint-imports` runs with no new exception.

Guard: `tests/sentry/io_policy/log_handlers/test_log_handlers_filtered.py`, static. It reuses
the call resolver in `tests/sentry/io_policy/_calls.py` (`:59`, `:71`, `:141`) for qualified
imports, aliases and method names, so there is one call scanner.

1. Every `.addHandler(...)` call: the argument is a direct call whose resolved target is
   exactly `decoy._safe_logging.safe_handler`, or the call is the restoration loop. The
   restoration exemption is structural, not keyed by function: the `addHandler` call sits in a
   `for` loop inside a `finally` block (the scanner's ancestor data), and its argument is that
   loop's target name, iterating over the name saved before the `try`. The `NullHandler` at
   `ci/engine_logging.py:38` is in the same function and gets no exemption.
2. Every `logging.getLogger(...)` call, under any alias or `from logging import getLogger`: a
   CLI-owned name (`__name__`, or a literal `decoy` or `decoy.*`) is allowed only inside
   `_safe_logging.py`. A lookup of an external logger (`decoy_engine.*`) is allowed.
3. Every logging method call (`debug`, `info`, `warning`, `error`, `exception`, `critical`,
   `log`) on a logger: the message argument is a string literal. An f-string, `%`, `+`,
   `.format()` or `str()` call is flagged, because text built before the call bypasses the
   filter. Values go in `args`, where the filter rewrites them. Each format operand in `args` is
   checked too, because a pre-rendered string in `args` reaches the output as text the filter
   cannot tell from a safe one. An operand is allowed only if it is a name bound by
   `except ... as`, a `_host_only(...)` call, a numeric literal, or the HTTP status attribute
   (`.status` on the response, `.code` on an `HTTPError`). Anything else is flagged, for example
   `str(exc)`, `exc.args[0]`, `exc.reason` or a raw URL name.
4. Every module-level logging call (`logging.debug`, `info`, `warning`, `error`, `exception`,
   `critical`, `log`) and every `logging.basicConfig` call is flagged, under any alias
   (`import logging as lg`, `from logging import warning`). These log through the root logger
   without the filter, and `basicConfig` adds an unfiltered root handler.

Self-test: a scratch tree with a bare `addHandler(StreamHandler())`, an aliased
`from logging import getLogger as gl; gl(__name__)`, an unbound `logging.Logger.addHandler(lg,
h)`, a lookalike `safe_handler` defined in the scratch module, an unwrapped handler next to a
restoration loop in the same function, `logger.warning(f"{exc}")`,
`logger.warning("x %s", str(exc))`, `logger.warning("x %s", exc.args[0])`,
`logger.warning("x %s", url)`, `logging.warning("x")`, `from logging import warning as w;
w("x")` and `logging.basicConfig()`; each is flagged. `logger.warning("x %s", exc)` (with `exc`
bound by `except ... as`) and `logger.warning("x %s", _host_only(url))` are not.

The runtime proof is per route, not an import census: AT-1 (`lastResort`), AT-2 (detector
handler), AT-6 (restoration).

## Class table

| # | Class | Applies | Structure that closes it | Proof | Mutation |
|---|---|---|---|---|---|
| 1 | value-bearing output | yes: the defect class | `safe_handler` and `safe_logger` are the only ways to attach a CLI handler or make a CLI logger; guard rule 3 keeps values in `args` | AT-1, AT-2, AT-3, AT-5 | M1: drop `addFilter` in `safe_handler`; M3: drop it in `safe_logger`; M8: add `logger.warning(f"{exc}")` in `notify.py` |
| 2 | cleanup on an exit path | yes: `detector_log` removes its handler in `finally`; `engine_logging` restores handlers in `finally` | the filtered handler is removed the same way; restoration re-adds the exact saved objects | AT-2 checks the handler list after exit; AT-6 | M6: wrap the restored handlers |
| 3 | state and concurrency | yes: loggers are process-global | `safe_handler` and `safe_logger` are idempotent (one filter, checked by type); the CLI does not touch shared handlers | AT-4, AT-6 | M2: add a filter on every call |
| 4 | route parity and fallback | yes: handler route, `lastResort` route, `-v` detector route; webhook 4xx as a response and as `HTTPError` | logger filter covers `lastResort`; handler filter covers the detector console for any child logger; one status branch for both 4xx forms | AT-1, AT-2, AT-3 | M3, M1, M9 |
| 5 | referential integrity | N/A: no table data | | | |
| 6 | untrusted producer | yes: exception text in `args` and `exc_info`; a webhook URL with userinfo | the engine filter rewrites exceptions to labels before any formatter; `_host_only` returns the hostname only | AT-1, AT-2, AT-3 with the canary | M1, M4 |
| 7 | check then use on a path | N/A: no path is checked or opened | | | |
| 8 | weak tests and overclaimed evidence | yes: a logger filter on the originating logger can hide a missing handler filter; pytest's root capture handlers can hide `lastResort` | AT-2 logs from a detector child logger with no logger filter; AT-1 removes pytest's root handlers for the case | AT-1, AT-2 | M1 must fail AT-2 alone |
| 9 | refactor drift | N/A: `getLogger` at `notify.py:62` becomes `safe_logger` with the same name | | | |
| 10 | frozen contract drift | yes, value only: `target_host` in the `--json` `notify` entry | key unchanged; value becomes the hostname per the parent contract; CHANGELOG entry | AT-3; `test_notify_live_webhook.py:152` and `test_run_notify_cl4.py:62` to `:75` updated | M4 |

## Enumerations

Read from CLI `d6b9e4c7`.

### Exit paths

- Notify delivery failure: warning, run exit unchanged (`notify.py:283`, `:289`, `:297`,
  `:300`), result `delivered=false` (`notify.py:448`). A real 4xx arrives as
  `urllib.error.HTTPError` from the opener (`_outbound.py:129`), not as a response object, and
  `notify.py:299` catches it as `URLError`: it reports "unreachable" and retries. AC2 adds an
  `HTTPError` branch before `:299` that sends `exc.code` through the same status rule as a
  response (4xx: one warning, no retry; 5xx: retry).
- Notify channel crash: `notify.py:445`, run exit unchanged.
- Detector context exit: `ui/output.py:298` removes the handler in `finally`.
- Engine logging context exit: `ci/engine_logging.py:44` to `:47` removes all handlers and
  re-adds the saved ones.

### Routes

- Handler the CLI creates: `ui/output.py:296` (`_ErrConsoleHandler` on
  `decoy_engine.detectors`); records from child loggers propagate to it.
- `lastResort`: the notify logger `notify.py:62` has no handler.
- NullHandlers the CLI creates: `ci/engine_logging.py:38`, `telemetry.py:143`. They write
  nothing; they go through `safe_handler` so the guard has no exception.
- Restored handlers: `ci/engine_logging.py:45`, the caller's own objects, re-added unchanged.
- Outbound POST: `_outbound.open_url` (`_outbound.py:145` to `:155`).

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
- the run result and library run record files the run writes.

## Reuse inventory

- Engine `SafeRecordFilter` (AE3) and its documented gaps.
- `_host_only` and `_redact_email` (`notify.py:456`, `:472`).
- The parent plan's test transport at `_outbound.open_url`.
- `tests/sentry/io_policy/_calls.py` for the guard.
- `tests/sentry/test_notify_redaction.py` (extended), `tests/e2e/test_notify_live_webhook.py`,
  `tests/e2e/test_run_notify_cl4.py`.
- The sentry manifest's discovery (`tests/sentry/test_sentry_manifest.py:40`).

## Frozen contracts touched

`target_host` in the `--json` `notify` entry: key and type unchanged; the value drops the port,
as the parent contract requires. No exit code, key or command changes.

## Behavior changes

1. A notify warning that logs an exception object prints its type label. Today's notify warnings
   already pass `type(exc).__name__` or a code, so their text is unchanged.
2. A detector record under `-v` that carries an exception prints its label. Detector records
   hold ids and counts today, so their text is unchanged.
3. `target_host` and the notify warning host read `hooks.example.com`, not
   `hooks.example.com:8443`. An IPv6 host reads `[::1]`. A bad port still gives the hostname,
   because only `parts.port` raises.
4. A host that embeds the CLI keeps its handlers' filters and output exactly as before the call.
5. A webhook that answers 4xx is posted once and warned about as
   `webhook <host> returned HTTP <code> (4xx, not retrying)`; today it is retried and reported as
   unreachable. A 5xx `HTTPError` keeps the retry.

## Acceptance tests

| Id | Test | Red-first or mutation |
|---|---|---|
| AT-1 | `tests/unit/safe_logging/test_safe_logging.py` (new): with pytest's root capture handlers removed for the case so `lastResort` runs, log `logger.warning("x %s", exc)` on the notify logger with the canary `DECOY_CANARY_F31_7Q4Z` in `exc`; and, inside an active `except`, `logger.warning("x", exc_info=True)`; capture stderr; assert the label and no canary | red on main (no filter on the notify logger). M3 |
| AT-2 | same file: inside `detector_log(state, on=True)`, a record from `decoy_engine.detectors.child` (a child with no logger filter) with `"%s"` and a canary-bearing exception in `args`; assert stderr has the label and no canary; after exit the handler is gone | red on main. M1 alone must fail it |
| AT-3 | `tests/sentry/test_notify_redaction.py` (extend): a failing job with webhook URL `http://user:DECOY_CANARY_F31_7Q4Z@hooks.example.com:8443/hook`, with pytest's root handlers removed so the warning goes through `lastResort` to stderr. Two transport cases at `_outbound.open_url`: (a) it returns a 400 response object; (b) it raises `urllib.error.HTTPError(url, 400, ...)`, as the real opener does. In both, assert exactly one POST, stderr contains the complete prefix `webhook hooks.example.com returned HTTP 400`, `delivered == false`, the job's original exit code, `target_host == "hooks.example.com"`, and canary absence from stdout, stderr, the whole `--json` document, the POST body and every file the run writes. Case (c): the first call raises `HTTPError(url, 503, ...)` and the second returns 200; assert exactly two POSTs and `delivered == true`, so a branch that treats every `HTTPError` as permanent fails | red on main for `target_host` and for case (b). M4, M4b, M9, M11 |
| AT-4 | same unit file: `safe_handler` twice on one handler and `safe_logger` twice on one name leave exactly one `_DeferredSafeFilter`; `safe_logger("other")` raises | M2 |
| AT-5 | `tests/sentry/io_policy/log_handlers/test_log_handlers_filtered.py` (new): the guard and its self-test (bare, aliased, unbound, lookalike, unwrapped-beside-restoration and f-string cases); on the real tree nothing is flagged | M5: unwrap `safe_handler(...)` around the `NullHandler` at `ci/engine_logging.py:38`; the guard fails while the restoration loop at `:45` still passes. M7, M8, M12, M13 |
| AT-6 | `tests/unit/safe_logging/test_engine_logging_restore.py` (new): a host handler with its own filter and formatter is on the engine logger; run the `engine_logging` context; afterwards the logger holds the same handler object, its filter list is unchanged, and a later exception record formats exactly as before the context | M6 |
| AT-7 | `tests/e2e/test_notify_live_webhook.py:152` and `tests/e2e/test_run_notify_cl4.py:62` to `:75` (credential, IPv6, bad-port cases) updated to the hostname | red on main |
| AT-8 | `tests/unit/safe_logging/test_safe_logging.py`: in a fresh `python -I` process (which ignores `PYTHONPATH`), the child first inserts the reviewed checkout's `src` at the front of `sys.path`, passed in by the parent from the test file's own location, then imports `decoy.__main__` and `decoy.notify`, asserts `decoy.__file__` resolves inside that `src`, and asserts `decoy_engine` is not in `sys.modules`. Plus the existing fresh-process regression `tests/unit/test_ci_rule_codes.py:416` | M10: import `SafeRecordFilter` at module scope in `_safe_logging.py` |

Mutations M1 to M13 and M4b run on the final head; the PR body records that head.

## Mutations

| Id | Mutation | Killed by |
|---|---|---|
| M1 | drop `addFilter` in `safe_handler` | AT-2 |
| M2 | add a filter on every call | AT-4 |
| M3 | drop `addFilter` in `safe_logger`, or plain `getLogger` for notify | AT-1 |
| M4 | `_host_only` returns `host:port` again | AT-3, AT-7 |
| M5 | unwrap one `addHandler` argument | AT-5 |
| M6 | pass the restored handlers through `safe_handler` | AT-6 |
| M7 | restore `logging.getLogger(__name__)` in `notify.py` | AT-5, AT-1 |
| M4b | change only the warning's host argument back to `host:port`; `target_host` stays correct | AT-3 stderr prefix |
| M8 | add `logger.warning(f"{exc}")` in `notify.py` | AT-5 rule 3 |
| M9 | remove the `HTTPError` branch, so a 400 falls to the `URLError` branch | AT-3 case (b): three attempts instead of one POST, no 4xx prefix |
| M10 | import `SafeRecordFilter` at module scope in `_safe_logging.py` | AT-8 |
| M11 | make the `HTTPError` branch return a permanent failure for every status | AT-3 case (c): one POST, `delivered == false` |
| M12 | change one `notify.py` warning operand to `str(exc)` | AT-5 rule 3 operand check |
| M13 | add `logging.warning("x")` at module scope in a CLI file | AT-5 rule 4 |

## Failure modes

| Failure | Detected by |
|---|---|
| A new module adds a bare handler | AT-5 |
| A new module makes a CLI logger with `getLogger` and logs an exception | AT-5 (no CLI-owned `getLogger` outside `_safe_logging.py`, aliases resolved) |
| A child CLI logger (`decoy.notify.x`) logs without a filter | `safe_logger` is the only maker; the guard flags the child's `getLogger` |
| The engine filter raises | AE3 contract: the filter falls back to labels and never raises; the CLI adds no code in the path |
| Interpolated text before the call (`f"{exc}"`) | AT-5 guard rule 3, M8 |
| The filter import loads the engine at CLI startup | `_DeferredSafeFilter`; AT-8, M10 |
| A real 4xx is retried and reported as unreachable | the `HTTPError` branch; AT-3 case (b), M9 |
| The CLI changes a host's handler | AT-6 |

## Design notes

1. A logger filter is the only stdlib place that covers `lastResort`, because `lastResort` is a
   module global the CLI must not change. A logger filter does not run for records that
   propagate from child loggers, so each CLI logger is made by `safe_logger`, and the detector
   handler carries its own filter for engine child loggers.
2. AE3's filter rewrites records in place. A filter on a shared host handler would change what
   that handler prints for unrelated loggers later, so the CLI filters only what it creates.

## Placement

| New file | Directory | CODEMAP line | Sits beside |
|---|---|---|---|
| `_safe_logging.py` | CLI `src/decoy/` | `CODEMAP.md:69`: "Private shared filesystem or process primitives used by more than one package: `src/decoy/_<noun>.py`" | `_env_flags.py` |
| `test_safe_logging.py`, `test_engine_logging_restore.py` | CLI `tests/unit/safe_logging/` (new package; `tests/unit/` has 58 direct files) | tests in `tests/unit/` packages | `tests/unit/run_progress/` |
| `test_log_handlers_filtered.py` | CLI `tests/sentry/io_policy/log_handlers/` (new package; `io_policy/` has 32 direct files) | sentry subpackages of `io_policy/` | `tests/sentry/io_policy/outbound/` |

The sentry manifest discovers the new sentry (`tests/sentry/test_sentry_manifest.py:40`); the
guard has no baseline, so `scripts/dev/sentry_registry.toml` needs no entry.

`src/decoy/` holds 20 modules; with AC1's two, 23, under the 25 cap. The module is added to
`.importlinter:21` to `:32` and the snapshot at `tests/sentry/layout/test_import_layers.py:44`
(Choke point).

## Size

About 120 changed source lines in six files (`_safe_logging.py`, `ui/output.py`,
`ci/engine_logging.py`, `telemetry.py`, `notify.py`, `.importlinter`), about 340 test lines.

## Slices

One slice, R2. Depends on AC0 only (pin with `SafeRecordFilter`). AE1, AE5 and AC1 are not
prerequisites. It edits `ui/output.py` lines `:275` to `:302`, which AC1a does not edit (AC1a
edits `:217` to `:256`); whichever merges second rebases.

## Test depth

T0 on the touched test files per edit; T1 impact selection per commit; T2 gate on the exact
head: T1 plus AT-1 to AT-8, `tests/unit/test_ci_rule_codes.py:416`, `lint-imports`, and M1 to
M13 plus M4b. `target_host` is a key of the `--json` notify entry. The CLI freeze covers JSON shape only
(`docs/release/versioning.md:24`): key names and types, not values. The key and its type do
not change, so this is not a frozen-contract trigger under `testing.md:84` to `:89`. If the
builder finds that `versioning.md:24` says otherwise on its head, the slice runs the full CLI
suite against the saved main baseline. Tests run on the gate nodes, never the devbox.

## Recurring defect checks (dev-rules catalog)

| Id | Class | Applies | Check |
|---|---|---|---|
| D1 | anchored validation | yes, narrow | `safe_logger` name check is `name == "decoy" or name.startswith("decoy.")`, no regex |
| D2 | strict types | yes | `safe_handler` and `safe_logger` typed; mypy on the new module |
| D3 | exception context | no | no new raise beyond the name refusal |
| D4 | versioned read models | no | |
| D5 | normalized scanners | yes | the guard reuses `_calls.py`; seeds aliased, unbound and lookalike calls; names its known limit (a handler passed through a variable built elsewhere) |
| D6 | private-module imports | yes | imports only `decoy_engine.safe_output.SafeRecordFilter`, lazily inside `_DeferredSafeFilter` |
| D7 | hidden CI failures | yes | no skip or `xfail` added; the guard is in the default sentry run |
| D8 | one trust class per entry | yes | one rule: every handler the CLI creates and every CLI logger carries the filter |
| D9 | mutations on final head | yes | M1 to M13 and M4b on the final head, recorded |
| D10 | allowlisted helpers | yes | `_safe_logging.py` is the only exempt module; the restoration loop is exempt by structure (loop target in `finally`), not by function name |
| D11 | no raised caps | yes | no baseline or cap moves |

## Pre-mortem

1. A builder satisfies AT-5 by wrapping a handler at a site that never logs exceptions and leaves
   the notify logger plain: AT-1 catches the notify route.
2. AT-2 passes because the engine already filters `decoy_engine.detectors`: the record comes from
   a child logger with no filter, and M1 alone must turn it red.
3. AT-1 passes because pytest's capture handler swallowed the record: the case removes root
   handlers so `lastResort` runs, and asserts the label is present.
4. A host embedding the CLI sees changed log output: AT-6.

## Docs and changelog

CLI `CHANGELOG.md`: logged exceptions print type labels; `target_host` shows the hostname only.
CODEMAP row for `_safe_logging.py` and the guard.

## Open items

None. The parent contract settles the bare hostname.

## Unverified

- The parent-plan lines `:601` to `:610`, `_calls.py` line numbers and `test_log_interpolation.py:28`
  come from the round-1 review; the builder confirms them on the head it starts from.
- `.importlinter`, `test_import_layers.py:44` and `:340`, `test_ci_rule_codes.py:416` and
  `docs/release/versioning.md:24` come from the round-2 review and are not read here.

## V2-LOG

None.
