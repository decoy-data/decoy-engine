# F31 AC2: SafeRecordFilter on every CLI log path

Status: plan

Rules consulted: README routing table, 00-universal, risk-and-exceptions, development-loop (PLAN,
proportion), cross-cutting-concerns (choke point, guard, seeded bypass), security, testing (test
depth), architecture, api-and-compatibility, code-review, verification, documentation, catalogs/recurring-defects, and the plan contract
(`30_Resources/Decoy-Plan-Contract-and-Defect-Catalog.md`).

Parent plan: engine `docs/plans/2026-11-24-f31-audit.md`, especially the AE3 contract at lines
304–313, the hostname and fallback at 323–324, and the AC2 red-first case at 601–610.
CLI roadmap row: `docs/roadmap/groups/health.md`, F31-AUDIT.

Risk: R2. This changes CLI-visible log output, notify host display and webhook 4xx handling.
Two independent implementation reviewers (Dennis, then Codex) and a T2 gate on the exact head.

Reviewed bases: CLI `d6b9e4c7`, engine `2b8a47fbe`. CLI pins engine 0.28.3. The engine
snapshot has the public `safe_error_type` but does not export `SafeRecordFilter`. AC2 is
ready to implement **after AC0**. In the installed, locked CLI environment, verify that the
released AE3 filter imports from `decoy_engine.safe_output` before starting. Then use that
installed implementation in AT-1/AT-2. AC0 owns the pin and lock. A missing or incompatible export blocks delivery of AC2.
Never substitute a local sanitizer, stub the filter in acceptance tests or pass a raw record
through on import failure.

## Defect class

A CLI log record carries an exception or pre-rendered data in its message, operands or traceback, and a handler
prints it. AE3 will attach `SafeRecordFilter` to engine-owned handlers. The CLI's own
handlers and loggers do not have it: the detector handler `_ErrConsoleHandler`
(`ui/output.py:275`) prints `record.getMessage()` (`:280` to `:281`), and the notify logger
(`notify.py:62`) has no handler, so its warnings reach stderr through the stdlib
`logging.lastResort` handler. Separately, `_host_only` (`notify.py:456`) shows `host:port`, and
the parent contract asks for the bare hostname.

## Guarantee and non-goals

Guarantee:

1. Every handler the CLI creates passes through `safe_handler(handler)` at attachment.
   That function adds one deferred `SafeRecordFilter` (Choke point).
2. Every CLI-owned logger (`decoy` and `decoy.*`) is made by `safe_logger(name)`, which adds
   the deferred `SafeRecordFilter` to the logger. A logger filter runs for records created on that logger,
   before any handler, `lastResort` included.
3. The CLI never adds a filter to a handler it did not create. `ci/engine_logging.py:44` to `:47`
   restores the caller's exact handler objects, unchanged, so a host handler keeps its own
   filters and formatting after the CLI returns.
4. For webhook and Slack, the warning and `target_host` show the bare hostname (`urlsplit(url).hostname`, IPv6
   in brackets), excluding userinfo, port, path and query. Malformed URLs retain the existing fallback.
5. The email warning and result expose only the mailbox domain. The same redactor supplies
   both. The current first-`@` split can print part of a quoted local part or an address
   comment. A read-only baseline probe with a failing SMTP transport confirmed both surfaces. For example, `"left@CANARY"@example.com` currently displays
   `***@CANARY"@example.com` in `notify.py:410` and `:435`.

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
reuses the public engine filter specified by AE3.

## Choke point

`src/decoy/_safe_logging.py`, two functions and one private filter class:

- `_DeferredSafeFilter(logging.Filter)` imports `decoy_engine.safe_output.SafeRecordFilter` on
  its first `filter()` call and delegates to one instance of it. `src/decoy/__main__.py:51`
  imports `ui/output.py` on every start, and `notify.py:62` makes its logger at import, so an
  eager import would load the engine during CLI startup, before `decoy ci` sets its logging
  policy. The deferred class keeps the startup contract.
- `safe_handler(h: logging.Handler) -> logging.Handler` attaches the shared `_DeferredSafeFilter`
  and returns the same `h`. Only for handlers the CLI constructs.
- `safe_logger(name: str) -> logging.Logger` returns `logging.getLogger(name)` with one
  `_DeferredSafeFilter` on the logger. It refuses a name outside `decoy` and `decoy.*`.

Use one module-owned deferred filter object for both factories. Stdlib `addFilter` already
ignores the same object on a second call. Return the engine filter’s result directly. At
`ui/output.py:295–301`, attach `safe_handler(handler)` and remove that same handler in
`finally`. No CLI code assigns to root handlers or `logging.lastResort`.

Layer map: the module joins the exhaustive CLI layer contract in `.importlinter:21` to `:32`
and its snapshot in `tests/sentry/layout/test_import_layers.py:44`, as an independent sibling on the existing `_config_file | _outbound` row, so
`notify` and `ui` can both import it and the `notify` relocation test at `:340` still passes.
`lint-imports` runs with no new exception.

Guard: `tests/sentry/io_policy/log_handlers/test_log_handlers_filtered.py`, static. It reuses
the call resolver in `tests/sentry/io_policy/_calls.py` (`:59`, `:71`, `:141`) for qualified
imports, aliases and method names, so there is one call scanner.

1. Check the handler operand of bound and unbound `addHandler` calls, including the
   `hdlr=` spelling. Require the resolved wrapper from this module. Its input must be a
   CLI-created handler (a constructor expression or a local bound to that constructor, as
   at `ui/output.py:295`). Check calls to the wrapper itself, so wrapping a borrowed
   handler also fails the guard. Seed `safe_handler(logger.handlers[0])` and a wrapper
   around the restore-loop target. The sole restoration
   exemption is `ci/engine_logging.py:45` in `engine_logging_silenced`: the same logger,
   the `finally` loop's target, and that loop's iterable bound before the try to
   `list(logger.handlers)`. Verify these relationships with `Site.guards()`. A different
   list, receiver, extra attachment or fresh handler in that function gets checked normally.
2. The sole raw CLI lookup is inside the checked `safe_logger` factory. Elsewhere admit raw
   lookups only for statically external names (including `"decoy_engine"`, `"opentelemetry"`
   and `ui/output.py:272`'s literal-backed `DETECTOR_LOGGER`). Reject root, CLI-owned and
   unresolved dynamic names, including positional and `name=` forms. Keep logger construction
   eager and the engine import lazy.
3. Check calls on logger receivers, including names bound to the factory or raw getter and
   direct chained calls. Resolve imported aliases with `_calls.sites/qualified`. Ignore
   unrelated receivers such as a CLI console or parser with an `error` method. Use the actual
   message slot (`msg=`, first positional, or second for `log(level, msg, ...)`). Require a
   literal message. AE3 transforms exception objects, but ordinary strings pass through. Permit exception arguments in a string conversion slot (e.g. `%s`); a numeric slot such as `%d` would fail formatting after replacement. Seed that mismatch.
   Check each formatting operand against the following sources. Unknown operands fail closed.

   - A current, unreassigned exception binding in its handler, or its `type(exc).__name__`
     diagnostic. Only the former relies on AE3 rewriting. Numeric literals are also safe.
   - The real notify helpers `_host_only` and `_redact_email` (lines 456 and 472). Resolve
     local definitions in their defining module or qualified imports. Reject lookalikes.
   - The HTTP status from the response returned by `_outbound.open_url` or a caught
     `urllib.error.HTTPError.code`, including the local `status_code` whose assignments
     come from those two sources. The refusal code comes from a caught
     `_outbound.OutboundRefused` (lines 297, 350). An arbitrary object's `.status` or
     `.code` is insufficient.
   - The retry limit and the one-based counter from `range(_max_retries)` (lines 289–305),
     and the parsed channel kind in `dispatch` (line 445). Scope these checks to their
     producers and reject other bindings or reassignments. Keep the warning text and its
     diagnostic fields. No exemption for a warning site or the notify module as a whole.
4. Reject stdlib module-level emitters and `basicConfig` under qualified and imported
   aliases, including `warn` and `fatal`. Use the same emitter names for method checks.
   This prevents implicit root configuration and emission through an unfiltered root logger.

AT-5 positive fixtures cover each operand above, both status sources, the restoration loop,
the real external lookups, logger aliases, and a non-logging `error` method. Scan the full
CLI source tree. Negative fixtures cover bare and unbound attachments, an unrelated saved
list, a neighboring unwrapped handler, lookalike wrappers and redactors, an aliased raw CLI
lookup, a root lookup, a dynamic lookup, root emitters and `basicConfig`. On a logger from
`safe_logger`, seed an f-string message, `str(exc)`, `exc.args[0]`, `exc.reason`, a raw URL,
a rebound status variable and an unrelated `.code` operand. Include a `msg=` and a
`log(level, msg)` case. Assert the precise offending sites so one hit cannot mask a miss.

The runtime proof is per route, not an import census: AT-1 (`lastResort`), AT-2 (detector
handler), AT-6 (restoration).

## Class table

| # | Class | Applies | Structure that closes it | Proof | Mutation |
|---|---|---|---|---|---|
| 1 | value-bearing output | yes: the defect class | `safe_handler` and `safe_logger` are the only ways to attach a CLI handler or make a CLI logger; guard rule 3 checks message and operand sources | AT-1, AT-2, AT-3, AT-5 | M1: drop `addFilter` in `safe_handler`; M3: drop it in `safe_logger`; M8: add `logger.warning(f"{exc}")` in `notify.py` |
| 2 | cleanup on an exit path | yes: `detector_log` removes its handler in `finally`; `engine_logging` restores handlers in `finally` | the filtered handler is removed the same way; restoration re-adds the exact saved objects | AT-2 checks the handler list after exit; AT-6 | M6: wrap the restored handlers |
| 3 | state and concurrency | yes: loggers are process-global | `safe_handler` and `safe_logger` are idempotent (one filter, deduplicated by object identity); the CLI does not touch shared handlers | AT-4, AT-6 | M2: allocate and add a fresh filter on every call |
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
  response. In each attempt read `resp.status` inside the existing response context, or
  read `exc.code` and close the file-like `HTTPError` before classifying it. Use one
  status decision after those paths converge. Keep one shared backoff tail, also used for
  ordinary `URLError`. Retain permanent outbound refusal, the response 2xx return, the
  existing retry budget for other non-2xx responses, and the same signed body and delivery ID
  across attempts. A 4xx logs once in the transport and returns its existing response-case
  detail. The separate dispatch summary still prints on stderr.
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

- The sentry checks CLI message literals and operands. AE3 owns exception operands, live
  `exc_info` and cached `exc_text`. It does not sanitize arbitrary data strings.
- `NotifyResult.target_host` (`notify.py:448`) and the host in every notify warning, for URL targets come from
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
3. Valid URL targets show the hostname without the port. **OWNER CALL (recommended default chosen)**:
   retain bracketed IPv6 display and the tested `(unknown host)` for missing hosts, malformed
   brackets and invalid or out-of-range ports. Keep the existing `parts.port` validation
   inside the helper's `try` and omit the port when rendering. For email, use the stdlib structured address header parser inside the existing
   `_redact_email`. Return `***@` plus the parsed domain for one defect-free mailbox with
   a domain. On malformed, ambiguous or unparseable input return the existing fixed
   `(redacted)`, including when parsing raises. Dispatch computes this display before
   its per-channel try block. Redaction must be total. The original address still goes to
   the sender; the display helper makes no delivery or validation decision.
4. Host handler identities, order, filters, formatter and the saved logger settings survive
   the context. Host handlers receiving a filtered Decoy record can see the sanitized record.

5. A webhook that answers 4xx is posted once and warned about as
   `webhook <host> returned HTTP <code> (4xx, not retrying)`; today it is retried and reported as
   unreachable. A 5xx `HTTPError` keeps the retry.

## Acceptance tests

| Id | Test | Red-first or mutation |
|---|---|---|
| AT-1 | `tests/unit/safe_logging/test_safe_logging.py` (new): with pytest's root capture handlers removed for the case so `lastResort` runs, log `logger.warning("x %s", exc)` on the notify logger with the canary `DECOY_CANARY_F31_7Q4Z` in `exc`; and, inside an active `except`, `logger.warning("x", exc_info=True)`; capture stderr; assert the expected built-in label (use ValueError) and no canary for **each** emission separately; add a cache-only LogRecord with tainted `exc_text` and require the literal message and no cache text | red on main (no filter on the notify logger). M3 |
| AT-2 | same file: inside `detector_log(state, on=True)`, a record from `decoy_engine.detectors.child` (a child with no logger filter) with `"%s"` and a canary-bearing exception in `args`; assert stderr has the label and no canary; require a normal detector line with its identifier/count unchanged. On normal exit and on a raised sentinel, the prior level and handler list are restored | red on main. M1 alone must fail it |
| AT-3 | `tests/sentry/test_notify_redaction.py` (extend): a failing job with webhook URL `http://user:DECOY_CANARY_F31_7Q4Z@hooks.example.com:8443/hook`, with pytest's root handlers removed so the warning goes through `lastResort` to stderr. Two transport cases at `_outbound.open_url`: (a) it returns a 400 response object; (b) it raises `urllib.error.HTTPError(url, 400, ...)`, as the real opener does. In both, assert exactly one POST, stderr contains the complete prefix `webhook hooks.example.com returned HTTP 400`, `delivered == false`, EXIT_RUNTIME (3) for a post-start RuntimeError, `target_host == "hooks.example.com"`, and canary absence from stdout, stderr, the whole `--json` document, each formatted warning, every POST body and every file the run writes. Case (c): the first call raises `HTTPError(url, 503, ...)` and the second returns 200; assert exactly two POSTs and `delivered == true`, with identical delivery ID, body bytes and HMAC header across attempts. Apply the hostname and canary checks to this retry too. The failed job still exits 3 | red on main for `target_host` and for case (b). M4, M4b, M9, M11 |
| AT-4 | `tests/unit/safe_logging/test_safe_logging.py`: `safe_handler` twice on one handler and `safe_logger` twice on one name leave exactly one `_DeferredSafeFilter`; `safe_logger("decoy")` and a child succeed, and `safe_logger("decoyish")` and `safe_logger("other")` raise without altering those loggers | M2 |
| AT-5 | `tests/sentry/io_policy/log_handlers/test_log_handlers_filtered.py` (new): the guard and its self-test (bare, aliased, unbound, lookalike, unwrapped-beside-restoration and f-string cases); on the real tree nothing is flagged | M5: unwrap `safe_handler(...)` around the `NullHandler` at `ci/engine_logging.py:38`; the guard fails while the restoration loop at `:45` still passes. M7, M8, M12, M13 |
| AT-6 | `tests/unit/safe_logging/test_engine_logging_restore.py` (new): put a host handler with its own filter and formatter on the engine logger. Exercise `engine_logging_silenced()` on normal and exceptional exit. Assert the ordered handler identities, filters, formatter, level and propagation are restored. Emit the same synthetic exception record before and after and compare the host sink’s non-empty output | M6 |
| AT-7 | `tests/e2e/test_notify_live_webhook.py:152` and `tests/e2e/test_run_notify_cl4.py:62` to `:75` (credential and IPv6 ports removed; malformed port retains the tested fallback). Add absent host, malformed brackets and out-of-range port cases | red on main |
| AT-8 | `tests/unit/safe_logging/test_safe_logging.py`: in a fresh `python -I` process (which ignores `PYTHONPATH`), the child first inserts the reviewed checkout's `src` at the front of `sys.path`, passed in by the parent from the test file's own location, then imports `decoy.__main__` and `decoy.notify`, asserts `decoy.__file__` resolves inside that `src`, and asserts `decoy_engine` is not in `sys.modules`. Plus the existing fresh-process regression `tests/unit/test_ci_rule_codes.py:416` | M10: import `SafeRecordFilter` at module scope in `_safe_logging.py` |

For AT-1/AT-3, isolate the notify → decoy → root handler chain for the stderr pass, with
propagation and WARNING enabled and the real stdlib last-resort handler. Restore all logging
state even on test failure. In a separate AT-3 capture pass, attach a recording handler
with a stock formatter and require the expected transport warning in its formatted records before checking them for the canary, including tracebacks.
Adding this handler to the stderr pass would suppress lastResort. AT-2 captures the Rich
handler’s own console in isolation so an ancestor handler cannot satisfy its assertion.

For AT-3 reuse the sentry’s post-start `run_pipeline` failure fixture pattern. Supply
`--notify-on always --json --result <tmp-result>`, set `DECOY_LIBRARY` to its own directory under
`tmp_path` (`cli/library/_paths.py:103–106`), and keep raw debug off. Assert a single parsed top-level
`notify` entry, the transport warning and separate delivery summary on failed delivery,
a written result equal to the JSON `result` member and an actual stored run-result.
Scan the result, library contents (read the logical record too), emitted logs and other
generated files under the isolated roots. The canary enters through the URL password. Configure a synthetic signing secret for the retry case.
Use zero backoff via the existing constants. Assert closed HTTPError response streams
with a tracked file object. In a read-only transport probe on CLI `d6b9e4c7`, a raised
400 produced three attempts, an “unreachable” warning with the port, and no password in that
warning. Before implementation run the same cases on the baseline and
record the observed failures per sink; a host:port mismatch alone does not prove a password leak.

AT-7 also exercises email through the normal notify fan-out with a mocked SMTP send failure.
Use a canary in a quoted local part containing `@` and in a trailing comment on a separate
address. Assert a nonempty SMTP warning and JSON target showing `***@example.com`, and no
canary on either surface. Keep the plain-address case; malformed/multiple addresses show
`(redacted)` and preserve the run exit. M14 restores the first-`@` split.

Mutations M1 to M14 and M4b run on the final head; the PR body records that head.

## Mutations

| Id | Mutation | Killed by |
|---|---|---|
| M1 | drop `addFilter` in `safe_handler` | AT-2 |
| M2 | allocate and add a fresh filter on every call | AT-4 |
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
| M14 | restore the first-`@` split in `_redact_email` | AT-7 SMTP warning and notify result |

## Failure modes

| Failure | Detected by |
|---|---|
| A new module adds a bare handler | AT-5 |
| A new module makes a CLI logger with `getLogger` and logs an exception | AT-5 (no CLI-owned `getLogger` outside `_safe_logging.py`, aliases resolved) |
| A child CLI logger (`decoy.notify.x`) logs without a filter | `safe_logger` is the only maker; the guard flags the child's `getLogger` |
| A pinned filter cannot process a record | AC0 must supply the AE3 contract; exercise the installed delegate on real records in AT-1/AT-2 |
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

About 120 changed source/config lines in six files (`_safe_logging.py`, `ui/output.py`,
`ci/engine_logging.py`, `telemetry.py`, `notify.py`, `.importlinter`), about 340 test lines across the acceptance files and layer snapshot, plus CODEMAP and CHANGELOG. The two internal factories are the only new CLI call points.

## Slices

One slice, R2. Depends on AC0 only (pin with `SafeRecordFilter`). AE1, AE5 and AC1 are not
prerequisites. It edits `ui/output.py` lines `:275` to `:302`, which AC1a does not edit (AC1a
edits `:217` to `:256`); whichever merges second rebases.

## Test depth

T0 on the touched test files per edit; T1 impact selection per commit; T2 gate on the exact
head: T1 plus AT-1 to AT-8, the existing webhook signing/retry tests in `tests/unit/test_notify.py`, `tests/unit/test_ci_rule_codes.py:416`, `lint-imports`, and M1 to
M14 plus M4b. Exercise the filter routes on supported Python versions on both sides of the
3.12 logging change; the AE3 contract requires in-place sanitization even where returning
a replacement record is unsupported. `target_host` is a key of the `--json` notify entry. The CLI freeze covers JSON shape only
(`docs/release/versioning.md:24`): key names and types, not values. The key and its type do
not change, so this is not a frozen-contract trigger under `testing.md:84` to `:89`. If the
builder finds that `versioning.md:24` says otherwise on its head, the slice runs the full CLI
suite against the saved main baseline. T3 runs the full default suite once on the merge head per `testing.md`. Implementation tests run on the gate nodes.

## Recurring defect checks (dev-rules catalog)

| Id | Class | Applies | Check |
|---|---|---|---|
| D1 | anchored validation | yes, narrow | `safe_logger` name check is `name == "decoy" or name.startswith("decoy.")`, no regex |
| D2 | strict wire and stored types | existing shape | AT-3 checks the parsed notify entry with a string hostname and a JSON boolean (use identity for true/false); there is no new reader |
| D3 | exception context | no | factory refusal uses fixed text and never interpolates the name; HTTPError handling introduces no wrapped exception |
| D4 | versioned read models | no | |
| D5 | normalized scanners | yes | the guard reuses `_calls.py`; seeds aliased, unbound and lookalike calls; rejects a handler variable at attachment; runtime monkey-patching is outside the scanner |
| D6 | private-module imports | yes | imports only `decoy_engine.safe_output.SafeRecordFilter`, lazily inside `_DeferredSafeFilter` |
| D7 | hidden CI failures | yes | no skip or `xfail` added; the guard is in the default sentry run |
| D8 | one trust class per entry | yes | one rule: every handler the CLI creates and every CLI logger carries the filter |
| D9 | mutations on final head | yes | M1 to M14 and M4b on the final head, recorded |
| D10 | allowlisted helpers | yes | `_safe_logging.py` has only the checked getter in `safe_logger`; AT-4 checks the factory itself and AT-5 checks the exact restore relationship |
| D11 | no raised caps | yes | no baseline or cap moves |

## Pre-mortem

1. A builder satisfies AT-5 by wrapping a handler at a site that never logs exceptions and leaves
   the notify logger plain: AT-1 catches the notify route.
2. AT-2 passes because the engine already filters `decoy_engine.detectors`: the record comes from
   a child logger with no filter, and M1 alone must turn it red.
3. AT-1 passes because pytest's capture handler swallowed the record: the case removes root
   handlers so `lastResort` runs, and asserts the label is present.
4. A host handler retains a CLI-installed filter after the context exits: AT-6.

## Docs and changelog

CLI `CHANGELOG.md`: logged exception objects print safe labels, URL targets omit valid ports, and a real webhook 4xx ends retries, and email diagnostics omit quoted local parts and comments.
CODEMAP row for `_safe_logging.py` and the guard.

## Open items

The compatibility choice for malformed authorities and IPv6 is recorded in Behavior changes.

## Unverified

AC0's released filter and AC2's future implementation have no runtime evidence on these
snapshots. AT-1 through AT-8 and the final-head mutations are implementation gates.

## Round 4 resolution

- **V1** Made the real AE3 export and AC0 pin a prerequisite for emitting filtered records.
- **DESIGN** Reconciled the guard with all eight existing notify warning sites. Added
  producer-aware positive and negative cases and one shared filter instance.
- **V1** Specified one webhook status decision, resource cleanup, and retry and signing checks.
- **V1** Fixed the planned trust in the first-`@` email redactor with one parsed-domain display helper and a warning/result regression.
- **V1** Made the canary checks non-vacuous for both logging routes, the POST, result file
  and stored record. Preserved the existing malformed-port fallback.
- **V2-LOG** Corrected host-handler guarantees, layer placement and baseline references.

## V2-LOG

Existing private engine access in CLI `ci/engine_logging.py:28–35` remains a follow-up.
Host-installed handlers, traceback locals and dynamically monkey-patched logging are outside
the CLI-owned output guarantee.
