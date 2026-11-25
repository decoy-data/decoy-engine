# F31 AE3 plan amendment: one closed rule for log arguments

Status: plan

Rules consulted: README routing table, 00-universal, risk-and-exceptions, development-loop (PLAN,
REMEDIATE three-round stop), cross-cutting-concerns, testing (test depth), security,
catalogs/recurring-defects.

Amends: `2026-11-24-f31-audit.md`, Part 2, Behavior item 4 (`SafeRecordFilter`) and slice AE3.
PR: decoy-engine #809, head `cade66080`. The PR reached the 3-round review cap (Codex R4 NO-GO),
so the plan changes before more code. Risk stays R2 (privacy logic).

## Why the plan changes

Each review round found a new leak or a new output change in the same function, and each fix was
a one-off patch:

| Round | Finding | Patch | What the patch opened |
|---|---|---|---|
| R1 | exceptions inside containers and mappings pass | scan one level into list, tuple, set, frozenset, dict | mapping keys, other mapping types |
| R2 | keys, `UserDict` msg, `Counter` type lost | scan keys, keep the mapping type and its `__missing__` | lookups run caller code |
| R3 | brace formatter reaches `_SafeMapping._original`; `ConfigParser` section enumerated; caller data mutated | rebuild as a new builtin of the same kind; pass clean mappings through; `_ScannedFactory` | the four R4 findings |
| R4 | `defaultdict` factory (a `functools.partial`) holds the exception; `%s`, `%r` and brace fields reach it | none yet | |
| R4 | `{"ValueError": 7, ValueError(): 11}`: the relabelled key overwrites the real key, so `%(ValueError)d` prints 11 | none yet | |
| R4 | a rebuilt `OrderedDict` loses its `move_to_end` order | none yet | |
| R4 | `mappingproxy` passes through, `%s` prints the exception text (strict xfail) | none yet | |

## Defect class

**Open-ended reconstruction of caller objects.** The filter tries to keep each caller mapping
type's behavior (its factory, its key equality, its order, its lazy lookup) while it removes
exceptions. Each behavior it keeps is caller state or caller code that a formatter can reach.
Each behavior it drops changes the output. A new mapping type or behavior is a new case, so the
case list never closes. In the audit plan's class table this is class 1 (value-bearing output)
reached through class 6 (untrusted producer).

## Guarantee and non-goals

Guarantee: after `SafeRecordFilter`, nothing reachable from `record.msg` or `record.args` is a
caller exception or a caller mapping object, and the filter runs no caller code (no
`__getitem__`, `__missing__`, `__iter__`, `items`, `__eq__` or factory of a caller type). Named
`%(name)` lookups on a lone plain-dict-backed mapping keep their stored values.

Non-goals, unchanged from the audit plan: pre-formatted text in `msg`, `exc.args` passed as an
argument, arbitrary wrapper objects whose `__str__` formats an exception, values deeper than the
scan depth, hostile objects (V2). A finding outside this guarantee is a follow-up item, not a
blocker for #809.

## Established solutions

Search run: the Sentry Python SDK serializer (`sentry_sdk/serializer.py`), the OWASP Error
Handling Cheat Sheet and ASVS 7.4.1, CWE-209, the OWASP Input Validation Cheat Sheet, and the
stdlib logging cookbook already cited in `_log_filter.py`.

- The Sentry serializer walks only types it knows (mappings, sequences, primitives) and sends
  every other object through one fallback instead of a per-type case. This amendment follows that
  shape with a stricter fallback: a fixed placeholder, not `repr`, because `repr` is caller code.
- OWASP input validation prefers an allowlist over a denylist. The R1 to R3 patches were a
  denylist of mapping behaviors. The table below is an allowlist of exact builtin types.
- ASVS 7.4.1 and CWE-209: when a value cannot be shown safely, show a generic message. The
  placeholder is that message for a mapping.
- Named-field parsing follows CPython's `%`-format key rule (`Objects/unicodeobject.c`,
  `unicode_format_arg_parse`): a key is the text inside balanced parentheses after `%(`, and `%%`
  is a literal.

The remaining custom code is the type table and the named-field read, about 80 lines. No library
filters `logging` args by type.

## Class table

Classes from the plan contract catalog (`30_Resources/Decoy-Plan-Contract-and-Defect-Catalog.md`).

| # | Class | Applies | Structure that closes it | Proof | Mutation |
|---|---|---|---|---|---|
| 1 | value-bearing output | yes | the closed exact-type table in `_safe_value`; the placeholder for every non-plain mapping | tests 1 to 4, 16 (seeded canary through stream and file handlers) | M1, M2, M7 |
| 2 | cleanup on an exit path | N/A: the filter owns no file or resource | | | |
| 3 | state and concurrency | yes, narrow: the filter must not change caller state | no write to any caller object; `_NamedArgs` is a new dict | tests 5, 8 | M4 |
| 4 | route parity and fallback | yes, narrow: stream, file and host handlers | one filter class on every engine handler; the existing `_UNRENDERABLE` fallback | `test_every_engine_handler_carries_the_filter`, test 4 on both handlers | M10 |
| 5 | referential integrity | N/A: no table data or FK shapes | | | |
| 6 | untrusted producer | yes: caller mapping types and factories | exact types only; no caller code runs | tests 15, 16 | M2, M4, M5 |
| 7 | check then use on a path | N/A: no paths | | | |
| 8 | weak tests and overclaimed evidence | yes | each Codex repro red on `cade66080`, recorded; mutations recorded with their head | the Acceptance tests and Mutations sections | |
| 9 | refactor drift | yes: the plain-dict, tuple and exc_info paths must print as before | tests 10, 12 and the dict case of 13 run unchanged | those tests, green on `cade66080` and on the final head | M9 |
| 10 | frozen contract drift | N/A: `SafeRecordFilter` keeps its name and signature; log text is not a frozen contract | | | |

## Enumerations

Read from `cade66080`, the PR head.

### Exit paths

- Normal: `_scrub` returns and `filter` returns True (`src/decoy_engine/safe_output/_log_filter.py:267`).
- Any exception in `_scrub`: the fallback writes constants only and returns True
  (`src/decoy_engine/safe_output/_log_filter.py:270`). The new code adds no other exit.

### Routes

- Engine console handler: `src/decoy_engine/internal/logging.py:124` and
  `src/decoy_engine/internal/logging.py:165`.
- Engine file handler: `src/decoy_engine/internal/logging.py:145`.
- All three are built by `_new_engine_handler` (`src/decoy_engine/internal/logging.py:22`), which
  adds the filter (`src/decoy_engine/internal/logging.py:29`).
- Host handlers attach the public `SafeRecordFilter` themselves.

### FK shapes

N/A: the filter handles log records, not table data.

### Fields

- `LogRecord` fields the filter reads or writes: `msg`, `args`, `exc_info`, `exc_text`, the
  private `_decoy_safe_exc_text` (`src/decoy_engine/safe_output/_log_filter.py:54`), and
  `stack_info` (kept).
- Argument shapes: a positional tuple; a lone non-empty mapping (`LogRecord.__init__` sets `args`
  to the mapping); a mapping or container as `msg`.
- Mapping kinds checked by test 16: `dict`, `dict` subclasses, `OrderedDict`, `Counter`,
  `defaultdict`, `UserDict`, `mappingproxy`, `ChainMap`, `ConfigParser` sections, caller
  `collections.abc.Mapping` classes.

### Output surfaces

- The formatted message from `msg` and `args`: written at
  `src/decoy_engine/safe_output/_log_filter.py:244` and
  `src/decoy_engine/safe_output/_log_filter.py:248`.
- The traceback text from `exc_info` and `exc_text`: written at
  `src/decoy_engine/safe_output/_log_filter.py:250` to `:257`.
- Brace-style formatter fields over the record (`{args[0].x}`): reach only what `args` holds.
- `stack_info`: code locations and engine source lines, kept.

## Reuse inventory

- `safe_error_type` and `_label` for exception labels (unchanged).
- `_safe_traceback`, `_chain`, `_frames` for `exc_info` (unchanged).
- The existing `_reachable` test helper and `_CANARY`.
- The call-site sentry `tests/sentry/test_log_interpolation.py` for the documented gaps.
- No new registry or sentry module: test 18 is an AST check of one file and stays in the unit
  test file.

## Frozen contracts touched

None. `SafeRecordFilter` is public in `decoy_engine.safe_output`; its name, constructor and
`filter` signature stay the same. The printed text for a non-plain mapping changes (Behavior
changes table), which is log output, not a frozen contract.

## Slices

One slice: the rest of AE3 on PR #809, in decoy-engine, branch `feat/f31-ae3`. Size about -60
source lines and +60 net test lines in two files. No other slice depends on this change.

## Pre-mortem

Ways a gate reviewer could break the built change, each now an acceptance test or a recorded
gap:

1. A mapping type not in the test list leaks: test 16 covers caller `Mapping` classes, and the
   table has no per-type row to forget.
2. A named-field read calls `__missing__`: tests 5 and 15, mutation M4.
3. `_NamedArgs` carries extra keys or a caller reference that a brace field reaches: tests 1, 17,
   mutations M6 and M8.
4. The field parser misreads `%(a(b))s` or `%%(a)s`: test 17 parser cells.
5. A `dict` subclass passes the plain-dict row through `isinstance`: test 3, mutation M5.
6. A wrapper object formats an exception: recorded gap, guarded at call sites.
7. A new engine handler skips the filter: `test_every_engine_handler_carries_the_filter`, M10.

## Choke point

One closed type table in one function, `_safe_value(value, depth)`, in
`safe_output/_log_filter.py`. Every value the filter writes back to `record.msg` or `record.args`
comes from it. It decides by exact type (`type(value) is X`), never by `isinstance`, and it runs
no caller code.

| Input (exact type unless stated) | Output |
|---|---|
| any `BaseException` subclass | its closed type label (`_label`, as today) |
| `str`, `bytes`, `int`, `float`, `complex`, `bool`, `None` | the value itself |
| `list`, `tuple`, `set`, `frozenset` | a new builtin of the same type with each item through `_safe_value(item, depth - 1)`; the value itself when no item changes |
| `dict` whose keys all have an exact type of `str`, `int`, `float`, `bool` or `None` | a new `dict` with each value through `_safe_value(value, depth - 1)` and the keys unchanged; the value itself when no value changes |
| `dict` with any other key type (an exception key included) | the placeholder |
| any other mapping: `issubclass(type(value), collections.abc.Mapping)` or a `UserDict` subclass. This covers dict subclasses, `OrderedDict`, `Counter`, `defaultdict`, `UserDict`, `mappingproxy`, `ChainMap`, `ConfigParser` sections and caller mapping classes | the placeholder |
| anything else, or any value at `depth == 0` | the value itself (the documented wrapper gap, unchanged) |

The placeholder is one module constant, `_MAPPING_PLACEHOLDER = _Label("<mapping>")`. It holds no
reference to the caller object, its type, its factory or its items. The filter never reads the
items of a non-plain mapping, so it never enumerates a lazy view and never calls a factory.

Decisions the table makes:

1. No pass-through for a non-plain mapping, even a clean one. A clean `defaultdict(int)` or
   `Counter` positional argument prints `<mapping>`. This also removes the identity-retention case
   (Codex R4 V2-LOG: formatting a missing key inserted it into the caller's mapping).
2. Keys are never rewritten. A dict that needs a key changed becomes the placeholder, so no
   relabelled key can collide with a real key.
3. No rebuild of a non-plain type. The filter constructs only `list`, `tuple`, `set`,
   `frozenset`, `dict`, `_Label` and `_NamedArgs` (below). The `OrderedDict`, `Counter` and
   `defaultdict` rebuilds and `_ScannedFactory` go away, and the order question goes with them.
4. `msg` goes through the same table at depth 1. A `UserDict` or other non-plain mapping used as
   `msg` prints `<mapping>`.

### Named lookups (`%(name)s`)

`LogRecord` sets `record.args` to the mapping itself when the only argument is a non-empty
mapping. Named lookups must keep working for that case. One function, `_named_args(msg, mapping)`,
handles it, and `_scrub` calls it only for that case:

1. When `msg` is not a `str`, or holds no `%(name)` field, the lone mapping is a positional
   value: `record.args = (_safe_value(mapping, _ARGS_DEPTH - 1),)`. `"%s" % (x,)` prints the same
   as `"%s" % x` for a mapping `x`.
2. Otherwise read the field names from `msg` with the CPython key rule above.
3. Find the store without running caller code: the mapping itself when
   `issubclass(type(m), dict)`; `vars(m)["data"]` when `m` is a `UserDict` and that attribute is
   an exact `dict`; otherwise no store.
4. For each name, read `dict.get(store, name, _ABSENT)`. This calls no `__getitem__`,
   `__missing__` or factory. A present value goes through `_safe_value(value, _ARGS_DEPTH - 1)`.
5. An absent name, or any name when there is no store, takes a value-free default from one closed
   table: `0` for a `Counter`; `factory()` for a `defaultdict` whose factory `is` one of the
   builtins in `_EMPTY_FACTORIES`; `_MAPPING_PLACEHOLDER` for all others.
6. `record.args` becomes a `_NamedArgs`: a `dict` subclass holding only the names from step 2.
   Its `__missing__` returns `_MAPPING_PLACEHOLDER` and its `__repr__` is the plain dict repr of
   those names. It holds no reference to the caller mapping.

Only names from the format string become keys, and values come from exact-key reads of the store.
The exception key in `{"ValueError": 7, ValueError(): 11}` is never read, so `%(ValueError)d`
prints 7. A `%(x)d` field whose value is the placeholder raises `TypeError` in `getMessage()`.
Logging then reports its standard logging error with the filtered args, which is the same
outcome as a missing key in stock logging.

### Removed

`_Lookup`, `_lookup_of`, `_factory_of`, `_ScannedFactory`, `_scan_pairs`, `_scan_mapping`,
`_store_of` (folded into step 3), and the `Counter`, `OrderedDict` and `defaultdict` rebuilds.

## Behavior changes from cade66080

| Input | cade66080 | After |
|---|---|---|
| positional clean `Counter`, `OrderedDict`, `defaultdict`, `UserDict` | passed through, prints its `repr` | `<mapping>` |
| positional `mappingproxy`, `ChainMap`, `ConfigParser` section | passed through, may print exception text | `<mapping>` |
| dict with an exception key | key relabelled, values may collide | `<mapping>` |
| lone `defaultdict` with a caller factory, missing name | factory called, result scanned | `<mapping>` |
| lone `Counter` or `defaultdict(int)`, missing name | `0` | `0`, without calling the mapping |
| dict holding a `defaultdict`, `{args[nested][missing]}` | label | the nested value is the `<mapping>` string, so the brace field fails and prints nothing from the caller |

On `cade66080` no engine logger call passes a `Counter`, `OrderedDict`, `defaultdict`,
`MappingProxyType` or `ChainMap` directly (grep of logger calls). The builder repeats that check
on the final head with a walk of logger calls and lists any hit in the PR body.

## Acceptance tests

Written first in `tests/unit/safe_output/test_log_filter.py`. Each Codex repro is a red test on
`cade66080`, shown red there before the fix. The canary is the existing `_CANARY`.

Codex R4 repros, red on `cade66080`:

1. `test_partial_factory_exception_is_unreachable`: `defaultdict(functools.partial(f,
   ValueError(_CANARY)))` as a positional arg and as the lone mapping, through an engine handler
   with `%s`, `%r` and `%(missing)s`: no canary. A `{`-style formatter with
   `{args[0].default_factory.args[0]}` (positional case) raises or prints no canary. `_reachable`
   from `record.args` and `record.msg` finds neither the exception nor the partial.
2. `test_exception_key_does_not_overwrite_a_named_key`: the lone mapping
   `{"ValueError": 7, ValueError(_CANARY): 11}` with `%(ValueError)d` prints `7`, no canary.
3. `test_ordereddict_arg_is_the_placeholder`: an `OrderedDict` with an exception value after
   `move_to_end("one")`, positional `%s`, prints `<mapping>`, no canary, and the caller's key
   order is unchanged. Lone-mapping case: `%(one)s %(two)s` prints both stored values.
4. `test_mappingproxy_is_the_placeholder`: the `mappingproxy` cell leaves
   `test_documented_gap_uncatchable_shapes` (its strict xfail would now fail) and becomes a
   passing test through the engine's stream and file handlers: `<mapping>`, no canary.
5. `test_named_lookup_never_mutates_a_clean_caller_mapping` (the R4 V2-LOG case): a lone clean
   `defaultdict(int)` with `%(missing)d` prints `0`, and `"missing" not in mapping` afterwards.

Earlier-round repros, kept or rewritten to the new rule (each was red on its round's head):

6. R3 brace formatter: `test_brace_formatter_cannot_reach_the_original_exception`, unchanged.
7. R3 `ConfigParser`: `test_fallback_lookup_result_is_not_enumerated` is rewritten. A lone
   `defaultdict(lambda: section)` gives `%(x)s` = `<mapping>`; a positional section gives
   `<mapping>`; no canary on stderr; `getMessage()` does not raise.
8. R3 caller mutation: `test_lookup_never_mutates_the_caller_mapping`, with the missing value now
   `<mapping>` (`%(missing)s` replaces `%(missing)d`).
9. R3 nested lookup: `test_nested_defaultdict_lookup_is_scanned` becomes
   `test_nested_non_plain_mapping_is_the_placeholder`: `{args[nested]}` prints `<mapping>`, no
   canary, and `_reachable` finds no caller object.
10. R2 `Counter` kept usable: `test_valid_record_is_not_dropped_by_the_filter` and
    `test_unchanged_mapping_arg_renders_the_same`, unchanged (`found 0`, `found 0 2`).
11. R2 `UserDict`: `test_non_dict_mapping_msg_and_arg_are_scanned` becomes
    `test_non_dict_mapping_msg_and_arg_are_the_placeholder`: two `<mapping>` outputs, no canary.
12. R1 cells (exc_info clearing, cached `exc_text`, the exploding-args fallback, containers one
    level down, nested tuples): unchanged.
13. `test_mapping_with_nothing_to_replace_passes_through` keeps only the `dict` case. The
    `counter`, `ordereddict`, `defaultdict_int` and `userdict` cases move to a new parametrized
    `test_clean_non_plain_mapping_is_the_placeholder`.
14. Removed with the code they tested: `test_missing_lookup_returning_exception_becomes_label`,
    `test_missing_lookup_returning_container_is_scanned`,
    `test_failing_missing_lookup_carries_no_exception_text`,
    `test_failing_factory_carries_no_exception_text`, and the strict xfail
    `test_documented_gap_missing_lookup_returning_secret_string`. Test 15 covers their shapes,
    because no lookup or factory runs any more.

New guards:

15. `test_no_caller_code_runs`, parametrized over: a `dict` subclass with `__getitem__`,
    `__missing__`, `__iter__`, `items`, `keys` and `__eq__` that record a call and raise; a
    `defaultdict` with such a factory; a `UserDict` with such a `__getitem__`; a
    `collections.abc.Mapping` with such `__getitem__` and `__iter__`. Positional and lone-mapping
    shapes, with `%s`, `%r` and `%(a)s`. Assert no method was called and no canary in the output.
16. `test_any_mapping_type_is_value_free` (Hypothesis): nests one and two levels deep built from
    `dict`, `OrderedDict`, `Counter`, `defaultdict` (empty-builtin and caller factories),
    `UserDict`, `mappingproxy`, `ChainMap`, a `ConfigParser` section and a caller `Mapping`, with
    the canary exception planted as a key, a value, a factory bound argument or a factory result.
    Format with `%s`, `%r`, a named field from the generated keys, and a `{`-style formatter over
    `{args}`. Assert no canary, and that `_reachable(record.args)` holds no planted object.
17. `test_named_args_holds_only_format_fields`: after filtering a lone mapping with fields `a` and
    `b`, `record.args` is a `_NamedArgs` with exactly the keys `{"a", "b"}`. Parser cells: a key
    with nested parentheses and a `%%` before a field, compared with CPython's own `%` result on
    a plain dict.
18. `test_filter_builds_only_closed_types` (sentry, same file, because it guards one module): an
    AST walk of `_log_filter.py` finds no call to `OrderedDict`, `Counter`, `defaultdict`,
    `UserDict`, `copy` or `type(...)(...)`, and no attribute read of `default_factory`, `items`,
    `keys` or `values`. A seeded `defaultdict(...)` call in a scratch copy turns it red.

The other documented gaps stay strict xfails: `exc_args`, `wrapper_str`, `too_deep`, and the
pre-formatted text cells.

## Mutations

Each must turn at least one named test red on the final head (recurring defect 9: record the head
each mutation ran on). The builder records the results in the PR body.

| # | Mutation | Test that must fail |
|---|---|---|
| M1 | return a clean non-plain mapping as is | 13, 4 |
| M2 | read a non-plain mapping through `.items()` instead of the placeholder | 15, 16, 7 |
| M3 | relabel exception keys into a rebuilt dict instead of the placeholder | 2, 16 |
| M4 | read a named field with `mapping[name]` instead of `dict.get(store, ...)` | 1, 5, 8, 15 |
| M5 | use `isinstance(value, dict)` for the plain-dict row | 3, 13, 16 |
| M6 | keep a reference to the caller mapping on `_NamedArgs` | 1, 16 |
| M7 | make the placeholder's `repr` call the caller object's `repr` | 1, 4, 16 |
| M8 | copy every stored key into `_NamedArgs`, not only the format fields | 2, 17 |
| M9 | drop the `Counter` row of the default table | 10 |
| M10 | remove the `addFilter` call in `_new_engine_handler` (existing guard) | `test_every_engine_handler_carries_the_filter`, 4 |

## Failure modes

| Failure | Detection | Response |
|---|---|---|
| a new mapping type appears | it is not an exact plain type, so it gets the placeholder | none needed |
| a log line that printed a clean `Counter` now prints `<mapping>` | the builder's walk of logger calls; the PR body list | pass `dict(counter)` at the call site |
| a named field's value is the placeholder under `%d` | stock logging error with filtered args | the call site passes a plain dict |
| the field parser disagrees with CPython on an odd key | test 17 parser cells | follow the CPython rule |

## Design notes

No new structure. The change removes the lookup machinery and replaces many type cases with one
table (open/closed: a new mapping type needs no new code). Each fact has one place: the type
table in `_safe_value`, the default table in `_named_args`, the placeholder constant.

## Placement and size

No new files. `_log_filter.py` loses `_Lookup`, `_ScannedFactory` and the rebuild code, and gains
`_safe_value`, `_named_args`, `_NamedArgs` and the placeholder. Expected: about -60 net source
lines, about +150 and -90 test lines. No new public names. Tests stay in
`tests/unit/safe_output/test_log_filter.py`.

## Test depth

T0 on `test_log_filter.py` per edit. T1 per commit: `tests/unit/safe_output/`,
`tests/sentry/test_log_interpolation.py`, the logging config tests that import
`_new_engine_handler`, ruff check, ruff format and mypy on changed files. No full-suite trigger
applies (no shared fixture, schema, lock or frozen contract change).

## Docs and changelog

The `_log_filter.py` module docstring gets the type table and the named-lookup rule in place of
the current mapping text. The gap list drops "a mapping type other than dict and `UserDict`". The
CHANGELOG line says a non-plain mapping argument prints `<mapping>` in engine logs.

## V2-LOG

- Wrapper objects whose `__str__` or `__repr__` formats an exception: unchanged gap, guarded at
  call sites by `test_log_interpolation.py`.
- A caller `defaultdict` factory that is value-free in practice (for example `lambda: 0`) gives
  `<mapping>` for a missing named field. Accepted.
