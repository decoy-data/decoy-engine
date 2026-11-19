Status: record

# NONFK-OOM S1: baseline memory of the non-FK full-frame fall-through

Date: 2026-11-19. Plan: `docs/plans/2026-11-19-nonfk-oom.md` section 9 (S1). Base: engine `origin/main`
`75fba3d85`; the numbers below were taken on the S1 branch before any routing change, so every cell is
today's behaviour. Bench: `scripts/bench-auto-chunk/bench_nonfk_fallthrough.py`.

## What was measured

A single non-FK mask table, Parquet in (`LazySource`), Parquet file sink, one thread. The table keeps an
`int64` column with nulls as passthrough, so the chunked gate declines it and the job falls through to the
full-frame route. Every cell reported `execution_mode: full_frame`, `route_reason: no_relationships`,
`loaded_fully_in_memory: true`.

| Workload | Columns |
|---|---|
| W-P | the W2 mix (3 hash, 3 passthrough, 2 redact, 2 truncate) plus `ni`, int64 with nulls, passthrough |
| W-S | W-P plus one `shuffle` column |
| W-U | W-S plus a unique string ID column, hashed |
| W-D | W-S plus two dictionary string columns that share one dictionary across row groups |

Each cell is a fresh process. Peak is `VmHWM` after `run_pipeline` returns; the increment is the peak minus
`VmRSS` right after imports (the kernel high-water mark is reset there). `LB` is `lower_bound_bytes` from
the Parquet footer (rows and schema only, no read). The static estimate is `estimate_peak_bytes(..., "full_frame")`
on the table read whole, taken in a separate process so it never touches a measured run.

## Environment

- Node: GCP `decoy-test-6` (us-east1-b, c3-standard-8, 31 GB RAM, 8 vCPU), Python 3.10 vm-run venv.
- Every worker ran under `systemd-run --user --scope -p MemoryMax=24000000000 -p MemorySwapMax=0`. So the
  kill ceiling `H` in these runs is the 24 GB cap, and `A = 0.85 H` is 20.4 GB. `systemd-run --user --scope`
  with the memory controller works on test-6 and on the Dell WSL2.
- Rounds: n=3 after one warmup at 1M rows; n=1 and no warmup at 10M rows (each 10M cell takes 7 to 8
  minutes, and peak RSS is stable across the 1M rounds, spread under 1 percent of the median).
- The Dell is not a source of any number here. See "Dell reboot".

## Results, 1M rows (n=3, median)

| Workload | LB (bytes) | Static estimate | Peak | Increment (min of 3) | Wall | Peak >= LB | Increment >= LB |
|---|---|---|---|---|---|---|---|
| W-P | 136,000,000 | 3,097,265,312 | 2,416,111,616 | 2,053,541,888 | 44.6 s | yes | yes |
| W-S | 148,000,000 | 3,372,820,324 | 2,519,764,992 | 2,267,840,512 | 45.8 s | yes | yes |
| W-U | 160,000,000 | 3,636,375,884 | 2,839,957,504 | 2,604,040,192 | 59.5 s | yes | yes |
| W-D | 158,000,000 | none | 2,541,010,944 | 2,350,813,184 | 44.5 s | yes | yes |

## Results, 10M rows (n=1)

| Workload | LB (bytes) | Static estimate | Peak | Increment | Wall | Peak >= LB | Increment >= LB |
|---|---|---|---|---|---|---|---|
| W-P | 1,360,000,000 | 29,085,258,760 | 19,874,451,456 | 19,684,614,144 | 400.8 s | yes | yes |
| W-S | 1,480,000,000 | 31,840,813,116 | 21,100,937,216 | 20,911,255,552 | 414.4 s | yes | yes |
| W-U | not recorded | 34,516,368,676 | killed by the cap (exit -9) | none | none | not applicable | not applicable |
| W-D | 1,580,000,000 | none | 21,348,970,496 | 21,159,448,576 | 436.0 s | yes | yes |

## Results, 1M rows, resident input (n=1)

The source is read into memory first (`pq.read_table`, dictionaries unified so chunks share one), so `LB`
uses the real `nbytes` and not the footer floor. Same node and cap, no warmup.

| Workload | LB (bytes) | Peak | Increment | Wall | Peak >= LB | Increment >= LB |
|---|---|---|---|---|---|---|
| W-P | 279,012,530 | 2,380,304,384 | 2,190,704,640 | 48.1 s | yes | yes |
| W-S | 302,901,283 | 2,513,989,632 | 2,324,242,432 | 47.2 s | yes | yes |
| W-U | 323,790,173 | 2,809,913,344 | 2,620,194,816 | 61.7 s | yes | yes |
| W-D | 312,905,203 | 2,414,723,072 | 2,224,902,144 | 58.9 s | yes | yes |

The resident peak matches the lazy peak within 2 percent at 1M, because the full-frame route reads the
lazy table whole before it masks. The bound is about 12 percent of the peak here.

## Reading

- The strict lower bound never exceeded a measured peak, at 1M or 10M, on any workload that finished. It is
  about 5 to 7 percent of the peak, so it is a safe but loose floor. The plan's S1 assumption holds on all
  four workloads, including the unique-ID (W-U) and shared-dictionary (W-D) shapes. No per-type pandas
  width was lowered.
- The full-frame peak is about 8 to 8.5 times the 1M peak at 10x the rows, so memory scales close to
  linearly with rows: roughly 2.0 GB per million rows for W-P and 2.1 GB for W-S and W-D. W-U is higher.
- The static estimate sits above the measured peak on every cell that has both: 1.28 to 1.34 times at 1M
  and 1.46 to 1.51 times at 10M. That matches the plan's "upper-biased" description (FM1: it must never refuse
  on its own). W-D has no estimate, because the estimator cannot price dictionary columns.
- The 10M W-S and W-D peaks (21.1 and 21.3 GB) lie above `A` (20.4 GB) and below `H` (24 GB). So the
  ladder in plan section 4.3 would call them `UNKNOWN`, not refuse them, which is the intended behaviour.

## Before-case (OOM at the cap)

W-U at 10M rows was killed by the 24 GB cgroup cap (`exit_status -9`) on every attempt. It is W-U, not
W-S: W-U is the workload that exceeds the cap on this node. This is today's behaviour for a job that does not
fit: the process dies mid-run with no coded error. The after-case (S5) expects the same job to refuse
with `nonfk_full_frame_capacity_exceeded` before the run, exit code 5, no staging directory. The dedicated
W-S cell with a tighter cap from plan section 9 was skipped on the coordinator's call.

## Not measured

- Probe timing (plan section 14, one probe on W-S at 10M against 5 percent of the run). Deferred to S4b,
  where `probe_peak_bytes` is wired; no one-off timing script was written.
- The 100M-row figure and any run with the compiled companion; these runs used the Python path only.

## Dell reboot

The first 10M attempt ran uncapped on the Dell (WSL2, 44 GB, 8 GB swap, a shared test node). The WSL VM
restarted during it, and two other vm-run jobs on that node were lost. After that every run used the
cgroup cap, and every 10M cell ran on `decoy-test-6` only. The cap turns a full-frame run that exceeds
memory into a killed worker instead of a node failure.

## Reproduce

```text
PYTHONPATH=src python scripts/bench-auto-chunk/bench_nonfk_fallthrough.py drive --out run.json \
    --rows 1000000 10000000 --workloads W-P --rounds 3 --warmup 1 --cgroup-bytes 24000000000
```
