# PM-1 comparison authority redesign

Status: plan

Date: 2026-11-27. PR #784 (POSTMASK-FAIL-CLOSED), branch `fix/postmask-fail-closed`, head
eaf160db3. Risk: R2 (value-leak check). This plan replaces the comparison parts of
`2026-11-25-pm1-number-keys-r5.md` and `2026-11-27-pm1-canonical-cell-walk.md`. Those plans
stay as history. The rest of the PR (PM-1a, the writer query) is kept as built.

Rules consulted: `00-universal.md`, `risk-and-exceptions.md`, `development-loop.md`,
`bugfix.md`, `testing.md`, `cross-cutting-concerns.md`, `architecture.md`, `reuse-first.md`,
`proportionality.md`, `catalogs/recurring-defects.md`.

Why a redesign: Claude fixed rounds 1 to 3 and Codex fixed round 4. Each round found new V1
cases in the same area (records, sets, units, spellings, number keys). The owner rule is to
change the plan, not patch again, when one class of finding repeats.

## The class of defect

All open findings share one class: **two representations of one cell disagree, and the
verdict reads the wrong one.** The code already names the symptom "comparison not preserved".

Today a source cell and an output cell can be compared through four representations:

1. the pandas cell in the caller's frame;
2. the Arrow array that `_native` builds (`runner.py:186`), read back with `to_pandas`;
3. the text key that `key_text` builds (`cell_text.py:87`) for a column Arrow refuses;
4. the canonical form that `canonical_cell` builds (`canonical_cell.py:130`) from 1, 2 or 3.

A fifth path still exists: `check_policy_validation` compares with
`Series.astype(object).equals` (`policy_validation.py:133`).

Each round found a cell where two of these disagree:

- Arrow loses set equality (CX-2) and the unit in `list<timestamp>` (DN-D2-pre-a).
- `Series.equals` and the canonical form disagree on nested dicts (CX-1).
- A dtype shortcut skips the record check for a categorical (CX-3).
- The text key must spell a value as its own `str()` export, so that a value which came back as
  text still matches (K4). It must also give one key to equal values of other types and units.
  These two jobs conflict. Every new kind (record, subarray, unit, complex NaN, namedtuple,
  0-dim box) needs a spelling that serves both jobs, and each fix broke another case (PC2-1,
  PC3D-1, PC4-1, PC4-2, O3 to O5, F1 to F4, B1, R3).
- `_require_preserved` (`runner.py:251`) is a backstop that compares key counts with cell
  counts. It compares column totals, so offsetting errors pass (PC1-2). Its diversity half
  blocks whole tables on harmless spellings (F4).

Why the design keeps producing it: identity is computed **after** conversion, on a derived
array that must be hashable and spelled the same across rows. The positional comparison does
not need that. Row i of the source is only compared with row i of the output. A key that must
agree across all rows is a much harder problem than a predicate on one pair of cells.

## Established solutions

Searched (online and in the codebase): the datacompy source (`datacompy/pandas.py`
`columns_equal`, the comparators in `datacompy/comparator/`), the reladiff driver guide
(`normalize_number`, `normalize_timestamp`), the Python docs on numeric comparison and hashing
(`stdtypes`, "Hashing of numeric types") and on `decimal` (`FloatOperation`), pandas
`Series.equals` and `hash_array`, Arrow `compute.equal` and `Array.equals`, SQL
`IS NOT DISTINCT FROM`. Found:

- **datacompy** compares two columns row by row. It runs an ordered list of typed comparators
  (boolean, numeric with tolerance, string, array-like). The first one that applies gives a
  boolean Series. Two nulls match; a null and a value do not. A mixed-type column falls back to
  "not equal". We follow the comparator pattern. We invert the fallback: for a leak check "not
  equal" is the unsafe answer, so a cell that no rule handles refuses the column.
- **reladiff (data-diff)** normalizes each column by its declared type to a common precision,
  then hashes. It needs keys because it diffs across databases. We hold both rows in one
  process, so we do not need keys.
- **Python numeric tower.** `==` between `int`, `float`, `Decimal` and `Fraction` is exact, and
  equal numbers hash equal across those types. Under a `FloatOperation` trap, equality stays
  silent. This replaces the binary64 key, the bands and the bounded `int()` work of round 5 for
  number-to-number identity.
- **pandas `hash_array`** hashes a mixed object array by the `str()` of each value. That is the
  text-key pattern of rounds 4 and 5, and it depends on spelling by design.
- **Arrow** `compute.equal` needs one common type, and `Array.equals` is type-strict. Neither
  compares a Python set or a NumPy record.
- **SQL `IS NOT DISTINCT FROM`** is null-safe equality: two nulls are not distinct.

Custom code that remains: the value forms for NumPy and pandas temporals and containers (kept
from the reviewed canonical walk; no library gives attosecond-exact identity across units), and
a closed list of export spellings for the text match (K4). No library predicts how a value was
exported to text.

## The design: one comparison authority

### The choke point

New module `src/decoy_engine/internal/cell_identity.py`. It is the only place that decides
whether a source cell and an output cell are the same value. Public names:

- `identity_facts(src: pd.Series, out: pd.Series) -> IdentityFacts`. Positional. Returns
  `comparable` (both non-null), `identical` (same value) and `all_same` (every row is the same
  value or both null). `IdentityFacts.merge` folds batches.
- `distinct_values(series: pd.Series) -> int`. The non-null distinct count on the value forms.
- `is_null(value) -> bool`. The one null decision. The detectors read it too.
- `CellNotComparableError(DecoyError)`. Fixed text, no value, raised with no context
  (recurring class 3).

Every reader calls these and nothing else:

| Reader | Calls |
|---|---|
| `_column_facts.column_facts` (batch path) | `identity_facts` per batch pair, merged |
| `runner._frame_tables` (frame path) | `identity_facts` on the frame columns, before Arrow |
| `residual_pii._frame_column_facts` | `identity_facts` |
| `policy_validation.check_policy_validation` (frame) | `identity_facts(...).all_same` in place of `.equals` |
| `source_distinct`, `cells_distinct_or_error` | `distinct_values` |
| `cell_text` detector null decision | `is_null` |

`bytes_identical` is `all_same` from the same call. No reader computes a flag, a count or a
null pairing on its own.

### The rule, per row

For row i, with source cell `a` and output cell `b`:

1. **Unbox.** A 0-dim array is its payload. `np.ma.masked` is null. A box that holds itself
   raises `CellNotComparableError`.
2. **Refuse records.** A NumPy structured value (`np.void` with fields, a structured ndarray)
   anywhere in either cell, at any depth (sequence item, set member, map key or value), raises
   `CellNotComparableError`. This check runs on every cell, null or not, before any shortcut.
3. **Nulls.** Both null: BOTH_NULL (not comparable, counts toward `all_same`). One null:
   ONE_NULL (not comparable, not same).
4. **Text against non-text.** If exactly one side is text (a `str`, or bytes, which decode as
   strict UTF-8 by the existing `cell_text` rule), the row is SAME when the text is one of the
   export spellings of the other cell (below). Else it is DIFFERENT.
5. **Otherwise** the row is SAME when `value_form(a) == value_form(b)`. Text against text is
   exact string equality, as on main.

`value_form` is the value half of today's `canonical_cell`, with every spelling field removed:

| Cell | Form |
|---|---|
| bool, `np.bool_` | `bool` (Python `True == 1`, as on main) |
| int, `np.integer` | `int` |
| float, `np.floating` up to 64 bits | `float` |
| wider float (`g`) | `Fraction(as_integer_ratio())`, exact |
| complex | `complex`; `clongdouble` as a pair of exact `Fraction` |
| `Decimal` | itself (exact `==` and hash against int and float) |
| `np.datetime64`, `pd.Timestamp`, `datetime` | `Instant(attoseconds, aware)`; Y and M units as `Months` |
| `np.timedelta64`, `pd.Timedelta`, `timedelta` | `Duration(attoseconds)`; Y and M as `Months`; generic unit as `int` |
| NaT, NaN, None, `pd.NA` | `NULL` at any depth |
| list, tuple, namedtuple, ndarray of any rank | `Seq(items)` |
| dict, Arrow map (list of pairs from `to_pandas`) | `Map(frozenset of pairs)` |
| set, frozenset | `Members(frozenset)` |
| bytes, bytearray, memoryview | `bytes` (top-level bytes are text, step 4) |
| other hashable object (`UUID`, `date`, `Period`, `Interval`) | itself, compared by its own `==` |
| other unhashable object | `CellNotComparableError` |

The temporal rows keep the reviewed fixes: `asm8` reads, never `.value` (DN-P1-2); the reserved
NaT integer is excluded (PC1-4); calendar months convert with Python ints, so no int64 wrap
(PC1-5); aware datetimes normalize to UTC (DN-P1-5).

Numbers compare by the Python numeric tower, so `int(2**53 + 1) != float(2**53)` and
`Decimal("0.1") != 0.1`. Both are true differences. No binary64 rounding enters identity.

### Export spellings (K4)

A non-text cell `x` matches the text `t` when any of these holds. `x` is the original cell, and
`x'` is its Python-native form (`.item()` for a NumPy scalar, `.tolist()` for an ndarray).

1. `t` is `str(x)`, `repr(x)`, `str(x')` or `repr(x')`.
2. `x` is a number (bool included) and `t` matches the numeral grammar (kept from round 5:
   ASCII, optional `-`, digits, fraction, exponent, `inf`). Then `t` matches when its exact value
   equals the exact value of `x`. When `x` is a float of at most 64 bits, `t` also matches when
   `float(t) == x`, so any text that rounds to the float matches (`"0.1"`, `"1e+23"`,
   `f"{x:.17e}"`, the exact expansion). When `x` is a wider float, `t` matches when
   `float(t) == float(str(x))`. The exponent is read from at most 20 digits; a longer exponent
   cannot match a finite number. No `int()` sees more than 25 digits, and no decimal context is
   read.
3. `x` is a temporal and `t` is `str(pd.Timestamp(x))` or `str(pd.Timedelta(x))` (in the ns
   range), `x'.isoformat()`, or `str(np.datetime64(x))`.
4. `x` is a container and `t` is `json.dumps(x', default=str)`, or the same with
   `sort_keys=True`.

The spellings are built only for a row where exactly one side is text, so other rows pay
nothing. An extra spelling can only add SAME rows. That fails closed (a block, never a leak).

### Fast path

When both series share one NumPy dtype of kind `b`, `i`, `u` or `f` (or `M`/`m` with one unit),
the verdicts come from a vectorized `==` with NaN as null. Such a column cannot hold a record
or text. Every other dtype (object, categorical, Arrow, string, mixed) takes the per-row rule on
`astype(object)` cells. A categorical is compared by its values, so its categories are never a
shortcut (CX-3).

### What the frame path carries

The frame path computes identity on the frames, before any Arrow conversion, for every paired
column. It hands the result to `column_facts` in a new keyword
`identity: Mapping[str, IdentityFacts | IdentityFailure]` (revision 1, item 12).
`column_facts` uses that entry and does not compare that column's batches. On the batch path
(`run_post_mask_tables`) the keyword is absent, and `column_facts` folds `identity_facts` over
the aligned batches. Both routes call the one authority.

Arrow conversion stays for the detectors, the DuckDB distinct counts and the value tally. A
column that Arrow refuses is carried as its `detector_text` (same null mask), not as a key.
There is no key, so `_require_preserved` and `ComparisonNotPreservedError` go.

### The sentry

`tests/sentry/test_cell_identity_choke_point.py` parses the syntax tree of
`src/decoy_engine/verification/postmask/`, `src/decoy_engine/internal/cell_text.py` and
`src/decoy_engine/detection/`. It fails on:

- a call to `.equals`, `.eq`, `.ne`, `.compare`, `np.array_equal` or `pd.testing.*`;
- a `Compare` node with `==` or `!=` where an operand is a name bound from `_series`, a frame
  column (`df[...]`, `.iloc`), `astype(object)` or `to_pandas`;
- a call to `nunique` outside `cell_identity.py`;
- anywhere in `src/`: an import of `canonical_cell`, or a definition named `identity_counts`,
  `canonical_cells`, `_compared`, `_frozen` or `key_text`.

The allowlist is a ratchet (it may only shrink) with one entry:
`verification/canary/_canonical.py`, the Arrow-side canary walk that predates this PR
(DN-F-V2-3). Its follow-up row moves the canary onto `cell_identity`.

Seeded proof (cross-cutting rule): the sentry test carries one seeded source string per form
above and asserts each one is flagged.

Behavioral guard: `test_identity_routes.py` runs every corpus pair through four public routes
(`run_post_mask`, `run_post_mask_tables` over the same tables staged natively,
`check_residual_pii` and `check_policy_validation`). It asserts that each route's comparable,
identical and `bytes_identical` equal `identity_facts` on the pair. The one mutation that must
turn it red: replace the `identity_facts` call in `residual_pii._frame_column_facts` with
`(src == out).sum()`.

## Guarantee and non-goals

Guarantee, on every post-mask route:

- An unchanged source cell counts as identical when the output holds the same value (by the
  value forms above) or the value as one of the listed export spellings.
- A column that holds a NumPy record on either side fails that column with an `error` finding
  (`CellNotComparableError`). It never fails the whole table, and it never passes.
- `bytes_identical`, `comparable` and `identical` come from one verdict vector, so they cannot
  disagree.
- Identity never reads an Arrow conversion of a frame, a text key, or a column total.
- Comparison raises only `CellNotComparableError` (recorded by class name) or an error that
  passes through. No error text carries a value.
- No result depends on `sys.set_int_max_str_digits` or on the decimal context.

Non-goals (recorded as follow-ups, not blockers):

- A spelling outside the list: locale numbers (`1,000`), `+5`, padded text, other date formats
  (`01/02/2020`).
- Text against text by value: source `"1.0"` against output `"1.00"` stays DIFFERENT, as on
  main.
- A text match inside a container: `[1, "a"]` against `["1", "a"]` is DIFFERENT. The whole
  cell's text is matched, not its elements.
- A record inside an opaque object that is not walked (DN-RD-opaque, V2-LOG).
- Record comparison by fields. Per-column refusal stands; no supported reader makes a record
  (DN-D2-3).
- The pyarrow 24 segfault on `(NaT, int64)` tuple cells in `_native` (own row, pre-existing).
- The canary walk (DN-F-V2-3).
- A column whose null source cells are filled in the output (DN-D2-null, V2-LOG).

## Behavior changes against main

1. A non-text cell exported as its text counts as unchanged (`Decimal`, list, dict or int to
   `str`). On main these read as "differs" (DN-D2-6). This gives more blocks and no new pass.
2. `list<timestamp[us]>` against `[ns]` with the same instants counts as unchanged
   (DN-D2-pre-a). The frame path no longer reads Arrow for identity, and on the batch path the
   value forms read units exactly.
3. A record column gives a column `error` finding.
4. A set column compares as sets.

## Failure modes

| Failure | Direction | Handling |
|---|---|---|
| A value form splits two equal values | leak | Kind-enumeration test A-K1 over every NumPy typecode, nesting and export; property test P1 |
| A value form merges two different values | false block | Accepted; listed merge only (`True == 1`) |
| An export spelling is missing | leak | Pinned list above; non-goals named |
| An extra spelling matches | false block | Accepted |
| A new cell kind | either | Hashable: its own `==`. Unhashable: refused. A-K1 goes red on a new typecode |
| A reader compares on its own | either | Sentry plus the route parity test |
| The fast path disagrees with the per-row rule | either | Property test P3 per fast dtype |
| Spelling work on a large column | slow | Only rows with text on one side build spellings; at most 10 strings per row |
| A cycle or the masked constant | hang | Step 1 guard; test PC1-1 with a 5 s timeout |

## What to keep and what to delete

Keep as built: the writer query and `plan/column_access/`, the passthrough exemption, the
failed-distinct grading, the deferred post-scan `pass_failed_with`, coded error propagation,
the gate hook raise, the nullable integer suite, `UnreadableCellError` and its reason,
`cell_text.cell_text`, `column_text`, `numpy_bytes_as_objects`, `detector_text` with its round-5
rules (detectors read cells as written), `cells_distinct_or_error`, `_count_or_error`, and their
tests (`test_value_free_check_errors.py`, `test_gate_fail_closed.py`,
`test_writer_ownership_findings.py`, `test_postmask_writer_ownership.py`, the detector cases in
`test_residual_pii_source_compare.py`, `test_order_free_facts.py`).

Move: the value half of `canonical_cell.py` (the forms, `unboxed`, `is_null`, the temporal
conversions and their fixes) goes into `cell_identity.py`. `temporal_text` and the numeral
grammar (`_NUMERAL`, `_reduced`, the exponent bound) stay in `cell_text.py`, and
`cell_identity` imports the grammar (one direction only). Rule: `cell_identity` holds no
spelling except the K4 list, and `cell_text` holds no identity.

Delete: `canonical_cell.py`; every `compare=False` spelling field; `Record` and `Blob`;
`contains_record` and `contains_members`; `key_text` and the number-key code (`_binary64_key`,
`_short_key`, `_float_key`, `_decimal_key`, `_text_key`, `_number_key`, `_canonical_key`,
`_canonical_text`, the bands); `runner._text`, `_require_preserved` and the set check in
`_native`; `_column_facts._compared`, `_has_record`, `_typed`, `canonical_cells` and
`identity_counts`; `ComparisonNotPreservedError` and `RecordNotComparableError`, with their
`reason_adapter` and `scan_set` rows (both added by this PR, never released);
`CellView.detector_text` (the table column is the detector text). Tests that pin key strings
go: `test_canonical_cell_keys.py`, and the key assertions in `test_text_fallback_parity.py` and
`test_canonical_cell.py`. Their run-level cases move into the acceptance files below, with the
expectations given there.

## Acceptance tests (written first, slice S1)

Files: `tests/unit/internal/test_cell_identity.py` (the pair table) and
`tests/unit/detection_verification/postscan/test_identity_routes.py` (route parity and runs).
Each pair row runs through `identity_facts` and through all four routes. Synthetic values only.
Rows marked "now green" pass on eaf160db3 and must stay green.

### Open at eaf160db3 (Codex `codex-pm1-r1.out`, Dennis delta 2)

| Id | Case | Expected |
|---|---|---|
| CX-1 | `{"a": [1, 2]}`, `{"a": [3, 4]}` unchanged, `hash` | `fail`, blocking, on every route (eaf160db3 tried a fix; no review saw it) |
| CX-2 | two set rows, same members, reversed insertion order, `hash` | identical 2 of 2, `fail` |
| CX-3a | two read-only record categories, codes reversed | column `error` (`CellNotComparableError`) |
| CX-3b | record against null, record against an equal record, a one-row record column | column `error` each |
| CX-4 | the mutation table below, recorded with its head in the PR body | review check |
| DN-D2-1 | `{rec}` vs `{str(rec.item())}`, `{rec: 1}`, `frozenset([rec])` | column `error` |
| DN-D2-6 | `Decimal`, list, dict and int cells against their `str` | identical on all rows, `fail` |
| DN-D2-pre-a | `list<datetime64[us]>` vs `[ns]`, same instants | identical on all rows, `fail` |

### Records (Dennis redesign, Codex PM-1 r2 to r4)

| Id | Case | Expected |
|---|---|---|
| DN-RD-1a | `rec.item()` and `tolist()` of a subarray of nested records | `error` |
| DN-RD-1b | `tuple(rec)` of nested and deep records | `error` |
| DN-RD-1c | `{name: rec[name]}` of nested records | `error` |
| DN-RD-m3 | mutation: drop the set and map branches of the record scan | DN-D2-1 goes red |
| PC2-1, PC3-1, PC3D-1, PC4-1 | record with an array field, record against `str(item())`, `M8[ns]` vs `M8[us]` field | `error`; the other columns are still graded |
| PC4-2 | subarray of nested records with the inner unit changed, plus an `email` column | record column `error`; `email` findings present; no table error |

### Canonical walk (Codex PM-1 r1, Dennis plan r1 and r2, Dennis final)

| Id | Case | Expected |
|---|---|---|
| PC1-1 | `[np.ma.masked, "marker"]`, and a box that holds itself | no hang (5 s); masked is null; the cycle is `error` |
| PC1-2 | rows `(1, 2)` and `[3]` vs `np.array([1, 2])` and `"[3]"` | identical 2 of 2 (per row, no totals) |
| PC1-3 | `[np.complex64(nan+0j)]` vs `"[(nan+0j)]"` | SAME by `str(x')` |
| PC1-4 | instant and duration of `-(2**62)` ticks in `2ns` and `2M` | not null, not equal to NaT |
| PC1-5 | `np.datetime64(2**62, "M")` | a positive instant |
| PC1-6 | mutation: uppercase the output text cells | the K4 rows go red |
| DN-P1-1 | `Timestamp`, `UUID`, `date` and `[1]` vs their `str` | SAME |
| DN-P1-2 | `as_unit("s")` Timestamp and Timedelta past 2262 | no raise; SAME to itself |
| DN-P1-5 | `np.timedelta64(5)` vs `5`; `datetime(..., +01:00)` vs the UTC Timestamp | SAME both |
| DN-P2-1 | `(1, 2)` vs `np.array([1, 2])` | SAME |
| DN-P2-2 | `[nan, 'a']`, `[pd.NaT, 'a']`, `[datetime(2020,1,1), 'a']`, `timedelta(seconds=1)`, a nested `Etc/GMT-1` Timestamp, each vs its `str` | SAME |
| DN-P2-3 | `{"b": 2, "a": 1}` vs its `str` | SAME (original order) |
| DN-F-V2-1 | per-row verdicts | covered by PC1-2 |
| DN-F-V2-2, A-K1 | every `np.typecodes["All"]` x top, list, tuple, dict, set, 0-dim, object array; exports `str`, `repr`, `item`, `tolist` | no raise except records; each cell SAME to itself and to its `str`; verdict snapshot |
| DN-F-LOW | `g` and `G` are explicit `value_form` rows | unit test |

### Older rounds (Codex delta, r3 to r5)

| Id | Case | Expected |
|---|---|---|
| OD-1 | `{"id": 1}` vs `{("id", 1)}`, distinct count | 2 |
| OD-2 | a two-field namedtuple cell | no raise; SAME to its tuple |
| OD-3 | an ndarray of dicts with keys reordered | SAME |
| O3-1, O4-1 | `timedelta64[s]` `[1]` vs `[ms]` `[1000]`, and the zero case | SAME |
| O3-2, O4-3 | `np.array(7)` cells; a 0-dim object array holding a dict, with a value changed | SAME; DIFFERENT |
| O4-2 | int array `[1, 2]` vs object array `[1, 2]` | SAME |
| O5-1 | `np.array([1], "timedelta64[M]")` with `"x"` | no raise; SAME to itself |
| O5-2 | `datetime64[2s]` 1 tick vs `[s]` 2 ticks; `1 fs` vs `2 fs` | SAME; DIFFERENT |
| O5-3 | `np.array(True)` vs `True`; a boxed NaT | SAME; null |

### Number keys (the round-5 plan and its reviews)

| Id | Case | Expected |
|---|---|---|
| F1, R2, B3, C1, C4, C2, D4, D6 | detector cases A1a to A1i of the r5 plan | unchanged (`detector_text` is kept); rerun on the new head |
| F2, R3, B1 | `0.1` vs `"0.1"`, `"1.00000000000000006e-01"` and the exact expansion; `1e23` vs `"1e+23"`; `np.longdouble("35.001417")` vs its `str` | SAME, `fail` |
| F3 | `10` vs `"1e" + "0"*640 + "1"` under int limits 640, 4300 and 0 | DIFFERENT, one verdict under each limit, no raise |
| F3b | `"10e" + "9"*640` and `"1e" + "9"*100_000` vs `10**700` | DIFFERENT, no raise |
| R4 | the A3d cells of r5 under a trapping context (prec 1; `FloatOperation`, `Inexact`, `Rounded` trapped) | the same verdicts as the default context |
| F4 | source `["1.0", "1.00"]`, output `[8, "masked"]`, plus an `email` column | no table error; `email` findings present |
| R5 | output `[bytearray(b"ab"), 2]` | no `distinct_error` |
| R6 | `a` is UTC midnight, `b` the same instant in New York; source `[a, b, a, b]`, output `[str(a), b, str(a), b]` | identical 4 of 4, column `fail` (was a table error) |
| D1 | `distinct_counts` on a frame table with `["1.0", "1.00", "x"]` | 3 |
| N-1 | `2**53 + 1` vs `float(2**53)`; `Decimal("0.1")` vs `0.1` | DIFFERENT (exact tower) |
| N-2 | `True` vs `"1"`; `True` vs `"True"` | SAME |

### Property tests (Hypothesis, fixed seed)

- P1: identity is reflexive and symmetric on drawn cells. In half the draws `b` is a transform of
  `a` (unit, box, zone, list or tuple or array, dict order), with a floor on SAME pairs.
- P2: for any finite binary64 `f`, `f` is SAME to `repr(f)`, `str(f)`, `f"{f:.17e}"` and
  `str(Decimal(f))`.
- P3: for each fast dtype, the fast path and the per-row rule give equal verdicts.

### Mutations (run on the final head, recorded with that head, recurring class 9)

| Mutation | Red test |
|---|---|
| drop step 2 for set members and map keys | DN-D2-1 |
| run the record scan only on non-null unequal pairs | CX-3b |
| let a categorical take the fast path | CX-3a |
| compute `all_same` with `Series.equals` | CX-1 |
| remove the `str(x')` spelling | PC1-3, DN-P2-2 |
| remove the float round-trip spelling | F2 |
| compare totals instead of rows | PC1-2 |
| `residual_pii` compares with `==` | route parity |
| the frame path reads identity from the Arrow table | CX-2, DN-D2-pre-a |

## Slices

Replaced by "Slices (revision 1)" in the revision section below.

## Placement and sizes

| File | Directory | CODEMAP line | Beside | Size after |
|---|---|---|---|---|
| `cell_identity.py` (new) | `src/decoy_engine/internal/` | the `internal/canonical_cell.py` row, renamed | `fk_tokens.py`, `cell_text.py` | about 560 |
| `cell_atoms.py` (new, revision 1 item 4) | `src/decoy_engine/internal/` | a new `internal/` row: the numeral grammar and the cell null rule | `pandas_missing.py` | about 120 |
| `cell_text.py` | same | existing | | about 240 (from 383) |
| `_column_facts.py` | `verification/postmask/` | existing | | about 470 (from 534) |
| `runner.py` | same | existing | | about 450 (from 517) |
| `residual_pii.py`, `policy_validation.py` | same | existing | | under 600 each |
| `test_cell_identity.py` (new) | `tests/unit/internal/` | tests beside the module | | about 500 |
| `test_identity_routes.py` (new) | `tests/unit/detection_verification/postscan/` | existing test directory | | about 300 |
| `test_cell_identity_choke_point.py` (new) | `tests/sentry/` | sentry directory | `test_cell_text_choke_point.py` | about 150 |

Every module stays at or under the repo GOAL of 600 lines (`tests/sentry/test_module_size.py`),
so also under the 800 cap. `internal/` gains one module and loses one, so its fan-out does not
change. If `cell_identity.py` passes 600, the temporal forms move to
`internal/_cell_temporal.py` in the same slice (a reason to change of their own).

## Compatibility

- `post-scan-integrity/v3` keeps its shape. Its semantics change before GA, as listed in
  "Behavior changes against main". Add these lines to the PM-1a entry in
  `docs/compatibility-contract.md` and to `changelog.d/postmask-fail-closed.md`.
- The signatures of `run_post_mask` and `run_post_mask_tables` do not change. `column_facts`
  (internal) gains `identity=`.
- `ComparisonNotPreservedError` and `RecordNotComparableError` were added by this PR and never
  released. They go with their `reason_adapter` and `scan_set` rows. `CellNotComparableError`
  maps to `post_scan/check_error`, the code the removed class used, and joins the non-pass-
  through set in `scan_set`.
- No frozen artifact, golden file, vault or disguise file is touched.

## Frozen contracts

`post-scan-integrity/v3` is the only frozen surface near this change. Its fields and shape do
not change; its identical counts and `bytes_identical` change meaning as listed in "Behavior
changes against main", recorded in the compat entry. `ColumnFacts` fields are unchanged.
`decoy-run-result/v1` is untouched. No cell value reaches a report, log or error.

## Reuse inventory

- From `canonical_cell.py`: the value forms (`NULL`, `Instant`, `Duration`, `Months`, `Seq`,
  `Map`, `Members`), `unboxed`, `is_null` and the temporal conversions, with their fixes.
- From `cell_text.py`: the numeral grammar, `_reduced`, the exponent bound, `cell_text` (bytes
  decode), `detector_text`, `UnreadableCellError`.
- From `_column_facts.py`: `_count_or_error`, `cells_distinct_or_error`, `_aligned`, `_counted`.
- Standard library: the numeric tower (`int`, `float`, `Decimal`, `Fraction`), `json.dumps`.
  NumPy and pandas: `np.datetime_data`, `Timestamp.asm8`, `Timedelta.asm8`.
- The comparator pattern of datacompy (`columns_equal`); not the library itself, since its
  mixed-type fallback is "not equal" and it has no record refusal or K4 match.
- Not reused, and why: the canary's `canonical_cells` (`verification/canary/_canonical.py:212`)
  converts Arrow arrays by type and never sees object cells. Moving it onto `cell_identity` is a
  follow-up row (DN-F-V2-3).

## Enumerations

### Exit paths

- `identity_facts` returns `IdentityFacts`, or raises `CellNotComparableError` (record, cycle,
  unhashable cell), or `UnreadableCellError` (non-UTF-8 bytes on a text side), or an error that
  passes through. Callers record the class name as the column's `identity_error`.
- `distinct_values` returns a count, or raises the same errors. `cells_distinct_or_error`
  records the class name.
- No `int()` on more than 25 digits, no decimal context read, no `.value` read, so no
  `ValueError` or `OverflowError` from number or temporal work.

### Routes

- Frame: `run_post_mask` (runner.py:81) through `_frame_tables` (runner.py:289, identity on
  frames) to `column_facts` (_column_facts.py:402) with `identity=`.
- Batch: `run_post_mask_tables` (runner.py:150) to `column_facts`, with `identity_facts` folded
  over `_aligned` batches (_column_facts.py:227).
- Frame residual: `check_residual_pii` (residual_pii.py:105) through `_frame_column_facts`
  (residual_pii.py:145).
- Frame policy: `check_policy_validation` through `_check_one_column`
  (policy_validation.py:83; the `.equals` at policy_validation.py:133 goes).

### FK shapes

N/A: the FK check reads key facts, not cell identity.

### Fields

N/A: no report or `ColumnFacts` field is added or removed. `CellView` loses `detector_text`
(internal).

### Output surfaces

- `policy_validation[]`: a record column gives an `error` finding (`_compare_failed`,
  policy_validation.py:160) where the whole table used to fail. A text export of a non-text
  cell now reads `fail` where main read `info`.
- `residual_pii[]`: the same column gives the existing "source comparison raised" `error`
  (residual_pii.py:503). The verdict code stays `post_scan/check_error`.
- Logs and exit codes: N/A, no log line is added and no exit code changes.

## Pre-mortem

If a review finds a new case, the likely cause is one of three. A kind with no `value_form` row:
A-K1 enumerates every NumPy typecode and nesting, so it shows as a red row, and an unhashable
kind is refused, never passed. A missing export spelling: the list is pinned, and a spelling
outside it is a non-goal, not a new round. A reader that compares on its own: the sentry and the
route parity test fail. A finding outside the guarantee becomes a follow-up row. A fourth
round of findings inside the guarantee goes to the owner, not to another fix round.

## Class table

| Class | Name | Closing structure | Test | Mutation |
|---|---|---|---|---|
| 1 | value | one value form per kind; exact numeric tower; attoseconds across units; calendar months apart; `asm8` reads | A-K1, P1, P2, N-1, O3 to O5, PC1-4, PC1-5 | float round trip removed; `.value` read |
| 2 | cleanup | N/A: no resources are opened | | |
| 3 | state | N/A: pure functions; `IdentityFacts.merge` is a fold over batches | route parity at `batch_rows=1` and one batch | |
| 4 | route | one authority, called by all four routes; identity computed before Arrow; sentry on other comparisons | `test_identity_routes.py`, CX-1, CX-2, DN-D2-pre-a | `residual_pii` uses `==`; frame path reads Arrow |
| 5 | referential | N/A: no FK or reference handling changes | | |
| 6 | untrusted | K4 export spellings matched per row; records refused per column; bounded exponent | DN-D2-6, DN-P2-2, F3, F3b, R4, CX-3 | `str(x')` spelling removed; record scan on unequal pairs only |
| 7 | toctou | N/A: no check-then-use on files or state | | |
| 8 | weak | run-level asserts on public entry points; property tests with derived pairs and a floor; mutation table on the final head | P1 to P3, PC1-6 | totals in place of rows |
| 9 | refactor | N/A: behavior change, not a structure-only move | | |
| 10 | frozen | `post-scan-integrity/v3` shape kept; semantic change recorded in the compat entry | compat corpus tests; `test_identity_routes.py` asserts the report keys | add a report field for the verdict vector |

## Owner question

Behavior change 1 makes an int, `Decimal`, list or dict exported as its text count as unchanged,
so the check blocks more than main does. This follows the K4 intent already in the changelog.
The question to the owner: should K4 apply to all non-text kinds (answer A) or only to numbers
and dates (answer B)? Still open.

This plan is written for answer A, which the Architect and Dennis both recommend.

If the owner answers B, the edit is: delete spelling rules 1 and 4 for containers and "other"
leaves (keep rule 1 for numbers and temporals, and rules 2 and 3), and flip these rows from SAME
to DIFFERENT (their column then reads `info` where A reads `fail`):

- DN-D2-6, the list and dict cells (the `Decimal` and int cells stay SAME);
- DN-P1-1, the `UUID` and `[1]` cells (`Timestamp` and `date` stay SAME);
- DN-P2-2, `[nan, 'a']`, `[pd.NaT, 'a']` and `[datetime(2020,1,1), 'a']` (the `timedelta` and
  nested Timestamp cells are containers too, so they flip; the top-level `timedelta` stays);
- DN-P2-3;
- PC1-2, the `"[3]"` row (identical becomes 1 of 2);
- PC1-3;
- A-K1, the `str` export of container and `V`/`O` cells;
- E-9 (revision 1), the `UUID` row.

## Revision 1, Dennis plan review

Dennis reviewed 4d78ab441: GO-WITH-FIXES (2 V1, 6 DESIGN, 4 LOW). He agrees the plan removes the
root cause. Each item is answered below by its number. Where this section differs from the body
above, this section holds.

### 1 (V1). `datetime.date` splits from the same day as a NumPy or pandas value

Fix: a `datetime.date` (not a `datetime`) maps to `Instant(attoseconds of that day at naive
midnight, aware=False)`. Python's own `date == datetime` is False; here they are SAME. That merge
fails closed. New rows:

| Id | Case | Expected |
|---|---|---|
| DN-R1-1a | `date(2020, 1, 1)` vs `np.datetime64("2020-01-01", "D")` | SAME |
| DN-R1-1b | `date(2020, 1, 1)` vs `np.datetime64("2020-01-01T00:00", "ns")` | SAME |
| DN-R1-1c | `date(2020, 1, 1)` vs `pd.Timestamp("2020-01-01")` | SAME |
| DN-R1-1d | `date(2020, 1, 1)` vs `pd.Timestamp("2020-01-01 00:00:01")` | DIFFERENT |
| DN-R1-1e | `date(2020, 1, 1)` vs `pd.Timestamp("2020-01-01", tz="UTC")` | SAME by item 8 |

### 2 (V1). NaN forms and wide floats

Fix: the null rule is "`x != x` is true", applied to scalars only (an array-like is a container),
as `pandas_missing.is_null_cell` does today. Before that test, a `Decimal` sNaN is caught with
`is_snan()`, since comparing it signals `InvalidOperation`. For a wider float (`g`) and
`clongdouble`, `np.isfinite` runs before `Fraction`: NaN is null, and an infinity maps to
`float("inf")` with its sign, so it equals a float infinity. New rows:

| Id | Case | Expected |
|---|---|---|
| DN-R1-2a | `float("nan")`, `np.float32("nan")`, `np.longdouble("nan")`, `Decimal("NaN")`, `complex("nan+0j")` | null each |
| DN-R1-2b | `Decimal("sNaN")`, default and trapping contexts | null, no raise |
| DN-R1-2c | `np.longdouble("inf")` vs `float("inf")`; `-inf` vs `-inf`; `inf` vs `-inf` | SAME; SAME; DIFFERENT |
| DN-R1-2d | `np.clongdouble("inf+0j")` vs `complex("inf+0j")` | SAME, no raise |
| DN-R1-2e | `np.longdouble("inf")` vs text `"inf"` | SAME (rule 2) |
| DN-R1-2f | `[float("nan")]` vs `[None]` | SAME (one NULL at depth) |

### 3. Vectorized fast paths and throughput

Fix: the fast path widens. Per-row work is only for cells no vectorized rule decides.

- Arrow (batch path): two arrays of one primitive or string type use `pyarrow.compute.equal`
  with an explicit null mask (`is_null` on both). Only `cell_identity.py` may call it.
- pandas masked dtypes (`Int64`, `Float64`, `boolean`) and `string` dtypes: compare on the
  values with the mask. `pd.NA` is null.
- `M` and `m` of different units: cast both to the finer unit, then compare. A cast that
  overflows falls back to the per-row rule for the column.
- K4: when one side is a text column, a vectorized `astype(str)` match of the other side runs
  first. Rows it matches are SAME. Only unmatched rows with a text cell that fits the numeral
  grammar or a temporal shape go to the per-row rule.

New throughput rows, one per kind, 1M rows each, run on the Mac node (never on the devbox). Each
must exceed the 20k rows/s floor (owner enterprise-readiness floor):

| Id | Kind | Floor |
|---|---|---|
| DN-R1-3a | int64 vs int64 (NumPy) | 20k rows/s |
| DN-R1-3b | `Int64` masked vs `Int64` | 20k rows/s |
| DN-R1-3c | `string` vs `string` | 20k rows/s |
| DN-R1-3d | `M8[us]` vs `M8[ns]` | 20k rows/s |
| DN-R1-3e | object int vs text of the int (K4) | 20k rows/s |
| DN-R1-3f | object mixed int and text, half changed | 20k rows/s |
| DN-R1-3g | list cells vs list cells | 20k rows/s |
| DN-R1-3h | Arrow string arrays on the batch path | 20k rows/s |

### 4. Import cycle

Fix: the numeral grammar (`_NUMERAL`, `_reduced`, the exponent bound) and the cell null rule
(unbox, masked constant, then `pandas_missing.is_null_cell`) move to one new leaf module,
`internal/cell_atoms.py`. It imports only `internal/pandas_missing.py`, NumPy, pandas and the
standard library. Import order inside `internal`: `cell_identity` may import `cell_text` and
`cell_atoms`; `cell_text` may import `cell_atoms`; `cell_atoms` imports neither.

New import-linter contract in `.importlinter` (type `layers`, container
`decoy_engine.internal`): `cell_identity : cell_text : cell_atoms : pandas_missing`. Mutation:
import `cell_identity` from `cell_text`; `test_import_layers.py` goes red.

### 5. One null rule for the masker and the verifier

Fix: extend `internal/pandas_missing.is_null_cell` with the sNaN guard (item 2). The masking
kernels, `derived`, `_formula` and the verifier all read it. `cell_atoms.is_null` adds only the
unboxing and the masked constant, then calls it. `transforms/windowed_date._is_null_cell` is a
third copy; it moves onto `is_null_cell` in a follow-up row, not in this PR. Row:

| Id | Case | Expected |
|---|---|---|
| DN-R1-5 | for each cell of DN-R1-2a, 2b, `None`, `pd.NA`, `pd.NaT`, `np.datetime64("NaT")` | `is_null_cell` and `cell_atoms.is_null` agree; a masking kernel treats it as missing |

### 6. Distinct counts

Fix: every distinct count in the post-mask package goes through `distinct_values`, with one
exception that is proven by parity. `policy_validation` (`nunique` at policy_validation.py:106
and :107) calls `distinct_values`. The DuckDB `column_distinct` (_column_facts.py:395) stays for
native Arrow columns on the batch path, because it counts in bounded memory. It is allowed only
for primitive, string and same-unit temporal types; any other type (list, struct, map, binary,
mixed units) goes to `distinct_values` over batches, or records `distinct_error` when the column
is too large for memory. Row:

| Id | Case | Expected |
|---|---|---|
| DN-R1-6 | per DuckDB-allowed type (int, float with NaN, string, `timestamp[us]`, bool, nulls) | `column_distinct` equals `distinct_values` on the same column |
| DN-R1-6b | a list column on the batch path | counted by `distinct_values`, never DuckDB |

### 7. Sentry scope and calls

Fix: the sentry scans all of `src/decoy_engine/verification/`, the post-scan modules in
`src/decoy_engine/execution/pipeline/` (`_post_scan.py`, `_post_scan_suite.py`), `detection/` and
`internal/cell_text.py`. It flags, outside `cell_identity.py`:

- the calls `.equals`, `.eq`, `.ne`, `.compare`, `.isin`, `.duplicated`, `.drop_duplicates`,
  `.unique`, `.value_counts`, `nunique`, `np.equal`, `np.not_equal`, `np.array_equal`,
  `np.array_equiv`, `pc.equal`, `pc.not_equal`, `pa.Array.equals`, `pd.testing.*`,
  `hash_pandas_object`, `hash_array`, `factorize`;
- `==` and `!=` where an operand is a cell name: a `_series` result, `df[...]`, `.iloc`,
  `astype(object)`, `to_pandas`, or a loop or comprehension variable over any of those
  (`for a, b in zip(src, out): a == b`);
- the definitions and the import listed in the body.

Each form has a seeded source string that the sentry test asserts is flagged. The canary entry
stays the only allowlist row. Mutation: drop the loop-variable rule; its seeded case goes red.

### 8. Aware against naive

Fix: an aware instant and a naive instant are SAME when the naive one equals the aware one's UTC
wall clock, or its own zone's wall clock. Two aware instants compare as UTC instants. Two naive
instants compare as wall clocks. `distinct_values` keeps the aware flag (an over-count, which
fails closed). Rows:

| Id | Case | Expected |
|---|---|---|
| DN-R1-8a | `Timestamp("2020-01-01 05:00", tz="America/New_York")` vs naive `"2020-01-01 10:00"` | SAME (UTC wall clock) |
| DN-R1-8b | the same aware value vs naive `"2020-01-01 05:00"` | SAME (zone wall clock) |
| DN-R1-8c | the same aware value vs naive `"2020-01-01 07:00"` | DIFFERENT |
| DN-R1-8d | `datetime(..., tzinfo=+01:00)` vs `np.datetime64` naive of its UTC time | SAME |

### 9. Red-first rows and slice sizes

Fix: every acceptance row lands in S1 as `pytest.mark.xfail(strict=True)`. A strict xfail that
passes fails the run, so no row can go green unseen. Each slice removes the marker from the rows
it turns green, and its review checks that the removed markers are exactly the rows of that
slice. The test files are larger than one 400-line slice, so S1 is split.

### Slices (revision 1)

| Slice | Content | Size |
|---|---|---|
| S1a | `test_cell_identity.py`: the pair table for value forms, nulls, temporals, records (all rows strict xfail). | about 390 test lines |
| S1b | `test_cell_identity.py`: K4 and number rows, property tests P1 to P3, edge rows E-1 to E-14 (strict xfail). | about 380 test lines |
| S1c | `test_identity_routes.py`: route parity, run rows, distinct parity, throughput rows (strict xfail; throughput marked `slow`). | about 360 test lines |
| S2 | `internal/cell_atoms.py` (grammar and null rule moved), the `is_null_cell` sNaN guard, the import-linter contract, `internal/cell_identity.py` value forms with record refusal and `CellNotComparableError`. Removes the xfail on the form, null and record rows. | about 390 changed |
| S3 | Row verdicts, all fast paths, K4 with its vectorized first pass, `identity_facts`, `IdentityFacts.merge`, `IdentityFailure`. Removes the xfail on the K4, number, property and edge rows. | about 360 changed |
| S4 | Wiring as in the body, plus `policy_validation` and DuckDB distinct counts on `distinct_values` (item 6). Removes the xfail on the route, run and distinct rows. | about 390 changed |
| S5 | Deletions as in the body, the widened sentry (item 7) with its seeded cases, CODEMAP, changelog, compat entry. Throughput rows run on the Mac node. Mutation table on the final head. | about 350 changed, plus about 1100 deleted test lines |

S2 to S3 have no production caller until S4 (proportionality exception; S4 lands before the
row closes).

### 10. Missing id rows

| Id | Case | Expected |
|---|---|---|
| A1f (r5) | two texted columns, `batch_rows=2`, nulls early, detector hits late | same rates and verdict at `batch_rows=2` and one batch |
| D2, D3, D7 (r5) | integral `Decimal` detector text; numeral text length; non-integral `Decimal` under `capitals=0` | as in r5 (kept with `detector_text`) |
| D5 (r5) | a source distinct count that raises | `source_distinct_failed` set; graded unknown diversity |
| DN-P1-3 | P1 draws paired cells | floor on SAME pairs enforced (P1) |
| DN-P1-9 | `ArrowDtype` and `string` columns | take the item 3 fast path; parity with the per-row rule |
| DN-F-LOW-2 | a map key `np.int64(1)` vs key `1` | SAME |
| DN-D2-2 | the 84 writable records in a set or dict key | N/A: cannot be built (TypeError at construction) |

### 11. Edge-case rows

| Id | Case | Expected |
|---|---|---|
| E-1 | empty source and output | comparable 0, `all_same` true, no raise |
| E-2 | both columns all null | comparable 0, `all_same` true |
| E-3 | source null, output value, every row | comparable 0, `all_same` false |
| E-4 | lengths differ | `identity_facts` is never called; the existing row-count finding stands |
| E-5 | source and output with different index labels, same order | compared by position |
| E-6 | duplicate column names | first position, as now |
| E-7 | `0.0` vs `-0.0` | SAME |
| E-8 | `True` vs `np.bool_(True)` vs `1` | SAME |
| E-9 | `uuid.UUID(int=1)` vs its `str` and its `.hex` | SAME; DIFFERENT (`.hex` is not listed) |
| E-10 | `[]`, `set()`, `{}`, `()` against each other | `[]` and `()` SAME; the rest DIFFERENT |
| E-11 | `b"ab"` vs `"ab"`; `b"\xff"` vs `"x"` | SAME; `UnreadableCellError` recorded for the column |
| E-12 | object int `10**30` vs `Decimal(10**30)` vs `"1e30"` | SAME all three |
| E-13 | categorical with unused categories, codes reordered | compared by values; unused categories ignored |
| E-14 | `pd.NA` in a `string` column vs `None` in an object column | both null |

### 12. Failure type

Fix: `IdentityFailure` is a frozen dataclass with one field, `error: str` (the class name). The
`identity=` keyword of `column_facts` takes `IdentityFacts | IdentityFailure`, so a bare string
cannot be mistaken for a count. `column_facts` sets `identity_error` from `failure.error`.
Mypy checks the union at each caller.
