# Handoff: build LARGE-STRING-FAST (roadmap row 24zy)

Status: ready to build. Written 2026-11-17. One engine slice, one PR.

Repo: `decoy-engine`. Branch: `perf/large-string-fast-path` from current main.

Rules consulted: 00-universal, risk-and-exceptions, development-loop, performance, testing,
architecture, cross-cutting-concerns, proportionality, documentation

## Read first

- Plan: [`../plans/2026-11-17-large-string-fast-path.md`](../plans/2026-11-17-large-string-fast-path.md).
  It holds the design, the reasons each edge case stays byte-identical, the rejected options and the
  acceptance list. This handoff says how to build it; the plan says why.
- Roadmap row **24zy LARGE-STRING-FAST** in the CLI repo `docs/ROADMAP.md`.
- Code: `src/decoy_engine/_arrow_types.py` and `src/decoy_engine/kernel/_scalar.py`
  (`redact_array` at `:82`, `truncate_array` at `:155`).
- Tests: `tests/unit/kernel/test_scalar_vectorized_parity.py`.

## The problem in three lines

`redact_array` and `truncate_array` use a fast Arrow path only when the input type is exactly
`pa.string()`. A `large_string` column (from Polars Parquet, or pandas `string[pyarrow]`) falls to
the per-row Python reference. Output is the same; speed is 8 to 55 times worse in the kernel and
about 10 times worse for a whole 2M-row job (numbers and host in the plan).

## The fix

Add `narrow_text(array)` beside `is_text` in `src/decoy_engine/_arrow_types.py`. It returns a
`string` array unchanged, safely casts `large_string` to `string`, and rejects non-text input. In
both dispatchers, call that helper after `combine_chunks()` and inside the existing `try`:

```python
if is_text(v.type):
    v = narrow_text(v)
    v.validate(full=True)
    ...
```

The helper is the one owner of offset-width normalization. Its call sits inside the guards' existing
`try`, so an over-2-GiB cast failure lands on the reference exactly as today. Do not touch
`_redact_array_reference` or `_truncate_array_reference`; they are frozen oracles.

## Steps

1. Branch from current engine main.
2. Tests first, and run them red:
   - Move the `large_string` cases from the two `*_excluded_inputs_take_reference` route-spy tests
     (`:387`, `:432`) into the fast-path spy tests. Before the fix these fail.
   - Add `large_string` versions of the differential cases listed in the plan's Tests section
     (truncate matrix, redact sweep, sliced, multi-chunk, all-null, empty, empty chunks, Unicode,
     invalid UTF-8, cast-raises fallback).
   - Add the small end-to-end `run_pipeline` test (string file vs `large_string` file, same output,
     no reference calls), and assert route evidence says `chunked`.
   - Add the central-mechanism guard: wrap `_scalar.narrow_text`, call both dispatchers with
     `large_string`, and assert one helper call from each.
3. In `tests/unit/test_arrow_types.py`, unit-test `narrow_text`: `string` identity, `large_string`
   values/nulls/slices, and non-text rejection. Simulate the over-2-GiB failure by monkeypatching
   `_scalar.narrow_text` to raise `pa.ArrowInvalid`; PyArrow extension methods are not the test seam.
4. Add the helper and call it from both dispatchers. Update both docstrings and the test module docstring:
   `large_string` is now admitted by a cast; the fallback list no longer names it.
5. Mark the deferred note at the top of `docs/plans/2026-09-21-phase5-native-operator-expansion.md`
   as done, pointing at this slice.
6. Measure: run `docs/plans/large-string-evidence/kernel_bench.py` and `run_probe.py` before and
   after on the same host. Put both tables, the host and the pyarrow version in the PR description.
7. Gates: `scripts/dev/gates.sh tests/unit/kernel tests/native` then the full suite with
   `GATES_WORKERS=4 scripts/dev/gates.sh --keep-going --steps tests tests`.
8. Changelog: add `changelog.d/large-string-fast-path.md` with a `### Changed` entry (speed only, no
   output change). The fragment check requires one because `src/` changes under a `perf` or `fix`
   commit.
9. Open the PR; after merge, update row 24zy in the CLI repo roadmap to MERGED with the PR number and
   merge commit, and add it to `RECENTLY-SHIPPED.md`.

## Worker rules

- Name the recurring-defect class of each finding.
- Write the generated tests first and record that they fail before the fix.
- Attack your own diff with the plan's mutations after the final source change.
- Run before and after baselines in the same environment from `uv.lock`.
- Never widen a threshold or skip a test to make a gate pass.
- Stop and report if a catalogued class repeats after its fix.

## Gotchas

- **Invalid UTF-8.** The cast does not check UTF-8, so `validate(full=True)` must still run after the
  cast, not before. It already does if you put the cast where shown. Build the invalid-bytes test
  input with `pa.Array.from_buffers(pa.large_string(), ...)` (int64 offsets).
- **Redact output type.** For an all-null or empty input, redact returns a `null`-typed array, not
  `string`, same as the reference. The harness checks the type; do not "fix" it.
- **Don't add a timing test to CI.** The `serial` marker rule (CONTRIBUTING) applies to any
  wall-clock assertion, and the plan keeps speed as a by-hand check.
- **Don't widen scope.** `string_view`, dictionary strings, `hash_array`, the native admission rules
  and the pandas handlers are non-goals in the plan.
- **Caller proof.** Native scalar, out-of-core and native auto-chunk all reach these guards directly.
  Pandas handlers also call them, but pandas conversion may already normalize `large_string` to
  `string`; do not require a storage width that the pandas route does not preserve.
- **Evidence scripts** live under `docs/plans/large-string-evidence/`. They are not tests and are not
  collected by pytest; run them with `python -I`. `source_types.py` needs `polars`, which is in the
  engine venv.

## Done when

- Every box in the plan's Acceptance section is ticked.
- `run_probe.py` shows zero reference calls for the `large_string` cells.
- Row 24zy says MERGED with the PR link.
