Status: plan (revision 1, 2026-11-22)

# GEN-VECTOR-STREAMS: sequence, categorical, constant, distribution and reference streams return Arrow arrays built with numpy, with the same bytes

Owner: Cam. Author: Opus (plan author). Date: 2026-11-22. Roadmap row: GEN-VECTOR-STREAMS (CLI `docs/roadmap/groups/generate.md:31`, 1.0.x): "sequence, reference and null-mask streams ... Output bytes must not change; if they do, back to owner." V1 fast-path audit (vault `10_Projects/decoy/v1-fast-path-audit-2026-11-22.md`, lines 155-156 and 218). Engine only.

Builds on GEN-STREAM-ALL (`plan/gen-stream-all`, `docs/plans/2026-11-22-gen-stream-all.md`): its S1a moves `_table_batches` into the new package `generation/stream/` (`_batches.py`), makes it accept a `pa.Array` from a stream, applies the null mask with `pc.if_else`, and adds `pool_take`. This row starts after GEN-STREAM-ALL S1a merges and changes no part of S1b to S4.

Not combined with GEN-NONFAKER-DRAWS (`plan/gen-nonfaker-draws`). That row also emits Arrow arrays from generation streams, but its mechanism is different (keyed draws for four Faker providers, shared with the mask side), it changes bytes, and its risk is higher. This row changes no bytes. The two share only the Arrow stream protocol that S1 here adds, and GEN-NONFAKER-DRAWS depends on it.

Anchors: a path with no prefix is under `src/decoy_engine/` in decoy-engine. Read at engine `origin/main` `70881ad79` (0.28.3). Line numbers are at that head.

Rules consulted: dev-rules `README.md`, `00-universal.md`, `risk-and-exceptions.md`, `development-loop.md` (PLAN), `feature-dev.md`, `reuse-first.md`, `scope-discipline.md`, `proportionality.md`, `testing.md` (test depth), `architecture.md`, `cross-cutting-concerns.md`, `performance.md`, `api-and-compatibility.md`, `documentation.md`, `workspace-and-vcs.md`, `catalogs/recurring-defects.md`; engine `CLAUDE.md` and `CODEMAP.md` ("Where things go").

Risk: R1 by effect (byte-identical, generation only, no keyed material), raised to R2 because it depends on CPython `random` internals for byte identity (section 5.2) and touches the frozen generation output. Plan review: Dennis, then Codex. Code gate: Codex.

Owner direction (2026-11-22): faster wins even when bytes change, if each change is named. This row needs no byte change: the probe in section 1 reproduces CPython's draws bit for bit with numpy. That also keeps the roadmap row's own rule.

## 1. Frame

The streams live in `generation/_column_streams.py` (381 lines). Each returns a Python list per batch (`ColumnStream.next_batch`, `:57`); `_table_batches` (`generation/_streamed.py:284`) then runs `pa.array(values)` per column per batch.

| Stream | Today | Cost |
|---|---|---|
| `SequenceStream` (`:125`) | Python loop; `str(value).zfill(pad)`, prefix and suffix per row | per-row Python format |
| `CategoricalStream` (`:144`) | `random.Random(base_int("py")).choices(cats, weights, k=size)` | C loop for unweighted (67 ns/row on the Dell); per-item `bisect` in Python for weighted |
| `ReferenceStream` (`:204`) | per-row Python: `rng.choice(vals)`, or `rng.choices(vals, weights, k=1)[0]`, or `vals[i % len]` | 468 ns/row for `choice` (Dell) |
| `NullMaskedStream` (`:241`) | numpy mask, then a Python loop setting `None` | small |
| `ConstantStream` (`generation/kinds/_constant.py`) | `[value] * size` | small |
| `ParametricStream` (`generation/kinds/_parametric.py`) | `default_rng(base_int("dist")).uniform(size)`, clip, `.tolist()` | `.tolist()` then `pa.array` |

The audit ranks sequence, categorical, constant and distribution as under the noise floor and reference as the slow one. The common cost for all of them is the list: `pa.array` over Python objects is about 34 ns/row (GEN-STREAM-ALL section 1), on top of each stream's own loop.

Probe (Dell, Python 3.10, numpy from the engine lock, 1,000,000 draws per case): an `np.random.MT19937` bit generator loaded with the exact state of `random.Random(seed)` reproduces CPython's output bit for bit.

| Case | Equal to CPython | numpy replay | CPython |
|---|---|---|---|
| `choices(cats, k)`, unweighted | yes, over batch sizes 1, 7, 4096, 65536, 3 | 248 ns/row (first cut, including the float build) | 67 ns/row |
| `choices(cats, weights, k)` | yes, including zero weights | not timed | per-item bisect |
| `choice(vals)` over 100,003 keys | yes, same batch sizes | 20.6 ns/row | 468 ns/row |

So reference gets 20x with no byte change. Unweighted categorical is already fast in CPython; the replay only pays if it skips the list. S1 measures the end-to-end batch (stream plus Arrow build) and keeps whichever is faster per case. The measurement decides; the bytes are the same either way.

## 2. Established solutions

Search run: reproducing CPython `random` with numpy (`numpy.random.MT19937` state, `random.getstate` layout), vectorized weighted choice (`numpy.searchsorted` over cumulative weights, the method `random.choices` itself uses with `bisect`), Arrow string building (`pyarrow.compute` `binary_join_element_wise`, `utf8_lpad`).

- CPython's `random.Random` is MT19937. `getstate()` returns 624 32-bit words and a position; numpy's `MT19937.state` takes the same key and position. `random()` is `(a >> 5) * 67108864 + (b >> 6)` over two 32-bit words, divided by 2**53 (CPython `_randommodule.c` `random_random`). `_randbelow(n)` is `getrandbits(n.bit_length())` with rejection (CPython `random.py`). `choices` without weights is `population[floor(random() * n)]`; with weights it is `bisect(cum_weights, random() * total)`. All of these hold for CPython 3.10 to 3.12, the engine's `requires-python` range (`pyproject.toml:13`, `>=3.10,<3.13`). The probe confirms them.
- `numpy.searchsorted(cum, u * total, side="right")` is the vector form of `bisect.bisect_right`, the exact call `random.choices` makes.
- Python's `str.zfill` keeps a leading sign; Arrow `utf8_lpad` does not. The sequence formatter pads the absolute value and adds the sign back (section 5.3).

### Reuse inventory

- GEN-STREAM-ALL S1a: `generation/stream/_batches.py` (Arrow path, `pc.if_else` null mask) and `pool_take`.
- `GenDeriveContext.base_int("py")`, `base_int("np")`, `base_int("dist")`: the seed roots stay the same.
- `sequence_affixes` (`generation/_numeric_typing.py:61`): the one reading of prefix and suffix.
- `check_reference_pool` (`generation/_column_streams.py:218`): still runs once per stream.
- `KeyPool` (`:101`): insertion order unchanged; it gains an Arrow `add`.

## 3. Guarantee and non-goals

After this row:

1. `SequenceStream`, `CategoricalStream`, `ReferenceStream`, `ConstantStream`, `ParametricStream` and `NullMaskedStream` return a `pa.Array` per batch through one new stream method, `next_array(offset, size)`. Each output is byte-identical to today's list output, type included, for every config those streams accept today.
2. Output does not depend on how rows are split into batches (today's route-independence property), on every supported Python version.
3. No Python list is built for these columns unless a sibling (`windowed_date`), a `KeyPool` collector or a declared cast needs the values. Then the list is built from the array once.
4. Whole-table generators (`synthesize.py`, `kinds/_lookup.py`, `window.py`) are unchanged and keep producing the same bytes, because the streams keep the same draws.
5. On a Python where the replay does not match (a future CPython), the stream falls back to today's CPython draw. The check is a fixed self-test at import, not a guess (section 5.2).

Non-goals: per-row Faker streams (GEN-NONFAKER-DRAWS); pooled Faker selection (GEN-STREAM-ALL); `windowed_date`; distribution families other than `uniform` (there are none today); a Rust generation kernel (the engine record `docs/records/2026-11-19-engine-speed-and-route-completeness.md` section 2.3 found Rust selection slower than numpy).

## 4. Enumerations

### Exit paths

| # | Condition | Result |
|---|---|---|
| E1 | replay self-test passes at import | numpy replay for `choice`, `choices` |
| E2 | replay self-test fails | CPython draw, list, then `pa.array`; bytes still equal; a debug record names the fallback once per process |
| E3 | sequence bound outside int64 for the planned row count | today's Python loop (`generation/_column_streams.py:133-142`), decided once per stream from `rows` with the bound helper `generation/_numeric_typing.py:74` `_fits` |
| E4 | empty reference pool | `pa.nulls(size, type)`, as today's `[None] * size` (`generation/_column_streams.py:228-229`) |
| E5 | `size == 0` | empty array of the column type |
| E6 | weights length differs from values | today's `ValueError` from `random.choices`, raised at stream construction with the same text |
| E7 | negative or zero weights total | today's `ValueError`, same text |

### Routes

| Route | Change |
|---|---|
| streamed, resident (`sink=None`) | streams return arrays; today they feed `generation/_streamed.py:304` `draw_batch` |
| streamed, with a sink | same |
| `_run_legacy` (`generation/_streamed.py:543`) and whole-table kinds | none |

### Codes

No new reason codes. The fallback in E2 is a debug record, not a warning: it changes no output.

### FK shapes

- `reference` to a parent table: the parent key list (`key_pools`) is read in insertion order, unchanged. The replay indexes the same list.
- A column that is a reference target (a key column): `KeyPool.add` takes the array and keeps order. A12 in GEN-STREAM-ALL covers the key opt-out; this row adds AT-6 for order.

### Fields

| Stream | Fields | Notes |
|---|---|---|
| sequence | `start`, `step`, `prefix`, `suffix`, `pad_length`, numeric form | sign-aware pad |
| categorical | `categories`, `weights` | weighted and unweighted |
| reference | `distribution` (`random`, `weighted`, `sequential`), `weights` | all three |
| constant | `value` | any scalar, including None |
| distribution | `family: uniform`, `low`, `high`, `min`, `max` | clip after draw, as today |
| null mask | `null_probability` | same `default_rng(base_int("np"))` draw |

### Output surfaces

| Surface | Change |
|---|---|
| generated tables | none (byte-identical) |
| `quality_metrics["generation_route"]` (GEN-STREAM-ALL S4) | none |
| debug log | one record per process if E2 |
| `docs/` | generation performance note in the existing route doc |

## 5. Design notes

Principles that apply: one place per fact (one replay helper; seed roots unchanged); open/closed on streams (a stream opts in by adding `next_array`; `_batches.py` does not switch on stream type). Established pattern: CPython's own algorithms, reproduced (section 2).

### 5.1 Stream protocol

`ColumnStream` keeps `next_batch(offset, size) -> list`. An optional `next_array(offset, size, type) -> pa.Array` is added. `generation/stream/_batches.py` calls `next_array` when the stream has it and `next_batch` otherwise. `NullMaskedStream.next_array` wraps the inner stream's array with the GEN-STREAM-ALL `pc.if_else` mask. A list is built from the array only when `emitted` siblings, a collector or a declared cast needs it, and only once.

### 5.2 Replay helper

`generation/stream/_mt_replay.py`, one class `MtReplay(seed_int)`:

- `random(n) -> float64 array`, `below(n_choices, size) -> int64 array`, `choice_indices(n, size)`, `weighted_indices(cum_weights, size)`.
- The state comes from `random.Random(seed_int).getstate()` and loads into `np.random.MT19937`. The stream holds one `MtReplay` for its life, so state carries across batches as the CPython generator does.
- `below` keeps CPython's rejection exactly: draw `k`-bit words, keep those under `n`, in order. Rejected words are consumed, as in CPython.
- Import-time self-test: fixed seeds and sizes compared with `random.Random`; any mismatch sets the module to E2. The test takes under 1 ms.

`CategoricalStream` and `ReferenceStream` use it. `ReferenceStream` `sequential` uses `np.arange(offset, offset + size) % len(vals)` and needs no RNG. The values are taken with `pool_take` over the parent list held once as a `pa.Array`.

### 5.3 Sequence

`np.arange(offset, offset + size, dtype=int64) * step + start` with an int64 bound check at construction (E3). Numeric form returns the int64 array. Text form: `pc.cast` to string, sign-aware pad (pad `abs`, then join `"-"` for negatives, matching `str.zfill`), then `binary_join_element_wise(prefix, body, suffix)`.

### 5.4 Constant and distribution

Constant: `pa.repeat(value, size)` cast to the column type, or `pa.nulls`. Distribution: the same `default_rng` draw and clip; the numpy array goes straight to `pa.array` without `.tolist()`. float64 values are the same objects, so the bytes match.

## 6. Placement

| What | Where | CODEMAP line | Beside |
|---|---|---|---|
| `MtReplay` | `generation/stream/_mt_replay.py` (new, about 90 lines) | GEN-STREAM-ALL's new row "Generation streamed batch assembly", `generation/stream/_<noun>.py` | `generation/stream/_batches.py` |
| `next_array` on five streams | `generation/_column_streams.py` (381 lines, about +70); `generation/kinds/_constant.py`, `generation/kinds/_parametric.py` (about +10 each) | "Generation" | no new top-level module; `generation/` stays at 25 |
| `_batches.py` dispatch | `generation/stream/_batches.py` (about +20) | same new row | - |
| tests | `tests/unit/generation/stream/test_mt_replay.py`, `test_vector_streams.py` | GEN-STREAM-ALL's `tests/unit/generation/stream/` | - |

If `_column_streams.py` passes 600 lines, the five `next_array` bodies move to `generation/stream/_vector.py` and the streams call them; S1 picks one at build time and lists the line counts.

## 7. Defect classes

### 7.1 Plan-contract classes

| # | Class | Where it applies | Structure that closes it | Proof | Mutation that must turn it red |
|---|---|---|---|---|---|
| 1 | Value-bearing output | the E2 debug record | it names the stream kind and Python version, never a value | AT-7 | log the first drawn value (AT-7 red) |
| 2 | Cleanup missing on an exit path | none | N/A: no resource is held; budget reservations are unchanged | n/a | n/a |
| 3 | State and concurrency | RNG state across batches | one `MtReplay` per stream, advanced in batch order; streams are not shared across threads | AT-2 | create a new `MtReplay` per batch (AT-2 red) |
| 4 | Route parity and silent fallback | streamed vs whole-table paths; E2 | same draws as the whole-table generators; E2 is byte-equal and recorded | AT-1, AT-5 | M1 |
| 5 | Referential integrity | reference columns | same parent list, same order, same indices | AT-1 reference cells, AT-6 | M3 |
| 6 | Untrusted producer | none | N/A: inputs are the compiled config and the engine's own RNG | n/a | n/a |
| 7 | Check then use | none | N/A: no file or path | n/a | n/a |
| 8 | Weak tests | AT-1 passes before | AT-3 (no list built) and AT-4 (speed) carry the fail-before | AT-3, AT-4 | M4 |
| 9 | Refactor drift | stream outputs | golden outputs captured at the GEN-STREAM-ALL S1a head | AT-1 | M2 |
| 10 | Frozen contract drift | generation output determinism | byte-identical; CHANGELOG states it | AT-1 | M1 |

### 7.2 Recurring-defect catalog (dev-rules)

| # | Class | Applies | Guard |
|---|---|---|---|
| 1 | Anchored validation | no | - |
| 2 | Strict wire and stored types | no new persisted model | - |
| 3 | No exception context | E6 and E7 errors keep today's text; no new raise | existing tests |
| 4 | Versioned read models | no | - |
| 5 | Normalized guard scanners | no | - |
| 6 | No reaching into private modules | `generation/stream/` and `generation/` are one package tree | import-linter |
| 7 | No hidden CI failures | AT-5 runs on every Python leg of the matrix with `fail-fast: false` | CI review |
| 8 | One input, one trust class | no | - |
| 9 | Mutations on the final head | yes | M1 to M5 on the final head, head recorded |
| 10 | Allowlisted helpers are still checked | no allowlist touched | - |
| 11 | No raised caps | `generation/` fan-out 25, module size | new module goes in `generation/stream/`; sizes listed |

## 8. Acceptance tests

| ID | Test | Fail-before | Slice |
|---|---|---|---|
| AT-1 | Golden parity: for each stream and each field form in section 4 (negative start, pad, prefix and suffix, `0` and `false` affixes, weighted with a zero weight, reference `random`, `weighted`, `sequential`, empty pool, constant None, uniform with clip, null probability 0, 0.3, 1), generated tables at 1, 7 and 120,000 rows equal goldens captured before the change, schema included | passes before (guard); fail-before is AT-3 | S1 |
| AT-2 | Partition invariance: batch layouts `[1]*7`, `[7, 4096, 3]`, `[65536]` and one batch give equal tables | passes before; guards state carry | S1 |
| AT-3 | Instrumented: for sequence, reference, constant and distribution columns with no sibling, collector or cast, no Python list of the column is built (spy on `next_batch` and `pa.array` over a list) | lists today | S1 |
| AT-4 | Speed, `perf`, Dell: a 10,000,000-row table with one reference column over 100,000 parent keys at or under 60 ns per row for the column (468 ns today) | 468 ns today | S1 |
| AT-5 | Replay self-test: `MtReplay` equals `random.Random` for `random`, `_randbelow`, `choice`, `choices` with and without weights, on every CI Python leg; a patched CPython draw (monkeypatched `random.Random.random`) makes the import self-test choose E2 and output still equals the goldens | no `MtReplay` today | S1 |
| AT-6 | Key order: a reference-target column collected through `KeyPool.add(array)` gives the same key list, same order, as the list path | no array path today | S1 |
| AT-7 | E2 record names only the stream kind and Python version | no record today | S1 |

## 9. Named mutations

| ID | Mutation | Must turn red |
|---|---|---|
| M1 | `random(n)` uses `b >> 5` instead of `b >> 6` | AT-1, AT-5 |
| M2 | Sequence pad pads the signed string (`utf8_lpad` on `"-5"`) | AT-1 (negative start cell) |
| M3 | `below` drops rejected words without consuming them | AT-1, AT-5 |
| M4 | `_batches.py` always calls `next_batch` | AT-3 |
| M5 | `searchsorted` with `side="left"` | AT-1 (weighted cells) |

## 10. Frozen contracts

- Generated output is deterministic per seed and frozen at release. This row keeps every byte.
- Supported Pythons: 3.10 to 3.12 (`pyproject.toml:13`). A future CPython that changes `random` makes AT-5 fail on that leg and E2 keeps the output right; it does not change bytes silently.

## 11. Pre-mortem

- CPython changes `_randbelow` or `choices` in a version the engine later adds. AT-5 on that leg fails first, and E2 keeps output equal.
- numpy changes `MT19937.state` layout. AT-5 fails; E2 again.
- The categorical replay is slower than CPython end to end. S1 keeps CPython for that case and still returns an array (`pa.array` over the `choices` list is the same as today), as the measurement in section 1 allows.
- A declared cast on a reference column forces the list path. That is today's cost, not a regression.
- GEN-STREAM-ALL S1a changes shape in review. This row then re-anchors to its merged `_batches.py`; the stream side does not change.

## 12. Slices

| Slice | Content | Size | Gate |
|---|---|---|---|
| S1 | `MtReplay` with self-test; `next_array` on the six streams; `_batches.py` dispatch; `KeyPool.add(array)`; AT-1 to AT-7 | M: about 220 lines, 300 lines tests | Codex (Dennis if the plan review raises it to R2 for code); T2 on the generation selection; AT-5 on every Python leg |

One slice. It can start the day GEN-STREAM-ALL S1a merges and fits before 2026-12-15.

## 13. Open questions for the owner

- Q1: Accept reproducing CPython `random` in numpy (byte-identical, with the self-test fallback) over switching these streams to numpy `default_rng` draws (simpler, faster for categorical, but every categorical and reference output changes)? Recommended: reproduce, so the row needs no `Breaking:` line.
