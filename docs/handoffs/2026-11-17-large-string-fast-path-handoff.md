# Handoff: build LARGE-STRING-FAST (roadmap row 24zy)

Status: ready to build. Written 2026-11-17. One engine slice, one PR.

Rules consulted: 00-universal, performance, testing, development-loop, documentation

## Read first

- Plan: [`../plans/2026-11-17-large-string-fast-path.md`](../plans/2026-11-17-large-string-fast-path.md).
  It holds the design, the reasons each edge case stays byte-identical, the rejected options and the
  acceptance list. This handoff says how to build it; the plan says why.
- Roadmap row **24zy LARGE-STRING-FAST** in the CLI repo `docs/ROADMAP.md`.
- Code: `src/decoy_engine/kernel/_scalar.py` (`redact_array` at `:82`, `truncate_array` at `:155`).
- Tests: `tests/unit/kernel/test_scalar_vectorized_parity.py`.

## The problem in three lines

`redact_array` and `truncate_array` use a fast Arrow path only when the input type is exactly
`pa.string()`. A `large_string` column (from Polars Parquet, or pandas `string[pyarrow]`) falls to
the per-row Python reference. Output is the same; speed is 8 to 55 times worse in the kernel and
about 10 times worse for a whole 2M-row job (numbers and host in the plan).

## The fix

In both dispatchers, right after `combine_chunks()` and before the `v.type == pa.string()` check:

```python
if pa.types.is_large_string(v.type):
    # Same UTF-8 values with 32-bit offsets; past 2 GiB the cast raises and the reference runs.
    v = v.cast(pa.string())
```

It sits inside the existing `try`, so any cast failure (over 2 GiB of text) lands on the reference,
exactly as today. Do not touch `_redact_array_reference` or `_truncate_array_reference`; they are
frozen oracles.

## Steps

1. Branch from current engine main.
2. Tests first, and run them red:
   - Move the `large_string` cases from the two `*_excluded_inputs_take_reference` route-spy tests
     (`:387`, `:432`) into the fast-path spy tests. Before the fix these fail.
   - Add `large_string` versions of the differential cases listed in the plan's Tests section
     (truncate matrix, redact sweep, sliced, multi-chunk, all-null, empty, empty chunks, Unicode,
     invalid UTF-8, cast-raises fallback).
   - Add the small end-to-end `run_pipeline` test (string file vs `large_string` file, same output,
     no reference calls).
3. Make the two-line change in each dispatcher. Update both docstrings and the test module docstring:
   `large_string` is now admitted by a cast; the fallback list no longer names it.
4. Mark the deferred note at the top of `docs/plans/2026-09-21-phase5-native-operator-expansion.md`
   as done, pointing at this slice.
5. Measure: run `docs/plans/large-string-evidence/kernel_bench.py` and `run_probe.py` before and
   after on the same host. Put both tables, the host and the pyarrow version in the PR description.
6. Gates: `scripts/dev/gates.sh tests/unit/kernel tests/native` then the full suite with
   `GATES_WORKERS=4 scripts/dev/gates.sh --keep-going --steps tests tests`.
7. Changelog: add `changelog.d/large-string-fast-path.md` with a `### Changed` entry (speed only, no
   output change). The fragment check requires one because `src/` changes under a `perf` or `fix`
   commit.
8. Open the PR; after merge, update row 24zy in the CLI repo roadmap to MERGED with the PR number and
   merge commit, and add it to `RECENTLY-SHIPPED.md`.

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
- **Evidence scripts** live under `docs/plans/large-string-evidence/`. They are not tests and are not
  collected by pytest; run them with `python -I`. `source_types.py` needs `polars`, which is in the
  engine venv.

## Done when

- Every box in the plan's Acceptance section is ticked.
- `run_probe.py` shows zero reference calls for the `large_string` cells.
- Row 24zy says MERGED with the PR link.
