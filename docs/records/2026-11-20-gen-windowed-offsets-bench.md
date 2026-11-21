Status: record

# windowed_date offsets from the index kernel, S2 benchmark

Slice S2 of the speed batch (`docs/plans/2026-11-19-speed-batch-f1-f3-f4.md`, row GEN-WINDOWED-BATCH).
Candidate: branch `feat/gen-windowed-offsets`. Baseline: `origin/main` after S1 (#718), the head the
branch was cut from. Raw numbers: `docs/records/evidence/2026-11-20-windowed-date-offsets-s2-bench.json`.

## Conditions

- Each run measured base and candidate in the same `vm-run` command, interleaved (base, candidate, base,
  candidate; two rounds for workload A, three runs for workload B), from two worktrees of the same snapshot.
- Dell WSL2 node (Linux, 26 threads), no native companion. The node was not idle: load average
  15.4 at the start of workload A and 11.6 at the start of workload B, with other runs on it. `vm-run`
  picks the slot. Treat absolute Dell numbers as a loaded node.
- Mac mini (M4, 10 cores) for the companion run of workload A (companion installed into that slot's
  venv with `uv pip install ./decoy-engine-native`; load average 8.2 at the start) and for a quiet-node run
  of workload B (load average 1.8; that slot had no companion).
- Workload A: `tests/perf/test_windowed_date_bench.py`, 200,000 rows, 5% nulls, window -30..90, three
  distributions, ISO strings and `datetime.date` cells, a fresh process per configuration, one untimed
  warm call, seven timed calls.
- Workload B: `scripts/fk-scale/bench_worker_gen.py --rows 1000000 --plan rep --budget-mb 1024`
  (1M `orders` plus 100k `people`, batch 32,768). The windowed_date anchor in this plan is a categorical
  column of ISO date strings.
- Workload C: cProfile of the same generation at 150k rows.

## Workload A, microseconds per row (median over seven calls; min to max in brackets)

Dell, no companion (reference kernel). Target: at most 20 us/row.

| Config | Base r1 | Cand r1 | Base r2 | Cand r2 |
|---|---|---|---|---|
| uniform, ISO | 27.8 (21.5-33.0) | 6.1 (4.8-7.7) | 24.9 (21.3-29.6) | 7.4 (5.0-8.3) |
| early, ISO | 29.8 (24.7-35.2) | 11.2 (8.6-14.6) | 24.1 (22.3-32.8) | 8.4 (8.3-9.8) |
| late, ISO | 29.7 (27.4-31.0) | 13.1 (12.6-13.9) | 21.8 (20.5-28.9) | 8.2 (8.0-8.4) |
| uniform, date | 22.6 (20.6-29.6) | 4.8 (4.4-5.1) | 22.6 (19.4-26.5) | 4.7 (4.4-8.4) |
| early, date | 28.9 (24.1-32.2) | 12.5 (9.1-13.6) | 28.7 (25.5-32.1) | 8.0 (7.7-10.9) |
| late, date | 28.0 (22.9-29.7) | 10.4 (7.9-11.2) | 25.8 (21.4-31.3) | 10.1 (7.9-12.5) |

Mac, native companion. Target: at most 10 us/row.

| Config | Base r1 | Cand r1 | Base r2 | Cand r2 |
|---|---|---|---|---|
| uniform, ISO | 5.7 | 0.6 | 5.7 | 0.6 |
| early, ISO | 6.2 | 0.7 | 6.2 | 0.7 |
| late, ISO | 6.2 | 0.7 | 6.2 | 0.7 |
| uniform, date | 5.5 | 0.5 | 5.5 | 0.5 |
| early, date | 6.1 | 0.6 | 6.1 | 0.6 |
| late, date | 6.1 | 0.6 | 6.1 | 0.6 |

Both targets hold with margin: the worst candidate cell is 13.1 us/row without the companion (limit 20) and
0.7 us/row with it (limit 10). The Dell variance rule (`(max - min) / median` above 10%) fails for several
cells on both sides because the node was loaded; the maxima are in the table. The Mac spread is under 2%.
The base here is the S1 head, so the micro-benchmark gain over S1 is about 3x without the companion and
about 10x with it. In every run the candidate output equals the oracle that draws one `derive_index` per
row and draw.

## Workload B, end to end (rows/s per run; peak RSS)

| Node | Base | Candidate | Median ratio |
|---|---|---|---|
| Dell, no companion | 36,296 / 30,105 / 28,737 (median 30,105) | 104,116 / 87,797 / 76,944 (median 87,797) | 2.9x |
| Mac, no companion | 156,240 / 153,433 / 152,513 (median 153,433) | 333,651 / 334,431 / 331,696 (median 333,651) | 2.2x |

The plan's S2 target for workload B is at least 4x the base. It is not met: 2.9x on the loaded Dell and
2.2x on the quiet Mac. The Dell spread across three runs is 25% for base and 31% for candidate, so the
10% variance rule fails there; the Mac spread is 2% and 1%. The Mac result is the cleaner one. The
reason is workload C: windowed_date is only part of the time, and the other columns now set the pace.

Peak RSS: Dell 238.1 to 248.0 MB base and 247.6 to 249.6 MB candidate; Mac 246 MB base and 254 MB candidate
(raw `ru_maxrss` 250,496 to 252,096 against 259,936 to 260,480; the Mac reports kilobytes). Both are within
+10% of base and under the 500 MB F4a ceiling. The orders digest is the same in every candidate run
(`97819aa8d0741827...`) and in every base run (`705ed6eb91bdb387...`): output is deterministic across reruns
and differs from base on purpose.

## Workload C, share of generation time (cProfile, 150k rows)

| Node | Side | Total | `apply_windowed_date` cumulative | Share |
|---|---|---|---|---|
| Dell | Base | 12.25 s | 6.32 s | 51.6% |
| Dell | Candidate | 8.02 s | 2.57 s | 32.0% |
| Mac | Base | 2.85 s | 1.26 s | 44.1% |
| Mac | Candidate | 2.21 s | 0.62 s | 28.0% |

windowed_date is still 28 to 32% of pure-generation time after S2. This profile was not split below the
function, so it does not say which part of the remaining cost is the anchor parse, the date arithmetic or
the draw.

## Verdict against the plan's S2 targets

- Workload A, with the companion (at most 10 us/row): met.
- Workload A, without the companion (at most 20 us/row): met.
- Workload B (at least 4x base): not met. Measured 2.9x (Dell) and 2.2x (Mac). The end-to-end ceiling for a
  change to this one column is set by its remaining share of generation time.
- Workload B peak RSS (at most base +10%, under 500 MB): met.
- Workload B ran without the native companion on both nodes, so no end-to-end figure with the companion exists.
