Status: record

# windowed_date batching, S1 benchmark

Slice S1 of the speed batch (`docs/plans/2026-11-19-speed-batch-f1-f3-f4.md`, row GEN-WINDOWED-BATCH).
Candidate: branch `feat/speed-s1-windowed-batch`. Baseline: `origin/main`
75fba3d855d71e3980a62afc3ce7f1187b72073d. Raw numbers: `docs/records/evidence/2026-11-19-windowed-date-batch-s1-bench.json`.

## Conditions

- Node: the Dell WSL2 Linux node through `vm-run engine` with `VMRUN_LINUX=1`, Python 3.10. The plan asks
  for an idle node and one fixed slot. The node was not idle: `node-watch` showed load 30 on 26 threads
  and eight other runs the whole time, and `vm-run` picks the slot. Treat absolute numbers as a loaded
  node. The base and candidate runs were interleaved (base, candidate, base, candidate) to cancel drift.
- Workload A: `tests/perf/test_windowed_date_bench.py`, 200,000 rows, 5% nulls, window -30..90, three
  distributions, ISO strings and `datetime.date` cells. A fresh process per configuration, one untimed
  warm call, seven timed calls. Two rounds per side.
- Workload B: `scripts/fk-scale/bench_worker_gen.py` with the `rep` plan (the pure-generation 1M tier of
  `test_f4a_gen_capacity.py`: 1M `orders` plus 100k `people`, batch 32,768, 1024 MB budget). Three runs per
  side, interleaved. The windowed_date anchor in this plan is a categorical column of ISO date strings.
- Workload C: cProfile of the same generation at 150k rows.

## Workload A, microseconds per row (median, min to max over seven calls)

| Config | Base round 1 | Candidate round 1 | Base round 2 | Candidate round 2 |
|---|---|---|---|---|
| uniform, ISO | 109.8 (106 to 123) | 18.6 (18.1 to 18.8) | 64.5 (62.8 to 77.8) | 25.6 (19.3 to 33.2) |
| early, ISO | 137.1 (112 to 138) | 20.8 (20.6 to 22.5) | 68.3 (67.3 to 75.4) | 21.4 (21.0 to 31.4) |
| late, ISO | 131.6 (102 to 141) | 22.7 (20.1 to 28.0) | 67.7 (66.6 to 70.1) | 21.9 (21.6 to 32.8) |
| uniform, date | 151.0 (144 to 160) | 19.3 (19.1 to 26.1) | 68.5 (63.4 to 76.8) | 23.2 (20.5 to 36.3) |
| early, date | 66.6 (64 to 157) | 20.0 (19.8 to 20.5) | 67.4 (64.6 to 71.4) | 29.1 (23.6 to 38.6) |
| late, date | not recorded (run cut short) | 20.0 (19.7 to 20.9) | 77.5 (66.8 to 85.6) | 28.5 (27.4 to 31.6) |

Base round 1 ran while the node was heavily loaded and the spread is large (the plan's variance rule,
`(max - min) / median > 10%`, fails for several rows on both sides). Round 2 is the quieter pair. Target
for S1: at most 45 us/row for both anchor shapes. The candidate median is at most 29.1 us/row in every
cell of both rounds, so the target holds with margin. The base is 64 to 78 us/row on the quieter round,
not the 132 us/row the plan's probe gave, so the micro-benchmark speedup is about 2.5x to 3.5x, not 7x.

## Workload B, end to end (3 runs each)

| Side | rows/s per run | median rows/s | peak RSS MB per run |
|---|---|---|---|
| Base | 9,205, 9,355, 9,719 | 9,355 | 243.8, 244.0, 236.1 |
| Candidate | 31,870, 28,928, 29,074 | 29,074 | 237.7, 248.2, 246.1 |

Candidate over base: 3.1x at the median (target at least 2x). The candidate spread is
(31,870 - 28,928) / 29,074 = 10.1%, just over the 10% variance rule; the base spread is 5.5%. It was not
rerun on an idle node because none was available. Peak RSS is within +1% of base and under the 500 MB F4a
ceiling. The output digest of every run, base and candidate, is
`015a6a750344cb1dfce47e3fdeb81ae3dcb4a835a1423d03da2c4967892527de`: output bytes are unchanged.

## Workload C, share of generation time (cProfile, 150k rows)

| Side | `apply_windowed_date` cumulative | Total | Share |
|---|---|---|---|
| Base | 20.96 s | 24.50 s | 85.6% |
| Candidate | 7.93 s | 11.71 s | 67.7% |

## S2 decision gate

Run S2 when, after S1, `windowed_date` is still over 50% of pure-generation time or workload B is under
40k rows/s. Both hold (67.7% and 29.1k rows/s), so the gate says S2 runs. The per-row PCG64 draw stays in this slice, and
the profile shows it (`_sample_offset` and the numpy generator setup) as the largest remaining cost.
