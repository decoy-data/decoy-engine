# F31 AE3 plan amendment: one closed rule for log arguments

Status: plan

Rules consulted: README routing table, 00-universal, risk-and-exceptions, development-loop (PLAN,
REMEDIATE three-round stop), cross-cutting-concerns, testing (test depth), security,
catalogs/recurring-defects.

Amends: `2026-11-24-f31-audit.md`, Part 2, Behavior item 4 (`SafeRecordFilter`) and slice AE3.
PR: decoy-engine #809, head `cade66080`. The PR reached the 3-round review cap (Codex R4 NO-GO),
so the plan changes before more code. Risk stays R2 (privacy logic).

Code head this revision is checked against: `9e63c1510`. Line numbers marked `@9e63c151` are
read from that head; unmarked line numbers are from `cade66080`.

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

Dennis plan review, gate round 1 on head `9e63c1510` (GO-WITH-FIXES). The plan had drifted from
the code. This revision describes the code at that head, row by row, and names the three changes
still required: a bound method becomes `<object>` (C1), an `int` or `float` enum member is copied
to its base (C2), and the guard checks every function the table calls (C3, test code only).

| Finding | Plan change |
|---|---|
| HIGH-1 drift | Choke point table rewritten to the head's rows 1 to 13 (`<object>`, `<nested>`, record classes, `_SCALAR_LIKE`, number copies, enums, `deque`, views, `slice`); behavior rows B1 to B13; tests 24 to 33 name the head's tests and the new cells; mutations M21 to M34; Placement lists every file; the logger-call walk covers every argument and `extra=` value, not five mapping types; the `wrapper_str` and `too_deep` strict xfails are retired (Decision 5) |
| HIGH-2 `extra=` | `extra=` attributes added to the guarantee, Fields, Output surfaces and class table row 1; tests 25 and 26 (JSON-style formatter); mutations M30 and M31 |
| MEDIUM-1 guard | test 18 ships in #809. It is on the head at `tests/sentry/safe_output/test_log_filter_closed_types.py`, not under `tests/unit/`, which is why the review did not find it. Its seeds, alias rules and the widened checked-function list (C3) are stated at test 18; the V2-LOG line that read as a deferral is removed |
| MEDIUM-2 rows | rows B10, B11 and B12, test 32, M32, and the widened walk |
| LOW-1 | step 5 names the `vars(defaultdict)["default_factory"].__get__` read and lists `_EMPTY_FACTORIES` |
| LOW-2 | the guarantee says `type(value)`, with `issubclass` on the type object, never `isinstance` |
| LOW-3 | step 3: a `UserDict` with no `__dict__` gives no store (the head catches `TypeError`); a hostile `__getattribute__` is V2 |
| LOW-4 | commit order: the red runs on `cade66080` are scratch runs, never committed as red tests or strict xfails |
| LOW-5 | test 18 moved into order; the `str` subclass row runs before the depth check on purpose (row 5, test 31, M33) |
| LOW clean code | V2-LOG: a row table with named predicates for `_safe_value` |

## Defect class

**Open-ended reconstruction of caller objects.** The filter tries to keep each caller mapping
type's behavior (its factory, its key equality, its order, its lazy lookup) while it removes
exceptions. Each behavior it keeps is caller state or caller code that a formatter can reach.
Each behavior it drops changes the output. A new mapping type or behavior is a new case, so the
case list never closes. In the audit plan's class table this is class 1 (value-bearing output)
reached through class 6 (untrusted producer).

## Guarantee and non-goals

Guarantee, inside the scan depth only:

- The scan reaches `record.msg` and one container level inside it, each positional argument
  (or each value of a lone mapping) and one container level inside it, and each attribute a
  caller adds with `extra=` and one container level inside it (HIGH-2).
- At every position the scan reaches, a caller exception becomes its label, a non-plain
  mapping becomes `<mapping>`, and any object with no row in the table becomes `<object>` or
  `<nested>`. A plain container at the depth limit becomes `<nested>`, so no value passes
  unread below the limit. No reference to a replaced object stays in what the filter writes
  back.
- For each value it inspects, the filter reads `type(value)` and decides with `is` against a
  builtin type or with `issubclass` on that type object, never with `isinstance` (LOW-2). It
  calls only the builtin methods named under Choke point (`dict.items`; the unbound `__iter__`
  of `list`, `tuple`, `set`, `frozenset`, `deque` and the three dict views; the unbound
  `__pos__` of `int`, `float` and `complex`; and `str.__str__`). It calls
  no `__getitem__`, `__missing__`, `__iter__`, `items`, `__eq__`, `__hash__`, `__repr__` or
  factory of a caller type, and no key lookup on a caller store.
- A value the filter returns unchanged is an exact builtin scalar, an exact `_SCALAR_LIKE`
  type, or an exact builtin container whose items all came back unchanged. Every subclass is
  copied, rebuilt or replaced, so no caller `__repr__` or `__str__` runs when a handler prints.
- Named `%(name)` lookups on a lone mapping whose items are in a plain `dict` (the mapping
  itself, or a `UserDict`'s `data`) keep their stored values when the key is an exact `str`,
  whatever the `msg` type and whatever reads them (`%`, or a host `{args[a]}` formatter).
- Each output surface of one record prints the same, on every handler, after any number of
  filter passes.

Caller metaclasses that change `issubclass` or class attribute reads, and a caller `tzinfo` or
other component held inside an exact `_SCALAR_LIKE` value, are outside the guarantee (V2).

Non-goals, from the audit plan: pre-formatted text in `msg`, `exc.args` passed as an argument,
hostile objects (V2). Two audit-plan non-goals are now covered by the code and leave the list
(Decision 5): a wrapper object whose `__str__` formats an exception prints `<object>` at every
position the scan reaches, and a value deeper than the scan depth is behind a `<nested>`
placeholder. Text a wrapper already formatted into `msg` stays a non-goal under "pre-formatted
text". A finding outside this guarantee is a follow-up item, not a blocker for #809.

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
| 1 | value-bearing output | yes: `msg`, `args`, `exc_info`, `exc_text` and `extra=` attributes | the closed exact-type table in `_safe_value`; `<mapping>` for every non-plain mapping; `<object>` and `<nested>` for every value with no row; the `extra=` loop in `_scrub` | tests 1 to 4, 16 (seeded canary through stream and file handlers), 24, 25, 26 | M1, M2, M7, M21 to M31 |
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

Read from `cade66080` and checked again on `9e63c151`.

### Exit paths

- Normal: `_scrub` returns and `filter` returns True (`src/decoy_engine/safe_output/_log_filter.py:267`,
  `:438@9e63c151`).
- Any exception in `_scrub`: the fallback writes constants only and returns True
  (`src/decoy_engine/safe_output/_log_filter.py:270`, `:430-437@9e63c151`). The new code adds
  no other exit.
- At `9e63c151` the fallback (`_log_filter.py:430-437@9e63c151`) also sets every `extra=`
  attribute to `_UNRENDERABLE`, because the attribute that failed may hold the value (test 25,
  M31).

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
- Every other record attribute (HIGH-2). `_STANDARD_FIELDS` is computed once from
  `vars(logging.makeLogRecord({}))` plus `message` and `asctime` (`_log_filter.py:171@9e63c151`),
  so it follows the running Python's own field list (`taskName` on 3.12). Any attribute outside
  it and outside `_decoy_safe_exc_text` came from `extra=` or a host filter, and goes through
  `_safe_value(value, 1)`, the `msg` depth (`_log_filter.py:405-408@9e63c151`).
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
- At `9e63c151` all of these are written in `_scrub` (`_log_filter.py:395-417@9e63c151`): `msg`
  at `:396`, `args` at `:399-404`, `extra=` attributes at `:405-408`, the traceback at `:410-417`.
- Brace-style formatter fields over the record (`{args[0].x}`): reach only what `args` holds.
- `extra=` attributes (HIGH-2): a `%(err)s` field in a host format string, or a JSON-style
  formatter that dumps `record.__dict__`, prints them. `logger.info("x", extra={"err": exc})`
  prints the exception text on stock logging. After the filter each one holds what
  `_safe_value(value, 1)` returned.
- `stack_info`: code locations and engine source lines, kept.

## Reuse inventory

- `safe_error_type` and `_label` for exception labels (unchanged).
- `_safe_traceback`, `_chain`, `_frames` for `exc_info` (unchanged).
- The existing `_reachable` test helper and `_CANARY`.
- The call-site sentry `tests/sentry/test_log_interpolation.py` for the documented gaps.
- `tests/sentry/_platform_ast.py` `import_map` and `resolve` for test 18's alias rules, so the
  guard reuses the repo's normalizer instead of a copy (recurring defect 5).
- No new registry. Test 18 is an AST check of one file, in
  `tests/sentry/safe_output/test_log_filter_closed_types.py` beside the existing
  `test_exception_text_copy.py`.

## Frozen contracts touched

None. `SafeRecordFilter` is public in `decoy_engine.safe_output`; its name, constructor and
`filter` signature stay the same. The printed text for a non-plain mapping changes (Behavior
changes table), which is log output, not a frozen contract.

## Slices

One slice: the rest of AE3 on PR #809, in decoy-engine, branch `feat/f31-ae3`. From
`9e63c151` the remaining work is C1 and C2 (about +3 and -3 source lines in `_log_filter.py`),
C3 (about +10 lines in the guard), and the new tests 26, 32 and 33 plus the new cells of 24 and
28 (about +120 test lines). Sizes per file are under Placement. No other slice depends on this
change.

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
6. A wrapper object formats an exception: `<object>` (row 13), test 24 `wrapper` cell, M22.
   A bound method of a dataclass prints the instance's `repr`: C1, test 24 `bound_method`
   cell, M34.
7. A route builds a handler outside `_new_engine_handler`: the extended
   `test_every_engine_handler_carries_the_filter`, M10.
8. Two handlers print one record differently: test 22, mutation M19.
9. An unused value fails the whole record: test 23, mutation M20.
10. An `extra=` attribute carries exception text to a `%(err)s` field or a JSON formatter:
    tests 25 and 26, M30. A failed scrub keeps the raw `extra=` value: test 25, M31.
11. A deny-by-default row breaks a `%d` field (an `IntEnum` or a numpy integer becomes a
    label): C2 for `int` and `float` enums, row B9 and the walk for the rest.

## Choke point

One closed type table, `_safe_value(value, depth)` with its tail `_other_value(value)`, in
`safe_output/_log_filter.py`. Every value the filter writes back to `record.msg`,
`record.args` or an `extra=` attribute comes from it. It reads `type(value)` once and decides
with `is` or with `issubclass` on the type object, never with `isinstance`, and it runs no
caller code.

Rows are checked in this order, as on `9e63c151` (`_log_filter.py:224-289@9e63c151`). The first
match wins. Rows 1 to 5 come before the depth check, so an exception, a record class, a
non-plain mapping or a `str` subclass is handled the same way at every position, depth 0
included.

| # | Input (exact type unless stated) | Output |
|---|---|---|
| 1 | any `BaseException` subclass | its closed type label (`_label`, as today) |
| 2 | a dataclass or attrs class: `__dataclass_fields__` or `__attrs_attrs__` is set on the type | `<object>`. A record class prints every field in its `repr`, and this row runs before rows 3 to 12, so a dataclass that is also a `tuple` subclass is not opened |
| 3 | any mapping that is not an exact `dict`: `issubclass(type(value), collections.abc.Mapping)` or a `UserDict` subclass. This covers dict subclasses, `OrderedDict`, `Counter`, `defaultdict`, `UserDict`, `mappingproxy`, `ChainMap`, `ConfigParser` sections and caller mapping classes | `<mapping>` |
| 4 | `_Label`, or an exact `_PLAIN_VALUE_TYPES` type: `str`, `bytes`, `bytearray`, `int`, `float`, `complex`, `bool`, `range`, `array.array`, `None` | the value itself |
| 5 | a `str` subclass other than `_Label` (Codex R1 V1; LOW-5: before the depth check) | `str.__str__(value)`, a plain copy, so its own `__str__` and `__repr__` never run. A `StrEnum` member takes this row and prints its value, as stock `%s` does |
| 6 | at `depth == 0`: an exact `dict`, a `slice`, or a subclass of `list`, `tuple`, `set`, `frozenset`, `deque` or a dict view | `<nested>`; any other value at depth 0 goes to rows 11 to 13 (`_other_value`) |
| 7 | `list`, `tuple`, `set`, `frozenset`, and any subclass of one of them (`namedtuple` included; Codex R2 V1-2) | items read with the unbound base iterator, each through `_safe_value(item, depth - 1)`. An exact base type with no changed item returns the value itself. Anything else (a changed item, or any subclass) becomes a new plain base type, never the subclass: `Result(issue=ValueError(c))` prints `(ValueError,)` and a clean `namedtuple` prints `(1,)` |
| 8 | `deque`, `dict_keys`, `dict_values`, `dict_items` (or a subclass) | a new `list` of the items, read with the base type's unbound `__iter__`, each through `_safe_value(item, depth - 1)`. A `dict_items` pair is a tuple one level down, so at `args` depth it prints `[<nested>]` |
| 9 | exact `slice` | `start`, `stop` and `step` each through `_safe_value(part, depth - 1)`; the value itself when none changes, else a new `slice` |
| 10 | exact `dict` | `_safe_pairs(value, depth)`: `<mapping>` when any key is not an exact `_PLAIN_KEY_TYPES` type (`str`, `int`, `float`, `bool`, `None`); else `dict(pairs)` when `changed`, else the value itself. Row 10 never reads the store again |
| 11 | exact `_SCALAR_LIKE` type: `PurePosixPath`, `PureWindowsPath`, `PosixPath`, `WindowsPath`, `Decimal`, `date`, `datetime`, `time`, `timedelta`, `UUID`, `type`, `ABCMeta`, `FunctionType`, `BuiltinFunctionType`, `None`, `Ellipsis`, `NotImplemented` | the value itself. C1 removes `MethodType` from this list (below) |
| 12 | a subclass of `int`, `float` or `complex`; an `enum.Enum` member | a number subclass is copied to its base with the unbound `__pos__` (`int.__pos__(value)`). C2 puts this check before the enum check, so an `IntEnum` or `IntFlag` member prints as its number, as stock `%s` and `%d` do. Any other enum member becomes the label `Class.NAME`, built from `type(value).__name__` and `vars(value)["_name_"]`; a member with no `_name_` is `<object>` |
| 13 | anything else | `<nested>` when `issubclass(type(value), collections.abc.Iterable)` (a generator, a caller class with `__iter__`, an array library's object; it is never iterated, so nothing is drained and no caller `__iter__` runs), else `<object>` (a `SimpleNamespace`, `argparse.Namespace`, `functools.partial`, a wrapper object, a caller class). This is the deny-by-default row that replaces the old "anything else passes" row |

Required code changes, each pinned by a test and a mutation:

- C1. Remove `types.MethodType` from `_SCALAR_LIKE`. A bound method's `repr` is
  `<bound method C.f of {repr(instance)}>`, so `holder.method` for a dataclass holding an
  exception prints the exception text through the dataclass `repr`. With C1 it falls to row 13
  and prints `<object>`. `BuiltinFunctionType` stays: a builtin method's `repr` names the
  instance's type and address, not its `repr`. Test 24 `bound_method` cell, M34.
- C2. In `_other_value`, check `_NUMBER_COPIES` before `enum.Enum`. On `9e63c151` an `IntEnum`
  argument becomes the label `Color.RED`, so a `%d` field raises `TypeError` and the line is
  lost. Copying to the base number prints `1` under `%s` and `%d`, which is what stock logging
  prints on Python 3.11 and later. Test 28 `int_enum` cell, M28.
- C3. Test 18's checked-function list `_CHECKED` grows from `_safe_value`, `_safe_pairs` and
  `_named_args` to every function the table calls: `_other_value`, `_is_container`,
  `_is_exact`, `_is_record_class` and `_default_for`. The `isinstance` ban, now applied to
  `_safe_value` alone (`test_log_filter_closed_types.py:50`), moves to the whole `_CHECKED` list,
  so the `isinstance`, `==` and membership rules cover the whole table. The code at `9e63c151`
  already passes the wider list; C3 changes test code only. Two new seeds prove it:
  `isinstance(value, enum.Enum)` inserted in `_other_value` and `kind == dict` inserted in
  `_is_container` must each be flagged by function name.

Builtin call form (D2). The filter reads containers only in these forms, and test 18 accepts no
other:

- one function, `_safe_pairs(store, depth)`, reads pairs with `dict.items(store)` (an unbound
  call) and is the only reader of mapping items. Row 10, the lone-mapping named values and the
  lone-mapping display all use its result. Nothing calls `dict.get`, `dict.__getitem__` or `in`
  on a caller store, because each of these compares the stored key with `__eq__` (Codex R2 D6:
  `dict.get({K("a"): 7}, "a")` runs `K.__eq__`). `dict.items` does not compare keys;
- rows 7 and 8 iterate with the unbound base iterator (`list.__iter__(value)`,
  `deque.__iter__(value)`, `_KEYS_VIEW.__iter__(value)` and so on, from the `_SEQUENCES` and
  `_ITERABLES` tables), so a subclass `__iter__` never runs. Row 13 never iterates;
- row 12 reads an enum member's name with `vars(value)["_name_"]` and copies a number with the
  unbound `int.__pos__`, `float.__pos__` or `complex.__pos__`, so no caller `__index__`,
  `__int__` or `__repr__` runs;
- key checks use `type(key) in _PLAIN_KEY_TYPES` on the type object, never `isinstance` and never
  a comparison of the key itself;
- "no item changes" is decided with `is`, never `==`, so no caller `__eq__` runs.

Test 18 pins the single `dict.items(store)` call to `_safe_pairs` and allows `__iter__` only on
the eight base names in rows 7 and 8 (`list`, `tuple`, `set`, `frozenset`, `deque`,
`_KEYS_VIEW`, `_VALUES_VIEW`, `_ITEMS_VIEW`).

`_safe_pairs(store, depth)` returns `(pairs, plain, changed)` from one traversal:

- `pairs` holds each admitted key and the result of scanning its value once at `depth - 1`.
- `plain` is true when every key has an exact type in `_PLAIN_KEY_TYPES`.
- `changed` starts false. Set it when any admitted value satisfies `scanned is not original`.
  Continue scanning after the first change. Row 10 rejects unsupported keys regardless of this flag.

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
   `frozenset`, `dict`, `slice`, the base number types (through `__pos__`), plain `str`,
   `_Label` and `_NamedArgs` (below). The `OrderedDict`, `Counter` and `defaultdict` rebuilds
   and `_ScannedFactory` go away, and the order question goes with them.
4. `msg` and each `extra=` attribute go through the same table at depth 1. A `UserDict` or other
   non-plain mapping used as `msg` prints `<mapping>`.
5. Deny by default (Dennis gate R1 HIGH-1). Row 13 replaces the old "anything else is the value
   itself" row. The Sentry serializer's shape (one fallback for unknown types) now applies to
   every object, not only to mappings, and its fallback is a fixed placeholder, never `repr`.
   This closes two audit-plan gaps:
   - `wrapper_str`. A wrapper object whose `__str__` formats an exception prints `<object>` at
     every position the scan reaches. The strict xfail cell is retired, not kept: it would
     XPASS and fail the strict run. It became the passing `wrapper` cell of test 24 (removed in
     `dab48dd1e`). The call-site sentry `test_log_interpolation.py` stays for text a wrapper
     already formatted into `msg`.
   - `too_deep`. A plain container at depth 0 becomes `<nested>` (row 6), so nothing passes
     unread below the limit. The strict xfail cell was retired in `a6f97b5c5` and replaced by
     test 30.
   - The `exc_args` and pre-formatted-text strict xfails stay. `exc.args` is a tuple of plain
     `str`, and pre-formatted text is a plain `str`, so row 4 passes both and they still fail
     strictly on `9e63c151` (recurring defect 7: the builder records the strict-xfail result on
     the final head).
6. Only an exact type returns the original object (security review on `7c82db97d`). A subclass
   of a scalar, a `_SCALAR_LIKE` type, a sequence or a mapping is copied, rebuilt or replaced,
   because a subclass may override `__repr__`.

### Named lookups (`%(name)s`)

`LogRecord` sets `record.args` to the mapping itself when the only argument is a non-empty
mapping. Named lookups must keep working for that case. One function, `_named_args(msg, mapping)`,
handles it, and `_scrub` calls it only for that case:

0. Re-filtering is a no-op (Codex R2 V1-3). When `type(record.args) is _NamedArgs`, `_scrub`
   keeps it unchanged. Its keys and values already came from one filter pass, and an exact type
   check runs no caller code. The engine attaches one filter per handler, so with console and
   file both on, the second handler sees the record the first one rewrote. Without this rule
   `_NamedArgs`, a `dict` subclass, would fall to row 3 and the file would print `<mapping>`
   where the console printed `{'k': 1}`. Positional args need no such rule: rows 1 to 13 return a
   rewritten value unchanged on a second pass, because `_Label` and every placeholder take row 4.
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
   an exact `dict`; otherwise no store. A `UserDict` subclass with `__slots__` and no `__dict__`
   makes `vars(m)` raise `TypeError`, and a missing `data` raises `KeyError`. `_named_args`
   catches both and takes "no store" (`_log_filter.py:345-348@9e63c151`), so the record prints
   `<mapping>` instead of going to the `_UNRENDERABLE` fallback (LOW-3). A subclass with its own
   `__getattribute__` is not reached by `vars`, which reads the instance `__dict__` slot
   directly; a caller metaclass or a `__dict__` descriptor is hostile code (V2).
4. Named values come from the shared traversal (Codex R2 D6): `pairs, plain, changed =
   _safe_pairs(store, _ARGS_DEPTH)`. The `_NamedArgs` keys are the pairs whose key has the exact
   type `str`, with their scanned values. No key is looked up by name, so no stored key's
   `__eq__` or `__hash__` runs. With no store, there are no pairs.
5. A name not in the pairs (absent, stored under a non-plain key, or no store) takes a value-free
   default from one closed table, through `__missing__`: `0` for a `Counter`; `factory()` for a
   `defaultdict` whose factory `is` one of the builtins in `_EMPTY_FACTORIES`;
   `_MAPPING_PLACEHOLDER` for all others. The default is chosen once, from the exact type of the
   caller mapping, and stored on `_NamedArgs` as a constant (`_default_for`,
   `_log_filter.py:326-336@9e63c151`).
   - The factory is read as `vars(defaultdict)["default_factory"].__get__(mapping)` (LOW-1): the
     C-level member descriptor taken from the `defaultdict` class itself, so a subclass
     attribute or `__getattribute__` cannot run, and test 18's ban on a `.default_factory`
     attribute read still holds. Only an exact `defaultdict` gets this far.
   - `_EMPTY_FACTORIES` (`_log_filter.py:153@9e63c151`) holds `int`, `float`, `complex`, `bool`,
     `str`, `bytes`, `list`, `tuple`, `dict`, `set` and `frozenset`. Each builds an empty value
     with no caller input. Membership is decided with `is`, never `==`.
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
| lone `{b"status": 7}`, `"x %r"` | `x {b'status': 7}` | `x <mapping>` (row 10 rejects bytes keys) |
| lone `d = {}; d["self"] = d`, `"x %r"` | `x {'self': {...}}` | `x {'self': {'self': <nested>}}` (the value at the depth limit is the nested placeholder) |
| host `{args[0]:d}`, msg `"done"`, lone `{0: 7}` | `7` | integer lookup returns the placeholder. Decimal formatting fails and the handler emits no line |
| lone dict with an exception or tuple key, `"failed: %s"` | the key relabelled | `failed: <mapping>` |

### Behavior changes from the deny-by-default table (`9e63c151`, with C1 and C2)

Each row names the table row from Choke point that causes it, the test that pins it and the
mutation that makes the row inert. "Stock" is what Python 3.11 and later logging prints with no
filter.

| # | Input | Stock / `cade66080` | After | Row | Test | Mutation |
|---|---|---|---|---|---|---|
| B1 | an object with no row: `SimpleNamespace`, `argparse.Namespace`, `functools.partial`, a wrapper whose `__str__` formats an exception, a bound method (C1), a caller class | its own `repr` or `str`, which may print exception text | `<object>` | 13 | 24 | M22, M34 |
| B2 | an iterable with no row: a generator, a caller class with `__iter__`, a numpy array, a pandas or Polars object | its own `repr` | `<nested>`, never iterated, so a generator is not drained | 13 | 24, 29 | M23 |
| B3 | a plain `list`, `tuple`, `set`, `frozenset` or `dict` at depth 0 (`[[x]]` positional, `{"k": [[x]]}` lone) | its `repr` | `<nested>` | 6 | 30 | M26 |
| B4 | a dataclass or attrs instance, at any position | its `repr`, every field | `<object>` | 2 | 24, 28 (`record_tuple`) | M21 |
| B5 | a `deque`, `dict_keys`, `dict_values` or `dict_items` | `deque([...])`, `dict_keys([...])` | a plain list: `[ValueError]`; a `dict_items` pair prints `[<nested>]` | 8 | 24 | M24 |
| B6 | a `slice` holding an exception | its `repr` with exception text | `slice(ValueError, None, None)`; a clean slice is returned as itself | 9 | 24 | M25 |
| B7 | a subclass of `int`, `float` or `complex` (`numpy.float64` included, an `IntEnum` or `IntFlag` member after C2) | the subclass's own `repr` and `str` | the base number: `5`, `1.5`, and `1` for `Color.RED` under `%s`, `%d` and `%r` | 12 | 28 (`int_sub`, `int_enum`, `int_flag`), 33 | M28, M29 |
| B8 | a subclass of a `_SCALAR_LIKE` type (a `Path` or `Decimal` subclass); a `str` subclass | own `repr` | `<object>`; a `str` subclass is a plain `str` copy | 11, 5 | 28, 31 | M27, M33 |
| B9 | a number type with no row: `numpy.int64`, `fractions.Fraction`, a caller `numbers.Number` | prints the number; `%d` works | `<object>`. Under `%d` `getMessage()` raises `TypeError` and logging reports its standard error, so the line is lost | 13 | 24 (`numpy_int` cell when numpy is installed, `fraction` cell always) | M22 |
| B10 | a positional exact `dict` with a clean key whose type is not in `_PLAIN_KEY_TYPES`: a tuple, `bytes`, `frozenset`, `IntEnum` or `StrEnum` key | its `repr` | `<mapping>` (keys are never rewritten, Decision 2) | 10 | 32 | M32 |
| B11 | a lone plain `dict` with a `%(missing)s` field | `KeyError`; logging reports its standard error and prints no line | `<mapping>` in the line, with no logging error. A visible placeholder is chosen over a dropped line | `_NamedArgs.__missing__` | 32 | M32 |
| B12 | an enum member: plain `Enum`, `StrEnum`, `IntEnum` (C2) | `%s` prints `Color.RED`, the `StrEnum` value or `1`; `%r` prints `<Color.RED: 1>` | plain `Enum`: `Color.RED` under `%s` and `%r`, built from `vars(value)["_name_"]`; `StrEnum`: its value as a plain `str` (row 5); `IntEnum`: `1` (C2). A caller `__str__` or `__repr__` on the enum never runs | 12, 5 | 28 (`enum`, `str_enum`, `int_enum`) | M28 |
| B13 | an `extra=` attribute: `extra={"err": exc}` | a `%(err)s` field or a JSON formatter prints the exception text | the attribute holds what `_safe_value(value, 1)` returned: `ValueError`, `<mapping>`, `<object>`; on a failed scrub every `extra=` attribute is `_UNRENDERABLE` | `_scrub` extras loop | 25, 26 | M30, M31 |

B9 and B10 can change real engine log lines, so the logger-call walk below lists them.

### Logger-call walk

On `cade66080` no engine logger call passed a `Counter`, `OrderedDict`, `defaultdict`,
`MappingProxyType` or `ChainMap` directly (grep of logger calls). That check is too narrow for
the deny-by-default table, so the builder replaces it with a walk on the final head:

- Parse every `.py` file under `src/decoy_engine/` with `ast` and find each call whose function
  is an attribute named `debug`, `info`, `warning`, `error`, `exception`, `critical` or `log`
  on any receiver (about 88 call sites by text search on `9e63c151`). A text grep alone is not
  the walk (cross-cutting concerns: enumerate with a walk).
- For each call, list every positional argument after the message and every `extra=` value
  that is not a literal `str`, `int`, `float`, `bool` or `None` constant, with its file, line
  and the type it holds at run time, read from the code.
- Flag each listed argument whose type falls in B1, B2, B5, B7, B8, B9, B10 or B12, or any
  argument used under `%d`, `%i` or `%x` whose type is not an exact `int`, `float` or `bool`.
- Prove the walk before trusting it: in a scratch copy, add one call that passes a
  `SimpleNamespace` and one that passes `numpy.int64(1)` under `%d`, and show both are flagged.
- Each flagged call is fixed at the call site in #809 (`int(n)`, `dict(c)`, `str(path)`), or
  listed in the PR body as an accepted output change with the line it prints after the filter.
  The full list goes in the PR body.

## Acceptance tests

Each Codex repro is a red test on `cade66080`, shown red there before the fix. The canary is the
existing `_CANARY`. On `9e63c151` the tests live in four files; the Placement table says which
test is in which file. Shared helpers stay in `log_filter_support.py`.

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
    | `test_exception_inside_container_arg_becomes_label[dict_key]` (:259) | `ValueError` in the output | `x <mapping>`, no canary (row 10: exception key) |
    | `test_exception_inside_mapping_arg_container_becomes_label[dict_key]` (:268) | `ValueError` in the output | `x <mapping>`, no canary (the value of `c` is a dict with an exception key) |
    | `test_tuple_key_in_lone_mapping_arg_becomes_label` (:292) | `ValueError` in the output | `failed: <mapping>`, no canary (row 10: tuple key; `_NamedArgs` display string); renamed `test_tuple_key_in_lone_mapping_arg_is_the_placeholder` |
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
      output is `<mapping>` (row 10) and neither method ran;
    - a plain `list` and a plain `dict` holding an exception next to a caller object whose
      `__eq__` records a call: the exception is relabelled and `__eq__` did not run.
    - Use a lone dict `{K("a"): 7, "b": ValueError(_CANARY)}`. The `str` subclass `K` keeps
      `str.__hash__` and records equality calls. Reset its recorder after construction. With
      `"%(a)s %(b)s"`, require exactly `<mapping> ValueError` and zero recorded calls. M4
      fetches the original exception for the admitted key `"b"` and prints the canary.
    - Exercise row 10 with positional args `(d, 1)` and msg `"%s %d"`. For `d = {"a": 7}`,
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
    - At depth 0, rows 1 to 5 still apply, so an exception or a non-plain mapping is planted at
      every level up to depth 0. A plain `list`, `tuple` or `dict` at depth 0 is not opened and
      becomes `<nested>` (row 6, test 30), so the strategy plants nothing inside one.
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
18. `test_filter_builds_only_closed_types` and `test_filter_sentry_flags_each_seed`, in
    `tests/sentry/safe_output/test_log_filter_closed_types.py` beside
    `test_exception_text_copy.py`. It ships in #809 and runs in the default suite the gate runs.
    An AST walk of `_log_filter.py` finds no call to `OrderedDict`, `Counter`, `defaultdict`,
    `UserDict`, `copy`, `copy.copy`, `copy.deepcopy` or `type(...)(...)`, no attribute read of
    `default_factory`, `get`, `keys` or `values`, and no `items` read except the single direct
    `dict.items(store)` call whose enclosing function is `_safe_pairs`. It requires exactly one
    site in the module. It allows `__iter__` only on the eight base names of rows 7 and 8
    (`list`, `tuple`, `set`, `frozenset`, `deque`, `_KEYS_VIEW`, `_VALUES_VIEW`, `_ITEMS_VIEW`).
    In every `_CHECKED` function (C3) it rejects `isinstance`, membership tests and `==`.
    - Comparisons (Codex R2 V2-LOG): the check is narrowed to caller values. An `==` or `!=` is
      allowed only when one side is an `int` constant (`depth == 0`).
    - Import aliases (recurring defect 5): call names resolve through the shared
      `tests/sentry/_platform_ast.py` `import_map` and `resolve`, so `collections.OrderedDict(...)`,
      `from collections import OrderedDict as OD` then `OD(...)`, and `import collections as c`
      then `c.defaultdict(...)` all count. Covered shapes: a bare call, a dotted module call, a
      `from` alias and a module alias. `getattr` with a string name, `eval` and a builtin rebound
      at run time are deliberate evasion and V2-LOG (owner scope rule, 2026-11-06).
    - Seeds, each a parametrized cell of `test_filter_sentry_flags_each_seed` and each red: a bare
      `defaultdict(...)` call, each alias spelling above, a `store.get(...)` read, a
      `value == depth` comparison, and a second `dict.items(value)` site outside `_safe_pairs`
      while the original stays (flagged by function and line). C3 adds
      `isinstance(value, enum.Enum)` in `_other_value` and `kind == dict` in `_is_container`; the
      seed cell takes the target function's `def` line as a parameter instead of the fixed
      `_HEAD`.
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
Tests for the deny-by-default table and `extra=` (Dennis gate R1 HIGH-1 and HIGH-2). Tests 24,
25, 27 to 31 are on `9e63c151` and are named here as they are; "new" marks a cell or test the
builder adds.

24. `test_protocol_routed_objects_print_no_exception_text` (positional and lone-value, through
    the engine stream and file handlers, exact output on both) and
    `test_protocol_routed_objects_at_the_depth_limit`, in `test_log_filter_objects.py`. Cells on
    the head: `deque`, `dict_keys`, `dict_values`, `dict_items`, `custom_iterable`, `generator`,
    `dataclass`, `attrs_like`, `slice`, `simple_namespace`, `namespace_subclass`,
    `argparse_namespace`, `partial`, `wrapper`. Each asserts the exact line, no recorded caller
    `__iter__` call, and that `_reachable(record.args)` holds no planted exception. New cells:
    - `bound_method` (C1): `_Holder(exc).method` prints `<object>`. Red on `9e63c151`, where
      `MethodType` passes and the bound method's `repr` prints the dataclass `repr`.
    - `fraction` (B9): `fractions.Fraction(1, 2)` prints `<object>`; `numpy_int` does the same
      for `numpy.int64(1)` and skips when numpy is not installed.
25. `extra=` attributes, in `test_log_filter.py`: `test_extra_attributes_are_scanned` (a
    `%(err)s`-style formatter prints exactly `x | ValueError | [<mapping>, 1]`),
    `test_failed_scrub_blanks_every_extra_attribute` (a forced failure in `_safe_value` gives
    `_UNRENDERABLE` in every field and no canary), and
    `test_standard_record_fields_are_not_rewritten` (`_STANDARD_FIELDS` attributes are left as
    they were).
26. New: `test_json_formatter_prints_no_extra_exception_text`, in `test_log_filter.py`. A
    formatter that returns `json.dumps(record.__dict__, default=str)`, the shape of common JSON
    log formatters, on an engine handler and on a host handler with `SafeRecordFilter` attached.
    Cells: `extra={"err": ValueError(_CANARY)}`, `extra={"ctx": _Holder(ValueError(_CANARY))}`
    and `extra={"rows": [ValueError(_CANARY)]}`. Assert no canary, and that the parsed JSON has
    `err == "ValueError"`, `ctx == "<object>"` and `rows == ["ValueError"]`.
27. `test_scalars_and_plain_objects_still_print_as_before` and
    `test_clean_exact_scalars_and_containers_keep_their_identity`, in
    `test_log_filter_objects.py`: exact `_SCALAR_LIKE` and plain values print as stock, at the
    top level and one level inside a list, and clean exact values keep their identity.
28. `test_a_subclass_never_prints_through_its_own_repr`, in `test_log_filter_objects.py`, over
    positional, lone-value and nested positions and `%s` and `%r`. Cells on the head: `int_sub`
    (`5`), `list_sub` (`[1]`), `path_sub` and `decimal_sub` (`<object>`), `enum` (`_Color.RED`)
    and `record_tuple` (`<object>`). New cells:
    - `int_enum` (C2): an `IntEnum` member with a canary `__str__` and `__repr__` prints `1`
      under `%s`, `%r` and `%d`, and the `%d` cell raises no logging error. Red on `9e63c151`,
      where it prints `Color.RED` and `%d` fails;
    - `int_flag` (C2): the same for an `IntFlag` member;
    - `str_enum`: a `StrEnum` member prints its value under `%s`.
29. `test_removing_the_iterable_route_is_visible`, in `test_log_filter_objects.py`: a caller
    iterable prints exactly `<nested>`.
30. `test_plain_container_at_the_depth_limit_is_the_placeholder` (list, tuple, dict and set at
    depth 0, positional and lone, exact `x [<nested>]`) and
    `test_clean_scalars_at_the_depth_limit_are_kept`, in `test_log_filter_mappings.py`. This
    replaces the `too_deep` strict xfail (retired in `a6f97b5c5`).
31. `test_str_subclass_is_a_plain_copy`, in `test_log_filter_mappings.py`: a `str` subclass as an
    argument, inside a list (depth 0) and as a dict value prints `ok`, never its canary
    `__str__` or `__repr__`, and no recorded call. Row 5 runs before the depth check on purpose:
    a `str` subclass is text, and a placeholder at depth 0 would hide a plain string value
    (LOW-5).
32. New: `test_non_plain_key_and_missing_name_print_the_placeholder`, in
    `test_log_filter_objects.py` (B10, B11). Positional `"x %s %d"` with args `(d, 1)` (two
    items, so `LogRecord` keeps the tuple) and a clean dict `d` keyed by a tuple, `bytes`,
    `frozenset`, an `IntEnum` member and a `StrEnum` member: each prints exactly
    `x <mapping> 1`. A lone plain `{"a": 1}` with `"%(a)s %(missing)s"` prints exactly
    `1 <mapping>` through an engine handler, with nothing on stderr.
33. New: `test_other_value_runs_no_caller_code`, in `test_log_filter_objects.py`. A caller class
    and an `int` subclass and a `float` subclass, each with recording `__repr__`, `__str__`,
    `__format__`, `__int__`, `__index__`, `__float__`, `__eq__` and `__hash__`, positional and
    lone-value. Assert `<object>`, `5` and `1.5`, and zero recorded calls.

The documented gaps that stay strict xfails on `9e63c151` are
`test_documented_gap_preformatted_text` (`fstring`, `str_arg`) and
`test_documented_gap_uncatchable_shapes` (`exc_args`). Rows 4 and 5 pass a plain `str` and a
tuple of plain `str`, so both still fail strictly after C1 and C2; the builder records the
strict-xfail result on the final head (recurring defect 7). The `wrapper_str` and `too_deep`
cells are retired (Decision 5) and are not restored.

## Mutations

Each must turn at least one named test red on the final head (recurring defect 9: record the head
each mutation ran on). The builder records the results in the PR body.

| # | Mutation | Test that must fail |
|---|---|---|
| M1 | return a clean non-plain mapping as is | 13, 4 |
| M2 | read a non-plain mapping through `.items()` instead of the placeholder | 15, 16, 7 |
| M3 | relabel exception keys into a rebuilt dict instead of the placeholder | 2, 16 |
| M4 | read a named field with `dict.get(store, name)` (or `mapping[name]`) instead of taking it from the `_safe_pairs` result | 15 (the raw value for admitted key `"b"` prints the canary instead of `ValueError`) |
| M5 | change the dispatch decision that admits a subclass (Codex R2 D7): row 3 no longer catches a `dict` subclass, and row 10 accepts it (`isinstance(value, dict)` in both places). Changing row 10 alone is inert, because row 3 runs first | 3, 13, 16 |
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
| M16 | rows 1 to 3 moved after the depth check | 16 (fixed cell: a `UserDict` holding the canary exception inside a positional `list`, at depth 0) |
| M17 | reduce the display depth alone: the display uses `_safe_pairs(store, _ARGS_DEPTH - 1)` while the named values keep `_ARGS_DEPTH` (Codex R2 V1-1) | 20 |
| M18 | row 7 returns a changed subclass as the subclass (`type(value)(new)`), or passes sequence subclasses through to row 13 (Codex R2 V1-2) | 21 |
| M19 | remove the `type(record.args) is _NamedArgs` keep rule in `_scrub` (Codex R2 V1-3) | 13, 22 |
| M20 | compute `repr(display_source)` in `_scrub` instead of in `__str__` and `__repr__` (Codex R2 V1-4) | 23 |
| M21 | drop row 2 (`_is_record_class`), so a dataclass or attrs instance falls through | 24 (`dataclass`, `attrs_like`), 26 (`ctx`), 28 (`record_tuple`) |
| M22 | row 13 returns the value itself instead of `<object>` (the old pass-through) | 24 (`wrapper`, `partial`, `simple_namespace`, `fraction`), 26 |
| M23 | row 13 returns an unknown iterable as itself, or iterates it into a list | 24 (`custom_iterable`, `generator`; the recorded `__iter__` call), 29 |
| M24 | drop the `_ITERABLES` loop (row 8), so a `deque` or view falls to row 13 | 24 (`deque` and the three view cells expect a list) |
| M25 | row 9 returns a `slice` without scanning its parts | 24 (`slice`) |
| M26 | row 6 returns a plain container at depth 0 as itself | 30 |
| M27 | `_other_value` admits a `_SCALAR_LIKE` subclass (`issubclass` in place of `_is_exact`) | 28 (`path_sub`, `decimal_sub`) |
| M28 | check `enum.Enum` before `_NUMBER_COPIES` (reverts C2) | 28 (`int_enum`, `int_flag`) |
| M29 | copy a number subclass with `base(value)` instead of the unbound `__pos__`, or return it as itself | 33 (recorded `__int__` or `__float__`), 28 (`int_sub`) |
| M30 | skip the `extra=` loop in `_scrub` | 25 (`test_extra_attributes_are_scanned`), 26 |
| M31 | the fallback in `filter` leaves `extra=` attributes as they are | 25 (`test_failed_scrub_blanks_every_extra_attribute`) |
| M32 | (a) row 10 ignores `plain` when nothing changed, so a dict with a non-plain key is returned as itself; (b) remove `_NamedArgs.__missing__` | 32 (a: the key cells; b: the `%(missing)s` cell), 13a `dict_key` cells |
| M33 | move row 5 after the depth check, or return a `str` subclass as itself | 31 (`in_list` cell for the move; every cell for the pass-through) |
| M34 | put `types.MethodType` back in `_SCALAR_LIKE` (reverts C1) | 24 (`bound_method`) |

Test 18 has its own seeds (listed at test 18), including the two C3 seeds. They are run with the
mutations and recorded the same way.

## Failure modes

| Failure | Detection | Response |
|---|---|---|
| a new mapping type appears | it is not an exact plain type, so it gets the placeholder | none needed |
| a log line that printed a clean `Counter` now prints `<mapping>` | the builder's walk of logger calls; the PR body list | pass `dict(counter)` at the call site |
| a named field's value is the placeholder under `%d` | stock logging error with filtered args | the call site passes a plain dict |
| the display `repr` fails on a stored value (for example the int-to-text limit) | test 23 | that one `%s` or `%r` prints `<mapping>`; named fields still print |
| a second filter on the same record | test 22 | the exact-type keep rule returns the `_NamedArgs` unchanged |
| a `%d` field gets `<object>` (a `numpy.int64`, a `Fraction`), B9 | the logger-call walk; stock logging error on stderr | the call site passes `int(n)`; the walk lists every such call in the PR body |
| an `IntEnum` under `%d` | test 28 `int_enum` | C2 copies it to `int`, so the line prints |
| an `extra=` value cannot be scanned | test 25 | the fallback writes `_UNRENDERABLE` to `msg` and to every `extra=` attribute |
| a generator or stream is passed as an argument | test 24 `generator` | `<nested>`; it is never iterated, so the caller can still read it |
| a retired strict xfail would XPASS | the strict run fails | `wrapper_str` and `too_deep` are retired, not kept (Decision 5); the two remaining xfails are rechecked on the final head |

## Design notes

No new structure. The change removes the lookup machinery and replaces many type cases with one
table (open/closed: a new mapping type needs no new code). Each fact has one place: the type
table in `_safe_value`, the one pair reader `_safe_pairs` (row 10, named values and display all
take its result, so their depth cannot differ), the default table in `_named_args`, the
placeholder constant.

## Placement and size

All files are in existing directories. The unit test files new since `cade66080` were split out
of `test_log_filter.py` so no test file passes the 700-line maximum; they sit beside it in
`tests/unit/safe_output/`, which already holds the `safe_output` unit tests. The guard sits in
`tests/sentry/safe_output/`, which the CODEMAP "Where things go" table names as the home of
the F31 safe-output sentries (`CODEMAP.md:168`).

| File | Status | Holds | Lines at `9e63c151` | Expected after |
|---|---|---|---|---|
| `src/decoy_engine/safe_output/_log_filter.py` | existing | the type table, pair reader, `_NamedArgs`, `_scrub`, the filter | 438 | about 438 (C1 -1, C2 reorders 3 lines; docstring edits) |
| `tests/unit/safe_output/test_log_filter.py` | existing | record, traceback, `exc_info`, container, handler-route and `extra=` tests (10 to 12, the 13a rows, 25, 26), the strict xfails | 421 | about 460 (test 26) |
| `tests/unit/safe_output/test_log_filter_mappings.py` | new, split in `a6f97b5c5` | the mapping and named-lookup tests (1 to 9, 13 to 17, 19 to 23), 30, 31 | 623 | 623: no tests added here, because it is past the 600 aim |
| `tests/unit/safe_output/test_log_filter_objects.py` | new, split in `9e63c151` | tests 24, 27, 28, 29, 32, 33 | 268 | about 350 |
| `tests/unit/safe_output/log_filter_support.py` | new, split in `a6f97b5c5` | shared helpers: `_CANARY`, handlers, `_record`, `_lone`, `_both`, `_reachable` | 127 | about 127 |
| `tests/sentry/safe_output/test_log_filter_closed_types.py` | new | test 18 and its seeds | 103 | about 115 (C3) |

`tests/sentry/test_module_size.py` budgets `src/` and `scripts/` only, so no census entry or pin
moves. `_log_filter.py` lost `_Lookup`, `_ScannedFactory` and the rebuild code and gained
`_safe_value`, `_other_value`, `_safe_pairs`, `_named_args`, `_NamedArgs` and the three
placeholders. No new public names.

## Test depth

T0 per edit on the touched test file (`test_log_filter.py`, `test_log_filter_mappings.py`,
`test_log_filter_objects.py` or the guard). T1 per commit: `tests/unit/safe_output/`,
`tests/sentry/safe_output/`, `tests/sentry/test_log_interpolation.py`, the logging config
tests that import `_new_engine_handler`, ruff check, ruff format and mypy on changed files. Tests
run with vm-run on the Mac or Dell, never on the devbox. No full-suite trigger
applies (no shared fixture, schema, lock or frozen contract change).

Commit order (Codex R2 D8):

1. Write the new and rewritten tests first. Run them on `cade66080` and record each red run (test
   id and failing assertion) in the PR body. Tests 20 and 21 pin current output, so they are
   green there; record that too. Record mixed tests by cell. Capture the old outputs from
   the three compatibility rows in test 19, and the first-pass brace leak in test 1.
   For preservation cells that already pass, show red with the named mutation. Seed both
   row 10 flag errors and the duplicate reader before accepting tests 15 and 18. Repeat these
   seeds with M1 to M34 on the final implementation head.
   The red runs on `cade66080` are scratch runs, recorded in the PR body. A red test is never
   committed as red or as a new strict xfail before the code that turns it green (LOW-4).
2. Commit the implementation together with every changed expectation in the 13a table, so each
   commit is green and no assertion is weakened or dropped on its own. No pin, cap or baseline
   moves.
3. From `9e63c151`, the rest goes in one commit per change, each with its tests: C1 with the
   `bound_method` cell; C2 with the `int_enum` and `int_flag` cells; C3 with its two seeds; then
   tests 26, 32 and 33 and the `fraction`, `numpy_int` and `str_enum` cells. Show the C1 and C2
   cells red on `9e63c151` in a scratch run first, and record it.
4. Run the logger-call walk on the final head and put its list in the PR body.
5. On the final recorded head, run T1 and every mutation M1 to M34 and the test 18 seeds, and
   record the head next to each result (recurring defect 9). Record that the two remaining
   strict xfails still fail strictly. A code change after that run voids it.

## Docs and changelog

The `_log_filter.py` module docstring gets the type table, the one pair reader, the re-filter
keep rule, the lazy display and the named-lookup rule in place of the current mapping text. The gap list drops "a mapping type other than dict and `UserDict`". On
`9e63c151` the docstring already has the table; C1 and C2 change its `_SCALAR_LIKE` line (a
bound method is `<object>`) and its enum line (an `int` or `float` enum prints its number), and
the stray `;` that ends the table list goes. The CHANGELOG fragment
(`changelog.d/f31-ae3-log-filter.md`) says that in engine logs a non-plain mapping argument
prints `<mapping>`, an object with no row prints `<object>`, an unknown iterable or a container
past the scan depth prints `<nested>`, and `extra=` attributes are filtered too. The CODEMAP
`tests/sentry/safe_output/` row adds `test_log_filter_closed_types.py`.

## V2-LOG (deferred)

- Keep the reviewed branch's live interpolation allowlist and recorded baseline empty.
- A caller `defaultdict` factory that is value-free in practice (for example `lambda: 0`) gives
  `<mapping>` for a missing named field. Accepted.
- Numbers with no row (`numpy.int64`, `Fraction`) print `<object>` (B9). If the walk finds no
  engine call that passes one, a row for numpy scalars waits for a real call site.
- `_safe_value` has more than ten ordered rows; a row table with named predicates would read
  better (Dennis gate R1, clean-code lens). No behavior change.
- `test_log_filter_mappings.py` is at 623 lines, past the 600 aim; split it at the Q1 2027
  cleanup.
- Text a wrapper object already formatted into `msg` stays a non-goal under "pre-formatted
  text", guarded at call sites by `test_log_interpolation.py`.
