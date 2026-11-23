Status: plan (revision 1, 2026-11-22)

# JOINT-MASK-VECTOR: pick `joint_mask` reference rows by index arrays, not row dicts

Owner: Cam. Author: Opus (plan author). Date: 2026-11-22. Roadmap row: JOINT-MASK-VECTOR (V1 engine, approved 2026-11-22: vectorize inside the handler, measure first), from the fast-path exceptions study (vault `10_Projects/decoy/fastpath-exceptions-study-2026-11-22.md`, section 3). Output must be identical, so Python `hmac` stays.

Anchors: paths are in this repository (decoy-engine), read at `origin/main` `70881ad79`. Line numbers are at that head.

Rules consulted: dev-rules `README.md`, `00-universal.md`, `risk-and-exceptions.md`, `development-loop.md` (PLAN, choke point, placement), `profiles/local-operations.md`, `performance.md`, `refactoring.md`, `cross-cutting-concerns.md`, `reuse-first.md`, `scope-discipline.md`, `testing.md`, `security.md`, `catalogs/recurring-defects.md`; engine `CLAUDE.md`, `CODEMAP.md`, `docs/determinism.md`.

Risk: R2. The keyed path runs an HMAC under a key derived from the mask key, and the change touches key handling (`OpaqueBox`, `del job_seed`). Output bytes do not change. Plan review: Dennis, then Codex. Code gate: Codex and Dennis.

## 1. Frame

`apply_joint_mask` (`transforms/joint_mask.py:276-332`) builds one dict per row and then one list per target column:

- Mask mode, `_pick_rows_mask` (`:335-397`), per row:
  - A null key (`val is None` or a float NaN) takes `tbl.row(int(rng.integers(0, row_count)))`.
  - Any other key takes `tbl.keyed_row(str(val), hmac_key=...)`, which runs `hmac_hex` and then `int(hex[:8], 16) % row_count` (`reference_tables/_types.py:87-125`).
- Gen mode, `_pick_rows_gen` (`:400-428`): one bulk `rng.integers(..., size=n)`, then `tbl.row(idx)` per row.
- `ReferenceTable.row` (`reference_tables/_types.py:68-85`) converts one Arrow scalar per column with `.as_py()`. Every row pays this cost.
- The output is `result[col] = [r.get(col) for r in rows]` (`transforms/joint_mask.py:327-328`).

**Measurement (S0, done for this plan; Dell VM, 2026-11-22, 200,000 rows, `us_zip5_city_state`, 3 target columns, 5% null keys):**

| Keys | Today | HMAC alone (per row) | Vectorized build | Identical |
|---|---|---|---|---|
| all distinct | 0.93 s | 0.15 s | 0.25 s | yes |
| 1,000 distinct | 0.94 s | 0.14 s | 0.15 s | yes |

The vectorized build does a per-row null check and `str()`, `pandas.factorize` on the key strings, `hmac_hex` once per distinct string, a gather of indices, one bulk null-fallback draw, and `take(...).to_pylist()` per target column. About 80% of today's time is the row dicts, not the HMAC. A bulk `integers(size=k)` equals `k` scalar draws for every range class (probe in the GROUPED-SERIES-VECTOR plan, ranges up to `2**62`), so the null-fallback stream is unchanged.

## 2. Established solutions

- **Dictionary encode, compute once per distinct value, then gather** (`pandas.factorize`, Arrow `dictionary_encode`): the standard way to apply a costly pure function to a column with repeats.
- **Columnar gather** (`pyarrow.ChunkedArray.take`, Arrow compute "Selections"): the reference table is already a `pa.Table`, so each target column is one `take` and one `to_pylist`. `to_pylist` and `Scalar.as_py` share one conversion, so the values are the same Python objects.
- **HMAC-SHA256** (RFC 2104) through the existing `internal.crypto.hmac_hex`: unchanged. The native index kernel uses a different construction and would change bytes, so it is not used.

### Reuse inventory

- `reference_tables/_types.py` `ReferenceTable`: `row`, `keyed_row`, `row_count`, `column_names`, `_table`. The index rule `int(hex[:8], 16) % row_count` moves into one method that `keyed_row` also calls.
- `internal/crypto.hmac_hex`: the one HMAC.
- `transforms/joint_mask.py`: `apply_joint_mask`, `_pick_rows_mask`, `_pick_rows_gen`, `_stream_source`, `_KEYED_ROW_SOURCE`, `_NULL_FALLBACK_LABEL`, `_GEN_ROW_LABEL`, `OpaqueBox` use, the `del job_seed` hygiene.
- `execution/_strategies/_joint_mask.py:119` handler and the `key_series` snapshot: unchanged callers.
- Draw-site entries `mask.joint_mask_null_fallback`, `mask.joint_mask_keyed_row` and gen (`execution/native/_draw_sites_mask.py:228-260`): text only, if a call shape changes.

## 3. Guarantee and non-goals

1. Output (values, Python types, row choice per key, the null-fallback sequence) is identical to `70881ad79` in mask and gen modes, with and without `key_series`.
2. The null test is unchanged: `None` or a float NaN is null. `pd.NA`, `NaT` and every other value are keyed by `str(val)`, as today.
3. HMAC runs once per distinct key string, under the same derived key, through `hmac_hex`.
4. At 200,000 rows: at least 3 times faster with all-distinct keys and at least 5 times faster with 1,000 distinct keys (Dell).

Non-goals: the chunked lane (multi-column output and the source-key snapshot, about 2 more slices, 1.0.x); the native index kernel; any change to the null rule, the reference tables or `key_by` handling.

## 4. Enumerations

### Exit paths

- `ValueError` for an empty table name (`transforms/joint_mask.py:311-312`) and for an unknown mode (`:322-323`): unchanged.
- `hmac_hex` returning `None` for a non-None key raises `ValueError` (`reference_tables/_types.py:118-120`): kept in the shared index method.
- Every exception path keeps `del job_seed` (`transforms/joint_mask.py:330-332`, `:394-397`, `:426-428`) and `del hmac_key` (`reference_tables/_types.py:123-125`).
- Plan-time refusals (`joint_mask_columns_missing`, `joint_mask_column_not_in_reference`, and the rest at `transforms/joint_mask.py:175-246`): unchanged.

### Routes and codes

- Mask: the full-frame route, as today. `joint_mask` keeps its capability row (`execution/native/_capabilities.py:384`) and its multi-column runner path (`execution/_runner.py:286`).
- No reason code added or changed.

### FK shapes

- `key_by` reads a pre-mask snapshot through `key_series` (cross-column V1) or the live frame. Both are read the same way as today.
- N/A beyond that: the output columns are reference values, not keys, and `joint_mask` is not join-safe.

### Fields

- `JointMaskConfig` (`columns`, `reference`, `key_by`, `table`): unchanged.
- `ReferenceTable` gains two methods: `keyed_indices(keys: Sequence[str], *, hmac_key: bytes) -> np.ndarray` and `take_columns(indices: np.ndarray, columns: Sequence[str]) -> dict[str, list[Any]]`.

### Output surfaces

- The target columns: identical.
- Draw-site text for `mask.joint_mask_null_fallback`: "one draw per null key_by value, in row order" stays true (one bulk draw of size null-count equals the scalar draws). Text is updated only to name the bulk call; the catalogue pin is re-run.

## 5. Design notes

### `ReferenceTable` (one index rule, one gather)

- `keyed_index(key_value, hmac_key) -> int`: `hmac_hex`, the `None` guard, `int(hex[:8], 16) % row_count`. `keyed_row` becomes `self.row(self.keyed_index(...))`, so the rule exists once.
- `keyed_indices(keys, hmac_key)`: `codes, uniques = pd.factorize(np.asarray(keys, dtype=object))`, then `keyed_index` per unique, then `out = per_unique[codes]`. Keys are already strings (the caller applies `str`), so `factorize` compares strings only. `1`, `1.0` and `True` give different strings and stay different keys, as today.
- `take_columns(indices, columns)`: `{c: self._table.column(c).take(pa.array(indices)).to_pylist() for c in columns}`. A column not in the table gives `[None] * len(indices)`, which matches `r.get(col)` today. Plan validation already refuses that case (`joint_mask_column_not_in_reference`).
- `reference_tables/_types.py` is 135 lines and grows to about 175.

### `_pick_rows_mask` becomes `_pick_indices_mask` (returns an index array)

- One pass over `key_col` with the same iteration (`for val in key_col`, so the same objects as today): build `is_null` with today's predicate, and `strs` holding `str(val)` for the non-null rows.
- `idx[~is_null] = tbl.keyed_indices(strs, hmac_key=hmac_key_box.open()[0])`.
- `idx[is_null] = rng.integers(0, row_count, size=is_null.sum())`, the same generator, seeded as today.
- The draw-site `call_site` names `_pick_rows_mask`. The builder keeps that function name with the new return type, or updates the catalogue entry in the same slice.

### `_pick_rows_gen`

Returns the existing `indices` array. It does not build rows.

### `apply_joint_mask`

`for col, values in tbl.take_columns(idx, config.columns).items(): result[col] = values`. A Python list is assigned, as today, so pandas infers the same dtype.

### Placement

| New file | Directory | CODEMAP row | Sits beside |
|---|---|---|---|
| `test_joint_mask_vector_parity.py` | `tests/unit/transforms/` | "Unit tests" | existing joint_mask tests |
| `test_reference_table_indices.py` | `tests/unit/reference_tables/` | "Unit tests" | existing reference table tests |

Size: about 70 changed source lines in two files; about 220 test lines. Slice size 0.75 (S0 is done; its numbers are in section 1 and are re-run in A6).

## 6. Defect classes

### Plan-contract catalog (docs/handoffs/DEFECT-CATALOG.md)

| # | Class | Where it could appear | Closing structure | Test | Mutation |
|---|---|---|---|---|---|
| 1 | Value-bearing output | the `hmac_hex` `None` error | message unchanged, no key value | A4 | include the key in the message (A4 red) |
| 2 | Cleanup missing on an exit path | key material on error | `del job_seed` and `del hmac_key` kept on every exit; key read only through `OpaqueBox.open()` | A5 | drop `del hmac_key` in `keyed_indices` (A5 red) |
| 3 | State and concurrency | the per-unique index cache | local to one call; no module cache | A3 | cache indices at module level (A3 red: second key changes nothing) |
| 4 | Route parity and silent fallback | mask vs gen, `key_series` vs live frame | both modes gather through `take_columns`; both key sources go through one loop | A1, A2 | let gen keep `tbl.row` (structure test A7 red) |
| 5 | Referential integrity | same key gives same row | one `keyed_index` rule for single and bulk | A1, A3 | bulk path drops the modulo (A1 red) |
| 6 | Untrusted producer | key values (surrogates, mixed types, `pd.NA`) | same `str` and `errors="replace"` path through `hmac_hex` | A2 | strict utf-8 (A2 red on a surrogate) |
| 7 | Check then use | null predicate, then the index fill | one mask `is_null` used for both fills | A2 | compute the null count from `pd.isna` (A2 red: `pd.NA` rows) |
| 8 | Weak tests | only string keys | Hypothesis keys of str, int, float, NaN, None, `pd.NA`, `NaT`, bool, mixed object, surrogates; repeats; all-null | A1, A2 | M1 to M4 |
| 9 | Behavior-preserving refactor drift | replacing row dicts | frozen copy of today's `_pick_rows_mask`, `_pick_rows_gen` and output build as the oracle | A1 (Hypothesis property test vs the frozen oracle) | M1, M2 |
| 10 | Frozen contract drift | determinism goldens, draw-site catalogue | goldens unchanged; catalogue text re-pinned only if a call shape changes | A8 | change the null draw to per-row seeds (A8 red) |

### Recurring defect classes (dev-rules catalog)

| # | Class | Applies | How |
|---|---|---|---|
| 1 | Anchored validation | no | none |
| 2 | Strict wire types | no | none |
| 3 | No exception context | no | no new raise; the `hmac_hex` guard is moved, not changed |
| 4 | Versioned read models | no | none |
| 5 | Normalized guard scanners | no | none |
| 6 | No private reaching | yes | `take_columns` and `keyed_indices` are public methods of `ReferenceTable`, so the transform stops touching `_table` |
| 7 | No hidden CI failures | yes | no skips; Hypothesis derandomized in CI |
| 8 | One trust class per entry point | no | none |
| 9 | Mutations on final head | yes | run on the final head, head recorded |
| 10 | Allowlisted helpers checked | no | none |
| 11 | No raised caps | no | none |

## 7. Acceptance tests (each with its fail-before)

- **A1** Parity, Hypothesis 500 examples per mode: mask mode with and without `key_series`, gen mode, each shipped reference table, 1 to 4 target columns. Output frames equal a frozen copy of today's code (values, element types, dtypes). Fail-before: n/a (identity); M1 to M3 show power.
- **A2** Null and odd keys: `[None, NaN, pd.NA, NaT, "1", 1, 1.0, True, "\ud800"]` repeated: same rows as today. `pd.NA` and `NaT` are keyed (not nulls), and `1`, `1.0` and `True` are three keys.
- **A3** Determinism: same key, same row across calls and across a fresh `ReferenceTable`. A different mask key changes the rows.
- **A4** `hmac_hex` returning `None` (patched) raises the same `ValueError` text.
- **A5** Key hygiene: after a forced error inside `keyed_indices`, no frame local named `hmac_key` or `job_seed` holds key bytes (frame inspection, as the existing hygiene tests do).
- **A6** Speed (Dell through `vm-run`, three runs after a warmup, median and spread in the PR): 200,000 and 1M rows, all-distinct and 1,000-distinct keys. Targets are guarantee 4.
- **A7** Structure: no call to `ReferenceTable.row` remains in `transforms/joint_mask.py` (AST check).
- **A8** The joint_mask determinism goldens and the draw-site catalogue pin pass. If the text changed, the diff touches only joint_mask entries.

## 8. Named mutations

- M1: factorize the raw values instead of `str(val)` -> A2 red (`1` and `1.0` merge).
- M2: null predicate `pd.isna(val)` -> A2 red (`pd.NA` and `NaT` become nulls).
- M3: draw the null fallback with `size=n` and index by row -> A1 red.
- M4: drop the modulo in `keyed_indices` -> A1 red (IndexError or a different row).

## 9. Slices

| Slice | Content | Size | Risk |
|---|---|---|---|
| S0 | measurement (done for this plan, section 1); re-run as A6 on the build | 0 | none |
| S1 | `keyed_index`, `keyed_indices`, `take_columns`; index-array mask and gen paths; draw-site text; A1 to A8 | 0.75 | R2 (key handling) |

Changelog fragment, not breaking: "`joint_mask` picks reference rows by index arrays; output unchanged." Test depth: T0 and T1 (joint_mask, reference table, determinism goldens and draw-site catalogue tests in the selection). No escalation trigger.

## 10. Frozen contracts

None changed. The reference-table row mapping, the null-fallback stream and `SEED_PROTOCOL_VERSION` are unchanged. `ReferenceTable` gains two methods. `reference_tables` is internal to the engine (no public export change).

## 11. Pre-mortem

- **Series iteration and `to_pylist` give different objects for an exotic dtype** (for example an Arrow-backed extension dtype in the key column, or a timezone-aware reference column). The key loop keeps `for val in key_col` exactly. A1 runs every shipped table, and the builder adds a timezone-aware and a decimal reference column case.
- **Very large distinct-key columns** make the factorize uniques large. Memory is one string per distinct key, which is less than today's dict per row.
- **The HMAC is still the floor with all-distinct keys.** This is expected: the owner chose to keep Python `hmac` for identical bytes. A native HMAC with the same construction is a 1.0.x follow-up if wanted.

## 12. Open questions

None for the owner.

## 13. Follow-ups (not this plan)

- `joint_mask` on the chunked lane: multi-column output plus the source-key snapshot (about 2 slices, 1.0.x).
- A native HMAC-SHA256 index kernel with the same construction (`hex[:8]` of HMAC-SHA256 over `str(val)` UTF-8 with replace), proved identical by a differential test.
