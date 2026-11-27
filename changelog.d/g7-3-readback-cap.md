### Added (isolated readback memory cap, F25-G7-3, 2026-11-27)

`run_pipeline_isolated` refuses to read a child's staged output back when a strict lower bound on what the driver would then hold is above the host or cgroup memory ceiling. The run ends `crashed` with the new reason `decoy.isolated_readback_capacity_exceeded` (`decoy/isolated_readback_capacity_exceeded`, in `CAPACITY_REASON_CODES`), nothing is published and the stage is removed. A run whose bound is at or under the ceiling, or whose ceiling cannot be detected, reads back exactly as before. `IsolatedRunResult.extra["readback"]` carries the figures. `decoy_engine.execution.pipeline` exports `check_readback`, `kill_ceiling` and `INSUFFICIENT`.

#### Memory failure while reading staged output

A memory failure while the driver reads staged output back, including `OSError` with `ENOMEM` and Arrow errors with a known memory marker, now ends the run `crashed` with reason `decoy.process_out_of_memory` and fixed text. It was `decoy.publication_failed`, and a bare `MemoryError` escaped as a raw exception.

On the isolated route, a memory error once publication may have started reports an unknown publication state (`decoy.process_out_of_memory` with publication state `unknown`). Rerun with the same operation id to confirm. A memory error before that point reports `not_published` and removes the stage. Neither path raises a raw `MemoryError`.

#### One memory boundary on both routes

`run_pipeline_isolated(isolate=False)` returns the same coded memory result as the isolated route: `process_out_of_memory` with publication state `unknown` from just before `publish_resident`, and `not_published` before that when there is no `output_dir`. It no longer lets a raw `MemoryError` escape.

An `ArrowMemoryError` during publication measurement or vault segment decoding is raised like any `MemoryError`. It is no longer reported as a failed receipt or a malformed vault segment. `ParquetTransactionalSink.commit` and `DeliveryStage` raise it, as they already raised a bare `MemoryError`. The reason adapter reports `process_out_of_memory` when classification itself runs out of memory, and a strict file-access policy raises `MemoryError` when rebuilding a scrubbed error runs out of memory. `fileaccess.reraise_memory` is removed.
