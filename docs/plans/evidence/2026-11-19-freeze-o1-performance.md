Status: record

# FREEZE-OUTPUT O1: build record (performance, mutations, goldens)

Plan: `docs/plans/2026-11-18-freeze-batch.md` rev 3.2, section 14 ("O1 used too much memory") and AT-O1a to AT-O1f. Slice head for the code measured here: `ad4f86303` on `feat/freeze-o1`. This file and the data files beside it were added after that head and change no source or test.

## 1. Performance

Method. One fresh process per cell. The source table is built first, then the run starts, so `+MB` is the process high-water mark after the run minus the mark after the build. The same probe ran against `origin/main` (`305fd36ed`) and the head, on the Dell (WSL2, Linux, `VMRUN_LINUX=1 ~/bin/vm-run engine`), with the head and main matrices running at the same time, so wall times carry some noise from other jobs on the box. The probe is `2026-11-19-freeze-o1-perf.py`, the matrix is `2026-11-19-freeze-o1-perf-matrix.sh`, raw rows are `2026-11-19-freeze-o1-perf-head.jsonl` and `-main.jsonl`, and the joined table is `2026-11-19-freeze-o1-perf-table.txt`.

Data: `id`, `v` (int64, 5% blanks, values below 1,000,000), `m` (text, redacted under `when: "v > 5"`). Classes: plain, FK (parent holds the same keys), declared integer (text source), date-shift anchor. Variants: `numexpr` (in-range values, in-range int literal), `object_value` (one value `2**60`), `object_literal` (`v > 9007199254740993`), `float_literal` (`v > 5.5`). `eval` is the time inside `_eval_predicate` (it includes the conversion); `frame` is the time inside `when_eval_frame` alone (head only).

Selected cells at 10M rows, full frame (`+MB` over the build, eval seconds):

| Class | Variant | main +MB | head +MB | main eval | head eval | head frame |
|---|---|---|---|---|---|---|
| plain | numexpr | 1594 | 1618 | 0.157 | 0.269 | 0.159 |
| plain | object_value | 1596 | 1606 | 0.191 | 1.158 | 0.510 |
| plain | object_literal | 339 | 888 | 0.166 | 1.215 | 0.527 |
| plain | float_literal | 1595 | 1618 | 0.075 | 1.890 | 0.617 |
| FK | numexpr | 2515 | 2514 | 0.143 | 0.372 | 0.167 |
| FK | object_value | 2505 | 2501 | 0.156 | 1.904 | 0.808 |
| FK | float_literal | 2514 | 2514 | 0.128 | 1.722 | 0.660 |
| declared | numexpr | 1195 | 1184 | 0.230 | 0.345 | 0.146 |
| declared | object_value | 1280 | 1270 | 0.256 | 1.483 | 0.438 |
| declared | float_literal | 1281 | 1198 | 0.273 | 2.026 | 0.577 |
| anchor | numexpr | 2731 | 2799 | 0.059 | 0.268 | 0.183 |
| anchor | object_value | 2732 | 2799 | 0.111 | 1.686 | 0.816 |
| anchor | float_literal | 2730 | 2790 | 0.092 | 1.956 | 0.557 |

Other routes at 10M rows: unified plain +1717 MB (main) against +2010 MB (head), eval 0.59 s against 2.46 s; unified declared +1506 against +1360 MB, eval 2.30 s against 3.08 s. At 1M rows every cell stays within 0.2 s of eval and 15 MB of main except plain `object_literal` (+57 MB, 0.15 s).

Chunked oracle leg, 65,536-row chunks, 10M rows: `+MB` is 0 on both sides because the source build mark is above the run mark, so the chunked route adds no memory above the table it reads. Eval time sums over 153 chunks: plain 0.69 s against 0.83 s, anchor 0.38 s against 0.88 s. FK and declared chunked cells were not measured: the chunked route refuses a passthrough FK parent key (`chunked_fk_parent_strategy_not_self_mask_safe`) and the declared text source fails the same way on main and head (`when_expression_error`, a limit of this probe).

Reading (round 2 numbers, before the exact integer evaluator; round 3 follows).
- The common path (an in-range value and an in-range int literal) keeps the old memory: 0 to 24 MB over main on plain, FK and declared at 10M, 68 MB on anchor, and its extra eval time is 0.11 to 0.23 s on runs of 15 to 195 s.
- The round-2 object path (a value or integer literal beyond `2**53`, or any float literal against an integer column) cost 1.0 to 1.9 s of eval at 10M rows, and its conversion alone is 0.4 to 0.8 s. The temporary object array adds up to about 0.55 GB, but the run peak only moves when no row is selected (plain `object_literal`: 339 to 888 MB). When rows are selected the peak is set later in the run and does not change. The `object_literal` peak (888 MB) stays below the same data's `numexpr` peak (1594 MB).
- The unified plain route at 10M is the largest measured move: +293 MB and +1.9 s eval, 17.4 s to 19.6 s wall. Unified keeps one full frame and now builds a float64 eval copy of the nullable column.
- The four classes cost the same within noise, as in the r1 note on the PR.

Stop line (round 2; the two cells it names are fixed in round 3). The plan states no number: "a regression beyond the existing route budget". The route budget is the governor slot budget, which is a per-slot byte limit set at run time. No measured run raised its peak above what a same-size run of the same route reached before this change, except unified plain at 10M (+293 MB). This record gives the numbers and does not claim a pass or a fail for that cell. The owner call, if wanted, is whether the unified route's extra float64 copy at 10M rows and the 1 to 2 s object-path cost for float literals are acceptable. Semantics were not changed to avoid them.

### Round 3: exact integer evaluator

Codex round 2 asked for the exact comparison to be done on the integers instead of through an object or float64 copy. `_eval_predicate` now walks the parsed predicate. A comparison or membership test on an integer column runs on the integers where they are: a nullable array through its own mask, a NumPy array as is. A float bound is rounded (`v > 18.5` is `v >= 19`, `v <= 18.5` is `v <= 18`, `v > -18.5` is `v >= -18`); a non-integral `==` is never true and `!=` is always true; a blank is selected only by `!=` and `not in`. The object path stays for a column holding a value beyond 2**53 and for an integer literal beyond 2**53 (an `int` literal such as `9007199254740993`). Other columns are read by the pandas evaluator one comparison at a time, and a string or bool literal against an integer column hands the whole predicate to the old path. Probe `2026-11-19-freeze-o1-perf-matrix-r3.sh`, rows in `...-perf-head-r3.jsonl`, same method and box as above, 10M rows, full frame (+MB over the build, eval seconds):

| Class, variant | main | round 2 | round 3 |
|---|---|---|---|
| plain, float_literal | 1595, 0.075 | 1618, 1.890 | 1547, 0.135 |
| FK, float_literal | 2514, 0.128 | 2514, 1.722 | 2511, 0.128 |
| declared, float_literal | 1281, 0.273 | 1198, 2.026 | 1136, 0.264 |
| anchor, float_literal | 2730, 0.092 | 2790, 1.956 | 2732, 0.129 |
| unified plain, numexpr | 1717, 0.59 | 2010, 2.457 | 1940, 0.366 |
| plain, object_literal | 339, 0.166 | 888, 1.215 | 659, 1.352 |
| FK, object_literal | 1852, 0.122 | 1848, 1.434 | 1768, 1.305 |
| declared, object_literal | 489, 0.251 | 561, 1.222 | 493, 1.523 |
| anchor, object_literal | 2798, 0.068 | 2798, 1.131 | 2786, 1.515 |

A float literal now costs what it did on main (0.13 to 0.26 s eval) and adds no memory. Unified plain no longer makes the float64 copy: eval is 0.37 s against 0.59 s on main, and the run peak is 1940 MB (round 2: 2010, main 1717; the remaining +223 MB is not from the `when:` evaluation and was not traced). The `object_literal` cells stay on the object path by design (an integer literal beyond 2**53): about 1.3 to 1.5 s and, for plain, +320 MB over main at 10M rows. Those are the only measured cells that still cost more than 1 s.

## 2. Mutations on the final code head

Run with `2026-11-19-freeze-o1-mutations.sh` (applies one change from `2026-11-19-freeze-o1-mutate.py` to `src/`, runs the O1 owners with `-x`, restores `src/`). The unmutated owner set passes. Code head `ad4f86303`; every mutation below was run on it. The first rows were retargeted in round 3 because the object and float64 conversions moved into `_int_leaf`.

| Mutation | Plan row | Result |
|---|---|---|
| object path never taken (`_int_leaf`) | AT-O1a, AT-O1c | red: `test_generated_frames_equal_the_python_integer_reference` |
| integer-literal range check removed | AT-O1b, AT-O1c | red: `test_the_object_path_is_taken_only_for_wide_values_or_integer_literals[v > 9007199254740993]` (it first survived: with the exact integer compare the answer is the same, so the left operand dtype witnesses the rule) |
| value range check removed | AT-O1c | red: reference test |
| float bound rounds the wrong way (`>= floor`, not `floor + 1`) | AT-O1b | red: reference test, and `test_non_integral_bounds_keep_the_blank_rule` |
| non-integral `!=` returns false | AT-O1b | red: `test_float_bounds_round_exactly_and_never_build_a_frame[!=-18.5]` |
| a blank is never selected (`!=`, `not in`) | AT-O1b | red: reference test |
| integer path disabled (old float64 or object frame returns) | round 3 | red: `test_float_bounds_round_exactly_and_never_build_a_frame` (the frame builder is replaced by a function that raises) |
| FK columns dropped from the set | AT-O1d | red: `test_only_allowlisted_functions_call_the_helper[fk_columns_for_table]` |
| anchor columns dropped | AT-O1b | red: `test_the_adapter_ingests_with_the_union_of_every_role[anchor]` |
| `top_code` columns dropped | AT-O1b | red: `...[top_code]` |
| `group_key` siblings dropped | AT-O1b | red: `...[group_key]` |
| declared integers dropped | AT-O1b | red: `...[declared]` |
| `when:`-read columns dropped | AT-O1f | red: `...[plain]` |
| set built by hand in `_chunked_carry.py` | AT-O1e | red: `test_only_allowlisted_functions_call_the_helper[fk_columns_for_table]` |
| new function calls `to_pandas_fk_safe` | AT-O1e | red: `...[to_pandas_fk_safe]` |
| `group_by_sibling` returns `None` | round 2 | red, run without `-x`: plan side `test_the_plan_side_set_names_the_sibling`, config side `test_the_unified_config_set_equals_the_plan_set[group_key-id == 5]`, and the runtime parity tests in `test_group_key_chunked.py` |

Not run: the two test-side mutations the plan names (accept a missing or wrong route witness, drop the fallback assertion). They change the tests, not `src/`, and this script only edits `src/`. They are not claimed as red.

Tests that injected a pandas result through `DataFrame.eval` (non-boolean result, missing numexpr, scope clamps) now use a text or float column, because an integer comparison no longer goes through pandas' evaluator. The evaluator branches they cover are unchanged.

## 3. Coverage limits

- AT-O1f over the gated strategy now runs redact, hash, truncate, text_redact, text_mask and passthrough on text, plus formula, bucket_perturb, fpe and shuffle on a source of their own type. The engine refuses `top_code` and numeric `bucketize` under a `when:` (`top_code_with_when_unsupported`, `gated_string_output_on_numeric_unsupported`), so no cell exists. `date_shift` is the `anchor` class. `derived` needs a second source column and an operation list and has no cell. The chunked oracle leg runs only the chunk-safe members of that list (not formula or shuffle, not text_mask under a `when:`). The plan sentence "every strategy" should say this list.
- The `group_key` native and unified route cells depend on the compiled companion having the raw-hex kernel. The tests now ask `load_compiled_raw_hex_kernel()` (it must load and pass its self-test) instead of `find_spec("decoy_engine_native")`, and expect the oracle and full-frame witnesses when it does not.
- AT-O1e covers the ingestion helpers. A new sentry, `tests/sentry/defects/test_group_by_single_reader.py`, fails on any direct `group_by` read in `execution/` outside `group_by_sibling` and a short exact-identity list (date_shift anchors and config validators, each with a reason).

## 4. Golden inventory (plan 5.6)

No file named in the plan's golden inventory is in this PR's diff against `origin/main`: `testflight/golden_fingerprints.json`, `tests/parity/_f0_expected.py`, `docs/proof-manifest.json`, `docs/capability-matrix.md`, `tests/fileaccess/route_corpus_golden.json`, `tests/native/_c8_iii_a_main_goldens.json`. All are unchanged. The gate run on the final head (`gates.sh --keep-going --baseline`) is the owner of the parity, proof and matrix checks; its result is in the PR description.
