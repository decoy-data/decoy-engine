# Post-mask value key, round 4

Status: plan

Date: 2026-11-25. PR #784 (POSTMASK-FAIL-CLOSED), after the third review round. The earlier
plan is `2026-11-24-postmask-fail-closed-and-ratchet-growth.md`. Risk: R2 (value-leak check).

Rules consulted: `00-universal.md`, `risk-and-exceptions.md`, `development-loop.md`,
`bugfix.md`.

## Problem

`key_text` (`src/decoy_engine/internal/cell_text.py`) gives one text key per cell of a column
Arrow refuses (mixed types). The runner grades "unchanged value" on these keys. Each review
round found one more pair of cells where the key and the value disagree:

- the same number in two spellings (`"9007199254740992.50"`, `"9.0071992547409925E15"`) keys
  differently from the number;
- `Decimal('1e-999999999999999999')` pads zeros and raises `MemoryError`;
- a huge integral `Decimal` takes `str(int(x))` and hits Python's int digit limit;
- `np.longdouble(0.1)` and `Decimal('0.1')` share a key, and the exact text of binary64 0.1
  does not share the key of the float 0.1;
- `inf` (float) and `Infinity` (Decimal) key differently.

Root cause: each type renders its own text, and the texts were patched to agree case by case.
There is no single numeric form that all types map to.

## How the keys are used (the semantic)

- The keys are the column the graders compare and the detectors read on the runner path.
- `_require_preserved` fails the table when the keys lose an equality the cells have (Python
  `==` through `identity_counts`). Extra key matches are allowed if the source does not turn
  constant. So a key may over-match but must never under-match.
- The tests already require that a number and its own text rendering key alike
  (`test_an_unchanged_wide_fraction_is_not_counted_as_masked`, form `decimal_text`). A masked
  output that writes the source number as text is a leak.

Decision: the key of a numeric cell is its **exact numeric value**, whatever its type, and text
that is a plain decimal numeral is read as that number. Textual identity is kept for all other
text, because the detectors read the key and must see the original characters.

## Established solutions

Searched: Python `decimal` (General Decimal Arithmetic spec, `Decimal.as_tuple`, `normalize`),
Python's cross-type numeric hash (`sys.hash_info`, docs "Hashing of numeric types"), and
`float.as_integer_ratio`. Findings:

- Python's numeric hash gives equal values one hash across int, float, Decimal and Fraction, but
  unequal values can collide and the key must be readable text for the detectors. Not usable.
- `Decimal.normalize()` is the spec's canonical form (strip trailing zeros), but it rounds to the
  context precision and clamps the exponent. The design uses the same form, built from
  `as_tuple()` with no context.
- `float.as_integer_ratio()` is the exact rational value of any binary float, NumPy's included;
  `n / 2**k = n * 5**k / 10**k` gives the exact decimal coefficient.

The remaining custom code is the rendering of the triple and the numeral grammar for text.

## The rule

Every number becomes `(negative, coefficient digits, exponent)` with no leading or trailing
zeros in the coefficient, from exact sources only:

| Cell | Source of the triple |
|---|---|
| bool, `np.bool_` | 1 or 0 |
| int, `np.integer` | digits of `Decimal(n)` (no int-to-str limit) |
| float, every `np.floating` incl. longdouble | `as_integer_ratio()` |
| `Decimal` | `as_tuple()` |
| text (str, decoded bytes, other cells' text) | the numeral grammar below, else the text itself |

Key rendering of a finite triple: zero is `0` (signed zero is one value). Otherwise plain
decimal text when at most 32 padding zeros are needed (`12300`, `0.000123`, `123.45`), else
`<coefficient>E<exponent>` (`1E-999999999999999999`). The form is a function of the triple, so
equal values give one key and unequal values give two (plain text has no `E`; each form is
unique per triple). Key size is at most the coefficient digits plus 32 zeros plus the
exponent's digits. Nothing is padded to the exponent.

Specials: +inf is `Infinity`, -inf is `-Infinity`, any NaN is `NaN`.

Numeral grammar (ASCII, full match): optional `-`; then `0` or a digit 1-9 followed by digits,
with an optional fraction, or a bare fraction `.5`; then an optional exponent `e`/`E` with an
optional sign. Also `inf`/`infinity` in any case with an optional `-`. A key parses back to
itself, so text that equals a key is that key's number.

Not numbers (kept as their text): a leading zero before another digit (`02134`), a leading `+`,
spaces, underscores, `nan`, fractions such as `1/2`. These are codes or spellings a detector
must still read as written (a ZIP with a leading zero, a phone with `+`).

## Guarantee and non-goals

Guarantee: for the cell types in the table, two cells with equal exact numeric values get one
key, unequal values get different keys, and keying allocates no more than the cell's own digits
plus a constant. Non-goals: Fraction and complex cells, numbers spelled outside the grammar,
the native (Arrow) path, the detectors.

## Size and placement

One source file (`internal/cell_text.py`: replace `_decimal_text`, `_wide_float_key` and the
number branch of `_number_key`; about 80 lines), one test file
(`tests/unit/detection_verification/postscan/test_text_fallback_parity.py`), one changelog
fragment. No new modules or public names. Choke point: `key_text` stays the only producer of
text keys; the existing sentry `tests/sentry/test_cell_text_choke_point.py` covers it.

## Acceptance tests (red on 6efd06af7 unless marked)

1. Trailing-zero text `"9007199254740992.50"` keys as `Decimal("9007199254740992.5")`; an
   output of that text over that source blocks.
2. Scientific text `"9.0071992547409925E15"` keys as the same Decimal; the run blocks.
3. `Decimal('1e-999999999999999999')` in a mixed column keys without error, the key is short,
   and the masked run has no table error.
4. `Decimal('1E+4500')` and `Decimal(10**5000 + 1)` key under the default 4300-digit limit;
   `Decimal('1E+4500')` and `Decimal('10E+4499')` share a key.
5. `np.float64(0.1)` and `Decimal('0.1')` key differently (longdouble too, where it is wider).
6. The exact text of binary64 0.1 and 0.2 keys as the floats 0.1 and 0.2; an output of that text
   over float source cells blocks.
7. `inf`/`-inf` floats key as `Decimal('Infinity')`/`Decimal('-Infinity')` and as the text
   `"inf"`; an unchanged infinity column emitted as Decimals blocks.
8. Regressions (green before and after): every existing parity case, signed zero, the wide
   float cases, the key of a key is the key, leading-zero text keeps its characters.

## Failure modes

- Over-match in the source: text `"1"` and `"1.0"` in one mixed column become one key. If that
  makes a varied source look constant, `_require_preserved` fails the table (fails closed,
  `ComparisonNotPreservedError`). Same as today for `1` and `"1"`.
- A number spelled with a leading zero, `+`, or as a fraction keys as text, so it can read as
  changed against the number. Python `==` also calls these unequal, so both paths agree.
- An exponent with more digits than the int-from-text limit (4300) cannot be parsed; that text
  keys as itself.
- Non-integral floats key as their exact expansion
  (`0.1000000000000000055511151231257827021181583404541015625`) instead of `repr`. Detectors
  full-match, and the patterns with digit runs accept no point, so no hit that `repr` text
  made is lost.
- `Decimal('sNaN')` already fails in pandas `notna` before keying. Out of scope.

## Pre-mortem

If this round fails review again, the likely cause is a cell type that still renders its own
text instead of going through the triple. The build therefore routes every number type through
one renderer and adds a test that the key of a key is the key.

## Slices

One slice on this PR's branch: plan, red tests, the rule in `cell_text.py`, changelog fragment.

## Reuse inventory

- `decimal.Decimal.as_tuple`, `Decimal(int)` for big-int digits, `float.as_integer_ratio`.
- The existing parity helpers in `test_text_fallback_parity.py` (`_masked_wide_run`, `_keys`).

## Frozen contracts

None touched. `key_text` is internal; its output reaches no report (keys stay value-free in
errors, `ComparisonNotPreservedError` text is fixed).

## Enumerations

### Exit paths

- `key_text` returns a list of keys; a null cell is `None` (src/decoy_engine/internal/cell_text.py:53).
- An unreadable bytes cell raises `UnreadableCellError` (unchanged).

### Routes

- Runner text fallback `_text` (src/decoy_engine/verification/postmask/runner.py:198), used by
  `_frame_table` (src/decoy_engine/verification/postmask/runner.py:211).
- Backstop `_require_preserved` reads the emitted keys
  (src/decoy_engine/verification/postmask/runner.py:234).

### FK shapes

N/A: keys are per column; FK checks do not read text keys.

### Fields

- Number branch of `_number_key` (src/decoy_engine/internal/cell_text.py:142).
- Text branch: every other cell through `cell_text`.

### Output surfaces

N/A: keys feed graders and detectors only; no key text reaches a report or log.

## Class table

| Class | Name | Closing structure | Test | Mutation |
|---|---|---|---|---|
| 1 | value | one triple renderer for every numeric type | acceptance 1-7 | render floats by `repr` again turns 5 and 6 red |
| 2 | cleanup | N/A: no resources are opened | | |
| 3 | state | N/A: pure functions, no shared state | | |
| 4 | route | `key_text` is the only key producer | sentry test_cell_text_choke_point.py | a second key builder in runner |
| 5 | referential | N/A: no FK or reference handling changes | | |
| 6 | untrusted | bounded key size, no padding to the exponent | acceptance 3 and 4 | pad zeros to the exponent turns 3 red |
| 7 | toctou | N/A: no check-then-use on files or state | | |
| 8 | weak | key equality checked through run-level verdicts, not only key lists | acceptance 1, 2, 6, 7 | keep text spelling turns 1 red |
| 9 | refactor | N/A: behavior change, no structure-only move | | |
| 10 | frozen | N/A: no frozen surface touched | | |
