Status: plan (revision 2, 2026-11-25; re-anchored to #813 and the passed GSA S1b and S2 plan)

# GEN-VECTOR-STREAMS: sequence, constant, distribution, categorical and reference streams hand the assembler Arrow arrays, with the same bytes

Owner: Cam. Author: Opus (plan author). Dates: revision 1 2026-11-22, revision 2 2026-11-25. Roadmap row: GEN-VECTOR-STREAMS (CLI `docs/roadmap/groups/generate.md`, a 1.0 row): "sequence, reference and null-mask streams ... Output bytes must not change; if they do, back to owner." V1 fast-path audit (vault `10_Projects/decoy/v1-fast-path-audit-2026-11-22.md`, lines 155-156 and 218). Engine only.

Owner decision already recorded (vault `OWNER-OPEN-DECISIONS.md`, 2026-11-22, go-with-recommended): reproduce the CPython bytes. This revision keeps that decision and has no open owner question.

Anchors. A path with no prefix is under `src/decoy_engine/` in decoy-engine. Read at engine `origin/main` `2b8a47fbe` and at GEN-STREAM-ALL S1a, PR #813, head `6b7dd3a56` (only pool files changed since `dca2db39a`; the cited stream and assembler lines are the same) (called "#813" below). Line numbers are at #813. The builder rechecks every line on the merged heads of the dependencies in section 12.

Builds on:

- GEN-STREAM-ALL S1a (#813, open). It already adds the Arrow stream protocol this row needs: an optional `supports_array` property and `next_array(offset, size) -> pa.Array` on a stream (`generation/_column_streams.py:202-209` on `PooledFakerStream`; the probe `supports_array(stream)` at `:285`), the null mask on arrays (`NullMaskedStream.next_array`, `generation/_column_streams.py:261`, a `pc.take` with null positions so a null slot holds no value bytes), and the assembler rule that keeps a column as an array unless a consumer needs Python values (`generation/stream/_batches.py:56` `array_columns`; the type check at `generation/stream/_batches.py:98`). Revision 1 of this plan proposed that protocol; it is now #813's, and this row only adds `next_array` to more streams.
- GEN-STREAM-ALL S2 (plan `origin/docs/plans-gsa-eor-1125:docs/plans/2026-11-25-gen-stream-all-s1b-s2.md`, passed; its `weighted_draw` section and AT-S2-10). It exports `weighted_draw(rng, values, weights, k)` from `generation/kinds/_categorical.py` as the one categorical and lookup draw, and adds a guard that forbids a local `choices` copy in the streamed categorical caller. This row's categorical replay goes through that module, so slice S2 here starts after GSA S2 merges.

Not combined with GEN-NONFAKER-DRAWS S3 (`origin/docs/plans-pap-gnf-1125:docs/plans/2026-11-25-gen-nonfaker-draws-s3.md`). Its `ComputedDrawStream` implements #813's protocol itself and needs nothing from this row. The two rows touch different streams. That plan says GVS chose a counter-based draw; that is wrong (this row replays CPython), and it changes nothing in GNF S3.

Rules consulted: dev-rules `README.md`, `00-universal.md`, `risk-and-exceptions.md`, `development-loop.md` (PLAN), `testing.md` (Test depth), `performance.md`, `catalogs/recurring-defects.md`; the plan contract (`obsidian-vault/30_Resources/Decoy-Plan-Contract-and-Defect-Catalog.md`); engine `CLAUDE.md`.

Risk: S1 is R1 (no RNG, byte-identical, generation only). S2 is R2: byte identity depends on reproducing CPython `random` (section 5.3), and it touches the frozen generation output and the ledger. Plan review: Dennis, then Codex. Code gate: Codex for S1; Codex and Dennis for S2.

## 1. Frame

On #813 each stream below returns a Python list per batch, and the assembler builds `pa.array(values, type=...)` per column per batch (`generation/stream/_batches.py:114`). Only pooled Faker and a null mask over it take the array path.

| Stream | Today (#813) | Cost |
|---|---|---|
| `SequenceStream` (`generation/_column_streams.py:134`) | Python loop; text form runs `str(value).zfill(pad)` and the affixes per row | per-row Python format |
| `ConstantStream` (`generation/kinds/_constant.py:31`) | `[value] * size` | list build and `pa.array` |
| `ParametricStream` (`generation/kinds/_parametric.py:60`) | `default_rng(base_int("dist"))`, clip, `.tolist()` | `.tolist()` then `pa.array` |
| `CategoricalStream` (`generation/_column_streams.py:153`) | `random.Random(base_int("py")).choices(cats, weights, k=size)` | C loop for unweighted (67 ns/row, Dell); Python `bisect` per item when weighted |
| `ReferenceStream` (`generation/_column_streams.py:212`) | per row: `rng.choice(vals)`, `rng.choices(vals, weights, k=1)[0]` or `vals[i % len]` | 468 ns/row for `choice` (Dell) |

`pa.array` over Python objects costs about 34 ns/row (GSA master plan section 1) on top of each stream's own loop. The audit ranks sequence, constant, distribution and categorical under the noise floor and reference as the slow one.

Probe (Dell, Python 3.10, numpy from the engine lock, 1,000,000 draws per case, 2026-11-22): an `np.random.MT19937` bit generator loaded with the state of `random.Random(seed)` reproduces CPython's output bit for bit.

| Case | Equal to CPython | numpy replay | CPython |
|---|---|---|---|
| `choices(cats, k)`, unweighted | yes, over batch sizes 1, 7, 4096, 65536, 3 | 248 ns/row (first cut, including the float build) | 67 ns/row |
| `choices(cats, weights, k)` | yes, including zero weights | not timed | per-item bisect |
| `choice(vals)` over 100,003 keys | yes, same batch sizes | 20.6 ns/row | 468 ns/row |

So reference gets about 20x on the draw with no byte change. Unweighted categorical is already fast in CPython; the replay only pays if it removes the list. S2 measures the end-to-end batch (draw plus Arrow build) per case and keeps the faster draw for that case (section 5.3). The bytes are the same either way.

## 2. Established solutions

Search run: reproducing CPython `random` with numpy (`numpy.random.MT19937` state, `random.Random.getstate` and `setstate` layout), vectorized weighted choice (`numpy.searchsorted` over cumulative weights, the vector form of the `bisect` call `random.choices` makes), Arrow string building (`pyarrow.compute.utf8_lpad`, `binary_join_element_wise`), Arrow constant arrays (`pyarrow.repeat`).

- CPython's `random.Random` is MT19937 (`Modules/_randommodule.c`). `getstate()` returns `(3, 624 words + position, gauss_next)`; numpy's `MT19937.state` takes the same 624-word key and position. `random()` is `((a >> 5) * 67108864.0 + (b >> 6)) / 2**53` over two 32-bit words. `getrandbits(k)` for `k <= 32` is one word shifted right by `32 - k`. `_randbelow(n)` is `getrandbits(n.bit_length())` with rejection, and rejected words are consumed. `choice(seq)` is `seq[_randbelow(len(seq))]`. `choices` without weights is `population[floor(random() * n)]` with `n` a float; with weights it is `population[bisect(cum_weights, random() * total, 0, n - 1)]` where `cum_weights = list(accumulate(weights))` and `total = cum_weights[-1] + 0.0`. All of this holds for CPython 3.10 to 3.12, the engine's range (`pyproject.toml:13`). The probe confirms it.
- `numpy.searchsorted(cum, x, side="right")` is `bisect.bisect_right`; the `hi = n - 1` bound of `choices` is a clip to `n - 1`. Equality needs the cumulative weights exact as float64, which holds when they are computed in Python by `accumulate` (as CPython does) and every partial sum is a float or an int of magnitude at most 2**53.
- `str.zfill(w)` keeps a leading sign and pads after it; Arrow `utf8_lpad` does not know signs. The sequence formatter pads the absolute value to `w - 1` for a negative value and prepends `"-"` (section 5.2).

### Reuse inventory

- #813: `supports_array`, `next_array`, `array_columns`, `NullMaskedStream.next_array`, and the type check that sends an array whose type differs from the schema field back to the list path. This row adds no protocol.
- #813: `stream.sibling_input` (`generation/stream/_siblings.py`), the one rule for which column a later column reads; `array_columns` already uses it.
- GSA S2: `weighted_draw` in `generation/kinds/_categorical.py` (the one categorical and lookup draw) and its AT-S2-10 guard.
- `GenDeriveContext.base_int("py")` and `base_int("dist")`: seed roots unchanged.
- `sequence_affixes` (`generation/_numeric_typing.py:77`) and `_fits` (`generation/_numeric_typing.py:90`): the one reading of affixes and the int64 bound.
- `check_reference_pool` (called at `generation/_column_streams.py:229`): still runs once per stream.
- `key_pool_bytes` (`generation/_bounds.py:301`), the preflight term at `generation/_streamed.py:238` and the live reservation at `generation/_streamed.py:485`: the model for the one new reservation in S2.

## 3. Guarantee and non-goals

After this row:

1. `SequenceStream`, `ConstantStream` and `ParametricStream` (S1), and `CategoricalStream` and `ReferenceStream` (S2) have `supports_array` and `next_array`. Their arrays are byte-identical to today's list output, type included, for every config those streams accept.
2. Output does not depend on how rows are split into batches, on every supported Python, on both paths.
3. The assembler's rule for when a column must stay a list is #813's, unchanged: a declared `output_type`, a key collector, a same-batch sibling reader, or a type mismatch. This row adds no new reason to build a list and removes none.
4. A stream that serves both `next_batch` and `next_array` leaves the same RNG state after the same rows, so the two methods can be mixed on one stream without changing later rows.
5. Whole-table generators (`synthesize.py`, `kinds/_lookup.py`, `window.py`) and their bytes are unchanged.
6. When the replay cannot prove itself on the running interpreter, or a config falls outside what the replay reproduces exactly (section 4, exit paths), the stream uses today's CPython draw. That is decided once per stream, never per batch.

Non-goals: per-row Faker (GEN-NONFAKER-DRAWS); pooled Faker (GSA); `windowed_date`; lookup streams (GSA S2 owns `LookupStream`; it can call the S2 helper later with no plan change, section 12); an Arrow key collector (`KeyPool` stays a Python list, so a key column keeps #813's list path); distribution families other than `uniform` (none exist); a Rust kernel (engine record `docs/records/2026-11-19-engine-speed-and-route-completeness.md` section 2.3 found Rust selection slower than numpy).

## 4. Enumerations

### Exit paths

| # | Condition | Result | Slice |
|---|---|---|---|
| E1 | replay self-test passes, config in range | numpy replay for `choice` and `choices` | S2 |
| E2 | replay self-test fails on this interpreter | CPython draw, `pa.array` over its list; bytes equal; one debug record per process names the fallback | S2 |
| E3 | sequence value for any planned row outside int64 | today's Python loop; decided at construction from `rows` with `_fits` (`generation/_numeric_typing.py:90`) | S1 |
| E4 | empty reference pool | a null array of the column type, as today's `[None] * size` (`ReferenceStream`, `generation/_column_streams.py:212`); the relationship policy's fail or warn (`generation/relational/_cardinality.py:139`) runs first, at construction, as today | S2 |
| E5 | `size == 0` | empty array; the RNG is not advanced (CPython `choices(k=0)` draws nothing) | S1, S2 |
| E6 | weights length differs from values, total not positive or not finite, a negative weight, a cumulative weight beyond 2**53 in magnitude, an empty category list, or a reference pool of at least 2**32 keys (bit length 33); a weight that is not an `int` or `float`; the population buffers do not fit the ledger (section 5.3) | CPython draw for that stream, so today's `ValueError` or `IndexError` is raised with the same text at the same batch, or today's values come out | S2 |
| E7 | the drawn array's type differs from the schema field | #813's list fallback (`generation/stream/_batches.py:98`); bytes equal | S1, S2 |
| E8 | `offset + size > rows` on a sequence (a caller reading past the planned rows) | the list path for that batch, so int64 cannot wrap silently | S1 |
| E9 | the parent key list does not convert to the child's schema field type | `SealedKeys.array` is `None`; every child reference column over that parent, null-masked or not, is a list column, decided at seal, before any child stream opens (section 5.4); the reservation stays charged (over-charge only) | S2 |

Order, so a cell that matches two rows takes the CPython result. Reference: construction is unchanged from #813 (`generation/_column_streams.py:229` onward), so a nonempty weighted pool with `weights: []` still raises the coded length error from `generation/relational/_cardinality.py:164` at construction, and the empty-pool policy runs there too; after construction E4, then E5 (a zero-size batch draws nothing and checks no weights, as the per-row loop does), then E6; a random reference on any fallback draws with `choice` per row, as today. Categorical: E6 before E5 (CPython `choices(k=0)` still validates its weights), and categorical `weights: []` keeps today's normalization. E2 before E1. An unknown reference `distribution` takes the `choice` branch, as today.

### Routes

| Route | Change |
|---|---|
| streamed, resident (`sink=None`) | the five streams return arrays when `array_columns` allows |
| streamed, with a sink | same |
| window (`generation/window.py`) | none: it calls `next_batch`, which keeps today's draws (guarantee 4) |
| `_run_legacy` (`generation/_streamed.py:537`) and whole-table kinds | none |
| GSA S2 provider and lookup streams | none |

### Codes

No new reason codes. E2 is a debug record, not a warning: it changes no output.

### FK shapes

- `reference` to a parent table: the sealed parent key list keeps its insertion order. S2 builds one Arrow copy of it per referenced parent key column that some child reference column reads on the array path (section 5.4), typed with the parent key's schema field type, reserved in the ledger, stored in the same `key_pools` entry as the list, shared by every such child stream, and gathered with `pc.take`. The indices are the ones CPython would draw.
- A column that is itself a reference target: it has a collector, so it stays on #813's list path. No change.
- `reference` with cardinality repair or fitted fan-out: not streamed today (admission), unchanged.

### Fields

| Stream | Fields | Notes |
|---|---|---|
| sequence | `start`, `step`, `prefix`, `suffix`, `pad_length`, numeric form | sign-aware pad |
| constant | `value` | any scalar, including `None` |
| distribution | `family: uniform`, `low`, `high`, `min`, `max` | clip after draw, as today |
| categorical | `categories`, `weights` | weighted and unweighted |
| reference | `distribution` (`random`, `weighted`, `sequential`), `weights` | all three |
| null mask | `null_probability` | #813's `NullMaskedStream.next_array`, unchanged |

### Output surfaces

| Surface | Change |
|---|---|
| generated tables | none (byte-identical) |
| ledger events | S2: one new reservation label `parent_key_array:<table>.<column>` |
| debug log | one record per process on E2, naming the Python version and the stream kind only |
| `docs/` | the generation route section of `CODEMAP.md` and the streams module docstring |

## 5. Design notes

Principles that apply: one place per fact (one replay module; the list-or-array rule stays in `array_columns`); open/closed on streams (a stream opts in by adding `supports_array` and `next_array`; the assembler never switches on stream type). Established pattern: CPython's own algorithms, reproduced (section 2).

### 5.1 Constant and distribution (S1)

Constant: `pa.repeat(value, size)` for a non-null value, a null array for `None`. If the inferred type differs from the schema field, E7 applies. Distribution: the same `default_rng` draw and clip, then `pa.array(ndarray)` with no `.tolist()`. A float64 value converts to the same Arrow double either way, NaN included.

### 5.2 Sequence (S1)

At construction, `_fits(start, start + step * (rows - 1))` decides the vector form (E3). Numeric form: `int_from_index(np.arange(offset, offset + size), lo=start, step=step)` from `generation.pool` (`generation/pool/_computed_draw.py:234`, exported at `generation/pool/__init__.py:126`). It does the arithmetic modulo 2**64 on uint64, so a step at or past 2**63 with every output inside int64 (for example `start = -2**63`, `step = 2**64 - 1`, two rows) gives the exact values; a plain int64 `np.arange(...) * step` raises `OverflowError` there. The existing `SequenceStream` constructor calls (`synthesize.py:412`, `window.py:195`) do not change. Text form: that int64 array cast to string, then for `pad_length > 0` the sign-aware pad (non-negative values: `utf8_lpad(width=pad, padding="0")`; negative values: `"-"` joined to `utf8_lpad(body, width=pad - 1, padding="0")`, where `body` is the cast string with its leading `"-"` sliced off, not `pc.abs`, which wraps at `INT64_MIN`), then `binary_join_element_wise(prefix, body, suffix, "")`. The stream needs `rows`, which `make_column_stream` already has (`generation/_column_streams.py:304`). numpy int64 wraps silently, so `next_array` checks `offset + size <= rows` and takes the list path otherwise (E8).

### 5.3 Replay (S2)

New `generation/kinds/_mt_replay.py`, exported through `generation.kinds`, about 110 lines. It holds no RNG of its own. Each call works on the caller's `random.Random`:

1. read `rng.getstate()`, load the 624 words and position into a fresh `np.random.MT19937`;
2. draw the raw 32-bit words the call needs;
3. write the advanced key and position back with `rng.setstate((3, tuple(words.tolist()) + (pos,), gauss_next))`. The words go back as native Python ints (CPython's `setstate` refuses a tuple of numpy `uint32` with `TypeError`) and `gauss_next` is carried over unchanged.

The adapter reads the state, draws on numpy, and calls `setstate` once at the end. If any step before that `setstate` raises, the stream RNG is untouched and that call takes the CPython draw. `replay_ok()` runs its probe on disposable `random.Random` objects, and any exception in the probe (a changed `getstate` layout, a numpy API change, a refused `setstate`) counts as a mismatch: E2, before any stream RNG is read.

So the `random.Random` a stream already holds stays the one source of truth. `next_batch` (CPython) and `next_array` (replay) leave identical state after the same rows (guarantee 4), and a switch between them mid-run cannot change later rows.

Functions:

- `replay_choices(rng, n, cum_weights, k) -> np.ndarray[int64]`: `random()` from word pairs, then `floor(u * float(n))` or `min(searchsorted(cum, u * total, "right"), n - 1)`. Each value takes exactly two words, so the words consumed are `2 * k`.
- `replay_randbelow(rng, n, k) -> np.ndarray[int64]`: `kbits = n.bit_length()`, words shifted by `32 - kbits`, rejection in order. The word count is not known in advance: draw blocks of at most `min(k + k // 2 + 64, 65_536)` words on a copy of the state, writing accepted values into the `k`-row output as each block is scanned and keeping no block after it is scanned, until `k` are accepted; then advance the real state by exactly the number of words up to the `k`th accepted one. Scratch is one block plus the output, both bounded by the batch. Rejected words are consumed, as in CPython. The block rule changes only speed, never values (AT-5 covers acceptance rates near one half).
- `replay_ok() -> bool`: a fixed self-test (tests force E2 through the module seam `_mt_replay._replay_ok_override`, and an adapter failure through `_mt_replay._state_adapter`; never by patching `random.Random`), run once per process on first use and cached: three seeds, sizes 0, 1, 7 and 4096, each function against `random.Random` on the same seed, including a weighted case with a zero weight and an `n` just above a power of two. Any mismatch sets E2 and writes the debug record.

Callers:

- `generation/kinds/_categorical.py` (GSA S2's `weighted_draw` module) gains `weighted_indices(rng, n, weights, k)`, which returns replay indices, or `None` when E2 or E6 applies. `weighted_draw` is unchanged. `CategoricalStream.next_array` gathers `pc.take(self._cats_array, indices)`; on `None` it returns `pa.array(weighted_draw(...))`. `_cats_array` and the cumulative weights scale with the number of categories, not with output rows, so they are priced: `categorical_population_bytes(n_categories, arrow_type, width)` in `generation/pool/_resident.py` (Arrow form through the same parts rule as `faker_pool_resident_parts`, `generation/pool/_resident.py:72`, plus `8 * n` for the cumulative float64 weights) is a preflight term and a live reservation on the table stage, made before the buffers are built. If it does not fit, the stream takes the CPython draw (E6 row, last cell), which allocates nothing new; the replay is never what makes a job refuse. The `k`-row index array and the replay scratch are batch-sized and go into the batch term beside `generation/_bounds.py:247`. The AT-S2-10 guard adds `weighted_indices` to its allowed helpers for the streamed categorical caller; no local `choices` copy appears.
- `ReferenceStream.next_array`: `random` calls `replay_randbelow(rng, len(vals), size)`; `weighted` calls `weighted_indices` with `k=size` (one `random()` per row, as `choices(k=1)` per row does); `sequential` uses `np.arange(offset, offset + size) % len(vals)` and no RNG. Values are `pc.take(parent_array, indices)`.

S2 keeps CPython for a case where the measured end-to-end batch is slower with the replay (expected: unweighted categorical with few categories). In that case `next_array` is `pa.array(weighted_draw(...), type=field_type)`: it skips `next_batch`, `to_pylist` and `restore_declared`, and AT-3 asserts exactly that for the case. That choice is a constant in `_categorical.py`, chosen from the AT-4 measurement and recorded in the PR; the replay still serves weighted categorical and every reference form.

### 5.4 Reservation for the parent array (S2)

The Arrow copy of a sealed parent key list is new memory, so it is priced before it is built. The decision whether a column takes the array path must be the same at preflight (no streams exist yet), at the parent's live reservation (the child's streams do not exist yet) and in the assembler. A per-table rule cannot see collectors: in a chain `A.id -> B.fk -> C.fk` only C's config shows that `B.fk` is collected. So S2 extracts the checks `array_columns` already makes (`generation/stream/_batches.py:63` onward: declared cast, collector, sibling reader) into one plan-wide predicate in `generation/stream/_batches.py`:

`column_reads_array(table, col, table_cols, referenced)`: no declared output type, `(table, col)` not in `referenced` (the plan-wide set from `_referenced_keys`, `generation/_streamed.py:180`, the same set GSA S1b+S2 uses), and not read by a later column of its table (`sibling_read_names` on #813; GEN-PER-COLUMN S1 replaces that with `TableColumnPlan.batch_reads` and its route, and this predicate then calls those). `array_columns` calls it for every column and adds only the stream's `supports_array` and, for a reference column, `sealed.array is not None` (E9, known at seal, before the child stream opens). `ReferenceStream.supports_array` is the constant `True`; E2, E4, E5 and E6 are handled inside `next_array`. A parent key column needs a copy when at least one child reference column over it passes `column_reads_array`; two such children share one copy and one charge.

Sizing: `reference_array_parts(parent_rows, key_type, key_payload)` in `generation/pool/_resident.py` returns the retained bytes and the conversion peak, built from the same parts rule as `faker_pool_resident_parts` (`generation/pool/_resident.py:72`: `rows + 1` offsets for string types, validity bitmap, builder growth to the next power of two during conversion). It does not use `arrow_column_bytes` (`src/decoy_engine/_arrow_types.py:243`), which counts `rows` offsets (four bytes short on a one-row `[""]`) and no builder growth.

Lifetime: one retained charge per parent key, label `parent_key_array:<t>.<c>`, reserved on `run_stack` before the parent's first batch, beside the `parent_key_pool` charge (`generation/_streamed.py:482-488`). It is held from seal through the last child that reads it and released once when the run ends, on success and on every failure (seal, child, sink). The conversion peak is a short charge taken on the same ledger at seal and released when the copy is built. In the preflight the retained bytes go into both run peaks (resident and sink) the same way the key total does (`generation/_streamed.py:216` onward), not into the stage peak, and the conversion peak is checked at the seal point. The copy is built at seal (`generation/_streamed.py:512-513`) with the parent key's schema field type and kept in the same `key_pools` value as the list, as a `SealedKeys(keys, array)` record (array `None` when no child reads it or E9 applies). There is no second dict. A shortfall raises `GenerationBudgetExceeded` before the parent's first batch. Under an unbounded ledger the charges are recorded and never refuse.

Ownership with GEN-PER-COLUMN: byte formulas (`key_pool_bytes`, `reference_array_parts`, `categorical_population_bytes`) live in `generation/pool/_resident.py`; the per-table orchestration (reservations, seal) lives in `generation/stream/_table_stage.py`, the module GEN-PER-COLUMN S2 creates by moving `_consume_table` and the per-table loop out of `_streamed.py`. One `seal_parent_keys(...)` operation builds `SealedKeys` for ordinary parents and for GEN-PER-COLUMN's deferred parents.

## 6. Placement

| What | Where | CODEMAP line | Beside |
|---|---|---|---|
| `next_array` on sequence, categorical, reference | `generation/_column_streams.py` (413 on #813, about 440 after GSA S2; about +35 in S1, +45 in S2, about 520 at the end) | "Generation", `_column_streams.py` row | the other streams |
| `next_array` on constant, distribution | `generation/kinds/_constant.py` (40, about +8), `generation/kinds/_parametric.py` (77, about +6) | `kinds/` row | the list forms |
| replay | `generation/kinds/_mt_replay.py` (new, about 110), exported by `generation/kinds/__init__.py` (83, about +3) | `kinds/` row | `_categorical.py` |
| `weighted_indices` | `generation/kinds/_categorical.py` (72 on #813, about 82 after GSA S2, about +15) | `kinds/` row | `weighted_draw` |
| `reference_array_parts`, `categorical_population_bytes` | `generation/pool/_resident.py` after the move below (about +35) | "Generation" pool | `faker_pool_resident_parts` |
| `column_reads_array` | `generation/stream/_batches.py` (121 on #813, about +15; the checks move out of `array_columns`) | "Generation streamed batch assembly" | `array_columns` |
| live reservations, `seal_parent_keys`, `SealedKeys` | `generation/stream/_table_stage.py` (created by the move below, about 120, then about +35) | "Generation streamed batch assembly" | `_consume_table` |
| preflight terms | `generation/_streamed.py` (about +12 after the move takes about 90 out) | "Generation" | the `key_pool_bytes` terms |
| tests | `tests/unit/generation/stream/test_vector_streams.py`, `tests/unit/generation/kinds/test_mt_replay.py` | generation unit tests | #813's stream tests |

`generation/` keeps its 25 counted modules (the fan-out limit; `__init__.py` is not counted); `kinds/` takes one. By the numbers above both files would pass 600, so S2 starts with two moves, each its own commit with no behavior change: (1) `key_pool_bytes` moves from `_bounds.py` into `generation/pool/_resident.py` beside `faker_pool_resident_bytes`, behind the same import (GEN-PER-COLUMN S2 names the same move; whichever row lands first makes it); (2) `_consume_table` (`_streamed.py:423`) and the per-table loop with its reservations and key sealing (to `:514`) move into `generation/stream/_table_stage.py`, the same move GEN-PER-COLUMN S2 names; whichever row lands first makes it, and the other adds to the moved code. `stream/` gains that module either way, counted once in both plans. The builder recounts `_streamed.py` after the move and after GSA S2 and S3; it stays under 600. Neither move raises a size ceiling.

## 7. Defect classes

### 7.1 Plan-contract classes

| # | Class | Where it applies | Structure that closes it | Proof | Mutation that must turn it red |
|---|---|---|---|---|---|
| 1 | Value-bearing output | the E2 debug record; E6 errors | the record names only the stream kind and Python version; E6 reuses CPython's own error text, which carries no generated value | AT-7 | M7 |
| 2 | Cleanup missing on an exit path | the parent-array and categorical population reservations | retained charge on `run_stack` with `parent_key_pool`, conversion charge released when the copy is built; categorical charge on the table stage; released once on every exit | AT-8 | M8 |
| 3 | Shared state and concurrency | RNG state across batches and across `next_batch` and `next_array` | the replay reads and writes back the stream's one `random.Random`; streams are per column and not shared across threads | AT-2, AT-5 | M3 |
| 4 | Route parity and silent fallback | array vs list path; E2, E6, E7 | every fallback is CPython or #813's list path, byte-equal, decided once | AT-1, AT-6 | M1 |
| 5 | Referential integrity | reference columns | same parent list, same order, same indices | AT-1 reference cells | M4 |
| 6 | Untrusted producer | none | N/A: inputs are the compiled config and the engine's own RNG | n/a | n/a |
| 7 | Check then use | none | N/A: no file or path is read | n/a | n/a |
| 8 | Weak tests | AT-1 passes before | AT-3 (array path taken) and AT-4 (speed) carry the fail-before | AT-3, AT-4 | M5 |
| 9 | Behavior-preserving refactor drift | stream outputs | goldens captured on the dependency head before the change | AT-1 | M2 |
| 10 | Frozen contract drift | generation output determinism | byte-identical; changelog fragment says so | AT-1 | M1 |

### 7.2 Recurring-defect catalog (dev-rules)

| # | Class | Applies | Guard |
|---|---|---|---|
| 1 | Anchored validation | no | - |
| 2 | Strict wire and stored types | no new persisted model | - |
| 3 | No exception context | E6 keeps CPython's raise; no new raise | AT-6 |
| 4 | Versioned read models | no | - |
| 5 | Normalized guard scanners | yes, GSA's AT-S2-10 AST guard gains one allowed helper | AT-S2-10 still red on a seeded local `choices` copy |
| 6 | No reaching into private modules | `_mt_replay.py` is reached only through `generation.kinds` | import-linter and the `kinds/_` rule |
| 7 | No hidden CI failures | unit tests run on 3.10 only; the 3.11.9 and 3.12.7 legs run import smoke and `faker_output_lock` (`.github/workflows/ci.yml` at #813, lines 63-96). S2 adds marker `mt_replay` on `test_mt_replay.py` and a CI job running `pytest -m mt_replay` on 3.10.20, 3.11.9 and 3.12.7 with `fail-fast: false` | the job in the S2 PR |
| 8 | One input, one trust class | no | - |
| 9 | Mutations on the final head | yes | named mutations on the final head of each slice, head recorded |
| 10 | Allowlisted helpers are still checked | yes, `weighted_indices` joins the AT-S2-10 list | the guard spies on it on the matching branch |
| 11 | No raised caps | `generation/` fan-out 25, module size | new module in `kinds/`; sizes in section 6 |

## 8. Acceptance tests

Goldens are captured on the dependency head, before any stream change, through the public `generate_tables_streamed` with a bounded Parquet sink and a resident run, and committed with the tests.

| ID | Test | Fail-before | Slice |
|---|---|---|---|
| AT-1 | Golden parity (tables hold no Faker, lookup or provider columns, so GSA S1b's intended byte changes cannot move the goldens): for each stream and each field form in section 4 (negative start with pad, pad shorter than the value, prefix and suffix, numeric form, constant `None` and string, uniform with and without clip, weighted with a zero weight, reference `random`, `weighted`, `sequential`, empty pool, null probability 0, 0.3 and 1 over each), tables of 1, 7 and 120,000 rows equal the goldens: decoded values, schema, and the Parquet file bytes at a fixed batch layout. Sequence overflow cells: `start = -2**63, step = 2**64 - 1` over two rows, its descending counterpart `start = 2**63 - 1, step = -(2**64 - 1)`, and a one-row sequence with a step past 2**64; each equals the golden through the vector form (not E3). S1 covers its three streams; S2 the other two | passes before (guard); fail-before is AT-3 | S1, S2 |
| AT-2 | Partition invariance through `run_generation(partition=...)` (`generation/_plan_entry.py:290` exposes only `batch_rows`): a 4,110-row table with layouts `[7, 4096, 3, 4]`, `[0, 4110]`, `[1]*10 + [4100]` and `[4110]` gives equal tables, zero-size pieces included | passes before; guards state carry | S1, S2 |
| AT-3 | Array path taken: for each stream of its slice, with no declared cast, collector or sibling reader, a spy sees `next_array`, no `next_batch`, and no `pa.array` over a list for that column; with a sibling reader the list path is used and values equal AT-1: through the public route a `windowed_date` whose anchor is an admitted date column; through a direct assembler fixture (public `condition_on` declines to legacy on #813, `generation/_admission.py:259`) a `condition_on` parent on a categorical. `constant(None)`, malformed weights and a mixed-type key list (E9) are tested at the direct stream and seal seams that accept them. A deliberate E7 mismatch: `to_pylist` and the conversion happen once and the stream is drawn once. For the unweighted categorical kept on CPython (section 5.3) the spy asserts no `next_batch`, no `to_pylist` and no `restore_declared`; `pa.array` over the drawn list is allowed for that case only. `column_reads_array` gives the same answer from config before streams exist and inside `array_columns` after; `array_columns` delegates to it (spy). A three-table chain `A.id -> B.fk -> C.fk`: `B.fk` is a list column and is collected, C reads B's keys, A reserves no copy, B reserves one; two sibling children over one parent share one copy and one charge | list today | S1, S2 |
| AT-4 | Speed, `perf`, Dell vm-run, the same end-to-end workload on the dependency head and on the candidate: a 10,000,000-row table with one reference column over 100,000 parent keys at or under 60 ns per row for that column on the candidate (the per-row `choice` costs 468 ns on its own; the dependency-head figure is recorded in the PR); the S2 PR records unweighted and weighted categorical with and without the replay and the constant chosen in section 5.3 | 468 ns today | S2 |
| AT-5 | Replay equality and mixing: on every CI Python leg, `replay_choices` and `replay_randbelow` equal `random.Random` for `random`, `_randbelow`, `choice`, `choices` with and without weights, over seeds and sizes 0, 1, 7, 4096; after each call `rng.getstate()` equals the CPython generator's state after the same draws. A stream that alternates `next_batch` and `next_array` over `[7, 4096, 3]` equals the one-path golden. `_replay_ok_override = False` forces E2; output then still equals AT-1. Crafted state: a helper sets the MT key at `pos` to untempered words that give a chosen `u`. With `u = 0.5` and weights `[1, 1]` the replay picks index 1 as `bisect` does (kills `side="left"`); with `u = 0.75` and weights `[5e-324, 0.0]`, `u * total` rounds to `total` and the clip keeps index 1 as CPython's bounded `bisect` does (kills removing the clip). Adapter: `_state_adapter` made to raise leaves the stream on CPython for that call, and the next draw and full `getstate()` equal CPython's. `replay_randbelow` at `n = 2**k + 1` (acceptance near one half) for `k` 4096 crosses several blocks. Runs under marker `mt_replay` on 3.10.20, 3.11.9 and 3.12.7 | no replay today | S2 |
| AT-6 | E6 cells: weights length mismatch, zero total, a negative weight with a positive total, a cumulative weight above 2**53, empty categories, a reference over `range(2**32)` at the direct seam (values and state equal CPython's), a `Decimal` weight (CPython's `TypeError`), a 1,000,000-category weighted categorical in a one-row job under a ceiling between the batch cost and the population cost (CPython draw, completes, no new allocation; the population charge is recorded in preflight and live). For the negative-weight and above-2**53 cells the test uses the AT-5 crafted-state helper to pick a `u` where the bare replay (E6 check off) differs from CPython, and asserts that precondition first. Each cell: each raises the same exception type and text at the same batch as the golden run, or (negative weight, large weight) gives the golden values through CPython | no replay today | S2 |
| AT-7 | The E2 debug record names only the Python version and stream kind; a test seeds a category value and asserts it is absent from every record and error | no record today | S2 |
| AT-8 | Parent-array reservation: the live retained event equals `reference_array_parts(100_000, key_type, payload).retained` and the seal event equals its conversion peak; preflight and live call the one helper (spy); both run peaks (resident and sink) grow by exactly the retained bytes against the same plan with the child on the list path; the parts are at or above measured Arrow buffers for string keys of payload 0, 1 and 64 and int64 keys, including one-row `[""]`; one retained charge per parent key, live through the last child, released exactly once on run exit for success, seal failure, child failure and sink failure; on a fixture where neither the streamed run nor the resident fallback fits, the band-adjusted ceiling (the smallest ceiling `_fits` passes, `_streamed.py:268-271`) completes and the next lower one refuses with `GENERATION_BUDGET_EXCEEDED` before the parent's first batch and before any sink write; on a ledger directly an exact reservation passes and one byte less refuses; the parent array has the parent key's Arrow type; a parent whose only child reference column has a declared cast reserves no array | no reservation today | S2 |
| AT-9 | E3: a sequence whose last planned value passes int64 uses the list path and equals the golden | passes before (control, through `next_batch`) | S1 |
| AT-9b | E8: a direct `next_array(rows - 2, 5)` call takes the list path and equals `next_batch(rows - 2, 5)` | fails before (no `next_array`) | S1 |

## 9. Named mutations

| ID | Mutation | Must turn red |
|---|---|---|
| M1 | `random()` replay uses `b >> 5` instead of `b >> 6` | AT-1, AT-5 |
| M2 | sequence pad pads the signed string, or pads a negative value's body to `pad` instead of `pad - 1` | AT-1 negative-start cell |
| M3 | the replay does not write the state back to `rng` | AT-2, AT-5 mixing cell |
| M4 | `replay_randbelow` drops rejected words without consuming them | AT-1 reference cell, AT-5 |
| M5 | on the S1 head `SequenceStream` loses `supports_array`; on the S2 head `CategoricalStream` loses it | AT-3 |
| M6 | `searchsorted` with `side="left"`, or the clip to `n - 1` removed | AT-5 crafted-state cells (`u = 0.5`, `[1, 1]`; `u = 0.75`, `[5e-324, 0.0]`) |
| M7 | the E2 record logs the first drawn value | AT-7 |
| M8 | the parent-array retained charge is released at stage close instead of run exit, or preflight leaves it out | AT-8 |
| M9 | E6 check removed for negative weights, or for cumulative weights above 2**53 | AT-6 (precondition cells) |
| M10 | `column_reads_array` checks collectors in the column's own table only | AT-3 three-table chain (`C` gets an empty pool or A reserves an unused copy) |
| M11 | sequence `next_array` drops the `offset + size <= rows` check | AT-9b |
| M12 | sequence numeric form uses int64 `np.arange(...) * step + start` instead of `int_from_index` | AT-1 overflow cells |
| M13 | the replay writes numpy `uint32` words back to `setstate`, or the probe lets an adapter exception escape | AT-5 adapter cell |
| M14 | `categorical_population_bytes` left out of preflight or the live stage | AT-6 population cell |

## 10. Frozen contracts

- Generated output is deterministic per seed and frozen at release. This row keeps every byte; the changelog fragment `changelog.d/gen-vector-streams-s<n>.md` says so with no `Breaking:` line.
- Supported Pythons: 3.10 to 3.12 (`pyproject.toml:13`). A future CPython that changes `random` makes AT-5 fail on that leg, and E2 keeps the output right on that interpreter.
- GSA S2's single categorical draw (`weighted_draw`, AT-S2-10) stays the one draw definition; the replay is its exact twin, listed in the same guard.

## 11. Pre-mortem

- CPython changes `_randbelow` or `choices` in a version the engine later adds. AT-5 on that leg fails first; E2 keeps the output equal.
- numpy changes the `MT19937.state` layout. AT-5 fails; E2 again.
- The replay's state write-back costs more than it saves for tiny batches. `getstate` and `setstate` are about 10 microseconds per call; at batch 1 that is slower than CPython but equal in bytes. The streamed layout uses batches of thousands of rows, so AT-4 measures the real case.
- A reference column with a declared cast keeps the list path. That is today's cost, not a regression.
- The parent Arrow copy doubles parent key memory for a very large parent. It is priced and refused before the first batch (AT-8), never an OOM.
- #813 or GSA S2 changes shape in review. This row re-anchors to the merged `stream/_batches.py` and `_categorical.py`; the stream bodies do not change.
- GEN-PER-COLUMN later serves a held column through a resident stream and runs the assembler in DAG order. It keeps `array_columns` as the list rule, so the streams here need no change (section 12).

## 12. Slices

| Slice | Content | Size | Gate | Test depth |
|---|---|---|---|---|
| S1 NO-RNG-ARRAYS | `next_array` and `supports_array` on sequence (with E3, E8 and `int_from_index`), constant and distribution; AT-1, AT-2, AT-3, AT-9, AT-9b for those streams; M2, M5 (S1 form), M11, M12 | S: about 60 lines code, 200 lines tests | Codex | T0 per edit; T1 impact selection (generation unit, parity, `tests/generation`) per commit; T2 on the exact head with AT-1 and the mutations. No full suite: no escalation trigger |
| S2 MT-REPLAY | `_mt_replay.py`, `weighted_indices`, `next_array` on categorical and reference, the two moves (section 6), `column_reads_array`, `SealedKeys`, `seal_parent_keys`, the parent-array and categorical population charges, the AT-S2-10 guard entry, the `mt_replay` CI job; AT-1 to AT-8 for those streams; M1, M3, M4, M5 (S2 form), M6 to M10, M13, M14 | M: about 210 lines code, 350 lines tests | Codex and Dennis (R2) | T0, T1 as S1; T2 on the exact head with AT-5 in the new `mt_replay` CI job on three Pythons, AT-8 and the mutations; AT-4 on the Dell. The CI job is a test-tooling change, an escalation trigger, so one full suite runs on the S2 head against the saved main baseline. A golden outside AT-1 moving is a stop |

Order and dependencies:

1. #813 (GSA S1a) merges. S1 here can start that day, in parallel with GSA S1b. Both touch `_column_streams.py` in different classes; the second to merge rebases.
2. GSA S1b and S2 merge in their own order. S2 here starts after GSA S2, because it extends `weighted_draw`'s module and the AT-S2-10 guard.
3. S2 here can build in parallel with GSA S3. Both may touch the `_streamed.py` preflight; the second to merge rebases and recounts its size.
4. GEN-PER-COLUMN (plan on `origin/plan/gen-per-column`) starts after GSA S3 and does not need this row. Its S1 replaces `sibling_read_names` with `TableColumnPlan.batch_reads` and its route; whichever lands second points `column_reads_array` at them. Its S2 and this S2 both create `stream/_table_stage.py` by the same move; whichever lands second builds on it, and both use `seal_parent_keys`. `array_columns` stays the one list rule in both plans.
5. Follow-up, not in this row: GSA's `LookupStream` can call `weighted_indices` for an array path; it is the same helper and needs no new design.

Both slices fit before 2026-12-15.

## 13. Open questions for the owner

None. Q1 of revision 1 (reproduce CPython bytes rather than switch to numpy draws) was answered on 2026-11-22: reproduce.
