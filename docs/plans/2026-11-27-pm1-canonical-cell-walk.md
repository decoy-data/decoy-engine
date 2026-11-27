# Post-mask canonical cell walk

Status: plan

Date: 2026-11-27. PR #784 (POSTMASK-FAIL-CLOSED), head eac919843. Risk: R2 (value-leak check).
Codex fix rounds 3, 4 and 5 on the PM-1 fixes (`~/scratch/codex-pm1-r3.md`, `-r4.md`, `-r5.md`)
were each GO-WITH-FIXES with new V1 findings in the same area: how a NumPy scalar or array cell
becomes an identity value and a text key. Under the review ladder that is a redesign, so this
plan replaces the two hand-tuned walks with one. It does not change the number key rule of
`2026-11-25-pm1-number-keys-r5.md`; that plan stays in force for scalar numbers and numerals.
Revised after plan review round 1 (Dennis, NO-GO, `~/scratch/dennis-pm1-plan-r1.md`); the
review tables below record the fixes from rounds 1 and 2.

Rules consulted: `README.md`, `00-universal.md`, `risk-and-exceptions.md`,
`development-loop.md`, `bugfix.md`, `testing.md`.

## Problem

Two functions walk a cell, and each was fixed for the other's last finding:

- Identity: `_frozen` (src/decoy_engine/verification/postmask/_column_facts.py:251) turns a
  cell into a hashable value that `identity_counts` and `source_distinct` compare with `==`.
- Text key: `_key_ordered` (src/decoy_engine/internal/cell_text.py:294) reorders a cell so
  `_number_key` (cell_text.py:281) can render it, and `_per_cell` (cell_text.py:79) decides null
  from the raw cell.

`_require_preserved` (src/decoy_engine/verification/postmask/runner.py:243) raises
`ComparisonNotPreservedError` when the keys split cells that identity holds equal, and the table
fails. So every case where the two walks disagree is a false block, and every case where the
key merges cells identity keeps apart counts a changed row as identical.

The guard compares column totals. The fail-closed runner rows below isolate one split
with an unchanged marker so another row cannot offset it.

The key has a second job: a source value and an output cell that is that value's text must
key alike. A CSV or JSON round trip, or a mixed column, gives the output side as text. Identity
holds a `Timestamp` and its string apart, so only the key match counts that row as unchanged.
If the key splits them too, an unmasked value counts as changed and passes silently. On the
base, `key_text` keys `pd.Timestamp("2020-01-01")`, `uuid.UUID(int=1)`, `date(2020, 1, 1)` and
`[1]` the same as their `str()`. The redesign must keep that.

Findings by round (all V1):

| Round | Case | What went wrong |
|---|---|---|
| r3 | zero-duration `timedelta64[s]` array vs `[ns]` array | key split equal cells |
| r3 | `np.array(7)` (0-dim) | key raised `TypeError` |
| r3 | 0-dim object array holding a dict | key read the dict's keys and dropped its values |
| r4 | 1 s as `timedelta64[s]` vs 1000 ms as `[ms]` | key split (`[1]` vs `[1000]`) |
| r4 | int array `[1, 2]` vs object array of the same ints | key split (`[1 2]` vs `[1, 2]`) |
| r4 | 0-dim `np.array(7)` on the identity side | `_frozen` raised `TypeError` |
| r5 | array cell of `timedelta64[M]` | key raised `ValueError` (`pd.Timedelta` has no months) |
| r5 | 1 tick of `datetime64[2s]` vs 2 ticks of `datetime64[s]` | key split |
| r5 | 1 fs vs 2 fs | key merged distinct instants (`pd.Timestamp` is ns) |
| r5 | `np.array(True)` vs `True` | key split (`"True"` vs `"1"`) |
| r5 | 0-dim `NaT` | identity says null, key says `"NaT"` |

Earlier PM-1 items in the same area: dict key order inside an array cell, a namedtuple cell,
and a dict that froze equal to a set of its pairs.

## Root cause

There is no single definition of what a cell is. Identity leans on Python and NumPy `==`, the
key leans on `str()` and pandas conversions, and null is decided before either walk runs. Each
NumPy kind (0-dim box, typed array, unit and multiplier, calendar unit, sub-ns unit, bool) then
needs the same fix in two or three places, and a round that fixes one place moves the
disagreement to another. Checked on this devbox with numpy 2.2.6 and pandas 2.3.3:

- `np.datetime64(1, "2s") == np.datetime64(2, "s")` is True.
- `np.timedelta64(1, "M") == np.timedelta64(30, "D")` raises `TypeError`, and
  `pd.Timedelta(np.timedelta64(1, "M"))` raises `ValueError`.
- 1 fs and 2 fs are equal once boxed as `pd.Timestamp`.
- An object Series holding a 0-dim `NaT` array reports the cell as not null.
- `pd.Timestamp("3000-01-01").as_unit("s").value` and the same for a `pd.Timedelta` past
  2262 raise `OverflowError`; `.asm8` gives the unit-preserving NumPy value (UTC for an aware
  timestamp).
- `np.timedelta64(5)` has unit `generic`, equals `5`, and subclasses `np.integer`.

## Established solutions

Search run: pandas source (`pandas/core/util/hashing.py`), the NumPy datetime reference, the
pyarrow type reference, and the Python numeric hashing rules; in the codebase, `fk_tokens.py`
(the one FK key definition) and the PM-1 plans.

- pandas `hash_pandas_object` and `util.hash_array` (`_hash_ndarray`): before hashing, a bool
  array becomes `u8` (so True hashes as 1), and a datetime64 or timedelta64 array becomes its
  `i8` view. Each kind becomes one integer form first, then one hash runs. pandas can use the
  raw `i8` because its own columns are unit-normalized; ours are not (object cells keep any
  NumPy unit), so the integer form must carry the unit.
- NumPy datetime docs (`reference/arrays.datetime.html`, "Datetime units"):
  `np.datetime_data(dtype)` returns `(unit, count)`, so `[2s]` is unit `s` times 2. Units W and
  below are linear. Y and M are calendar units: a datetime in Y or M converts exactly to days,
  and a timedelta in Y or M does not convert to any linear unit. A 0-dim array unwraps with
  `value[()]`. A generic-unit timedelta is a plain count.
- pandas `Timestamp.asm8` and `Timedelta.asm8`: the value as `datetime64`/`timedelta64` in the
  object's own unit, with no ns conversion, so it cannot overflow.
- pyarrow types (`timestamp(unit, tz)`, `duration(unit)`, `month_day_nano_interval`): a
  calendar interval is its own type, never equal to a duration, and timestamps with a time zone
  compare by their UTC instant.
- Python numeric hashing (stdtypes, "Hashing of numeric types"): numbers equal under `==` hash
  equal across `bool`, `int`, `float`, `Decimal` and NumPy scalars, so number leaves can stay
  numbers.
- Python `dataclasses.field(compare=False)`: a field left out of `__eq__` and `__hash__`, used
  here to carry a display zone that identity ignores.
- In the codebase, `internal/fk_tokens.py` is the precedent: one module defines when two values
  are the same key, and every route reads it.

Pattern adopted: pandas' "one canonical integer form per kind, then one comparison", with an
exact unit (attoseconds as a Python `int`, so no overflow and no sub-ns loss) instead of the
dtype's own unit, and Arrow's rule that calendar intervals are a separate kind. Keys stay text
that matches `str()`, as on the base. Custom code is still needed because no library
canonicalizes arbitrary nested object cells; the walk is about 170 lines.

## Guarantee and non-goals

Guarantee, for any two cells `a` and `b` of a text-keyed column:

1. `canon(a) == canon(b)` implies `key(a) == key(b)`, with three spelling exceptions, each of
   which split the keys and so fail the table closed through `_require_preserved`, as on the
   base:
   - E1: aware instants that are equal but shown in different zones (UTC vs `Etc/GMT-1`). The
     key keeps each zone's text so that a value and its `str()` still match (K4).
   - E2: equal leaves with different display spellings. At any nested position this includes
     numbers, signed zeros, null variants, Python vs pandas temporals, and any other equal
     leaves with different reprs. It also covers equal top-level temporals with different
     source spellings, such as Python and pandas one-second durations. Equal unordered
     containers may likewise retain different base reprs (set order or frozenset punctuation).
   - E3: lists, tuples, namedtuples and arrays share sequence identity. A tuple or namedtuple
     keeps tuple punctuation. An array or list uses brackets. The split preserves the base
     table failure for a tuple returned as an array by Parquet (C30).
2. Null agrees: identity treats a cell as null exactly when its key is `None`.
3. The key merges cells that identity keeps apart only under four declared rules. K1 to K3 come
   from earlier rounds and are unchanged:
   - K1: a top-level numeral string keys as the number it spells.
   - K2: top-level numbers that round to one binary64 share a key.
   - K3: bytes key as their UTF-8 text.
   - K4: preserve every base match between a typed cell and its exported text. For cells
     that keyed as their own `str()`, the string spelling that cell must still match. Base
     container normalization (including sorted maps) defines the limits of this promise.
     That is the leak-direction match: a value that came back as text still counts as
     unchanged.
   Outside K1 to K4, `key(a) == key(b)` implies `canon(a) == canon(b)`. Every merge only adds
   identical rows: a false block at worst, never a leak.

Non-goals: the number key rule; the detector text of non-temporal cells; the Arrow batch
path's map-as-pairs reading; and the canary's Arrow-side `canonical_cells`
(src/decoy_engine/verification/canary/_canonical.py:212), which converts Arrow arrays by type
for the canary policy and never sees object cells (follow-up for V2-LOG: one walk for both).
`datetime.date`, `pd.Period`, `uuid.UUID` and other types stay "other" leaves: compared by
`==` and keyed by their text, as on the base.

## The rule

New module `src/decoy_engine/internal/canonical_cell.py`, one public function
`canonical_cell(value) -> object`, a reference null form `NULL`, and the frozen dataclasses `Instant`,
`Duration` and `Months`. It is the only walk for object cells. It imports only NumPy, pandas and
the standard library. Order of checks:

1. A 0-dim `np.ndarray` is replaced by `value[()]`, repeatedly, before anything else.
2. Null: `None`, `pd.NA`, `pd.NaT`, a float NaN (Python or NumPy), and a `datetime64` or
   `timedelta64` NaT of any unit give forms equal to `NULL` at every depth. Keep the existing scalar
   missing-value semantics (including Decimal NaN and complex NaN). A frozen null form has
   no comparing fields. Its nested spelling (`nan`, `NaT`, `None`, `<NA>`, etc.) is
   `field(compare=False)`; NumPy temporal NaT displays as pandas NaT. Readers recognize the
   null form by type, so different instances and spellings have one identity and hash.
3. Temporal, checked before numbers because `np.timedelta64` subclasses `np.integer`. `AS` maps
   W, D, h, m, s, ms, us, ns, ps, fs, as to attoseconds (`as` is 1). `ticks` is
   `int(value.astype(np.int64))`.

| Input | Canonical form |
|---|---|
| `np.datetime64`, linear unit `u` with count `c` | `Instant(ticks * c * AS[u], aware=False)` |
| `np.datetime64` in Y or M (any count) | converted with `astype("datetime64[D]")`, then as above |
| `pd.Timestamp`, naive | `ts.asm8` through the `np.datetime64` row |
| `pd.Timestamp`, aware | `ts.asm8` (the UTC instant) through the same row, `aware=True`, `zone=ts.tz` |
| `datetime.datetime`, naive | `Instant(exact attoseconds from the epoch, aware=False)`, from the date's days, seconds and microseconds |
| `datetime.datetime`, aware | the naive attosecond count minus the offset in attoseconds (Python integers), `aware=True`, `zone=dt.tzinfo` |
| `np.timedelta64`, generic unit | the `int` it equals (`np.timedelta64(5) == 5`), then step 4 |
| `np.timedelta64`, linear unit | `Duration(ticks * c * AS[u])` |
| `np.timedelta64` in Y or M | `Months(ticks * c * (12 if Y else 1))` |
| `pd.Timedelta` | `td.asm8` through the `np.timedelta64` row |
| `datetime.timedelta` | `Duration(exact attoseconds)` from days, seconds, microseconds |

`pd.Timestamp` and `pd.Timedelta` are checked before their `datetime` parents. No step reads
`.value` or converts to ns, so a far date in a non-ns unit cannot overflow. `Instant.zone` is
`field(compare=False)`: equality and hash read `(attoseconds, aware)` only, so a naive and an
aware instant never compare equal (as in pandas), and the same instant in two zones does.

4. Number leaves: `np.bool_` becomes `bool`; `np.integer` becomes `int`; `np.float16`,
   `float32` and `float64` become `float` (exact widening); `np.longdouble`, `complex`,
   `Decimal`, `int`, `float` and `bool` stay as they are.
5. `bytes`, `bytearray`, `memoryview` become `bytes`. `str` stays.
6. Containers: a frozen sequence form represents `("list", tuple(canon(v) for v in value))`
   for lists, tuples, namedtuples and non-0-dim arrays. Only the children participate in
   equality and hash. Carry the display style in `field(compare=False)`: parentheses for
   tuples and namedtuples (including the singleton comma), brackets for lists and arrays.
   Maps and sets retain their distinct identity tags and unordered frozensets of canonical
   pairs or members. Preserve the base display separately wherever membership alone loses
   spelling or multiplicity: maps render the original key reprs in repr-sorted order and
   render their canonical values; sets and frozensets retain their Python container repr.
   Display fields never enter equality or hash.
7. Anything else is returned unchanged (an "other" leaf).

Every form is hashable when its leaves are. A temporal form is its own dataclass, so it never
equals a number or a container.

### Temporal text

`canonical_cell.py` also holds `temporal_text(form) -> str`, the one place a temporal form
becomes top-level text. Each temporal form carries a display field with `compare=False`.
Keep the source kind and original Python or pandas value (including its actual tz object),
so top-level text uses its `str` and nested text uses its `repr`. A Python timedelta thus
keys as `"0:00:01"` and a nested Python datetime keeps its `datetime.datetime(...)` repr.
A nested pandas Timestamp uses the original named zone directly. Never parse rendered text
to recover a temporal object. Provide the nested spelling from the same temporal conversion.

For NumPy temporals, derive both spellings from the exact normalized count below. Use
`str` at the top level and the normalized pandas object's `repr` inside containers when
pandas can represent it. Otherwise use the exact fallback spelling at either depth:

- `Instant` with attoseconds a whole number of ns inside the ns range: `str(pd.Timestamp(ns))`,
  localized to `zone` when aware (`"2020-01-01 00:00:00"`, `"2020-01-01 01:00:00+01:00"`).
- `Instant` outside the ns range: the coarsest of s, ms, us that divides it exactly,
  `str(pd.Timestamp(np.datetime64(v, unit)))` (`"3000-01-01 00:00:00"`), localized as above.
- `Instant` with a sub-ns part: `str(np.datetime64(v, unit))` at the coarsest of ps, fs, as.
- `Duration`: the same three steps with `pd.Timedelta` and `np.timedelta64`
  (`"0 days 00:00:01"`, `"146000 days 00:00:00"`, `"1 femtoseconds"`).
- `Months`: `str(np.timedelta64(n, "M"))` (`"3 months"`).
- When no unit holds the value in int64 (a `[W]` or count-scaled value past every pandas
  unit), the text is `f"{attoseconds} attoseconds"`, so the walk never raises.

### Readers

- Identity: `canonical_cells` (_column_facts.py:268) maps `canonical_cell` over the cells and
  turns each top-level null form into `None`; `_frozen` and `_MAPPING_TAG` are deleted. `identity_counts` walks
  both sides unless they share one non-object dtype (then raw `==` is exact and the walk is
  skipped, as now for typed columns). `source_distinct` walks every dtype except bool, int,
  uint and float, which pass through (object, categorical, datetime, timedelta, string and
  every `pd.ArrowDtype` column are walked).
- Key: `key_text` in `cell_text.py` renders `canonical_cell(cell)` through one renderer,
  `_canonical_key`, in the same module (it needs `_number_key` and `_text_key`, and
  `canonical_cell.py` must not import `cell_text.py`):
  - `NULL` gives `None`.
  - A top-level number leaf gives `_number_key(leaf)` (K2), a top-level `str` gives
    `_text_key(str)` (K1), and top-level `bytes` give `_text_key` of the UTF-8 text (K3). These
    are the keys of today, unchanged.
  - A top-level temporal form gives `_text_key(temporal_text(form))`.
  - A top-level container or other leaf gives `_text_key(_canonical_text(form))`, where
    `_canonical_text` renders the form the way `str()` renders the Python value: `"[a, b]"`
    for bracket-style sequences, `"(a, b)"` or `"(a,)"` for tuple style, and the display
    rules in step 6 for maps and sets. Nested leaves use their base container repr, including
    each null variant and the nested temporal spelling above. Use `repr` for other nested
    leaves (e.g. UUID or date), and `cell_text` for a top-level other leaf. When widening a
    leaf would erase its base nested spelling (e.g. bytearray to bytes), retain that spelling
    as non-comparing display data. NumPy numbers retain the base Python scalar presentation.
  - So `[1]` keys `"[1]"`, `{"a": 1}` keys `"{'a': 1}"`, and `uuid.UUID(int=1)` keys its
    hyphenated text, all as on the base (K4). There is no prefix or escape.
  - `_key_ordered` is deleted. `_number_key` loses its `_python_scalar` call
    (cell_text.py:281): after the walk a number leaf is already a Python or NumPy number, and
    that call was the second temporal path. Non-UTF-8 bytes still raise `UnreadableCellError`.
- Detector text: `detector_text` decides null from `canonical_cell` (so the three readers agree
  on null rows) and renders a 0-dim array's payload. Top-level NumPy temporals use the
  same exact conversion and fallback as the key, including generic counts and calendar months.
  Other non-null cells keep their detector rendering; detectors read cells
  as written.
- `_python_scalar` stays only for `_detector_cell`.

## Design notes

- One module owns the walk; `internal/cell_text.py` and `verification/postmask/_column_facts.py`
  both import it, and the dependency runs one way (`cell_text` imports `canonical_cell`). No
  caller walks a cell itself. This is the choke point: identity, key and null all read
  `canonical_cell`, and P1 is the guard test that fails if a reader walks on its own
  (mutation: null check without the 0-dim unwrap turns C13 and P1 red).
- Principles: single source of truth for "same cell" (the change pain is three rounds of fixes
  in two places); a new leaf kind is one row in the step list, not a fix per reader.
- Two forms of a cell, kept apart on purpose: the canonical form answers "same value?", the
  key text answers "same value or its text?". The key is built only from the canonical form,
  so the two can differ only where this plan declares it (E1 to E3, K1 to K4).
- Attoseconds as Python `int` keep `datetime64[as]` and far dates exact.
- A nested NaN is `NULL`, so `[nan]` equals `[nan]` on both sides and both key `"[nan]"`.
  Before, identity depended on whether the two NaN objects were the same object.
- Nested numbers keep their `str()` spelling (E2) rather than the number key: a list source
  and its text output then match (leak direction), and `[1]` vs `[1.0]` fails closed as on the
  base.

## Placement

| File | Directory | CODEMAP line | Sits beside |
|---|---|---|---|
| `canonical_cell.py` | `src/decoy_engine/internal/` | "`src/decoy_engine/internal/` Private helpers" (line 144); precedent `internal/fk_tokens.py` (line 33) | `cell_text.py`, `fk_tokens.py` |
| `test_canonical_cell.py` | `tests/unit/internal/` | mirrors the source path | `test_env_flags.py` |

`internal/` holds 13 modules, under the fan-out limit. S2 adds a CODEMAP row for the module.

## Size

`canonical_cell.py` about 170 lines (walk plus `temporal_text`). `cell_text.py` goes from 357
lines to about 360 (minus `_key_ordered`, plus `_canonical_key` and `_canonical_text`).
`_column_facts.py` from 519 to about 505. The new test file is about 280 lines. All under the
engine module cap (600 target, 700 hard max, `tests/sentry/test_module_size.py`) and the
800-line rule. Public names added: `canonical_cell`, `temporal_text`, `NULL`, `Instant`,
`Duration`, `Months` (engine-internal; not exported from the package).

## Frozen contracts

None. Keys and canonical forms reach no report, log or public API. `ColumnFacts` fields and
`decoy-run-result/v1` are unchanged.

## Acceptance tests (red on eac919843 unless marked)

In `tests/unit/internal/test_canonical_cell.py` (walk and key) and
`tests/unit/verification/test_order_free_facts.py` (through `_frame_tables`, with a second text
row forcing the text fallback). "Runner ok" means no table error and identical equals
comparable. "Fails closed" means `ComparisonNotPreservedError`.

| Id | Cells (source vs output) | Expected |
|---|---|---|
| C1 | `array([0], "m8[s]")` vs `array([0], "m8[ns]")` | same canon, same key, runner ok (green on base) |
| C2 | `np.array(7)` vs `np.array(7)` | canon `7`, key `"7"`, runner ok |
| C3 | 0-dim object array of `{"a": 1}` vs `{"a": 2}` | different canon and key |
| C4 | `array([1], "m8[s]")` vs `array([1000], "m8[ms]")` | same canon `("list", (Duration(10**18),))`, same key, runner ok |
| C5 | `array([1, 2])` vs `np.array([1, 2], dtype=object)` | same canon and key, runner ok |
| C6 | `array([1], "m8[M]")` vs itself | canon `("list", (Months(1),))`, no raise, runner ok |
| C7 | `array([1], "m8[Y]")` vs `array([12], "m8[M]")` | same canon and key |
| C8 | `array([1], "m8[M]")` vs `array([30], "m8[D]")` | different canon and key, no raise |
| C9 | `array([1], "M8[2s]")` vs `array([2], "M8[s]")` | same canon, both keys equal `str([pd.Timestamp("1970-01-01 00:00:02")])`, runner ok |
| C10 | `array([1], "M8[fs]")` vs `array([2], "M8[fs]")` | different canon and key; identical is 0 |
| C11 | `array([1], "M8[M]")` vs `array(["1970-02-01"], "M8[D]")` | same canon and key |
| C12 | `np.array(True)` vs `True` | key `"1"` both, runner ok |
| C13 | `np.array(np.datetime64("NaT"))` | `NULL`; `key_text` gives `None`; not comparable |
| C14 | `[{"b": 2, "a": 1}]` (array cell) vs `[{"a": 1, "b": 2}]` | same key |
| C15 | namedtuple `P(1, 2)` vs `(1, 2)` | same canon, same key `"(1, 2)"`; list `[1, 2]` has the same canon and hash but a bracketed key (E3) |
| C16 | `{"id": 1}` vs `{("id", 1)}` | different canon and key |
| C17 | aware `Timestamp("2020-01-01", tz="UTC")` vs the same instant at `Etc/GMT-1` | same canon, different key (E1), fails closed (green on base) |
| C18 | naive vs aware `Timestamp("2020-01-01")` | different canon and key |
| C19 | `[nan]` vs `[nan]` (distinct NaN objects) | same canon and key, identical 1 |
| C20 | `[1]` vs `[1.0]` | same canon, different key (E2), fails closed (green on base) |
| C21 | `Timestamp("3000-01-01").as_unit("s")` vs itself | key `"3000-01-01 00:00:00"`, no raise, runner ok |
| C22 | list `[1]` vs string `"[1]"` | same key (K4), identical 1 (green on base) |
| C23 | `Timedelta` of 146000 days in unit `s` vs itself | key `"146000 days 00:00:00"`, no raise, runner ok |
| C24 | `np.timedelta64(5)` (generic) vs `5` | same canon `5`, key `"5"`, runner ok |
| C25 | `datetime(2020, 1, 1, 1, tzinfo=+01:00)` vs `Timestamp("2020-01-01 01:00", tz="Etc/GMT-1")` | same canon and key, runner ok |
| C26 | `datetime(2020, 1, 1, 1, tzinfo=+01:00)` vs `Timestamp("2020-01-01", tz="UTC")` | same canon, different key (E1), fails closed |
| C27 | `array([1], "M8[fs]")` | leaf text `"1970-01-01T00:00:00.000000000000001"`; the array key encloses that text in brackets, no raise |
| C28 | top-level `10001.0`, `10001`, `None`, `memoryview(b"a@x.com")` | keys unchanged (green on base) |
| C29 | numeric-key regression set in `test_text_fallback_parity.py` | unchanged (green on base) |
| C30 | `(1, 2)` vs `np.array([1, 2])`, second row the same text marker | same canon and hash, keys `"(1, 2)"` and `"[1, 2]"`; 2/2 identical by cells, 1/2 by keys; runner fails closed (E3, green on base) |

K4 runner rows (leak direction): each source cell is typed, the output cell is the `str()` of
the same value in a mixed column, expected identical equals comparable. All green on base.

| Id | Source cell | Output cell |
|---|---|---|
| T1 | `pd.Timestamp("2020-01-01")` | `"2020-01-01 00:00:00"` |
| T2 | `pd.Timestamp("2020-01-01 01:00", tz="Etc/GMT-1")` | `"2020-01-01 01:00:00+01:00"` |
| T3 | `pd.Timedelta(seconds=1)` | `"0 days 00:00:01"` |
| T4 | `uuid.UUID(int=1)` | `"00000000-0000-0000-0000-000000000001"` |
| T5 | `datetime.date(2020, 1, 1)` | `"2020-01-01"` |
| T6 | `[1, "a"]` | `"[1, 'a']"` |
| T7 | `{"a": 1}` | `"{'a': 1}"` |
| T8 | `(1, "a")` | `"(1, 'a')"` |
| T9 | `[float("nan"), 'a']` | `"[nan, 'a']"` |
| T10 | `[pd.NaT, 'a']` | `"[NaT, 'a']"` |
| T11 | `[datetime(2020, 1, 1), 'a']` | `"[datetime.datetime(2020, 1, 1, 0, 0), 'a']"` |
| T12 | `timedelta(seconds=1)` | `"0:00:01"` |
| T13 | `[pd.Timestamp("2020-01-01 01:00", tz="Etc/GMT-1"), 'a']` | `"[Timestamp('2020-01-01 01:00:00+0100', tz='Etc/GMT-1'), 'a']"` |

For each T row, assert the literal against `str(source)`, both keys against that literal,
and 2/2 identical by key through the runner with the common marker. Preserve object dtype
on input. Dennis's round-2 probes and the base runner confirm T9–T13 are green. Run the additional K4 variants in the review table by the same procedure.

Property tests (Hypothesis, already a dev dependency, fixed seed through the project profile;
any failing example is pinned as a C row). Pairs are not drawn independently, since two
independent draws almost never share a canonical form. Each case draws `a`, then draws `b` as
either `transform(a)` (about half the cases) or a fresh cell. `transform` applies one
equality-preserving change: another unit or count for a temporal leaf, a typed array vs an
object array vs a list, a namedtuple vs a tuple, a 0-dim box, a dict re-inserted in another key order, a
NumPy scalar for a Python number, an `asm8` round trip. Each test counts the cases where
`canon(a) == canon(b)` and fails unless that count is at least a quarter of the cases run
(the counter lives in a module fixture; `hypothesis.event` records it for the report).

- P1, pairs outside E1–E3: `canon(a) == canon(b)` implies `key(a) == key(b)`,
  and `canon(a)` is a null form exactly when `key(a) is None`. The strategy covers every leaf kind
  above, numeral strings, bytes, `Decimal`, ints past 2**53, every NumPy unit with counts 1
  and 2, tz-naive and aware timestamps in UTC, NaT of each kind, 0-dim boxing, and lists,
  tuples, typed and object arrays, dicts and sets nested to depth 3.
- P2, the iff: `canon(a) == canon(b)` exactly when `key(a) == key(b)`. It is the requested
  property `_frozen(a) == _frozen(b)` iff `key_text(a) == key_text(b)`, with `canonical_cell` in
  place of `_frozen`. The strategy is P1's without the inputs where a declared rule applies:
  no strings at any depth (K1, K4), no bytes (K3), no `Decimal`, `np.longdouble` or `complex`,
  ints within 2**53 and floats as binary64 only (K2), no "other" leaves (their `==` can be
  coarser or finer than their text), no aware instants outside UTC (E1), and one display spelling per equal leaf (E2) and sequence (E3).
  Apply exclusions to fresh pairs too, using the input forms independently of the renderer.
  For unordered containers use matching base repr order and punctuation outside E2.
- P3, runner level: for a generated cell `a` and a spelling-preserving `b = transform(a)` outside E1–E3, a mixed column pair gives
  no table error and identical equals comparable.

## Mutations (each must turn the named test red)

| Mutation | Red test |
|---|---|
| drop the dtype count from the instant and duration forms | C9, P3 |
| `AS` table stops at ns (sub-ns merged) | C10, C27 |
| map calendar months to 30 days | C8 |
| remove the 0-dim unwrap from the null check | C13 |
| read `pd.Timestamp.value` instead of `asm8` | C21 |
| leave out the UTC offset for an aware `datetime` | C25 |
| look up a generic timedelta in `AS` | C24 |
| drop the `"map"` tag | C16 |
| `identity_counts` passes raw cells through when the dtypes differ | C9 runner, P3 |
| key a `pd.Timestamp` by UTC instant but drop the aware flag | C18 |
| prefix top-level temporal, container and other keys (the round-1 `"\x1e"` design) | T1-T13, C22 |
| render nested numbers with `_number_key` | C20 (use a nested float) |
| give tuples their own canonical identity tag | C30 runner silently accepts the table |
| render every nested null as `None` | T9 splits from its text and drops to 1/2 identical |
| compare `Instant.zone` in `__eq__` | C17 canon assert, C26 |

## Failure modes

- Leak direction: a typed value whose output came back in a text spelling that is not its
  `str()` (a JSON dict `'{"a": 1}'`, an ISO timestamp `"2020-01-01T00:00:00"`, an aware value
  printed in another zone) keys apart from the source and counts as changed. Same as the base;
  K4 preserves the base spelling. In particular a dict inserted as `b` then `a` keys as
  `"{'a': 1, 'b': 2}"`. Its insertion-ordered output string `"{'b': 2, 'a': 1}"` splits
  from that key and counts as changed, just as on base.
- Unhashable "other" leaf: `canonical_cells` raises `TypeError` as now; the column records it as
  `identity_error` and the table fails closed. Unchanged.
- A cell nested past the recursion limit or containing itself: `RecursionError`, recorded the
  same way. Unchanged; no new limit.
- E1, E2 and E3: keys split values identity holds equal, and `_require_preserved` fails the table
  closed. Same as the base. A false block, not a leak.
- An "other" type whose `==` is coarser than its text (equal objects with different text): the
  key splits them, and `_require_preserved` fails the table closed. The guard stays as a
  backstop for that and for any future leaf kind.
- K1 to K4 merges add identical rows only: a false block at worst, never a leak. Accepted for
  V1, as in the number-keys plan.
- Cost: the walk runs per cell on object and temporal columns of the text-keyed path and on
  `identity_counts` pairs whose dtypes differ. Same-dtype typed pairs skip it, as now.

## Pre-mortem

If a review finds a new case, the likely cause is a leaf kind the step list misses (a new NumPy
or pandas scalar). P1 and P2 run every kind in the strategy, so a missed kind shows as a
property failure, not a one-off. A second likely cause is a reader that walks a cell itself
again; the S2 hand-back carries a grep for `ndim == 0`, `tolist()`, `.value` and
`_python_scalar` outside `canonical_cell.py` and `_detector_cell`. A third is a key that drifts
from `str()`; T1 to T13 hold the leak direction. This plan follows three Codex fix rounds; a
fourth round of findings in this area goes to the owner, not to another fix round.

## Slices

On the PR #784 branch, in order, one builder:

1. **S1 walk** (`src/decoy_engine/internal/canonical_cell.py`, new; tests
   `tests/unit/internal/test_canonical_cell.py`): the walk, `NULL`, the temporal dataclasses and
   `temporal_text`. No reader changes. Red-first: the canonical-form asserts of C1 to C27 and
   the `temporal_text` strings of C21, C23 and C27. Commit
   `fix(postmask): one canonical walk for cell identity`.
2. **S2 wire in** (`internal/cell_text.py`, `verification/postmask/_column_facts.py`,
   `CODEMAP.md`): `_canonical_key` and `_canonical_text` in `cell_text.py`; `key_text` and
   `detector_text` use the walk; `_number_key` drops `_python_scalar`; `canonical_cells`,
   `identity_counts` and `source_distinct` use the walk; delete `_frozen`, `_MAPPING_TAG` and
   `_key_ordered`. Red-first: the key asserts of C1 to C30, the runner rows, T1 to T13, P1, P2
   and P3. Update any test that pins a container or temporal key string, and list each one in
   the hand-back with the old and new string. Commit
   `fix(postmask): read identity and keys through the canonical walk`.
3. **S3 close-out**: update `changelog.d/postmask-fail-closed.md`; run the mutation table on the
   final head and record that head with each red test in the PR body and hand-back. Ruff,
   format and mypy on touched files. Tests through `vm-run` only (T0 per file, T1 impact set on
   the head).

## Reuse inventory

- `_number_key`, `_text_key`, `cell_text` and `UnreadableCellError` in `cell_text.py`.
- `canonical_cells`, `identity_counts`, `source_distinct` in `_column_facts.py` (bodies change,
  names and callers stay).
- `np.datetime_data`, `numpy.datetime64.astype`, `Timestamp.asm8`, `Timedelta.asm8`,
  `dataclasses.field(compare=False)`.
- The `_frame_tables` helpers and fixtures in `test_order_free_facts.py`.
- Not reused, and why: the canary's `canonical_cells` (verification/canary/_canonical.py:212)
  converts Arrow arrays by type and never sees object cells. Merging the two walks is a V2-LOG
  item.

## Enumerations

### Exit paths

- `canonical_cell` returns a form or `NULL`. It raises `RecursionError` on a self-holding or
  too-deep cell, and nothing else: no step reads `.value` or converts a NumPy value to ns, a
  generic timedelta never reaches `AS`, and `temporal_text` falls back to an attosecond count
  instead of raising.
- `key_text` returns one entry per row, `None` for a null; non-UTF-8 bytes raise
  `UnreadableCellError` (unchanged).
- `identity_counts` raises `TypeError` for an unhashable leaf (unchanged).
- `_require_preserved` raises `ComparisonNotPreservedError` as now; after this plan it is
  reached through the walks only by an E1–E3 spelling split or an "other" leaf.

### Routes

- Text fallback `_text` (runner.py:196) through `_frame_table` (runner.py:209).
- Cell view `_cell_view` (runner.py:237): `detector_text` and `cells_distinct_or_error`.
- `_require_preserved` (runner.py:243): `identity_counts` on cells and on keys.
- Batch path: `_add_identity` (_column_facts.py:299) through `identity_counts`
  (_column_facts.py:288).

### FK shapes

N/A: the FK check reads frames, not keys or canonical forms.

### Fields

N/A: no field is added or removed.

### Output surfaces

N/A: no report field, log line or exit code changes.

## Class table

| Class | Name | Closing structure | Test | Mutation |
|---|---|---|---|---|
| 1 | value | one canonical form per kind, exact units in attoseconds, calendar months apart, `asm8` reads | C4, C6-C11, C21, C23-C25, P2 | drop count; ns-capped table; months as 30 days; `.value` read |
| 2 | cleanup | N/A: no resources are opened | | |
| 3 | state | N/A: pure functions | | |
| 4 | route | one walk; identity, key and detector null all read it | C13, P1, P3 | null check without unwrap; raw pass on differing dtypes |
| 5 | referential | N/A: no FK or reference handling changes | | |
| 6 | untrusted | keys stay `str()` text so a value returned as text still matches (K4) | T1-T13, C22 | prefix top-level keys |
| 7 | toctou | N/A: no check-then-use on files or state | | |
| 8 | weak | runner-level asserts (identical equals comparable); property tests with derived pairs and a floor on equal pairs | P1-P3 | nested numbers via `_number_key` |
| 9 | refactor | N/A: behavior change, no structure-only move | | |
| 10 | frozen | N/A: no frozen surface touched | | |

## Review round 1

| Finding | Fix in this plan |
|---|---|
| 1 BLOCKER: `\x1e` prefix splits a value from its text | Prefix and escape dropped; temporal, container and other keys are `str()` text built from the canonical form; K4 declared; C22 flipped; T1-T8 runner rows; "prefix top-level keys" mutation; Non-goals now agree |
| 2 HIGH: `.value` overflows past 2262 | `pd.Timestamp` and `pd.Timedelta` read `asm8` through the NumPy rows; C21, C23; `temporal_text` has an int64 fallback; Exit paths corrected |
| 3 vacuous properties | `b = transform(a)` in about half the cases; floor of a quarter equal-canon pairs per test |
| 4 P2 overclaims | P2 exclusions name other leaves, `np.longdouble`, `complex`, strings, E1 and E2 |
| 5 generic td64, aware datetime | generic timedelta is its `int`; aware `datetime` subtracts `utcoffset()`; C24, C25, C26 |
| 6 circular import | `_canonical_key` and `_canonical_text` live in `cell_text.py`; S1 is walk-only, key rows move to S2 |
| 7 `_python_scalar` in `_number_key` | S2 drops it; hand-back grep names it |
| 8 canary `canonical_cells` | named in Non-goals and Reuse, V2-LOG follow-up |
| 9 `source_distinct` dtypes | walks every dtype except bool, int, uint, float |

## Review round 2

| Finding | Resolution and guard |
|---|---|
| V1 BLOCKER: tuple identity split after Parquet round trip | Step 6 shares sequence identity and keeps punctuation in a non-comparing field. E3, C15 and C30 preserve the runner rejection. Giving tuples a distinct tag turns C30 red. |
| V1 HIGH: K4 lost null and temporal spellings | Null and temporal forms retain non-comparing display data. E2 covers equal leaves with different spellings. T9 to T13 pin the base text and runner counts. Rendering every nested null as None turns T9 red. C9 guards normalized nested NumPy temporal repr. |
| V1 self-review: nested other leaves and unordered containers could lose base repr | Preserve nested repr (including UUID, date and bytearray) and original set/frozenset display. Add K4 runner variants against their own text for `[date(2020, 1, 1)]`, `[bytearray(b"a")]` and `frozenset({1})`. |
| V2-LOG LOW: missing dict insertion-order limit | Failure modes records the sorted dict key and insertion-ordered output string that already split on base. |

## Record redesign (amendment, 2026-11-27)

Four Codex findings in the record path (r3 ns vs us field; r4 case 1, an unchanged `M8[us]` record
exported as `str(record.item())`; r4 case 2, a subarray of nested records after an inner unit
change) came from one habit: predicting how NumPy or Python spells a record as text. Each spelling
path (`str(item())`, `repr`, `Timestamp` against `datetime`, the unit inside `repr`) can split from
identity. The walk stops predicting it.

Rule:
1. A NumPy record scalar is `Record(fields)`: the canonical forms of its fields in dtype order,
   recursing into nested records and subarrays. Field names stay out of identity. Its key text is
   one fixed rendering of those fields, `record(<field>, ...)`, built by `_canonical_text` in
   `cell_text.py`. No record text comes from `item()`, `str()` or NumPy `repr`.
2. A record row is identical or refused. When either side's form is a record or holds one (at
   any depth: a sequence item, a set member, a mapping key or a mapping value; a read-only NumPy
   record is hashable), and the two forms are not equal, the pair
   is not comparable. `identity_counts` raises `RecordNotComparableError` (a
   `ComparisonNotPreservedError`, fixed text, class name only, same `check_error` classification).
   The table is refused as for any comparison failure. It is never reported as "differs as
   expected". The first draft asked only whether exactly one side held a record, so a partial
   export that kept an inner record (`item()` of a subarray of nested records, `tuple(rec)` of a
   nested record, a dict holding a record, an object field holding a record against its text)
   passed. Equality of forms is the only test, so no position walk is needed. A masked record
   column therefore refuses the table.
3. Scope: table level, as the plan already has. One record column refuses the whole table.

Removed: `Record.spelling`, `_record_spelling`, `_field_spelling`.
Added: `RecordNotComparableError` (`internal/cell_text.py`), `contains_record`
(`internal/canonical_cell.py`). `ComparisonNotPreservedError` takes an optional fixed message.

Cases closed: r3 ns vs us (identity from fields); r4 case 1 (record to text is refused); r4 case 2
(the subarray keys from fields, so the units cannot split it); text to record is refused the same
way. Tests: the "records" sections of `tests/unit/internal/test_canonical_cell_keys.py`.

V2-LOG: per-column refusal (only the record column, not the table) and a documented text export
for records, if a customer needs a record column to be compared with text.
