# PM-1 comparison authority redesign

Status: revision 2 plan. Reviewed against branch `0a0547fec` and main `9812da814`.
The revision 2 rows are implementation requirements. The earlier review IDs stay for traceability.

PR #784, branch `fix/postmask-fail-closed`. Risk R2 covers the value-leak check.
This plan replaces the comparison parts of the November 25 number-key and November 27
canonical-cell plans. Keep the PM-1a writer query.

## Why comparison moves before conversion

The branch compares frame cells, converted Arrow arrays and text keys. The canonical walk
at `canonical_cell.py:130` can see any of the three. Standalone policy uses pandas equality
at `policy_validation.py:133`. Conversion loses set order semantics, nested units and absent
struct fields. The totals check at `runner.py:251` can miss offsetting row errors.
Compare the source and output at the same position while both still have their original types.

Reuse typed comparators, null-safe equality and Python's exact numeric comparisons.
Arrow kernels handle common typed arrays. The existing temporal conversion handles exact
units. A closed list of spellings covers whole-cell text exports. Refuse unsupported cells.

## The design: one comparison authority

### The choke point

New module `src/decoy_engine/internal/cell_identity.py`. It is the only place that decides
whether a source cell and an output cell are the same value. Public names:

- `identity_facts(src: Column, out: Column) -> IdentityFacts`. Here `Column` means a pandas Series or a typed Arrow array. Compare by position. Return
  `comparable` (both non-null), `identical` (same value) and `all_same` (every row is the same
  value or both null). `IdentityFacts.merge` folds batches.
- `distinct_values(column: Column) -> int`. The non-null distinct count on the value forms.
- Both readers import `cell_atoms.is_null`. It unboxes and calls the shared scalar predicate.
- `CellNotComparableError(DecoyError)`. Fixed text, no value, raised with no context
  (recurring class 3).

Each reader uses the authority through the following calls.

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

1. **Unbox.** A 0-dim array is its payload. `np.ma.masked` is null. A cycle on the active walk path
   raises `CellNotComparableError`.
2. **Refuse records.** A NumPy structured value (`np.void` with fields, a structured ndarray)
   anywhere in either cell, at any depth (sequence item, set member, map key or value), raises
   `CellNotComparableError`. This check runs on every cell, null or not, before any shortcut.
3. **Nulls.** Both null: BOTH_NULL (not comparable, counts toward `all_same`). One null:
   ONE_NULL (not comparable, not same).
4. **Text against non-text.** If exactly one side is text (a `str`, or bytes, which decode as
   strict UTF-8 by the existing `cell_text` rule), the row is SAME when the text is one of the
   export spellings of the other cell (below). Else it is DIFFERENT.
5. **Otherwise** the row is SAME when the authority matches their value forms recursively (R2-V6 and R2-V7). Text against text is
   exact string equality, as on main.

`value_form` is the value half of today's `canonical_cell`, with every spelling field removed:

| Cell | Form |
|---|---|
| bool, `np.bool_` | `bool` (Python `True == 1`, as on main) |
| int, `np.integer` | `int` |
| float, `np.floating` up to 64 bits | `float` |
| wider float (`g`) | `Fraction(as_integer_ratio())`, exact |
| complex | exact real and imaginary components across widths (R2-V6) |
| `Decimal` | itself (exact `==` and hash against int and float) |
| `np.datetime64`, `pd.Timestamp`, `datetime` | `Instant(attoseconds, aware)`; Y and M instants at the first midnight of their period |
| `np.timedelta64`, `pd.Timedelta`, `timedelta` | `Duration(attoseconds)`; Y and M as `Months`; generic unit as `int` |
| NaT, NaN, None, `pd.NA` | `NULL` at any depth |
| list, tuple, namedtuple, ndarray of any rank | `Seq(items)` |
| dict, Arrow map identified by its Arrow type | unordered key/value pairs with unique keys (R2-V7) |
| set, frozenset | `Members(frozenset)` |
| bytes, bytearray, memoryview | `bytes` (top-level bytes are text, step 4) |
| `date` | naive midnight instant |
| other hashable object (`UUID`, `Period`, `Interval`) | itself, compared by its own `==` |
| other unhashable object | `CellNotComparableError` |

The temporal rows keep the reviewed fixes: `asm8` reads, never `.value` (DN-P1-2); the reserved
NaT integer is excluded (PC1-4); calendar months convert with Python ints, so no int64 wrap
(PC1-5); aware datetimes normalize to UTC (DN-P1-5).

Numbers compare by the Python numeric tower, so `int(2**53 + 1) != float(2**53)` and
`Decimal("0.1") != 0.1`. Both are true differences. No binary64 rounding enters identity.

### Export spellings (K4)

A non-text cell `x` matches the text `t` when any of these holds. `x` is the original cell, and
`x'` is its recursive Python-native form, including NumPy leaves inside Python containers. R2-V4 and R2-V5 define the renderings.

1. `t` is `str(x)`, `repr(x)`, `str(x')` or `repr(x')`.
2. `x` is a real number (bool included) and `t` matches the numeral grammar (kept from round 5:
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

Use the typed kernels in revision 1 item 3 with the masks and bounds in R2-V3 and R2-V6.
For K4 use the eligibility and fallback rules in R2-V4. Resolve categorical codes to their values.

### What the frame path carries

Before conversion, compute identity on aligned frame columns. Pass the typed result by name through
`identity=`. Store each present side's distinct count and error in its existing `CellView`.
Do this for every requested frame count, including unpaired columns. See R2-V1 and R2-V7.
Batch readers pass typed arrays directly. Detectors can still use a pandas view.
Use detector text only where the healthy frame column needs a text fallback.
Remove the comparison keys, `_require_preserved` and `ComparisonNotPreservedError`.

### The sentry

Use the scoped AST guard in revision 1 item 7 and the seeded cases in R2-D2.
Use the public route matrix in R2-D3. Compare each route's observable findings to the expected
facts. Mutate the residual reader to use `(src == out).sum()`. Its parity case must fail.

## Guarantee and non-goals

Guarantee, on every post-mask route:

- An unchanged source cell counts as identical when the output holds the same value (by the
  value forms above) or the value as one of the listed export spellings.
- A column that holds a NumPy record on either side fails that column with an `error` finding
  (`CellNotComparableError`). It never fails the whole table, and it never passes.
- `bytes_identical`, `comparable` and `identical` come from one verdict vector, so they cannot
  disagree.
- Identity never reads an Arrow conversion of a frame, a text key, or a column total.
- Refusal and decode errors have fixed text and empty exception context. Propagate coded
  pass-through errors. Record other failures by class alone.
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
5. For an unchanged hash column, the constant exception requires two successful counts of at most one. R6 pins a constant source exported in two forms.

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
| Spelling work on a large column | slow | Build candidates lazily for eligible mixed pairs. See R2-D3 for the timed gate |
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

Move the shared temporal conversion and numeral primitives to `cell_atoms.py` (R2-D1).
Keep detector formatting in `cell_text.py`. Only `cell_identity.py` owns pair semantics and dispatch for distinct counts.

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
`tests/unit/detection_verification/postscan/identity/test_identity_routes.py` (route parity and runs).
Each pair runs through the authority. Run each public route that preserves the fixture type (R2-D3). Synthetic values only.
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

The implementation schedule is in revision 1 item 9.

## Placement and sizes

| File | Directory | CODEMAP line | Beside | Size after |
|---|---|---|---|---|
| `cell_identity.py` (new) | `src/decoy_engine/internal/` | the `internal/canonical_cell.py` row, renamed | `fk_tokens.py`, `cell_text.py` | about 560 |
| `cell_atoms.py` (new, revision 1 item 4) | `src/decoy_engine/internal/` | a new `internal/` row: the shared temporal forms, unboxing and number primitives | `pandas_missing.py` | about 250 |
| `cell_text.py` | same | existing | | about 240 (from 383) |
| `_column_facts.py` | `verification/postmask/` | existing | | about 470 (from 534) |
| `runner.py` | same | existing | | about 450 (from 517) |
| `residual_pii.py`, `policy_validation.py` | same | existing | | under 600 each |
| `test_cell_identity.py` (new) | `tests/unit/internal/` | tests beside the module | | about 420 |
| `test_cell_identity_exports.py` (new) | `tests/unit/internal/` | behavior of the same internal module | K4 and property rows | about 410 |
| `test_identity_routes.py` (new) | `tests/unit/detection_verification/postscan/identity/` | new test package with empty `__init__.py` | route and timing rows | about 420 |
| `test_cell_identity_choke_point.py` (new) | `tests/sentry/post_scan/` | post-scan guards | `test_post_scan_choke_points.py` | about 150 |

The size goal is 600 lines per module. Count setup and fixture lines in each estimate.
The two new internal modules replace one. The package grows from 14 Python files to 15.
Split test work by the concerns in the table. Put route tests under the named identity package.

## Compatibility

- `post-scan-integrity/v3` keeps its shape. Its semantics change before GA, as listed in
  "Behavior changes against main". Replace superseded claims in the PM-1a entry in
  `docs/compatibility-contract.md` and to `changelog.d/postmask-fail-closed.md`.
- The signatures of `run_post_mask` and `run_post_mask_tables` do not change. `column_facts`
  (internal) gains `identity=`.
- `ComparisonNotPreservedError` and `RecordNotComparableError` were added by this PR and never
  released. They go with their `reason_adapter` and `scan_set` rows. `CellNotComparableError`
  maps to `post_scan/check_error`, the code the removed class used, and joins the non-pass-
  through set in `scan_set`.
- No frozen artifact, golden file, vault or disguise file is touched.

## Frozen contracts

See R2-L2 for each frozen owning path, its compatibility decision and its gate.

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

Use A-K1 to detect a missing kind, the K4 rows to detect a missing spelling and route parity
to detect a second comparator. Escalate another round of findings inside the guarantee to the owner.

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
root cause. Each item is answered below by its number. Revision 2 incorporates the later Codex corrections.

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
`clongdouble`, test each component before forming a ratio (R2-V6). NaN is null. Each infinite component maps to
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

Compare native NumPy, pandas masked, string and Arrow columns in the authority.
Use the same two null masks for counts and equality (R2-V3). Prove cross-unit casts fit (R2-V6).
Use the exact scalar fallback for unresolved pairs. Apply R2-V4 before any K4 shortcut.

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

Share the numeral grammar and temporal converter below both readers. R2-D1 specifies the layer contract and mutation.

### 5. One null rule for the masker and the verifier

Extend `pandas_missing.is_null_cell` for masked constants and Decimal sNaN. Unbox through
`cell_atoms` before testing a boxed cell. Keep the existing masker on the shared scalar predicate.
Track the older windowed-date copy in R2-L3.

| Id | Case | Expected |
|---|---|---|
| DN-R1-5 | for each cell of DN-R1-2a, 2b, `None`, `pd.NA`, `pd.NaT`, `np.datetime64("NaT")` | `is_null_cell` and `cell_atoms.is_null` agree; a masking kernel treats it as missing |

### 6. Distinct counts

Use the original frame counts in R2-V1. For batch counts use the closed allowlist and fallback in R2-V2.

| Id | Case | Expected |
|---|---|---|
| DN-R1-6 | each DuckDB type listed in R2-V2, with nulls | `column_distinct` equals `distinct_values` on the same column |
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
- imports of the retired canonical module and local comparator definitions in the comparison paths (R2-D2).

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

S1 records each existing route result on the test node. Keep passing rows active. Mark only
observed failing parameters with strict xfail and the specific expected failure. Exercise new
API cases through a function-local import. Scope any expected missing-module failure to that
module. Once the API exists, remove that marker and check the expected result.

| Slice | Deliverable and marker removal | Budget |
|---|---|---|
| S1a | Value forms, nulls and record cases in `test_cell_identity.py` | 390 lines |
| S1b | Export and property cases in `test_cell_identity_exports.py` | 380 lines |
| S1c | Route, distinct and slow Mac timing cases in the identity test package | 360 lines |
| S2 | Shared atoms, missing predicate, layers, forms and refusal. Move both temporal consumers together. Activate their rows | 390 lines |
| S3 | Identity, merge, kernels and exports. Activate pair and property rows | split into increments under 400 changed lines |
| S4 | Frame facts, typed batches, projections and public readers. Activate route and count rows | split by boundary under 400 changed lines |
| S5a | Replace the retired production paths. Land the guard, CODEMAP and compatibility edits | increments under 400 changed lines |
| S5b | Delete retired key tests after their run-level replacements pass | three deletion batches of at most 400 lines |
| S5c | Remove remaining throughput xfails. Run the full timing matrix on the Mac. Record final-head mutations and gates | test-node evidence |

Count additions and deletions in each slice. S2 and S3 gain their production callers in S4.

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

## Revision 2, Codex plan fixes

The review used branch `0a0547fec`. The main comparison is `9812da814`.
The rows below specify gates for implementation on the test nodes.

### V1 findings

**R2-V1. Count original frame cells.** In `runner.py:231`, Arrow can fill a missing struct
field with null. An unchanged diverse source then looks constant to `policy_validation.py:242`.
Before conversion, call `cells_distinct_or_error` once per selected column on each present side.
Save the result in that side's `CellView`, even for a column that converts successfully.
Both `column_facts` and `distinct_counts` read it through `_distinct_or_error` at
`_column_facts.py:384`. Preserve identity separately. A failed source count sets
`source_distinct_failed`. A failed output count sets the count error without setting that flag.
Grade using the existing error path. A failed count cannot establish a constant source.
In the shared policy grader `_decide`, apply the constant exception only when both counts
are at most one. R6 has one source instant and two output forms. Its four matching rows must block.

| Test | Input and boundary | Required result |
|---|---|---|
| R2-V1a | Call `run_post_mask` on unchanged hash rows `[{"k": None}, {}]` | Source and output distinct counts are 2. Both rows match. Policy gives a blocking fail. |
| R2-V1b | Inject an uncoded count failure on each side separately with a healthy neighbor | Preserve the other count and identity. Record the class alone. Only source failure sets the source flag. Still grade the neighbor. |
| R2-V1c | Run R6 and a control with the same single instant on both sides | R6 counts 1 and 2, matches 4 and fails. The control counts 1 and 1 and gets constant-source info. |

**R2-V2. Count batches without losing precision.** Keep one dispatch for post-mask counts.
The DuckDB path at `profiling/_scan_integrity.py:552` accepts bool, signed and unsigned integers,
float32/64 and UTF-8 strings after parity checks. Include ordinary and large UTF-8 in those checks.
Use exact counting for all temporal types. Read timestamp and duration ticks in their declared
unit, including timezone metadata. Avoid a Python datetime conversion that truncates nanoseconds.
For other types, feed exact distinct forms into one state for the entire column and side.
Use the caller's memory limit. Refuse the count with a count error before exceeding its budget.
Discard partial counts. Keep stream length verification and coded-error propagation.

| Test | Input and boundary | Required result |
|---|---|---|
| R2-V2a | Arrow `timestamp[ns, UTC]` and `duration[ns]`, ticks 1 and 2, unchanged hash | Exact count 2 on each side for each type. Policy fails. Neither column enters DuckDB. |
| R2-V2b | List rows `[1], [2], [1]` at batch sizes 1, 2 and 3 | Count 2 each time. A forced budget failure gives unknown diversity. |
| R2-V2c | Each allowed type with duplicates, null and boundary values. Include NaN for floats | DuckDB equals the authority's exact count. A new type defaults to exact counting. |

**R2-V3. Share missing-value semantics.** In `pandas_missing.py:8`, recognize
`np.ma.masked` by identity and Decimal signaling NaN before scalar comparison.
Keep containers out of scalar self-comparison. Reuse this predicate after unboxing.
For each side of an Arrow floating pair, combine physical nulls with valid NaNs.
Use the validity mask plus NaN in valid payloads for pandas masked floating arrays too.
Apply equality only to rows valid on both sides. Count those rows as comparable.
Count equal comparable rows as identical. Both-missing rows also preserve `all_same`.

| Test | Input and boundary | Required result |
|---|---|---|
| R2-V3a | Compare valid NaN, physical null, 1 and 2 with themselves and with the two missing forms swapped. Use Arrow and pandas FloatingArray with explicit masks | Comparable 2, identical 2, all same, distinct 2. Replace one missing output with 3 and all same becomes false. |
| R2-V3b | Send masked constant and Decimal sNaN through the masking kernel and the authority | Both treat each cell as missing. No trap fires. |

**R2-V4. A shortcut proves only a positive match.** Resolve categorical values first.
Validate both cells for cycles and records before the null and export rules.
A primitive dtype can prove the record check for a whole array. Decode a byte operand through
the existing strict UTF-8 reader. Compare two text operands literally after decoding.
For exactly one text operand, apply the selected A or B kind rule. A typed shortcut may accept
a match only if its rendering is one of the specified stable spellings. Every eligible miss
tries the entire scalar list for that kind. Recurse through Python containers when building
the native export form. Preserve container order and representation where the spelling needs it.
Skip a JSON candidate if that export cannot represent the value, then try the other candidates.

| Test | Compare shortcut enabled and forced scalar in both directions | Required result |
|---|---|---|
| R2-V4a | Original and native str and repr, Decimal repr, PC1-3, default and sorted JSON of a dict with reversed keys | Each listed spelling matches under A. Under B the numeric matches remain. The container matches flip. |
| R2-V4b | Decimal repr as UTF-8 bytes, invalid UTF-8, numeric exponent, pandas temporal string, ISO and NumPy temporal strings | Match each listed valid spelling under A and B. Invalid bytes give the fixed column error. |
| R2-V4c | Compact JSON `"[1,2]"` vs list, a null vs its printed name, record vs its printed value | DIFFERENT, ONE_NULL, column error. Every shortcut result equals the scalar result. |

**R2-V5. Make export spellings independent of interpreter settings.** Use the digit routine
at `cell_text.py:236` for Python integers of any size. It reads the digits from an exact
Decimal tuple. Keep the sign. Build Decimal str and repr from sign, digits and exponent.
Accept both exponent letter cases that the listed exporters produce. Preserve scale and repr
quoting. Use the same numeric leaf renderers inside original, native and JSON spellings.
For nested Decimal values, match the whole rendering under each fixed capitals choice.
For JSON, preserve Python's quoting, separators, order and supported key conversions.
A nested integer must still be an unquoted JSON number. Use the stable tokens before rendering
a container, including arrays and mapping keys. Never pass a limit-sensitive value or its
container to bulk string conversion, ordinary int formatting or the default JSON encoder.
Keep the exact parser bounded. Use the existing ASCII grammar with `fullmatch`.
Do not change the process digit limit or the caller's Decimal context to make a match.

| Test | Fixed text across settings | Required result |
|---|---|---|
| R2-V5a | Compare `10**700` to `"1" + "0"*700`, and the negative case. Under A also embed each as a list element and dict value in fixed JSON | SAME at integer limits 640, 4300 and 0. A one-digit change differs. Test both directions and both dispatch paths. |
| R2-V5b | Use literal outputs `"[Decimal('1E+8')]"` and `"[Decimal('1e+8')]"` against the same list. Also test top-level Decimal repr | Same answers at capitals 0 and 1, including the R4 trapping context. Both list spellings match under A and differ under B. Decimal repr matches under both. |
| R2-V5c | Combine the two settings matrices. Compare a dict with a huge int and Decimal to its fixed default JSON export under A | SAME in all six settings. No exception, rounded value or setting change. |

**R2-V6. Use exact temporal and complex forms.** Keep the first-of-month converter at
`canonical_cell.py:198`. A calendar instant starts at midnight on day one.
A calendar duration has a month count. For fixed units, compare tick multipliers using
Python integers. Before a vector cast, check the non-null extrema of both arrays in the
target unit. Exclude the NaT sentinel and check exact representability. Use the exact
scalar path when bounds or units preclude a safe cast.

Compare every complex width as two real components. A NaN in either component makes the
cell null. Keep each finite component's exact ratio and each infinity's sign and position.
Compare real numeric operands as having imaginary part zero. Distinct forms must hash equal
for equal numeric values across widths. Apply the aware/naive rule at every instant leaf.
Keep UTC ticks and the original local wall time for pair comparison. Keep the awareness tag
and UTC ticks for distinct counting. Mixed-awareness matching can be non-transitive.
Use positional recursion for sequences. For unordered collections require a one-to-one pairing
of recursively matching members or key/value pairs. Use a complete matching when ambiguous.

| Test | Pairs in both directions | Required result |
|---|---|---|
| R2-V6a | January 2020 in Y and M instant units vs January 1 midnight. Compare one month duration to 31 days | Instants SAME. Durations DIFFERENT. |
| R2-V6b | Year 2500 in microseconds vs its wrapped nanosecond cast. Also compare the original with a representable coarser equivalent | DIFFERENT for the wrapped value. SAME for the equivalent. Test the NaT boundary and the last safe tick. |
| R2-V6c | Python complex vs clongdouble at (1.5, 2), (+inf, 2), (1, -inf). Change only the other component. Compare (1.5, 0) to real 1.5 | Equal pairs match and count once. Changed components differ. A NaN component is null. |
| R2-V6d | Put DN-R1-8a through 8c in a list, a map value and a set. Include an unordered pair with two possible partners for one member | UTC and local matches hold at depth. The unrelated instant differs. Reordering leaves the verdict intact. |

**R2-V7. Preserve map origin and contain cycles.** Pass Arrow arrays with their schema
into the authority. Retain child types in the walk, including maps inside lists or structs.
Read pandas Arrow extension columns with their Arrow type. A plain Python list of pairs
is a sequence. Arrow maps and Python dicts with unique exact-form keys compare as maps.
Refuse an Arrow map with duplicate exact keys before any conversion to dict or frozenset.
Use the same validated walk for identity, counting and export eligibility.
Track container and box identities on the active recursion path. Remove each on return.
A shared child reached from a sibling is valid. A back edge gives the fixed column error.

Validate frame columns before any Arrow call, including unpaired or unaligned columns.
On refusal keep the column name, row count and failure. Tag the refused side with its typed failure. Use a length-matched null placeholder
where the internal table needs a physical column. Skip conversion, detector rendering and value
tallies for the refused data. Every consuming check must observe the failure before using that
placeholder. Keep the configured check error visible to the blocking verdict. Continue with the other columns.

| Test | Input and boundary | Required result |
|---|---|---|
| R2-V7a | Reorder a typed Arrow map, a nested Arrow map and an ordinary frame list of pairs | Maps SAME, list DIFFERENT. A changed map value differs. A map with duplicate keys gives a column error. |
| R2-V7b | Self-linked list, dict and 0-D box, plus one child shared twice without a cycle | Each cycle gives a fixed error within 5 seconds. Shared child matches. |
| R2-V7c | Put each cycle beside a diverse unchanged hash column at `run_post_mask`. Also run standalone residual | No Arrow or detector call sees the cyclic cell. The column gives an error. The healthy neighbor retains its expected finding. |

**R2-V8. Isolate standalone failures and select first positions.** Move first-position lookup
from `runner.py:212` into the common post-mask input code. Use it for both sides before
pandas lookup, Arrow schema lookup, projection or conversion. Use `iloc` for frame columns
and field indices for Arrow. Resolve duplicate names before name-only lazy or staged projection.
If the reader only projects by name, read physical fields without name projection and select
the first indices before exposing a batch. Share the same resolution in cast and gate projections.
Keep the first schema field, its type and its values together. Export this selector via
`verification.postmask` for pipeline callers.

In `policy_validation.py:103`, route each count through `cells_distinct_or_error`.
Use the same per-column failure handling for identity and both counts as the rest of post-mask.
Preserve missing-column and length findings. On aligned input, check the typed failure or count
error before calling `_decide`. Propagate coded pass-through errors. Record other errors by
class alone. Standalone residual must handle a refused cell before invoking its detectors.

| Test | Public reader inputs | Required result |
|---|---|---|
| R2-V8a | Record column first, diverse unchanged hash column second. Run standalone policy, residual and frame runner | Record has a column error. The second column gets its normal finding. No table abort or cell text. |
| R2-V8b | Duplicate labels with different types and conflicting verdicts. Vary the second field and reverse field order | Each frame reader and `run_post_mask_tables` grades the first physical field on each side. One policy finding per configured column. No ambiguous Arrow lookup. |
| R2-V8c | Inject count-only failures and a coded pass-through in standalone policy | Uncoded failure gives a column error and preserves neighbor grading. The coded exception propagates unchanged. |

### DESIGN findings

**R2-D1. Put common conversions below both consumers.** Move the temporal classes and exact
converter at `internal/canonical_cell.py:179` through line 240 into `internal/cell_atoms.py`.
The detector at `internal/cell_text.py:357` uses that converter and the retained temporal formatter
from `canonical_cell.py:310`. Identity uses the same converter. Keep the formatter in `cell_text`.
Share the numeral grammar, reduction, exact digit extraction and unboxing through `cell_atoms`.
Keep scalar missing-value decisions in `pandas_missing`. Give the new layers contract its own
section in `.importlinter`, with container `decoy_engine.internal` and these ordered layers.

```ini
layers =
    cell_identity
    cell_text
    cell_atoms
    pandas_missing
```

| Test | Gate | Required result |
|---|---|---|
| R2-D1a | Inspect the actual contract and run the isolated layers gate. Seed an import of identity in cell_text | Clean dependency direction passes. The reverse edge fails import-linter. No new ignore entry. |
| R2-D1b | Run retained detector text rows D2/D3/D7. Feed the detector and identity the same sub-nanosecond and calendar-unit temporal fixtures | Retained detector expectations and exact identity pass. Both consumers use the one temporal converter. |

**R2-D2. Normalize imports in the scoped guard.** Put the sentry in
`tests/sentry/post_scan/test_cell_identity_choke_point.py`. Resolve qualified calls through
module aliases and direct imported aliases. Follow column bindings through assignments, indexing
and loops. Flag the listed operators and methods when applied to comparison inputs.
Scope retired definition names to the comparison modules. Include `identity_counts`,
`canonical_cells`, `_compared`, `_frozen` and `key_text`. Restrict the canary exception to
its existing helper. Scan production imports of the retired module. Check every guard exception
by its file and symbol. Keep legitimate detector frequency counts outside the comparison rule.

| Test | Seed | Required result |
|---|---|---|
| R2-D2a | `from numpy import equal as eq` then `eq(src, out)`, a qualified alias, and a loop over paired column values | Each comparison is flagged. Removing alias normalization or loop tracking fails its seed. |
| R2-D2b | Comparator-local `_frozen`, provider helper at `providers_v2/_faker_draw_contracts.py:54`, unrelated metadata comparison | Only the comparator-local copy is flagged. Run the guard on actual source as well as seeds. |

**R2-D3. Measure the production routes.** Replace the identity-side `_series` call at
`verification/postmask/_column_facts.py:439` with positional extraction of each aligned Arrow
array. Pass the typed arrays straight to `identity_facts`. Keep pandas conversion for detector
consumers. On the Mac test node use one worker and one thread for native libraries and DuckDB.
Use one million rows per measured run. Warm up once. Record elapsed time and rows/s for three
repeats by dtype and route, on the final head. Time the public call through its verdict, including
projection, conversion, counts and grading. For staging, prepare the input fixture outside the
timer and time the native pre-commit gate including its staged read and decision.

| Test | Route and fixtures | Required result |
|---|---|---|
| R2-D3a | `run_post_mask` on all DN-R1-3a to 3g frame fixtures | Each repeat exceeds 20k rows/s. Assert expected findings and counts. |
| R2-D3b | `run_post_mask_tables` on out-of-core batches and the actual native staged pre-commit gate at `execution/pipeline/_post_scan.py:338`. Run integer, nullable integer, float with valid NaN, string and exact cross-unit timestamp cases on each | Each route and kind exceeds 20k rows/s per repeat. Grade equals the scalar fixture oracle. Inspect staged schema and values to confirm the tested representation. |
| R2-D3c | Instrument the scalar pair comparator on the same common typed columns in a separate untimed run | Zero scalar pair calls on each route. Batch and staged identity receive Arrow arrays. No input-side pandas materialization for comparison. |
| R2-D3d | Route parity for native-safe pairs. Test sets, records and cycles at original-frame entry points | Each reader agrees on the facts it exposes or the resulting finding. Native tests use fixtures that survive staging with the intended type. |

### V2-LOG plan notes

| Finding | Plan decision | Acceptance row |
|---|---|---|
| R2-L1. Test scheduling and size | Split the pair suites and deletion batches as shown in Placement and S1 to S5c. Retained green rows run from S1. | Collect S1 on the node with the future module absent. Verify each strict xfail against its observed failure. In S5c verify zero throughput xfails and record the Mac runs. |
| R2-L2. Frozen owning paths | `profiling/scan_set.py` changes exception classification for scan-set/v1. Its wire fields and reader stay compatible. `reason_adapter.py` and `reasons/runtime/_part3.py` touch public reason translation and the registry. Retain the additive unreleased `cell_unreadable` reason. Reuse the registered check-error reason for comparison refusal. `verification/postmask/_blocked.py` owns the public blocked error. Preserve its public type and the documented gate behavior. The post-scan v3 counts change as listed above. | Run scan-set round trips, registry baseline, public API and exception hierarchy checks, blocked-error tests and the mapped v3 post-mask runner and v2 reader tests on the node. Verify the existing tags and reason pins. Replace the obsolete key, band and comparison-error claims in the changelog and compatibility entry. |
| R2-L3. Windowed-date helper | `transforms/windowed_date.py:302` predates PM-1. Track migration to the shared predicate for V2. | At migration, compare the helper and shared predicate on the DN-R1-5 missing cells. R2-V3b separately gates the shared masker's masked-constant behavior in V1. |

**V2-LOG size note.** This revision retains the earlier acceptance tables and review IDs.
Log the plan in the 800 to 900 line cleanup band.

### Final plan self-review

All eight V1 findings and three change-created DESIGN findings have acceptance rows.
The three review notes have implementation or follow-up checks. The recurring-defect review
adds a strict typed failure handoff, fixed exceptions raised outside handlers, full-string
numeral matching, alias-aware guard seeds and final-head mutation evidence. Keep existing
wire types, reader versions and pins. Run the gates on test nodes with failures visible.

GO for the plan. The owner still chooses A or B. Implementation and test-node evidence remain.
