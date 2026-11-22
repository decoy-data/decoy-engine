Status: plan (revision 1, 2026-11-22)

# GROUPED-SERIES-VECTOR: vectorize `grouped_series` inside the handler

Owner: Cam. Author: Opus (plan author). Date: 2026-11-22. Roadmap row: GROUPED-SERIES-VECTOR (V1 engine, approved 2026-11-22), from the fast-path exceptions study (vault `10_Projects/decoy/fastpath-exceptions-study-2026-11-22.md`, section 1). Owner decision 2026-11-22: null group keys follow the SQL rule (all nulls form one group, whatever the column type). That is a named byte change.

Anchors: paths are in this repository (decoy-engine), read at `origin/main` `70881ad79`. Line numbers are at that head.

Rules consulted: dev-rules `README.md`, `00-universal.md`, `risk-and-exceptions.md`, `development-loop.md` (PLAN, choke point, placement), `profiles/local-operations.md`, `feature-dev.md`, `performance.md`, `refactoring.md`, `cross-cutting-concerns.md`, `reuse-first.md`, `scope-discipline.md`, `testing.md`, `api-and-compatibility.md`, `catalogs/recurring-defects.md`; engine `CLAUDE.md`, `CODEMAP.md`, `docs/determinism.md`, `docs/compatibility-contract.md` (section 3.3 precedent for a one-site draw change without a protocol bump); PER-COLUMN-ROUTING plan (keeps `grouped_series` on the full-frame half).

Risk: R2. One draw site (`mask.grouped_series_monotone_walk`) changes output for null group keys outside object columns. Plan review: Dennis, then Codex. Code gate: Codex and Dennis.

## 1. Frame

`apply_grouped_series` (`transforms/grouped_series.py:174-218`) sorts by `(group_by, order_by)` with a stable sort, then walks the sorted frame with `iterrows`, one Python step per row:

- `_apply_cumcount` (`:221-249`): resets a counter when `g != current_group`.
- `_apply_monotone_walk` (`:252-298`): on each new group, seeds `numpy.random.default_rng` from `derive(seed, namespace, str(g))[:8]`; per row writes the running total and draws one `integers(step, max_step + 1)`.

Evidence (study, Dell node, pandas 2.3.3, numpy 2.2.6):

- `iterrows` is the cost. A vectorized build is 96 times faster at 1M rows with identical output for non-null groups.
- One bulk `integers(lo, hi + 1, size=k)` gives the same values as `k` scalar draws. The study measured `(1, 10)`. This plan's probe (Dell VM, 2026-11-22, 1,000 draws per range) found them equal for `[1, 10]`, `[0, 1]`, `[1, 2**31]`, `[1, 2**32]`, `[1, 2**32 + 1]`, `[1, 2**40]` and `[0, 2**62]`, so every range class is covered.
- Null keys depend on the dtype today. `g != current_group` is always true for NaN, so in a float column each null row is its own group (study: `[0, 0, 1, 0, 0]` for groups `[1, NaN, 1, None, NaN]`). In an object column `None == None`, so null rows share a group. For a pandas `string` or nullable dtype, `pd.NA != x` is `pd.NA` and `if pd.NA` raises an uncoded `TypeError` (read from the code; A5 pins it before the change).

The same walk also lives in `GroupedSeriesWalkProvider.walk` (`execution/native/protocol/providers_mask.py:264-315`), the independent protocol reference. `tests/native/test_determinism_goldens.py:230-261` pins the two equal on non-null groups.

## 2. Established solutions

- **Group-relative position by run boundaries.** After a sort, equal keys are adjacent. `cumcount` equals `arange(n) - run_start[run_id]`. This is how pandas implements `GroupBy.cumcount` (pandas 2.x, Apache-2.0) and how Arrow-based engines number rows within a partition (SQL `ROW_NUMBER() OVER (PARTITION BY g ORDER BY o) - 1`).
- **SQL null grouping.** `GROUP BY` and `PARTITION BY` put all nulls in one group (ISO/IEC 9075-2, "grouping": nulls are not distinct for grouping). pandas `factorize(..., use_na_sentinel=False)` and `groupby(dropna=False)` follow the same rule.
- **Bulk draws from one generator.** `Generator.integers(..., size=k)` draws `k` values from the same PCG64 stream (NumPy, BSD). Equality with scalar draws is measured (section 1) and pinned by test A6.

### Reuse inventory

- `transforms/grouped_series.py`: `GroupedSeriesConfig`, `apply_grouped_series` (`:174`), `_apply_cumcount`, `_apply_monotone_walk`. The functions keep their names and signatures. `tests/native/test_determinism_goldens.py:93` imports `_apply_monotone_walk`.
- `determinism/_derive.derive`: one call per group, as today.
- `execution/native/protocol/providers_mask.py:264` `GroupedSeriesWalkProvider`: stays the independent reference. It is not called by the transform, so the golden stays a real cross-check.
- `execution/native/_draw_sites_mask.py:320-331` draw-site entry: the text gains the null-group rule.
- Callers: `execution/_strategies/_grouped_series.py:67` (mask) and `generation/_grouped_windowed_generators.py:68` (generate). Both are unchanged.

## 3. Guarantee and non-goals

After this plan:

1. `cumcount` and `monotone_walk` output is identical to `70881ad79` for every input whose group key column has no null.
2. Object-dtype group columns whose only null spelling is `None` give identical output, nulls included.
3. Every other null spelling (`NaN`, `NaT`, `pd.NA`, and an object column that mixes `None` with `NaN`) forms one null group, with group label `None` for seeding. This is the named byte change.
4. Nullable and `string` dtype group columns with nulls run instead of raising an uncoded `TypeError`.
5. Values stay exact Python-int semantics. A value past int64 raises as it does today, and it never wraps.
6. At 1M rows with 1,000 groups: at least 30 times faster for both generators (Dell node).

Non-goals: chunking `grouped_series` (WHOLE-COLUMN-PREPASS, 1.0.x); any change to the sort (it stays pandas `sort_values(..., kind="stable")`, so order, null placement and mixed-type errors are unchanged); any change to config, validation or route.

## 4. Enumerations

### Exit paths

- `PlanCompileError` from `GroupedSeriesConfig.from_dict` (`transforms/grouped_series.py:150-172`): unchanged.
- `n == 0` (`transforms/grouped_series.py:203-204`): returns an empty int Series, unchanged.
- `TypeError` from `sort_values` on a mixed-type object column: unchanged, since the sort is the same call.
- `OverflowError` when a value passes int64: same type as today (S1 design keeps exact ints when the bound check fails).
- The `except BaseException: del seed; raise` key hygiene in both functions: kept.
- Removed: the uncoded `TypeError` from `pd.NA` comparison (guarantee 4).

### Routes and codes

- Mask: full-frame oracle route, as today; `grouped_series` stays non-row-local, global, order-sensitive (`execution/native/_capabilities.py:337-344`), and every chunk and out-of-core decline is unchanged.
- Generate: the legacy generation path (`generation/_grouped_windowed_generators.py:30-68`), as today.
- No route code or reason code added or removed.

### FK shapes

N/A: `grouped_series` is not join-safe and has no FK role; `group_by` and `order_by` are read, never keyed.

### Fields

- `GroupedSeriesConfig`: unchanged fields (`group_by`, `order_by`, `generator`, `start`, `step`, `max_step`).
- Config schema: unchanged.

### Output surfaces

- The output column: identical except guarantee 3.
- Draw-site catalogue entry `mask.grouped_series_monotone_walk`: `seed_derivation` and `call_shape` text change (null label `None`, bulk draw per group). `tests/native/test_draw_sites_catalogue_pinned.py` is re-baselined in the same slice.
- `GroupedSeriesWalkProvider` docstring: states the null-group rule. Its code is unchanged: called with label `None` it already seeds from `"None"`.
- `docs/compatibility-contract.md`: a dated entry like section 3.3 (one draw site changes, `SEED_PROTOCOL_VERSION` stays 7 because only null groups outside object `None` move and a bump would rekey every keyed column).
- `changelog.d/` fragment with a `Breaking:` line.

## 5. Design notes

One slice, in `transforms/grouped_series.py` only. The module stays near 300 lines.

Shared step, `_sorted_runs(working, group_col, order_col, pos_col) -> _Runs`:

- `sorted_df = working.sort_values([group_col, order_col], kind="stable")`, the same call as today.
- `keys = sorted_df[group_col].to_numpy(dtype=object)`, `positions = sorted_df[pos_col].to_numpy()`.
- `codes, _ = pd.factorize(keys, use_na_sentinel=False)`. All null spellings share one code (SQL rule). Non-null keys that compare equal share a code, as the `!=` walk does today: `1`, `1.0` and `True` hash and compare equal; `0.0` and `-0.0` compare equal (A3 pins both).
- Run starts: `starts = flatnonzero(r_[True, codes[1:] != codes[:-1]])`. After a sort, equal keys are adjacent and nulls sort last together, so each run is one group. A test asserts the run count equals the distinct code count (A4), so a sort that ever split a group fails loudly.
- Run label: `keys[start]` for a non-null run and `None` for the null run. Today the label is the first row's key, so non-null labels are unchanged.

`_apply_cumcount`:

- `rank = arange(n) - repeat(starts, lengths)`.
- Bound check in Python ints: `start + (max_len - 1) * step` and `start` inside int64. If yes, compute `start + rank * step` as int64 and scatter with `out[positions] = values`. If no, compute per value in Python ints and let `pd.Series(..., dtype=int)` raise `OverflowError` as today.

`_apply_monotone_walk`:

- One Python loop over runs, not rows. For each run: `g_seed = int.from_bytes(derive(seed, namespace, str(label).encode("utf-8", errors="replace"))[:8], "big")`, `steps = default_rng(g_seed).integers(step, max_step + 1, size=length)`. Then the run's values are `start` followed by `start + cumsum(steps[:-1])`. Today each row draws once, the last draw is unused, and the draw count is the same.
- Bound check: `start + max_len * max_step` inside int64 means int64 `cumsum` is exact. Otherwise cumulate in Python ints for that run (exact, as today).
- Scatter to original positions, return `pd.Series(out, dtype=int)` as today.

Worst case: one row per group. The loop then runs once per row with one `derive` and one `default_rng` each. Today does the same work plus `iterrows`, so the change is still faster but bounded by HKDF cost. A7 reports that case as well.

### Placement

| New file | Directory | CODEMAP row | Sits beside |
|---|---|---|---|
| none: tests extend `tests/unit/transforms/test_grouped_series.py` (703 lines, a test file; module-size ceiling applies to `src/` only) | `tests/unit/transforms/` | "Unit tests" | the existing suite |
| `test_grouped_series_vector_parity.py` | `tests/unit/transforms/` | "Unit tests" | `test_grouped_series.py` |

Size: about 90 changed source lines; about 250 test lines. Slice size 0.75.

## 6. Defect classes

### Plan-contract catalog (docs/handoffs/DEFECT-CATALOG.md)

| # | Class | Where it could appear | Closing structure | Test | Mutation |
|---|---|---|---|---|---|
| 1 | Value-bearing output | none: no message carries a group key | no new error text; `del seed` hygiene kept | A8 | drop the `del seed` on the error path (A8 red) |
| 2 | Cleanup missing on an exit path | N/A: no resource opened | N/A: in-memory arrays only | none needed | N/A: nothing to release |
| 3 | State and concurrency | per-group generators | one generator per run, local to the call | A6 | reuse one generator across runs (A2 red) |
| 4 | Route parity and silent fallback | mask vs generate | both call `apply_grouped_series`; no new branch per caller | A2 | N/A: one function, no per-route code |
| 5 | Referential integrity | N/A: no key column produced | N/A: output is not an FK | none needed | N/A |
| 6 | Untrusted producer | group labels (surrogates, mixed types) | `errors="replace"` encode kept; sort unchanged | A3 | strict utf-8 encode (A3 red on a lone surrogate) |
| 7 | Check then use | int64 bound check before int64 math | bound computed from the same `start`, `step`, `max_step` and run lengths used in the math | A9 | drop the bound check (A9 red: wraps instead of raising) |
| 8 | Weak tests | parity only on clean groups | Hypothesis parity with nulls, mixed equal keys, `-0.0`, one-row groups, large ranges | A1 | M1 to M4 |
| 9 | Behavior-preserving refactor drift | replacing `iterrows` | frozen copy of today's two functions as the oracle | A1 (Hypothesis property test vs the frozen oracle) | M1, M3 |
| 10 | Frozen contract drift | draw-site catalogue, determinism goldens | catalogue re-baselined with the named change; compatibility-contract entry; protocol version stays | A10 | change the null label to `"nan"` (A5 red) |

### Recurring defect classes (dev-rules catalog)

| # | Class | Applies | How |
|---|---|---|---|
| 1 | Anchored validation | no | no new validation |
| 2 | Strict wire types | no | none |
| 3 | No exception context | no | no new raise |
| 4 | Versioned read models | no | none |
| 5 | Normalized guard scanners | no | none |
| 6 | No private reaching | yes | the golden test already imports `_apply_monotone_walk`; the name is kept, and no new private import is added |
| 7 | No hidden CI failures | yes | no skips; Hypothesis derandomized in CI |
| 8 | One trust class per entry point | no | none |
| 9 | Mutations on final head | yes | closing structure: mutation run on the final head with the head recorded; test A1; mutations M1, M3, M4, M5 |
| 10 | Allowlisted helpers checked | no | none |
| 11 | No raised caps | yes | no module-size ceiling raised |

## 7. Acceptance tests (each with its fail-before)

- **A1** Parity, Hypothesis 1,000 examples: group columns of int, float, str and object (with ties, unsorted input, one-row groups, `start`, `step`, `max_step` from the config range); no nulls. Both generators match a frozen copy of today's functions exactly. Fail-before: n/a (identity); M1 to M3 show power.
- **A2** Mask and generate parity: the handler and `_grouped_windowed_generators` on the same frame give the same values as the frozen copy. The existing `test_grouped_series.py` and `TestGroupedSeriesGolden` (`tests/native/test_determinism_goldens.py:230`) pass unchanged, including `test_golden_vector_pins_step_stream` (`[1, 10, 17, 1, 3, 12]`).
- **A3** Equal-key pins: keys `[1, 1.0, True]` form one group; `[0.0, -0.0]` form one group; a lone-surrogate label still walks; each matches today.
- **A4** Runs equal groups: for every A1 example, the run count equals the distinct-key count.
- **A5** Null rule, the named change: float `[1, NaN, 1, None, NaN]` cumcount gives `[0, 0, 1, 1, 2]`, not today's `[0, 0, 1, 0, 0]`. A `string` dtype column with `pd.NA` runs. An object column with only `None` is identical to today. The null group's walk equals `GroupedSeriesWalkProvider.walk(key, ns, None, k, ...)`. Fail-before: today gives `[0, 0, 1, 0, 0]` and the `string` case raises `TypeError`.
- **A6** Bulk draw pin: for ranges `[1, 10]`, `[0, 1]`, `[1, 2**32]`, `[1, 2**32 + 1]` and `[0, 2**62]`, `integers(size=k)` equals `k` scalar draws. Fail-before: n/a (it pins a library property the design relies on, so a numpy upgrade that breaks it fails here first).
- **A7** Speed (Dell through `vm-run`, three runs after a warmup, median and spread in the PR): 1M rows, 1,000 groups, both generators at least 30 times faster; the 1M-groups case is reported, with no target.
- **A8** Key hygiene: an error raised inside the walk (forced by a patched `derive`) leaves no frame local named `seed` holding the key.
- **A9** Overflow: `start = 2**62`, `step = 2**61` over 4 rows raises `OverflowError`, as today; it never returns wrapped values. Fail-before: n/a (identity); M4 shows power.
- **A10** Draw-site catalogue pin re-baselined; the diff touches only the `mask.grouped_series_monotone_walk` text.

## 8. Named mutations

- M1: compute run starts without the sort (factorize the unsorted column) -> A1 red.
- M2: draw `size=length - 1` instead of `size=length` -> A1 stays green (the last draw is unused); A6 is unaffected. Kept as an equivalent-mutant note: the draw count does not change output, so the plan does not rely on it.
- M3: seed the run label from `keys[start + 1]` -> A1 red.
- M4: skip the int64 bound check -> A9 red.
- M5: `use_na_sentinel=True` (nulls each their own code) -> A5 red.

## 9. Slices

| Slice | Content | Size | Risk |
|---|---|---|---|
| S1 | `_sorted_runs`, vectorized `_apply_cumcount` and `_apply_monotone_walk`, draw-site text, provider docstring, compatibility-contract entry, changelog `Breaking:` line, A1 to A10 | 0.75 | R2 (named byte change on one draw site) |

Changelog `Breaking:` line: "`grouped_series`: null `group_by` values now form one group in every column type (SQL rule). Before, each NaN or NaT row was its own group and a nullable string column raised. Object columns with `None` are unchanged." Test depth: T0 per edit, T1 impact-selected per commit (the determinism goldens and draw-site catalogue tests are in the selection). Escalation trigger: none (the catalogue pin is a test fixture owned by this draw site, not a shared fixture).

## 10. Frozen contracts

- Determinism: `SEED_PROTOCOL_VERSION` stays 7. Only null groups outside object `None` columns change; the same reasoning as compatibility-contract section 3.3 (`windowed_date`) applies, and the plan adds a dated entry there.
- Draw-site catalogue (`tests/native/test_draw_sites_catalogue_pinned.py`): one entry's text re-baselined.
- Public API: none. `apply_grouped_series` signature unchanged.

## 11. Pre-mortem

- **A pandas `factorize` corner treats two keys differently from `!=`** (for example `Decimal` and float, or `numpy.datetime64` and `Timestamp` in one object column). A1 generates mixed equal keys, and A4 catches a split. If a case differs, stop and report it. Do not add a per-type branch.
- **numpy changes bulk-draw buffering in a future release.** A6 fails first; numpy is pinned by the lock, and the bump would show it.
- **Many tiny groups stay slow.** The HKDF per group bounds the speedup. That is reported, not hidden (A7). A batched `derive` is out of scope.
- **The owner wants a different null label.** The label is one constant (`_NULL_GROUP_LABEL = None`). The default keeps object `None` columns identical.

## 12. Open questions

- Q1 (owner, default recommended): the null group seeds from label `None`, so object columns with `None` keep their bytes. The cost: the null group and a literal `"None"` string group in the same column draw the same steps. That is true today too, and the rows stay in separate groups. Alternative: a distinct label, which changes object `None` columns too.

## 13. Follow-ups (not this plan)

- WHOLE-COLUMN-PREPASS (1.0.x): lets `grouped_series` run on the chunked lane through one pre-pass consumer.
