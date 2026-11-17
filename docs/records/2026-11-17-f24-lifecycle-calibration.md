Status: record

# F24 lifecycle estimate: accuracy calibration (84-E1)

Head the cells ran on: `b1213e83a` (source files identical to `f5b26d420`). Run on a Linux test VM
through `vm-run`, one child process per cell, peak RSS from `wait4` `ru_maxrss` outside the
child. The worker reads each source whole, runs `run_pipeline` on the resident tables and writes
every target. It does not pass the vault writer, quarantine path, report flags, resource limits
or the native gate result.

Result: 10 of 14 cells pass. Four cells put the estimate below the measured peak. Under the
plan's rule (FM-12) the slice stops here and the plan is amended; no constant was tuned.

| Cell | Rows | Predicted route | Realized route | Limiting phase | Predicted MB | Measured MB | Ratio | Result |
|---|---|---|---|---|---|---|---|---|
| AT-E1-17 | 1M | full_frame | full_frame | execute | 2156 | 721 | 2.99 | pass (lower) |
| AT-E1-17 | 3M | full_frame | full_frame | execute | 6432 | 1713 | 3.76 | pass (lower) |
| AT-E1-18 | 1M | sequential | out_of_core | execute | 928 | 620 | 1.50 | pass (lower) |
| AT-E1-18 | 3M | sequential | out_of_core | execute | 2435 | 1238 | 1.97 | pass (lower) |
| AT-E1-19 | 1M | sequential | sequential | execute | 285 | 625 | 0.46 | FAIL |
| AT-E1-19 | 3M | sequential | sequential | execute | 456 | 1435 | 0.32 | FAIL |
| AT-E1-23 | 1M | full_frame | full_frame | execute | 383 | 397 | 0.96 | FAIL |
| AT-E1-23 | 3M | full_frame | full_frame | execute | 749 | 793 | 0.95 | FAIL |
| AT-E1-24 | 1M | full_frame | full_frame | execute | 1164 | 652 | 1.78 | pass (lower) |
| AT-E1-24 | 3M | full_frame | full_frame | execute | 3207 | 1646 | 1.95 | pass (lower) |
| AT-E1-25 | 1M | full_frame | full_frame | execute | 1178 | 1078 | 1.09 | pass (lower) |
| AT-E1-25 | 3M | full_frame | full_frame | execute | 3316 | 2634 | 1.26 | pass (lower) |
| AT-E1-27 | 1M | full_frame | full_frame | execute | 794 | 701 | 1.13 | pass (bounded) |
| AT-E1-27 | 3M | full_frame | full_frame | execute | 1983 | 1605 | 1.24 | pass (bounded) |

Phase peaks and wall times per cell are in the `F24_CELL` lines the test prints.

## What the failures show

- AT-E1-19 (numeric FK chain, three tables, sequential, CSV targets): measured peak grows about
  400 MB per million rows; the model predicts 285 MB at 1M and 456 MB at 3M. The execute term
  is the TB-4 sequential model on numeric data and the write phase prices CSV output as a
  pandas frame only. The plan expected this cell on out_of_core; at these row counts the
  router chooses sequential, so the 1.5 bound check was reached on a route the plan did not
  calibrate for numeric data.
- AT-E1-23 (one numeric table, full_frame, Parquet target): 4 to 5 percent below measured at
  both sizes. The plan's TB-4 ratio for this shape was 1.26 to 1.28; the worker's process
  baseline or its resident Arrow copies run above the 200 MiB intercept.
- AT-E1-27 passes, with execute as the limiting phase; the write phase is 596 MB (1M) and
  1388 MB (3M) against 794 and 1983 for execute, so the plan's expected write-limited
  outcome did not occur. Its bound check used the execute phase.
- String cells (17, 18, 24, 25) are above the measured peak everywhere, as the plan expects.
- Realized and predicted routes differ for AT-E1-18 (sequential predicted, out_of_core realized).
