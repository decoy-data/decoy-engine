### Added (isolated readback memory cap, F25-G7-3, 2026-11-27)

`run_pipeline_isolated` refuses to read a child's staged output back when a strict lower bound on what the driver would then hold is above the host or cgroup memory ceiling. The run ends `crashed` with the new reason `decoy.isolated_readback_capacity_exceeded` (in `CAPACITY_REASON_CODES`), nothing is published and the stage is removed. A run whose bound is at or under the ceiling, or whose ceiling cannot be detected, reads back exactly as before. `IsolatedRunResult.extra["readback"]` carries the figures. `decoy_engine.execution.pipeline` exports `check_readback`, `kill_ceiling` and `INSUFFICIENT`.

#### Memory failure while reading staged output

A memory failure while the driver reads staged output back, including `OSError` with `ENOMEM` and Arrow errors with a known memory marker, now ends the run `crashed` with reason `decoy.process_out_of_memory` and fixed text. It was `decoy.publication_failed`, and a bare `MemoryError` escaped as a raw exception.
