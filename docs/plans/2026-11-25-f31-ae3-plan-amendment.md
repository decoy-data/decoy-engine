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

Dennis plan review R1 (GO-WITH-FIXES) is folded in below: the lone-mapping path always returns a
truthy `_NamedArgs` (V1-1), the existing tests the rule turns red are listed (V1-2), the exception
and mapping rows come before the depth check (V1-3), the guarantee is narrowed (D1), the builtin
call form is fixed (D2), three mutations are added (D3), and lone `ChainMap`, `mappingproxy` and
`UserDict` rows are added to the behavior table.

Codex plan review R2 (NO-GO) is folded in as rules, not cases. Each claim was checked on
`cade66080` with the interpreter:

- V1-1: a lone dict's `%s` display scanned one level too shallow. The display now comes from the
  same scanned pairs as named lookup.
- V1-2: a `namedtuple` would pass through and print the canary. Subclasses of the four sequence
  types keep the current safe rule.
- V1-3: a second filter turned a clean display into `<mapping>`. Re-filtering is now a no-op.
- V1-4: an unused field (`10**5000`) made an eager `repr` fail the whole record. Display is now
  lazy.
- V1-5: a `PurePath` msg and a host `{args[a]}` formatter lost fields. The field parser is
  removed: `_NamedArgs` holds every safe exact-`str` key.
- D6: `dict.get` still ran a `str` subclass key's `__eq__`. Named values now come from the
  shared pair traversal.
- D7: the brace repro now uses `{args[0].default_factory._factory.args[0]}`, M5 mutates the
  subclass dispatch, and M10 bypasses the factory at one route.
- D8: test 13's identity assertion is replaced in the implementation commit.
- V2-LOG: test 18's `==` check is narrowed to caller values.

## Defect class

**Open-ended reconstruction of caller objects.** The filter tries to keep each caller mapping
type's behavior (its factory, its key equality, its order, its lazy lookup) while it removes
exceptions. Each behavior it keeps is caller state or caller code that a formatter can reach.
Each behavior it drops changes the output. A new mapping type or behavior is a new case, so the
case list never closes. In the audit plan's class table this is class 1 (value-bearing output)
reached through class 6 (untrusted producer).

## Guarantee and non-goals

Guarantee, inside the scan depth only:

- The scan reaches `record.msg` and one container level inside it, and each positional argument
  (or each value of a lone mapping) and one container level inside it.
- At every position the scan reaches, a caller exception becomes its label and a non-plain
  mapping becomes the placeholder. No reference to either stays in what the filter writes back.
- For each value it inspects, the filter makes exact type checks and calls only the builtin
  methods named under Choke point (`dict.items` and the unbound `__iter__` of `list`, `tuple`,
  `set` or `frozenset`). It calls no `__getitem__`, `__missing__`, `__iter__`, `items`, `__eq__`,
  `__hash__`, `__repr__` or factory of a caller type, and no key lookup on a caller store.
- Named `%(name)` lookups on a lone mapping whose items are in a plain `dict` (the mapping
  itself, or a `UserDict`'s `data`) keep their stored values when the key is an exact `str`,
  whatever the `msg` type and whatever reads them (`%`, or a host `{args[a]}` formatter).
- Each output surface of one record prints the same, on every handler, after any number of
  filter passes.

Values past the scan depth, objects that are not exceptions or mappings, and caller metaclasses
that change `issubclass` are outside the guarantee (the documented gaps and V2).

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
- No named-field parsing (Codex R2 V1-5). `LogRecord.getMessage` does `str(msg) % args`, and
  the stdlib `%` operator does the key lookup itself on the dict it is given. Handing it a plain
  dict of every safe `str` key reuses CPython's own key rule instead of a copy of it.

The remaining custom code is the type table and the shared pair traversal, about 80 lines. No library
filters `logging` args by type.

## Class table

Classes from the plan contract catalog (`30_Resources/Decoy-Plan-Contract-and-Defect-Catalog.md`).

| # | Class | Applies | Structure that closes it | Proof | Mutation |
|---|---|---|---|---|---|
| 1 | value-bearing output | yes | the closed exact-type table in `_safe_value`; the placeholder for every non-plain mapping | tests 1 to 4, 16 (seeded canary through stream and file handlers) | M1, M2, M7 |
| 2 | cleanup on an exit path | N/A: the filter owns no file or resource | | | |
| 3 | state and concurrency | yes, narrow: the filter must not change caller state | no write to any caller object; `_NamedArgs` is a new dict | tests 5, 8 | M4 |
| 4 | route parity and fallback | yes, narrow: stream, file and host handlers | one filter class on every engine handler; the existing `_UNRENDERABLE` fallback; a second filter pass keeps `_NamedArgs` unchanged | `test_every_engine_handler_carries_the_filter` (extended to console, file and fallback), test 4 on both handlers, test 22 | M10, M19 |
| 5 | referential integrity | N/A: no table data or FK shapes | | | |
| 6 | untrusted producer | yes: caller mapping types and factories | exact types only; no caller code runs | tests 15, 16 | M2, M4, M5 |
| 7 | check then use on a path | N/A: no paths | | | |
| 8 | weak tests and overclaimed evidence | yes | each Codex repro red on `cade66080`, recorded; mutations recorded with their head | the Acceptance tests and Mutations sections | |
| 9 | refactor drift | yes: the plain-dict, tuple, sequence-subclass and exc_info paths must print as before | tests 10 and 12 run unchanged; the dict case of 13 keeps its output assertion and changes only its identity assertion (Codex R2 D8); tests 20 and 21 pin the `cade66080` output | those tests, green on the final head; 20 and 21 also green on `cade66080` | M9, M17, M18 |
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

One slice: the rest of AE3 on PR #809, in decoy-engine, branch `feat/f31-ae3`. Size about -50
source lines and +130 net test lines in two files. No other slice depends on this change.

## Pre-mortem

Ways a gate reviewer could break the built change, each now an acceptance test or a recorded
gap:

1. A mapping type not in the test list leaks: test 16 covers caller `Mapping` classes, and the
   table has no per-type row to forget.
2. A named-field read calls `__missing__` or a stored key's `__eq__`: tests 5 and 15, mutation
   M4.
3. `_NamedArgs` carries an unscanned value, a non-`str` key or a caller reference that a brace
   field reaches: tests 1, 17, mutations M6 and M8.
4. The display and the named values drift apart in depth: test 20, mutation M17.
5. A `dict` subclass passes the plain-dict row: test 3, mutation M5. A sequence subclass prints
   its own `repr`: test 21, mutation M18.
6. A wrapper object formats an exception: recorded gap, guarded at call sites.
7. A route builds a handler outside `_new_engine_handler`: the extended
   `test_every_engine_handler_carries_the_filter`, M10.
8. Two handlers print one record differently: test 22, mutation M19.
9. An unused value fails the whole record: test 23, mutation M20.

## Choke point

One closed type table in one function, `_safe_value(value, depth)`, in
`safe_output/_log_filter.py`. Every value the filter writes back to `record.msg` or `record.args`
comes from it. It decides by exact type (`type(value) is X`), never by `isinstance`, and it runs
no caller code.

Rows are checked in this order. The first match wins. Rows 1 and 2 come before the depth check,
so an exception or a non-plain mapping is replaced at every position the scan reaches, depth 0
included.

| # | Input (exact type unless stated) | Output |
|---|---|---|
| 1 | any `BaseException` subclass | its closed type label (`_label`, as today) |
| 2 | any mapping that is not an exact `dict`: `issubclass(type(value), collections.abc.Mapping)` or a `UserDict` subclass. This covers dict subclasses, `OrderedDict`, `Counter`, `defaultdict`, `UserDict`, `mappingproxy`, `ChainMap`, `ConfigParser` sections and caller mapping classes | the placeholder |
| 3 | at `depth == 0`: a `list`, `tuple`, `set`, `frozenset`, `dict` or a subclass of one of the first four (Codex R1 V1) | the placeholder `<nested>`; any other value at depth 0 is the value itself |
| 4 | `str`, `bytes`, `int`, `float`, `complex`, `bool`, `None` | the value itself |
| 4a | a `str` subclass other than `_Label` (Codex R1 V1) | `str.__str__(value)`, a plain copy, so its own `__str__` and `__repr__` never run |
| 5 | `list`, `tuple`, `set`, `frozenset`, and any subclass of one of them (`namedtuple` included; Codex R2 V1-2) | items read with the unbound base iterator (`list.__iter__(value)` and so on, as `cade66080` does), each through `_safe_value(item, depth - 1)`. When any item changes, the result is a new plain base type (`list`, `tuple`, `set` or `frozenset`), never the subclass, so no subclass `repr` runs on a changed value: `Result(issue=ValueError(c))` prints `(ValueError,)`. When no item changes, the value itself |
| 6 | `dict` whose keys all have an exact type of `str`, `int`, `float`, `bool` or `None` | consume the reader’s `changed` flag. Return `dict(pairs)` if true, otherwise return the original dict. Row 6 never reads the store again |
| 7 | `dict` with any other key type (an exception key or a `str` subclass included) | the placeholder |
| 8 | anything else | the value itself (the documented wrapper gap, unchanged) |

Builtin call form (D2). The filter reads containers only in these forms, and test 18 accepts no
other:

- one function, `_safe_pairs(store, depth)`, reads pairs with `dict.items(store)` (an unbound
  call) and is the only reader of mapping items. Row 6, the lone-mapping named values and the
  lone-mapping display all use its result. Nothing calls `dict.get`, `dict.__getitem__` or `in`
  on a caller store, because each of these compares the stored key with `__eq__` (Codex R2 D6:
  `dict.get({K("a"): 7}, "a")` runs `K.__eq__`). `dict.items` does not compare keys;
- row 5 iterates with the unbound base iterator (`list.__iter__(value)`), so a subclass
  `__iter__` never runs;
- key checks use `type(key) in _PLAIN_KEY_TYPES` on the type object, never `isinstance` and never
  a comparison of the key itself;
- "no item changes" is decided with `is`, never `==`, so no caller `__eq__` runs.

Test 18 pins the single `dict.items(store)` call to `_safe_pairs` and checks the unbound base iterators in row 5.

`_safe_pairs(store, depth)` returns `(pairs, plain, changed)` from one traversal:

- `pairs` holds each admitted key and the result of scanning its value once at `depth - 1`.
- `plain` is true when every key has an exact type in `_PLAIN_KEY_TYPES`.
- `changed` starts false. Set it when any admitted value satisfies `scanned is not original`.
  Continue scanning after the first change. Row 7 rejects unsupported keys regardless of this flag.

One `depth` argument feeds both the named values and the display, so the two cannot drift
(Codex R2 V1-1). For the lone mapping the call is `_safe_pairs(store, _ARGS_DEPTH)`: each stored
value is scanned at depth 1 and the items of a plain container value at depth 0, the same depth
a positional argument gets.

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

0. Re-filtering is a no-op (Codex R2 V1-3). When `type(record.args) is _NamedArgs`, `_scrub`
   keeps it unchanged. Its keys and values already came from one filter pass, and an exact type
   check runs no caller code. The engine attaches one filter per handler, so with console and
   file both on, the second handler sees the record the first one rewrote. Without this rule
   `_NamedArgs`, a `dict` subclass, would fall to row 2 and the file would print `<mapping>`
   where the console printed `{'k': 1}`. Positional args need no such rule: rows 1 to 8 return a
   rewritten value unchanged on a second pass, because `_Label` and the placeholder fall to row 8.
   `_NamedArgs` is private; a caller who builds one on purpose is a hostile caller (V2).
1. `_named_args` always returns a `_NamedArgs`, also when `msg` has no `%(name)` field. It never
   turns the lone mapping into a tuple: `"done" % ("<mapping>",)` raises "not all arguments
   converted", while `"done" % {"a": 1}` prints `done`. Stock `%` with a mapping argument ignores
   unused keys, and `_NamedArgs` keeps that.
2. No field inventory (Codex R2 V1-5). The plan no longer reads field names from `msg`. Stock
   logging converts `msg` with `str(msg)` before `%`, so a `PurePath("%(a)d")` msg reads `a`
   (verified: it prints 7 on `cade66080`). A host formatter with `{args[a]}` reads any stored key,
   also one the message does not name. A key set chosen from `msg` would break both. `_NamedArgs`
   holds every safe exact-`str` key instead (step 4), so the msg type does not matter and the
   field parser and its `%%` and nested-parenthesis rules are removed.
3. Find the store without running caller code: the mapping itself when
   `issubclass(type(m), dict)`; `vars(m)["data"]` when `m` is a `UserDict` and that attribute is
   an exact `dict`; otherwise no store.
4. Named values come from the shared traversal (Codex R2 D6): `pairs, plain, changed =
   _safe_pairs(store, _ARGS_DEPTH)`. The `_NamedArgs` keys are the pairs whose key has the exact
   type `str`, with their scanned values. No key is looked up by name, so no stored key's
   `__eq__` or `__hash__` runs. With no store, there are no pairs.
5. A name not in the pairs (absent, stored under a non-plain key, or no store) takes a value-free
   default from one closed table, through `__missing__`: `0` for a `Counter`; `factory()` for a
   `defaultdict` whose factory `is` one of the builtins in `_EMPTY_FACTORIES`;
   `_MAPPING_PLACEHOLDER` for all others. The default is chosen once, from the exact type of the
   caller mapping, and stored on `_NamedArgs` as a constant.
6. `record.args` becomes a `_NamedArgs`: a `dict` subclass holding the safe `str` pairs from
   step 4, the default from step 5, and the display source. It stores no separate reference to the caller mapping. A value at the depth limit
   can refer back to the original mapping, as in the recursive display cell below.
   - `__missing__` returns the stored default.
   - `__bool__` returns True, also with no keys. `LogRecord.getMessage` formats only when
     `self.args` is truthy, so an empty `_NamedArgs` would leave `%%` unformatted.
   - `__str__` and `__repr__` give the display. This is what `%s`, `%r` and a brace `{args}`
     print for the lone mapping (`"x %s" % m` formats the whole mapping). The display source is
     `dict(pairs)` when the mapping is an exact `dict` and `plain` is True, else `None`. Both
     come from the same `_safe_pairs` call as the named values, at the same depth (Codex R2
     V1-1).
   - The display is lazy (Codex R2 V1-4). `__str__` and `__repr__` compute
     `repr(display_source)` when called, never in `_scrub`. A failure there (for example the
     int-to-text limit on `10**5000`) returns `<mapping>` for that one use and does not reach
     `_scrub`, so the `_UNRENDERABLE` fallback never runs for it. A named-only message that does
     not print the whole mapping never calls them, so an unused value cannot drop the line: with
     `"%(a)d"` and `{"a": 7, "unused": 10**5000}` the output is `7`, the same as stock. With
     `None` as the display source, both return `<mapping>`.

Values come from exact-type key checks during one pass over the store. The exception key in
`{"ValueError": 7, ValueError(): 11}` is not a plain key, so it gives no pair, and
`%(ValueError)d` prints 7 from the real `str` key. A `%(x)d` field whose value is the
placeholder raises `TypeError` in `getMessage()`. Logging then reports its standard logging
error with the filtered args, which is the same outcome as a missing key in stock logging.

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
| lone `ChainMap`, `%(a)s` | passed through; the ChainMap's own lookup prints the value | `<mapping>` (no plain store) |
| lone `mappingproxy`, `%(a)s` | passed through; prints the value, or exception text for an exception value | `<mapping>` (no plain store) |
| lone `UserDict`, `%(a)s` with `a` stored | the value, rebuilt as a dict when it changed | the value from the `_safe_pairs` pass over `data` |
| lone plain dict with a `str` subclass key, `%(a)s` naming it | the stored value, found through the key's `__eq__` | `<mapping>` (not a plain key, so no pair; no `__eq__` runs) |
| lone mapping read by a host `{args[a]}` formatter | the stored value | the scanned stored value when `a` is an exact `str` key, else the default |
| lone `UserDict`, `%(missing)s` | `KeyError`, a stock logging error | `<mapping>` |
| lone mapping, `"x %s"` or `"x %r"` | the mapping's own `str` or `repr` | an exact dict with admitted keys prints the repr of its scanned pair copy. Other mappings and rejected keys print `x <mapping>` |
| lone `{b"status": 7}`, `"x %r"` | `x {b'status': 7}` | `x <mapping>` (row 7 rejects bytes keys) |
| lone `d = {}; d["self"] = d`, `"x %r"` | `x {'self': {...}}` | `x {'self': {'self': <nested>}}` (the value at the depth limit is the nested placeholder) |
| host `{args[0]:d}`, msg `"done"`, lone `{0: 7}` | `7` | integer lookup returns the placeholder. Decimal formatting fails and the handler emits no line |
| lone dict with an exception or tuple key, `"failed: %s"` | the key relabelled | `failed: <mapping>` |

On `cade66080` no engine logger call passes a `Counter`, `OrderedDict`, `defaultdict`,
`MappingProxyType` or `ChainMap` directly (grep of logger calls). The builder repeats that check
on the final head with a walk of logger calls and lists any hit in the PR body.

## Acceptance tests

Written first in `tests/unit/safe_output/test_log_filter.py`. Each Codex repro is a red test on
`cade66080`, shown red there before the fix. The canary is the existing `_CANARY`.

Codex R4 repros, red on `cade66080`:

1. `test_partial_factory_exception_is_unreachable`: `defaultdict(functools.partial(f,
   ValueError(_CANARY)))` as a positional arg and as the lone mapping, through an engine handler
   with `%s`, `%r` and `%(missing)s`: no canary. `_reachable` from `record.args` and
   `record.msg` finds neither the exception nor the partial. Two rules for the cells (Codex R2
   D7):
   - The brace cell uses the field `{args[0].default_factory._factory.args[0]}`, which prints the
     canary on `cade66080` (`.default_factory.args[0]` already raises there, so it proves
     nothing). The mapping is truly positional: `args` is `(dd, 1)` with msg `"%s %s"`, so
     `LogRecord` keeps the tuple. Use a fresh record for this brace assertion. Apply the filter exactly once and call
     the brace formatter directly. Require `AttributeError` on the placeholder. The canary
     printed on the first pre-fix pass makes this assertion red. A second pass can mask it.
   - The lone-mapping cell uses a nonempty `defaultdict` (`{"a": 1}` plus the factory).
     `LogRecord` keeps an empty mapping as a one-item tuple, so an empty one would test the
     positional path twice.
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
    `test_clean_non_plain_mapping_is_the_placeholder`. The `dict` case (Codex R2 D8) keeps
    `record.getMessage() == repr(mapping)` and replaces `record.args is mapping` (`:497` on
    `cade66080`; a lone mapping now always becomes a new `_NamedArgs`) with two assertions: the
    caller mapping equals a copy taken before the filter, and a second `filter` call leaves
    `record.args` the same object with the same `getMessage()`. This is a changed expectation, so
    it goes in the 13a table and in the implementation commit.
13a. Existing tests the new rule turns red on purpose (Dennis V1-2). Each is rewritten in the
    same commit as the code change, with the new expected output below. No assertion is dropped
    without a replacement.

    | Test (line on `cade66080`) | Old expectation | New expected output |
    |---|---|---|
    | `test_exception_inside_container_arg_becomes_label[dict_key]` (:259) | `ValueError` in the output | `x <mapping>`, no canary (row 7: exception key) |
    | `test_exception_inside_mapping_arg_container_becomes_label[dict_key]` (:268) | `ValueError` in the output | `x <mapping>`, no canary (the value of `c` is a dict with an exception key) |
    | `test_tuple_key_in_lone_mapping_arg_becomes_label` (:292) | `ValueError` in the output | `failed: <mapping>`, no canary (row 7: tuple key; `_NamedArgs` display string); renamed `test_tuple_key_in_lone_mapping_arg_is_the_placeholder` |
    | `test_mapping_needing_replacement_keeps_missing_lookup` (:321, `defaultdict(lambda: 0, ...)`) | `WARNING ValueError 0` | the field changes to `%(missing)s` and the output is `WARNING ValueError <mapping>` (caller factory, not called). A second cell keeps `%(missing)d` and asserts the stock logging error on stderr, with no canary on stderr and nothing in the handler output |
    | `test_fallback_clears_live_exc_info` (:236, monkeypatches `_scan`) | fallback runs | monkeypatches `_safe_value` instead (`_scan` is removed, and `monkeypatch.setattr` fails on a missing name); assertions unchanged |
    | `test_mapping_with_nothing_to_replace_passes_through[dict]` (:497) | `record.args is mapping` | caller mapping unchanged, and a second filter keeps `record.args` and the message (test 13) |

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
    Two more cells for D3:
    - a plain `dict` whose key is a `str` subclass with a recording `__hash__` and `__eq__`: the
      output is `<mapping>` (row 7) and neither method ran;
    - a plain `list` and a plain `dict` holding an exception next to a caller object whose
      `__eq__` records a call: the exception is relabelled and `__eq__` did not run.
    - Use a lone dict `{K("a"): 7, "b": ValueError(_CANARY)}`. The `str` subclass `K` keeps
      `str.__hash__` and records equality calls. Reset its recorder after construction. With
      `"%(a)s %(b)s"`, require exactly `<mapping> ValueError` and zero recorded calls. M4
      fetches the original exception for the admitted key `"b"` and prints the canary.
    - Exercise row 6 with positional args `(d, 1)` and msg `"%s %d"`. For `d = {"a": 7}`,
      assert the filtered first argument is `d`. For `d = {"a": ValueError(_CANARY)}`, require
      a different dict, exact output `{'a': ValueError} 1`, and the original exception still
      in `d`. Force the reader’s `changed` flag true and false in separate mutations. The
      clean identity assertion and the changed output assertion, respectively, must fail.
16. `test_any_mapping_type_is_value_free` (Hypothesis): nests one and two levels deep built from
    `dict`, `OrderedDict`, `Counter`, `defaultdict` (empty-builtin and caller factories),
    `UserDict`, `mappingproxy`, `ChainMap`, a `ConfigParser` section and a caller `Mapping`, with
    the canary exception planted as a key, a value, a factory bound argument or a factory result.
    Format with `%s`, `%r`, a named field from the generated keys, and a `{`-style formatter over
    `{args}`. Assert no canary, and that `_reachable(record.args)` holds no planted object.
    Depth limits (V1-3), which the strategy follows:
    - positional: `record.args` is scanned at depth 2. Each argument is checked at depth 1 and
      the items of a plain container argument at depth 0.
    - lone mapping: each stored value is scanned at depth 1 and the items of a plain container
      value at depth 0.
    - `msg`: depth 1, so the items of a plain container `msg` are checked at depth 0.
    - At depth 0, rows 1 and 2 still apply, so an exception or a non-plain mapping is planted at
      every level up to depth 0. A plain `list`, `tuple` or `dict` at depth 0 is not opened, so
      the strategy plants nothing inside one. That is the `too_deep` strict xfail cell.
    - One fixed example runs on every run: a `UserDict` holding the canary exception inside a
      positional `list` prints `x [<mapping>]`.
17. `test_named_args_match_stock_output` (reworked for Codex R2 V1-5; the field parser is gone,
    so its parser cells go too). Each cell compares the real formatted output with stock logging
    on a clean plain dict, never a key set alone:
    - a `PurePath("%(a)d")` msg with `{"a": 7}` prints `7`;
    - a host `logging.Formatter("{message} {args[a]}", style="{")` with msg `"done"` and
      `{"a": 7}` prints `done 7`;
    - a key with nested parentheses (`%(a(b))s`) and a `%%(a)s %(b)s` msg print the same as stock;
    - `record.args` has exactly the exact-`str` keys of the store, and none of its non-`str` keys
      (an `int` key cell and a `str` subclass key cell).
19. `test_lone_mapping_keeps_mapping_semantics` (V1-1). The lone mapping goes through an engine
    handler. Check each specified result and assert
    `record.args` is a truthy `_NamedArgs`:
    - no conversions, `"x"` (the msg of test 9) and `"done"`: prints `x` and `done`, no logging
      error;
    - `"100%%"` with lone `{0: 7}`: require zero stored keys in the truthy `_NamedArgs` and
      exactly `100%`. Removing `__bool__` leaves `100%%`;
    - `"x %s"` and `"x %r"` of a clean plain dict `{"k": 1}`: prints `x {'k': 1}`, the same as
      stock;
    - Pin the three deliberate compatibility changes. With `"x %r"`, require exactly
      `x <mapping>` for `{b"status": 7}` and `x {'self': {'self': <nested>}}` for
      `d = {}; d["self"] = d`. With msg `"done"` and lone `{0: 7}`, use a host stream
      handler with a brace-style `{args[0]:d}` formatter. Assert the filtered index lookup
      returns the placeholder, direct formatting raises for the decimal conversion, and the
      handler reports a formatting error with exactly empty output in its destination;
    - `"x %s"` and `"x %r"` of a `Counter`: prints `x <mapping>`;
    - `"x %s"` of a plain dict holding an exception value: prints `x {'k': ValueError}` (the
      label prints bare under `repr`), no canary.
20. `test_lone_mapping_display_scans_to_the_named_depth` (Codex R2 V1-1). The lone mapping
    `{"k": [ValueError(_CANARY)]}` through the engine file handler prints exactly
    `x {'k': [ValueError]}` with `"x %s"` and `"x %r"`, the same as `cade66080`, and a host
    `{`-style formatter over `{args}` prints `{'k': [ValueError]}`. `%(k)s` prints `[ValueError]`.
    No canary in any cell.
21. `test_sequence_subclass_keeps_the_safe_rule` (Codex R2 V1-2). A
    `namedtuple("Result", "issue")(ValueError(_CANARY))` as a positional `%s` argument through
    the engine file handler prints exactly `(ValueError,)`, the same as `cade66080`. Cells for a
    `list` subclass and a `set` subclass with an exception item print `[ValueError]` and
    `{ValueError}`. A clean `namedtuple` is rebuilt as a plain tuple and prints `(1,)`: only an exact builtin returns the original object (security review).
22. `test_two_handlers_print_the_same_record` (Codex R2 V1-3). Two engine handlers built by
    `_new_engine_handler`, one stream and one file, handle the same record in turn. Use a fresh record and empty buffers per cell, with
    message-only formatters. Flush before reading the file. Compare the complete contents of
    **each** destination independently with the expected string.

    | Lone mapping | Message | Expected in each destination |
    |---|---|---|
    | `{"k": 1}` | `"x %s"` and `"x %r"` (separate cells) | `"x {'k': 1}\n"` |
    | `{"k": 1}` | `"%(k)d"` | `"1\n"` |
    | `{"k": ValueError(_CANARY)}` | `"x %s"` and `"x %r"` (separate cells) | `"x {'k': ValueError}\n"` |
    | `{"k": ValueError(_CANARY)}` | `"%(k)s"` | `"ValueError\n"` |

23. `test_unused_value_cannot_drop_a_named_record` (Codex R2 V1-4). The lone mapping
    `{"a": 7, "unused": 10**5000}` with `"%(a)d"` prints `7`, the same as stock logging, and not
    `_UNRENDERABLE`. The same mapping with `"x %s"` prints `x <mapping>` and the line is not
    dropped.
18. `test_filter_builds_only_closed_types` (sentry, same file, because it guards one module): an
    AST walk of `_log_filter.py` finds no call to `OrderedDict`, `Counter`, `defaultdict`,
    `UserDict`, `copy` or `type(...)(...)`, no attribute read of `default_factory`, and no
    `items` read except the single direct `dict.items(store)` call whose enclosing function is
    `_safe_pairs`. Require exactly one site in the module. Allow `__iter__` only on the four
    base sequence types. Reject reads of `get`, `keys` and `values`, and reject `isinstance`
    in `_safe_value`.
    - Comparisons (Codex R2 V2-LOG): the check is narrowed to caller values. An `==` or `!=` is
      allowed only when one side is an `int` constant (`depth == 0`); any other `==` or `!=` in
      `_safe_value`, `_safe_pairs` or `_named_args` fails it.
    - Import aliases (recurring defect 5): constructor names are resolved through the module's
      imports, so `collections.OrderedDict(...)`, `from collections import OrderedDict as OD`
      then `OD(...)`, and `import collections as c` then `c.defaultdict(...)` all count.
    - Seeds, each in a scratch copy and each red: a bare `defaultdict(...)` call, each alias
      spelling above, a `store.get(...)` read, and a `value == other` comparison. Insert a second
      `dict.items(store)` site outside `_safe_pairs` while keeping the original. Test 18 must
      flag the added site by function and line.

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
| M4 | read a named field with `dict.get(store, name)` (or `mapping[name]`) instead of taking it from the `_safe_pairs` result | 15 (the raw value for admitted key `"b"` prints the canary instead of `ValueError`) |
| M5 | change the dispatch decision that admits a subclass (Codex R2 D7): row 2 no longer catches a `dict` subclass, and row 6 accepts it (`isinstance(value, dict)` in both places). Changing row 6 alone is inert, because row 2 runs first | 3, 13, 16 |
| M6 | keep a reference to the caller mapping on `_NamedArgs` | 1, 16 |
| M7 | make the placeholder's `repr` call the caller object's `repr` | 1, 4, 16 |
| M8 | copy a non-exact-`str` key (an `int` key or a `str` subclass key) and its value into `_NamedArgs` | 15, 17 (non-`str` key cells) |
| M9 | drop the `Counter` row of the default table | 10 |
| M10 | one route bypasses the factory (Codex R2 D7): the file handler at `internal/logging.py:145`, or the fallback console at `:165`, is built directly as a `logging` handler without the filter. The guard is extended to configure console, file (under `tmp_path`) and the fallback console, and to walk every handler on the engine logger | `test_every_engine_handler_carries_the_filter` (extended), 4 |
| M11 | key check with `isinstance(key, (str, int, float, bool, type(None)))` instead of the exact type | 15 (`str` subclass key cell) |
| M12 | decide "no item changes" with `==` instead of `is` | 15 (recording `__eq__` cell) |
| M13 | (replaces the retired parser mutation) `_NamedArgs` keeps only the fields named in a `str` msg | 17 (`PurePath` and host `{args[a]}` cells) |
| M14 | lone mapping with no fields becomes a one-item tuple | 19 (`"done"`, `"x"` cells) |
| M15 | `_NamedArgs.__bool__` removed, so an empty one is falsy | 19 (`100%%` with nonempty `{0: 7}` and zero admitted names) |
| M16 | rows 1 and 2 moved after the depth check | 16 (fixed cell: a `UserDict` holding the canary exception inside a positional `list`, at depth 0) |
| M17 | reduce the display depth alone: the display uses `_safe_pairs(store, _ARGS_DEPTH - 1)` while the named values keep `_ARGS_DEPTH` (Codex R2 V1-1) | 20 |
| M18 | row 5 returns a changed subclass as the subclass (`type(value)(new)`), or passes sequence subclasses through to row 8 (Codex R2 V1-2) | 21 |
| M19 | remove the `type(record.args) is _NamedArgs` keep rule in `_scrub` (Codex R2 V1-3) | 13, 22 |
| M20 | compute `repr(display_source)` in `_scrub` instead of in `__str__` and `__repr__` (Codex R2 V1-4) | 23 |

## Failure modes

| Failure | Detection | Response |
|---|---|---|
| a new mapping type appears | it is not an exact plain type, so it gets the placeholder | none needed |
| a log line that printed a clean `Counter` now prints `<mapping>` | the builder's walk of logger calls; the PR body list | pass `dict(counter)` at the call site |
| a named field's value is the placeholder under `%d` | stock logging error with filtered args | the call site passes a plain dict |
| the display `repr` fails on a stored value (for example the int-to-text limit) | test 23 | that one `%s` or `%r` prints `<mapping>`; named fields still print |
| a second filter on the same record | test 22 | the exact-type keep rule returns the `_NamedArgs` unchanged |

## Design notes

No new structure. The change removes the lookup machinery and replaces many type cases with one
table (open/closed: a new mapping type needs no new code). Each fact has one place: the type
table in `_safe_value`, the one pair reader `_safe_pairs` (row 6, named values and display all
take its result, so their depth cannot differ), the default table in `_named_args`, the
placeholder constant.

## Placement and size

| Existing file | Placement |
|---|---|
| `src/decoy_engine/safe_output/_log_filter.py` | Filter, pair reader and display policy |
| `tests/unit/safe_output/test_log_filter.py` | Output, identity and single-reader guard tests |

No new files. `_log_filter.py` loses `_Lookup`, `_ScannedFactory` and the rebuild code, and gains
`_safe_value`, `_safe_pairs`, `_named_args`, `_NamedArgs` and the placeholder. Expected: about
-50 net source lines, about +220 and -90 test lines. No new public names. Tests stay in
`tests/unit/safe_output/test_log_filter.py`.

## Test depth

T0 on `test_log_filter.py` per edit. T1 per commit: `tests/unit/safe_output/`,
`tests/sentry/test_log_interpolation.py`, the logging config tests that import
`_new_engine_handler`, ruff check, ruff format and mypy on changed files. No full-suite trigger
applies (no shared fixture, schema, lock or frozen contract change).

Commit order (Codex R2 D8):

1. Write the new and rewritten tests first. Run them on `cade66080` and record each red run (test
   id and failing assertion) in the PR body. Tests 20 and 21 pin current output, so they are
   green there; record that too. Record mixed tests by cell. Capture the old outputs from
   the three compatibility rows in test 19, and the first-pass brace leak in test 1.
   For preservation cells that already pass, show red with the named mutation. Seed both
   row 6 flag errors and the duplicate reader before accepting tests 15 and 18. Repeat these
   seeds with M1–M20 on the final implementation head.
2. Commit the implementation together with every changed expectation in the 13a table, so each
   commit is green and no assertion is weakened or dropped on its own. No pin, cap or baseline
   moves.
3. On the final recorded head, run T1 and every mutation M1 to M20, and record the head next to
   each result (recurring defect 9). A code change after that run voids it.

## Docs and changelog

The `_log_filter.py` module docstring gets the type table, the one pair reader, the re-filter
keep rule, the lazy display and the named-lookup rule in place of the current mapping text. The gap list drops "a mapping type other than dict and `UserDict`". The
CHANGELOG line says a non-plain mapping argument prints `<mapping>` in engine logs.

## V2-LOG (deferred)

- Collect the AST guard seed failures and final-HEAD mutation evidence at implementation.
  Keep the reviewed branch’s live interpolation allowlist and recorded baseline empty.
- Wrapper objects whose `__str__` or `__repr__` formats an exception: unchanged gap, guarded at
  call sites by `test_log_interpolation.py`.
- A caller `defaultdict` factory that is value-free in practice (for example `lambda: 0`) gives
  `<mapping>` for a missing named field. Accepted.
