# Post-mask canonical cell walk

Status: plan

Date: 2026-11-27. PR #784 (POSTMASK-FAIL-CLOSED), head eac919843. Risk: R2 (value-leak check).
Codex fix rounds 3, 4 and 5 on the PM-1 fixes (`~/scratch/codex-pm1-r3.md`, `-r4.md`, `-r5.md`)
were each GO-WITH-FIXES with new V1 findings in the same area: how a NumPy scalar or array cell
becomes an identity value and a text key. Under the review ladder that is a redesign, so this
plan replaces the two hand-tuned walks with one. It does not change the number key rule of
`2026-11-25-pm1-number-keys-r5.md`; that plan stays in force for scalar numbers and numerals.

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
`np.datetime64(1, "2s") == np.datetime64(2, "s")` is True; `np.timedelta64(1, "M") ==
np.timedelta64(30, "D")` raises `TypeError`; `pd.Timedelta(np.timedelta64(1, "M"))` raises
`ValueError`; 1 fs and 2 fs are equal once boxed as `pd.Timestamp`; and an object Series
holding a 0-dim `NaT` array reports the cell as not null.

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
  `value[()]`.
- pyarrow types (`timestamp(unit, tz)`, `duration(unit)`, `month_day_nano_interval`): a
  calendar interval is its own type, never equal to a duration, and timestamps with a time zone
  compare by their UTC instant.
- Python numeric hashing (stdtypes, "Hashing of numeric types"): numbers equal under `==` hash
  equal across `bool`, `int`, `float`, `Decimal` and NumPy scalars, so number leaves can stay
  numbers.
- In the codebase, `internal/fk_tokens.py` is the precedent: one module defines when two values
  are the same key, and every route reads it.

Pattern adopted: pandas' "one canonical integer form per kind, then one comparison", with an
exact unit (attoseconds as a Python `int`, so no overflow and no sub-ns loss) instead of the
dtype's own unit, and Arrow's rule that calendar intervals are a separate kind. Custom code is
still needed because no library canonicalizes arbitrary nested object cells; the walk is about
160 lines.

## Guarantee and non-goals

Guarantee, for any two cells `a` and `b` of a text-keyed column:

1. `canon(a) == canon(b)` implies `key(a) == key(b)`. The keys never split what identity holds
   equal, so the walks cannot cause `ComparisonNotPreservedError`.
2. Null agrees: identity treats a cell as null exactly when its key is `None`.
3. The key merges cells that identity keeps apart only under three declared rules, all from
   earlier rounds and unchanged: K1 a top-level numeral string keys as the number it spells;
   K2 numbers that round to one binary64 share a key; K3 bytes key as their UTF-8 text. Outside
   K1 to K3, `key(a) == key(b)` implies `canon(a) == canon(b)`.

Non-goals: the number key rule, the detector text of non-temporal cells, `datetime.date`,
`pd.Period` and other types (they stay "other" leaves, compared by `==` and keyed by their
text, as now), and the Arrow batch path's map-as-pairs reading (unchanged).

## The rule

New module `src/decoy_engine/internal/canonical_cell.py`, one public function
`canonical_cell(value) -> object` and a `NULL` sentinel. It is the only walk. Order of checks:

1. A 0-dim `np.ndarray` is replaced by `value[()]`, repeatedly, before anything else.
2. Null: `None`, `pd.NA`, `pd.NaT`, a float NaN (Python or NumPy), and a `datetime64` or
   `timedelta64` NaT of any unit give `NULL`. This applies at every depth.
3. Temporal, checked before numbers because `np.timedelta64` subclasses `np.integer`:

| Input | Canonical form |
|---|---|
| `np.datetime64`, linear unit `u` with count `c` | `("instant", ticks * c * AS[u], False)` |
| `np.datetime64` in Y or M (any count) | converted with `astype("datetime64[D]")`, then as above |
| `pd.Timestamp` | `("instant", ts.value * 10**9, ts.tzinfo is not None)` (`value` is UTC ns) |
| `datetime.datetime` | `("instant", exact attoseconds from the epoch, aware)`, from days, seconds, microseconds |
| `np.timedelta64`, linear unit | `("duration", ticks * c * AS[u])` |
| `np.timedelta64` in Y or M | `("months", ticks * c * (12 if Y else 1))` |
| `pd.Timedelta` | `("duration", td.value * 10**9)` |
| `datetime.timedelta` | `("duration", exact attoseconds)` |

`AS` maps W, D, h, m, s, ms, us, ns, ps, fs, as to attoseconds (`as` is 1). `ticks` is
`int(value.astype(np.int64))`. `pd.Timestamp` and `pd.Timedelta` are checked before their
`datetime` parents. A naive and an aware instant never compare equal, as in pandas.

4. Number leaves: `np.bool_` becomes `bool`; `np.integer` becomes `int`; `np.float16`,
   `float32` and `float64` become `float` (exact widening); `np.longdouble`, `Decimal`, `int`,
   `float` and `bool` stay as they are.
5. `bytes`, `bytearray`, `memoryview` become `bytes`. `str` stays.
6. Containers: a `dict` becomes `("map", frozenset((canon(k), canon(v)) ...))`. A `list`,
   `tuple` (namedtuple included) or non-0-dim `ndarray` of any dtype becomes
   `("list", tuple(canon(v) for v in value))`. A `set` or `frozenset` becomes
   `("set", frozenset(canon(v) ...))`. The tag keeps a dict, a list of pairs and a set of pairs
   apart.
7. Anything else is returned unchanged (an "other" leaf).

Every form is hashable when its leaves are. A temporal form is a tagged tuple, so it never
equals a number or a list.

### Readers

- Identity: `canonical_cells` (_column_facts.py:268) maps `canonical_cell` over the cells and
  turns `NULL` into `None`; `_frozen` and `_MAPPING_TAG` are deleted. `identity_counts` walks
  both sides unless they share one non-object dtype (then raw `==` is exact and the walk is
  skipped, as now for typed columns). `source_distinct` walks an object, categorical, datetime
  or timedelta column and passes a bool, int, uint or float column through.
- Key: `key_text` renders `canonical_cell(cell)`:
  - `NULL` gives `None`.
  - A top-level number leaf gives `_number_key(leaf)`, a top-level `str` gives
    `_text_key(str)` (K1), and top-level `bytes` give `_text_key` of the UTF-8 text (K3). These
    three are the keys of today, unchanged.
  - Anything else gives `"\x1e" + json.dumps(tree)`, where `tree` tags each node: `["n", k]` for
    a number (k from `_number_key`, so K2 applies at every depth), `["s", text]` for a string or
    UTF-8 bytes, `["t", str(as), aware]`, `["d", str(as)]`, `["mo", str(n)]`, `["z"]` for a
    nested null, `["L", ...]`, `["M", ...]` and `["S", ...]` with map pairs and set members
    sorted by their own serialized text, and `["o", cell_text(leaf)]` for an other leaf.
  - A top-level string that starts with `"\x1e"` keys as `"\x1e" + json.dumps(["s", text])`,
    so no string can spell a container's key.
  - `_key_ordered` is deleted. Non-UTF-8 bytes still raise `UnreadableCellError`.
- Detector text: `detector_text` decides null from `canonical_cell` (so the three readers agree
  on null rows) and renders a 0-dim array's payload. Otherwise unchanged; detectors read cells
  as written.
- `_python_scalar` stays only for `_detector_cell`.

## Design notes

- One module owns the walk; `internal/cell_text.py` and `verification/postmask/_column_facts.py`
  both import it. No caller walks a cell itself. This is the choke point: identity, key and
  null all read `canonical_cell`, and P1 is the guard test that fails if a reader walks on its
  own (mutation: null check without the 0-dim unwrap turns C13 and P1 red).
- Principles: single source of truth for "same cell" (the change pain is three rounds of fixes
  in two places); open for a new leaf kind by adding one row to the step list, not a fix per
  reader.
- Attoseconds as Python `int` keep `datetime64[as]` and far dates exact; no step goes through
  `pd.Timestamp` or `pd.Timedelta` for NumPy values.
- A nested NaN is `NULL`, so `[nan]` equals `[nan]` on both sides. Before, identity depended on
  whether the two NaN objects were the same object.
- Nested numbers key through `_number_key`, so `[1]` and `[1.0]` share a key, as identity holds
  them equal. Before, `cell_text` split them.

## Placement

| File | Directory | CODEMAP line | Sits beside |
|---|---|---|---|
| `canonical_cell.py` | `src/decoy_engine/internal/` | "`src/decoy_engine/internal/` Private helpers" (line 144); precedent `internal/fk_tokens.py` (line 33) | `cell_text.py`, `fk_tokens.py` |
| `test_canonical_cell.py` | `tests/unit/internal/` | mirrors the source path | `test_env_flags.py` |

`internal/` holds 14 entries, under the fan-out limit. S2 adds a CODEMAP row for the module.

## Size

`canonical_cell.py` about 160 lines. `cell_text.py` goes from 357 lines to about 340 (minus
`_key_ordered`, plus the tree renderer). `_column_facts.py` from 519 to about 505. The new test
file is about 250 lines. All under the engine module cap (600 target, 700 hard max, `tests/sentry/test_module_size.py`) and the 800-line rule. Public names added: `canonical_cell`,
`NULL` (module-private to the engine; not exported from the package).

## Frozen contracts

None. Keys and canonical forms reach no report, log or public API. `ColumnFacts` fields and
`decoy-run-result/v1` are unchanged.

## Acceptance tests (red on eac919843 unless marked)

In `tests/unit/internal/test_canonical_cell.py` (walk and key) and
`tests/unit/verification/test_order_free_facts.py` (through `_frame_tables`, with a second text
row forcing the text fallback). "Runner ok" means no table error and identical equals
comparable.

| Id | Cells (source vs output) | Expected |
|---|---|---|
| C1 | `array([0], "m8[s]")` vs `array([0], "m8[ns]")` | same canon, same key, runner ok (green on base) |
| C2 | `np.array(7)` vs `np.array(7)` | canon `7`, key `"7"`, runner ok |
| C3 | 0-dim object array of `{"a": 1}` vs `{"a": 2}` | different canon and key |
| C4 | `array([1], "m8[s]")` vs `array([1000], "m8[ms]")` | same canon `("list", (("duration", 10**18),))`, same key, runner ok |
| C5 | `array([1, 2])` vs `np.array([1, 2], dtype=object)` | same canon and key, runner ok |
| C6 | `array([1], "m8[M]")` vs itself | canon `("list", (("months", 1),))`, no raise, runner ok |
| C7 | `array([1], "m8[Y]")` vs `array([12], "m8[M]")` | same canon and key |
| C8 | `array([1], "m8[M]")` vs `array([30], "m8[D]")` | different canon and key, no raise |
| C9 | `array([1], "M8[2s]")` vs `array([2], "M8[s]")` | same canon and key, runner ok |
| C10 | `array([1], "M8[fs]")` vs `array([2], "M8[fs]")` | different canon and key; identical is 0 |
| C11 | `array([1], "M8[M]")` vs `array(["1970-02-01"], "M8[D]")` | same canon and key |
| C12 | `np.array(True)` vs `True` | key `"1"` both, runner ok |
| C13 | `np.array(np.datetime64("NaT"))` | `NULL`; `key_text` gives `None`; not comparable |
| C14 | `[{"b": 2, "a": 1}]` (array cell) vs `[{"a": 1, "b": 2}]` | same key |
| C15 | namedtuple `P(1, 2)` vs `(1, 2)` | same canon, key renders without error |
| C16 | `{"id": 1}` vs `{("id", 1)}` | different canon and key |
| C17 | aware `Timestamp("2020-01-01", tz="UTC")` vs the same instant at `Etc/GMT-1` | same canon and key, runner ok |
| C18 | naive vs aware `Timestamp("2020-01-01")` | different canon and key |
| C19 | `[nan]` vs `[nan]` (distinct NaN objects) | same canon and key, identical 1 |
| C20 | `[1]` vs `[1.0]` | same key (was split) |
| C21 | `"\x1e[\"L\"]"` vs an empty list cell | different keys |
| C22 | list `[1]` vs string `"[1]"` | different keys (they shared one before) |
| C23 | top-level `10001.0`, `10001`, `None`, `memoryview(b"a@x.com")` | keys unchanged (green on base) |
| C24 | numeric-key regression set in `test_text_fallback_parity.py` | unchanged (green on base) |

Property tests (Hypothesis, already a dev dependency, fixed seed through the project profile;
any failing example is pinned as a C row):

- P1, all cells: `canon(a) == canon(b)` implies `key(a) == key(b)`, and `canon(a) is NULL`
  exactly when `key(a) is None`. The strategy covers every leaf kind above, numeral strings,
  bytes, `Decimal`, ints past 2**53, every NumPy unit with counts 1 and 2, tz-naive and aware
  timestamps, NaT of each kind, 0-dim boxing, and lists, tuples, typed and object arrays, dicts
  and sets nested to depth 3.
- P2, the same strategy without K1 to K3 inputs (no numeral strings, no bytes, no `Decimal`,
  ints within 2**53, floats as binary64): `canon(a) == canon(b)` exactly when
  `key(a) == key(b)`. This is the requested property `_frozen(a) == _frozen(b)` iff
  `key_text(a) == key_text(b)`, with `canonical_cell` in place of `_frozen`.
- P3, runner level: for a generated cell `a` and `b` built from it by an equality-preserving
  change (another unit or count, typed vs object array, 0-dim boxing, another time zone for an
  aware instant), a mixed column pair gives no table error and identical equals comparable.

## Mutations (each must turn the named test red)

| Mutation | Red test |
|---|---|
| drop the dtype count from the instant and duration forms | C9, P3 |
| `AS` table stops at ns (sub-ns merged) | C10 |
| map calendar months to 30 days | C8 |
| remove the 0-dim unwrap from the null check | C13 |
| render nested numbers with `cell_text` | C20, P1 |
| drop the `"\x1e"` escape for strings | C21 |
| drop the `"map"` tag | C16 |
| `identity_counts` passes raw cells through when the dtypes differ | C9 runner, P3 |
| key a `pd.Timestamp` by UTC instant but drop the aware flag | C18 |

## Failure modes

- Unhashable "other" leaf: `canonical_cells` raises `TypeError` as now; the column records it as
  `identity_error` and the table fails closed. Unchanged.
- A cell nested past the recursion limit or containing itself: `RecursionError`, recorded the
  same way. Unchanged; no new limit.
- An "other" type whose `==` is coarser than its text (equal objects with different text): the
  key splits them, and `_require_preserved` fails the table closed. The guard stays as a
  backstop for that and for any future leaf kind.
- K1 to K3 merges add identical rows only: a false block at worst, never a leak. Accepted for
  V1, as in the number-keys plan.
- Cost: the walk runs per cell on object and temporal columns of the text-keyed path and on
  `identity_counts` pairs whose dtypes differ. Same-dtype typed pairs skip it, as now.

## Pre-mortem

If a review finds a new case, the likely cause is a leaf kind the step list misses (a new NumPy
or pandas scalar). P1 and P2 run every kind in the strategy, so a missed kind shows as a
property failure, not a one-off. A second likely cause is a reader that walks a cell itself
again; a grep for `ndim == 0`, `tolist()` and `_python_scalar` outside `canonical_cell.py` and
`_detector_cell` belongs in the S2 hand-back. This plan follows three Codex fix rounds; a
fourth round of findings in this area goes to the owner, not to another fix round.

## Slices

On the PR #784 branch, in order, one builder:

1. **S1 walk** (`src/decoy_engine/internal/canonical_cell.py`, new; tests
   `tests/unit/internal/test_canonical_cell.py`): the walk, `NULL`, and the key renderer as a
   pure function. Red-first: C1 to C22 at the walk and key level, P1, P2. Commit
   `fix(postmask): one canonical walk for cell identity and keys`.
2. **S2 wire in** (`internal/cell_text.py`, `verification/postmask/_column_facts.py`,
   `CODEMAP.md`): `key_text` and `detector_text` use the walk; `canonical_cells`,
   `identity_counts` and `source_distinct` use it; delete `_frozen`, `_MAPPING_TAG` and
   `_key_ordered`. Red-first: the runner columns of C1 to C19 and P3 in
   `test_order_free_facts.py`. Update any test that pins a container or temporal key string,
   and list each one in the hand-back. Commit
   `fix(postmask): read identity and keys through the canonical walk`.
3. **S3 close-out**: update `changelog.d/postmask-fail-closed.md`; run the mutation table on the
   final head and record that head with each red test in the PR body and hand-back. Ruff,
   format and mypy on touched files. Tests through `vm-run` only (T0 per file, T1 impact set on
   the head).

## Reuse inventory

- `_number_key`, `_text_key`, `cell_text` and `UnreadableCellError` in `cell_text.py`.
- `canonical_cells`, `identity_counts`, `source_distinct` in `_column_facts.py` (bodies change,
  names and callers stay).
- `np.datetime_data`, `numpy.datetime64.astype`, `json.dumps`.
- The `_frame_tables` helpers and fixtures in `test_order_free_facts.py`.

## Enumerations

### Exit paths

- `canonical_cell` returns a form or `NULL`; it raises only `RecursionError` on a self-holding
  or too-deep cell.
- `key_text` returns one entry per row, `None` for a null; non-UTF-8 bytes raise
  `UnreadableCellError` (unchanged).
- `identity_counts` raises `TypeError` for an unhashable leaf (unchanged).
- `_require_preserved` raises `ComparisonNotPreservedError` as now; after this plan only an
  "other" leaf can trigger it through the walks.

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
| 1 | value | one canonical form per kind, exact units in attoseconds, calendar months apart | C4, C6-C11, P2 | drop count; ns-capped table; months as 30 days |
| 2 | cleanup | N/A: no resources are opened | | |
| 3 | state | N/A: pure functions | | |
| 4 | route | one walk; identity, key and detector null all read it | C13, P1, P3 | null check without unwrap; raw pass on differing dtypes |
| 5 | referential | N/A: no FK or reference handling changes | | |
| 6 | untrusted | string escape so no cell spells a container key | C21, C22 | drop the escape |
| 7 | toctou | N/A: no check-then-use on files or state | | |
| 8 | weak | runner-level asserts (identical equals comparable), not only key lists; property tests over every kind | P1-P3 | nested numbers via `cell_text` |
| 9 | refactor | N/A: behavior change, no structure-only move | | |
| 10 | frozen | N/A: no frozen surface touched | | |
