# Post-mask number keys, round 5

Status: plan

Date: 2026-11-25. PR #784 (POSTMASK-FAIL-CLOSED), head c1430bb57, after Codex delta 3 (NO-GO)
and two Codex plan reviews of this plan (r5a and r5b, both NO-GO; findings folded in below).
Supersedes the rule section of `2026-11-25-post-mask-value-key-round4.md`; the rest of that plan
stays as history. Risk: R2 (value-leak check). The PR has hit the 3-round review cap twice, so
this round changes the plan, not only the code. This is plan round 3 of 3.

Rules consulted: `00-universal.md`, `risk-and-exceptions.md`, `development-loop.md`,
`bugfix.md`, `testing.md`.

## Problem

On a column Arrow refuses (mixed types), `_frame_table` puts one text key per cell into the
table (src/decoy_engine/verification/postmask/runner.py:211). Every reader of that table column
then reads the key: the identity count, the bytes-identical flag, the distinct counts, the
detectors and the value tally. Round 4 made the key an exact numeric value. Codex delta 3 found
four V1 fail-open or false-block cases on c1430bb57 that 6efd06af7 handled:

1. Detector input lost digits. Text `212555.0100` keys as `212555.01`, so the `us_phone` (and
   `device_id`) detector misses an unchanged phone column.
2. A float written as its short text (`0.1`) no longer counts as unchanged. The float keys as
   its exact expansion `0.1000000000000000055511151231257827021181583404541015625`.
3. The exponent goes through `int()` (src/decoy_engine/internal/cell_text.py:182), so the key
   depends on `sys.set_int_max_str_digits`. `"1e" + "0"*640 + "1"` keys as text at limit 640 and
   as 10 at limit 4300. `"10e" + "9"*640` parses and then raises `ValueError` when the exponent
   is formatted (src/decoy_engine/internal/cell_text.py:143).
4. Source spellings `"1.0"` and `"1.00"` share a key, so the source looks constant through the
   keys, and `_require_preserved` raises `ComparisonNotPreservedError`
   (src/decoy_engine/verification/postmask/runner.py:262), which blocks the whole table.

The plan reviews then found these cases against earlier drafts of this plan:

- r5a: (R2) the comparison key changed the digits a detector saw for a Luhn-valid integer above
  2**53; (R3) `f"{0.1:.17e}"` keyed apart from 0.1; (R4) `Decimal(float(text))` raises under a
  `FloatOperation` trap; (R5) `bytearray` cells make a cell count raise; (R6) dropping both
  directions of the diversity guard lets an equal-cells-but-split-keys source pass.
- r5b: (B1) float `1e23` and its `repr` text `"1e+23"` keyed apart; (B2, B4) running the
  detectors on two arrays and keeping the larger hit count can downgrade a grade and depends on
  batch size; (B3) `Decimal("12.0000000000000001")` and `Decimal("212555.0100")` lost detector
  digits.
- r5c (round 3, NO-GO, fixed in this text without a fourth review): (C1) integral
  `Decimal("4111111111111111.00")` read as written hides a PAN; (C2) `np.longdouble("35.001417")`
  rounds to a different binary64 than its own `str` export; (C3) no mutation proves the one-run
  detector rule; (C4) integral detector text rendered `10**33` as `1E33`.

## Root cause

One array does two jobs. The comparison needs a value identity that ignores spelling. The
detectors and the diversity count need the cells as written. Each round tuned the one key for
one job and broke the other. The drafts of this plan then tried to make the detectors see both
spellings and the key keep exact digits; each half broke a case of the other. The fix gives
each reader one array that serves only that reader:

| Reader | Reads after this plan |
|---|---|
| identity count, bytes-identical flag (`_add_identity`) | the comparison key |
| detectors (`_add_detectors`) | the detector text only (one run per batch, as now) |
| source and output distinct counts | the cells (`source_distinct`) |
| value tally (`_ValueTally.add`) | the key array, unchanged (string type, nulls only) |
| `_require_preserved` | cells and keys: lost equality, and constant cells with varied keys |

Finding 3 has its own cause: exponent text reaches `int()` with no bound.

## Established solutions

Searched: Python float formatting docs and the shortest round-trip literature, the General
Decimal Arithmetic spec and Python `decimal` docs (exact comparison, `as_tuple`, context traps),
Python and NumPy numeric comparison and promotion rules, and CPython's int-to-str limit docs
(`sys.int_info`). Found:

- NumPy and pandas compare mixed int, float and Decimal data by promoting to float64. The key
  follows that pattern: every finite number in binary64 range keys as its nearest binary64.
- Correctly rounded decimal-to-binary64 parsing (Clinger, "How to Read Floating Point Numbers
  Accurately", 1990; CPython `float(str)`), and shortest round-trip printing (Steele and White,
  1990; Python `repr(float)` uses David Gay's shortest mode). Together they give one canonical
  text per binary64 for every spelling that rounds to it: `repr`, `.17e`, `.17g`, exact
  expansion, integer digits.
- General Decimal Arithmetic "reduce" form, built from `Decimal.as_tuple()` with no context
  (kept from round 4) for values outside binary64 range. `as_tuple` and `str(Decimal)` read no
  context and raise no trap.
- `sys.int_info.str_digits_check_threshold` is 640, the lowest limit a process can set. Any
  `int()` or `str(int)` on at most 25 digits is safe under every limit.

No library gives a text key that is equal across int, float, Decimal and numeral text. The
custom part stays one renderer and one numeral grammar, both already in `cell_text.py`.

## Guarantee and non-goals

Guarantee, for text-keyed columns on the resident frame path:

- Every int, float, Decimal or numeral-text cell in binary64 range keys as the shortest text of
  its nearest binary64. So cells with one exact value share a key, and a number shares a key
  with every text a normal exporter writes for it (`repr`, `str`, `.17e`, `.17g`, exact
  expansion, integer digits). Outside binary64 range the key is the exact value, or a band.
- Number keying (the numeric and numeral branches) never raises, and gives the same keys under
  every `sys.set_int_max_str_digits` value and every decimal context, traps included.
- Detectors read text, bytes and Decimal cells as written, and int and float cells in the
  6efd06af7 rendering with exact integral digits. This is what 6efd06af7 and the frame path
  (`check_residual_pii`) read.
- Source spelling diversity never lowers the source distinct count used for grading.
- A source whose cells are constant but whose keys vary still fails the table, as now.

Non-goals (record as follow-ups, not blockers): detectors reading a numeral string in a
normalized spelling (text `"2125550100.0"` does not hit `us_phone`; same as 6efd06af7 and the
frame path); numbers spelled outside the grammar (`+5`, `1,000`, ` 5`); float32 short text
(`"0.1"` for `np.float32(0.1)`); Fraction and complex cells; the native and lazy Arrow paths
(no text keys there); the existing `cell_text` fallback for other cells (for example a list
holding `10**700`), which already depends on the int-digit limit and is unchanged here;
duplicate column names, which already fail Arrow's name projection.

## The rule

### Comparison key (`key_text`)

Every non-null cell gets one key. A key is a function of the cell's value, so equal cells get
one key. Keys may also match unequal cells that round to one binary64 (over-match). Over-match
is allowed: it can only add identical rows, which fails closed, and diversity no longer reads
keys. Under-match between cells equal under `==` is caught by `_require_preserved`.

Step 1, exact value. Each number becomes `(negative, coefficient digits, exponent)`, with
trailing coefficient zeros moved into the exponent (reduced form):

| Cell | Exact value from |
|---|---|
| bool, `np.bool_` | 1 or 0 |
| int, `np.integer` | `Decimal(abs(n)).as_tuple()` digits (no int-to-str limit) |
| float, `np.floating` of any width | `as_integer_ratio()` |
| `Decimal` | `as_tuple()` |
| text (str, decoded bytes) | the numeral grammar below, else the text is its own key |
| any other cell | `cell_text`, kept as text (unchanged) |

Step 2, binary64. If the value is non-zero, finite and its adjusted exponent (exponent of the
leading digit) is in [-325, 308], let `f` be its nearest binary64: the cell itself for a
`float` or `np.float64`, `float(v)` for NumPy floats narrower than binary64, `float(str(v))`
for NumPy floats wider than binary64 (so a wide cell keys like its own `str` export; equal
wide cells have equal `str`), and `float(t)` for the rest, where
`t` is the numeral text built from the reduced form (at most about 330 characters in this
range; never a Decimal-float operation, so no context trap can fire). If `f` is finite, the
value becomes the value of `repr(f)`; `f` equal to zero keys `0`. Otherwise, or outside the
range, the exact value stays.

`float(t)` and `float(np.longdouble)` round correctly from the exact value, so step 2 is a
function of the value. Since `float(repr(f)) == f`, the key of a key is the key. Examples:
float `1e23`, text `"1e+23"` and text `"99999999999999991611392"` key alike; float 0.1, text
`"0.1"`, `"1.00000000000000006e-01"`, the exact expansion, `Decimal("0.1")` and
`np.longdouble("0.1")` key `0.1`; int `2**53 + 1`, `np.int64(2**53 + 1)` and float `2**53` key
`9007199254740992`, which also closes the NumPy promotion case `np.int64(2**53 + 1) ==
np.float64(2**53)`.

Step 3, render. Zero (either sign) is `0`. Infinities are `Infinity` and `-Infinity`; NaN
follows the existing null policy. The adjusted exponent decides the form:

- above `10**19`: `Overflow` or `-Overflow`;
- below `-10**19`: `Underflow` or `-Underflow`;
- else the round-4 form: plain decimal text with at most 32 padding zeros, else
  `<coefficient>E<exponent>`.

No int, float or Decimal cell can reach the bands (Decimal `MAX_EMAX` is about `10**18`), so
they only bucket absurd text. The band is chosen by the adjusted exponent, a function of the
value, so two spellings of one huge value share a band. Over-match inside a band, and with the
literal text `Overflow`, is accepted.

Numeral grammar (ASCII, full match, unchanged from round 4 except the exponent): optional `-`;
`0` or a digit 1-9 then digits, with an optional fraction, or a bare fraction `.5`; an optional
`e` or `E`, an optional sign, and one or more digits. Also `inf` or `infinity` in any case with
an optional `-`. Kept as text: a leading zero before a digit (`02134`), a leading `+`, spaces,
underscores, `nan`, `1/2`.

Exponent parsing, bounded: if the coefficient digits are all zero the key is `0` and the
exponent is not read. Else strip the exponent's leading zeros. If more than 20 significant
digits remain, the value is in a band (the exponent's sign picks Overflow or Underflow). Else
`int()` on at most 20 digits; the adjusted exponent is that number plus the coefficient length
minus one (after stripping leading fraction zeros). No `int()` or `str(int)` in number keying
sees more than 25 digits. Key length is at most the cell's digits plus 32 zeros plus 22
characters.

### Detector text (new `detector_text`)

One text per non-null cell, read by the detectors in place of the key, in one run per batch:

- str and bytes cells, and any other non-number cell: `cell_text` (characters as written;
  numerals are not parsed).
- Integral int, NumPy integer, float, NumPy float and Decimal cells: exact digits, digit-only
  (sign, coefficient, then the trailing zeros written out, never an `E` form) when that text is
  at most 64 characters, longer than any detector pattern; else the step 3 form. No step 2, no
  int conversion. `411111111111111936` keeps its digits, `10**33` reads as 34 digits,
  `Decimal("4111111111111111.00")` reads `4111111111111111`, `2125550100.0` reads `2125550100`.
- Non-integral Decimal cells: `cell_text`, as written. `Decimal("212555.0100")` reads
  `212555.0100`.
- Non-integral float and NumPy float cells: `repr(float(v))`, the 6efd06af7 rendering. `0.1`
  reads `0.1`.

### Diversity

For a text-keyed column, `source_distinct` and `output_distinct` are counted on the cells with
`source_distinct` (src/decoy_engine/verification/postmask/_column_facts.py:273), the count
`_require_preserved` already uses. A count that raises records the class name as
`distinct_error`, as now. `_frozen` (src/decoy_engine/verification/postmask/_column_facts.py:248)
turns `bytearray` and `memoryview` cells into `bytes`, so they are hashable; Python already
compares `bytearray(b"ab") == b"ab"` as equal, so identity counts do not change.

`_require_preserved` keeps its lost-equality half (`by_keys[0] != by_cells[0] or by_keys[1] <
by_cells[1]`). Its diversity half (runner.py:262) keeps one direction only: raise when the
source cells are constant and the source keys are varied (cells equal under `==` but keyed
apart, for example one instant as a UTC and a New York timestamp). The other direction (varied
cells, constant keys) is finding 4 and is dropped: the facts now read cell diversity, so it can
no longer grade wrong.

### Plumbing

- `src/decoy_engine/internal/cell_text.py`: `key_text` gets the new rule. New public
  `detector_text(series) -> list[str | None]`. One private helper per step. The module stays
  the only text producer (sentry `tests/sentry/test_cell_text_choke_point.py`). No baseline
  change: `tests/sentry/baselines/cell-text-names.json` lists exempt conversion sites, not
  helper names.
- `src/decoy_engine/verification/postmask/_stream_input.py`: `TableBatches` gets one optional
  field, `cell_views: Mapping[str, CellView]` (empty by default). `CellView` is a frozen
  dataclass in the same file with `detector_text: pa.Array` (string, same null mask as the key
  array), `distinct: int`, `distinct_error: str | None`. Only `_frame_table` sets it, and only
  for text-keyed columns. `dataclasses.replace` in `_counted` keeps it.
- `runner.py` `_frame_table`: for each text-keyed column, put the key array in the table (as
  now) and add the `CellView` under the column name, first position only (the column
  `column_facts` reads).
- `_column_facts.py` `column_facts`: when `output.cell_views` has the column, `_add_detectors`
  gets the matching slice of `detector_text` instead of `out_s`. The output row offset advances
  once per yielded output batch, by `out_batch.num_rows`, after all columns, on both the
  compared and the output-only route. The distinct count of each side comes from its view
  instead of `_distinct_or_error`. Columns without a view are unchanged (all native and lazy
  tables).
- `runner.py` `_require_preserved`: one-direction diversity check as above.

## Design notes

- Principle: single responsibility per array. Change pain addressed: each review round had to
  retune one key for two readers. Each fact now lives in one place: value identity in
  `key_text`, characters as written in `detector_text`, diversity in `source_distinct`.
- `CellView` is a typed context object on the table, not new parameters on `column_facts`;
  absent views keep today's behavior for every other table shape.
- No new module, no new file. Placement: N/A, no file is added.

## Size

About 130 changed source lines in four files: `internal/cell_text.py`,
`verification/postmask/_stream_input.py`, `verification/postmask/_column_facts.py`,
`verification/postmask/runner.py`. Public names added: `detector_text`, `CellView`,
`TableBatches.cell_views`. Tests in the two files below. A build well past this stops and
explains.

## Frozen contracts

None touched. `key_text`, `detector_text`, `CellView` and `TableBatches` are internal. No report
field changes shape; `ComparisonNotPreservedError` text stays fixed. Keys and detector text never
reach a report or log.

## Acceptance tests (red on c1430bb57 unless marked)

Run-level tests use `run_post_mask` and `post_scan_verdict`, not only key lists. Files:
`tests/unit/detection_verification/postscan/test_text_fallback_parity.py` (keys, runs) and
`tests/unit/detection_verification/test_residual_pii_source_compare.py` (detector cases).
Synthetic values only (reserved 555-01xx phones, test PANs).

Finding 1, R2, B3, detector input:

- A1a. Mixed `phone` column: 60 dotted phone strings in the form `212555.0100` unchanged,
  one int changed 1 to 2, strategy `hash`. Residual finding `us_phone` with severity `fail`;
  verdict blocking. Same shape for the `device_id` case Codex reproduced.
- A1b. `detector_text` keeps `"212555.0100"`, `"02134"`, `"+1 212 555 0100"` and
  `Decimal("212555.0100")` as written, while `key_text` gives `212555.01` for the first.
- A1c (green before and after). Mixed column of float phone cells `2125550100.0` and one str
  cell: `detector_text` gives `2125550100` and the run still reports the phone hit.
- A1e (R2). Neutral column `v`: 60 unchanged ints `411111111111111936` (synthetic Luhn-valid)
  and one text marker changed `"old"` to `"new"`, `hash`: residual `pan` `fail`, verdict
  blocking; `detector_text` keeps the digits.
- A1g (B3). `hash`, 60 unchanged `Decimal("12.0000000000000001")` in `device_id` and one text
  marker changed `"x"` to `"z"`: residual `device_id` `fail`, verdict blocking. Same with 60
  `Decimal("212555.0100")` in `phone` and `us_phone`.
- A1h (C1, C4). `hash`, 60 unchanged `Decimal("4111111111111111.00")` in neutral `v` and one
  marker changed `"old"` to `"new"`: residual `pan` `fail`, verdict blocking. `detector_text`
  of `10**33` is `"1" + "0"*33`.
- A1i (C3). `phone`: 30 `"212555.0100"`, 30 `"2125550100.0"` and one changed int marker:
  `us_phone` hits are 30 of 61 at `batch_rows=1` and at one batch.
- A1f. Batch offset: two text-keyed columns, `batch_rows=2`, nulls in the early rows, detector
  hits only in later rows: each column reports its hits, with the same rates and verdict at
  `batch_rows=2` and at one batch.

Finding 2, R3, B1, round-trip text:

- A2a. Source `[0.1, 0.2, "mixed"]`, output `["0.1", "0.2", "mixed"]`, strategy `hash`: the
  column grades `fail`, verdict blocking. Same with the output written as `f"{v:.17e}"`
  (`"1.00000000000000006e-01"`), and with source `[1e23, "mixed"]` against output
  `["1e+23", "mixed"]`, and with a `lat` source `[np.longdouble("35.001417"), "unknown"]`
  against its `str` export (C2, on hosts with a wide longdouble).
- A2b. `key_text` gives one key for float 0.1, `np.float64(0.1)`, `np.longdouble("0.1")`, text
  `"0.1"`, `"1.00000000000000006e-01"`, `Decimal("0.1")` and `str(Decimal(0.1))`; for `1e-07`
  / `"1e-07"` / `"1E-7"` / `"0.0000001"`; for `2125550100.0` / `"2125550100"` /
  `"2125550100.0"` / `"2.1255501E9"` / `"2.1255501e+09"`; for `1e23` / `"1e+23"` /
  `"99999999999999991611392"`; for `np.longdouble("35.001417")` and `"35.001417"`; and for int `2**53 + 1`, `np.int64(2**53 + 1)` and float
  `2**53`.
- A2c. Property test (Hypothesis, fixed seed): for any finite binary64 `f`, the keys of `f`,
  `repr(f)`, `str(f)`, `str(Decimal(f))`, `Decimal(f)`, `f"{f:.17e}"` and `f"{f:.17g}"` are
  equal, and the key of that key is itself. For any int `n` with `abs(n) < 2**1000`, the keys
  of `n`, `str(n)`, `Decimal(n)` and (when finite) `float(n)` are equal. For any pair of int,
  float or Decimal cells with `a == b` (Python), the keys are equal.
- A2d. Range edges, explicit pairs: `Decimal("1e-326")` keeps its exact key; `"1e-325"` and
  `"2e-324"` key `0`; `"3e-324"` keys as `5e-324`; `"1" + "0"*308 + ".1"` keys as `1e308`; and
  `"2" + "0"*308 + ".1"` (rounds to infinity) keeps its exact finite key, equal to the key of
  `Decimal` of the same text.
- A2e. `test_the_exact_text_of_a_float_keys_as_the_float_and_blocks` keeps its run assertion
  (blocks); its key assertion changes from the exact expansions to the keys `0.1` and `0.2`.

Finding 3 and R4, exponent bounds and context:

- A3a. Source `10`, output `"1e" + "0"*640 + "1"` in a mixed column: the key is `10` and the
  column grades `fail`, with identical keys and verdict under `sys.set_int_max_str_digits` 640,
  4300 and 0 (restored in `finally`).
- A3b. `key_text` at limit 640 on `"10e" + "9"*640`, `"1e" + "9"*100_000`,
  `"1e-" + "9"*100_000`, `"-1e" + "9"*30` and `"0e" + "9"*100_000` returns `Overflow`,
  `Overflow`, `Underflow`, `-Overflow` and `0`, and raises nothing.
- A3c. Band by value, not spelling: `"1e100000000000000000000"` and
  `"10e99999999999999999999"` share a key; at the boundary, `"10e10000000000000000000"` and
  `"1e10000000000000000001"` both key `Overflow` while `"1e10000000000000000000"` does not.
- A3d. Keys do not change inside `with localcontext() as ctx:` with `ctx.prec = 1`,
  `ctx.Emax = 9`, `ctx.Emin = -9` and `FloatOperation`, `Inexact` and `Rounded` trapped, for
  `"1.5"`, `Decimal("1.5")`, `0.1`, `"1e-07"` and `Decimal("1E4500")`.

Finding 4, R5, R6, source spellings and diversity:

- A4a. Source exactly `["1.0", "1.00"]`, output `[8, "masked"]`, and an unrelated `email`
  column masked with `faker`: no table error, no `ComparisonNotPreservedError`, and the `email`
  findings are present.
- A4b. `ColumnFacts.source_distinct` for a source `["1.0", "1.00", "x"]` counts the cells (3),
  not the keys (2).
- A4c. `test_a_source_that_only_looks_constant_through_its_keys_fails_the_table` is rewritten on
  purpose: the unchanged `PAN`/`"PAN"` column now blocks through a residual `fail` finding
  (source varied by cells, every row identical by keys) instead of a table error. The verdict
  stays blocking and no PAN digits reach the report.
- A4d (R5). `hash`, source `[1, "x"]`, output `[bytearray(b"ab"), 2]`: no `distinct_error`, no
  blocking error for that column.
- A4e (R6, green before, red if both diversity directions are dropped). `a` is midnight UTC
  on 2020-01-01 and `b` the same instant in New York; source `[a, b, a, b]`, output
  `[str(a), b, str(a), b]`, `hash`: the table fails with `ComparisonNotPreservedError`, verdict
  blocking.
- A4f. `test_the_backstop_checks_the_keys_the_emitter_produced` is rewritten on purpose: the
  patched emitter changes only the output's first key on an unchanged, varied column, so one
  real equality is lost; the backstop blocks. The old patch (one key for every row) relied on
  the dropped direction.

Tests changed on purpose because non-integral and wide values now round to binary64 (each keeps
its run and context assertions):

- `test_a_binary_float_and_the_decimal_it_rounds_from_key_apart`: retired; replaced by A2b.
- `test_a_fractional_wide_float_keeps_its_precision_in_the_key`: retired; `1 + 2**-60` and 1
  share a key by design.
- `test_wide_fractional_keys_do_not_depend_on_the_decimal_context`: keys now equal; the run
  stays non-blocking.
- `test_an_unchanged_wide_float_column_that_keys_alike_in_a_double_still_fails`: its key count
  becomes 1; the run still grades `fail` (cell diversity is 2).
- `test_a_whole_wide_float_keys_as_the_equal_int`: expected key becomes `str(2**53)`.

Regressions (green before and after): every other parity case, the Fraction backstop test
(`test_a_cell_equal_to_its_output_but_keyed_differently_fails_the_table`), the bytearray
null-output test, the key-of-key test (extend its parametrize with `Overflow`, `1E4500`, `0.1`,
`9007199254740992`), signed zero, infinities, leading-zero text, the huge longdouble and huge
Decimal tests, and the round-4 tiny Decimal and Decimal spelling tests.

## Mutations (each must turn the named test red)

| Mutation | Red test |
|---|---|
| detectors read the key array again | A1a, A1g |
| detector text for ints goes through step 2 | A1e |
| detector text for Decimal is its key | A1g |
| detector text for floats is `cell_text` (`2125550100.0`) | A1c |
| detector text for integral Decimal is `cell_text` | A1h |
| integral detector text in the step 3 `E` form | A1h |
| detectors run on both arrays and keep the larger hit count per batch | A1i |
| wide NumPy floats step 2 through `float(v)` | A2a `lat` case, A2b |
| output offset advanced per column, or not advanced | A1f |
| non-integral key back to the exact expansion (round 4) | A2a, A2b, A2c |
| step 2 skipped for integral values | A2a `1e23` case, A2b, A2c |
| step 2 kept when `f` is infinite | A2d |
| step 2 through `Decimal(float(t))` or a Decimal context | A3d |
| `int()` on the raw exponent text | A3a, A3b |
| no leading-zero strip on the exponent | A3a |
| band by raw exponent instead of adjusted exponent | A3c boundary case |
| distinct counts read keys again | A4b |
| `_frozen` leaves `bytearray` as it is | A4d |
| both diversity directions dropped | A4e |
| `_require_preserved` loses its lost-equality half | A4f, Fraction backstop test |

## Failure modes

- Over-match: values that round to one binary64 (two integers above 2**53 within one ulp, a
  wide float and its double, `Decimal("0.10000000000000001")` and 0.1), and two band values.
  All add identical rows only; diversity reads cells. Worst case is an extra `fail` on a column
  masked to a different value with the same key: a false block, not a leak. Accepted for V1.
- Under-match between `==`-equal cells of other types (timestamps across time zones): the
  lost-equality half and the one-direction diversity guard fail the table closed.
- Detectors read cells as written: a numeral string in an exporter's float spelling
  (`"2125550100.0"`) is not normalized for detectors. Same as 6efd06af7 and the frame path;
  recorded as a known limit.
- Cost: step 2 adds one `float()` per numeric cell in range. Only text-keyed (mixed) columns on
  the resident frame path pay it, plus one extra string array per such column.

## Pre-mortem

If a later review finds a new case, the likely cause is a reader that still takes the key where
it needs the cells, or the reverse. The "Root cause" table names each reader, and the mutation
table covers each one. A second likely cause is a number type that skips step 2; A2b and the
A2c property test cover every type in the step 1 table. A third is a cell type equal under `==`
but keyed apart; the one-direction diversity guard and the lost-equality half fail those tables
closed. Plan round 3 returned NO-GO with two V1 findings (C1, C2) and two low ones; all four
are fixed in this text. A fourth review round needs owner direction.

## Slices

All on the PR #784 branch, in order, one builder:

1. **S1 key rule** (`internal/cell_text.py`): bounded exponent parse, bands, binary64 step,
   `detector_text`. Red-first: A1b, A1e detector-text part, A2b, A2c, A2d, A3b, A3c, A3d,
   key-of-key; update the five wide-float tests listed above. Commit
   `fix(postmask): key numbers by binary64 spelling with a bounded exponent`.
2. **S2 split readers** (`_stream_input.py`, `_column_facts.py`, `runner.py`): `CellView`;
   detectors read detector text; distinct reads the view; `_frozen` handles bytes-like cells;
   `_require_preserved` keeps one diversity direction. Red-first: A1a, A1c, A1e, A1f, A1g, A1h, A1i, A2a,
   A2e, A3a, A4a-A4f. Commit `fix(postmask): read detector text and diversity from the cells`.
3. **S3 close-out**: update `changelog.d/postmask-fail-closed.md`; run the mutation table; ruff
   and mypy on touched files. Tests through `vm-run` only (T0 per file, T1 impact set on the
   head).

## Reuse inventory

- `repr(float)` (shortest round-trip), `float(str)` (correctly rounded), `Decimal.as_tuple`,
  `Decimal(int)`, `float.as_integer_ratio`.
- `source_distinct`, `identity_counts` and `_frozen` in `_column_facts.py`.
- `_number_text` renderer and `_NUMERAL` grammar in `cell_text.py`, extended, not replaced.
- Parity helpers in `test_text_fallback_parity.py` (`_masked_wide_run`, `_keys`,
  `_assert_backstop_blocks`).

## Enumerations

### Exit paths

- `key_text` and `detector_text` return one entry per row; a null is `None`
  (src/decoy_engine/internal/cell_text.py:54).
- Non-UTF-8 bytes raise `UnreadableCellError` (unchanged). The numeric and numeral branches
  raise nothing else.
- `_require_preserved` raises `ComparisonNotPreservedError` for lost equality, or for constant
  source cells with varied keys (src/decoy_engine/verification/postmask/runner.py:234).

### Routes

- Text fallback `_text` (src/decoy_engine/verification/postmask/runner.py:198) via
  `_frame_table` (src/decoy_engine/verification/postmask/runner.py:211).
- Detector call in `column_facts`
  (src/decoy_engine/verification/postmask/_column_facts.py:405).
- Distinct count `_distinct_or_error`
  (src/decoy_engine/verification/postmask/_column_facts.py:343).
- Value tally `values.add` (src/decoy_engine/verification/postmask/_column_facts.py:408): reads
  the key array, unchanged; string type, so only rows and nulls count.
- Not changed: native and lazy tables (no view), the distribution source pass, and
  `check_residual_pii`'s frame path
  (src/decoy_engine/verification/postmask/residual_pii.py:145), which runs detectors on the raw
  frame.

### FK shapes

N/A: keys are per column; the FK check reads the frames, not the text keys.

### Fields

- `TableBatches.cell_views` (new, src/decoy_engine/verification/postmask/_stream_input.py:25).
- `ColumnFacts.source_distinct` and `output_distinct` for text-keyed columns, now from cells.

### Output surfaces

N/A: no new report field; keys and detector text reach no report or log.

## Class table

| Class | Name | Closing structure | Test | Mutation |
|---|---|---|---|---|
| 1 | value | one rule: every in-range number keys as its nearest binary64's shortest text | A2a-A2e, A3a | non-integral key back to exact expansion |
| 2 | cleanup | N/A: no resources are opened | | |
| 3 | state | N/A: pure functions; the `sys` limit and decimal context are restored in the tests | A3a, A3d | |
| 4 | route | each reader named: identity reads keys, detectors read detector text, diversity reads cells | A1a, A1g, A4b | detectors read the key array again |
| 5 | referential | N/A: no FK or reference handling changes | | |
| 6 | untrusted | bounded exponent, no int conversion past 25 digits, value bands, no Decimal-float mix | A3a-A3d | `int()` on raw exponent text |
| 7 | toctou | N/A: no check-then-use on files or state | | |
| 8 | weak | run-level verdict assertions, not only key lists; retired tests named in this plan | A1a, A2a, A4c, A4f | distinct reads keys again |
| 9 | refactor | N/A: behavior change, no structure-only move | | |
| 10 | frozen | N/A: no frozen surface touched | | |
