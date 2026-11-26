Status: plan (revision 5, 2026-11-26; fix round 2 after Dennis review; re-anchored to #813 head `308cef4a3` and the passed GSA S1b and S2 plan)

# GEN-VECTOR-STREAMS: sequence, constant, distribution, categorical and reference streams hand the assembler Arrow arrays, with the same bytes

Owner: Cam. Author: Opus (plan author). Dates: revision 1 2026-11-22, revisions 2 and 3 2026-11-25, revisions 4 and 5 2026-11-26. Roadmap row: GEN-VECTOR-STREAMS (CLI `docs/roadmap/groups/generate.md`, a 1.0 row): "sequence, reference and null-mask streams ... Output bytes must not change; if they do, back to owner." V1 fast-path audit (vault `10_Projects/decoy/v1-fast-path-audit-2026-11-22.md`, lines 155-156 and 218). Engine only.

Owner decision already recorded (vault `OWNER-OPEN-DECISIONS.md`, 2026-11-22, go-with-recommended): reproduce the CPython bytes. This revision keeps that decision and has no open owner question.

Anchors. A path with no prefix is under `src/decoy_engine/` in decoy-engine. Read at engine `origin/main` `0952fbae2` and at GEN-STREAM-ALL S1a, PR #813, head `308cef4a3` (called "#813" below). Since `f329ccd46`, #813 merged main and moved the Faker locale imports into `internal/faker_locale.py`; the stream bodies in `_column_streams.py` start three lines earlier and their code is unchanged. Since `2b8a47fbe`, main changed only `checksums.py` and `_fpe_checksum.py` under `src/`. Line numbers are at #813. The builder rechecks every line on the merged heads of the dependencies in section 12.

Builds on:

- GEN-STREAM-ALL S1a (#813, open). It already adds the Arrow stream protocol this row needs: an optional `supports_array` property and `next_array(offset, size) -> pa.Array` on a stream (`generation/_column_streams.py:198-206` on `PooledFakerStream`; the probe `supports_array(stream)` at `:282`), the null mask on arrays (`NullMaskedStream.next_array`, `generation/_column_streams.py:258`, a `pc.take` with null positions so a null slot holds no value bytes), and the assembler rule that keeps a column as an array unless a consumer needs Python values (`generation/stream/_batches.py:56` `array_columns`; the type check at `generation/stream/_batches.py:98`). Revision 1 of this plan proposed that protocol; it is now #813's, and this row only adds `next_array` to more streams.
- GEN-STREAM-ALL S2 (plan `origin/docs/plans-gsa-eor-1125:docs/plans/2026-11-25-gen-stream-all-s1b-s2.md`, passed; its `weighted_draw` section and AT-S2-10). It exports `weighted_draw(rng, values, weights, k)` from `generation/kinds/_categorical.py` as the one categorical and lookup draw, and adds a guard that forbids a local `choices` copy in the streamed categorical caller. This row's categorical replay goes through that module, so slice S2 here starts after GSA S2 merges.

Not combined with GEN-NONFAKER-DRAWS S3 (`origin/docs/plans-pap-gnf-1125:docs/plans/2026-11-25-gen-nonfaker-draws-s3.md`). Its `ComputedDrawStream` implements #813's protocol itself and needs nothing from this row. The two rows touch different streams. That plan says GVS chose a counter-based draw; that is wrong (this row replays CPython), and it changes nothing in GNF S3.

Rules consulted: dev-rules `README.md`, `00-universal.md`, `risk-and-exceptions.md`, `development-loop.md` (PLAN), `testing.md` (Test depth), `performance.md`, `catalogs/recurring-defects.md`; the plan contract (`obsidian-vault/30_Resources/Decoy-Plan-Contract-and-Defect-Catalog.md`); engine `CLAUDE.md`.

Risk: S1 is R1 (no RNG, byte-identical, generation only). S2 is R2: byte identity depends on reproducing CPython `random` (section 5.3), and it touches the frozen generation output and the ledger. Plan review: Dennis, then Codex. Code gate: Codex for S1; Codex and Dennis for S2.

## 1. Frame

On #813 each stream below returns a Python list per batch, and the assembler builds `pa.array(values, type=...)` per column per batch (`generation/stream/_batches.py:114`). Only pooled Faker and a null mask over it take the array path.

| Stream | Today (#813) | Cost |
|---|---|---|
| `SequenceStream` (`generation/_column_streams.py:131`) | Python loop; text form runs `str(value).zfill(pad)` and the affixes per row | per-row Python format |
| `ConstantStream` (`generation/kinds/_constant.py:31`) | `[value] * size` | list build and `pa.array` |
| `ParametricStream` (`generation/kinds/_parametric.py:60`) | `default_rng(base_int("dist"))`, clip, `.tolist()` | `.tolist()` then `pa.array` |
| `CategoricalStream` (`generation/_column_streams.py:150`) | `random.Random(base_int("py")).choices(cats, weights, k=size)` | C loop for unweighted (67 ns/row, Dell); Python `bisect` per item when weighted |
| `ReferenceStream` (`generation/_column_streams.py:209`) | per row: `rng.choice(vals)`, `rng.choices(vals, weights, k=1)[0]` or `vals[i % len]` | 468 ns/row for `choice` (Dell) |

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
- #813: `pool_take(pool, indices)` (`generation/pool/_value_pool.py:181`, exported at `generation/pool/__init__.py:92`), the one pooled pick over an Arrow value array. The categorical and reference gathers in S2 call it, so a later change to the pick stays one edit.
- #813: the two-form pool (`ValuePool.arrow`, `generation/pool/_value_pool.py:53`): a Python form for the list path and an Arrow form for the take. `SealedKeys(keys, array)` (section 5.4) follows the same pattern.
- #813: `stream.sibling_input` (`generation/stream/_siblings.py`), the one rule for which column a later column reads; `array_columns` already uses it.
- GSA S2: `weighted_draw` in `generation/kinds/_categorical.py` (the one categorical and lookup draw) and its AT-S2-10 guard.
- `GenDeriveContext.base_int("py")` and `base_int("dist")`: seed roots unchanged.
- `sequence_affixes` (`generation/_numeric_typing.py:77`) and `_fits` (`generation/_numeric_typing.py:90`): the one reading of affixes and the int64 bound.
- `check_reference_pool` (called at `generation/_column_streams.py:226`): still runs once per stream.
- `key_pool_bytes` (`generation/_bounds.py:301`), the preflight term at `generation/_streamed.py:238` and the live reservation at `generation/_streamed.py:485`: the model for the one new reservation in S2.

## 3. Guarantee and non-goals

After this row:

1. `SequenceStream`, `ConstantStream` and `ParametricStream` (S1), and `CategoricalStream` and `ReferenceStream` (S2) have `supports_array` and `next_array`. Their arrays are byte-identical to today's list output, type included, for every config those streams accept.
2. Output does not depend on how rows are split into batches, on every supported Python, on both paths.
3. The assembler's rule for when a column must stay a list is #813's, unchanged: a declared `output_type`, a key collector, a same-batch sibling reader, or a type mismatch. This row adds no new reason to build a list and removes none. E9, E10 and E11 act only through the stream's own `supports_array`, as #813's pooled Faker capability already does.
4. A stream that serves both `next_batch` and `next_array` leaves the same RNG state after the same rows, so the two methods can be mixed on one stream without changing later rows.
5. Whole-table generators (`synthesize.py`, `kinds/_lookup.py`, `window.py`) and their bytes are unchanged.
6. When the replay cannot prove itself on the running interpreter, or a config falls outside what the replay reproduces exactly (section 4, exit paths), the stream uses today's CPython draw. That is decided once per stream, never per batch.
7. The speed-up memory is optional. The parent-key Arrow copy (section 5.4) and each replay population (section 5.3) are admitted only when the mode chosen on the baseline plan still fits with them. Admission preserves that mode and its reason. When one does not fit, that column takes the list path or the CPython draw. A job that passes today's preflight is never refused because of them (sentry in section 7.2, row 11).
8. The weighted-draw floor rises. The preflight now prices CPython's temporary cumulative-weights list for a weighted categorical or weighted reference column (section 5.3). Today's preflight does not count that memory, so a job with a large weighted population can refuse at a ceiling it passes today. The pricing is correct: today's run uses that memory without a charge. GSA S2 owns the scratch helper and the lookup charge; this row owns the term for categorical and reference columns. If GSA S2 already charges those columns when it merges, this row reuses that term and adds none. For pooled Faker, only bounded allocation rounding, including space for the terminal offset, can raise the Arrow charge. The per-row rates, doubling and fixed allowance stay the same. The changelog fragment records both effects (section 10).

Non-goals: per-row Faker (GEN-NONFAKER-DRAWS); pooled Faker (GSA); `windowed_date`; lookup streams (GSA S2 owns `LookupStream`; it can call the S2 helper later with no plan change, section 12); an Arrow key collector (`KeyPool` stays a Python list, so a key column keeps #813's list path); distribution families other than `uniform` (none exist); a Rust kernel (engine record `docs/records/2026-11-19-engine-speed-and-route-completeness.md` section 2.3 found Rust selection slower than numpy).

## 4. Enumerations

### Exit paths

| # | Condition | Result | Slice |
|---|---|---|---|
| E1 | replay self-test passes, config in range | numpy replay for `choice` and `choices` | S2 |
| E2 | replay self-test fails on this interpreter | CPython draw, `pa.array` over its list; bytes equal; one debug record per process names the fallback | S2 |
| E3 | sequence value for any planned row outside int64 | today's Python loop; decided at construction from `rows` with `_fits` (`generation/_numeric_typing.py:90`) | S1 |
| E4 | empty reference pool | a null array of the column type, as today's `[None] * size` (`ReferenceStream`, `generation/_column_streams.py:209`); the relationship policy's fail or warn (`generation/relational/_cardinality.py:143` onward) runs first, at construction, as today | S2 |
| E5 | `size == 0` | empty array; the RNG is not advanced (CPython `choices(k=0)` draws nothing) | S1, S2 |
| E6 | weights length differs from values, total not positive or not finite, a negative weight, a cumulative weight beyond 2**53 in magnitude, an empty category list, or a reference pool of at least 2**32 keys (bit length 33); a weight that is not an `int` or `float`; the preflight chose the CPython form because the replay population does not fit (section 5.3) | CPython draw for that stream, so today's `ValueError` or `IndexError` is raised with the same text at the same batch, or today's values come out | S2 |
| E7 | the drawn array's type differs from the schema field | #813's list fallback (`generation/stream/_batches.py:98`); bytes equal | S1, S2 |
| E8 | `offset + size > rows` on a sequence (a caller reading past the planned rows) | the list path for that batch, so int64 cannot wrap silently | S1 |
| E9 | the parent key list does not convert to the child's schema field type | `SealedKeys.array` is `None`, so each child `ReferenceStream.supports_array` is `False` and `NullMaskedStream` passes that on; every child reference column over that parent is a list column, decided at seal, before any child stream opens (section 5.4); the reservation stays charged (over-charge only) | S2 |
| E10 | the parent key field has 32-bit offsets (`string` or `binary`) and the projected payload is over `2**31 - 1` bytes (`_OFFSET_LIMIT`, `_arrow_types.py:42`), or the built copy is a `pa.ChunkedArray` (pyarrow splits a binary array that overflows its offsets) | `SealedKeys.array` is `None`, as E9: every child reference column over that parent is a list column. `reference_array_parts` returns `None` for the projected case, so the preflight never admits that copy and there is no charge. A chunked result found at seal is dropped, and its charges are released before the parent's first batch | S2 |
| E11 | the preflight did not admit the parent-key copy because the run does not fit with it (section 5.4) | `SealedKeys.array` is `None`, as E9; no `parent_key_array` charge and no event | S2 |

Order, so a cell that matches two rows takes the CPython result. Reference: construction is unchanged from #813 (`generation/_column_streams.py:226` onward), so a nonempty weighted pool with `weights: []` still raises the coded length error from `generation/relational/_cardinality.py:167-172` at construction, and the empty-pool policy runs there too; after construction E4, then E5 (a zero-size batch draws nothing and checks no weights, as the per-row loop does), then E6; a random reference on any fallback draws with `choice` per row, as today. Categorical: E6 before E5 (CPython `choices(k=0)` still validates its weights), and categorical `weights: []` keeps today's normalization. E2 before E1. An unknown reference `distribution` takes the `choice` branch, as today. Parent copy: E10 and E11 are decided before E9 can be seen (preflight and seal); all three give the same result, `SealedKeys.array = None`.

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

- `reference` to a parent table: the sealed parent key list keeps its insertion order. S2 builds one Arrow copy of it per referenced parent key column that some child reference column reads on the array path (section 5.4), typed with the parent key's schema field type, reserved in the ledger, stored in the same `key_pools` entry as the list, shared by every such child stream, and gathered with `pool_take`. The indices are the ones CPython would draw.
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
| ledger events | S2: two new optional reservation labels, `parent_key_array:<table>.<column>` and `replay_population:<table>.<column>`, each written only when the preflight admitted it |
| debug log | one record per process on E2, naming the Python version and the stream kind only |
| `docs/` | the generation route section of `CODEMAP.md` and the streams module docstring |

## 5. Design notes

Principles that apply: one place per fact (one replay module; the list-or-array rule stays in `array_columns`); open/closed on streams (a stream opts in by adding `supports_array` and `next_array`; the assembler never switches on stream type). Established pattern: CPython's own algorithms, reproduced (section 2).

### 5.1 Constant and distribution (S1)

Constant: `pa.repeat(pa.scalar(value, type=constant_arrow_type(col)), size)` for a non-null value, and `pa.nulls(size, pa.string())` for `None` (`constant_arrow_type` gives `pa.string()` for `None`; `config/_generate_type_checks.py:326`). The type comes from the same helper the schema uses, so E7 is a guard, not the normal path. If the type still differs from the schema field, E7 applies. Distribution: the same `default_rng` draw and clip, then `pa.array(ndarray)` with no `.tolist()`. A float64 value converts to the same Arrow double either way, NaN included.

### 5.2 Sequence (S1)

At construction, `_fits(start, start + step * (rows - 1))` decides the vector form (E3). Numeric form: `int_from_index(np.arange(offset, offset + size), lo=start, step=step)` from `generation.pool` (`generation/pool/_computed_draw.py:234`, exported at `generation/pool/__init__.py:126`). It does the arithmetic modulo 2**64 on uint64, so a step at or past 2**63 with every output inside int64 (for example `start = -2**63`, `step = 2**64 - 1`, two rows) gives the exact values; a plain int64 `np.arange(...) * step` raises `OverflowError` there. The existing `SequenceStream` constructor calls (`synthesize.py:413`, `window.py:195`) do not change; they pass no `rows`, and a `SequenceStream` built with `rows=None` has `supports_array` False. Text form: that int64 array cast to string, then for `pad_length > 0` the sign-aware pad (non-negative values: `utf8_lpad(width=pad, padding="0")`; negative values: `"-"` joined to `utf8_lpad(body, width=pad - 1, padding="0")`, where `body` is the cast string with its leading `"-"` sliced off, not `pc.abs`, which wraps at `INT64_MIN`), then `binary_join_element_wise(prefix, body, suffix, "")`. The stream needs `rows`, which `make_column_stream` already has (`generation/_column_streams.py:301`), as an optional argument. numpy int64 wraps silently, so `next_array` checks `offset + size <= rows` and takes the list path otherwise (E8).

### 5.3 Replay (S2)

New `generation/kinds/_mt_replay.py`, exported through `generation.kinds`, about 110 lines. It holds no RNG of its own. Each call works on the caller's `random.Random`:

1. read `rng.getstate()`, load the 624 words and position into a fresh `np.random.MT19937`;
2. draw the raw 32-bit words the call needs;
3. write the advanced key and position back with `rng.setstate((3, tuple(words.tolist()) + (pos,), gauss_next))`. The words go back as native Python ints (CPython's `setstate` refuses a tuple of numpy `uint32` with `TypeError`) and `gauss_next` is carried over unchanged.

The adapter reads the state, draws on numpy, and calls `setstate` once at the end. If any step before that `setstate` raises, the stream RNG is untouched and that call takes the CPython draw. `replay_ok()` runs its probe on disposable `random.Random` objects, and any exception in the probe (a changed `getstate` layout, a numpy API change, a refused `setstate`) counts as a mismatch: E2, before any stream RNG is read.

So the `random.Random` a stream already holds stays the one source of truth. `next_batch` (CPython) and `next_array` (replay) leave identical state after the same rows (guarantee 4), and a switch between them mid-run cannot change later rows.

Functions:

- `ReplayPopulation(n, cum_weights, total)` and `prepare_population(n, weights) -> ReplayPopulation | None`: the one prepared form of a population, built once per stream at construction, after its reservation (section 5.3, draw form). For `weights is None` it holds `cum_weights = None`. Otherwise it runs `list(accumulate(weights))` in Python once (exact, as CPython does), runs every E6 check once, converts the list to one float64 array, and frees the list. It returns `None` when E6 applies, and the stream then uses CPython for its whole life. Both callers below take this object; neither takes raw weights.
- `replay_choices(rng, pop, k) -> np.ndarray[int64]`: `random()` from word pairs, then `floor(u * float(pop.n))` when `pop.cum_weights is None`, or `min(searchsorted(pop.cum_weights, u * pop.total, "right"), pop.n - 1)`. Each value takes exactly two words, so the words consumed are `2 * k`.
- `replay_randbelow(rng, n, k) -> np.ndarray[int64]`: `kbits = n.bit_length()`, words shifted by `32 - kbits`, rejection in order. The word count is not known in advance: draw blocks of at most `min(k + k // 2 + 64, 65_536)` words on a copy of the state, writing accepted values into the `k`-row output as each block is scanned and keeping no block after it is scanned, until `k` are accepted; then advance the real state by exactly the number of words up to the `k`th accepted one. Scratch is one block plus the output, both bounded by the batch. Rejected words are consumed, as in CPython. The block rule changes only speed, never values (AT-5 covers acceptance rates near one half).
- `replay_ok() -> bool`: a fixed self-test (tests force E2 through the module seam `_mt_replay._replay_ok_override`, and an adapter failure through `_mt_replay._state_adapter`; never by patching `random.Random`), run once per process on first use and cached: three seeds, sizes 0, 1, 7 and 4096, each function against `random.Random` on the same seed, including a weighted case with a zero weight and an `n` just above a power of two. Any mismatch sets E2 and writes the debug record.

Callers:

- `generation/kinds/_categorical.py` (GSA S2's `weighted_draw` module) gains `weighted_indices(rng, pop, k)`, which returns `replay_choices` indices, or `None` when E2 applies. `weighted_draw` is unchanged. `CategoricalStream` builds `self._pop = prepare_population(len(cats), weights)` and `self._cats_array = pa.array(cats, type=categorical_arrow_type(col)[0])` (`config/_generate_type_checks.py:298`) once at construction. When that helper gives no type, `_cats_array` is `None` and `supports_array` is False. `next_array` gathers `pool_take(self._cats_array, indices)`; when `self._pop` or the indices are `None` it returns `pa.array(weighted_draw(...), type=field_type)`.
- `ReferenceStream.next_array`: `random` calls `replay_randbelow(rng, len(vals), size)`, as `choice` does; `weighted` calls `weighted_indices(rng, self._pop, size)` (one `random()` per row, as `choices(k=1)` per row does). `weighted` with no `weights` (or `weights: []` over an empty pool, which E4 serves) keeps `self._weights = None` (`generation/_column_streams.py:229`), so CPython calls `choices(vals, weights=None, k=1)`: the unweighted `floor(random() * n)` form, two words per row. The replay maps it to `replay_choices` with `pop.cum_weights = None`, never to `replay_randbelow` (one word per row, different values); `ReferenceStream` builds `self._pop = prepare_population(len(vals), self._weights)` once at construction, for `weighted` only. `sequential` uses `np.arange(offset, offset + size) % len(vals)` and no RNG. Values are `pool_take(parent_array, indices)`. `NullMaskedStream` keeps its own `pc.take` over null positions (`generation/_column_streams.py:268`): that is a mask, not a pool pick.

**Draw form at preflight (S2).** Weighted categorical and weighted reference draws both use CPython's `choices` (`generation/_column_streams.py:158` and `:240`). Each call builds a temporary cumulative-weights list over the whole population. A million weights cost about 32 MB even for one row on CPython 3.10.20. Use GSA S1b+S2's lookup scratch helper to price each call.

A table draws one column at a time (`generation/stream/_batches.py:87-104`). Each call frees its scratch before the next column draws. Add the largest single scratch estimate in the stage to its other costs. Use zero if the stage has no weighted callers. Keep that allowance for CPython fallback even when replay is admitted. `prepare_population` builds the same list once at construction and frees it before the next stream opens; no column draws while streams are built, so the same single-scratch allowance covers it.

Replay populations stay live together. Price each with `replay_population_bytes(n, arrow_type, width)` in `generation/pool/_resident.py`. Include the `ReplayPopulation` float64 cumulative weights (`8 * n`) and, for categorical draws, `_cats_array`. One greedy admission in `draw_forms` decides every optional reservation in the run: the parent-key copies (section 5.4) and the replay populations. Start with every copy absent and all weighted columns on CPython. Before opening any stream, decide `stream_it` once on this baseline using #813's bounded-sink check and `_fits(ledger, plan.streaming_peak())`. If resident was selected, apply its existing baseline refusal check. Keep that mode and reason through execution. Try parent-key copies in plan table order using section 5.4, then replay-eligible columns in table column order. Include each trial population with the other admitted populations of its stage. For either kind of candidate, call `_fits` on the trial plan's peak for the selected mode only. Keep the trial in `draw_forms` if it fits, otherwise discard its charges and continue (E11 for a copy, E6 for a population). Never recompute `stream_it` after admission. An unbounded ledger admits all eligible columns. The live stage uses `draw_forms` and reserves each admitted population before building it. The row index array and batch-sized replay scratch go in the batch term beside `generation/_bounds.py:247`.

S2 keeps CPython for a case where the measured end-to-end batch is slower with the replay (expected: unweighted categorical with few categories). In that case `next_array` is `pa.array(weighted_draw(...), type=field_type)`: it skips `next_batch`, `to_pylist` and `restore_declared`, and AT-3 asserts exactly that for the case. That choice is a constant in `_categorical.py`, chosen from the AT-4 measurement and recorded in the PR; the replay still serves weighted categorical and every reference form.

### 5.4 Reservation for the parent array (S2)

The Arrow copy of a sealed parent key list is new memory, so it is priced before it is built. The decision whether a column takes the array path must be the same at preflight (no streams exist yet), at the parent's live reservation (the child's streams do not exist yet) and in the assembler. A per-table rule cannot see collectors: in a chain `A.id -> B.fk -> C.fk` only C's config shows that `B.fk` is collected. So S2 extracts the checks `array_columns` already makes (`generation/stream/_batches.py:63` onward: declared cast, collector, sibling reader) into one plan-wide predicate in `generation/stream/_batches.py`:

`column_reads_array(table, col, table_cols, collected)`: no declared output type, `(table, col)` not in `collected`, and not read by a later column of its table (`sibling_read_names` on #813; GEN-PER-COLUMN S1 replaces that with `TableColumnPlan.batch_reads` and its route, and this predicate then calls those). `collected` is every column that has a collector, plan-wide, not only reference targets. On the GSA head it is the FK target set from `_referenced_keys` (`generation/_streamed.py:180`; GSA S1b+S2's `referenced_key_columns`). On the GEN-PER-COLUMN head it also holds the parent non-key columns that `TableColumnPlan` collects for a child's `windowed_date.anchor_via`, because #813's array branch leaves `values` unset and the collector at `generation/stream/_batches.py:117-118` would get nothing. `array_columns` calls it for every column and adds only the stream's `supports_array`, as #813 does (`generation/stream/_batches.py:63-69`). Capability stays on the stream instance, as #813 already does for pooled Faker (`generation/_column_streams.py:198-200`) and propagates through `NullMaskedStream` (`:254-256`): `ReferenceStream.supports_array` is `sealed.array is not None` (E9 is known at seal, before the child stream opens). E2, E4, E5 and E6 are handled inside `next_array`. The predicate is the structural rule the preflight uses; the stream capability can only turn an admitted column into a list column (over-charge only). A parent key column needs a copy when at least one child reference column over it passes `column_reads_array`; two such children share one copy and one charge.

For sizing, `reference_array_parts(parent_rows, key_type, key_payload)` returns retained bytes and the conversion peak, or `None` when E10 applies (32-bit offsets and `parent_rows * key_payload` over `_OFFSET_LIMIT`, reused from `_arrow_types.py:42` and read as a module attribute at call time). Both come from one new helper, `arrow_allocated_bytes(arrow_type, rows, width, validity: bool)`, in `src/decoy_engine/_arrow_types.py` beside `arrow_column_bytes` (`:243`). `faker_pool_resident_parts` (`generation/pool/_resident.py:72-82`) switches to it too, so `pool/_resident.py` holds no Arrow-size helper of its own. The new helper counts each allocated buffer separately: data, the `rows + 1` offsets (4 bytes each for `string` and `binary`, 8 for `large_string` and `large_binary`), and the validity bitmap when requested. Pass the retained array’s bitmap requirement for retained bytes and `validity=True` for the Faker build peak even if the finished array drops the bitmap. It rounds each buffer up to the allocator's allocation size before adding. In PyArrow 24, `pa.array([""])` retains 64 bytes for its 8-byte offsets buffer. The conversion peak also covers builder growth to the next power of two and the input list. The pool keeps its own doubling and fixed allowance on top.

Why two helpers. `arrow_column_bytes` is a logical estimate for the bounds and lifecycle budgets (`_bounds.py`, `pipeline/_lifecycle.py`): `rows` offsets, no validity bitmap, no rounding. Those callers compare against estimates of the same kind, and moving them would change today's refusal floors. A reservation for memory that is really allocated needs the rounded count (`arrow_column_bytes` is four bytes short on a one-row `[""]`). Both stay in one module, and a guard test holds them in order: `arrow_allocated_bytes(t, r, w, validity) >= arrow_column_bytes(t, r, w)` for both validity flags and every `t` in int64, float64, bool, string, binary, large_string and large_binary, every `r` in 0, 1, 7 and 4096, and `w` in 0, 1 and 64 (AT-8b).

Admission. The copy is optional (guarantee 7). The preflight admits it through the `draw_forms` greedy admission in section 5.3: a candidate parent key column (one that some child reads through `column_reads_array`, with `reference_array_parts` not `None`) adds its retained bytes to `key_pools`, shared by both run peaks (`generation/_streamed.py:216-220`). Set `stage_peak` to the maximum of the ordinary stage estimates (including admitted populations) and the individual conversion peaks of all admitted copies, including the trial copy. Each conversion therefore competes for the stage maximum on top of the key-pool total that already includes all retained copies. Keep the trial only if the peak for the baseline mode passes `_fits`. Otherwise `draw_forms` records the copy as not admitted (E11), and the job runs on the list path with today's memory. So the copy never moves the refusal floor: a job that fits today without the copy runs at the same ceiling.

Lifetime of an admitted copy: one retained charge per parent key, label `parent_key_array:<t>.<c>`, reserved on `run_stack` before the parent's first batch, beside the `parent_key_pool` charge (`generation/_streamed.py:482-488`). It is held from seal through the last child that reads it and released once when the run ends, on success and on every failure (seal, child, sink). The conversion peak is a short charge taken on the same ledger at seal and released when the copy is built. The copy is built at seal (`generation/_streamed.py:512-513`) with the parent key's schema field type and kept in the same `key_pools` value as the list, as a `SealedKeys(keys, array)` record. `array` is `None` when no child reads it, when the copy was not admitted (E11), when E9 applies, or when E10 applies. A built copy that comes back as a `pa.ChunkedArray` (E10 at seal) is dropped and both charges are released at once. There is no second dict. A live reservation for an admitted copy that still refuses is a pricing bug, not a fallback case: it raises `GenerationBudgetExceeded` before the parent's first batch, as the replay population reservations do. Under an unbounded ledger every copy is admitted, and the charges are recorded and never refuse.

Ownership with GEN-PER-COLUMN: byte formulas (`key_pool_bytes`, `reference_array_parts`, `replay_population_bytes`) live in `generation/pool/_resident.py`; the per-table orchestration (reservations, seal) lives in `generation/stream/_table_stage.py`, the module GEN-PER-COLUMN S2 creates by moving `_consume_table` and the per-table loop out of `_streamed.py`. One `seal_parent_keys(...)` operation builds `SealedKeys` for ordinary parents and for GEN-PER-COLUMN's deferred parents.

## 6. Placement

| What | Where | CODEMAP line | Beside |
|---|---|---|---|
| `next_array` on sequence, categorical, reference | `generation/_column_streams.py` (410 on #813, about 440 after GSA S2; about +35 in S1, +45 in S2, about 520 at the end) | "Generation", `_column_streams.py` row | the other streams |
| `next_array` on constant, distribution | `generation/kinds/_constant.py` (40, about +8), `generation/kinds/_parametric.py` (77, about +6) | `kinds/` row | the list forms |
| replay | `generation/kinds/_mt_replay.py` (new, about 110), exported by `generation/kinds/__init__.py` (83, about +3) | `kinds/` row | `_categorical.py` |
| `weighted_indices` | `generation/kinds/_categorical.py` (72 on #813, about 82 after GSA S2, about +15) | `kinds/` row | `weighted_draw` |
| `arrow_allocated_bytes` | `src/decoy_engine/_arrow_types.py` (254 on #813, about +25) | the `_arrow_types.py` row | `arrow_column_bytes` |
| `reference_array_parts`, `replay_population_bytes` | `generation/pool/_resident.py` after the move below (about +35); calls `arrow_allocated_bytes`, defines no Arrow-size helper | "Generation" pool | `faker_pool_resident_parts` |
| `OPTIONAL_RESERVATIONS`, `REQUIRED_RESERVATIONS` | `generation/_budget_ledger.py` | "Generation" | the ledger |
| `ReplayPopulation`, `prepare_population` | `generation/kinds/_mt_replay.py` (counted in its 110 lines) | `kinds/` row | the replay functions |
| `column_reads_array` | `generation/stream/_batches.py` (121 on #813, about +15; the checks move out of `array_columns`) | "Generation streamed batch assembly" | `array_columns` |
| live reservations, `seal_parent_keys`, `SealedKeys` | `generation/stream/_table_stage.py` (created by the move below, about 120, then about +35) | "Generation streamed batch assembly" | `_consume_table` |
| preflight terms | `generation/_streamed.py` (about +12 after the move takes about 90 out) | "Generation" | the `key_pool_bytes` terms |
| tests | `tests/unit/generation/stream/test_vector_streams.py`, `tests/unit/generation/kinds/test_mt_replay.py`, `tests/unit/test_arrow_types.py` (AT-8b cell) | generation unit tests | #813's stream tests |
| sentry | `tests/sentry/generation/test_optional_reservations.py` (new, about 80) | `tests/sentry/generation/` | the other generation sentries |

`generation/` keeps its 25 counted modules (the fan-out limit; `__init__.py` is not counted); `kinds/` takes one. By the numbers above both files would pass 600, so S2 starts with two moves, each its own commit with no behavior change: (1) `key_pool_bytes` moves from `_bounds.py` into `generation/pool/_resident.py` beside `faker_pool_resident_bytes`, behind the same import (GEN-PER-COLUMN S2 names the same move; whichever row lands first makes it); (2) `_consume_table` (`_streamed.py:423`) and the per-table loop with its reservations and key sealing (to `:514`) move into `generation/stream/_table_stage.py`, the same move GEN-PER-COLUMN S2 names; whichever row lands first makes it, and the other adds to the moved code. `stream/` gains that module either way, counted once in both plans. The builder recounts `_streamed.py` after the move and after GSA S2 and S3; it stays under 600. Neither move raises a size ceiling.

`_mt_replay.py` is an RNG adapter, and CODEMAP describes `kinds/` as source-free generate types. It still goes in `kinds/`, beside `weighted_draw`, the one draw it twins: AT-S2-10 guards that module, and `pool/` already has 16 modules of pool primitives that hold no RNG. The S2 PR adds one line to the CODEMAP `kinds/` row naming the replay adapter.

## 7. Defect classes

### 7.1 Plan-contract classes

| # | Class | Where it applies | Structure that closes it | Proof | Mutation that must turn it red |
|---|---|---|---|---|---|
| 1 | Value-bearing output | the E2 debug record; E6 errors | the record names only the stream kind and Python version; E6 reuses CPython's own error text, which carries no generated value | AT-7 | M7 |
| 2 | Cleanup missing on an exit path | the parent-array and categorical population reservations | retained charge on `run_stack` with `parent_key_pool`, conversion charge released when the copy is built; both released at once when E10 drops a chunked copy; categorical charge on the table stage; released once on every exit | AT-8, AT-10 | M8, M17 |
| 2b | New memory made mandatory | the parent-key copy and the replay populations | one `draw_forms` greedy admission; each optional label registered in `OPTIONAL_RESERVATIONS`; the sentry "no new required reservation without a fallback" | AT-8 floor cell, AT-6 (a), the sentry | M16, M16s |
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
| 5 | Normalized guard scanners | yes, GSA's AT-S2-10 AST guard gains two allowed helpers: `weighted_indices` (the `choices` twin) and `replay_randbelow`, listed as a separate allowed contract because it is a second bounded-index draw beside GSA's bounded-index cursor and replays `choice`, not `choices`. The new reservation sentry matches `<expr>.reserve(<label>, ...)` calls in the syntax tree of `generation/`, with the label as a string constant or an f-string whose leading constant part gives the prefix; those are the shapes the code uses today | AT-S2-10 still red on a seeded local `choices` copy; the reservation sentry red on a seeded unregistered label |
| 6 | No reaching into private modules | `_mt_replay.py` is reached only through `generation.kinds` | import-linter and the `kinds/_` rule |
| 7 | No hidden CI failures | unit tests run on 3.10 only; the 3.11.9 and 3.12.7 legs run import smoke and `faker_output_lock` (`.github/workflows/ci.yml` at #813, lines 63-96). S2 adds marker `mt_replay` on `test_mt_replay.py` and a CI job running `pytest -m mt_replay` on 3.10.20, 3.11.9 and 3.12.7 with `fail-fast: false` | the job in the S2 PR |
| 8 | One input, one trust class | no | - |
| 9 | Mutations on the final head | yes | named mutations on the final head of each slice, head recorded |
| 10 | Allowlisted helpers are still checked | yes, `weighted_indices` and `replay_randbelow` join the AT-S2-10 list by exact `(path, name)` | the guard spies on each on the matching branch |
| 11 | No raised caps | `generation/` fan-out 25, module size; and the memory floor | new module in `kinds/`; sizes in section 6. Sentry `tests/sentry/generation/test_optional_reservations.py`, "no new required reservation without a fallback": the sentry imports both prefix sets from `generation/_budget_ledger.py`. Every ledger label prefix reserved in `generation/` is either in `REQUIRED_RESERVATIONS` (the sentry's ratchet, equal to the prefixes on today's main; it may shrink, never grow without a reviewed change) or in `OPTIONAL_RESERVATIONS`, and each optional label has a `draw_forms` key the preflight can drop. Apart from Faker allocation rounding, the floor increase (guarantee 8) is the CPython scratch term, priced through GSA's helper, not a new ledger label |

## 8. Acceptance tests

Goldens are captured on the dependency head, before any stream change, through the public `generate_tables_streamed` with a bounded Parquet sink and a resident run, and committed with the tests.

| ID | Test | Fail-before | Slice |
|---|---|---|---|
| AT-1 | Golden parity (tables hold no Faker, lookup or provider columns, so GSA S1b's intended byte changes cannot move the goldens): for each stream and each field form in section 4 (negative start with pad, pad shorter than the value, prefix and suffix, numeric form, constant `None` and string, uniform with and without clip, weighted with a zero weight, reference `random`, `weighted`, `weighted` with no `weights` (two words per row, the unweighted `choices` form), `sequential`, empty pool, null probability 0, 0.3 and 1 over each), tables of 1, 7 and 120,000 rows equal the goldens: decoded values, schema, and the Parquet file bytes at a fixed batch layout, compared with the footer's `created_by` string stripped (it names the pyarrow version, so a pyarrow bump would otherwise fail the goldens). Sequence overflow cells: `start = -2**63, step = 2**64 - 1` over two rows, its descending counterpart `start = 2**63 - 1, step = -(2**64 - 1)`, and a one-row sequence with a step past 2**64; each equals the golden through the vector form (not E3). S1 covers its three streams; S2 the other two | passes before (guard); fail-before is AT-3 | S1, S2 |
| AT-2 | Partition invariance through `run_generation(partition=...)` (`generation/_plan_entry.py:290` exposes only `batch_rows`): a 4,110-row table with layouts `[7, 4096, 3, 4]`, `[0, 4110]`, `[1]*10 + [4100]` and `[4110]` gives equal tables, zero-size pieces included | passes before; guards state carry | S1, S2 |
| AT-3 | Array path taken: for each stream of its slice, with no declared cast, collector or sibling reader, a spy sees `next_array`, no `next_batch`, and no `pa.array` over a list for that column; with a sibling reader the list path is used and values equal AT-1: through the public route a `windowed_date` whose anchor is an admitted date column; through a direct assembler fixture (public `condition_on` declines to legacy on #813, `generation/_admission.py:259`) a `condition_on` parent on a categorical. `constant(None)`, malformed weights and a mixed-type key list (E9) are tested at the direct stream and seal seams that accept them. A deliberate E7 mismatch: `to_pylist` and the conversion happen once and the stream is drawn once. For the unweighted categorical kept on CPython (section 5.3) the spy asserts no `next_batch`, no `to_pylist` and no `restore_declared`; `pa.array` over the drawn list is allowed for that case only. A `SequenceStream` built with `rows=None` (the `synthesize.py:413` and `window.py:195` calls) has `supports_array` False. `column_reads_array` gives the same answer from config before streams exist and inside `array_columns` after; `array_columns` delegates to it (spy). The categorical and reference array paths gather through `generation.pool.pool_take` (spy on the name each stream module imports). A three-table chain `A.id -> B.fk -> C.fk`: `B.fk` is a list column and is collected, C reads B's keys, A reserves no copy, B reserves one; two sibling children over one parent share one copy and one charge. An E9 parent with one masked and one unmasked child: both are list columns with equal values. Integration cell, run on whichever of this row and GEN-PER-COLUMN lands second: a parent with distinct `id` and `created` date columns, a child with a `reference` to `id` and a `windowed_date` whose `anchor_via` reads the parent `created`; the parent `created` is a list column, it is collected, and the child's dates equal the legacy loop | list today | S1, S2 |
| AT-4 | Speed, `perf`, Dell vm-run, the same end-to-end workload on the dependency head and on the candidate: a 10,000,000-row table with one reference column over 100,000 parent keys at or under 60 ns per row for that column on the candidate (the per-row `choice` draw alone costs 468 ns; the builder times the same end-to-end workload on the dependency head first and records it as the fail-before, which must be above 60 ns per row); the S2 PR records unweighted and weighted categorical with and without the replay and the constant chosen in section 5.3 | 468 ns today | S2 |
| AT-5 | Replay equality and mixing: on every CI Python leg, `replay_choices` and `replay_randbelow` equal `random.Random` for `random`, `_randbelow`, `choice`, `choices` with and without weights, over seeds and sizes 0, 1, 7, 4096; after each call `rng.getstate()` equals the CPython generator's state after the same draws. A stream that alternates `next_batch` and `next_array` over `[7, 4096, 3]` equals the one-path golden. `_replay_ok_override = False` forces E2; output then still equals AT-1. Crafted state: a helper sets the MT key at `pos` to untempered words that give a chosen `u`. With `u = 0.5` and weights `[1, 1]` the replay picks index 1 as `bisect` does (kills `side="left"`); with `u = 0.75` and weights `[5e-324, 0.0]`, `u * total` rounds to `total` and the clip keeps index 1 as CPython's bounded `bisect` does (kills removing the clip). Adapter, two cells: (1) on a supported interpreter a replay call writes back and the full `getstate()` equals CPython's after the same draws, with a spy proving the replay ran; (2) with the probe cache cleared, `_state_adapter` made to raise during the probe gives E2 (`replay_ok()` is False), and the stream's next draw and full state equal CPython's. `replay_randbelow` at `n = 2**k + 1` (acceptance near one half) for `k` 4096 crosses several blocks. Runs under marker `mt_replay` on 3.10.20, 3.11.9 and 3.12.7 | no replay today | S2 |
| AT-6 | E6 cells: weights length mismatch, zero total, a negative weight with a positive total, a cumulative weight above 2**53, empty categories, a reference over `range(2**32)` at the direct seam (values and state equal CPython's), a `Decimal` weight (CPython's `TypeError`), for a 1,000,000-category weighted categorical and a weighted reference over 1,000,000 parent keys, each in a one-row job: (a) a fallback-only ceiling, above the mandatory CPython scratch and below mandatory plus replay: the job completes on CPython with no replay allocation and no replay ledger event; (b) a replay-admitted ceiling: the replay reservation event comes before the buffers are allocated (spy order); (c) a ceiling below the mandatory scratch refuses before any stream opens, as GSA prices it. Cell (d) puts two weighted categorical columns in the same one-row table, each with 1,000,000 categories. Use a resident run at the smallest band-adjusted ceiling that fits its other costs plus one column's scratch. Check that the same ceiling fails `_fits` with both scratch estimates added (`generation/_streamed.py:268-271`). The job must complete and both values must match the CPython golden. Categorical `weights: []` at the direct seam raises CPython's `ValueError` even at `k = 0`. Call-count cell: over a three-batch run each weighted stream calls `prepare_population` exactly once, at construction, after its `replay_population` reservation event (spy order), and the E6 checks run once. For the negative-weight and above-2**53 cells the test uses the AT-5 crafted-state helper to pick a `u` where the bare replay (E6 check off) differs from CPython, and asserts that precondition first. Each cell: each raises the same exception type and text at the same batch as the golden run, or (negative weight, large weight) gives the golden values through CPython | no replay today | S2 |
| AT-7 | The E2 debug record names only the Python version and stream kind; a test seeds a category value and asserts it is absent from every record and error | no record today | S2 |
| AT-8 | Parent-array reservation: the live retained event equals `reference_array_parts(100_000, key_type, payload).retained` and the seal event equals its conversion peak; with two admitted copies whose larger conversion dominates ordinary stages, assert the chosen preflight peak equals layouts + baseline key pools + both retained charges + max(ordinary stages and both individual conversions) + the mode's sink or accumulator term; preflight and live call the one helper (spy); on a separate fixture whose ordinary stage dominates conversion, both run peaks (resident and sink) grow by exactly the retained bytes against the same plan with the child on the list path; retained and conversion peak are each at or above their own measurement (`pa.total_allocated_bytes` after the copy, and the peak during conversion) for string and large_string keys of payload 0, 1 and 64 and int64 keys, including one-row `[""]`; one retained charge per parent key, live through the last child, released exactly once on run exit for success, seal failure, child failure and sink failure; mode cell with a bounded sink whose baseline streams but whose trial copy fits only the resident peak: assert no copy admitted, no retained event, mode `streamed` and reason `eligible`. Trace mode selection once on the baseline to catch redundant recomputation even after a rejected trial; floor cell (HIGH-1): at today's band-adjusted floor for the same plan (the smallest ceiling the dependency head's `_fits` passes, `_streamed.py:268-271`, measured on the dependency head and recorded), the job completes on the list path with no `parent_key_array` event, its output equals the AT-1 golden, and the next lower ceiling refuses with `GENERATION_BUDGET_EXCEEDED` before the parent's first batch and before any sink write, as it does today; at that floor plus the copy's retained bytes and conversion peak, the copy is admitted and its events appear; on a ledger directly an exact reservation passes and one byte less refuses; the parent array has the parent key's Arrow type; a parent whose only child reference column has a declared cast reserves no array | no reservation today | S2 |
| AT-8b | Size helpers (MEDIUM-3): `arrow_allocated_bytes(t, r, w, validity) >= arrow_column_bytes(t, r, w)` over the section 5.4 grid. Parametrize retained-byte measurements over all four text types on that grid (no nulls, validity False). For one empty value (`[""]` or `[b""]`), measure the actual offsets buffer (8 bytes for standard, 16 for large) and require the helper to equal the measured 64-byte retained allocation. At 4096 empty values require the helper to cover the measured allocator delta for each type, where rounding cannot hide the offset width. Across the same row/payload grid assert `faker_pool_resident_parts(n, p).arrow_peak >= 2 * (n * (p + 4) + n // 8 + 1)` against #813 and spy on its explicit `validity=True` argument; `faker_pool_resident_parts` and `reference_array_parts` call `_arrow_types.arrow_allocated_bytes` (spy), and `generation/pool/_resident.py` defines no function whose name matches `arrow*bytes` | no helper today | S2 |
| AT-10 | E10 at the seal seam, with `_arrow_types._OFFSET_LIMIT` set to 100 bytes by `monkeypatch` (the seam the O3 text-width tests already use; `reference_array_parts` reads it as a module attribute at call time, never through `from ... import`): (a) a string parent of ten 36-byte keys gives `reference_array_parts(...) is None`, no copy is admitted, `SealedKeys.array is None`, no `parent_key_array` event, and the child's values equal the golden through the list path; (b) with the seam `_table_stage._build_key_array` returning a two-chunk `pa.ChunkedArray`, seal sets `SealedKeys.array = None`, both charges are released before the parent's first batch (ledger events), and the child equals the golden; (c) a `large_string` parent with the same keys keeps its copy (64-bit offsets, E10 does not apply) | no copy today | S2 |
| AT-9 | E3: a sequence whose last planned value passes int64 uses the list path and equals the golden | passes before (control, through `next_batch`) | S1 |
| AT-9b | E8: a text sequence with prefix `"S"`, `rows = 2`, `start = 2**63 - 2`, `step = 1` (both planned values fit int64): `next_array(0, 4)` returns `["S9223372036854775806", "S9223372036854775807", "S9223372036854775808", "S9223372036854775809"]` decoded, equal to `next_batch(0, 4)`, and a spy shows the list path | fails before (no `next_array`) | S1 |

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
| M10 | `column_reads_array` checks collectors in the column's own table only, or `collected` holds FK targets only | AT-3 three-table chain (`C` gets an empty pool or A reserves an unused copy) and the `anchor_via` integration cell (child dates wrong) |
| M11 | sequence `next_array` drops the `offset + size <= rows` check | AT-9b |
| M12 | sequence numeric form uses int64 `np.arange(...) * step + start` instead of `int_from_index` | AT-1 overflow cells |
| M13 | the replay writes numpy `uint32` words back to `setstate`, or the probe lets an adapter exception escape | AT-5 adapter cells (1) and (2) |
| M14a | the preflight leaves out the replay population (admits replay always) | AT-6 cell (a): replay allocation under a fallback-only ceiling, or a live refusal |
| M14b | the live stage builds replay buffers without the reservation | AT-6 cell (b): no reservation event before allocation |
| M14c | preflight sums weighted scratch across the table's columns | AT-6 cell (d) refuses before either golden value is produced |
| M15 | the categorical or reference array path gathers with a direct `pc.take` instead of `pool_take` | AT-3 `pool_take` spy cell |
| M16 | the preflight adds the parent-key copy to both run peaks unconditionally (copy made mandatory) | AT-8 floor cell (today's floor refuses) |
| M16a | recompute `stream_it` after admission | AT-8 mode cell (decision count, mode and reason) |
| M16b | omit the conversions from the preflight stage maximum or add them together | AT-8 seal-event and preflight cell |
| M16s | a seeded `ledger.reserve(f"scratch_copy:{t}", n)` in `generation/` with no registry entry | the optional-reservation sentry |
| M16r | move a prefix set into the sentry and remove its ledger definition | reservation sentry imports both ledger sets |
| M17 | E10 removed: no projected-payload check, or a chunked copy kept | AT-10 (a) or (b): a copy is admitted, or `RecordBatch.from_arrays` fails |
| M18 | reference `weighted` with no `weights` routed to `replay_randbelow` | AT-1 `weighted` with no `weights` cell |
| M19 | `prepare_population` called per batch instead of once per stream | AT-6 call-count cell |
| M20 | `arrow_allocated_bytes` drops the extra offset or the allocation rounding | AT-8b 4096-empty-values cell for the terminal offset and exact one-row cell for rounding |
| M20a | price the Faker build with `validity=False` | AT-8b Faker floor and call spy |
| M20b | price `large_*` with 4-byte offsets | AT-8b four-type measurement at 4096 empty values |

## 10. Frozen contracts

- Generated output is deterministic per seed and frozen at release. This row keeps every byte; the changelog fragment `changelog.d/gen-vector-streams-s<n>.md` says so with no `Breaking:` line. The S2 fragment also carries this line: "Some jobs with a large weighted categorical or weighted reference column now refuse at a memory ceiling they passed before. The preflight now counts the temporary cumulative-weights list that the draw has always built; output bytes do not change." (guarantee 8). Mention the bounded allocation-rounding increase for pooled Faker in the same fragment.
- Supported Pythons: 3.10 to 3.12 (`pyproject.toml:13`). A future CPython that changes `random` makes AT-5 fail on that leg, and E2 keeps the output right on that interpreter.
- GSA S2's single categorical draw (`weighted_draw`, AT-S2-10) stays the one draw definition; the replay is its exact twin, listed in the same guard.

## 11. Pre-mortem

- CPython changes `_randbelow` or `choices` in a version the engine later adds. AT-5 on that leg fails first; E2 keeps the output equal.
- numpy changes the `MT19937.state` layout. AT-5 fails; E2 again.
- The replay's state write-back costs more than it saves for tiny batches. `getstate` and `setstate` are about 10 microseconds per call; at batch 1 that is slower than CPython but equal in bytes. The streamed layout uses batches of thousands of rows, so AT-4 measures the real case.
- A reference column with a declared cast keeps the list path. That is today's cost, not a regression.
- The parent Arrow copy doubles parent key memory for a very large parent. It is priced and admitted only when it fits; otherwise the children take the list path (E11, AT-8), never an OOM and never a new refusal.
- A string parent key column over 2 GiB of payload (about 60M UUID keys) would make pyarrow return a chunked array that the assembler cannot use. E10 keeps the copy off for it (AT-10).
- #813 or GSA S2 changes shape in review. This row re-anchors to the merged `stream/_batches.py` and `_categorical.py`; the stream bodies do not change.
- GEN-PER-COLUMN later serves a held column through a resident stream and runs the assembler in DAG order. It keeps `array_columns` as the list rule, so the streams here need no change (section 12).

## 12. Slices

| Slice | Content | Size | Gate | Test depth |
|---|---|---|---|---|
| S1 NO-RNG-ARRAYS | `next_array` and `supports_array` on sequence (with E3, E8 and `int_from_index`), constant and distribution; AT-1, AT-2, AT-3, AT-9, AT-9b for those streams; M2, M5 (S1 form), M11, M12 | S: about 60 lines code, 200 lines tests | Codex | T0 per edit; T1 impact selection (generation unit, parity, `tests/generation`) per commit; T2 on the exact head with AT-1 and the mutations. No full suite: no escalation trigger |
| S2 MT-REPLAY | `_mt_replay.py`, `weighted_indices`, `next_array` on categorical and reference, the two moves (section 6), `column_reads_array`, `SealedKeys`, `seal_parent_keys`, the parent-array charge, `draw_forms` and the replay population charge, the AT-S2-10 guard entries, `arrow_allocated_bytes`, E10 and E11, the optional-reservation sentry, the `mt_replay` CI job; AT-1 to AT-8, AT-8b and AT-10 for those streams; M1, M3, M4, M5 (S2 form), M6 to M10, M13, M14a, M14b, M14c, M15 through M20b, including lettered variants | M: about 250 lines code, 430 lines tests | Codex and Dennis (R2) | T0, T1 as S1; T2 on the exact head with AT-5 in the new `mt_replay` CI job on three Pythons, AT-8, AT-10 and the mutations; AT-4 on the Dell. The CI job is a test-tooling change, an escalation trigger, so one full suite runs on the S2 head against the saved main baseline. A golden outside AT-1 moving is a stop |

Order and dependencies:

1. #813 (GSA S1a) merges. S1 here can start that day, in parallel with GSA S1b. Both touch `_column_streams.py` in different classes; the second to merge rebases.
2. GSA S1b and S2 merge in their own order. S2 here starts after GSA S2, because it extends `weighted_draw`'s module and the AT-S2-10 guard.
3. S2 here can build in parallel with GSA S3. Both may touch the `_streamed.py` preflight; the second to merge rebases and recounts its size.
4. GEN-PER-COLUMN (plan on `origin/plan/gen-per-column`) starts after GSA S3 and does not need this row. Its S1 replaces `sibling_read_names` with `TableColumnPlan.batch_reads` and its route; whichever lands second points `column_reads_array` at them. Its S2 and this S2 both create `stream/_table_stage.py` by the same move; whichever lands second builds on it, and both use `seal_parent_keys`. `array_columns` stays the one list rule in both plans.
5. Follow-up, not in this row: GSA's `LookupStream` can call `weighted_indices` for an array path; it is the same helper and needs no new design.

Both slices fit before 2026-12-15.

## 13. Open questions for the owner

None. Q1 of revision 1 (reproduce CPython bytes rather than switch to numpy draws) was answered on 2026-11-22: reproduce.

## 14. Fix round 1 (Dennis plan review, 2026-11-26)

Verdict GO-WITH-FIXES: 0 BLOCKER, 2 HIGH, 4 MEDIUM, 6 LOW. All fixes are plan text; the design and the byte-identity replay are unchanged.

| Finding | Where the plan answers it |
|---|---|
| HIGH-1: the parent-key copy was mandatory and could refuse jobs that run today | guarantee 7; E11; section 5.3 (one `draw_forms` greedy admission for copies and populations); section 5.4 "Admission"; AT-8 floor cell reworded; M16; sentry "no new required reservation without a fallback" (section 7.2 row 11, defect class 2b, M16s) |
| HIGH-2: string parent keys over 2 GiB give a chunked array | E10; `reference_array_parts` returns `None` (section 5.4); AT-10; M17; pre-mortem |
| MEDIUM-1: reference `weighted` with no `weights` | section 5.3 callers (the unweighted `choices` form through `replay_choices`, never `replay_randbelow`); AT-1 cell; M18 |
| MEDIUM-2: no owner for the cumulative weights | `ReplayPopulation` and `prepare_population` (section 5.3), built once per stream after the reservation, E6 checked once; AT-6 call-count cell; M19 |
| MEDIUM-3: a second Arrow-size helper | `arrow_allocated_bytes` in `_arrow_types.py` beside `arrow_column_bytes`, with the reason they differ (section 5.4); placement table; AT-8b guard; M20 |
| MEDIUM-4 (V2-LOG): the refusal floor rises | guarantee 8 (owner of the charge named); changelog line in section 10 |
| LOW-1: anchors | header and anchor paragraph re-read at #813 `308cef4a3` and main `0952fbae2`; stream bodies in `_column_streams.py` start three lines earlier; `synthesize.py:413`; `_cardinality.py:143` and `:167-172` |
| LOW-2: array type sources | section 5.1 (constant) and section 5.3 callers (`_cats_array`) |
| LOW-3: `SequenceStream` with `rows=None` | section 5.2; AT-3 |
| LOW-4: `replay_randbelow` in AT-S2-10 | section 7.2 rows 5 and 10 |
| LOW-5: placement of `_mt_replay.py` | section 6, note under the placement table |
| LOW-6: Parquet `created_by` in goldens | AT-1 |

## 15. Fix round 2

| Finding | Where the plan answers it |
|---|---|
| MEDIUM-A (V1, DESIGN) | Guarantee 7 and sections 5.3–5.4 pin the mode before admission. AT-8 mode cell, M16a. |
| MEDIUM-B (V1, DESIGN) | Section 5.4 defines the stage maximum above retained key pools. AT-8 seal-event cell, M16b. |
| MEDIUM-C (V1) | Guarantee 8 and section 5.4 price validity during the Faker build. AT-8b Faker floor and spy, M20a. |
| MEDIUM-D (V1) | Section 5.4 derives offset width from type. AT-8 measures large_string keys. AT-8b measures all four text types, M20b. |
| LOW-1 (V2-LOG, DESIGN) | Sections 6 and 7.2 place both prefix sets beside the ledger. Reservation sentry, M16r and M16s. |
| LOW-2 (V2-LOG) | Deferred. A replay population may be reserved and unused after E6 fallback. |
| LOW-3 (V2-LOG) | Header and round 1 anchor row agree. Compare stream-body anchors at `f329ccd46` and `308cef4a3`; reversing the direction fails that check. |
