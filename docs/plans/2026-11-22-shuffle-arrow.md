Status: plan (revision 1, 2026-11-22)

# SHUFFLE-ARROW: write the shuffle permutation back in one vectorized step

Owner: Cam. Author: Opus (plan author). Date: 2026-11-22. Roadmap row: SHUFFLE-ARROW (V1 engine, approved 2026-11-22), from the fast-path exceptions study (vault `10_Projects/decoy/fastpath-exceptions-study-2026-11-22.md`, section 3). Output must be identical: the same permutation, the same values and the same Python types.

Anchors: paths are in this repository (decoy-engine), read at `origin/main` `70881ad79`. Line numbers are at that head.

Rules consulted: dev-rules `README.md`, `00-universal.md`, `risk-and-exceptions.md`, `development-loop.md` (PLAN), `profiles/local-operations.md`, `performance.md`, `refactoring.md`, `reuse-first.md`, `scope-discipline.md`, `proportionality.md`, `testing.md`, `catalogs/recurring-defects.md`; engine `CLAUDE.md`, `CODEMAP.md`, `docs/determinism.md`.

Risk: R1. One handler, no draw change, no route change, identical bytes. Plan review: Codex. Code gate: Codex.

## 1. Frame

`ShuffleStrategyHandler.run` (`execution/_strategies/_shuffle.py:47-89`) derives one seed, draws one `rng.permutation(len(non_na_values))` (`:80`), then writes the permuted values back with a Python loop over every non-null position (`:81-83`) into a list of `None`, and wraps it in an object Series (`:88`).

Measured for this plan (Dell VM, 2026-11-22, 1M rows, 10% nulls, same seed):

| Build | strings | floats | Identical values and types |
|---|---|---|---|
| today (loop) | 0.201 s | 0.171 s | baseline |
| numpy object scatter `out = np.full(n, None, object); out[~na] = permuted` | 0.054 s | 0.049 s | yes, both |
| Arrow `filter`, `take`, `replace_with_mask`, back to pandas | 0.141 s | 0.024 s | strings yes; floats **no** (nulls come back as `NaN`, values as numpy floats) |

The study measured the Arrow form at 5 times faster on strings (1.11 s to 0.22 s, a different harness).

**Design choice: the numpy scatter, not an Arrow round trip.** The handler receives and returns a pandas frame on the oracle route. An Arrow round trip changes null spelling and value types for non-string columns, so it would need a per-type repair, and it is slower on strings. The scatter does the same permutation and gather in one vectorized step, keeps every value object exactly, and is 3.5 to 4 times faster on both types. The row name stays; the Arrow kernel belongs to WHOLE-COLUMN-PREPASS (1.0.x), where the column arrives as Arrow. If the owner wants the Arrow form in V1 anyway, that is open question Q1.

## 2. Established solutions

- **Scatter by boolean mask** (`ndarray.__setitem__` with a mask, NumPy, BSD): the standard vectorized inverse of a gather. `out[mask] = values` writes `values` in mask order, which is exactly today's loop order (`non_na_positions` ascending).
- **Seeded permutation** (`numpy.random.Generator.permutation`): unchanged.

### Reuse inventory

- `execution/_strategies/_shuffle.py`: the handler, `UNKEYED_SHUFFLE_NAMESPACE`, the seed derivation (`:65-79`), the permutation (`:80`) and the object Series wrap (`:88`). Only lines `:81-83` change.
- `determinism.derive`, `context_draw_identity`: unchanged.
- Existing shuffle tests (`tests/unit/execution/` shuffle handler tests and the determinism goldens for the shuffle draw site): the parity oracle.

## 3. Guarantee and non-goals

1. Output values, Python types, null positions and the object dtype are identical to `70881ad79` for every column type, in deterministic and unkeyed modes.
2. The seed and the permutation draw are unchanged, so the draw-site entry and `SEED_PROTOCOL_VERSION` are unchanged.
3. At 1M rows, the handler is at least 2.5 times faster on strings and floats.

Non-goals: chunking `shuffle` (WHOLE-COLUMN-PREPASS); an Arrow round trip; any change to `isna` (`pd.NA`, `NaT` and `NaN` stay nulls as today).

## 4. Enumerations

### Exit paths

- `shuffle_requires_namespace` (`execution/_strategies/_shuffle.py:61-66`): unchanged, raised before any draw.
- Normal return: `(df, [])` with the column replaced (`execution/_strategies/_shuffle.py:88-89`).
- Empty column or all-null column: the scatter writes nothing; same as today (A2).

### Routes and codes

- Full-frame oracle route, as today: `shuffle` stays non-row-local in `execution/native/_capabilities.py`, and every chunk decline is unchanged.
- No reason code added or changed.

### FK shapes

N/A: `shuffle` is not join-safe (`join_safe = False`, `execution/_strategies/_shuffle.py:42`) and has no FK role.

### Fields

N/A: no config or plan field changes; `deterministic` and `namespace` are read as today.

### Output surfaces

- The output column: identical (guarantee 1).
- Draw-site catalogue entry for shuffle: unchanged (the draw is unchanged).

## 5. Design notes

Replace `:81-83` with:

- `out = np.full(len(source), None, dtype=object)`
- `out[~na_mask] = permuted`

then wrap as today: `pd.Series(out, dtype=object, index=df.index)`. `permuted` is already an object array of the original value objects (`source.to_numpy(dtype=object)`), so the scatter copies references, not converted values. `non_na_positions` is no longer needed and is removed.

### Placement

| New file | Directory | CODEMAP row | Sits beside |
|---|---|---|---|
| `test_shuffle_scatter_parity.py` | `tests/unit/execution/` | "Unit tests" | existing shuffle handler tests |

Size: about 5 changed source lines; about 90 test lines. Slice size 0.25.

## 6. Defect classes

### Plan-contract catalog (docs/handoffs/DEFECT-CATALOG.md)

| # | Class | Where it could appear | Closing structure | Test | Mutation |
|---|---|---|---|---|---|
| 1 | Value-bearing output | N/A: no message changes | N/A: no new text | none needed | N/A |
| 2 | Cleanup missing on an exit path | N/A: no resource | N/A: arrays only | none needed | N/A |
| 3 | State and concurrency | N/A: one local generator, as today | N/A: unchanged | none needed | N/A |
| 4 | Route parity and silent fallback | N/A: one route, unchanged | N/A: no route change | none needed | N/A |
| 5 | Referential integrity | N/A: not join-safe | N/A: no FK | none needed | N/A |
| 6 | Untrusted producer | mixed-type object columns | scatter copies object references, so no coercion | A1 | build `out` with `np.empty(n)` float (A1 red) |
| 7 | Check then use | N/A: no check | N/A | none needed | N/A |
| 8 | Weak tests | only string columns tested | Hypothesis over str, int, float, bool, Decimal, datetime, mixed object, `pd.NA`, `NaT`, all-null, empty | A1, A2 | M1, M2 |
| 9 | Behavior-preserving refactor drift | replacing the loop | frozen copy of today's handler as the oracle | A1 (Hypothesis property test vs the frozen oracle) | M1, M2 |
| 10 | Frozen contract drift | determinism goldens | goldens pass unchanged | A3 | change the permutation seed slice (A3 red) |

### Recurring defect classes (dev-rules catalog)

| # | Class | Applies | How |
|---|---|---|---|
| 1 | Anchored validation | no | none |
| 2 | Strict wire types | no | none |
| 3 | No exception context | no | no new raise |
| 4 | Versioned read models | no | none |
| 5 | Normalized guard scanners | no | none |
| 6 | No private reaching | no | none |
| 7 | No hidden CI failures | yes | no skips; Hypothesis derandomized in CI |
| 8 | One trust class per entry point | no | none |
| 9 | Mutations on final head | yes | run on the final head, head recorded |
| 10 | Allowlisted helpers checked | no | none |
| 11 | No raised caps | no | none |

## 7. Acceptance tests (each with its fail-before)

- **A1** Parity, Hypothesis 500 examples: columns of each type in section 6 row 8, with random null positions, both modes. The handler output equals a frozen copy of today's handler: `Series.equals`, plus element `type` equality, plus the same null positions. Fail-before: n/a (identity); M1 and M2 show power.
- **A2** Edge cases: empty frame, all-null column, one non-null value: same as today.
- **A3** Existing shuffle handler tests and the shuffle determinism golden pass unchanged.
- **A4** Speed (Dell through `vm-run`, three runs after a warmup, median and spread in the PR): 1M rows, strings and floats, at least 2.5 times faster.

## 8. Named mutations

- M1: scatter into `out[na_mask]` -> A1 red.
- M2: build `out` as `pd.Series(permuted)` reindexed without the null mask -> A1 red.
- M3: wrap without `dtype=object` -> A1 red on int columns with nulls (float re-inference).

## 9. Slices

| Slice | Content | Size | Risk |
|---|---|---|---|
| S1 | scatter write-back, A1 to A4 | 0.25 | R1 |

Changelog fragment, not breaking: "`shuffle` writes its permutation back in one vectorized step; output unchanged." Test depth: T0 and T1. No escalation trigger.

## 10. Frozen contracts

None touched. Output bytes, the draw site and `SEED_PROTOCOL_VERSION` are unchanged.

## 11. Pre-mortem

- **numpy coerces on assignment.** An object array assigned from an object array keeps references. A1 checks element types to prove it.
- **A pandas extension dtype source** (for example `string[pyarrow]`): `to_numpy(dtype=object)` gives the same objects as today, because that line does not change.

## 12. Open questions

- Q1 (owner, default recommended): ship the numpy scatter (identical for every type, faster on both measured types) instead of an Arrow round trip (identical on strings only). The Arrow kernel comes with WHOLE-COLUMN-PREPASS.

## 13. Follow-ups (not this plan)

- WHOLE-COLUMN-PREPASS (1.0.x): `shuffle` on the chunked lane, where the Arrow `filter`/`take`/`replace_with_mask` form fits because the column is Arrow already.
