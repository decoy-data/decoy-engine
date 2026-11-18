Status: record

# OUTPUT-METADATA-LEAK E0: the canary matrix

Date: 2026-11-18. Branch `feat/metaleak-e0`, from engine main `ad36687a6`. Plan:
`docs/plans/2026-11-18-output-metadata-leak.md` (revision 3.1), slice E0, section 8.1.

## What was run

`tests/security/test_output_metadata_canary.py` on one Linux node (`VMRUN_LINUX=1 ~/bin/vm-run
engine <worktree> ...`, CPython 3.10 lock venv, pyarrow 24.0.0). The auto-chunk cell also ran in a
copy of that venv with the native companion built into it (`decoy-native-abi-3`, built with
`uv pip install ./decoy-engine-native` on the node), because no `vm-run` venv carries the companion.
Without the companion the cell skips.

Every source carries one canary per carrier: schema key, key name, pandas `attrs` (the `attributes`
member of the pandas blob and the separate `PANDAS_ATTRS` footer key that `DataFrame.to_parquet`
writes), column-index name, range-index name, forged `creator` and `pandas_version`, field metadata
and its key name, a nested child field, an unregistered extension. `canaries_in` looks in the raw
bytes, every footer key and value, the decoded `ARROW:schema`, the parsed pandas blob, and reports
`PANDAS_ATTRS` when that footer key is present.

## How a cell is checked

- Route evidence comes from the engine's own result: `execution_mode`, `route_reason` and
  `outputs_streamed` for every `run_pipeline` cell; `auto_chunk.mode`, `lane`, `output.mode` and
  `chunked_route.native_admitted` for the auto-chunk cell; `IsolatedRunResult.isolated` and
  `outcome` for the isolated cell; `output_paths` for subset. A wrong route fails the cell as an
  ordinary failure, never as an xfail.
- Provenance: the files read are the ones the `CommitReceipt` binds (size, rows and sha256 of each
  file equal a receipt artifact), the sink's committed paths, the subset `output_paths`, or the
  isolated commit directory.
- Two tests per route. `test_leak_set_on_base` pins the exact canary set the base leaks, so a
  partial fix fails it until the pin is updated. `test_route_is_clean` is the guarantee, a strict
  xfail that accepts only the leak failure. E1 deletes the pin test and the markers.

## Matrix

"Leaks" is the exact set found in the committed output on the base.

| Cell | Route and entry | Leaks |
|---|---|---|
| CE-1 | out-of-core FK, `ParquetTransactionalSink` | ATTRS COLIDX CREATOR PANDAS_ATTRS PDVER RIDX SCHEMA SKEY |
| CE-2 | full_frame, results published by `publish_tables` | ATTRS |
| CE-2 | sequential (`pure_mask_fk`), sink | ATTRS |
| CE-3 | `stream` with a sink on lazy sources (runs as out-of-core) | same 8 as CE-1 |
| CE-4 | auto-chunk dispatcher, native companion admitted, streamed into a sink | FIELD FKEY |
| CE-5 | resident with a `limit` transform | ATTRS |
| CE-6 | mixed generate and mask | ATTRS |
| CE-6 | isolated child process, `output_dir` commit | ATTRS |
| CE-6 | F22 `publish_tables`, table straight from a canary source, with a struct child | the 8 of CE-1, plus FIELD FKEY NESTED |
| CE-6 | declared casting (a declared date column), out-of-core | same 8 as CE-1 |
| CE-6 | multi-parent FK (two parents, one child column), out-of-core | same 8 as CE-1 |
| CE-6 | composite FK (two key columns), out-of-core | same 8 as CE-1 |
| CE-7 | unregistered extension column, full_frame | ATTRS |
| CE-7 | unregistered extension column, out-of-core | same 8 as CE-1 |
| CE-8 | zero-row source, out-of-core | same 8 as CE-1 |
| CE-8 | zero-row source, `stream` | same 8 as CE-1 |
| CE-9 | subset (`run_subset`, Polars) | none (green) |
| CE-10 | no engine CSV writer (call-resolver guard) | none (green) |

## Findings that change the plan's assumptions

- A resident route (full_frame, resident transforms, generate and mask) never writes through the
  sink: the sink is inert unless the run streamed. The plan names `run_pipeline(sink=...)` for
  these cells. They publish the returned tables through `publish_tables` instead, the engine's
  resident publisher.
- Single-table jobs are not out-of-core eligible (`no_relationships`), so the extension and
  zero-row out-of-core cells use the FK job.
- `execution_mode="stream"` on lazy sources is reported and run as `out_of_core`. It is a second
  entry to the same route, not a separate one.
- The auto-chunk route cannot take a zero-row source: `auto_chunk_threshold_rows` must be a
  positive integer, and a zero-row table is below any threshold. The zero-row chunked cell of the
  plan is not reachable through `run_pipeline`; the CLI chunked writer is covered by CC-3 in C1.
- Resident routes drop most metadata through the pandas round trip. Only `attributes` survives
  there. The full set leaks on the out-of-core and stream routes (the carriers of section 5.1) and
  on the unmodified table of `publish_tables`. The auto-chunk route leaks only passthrough field
  metadata.
- Field metadata (FIELD, FKEY, NESTED) reached an output only where a table is written unchanged
  or passed through the chunked route. An unregistered extension marker (EXT) did not reach any
  output; the cells stay as guards.
- The choke point still covers every cell above, so the design in section 4 does not change. The
  list of writers in section 5.3 is complete for the cells run.

## Mutations on the final head

Each turns its guard red (helper and route tests, run on the node):

- Finder ignores the `PANDAS_ATTRS` key: 2 helper tests red.
- Schema walk drops the dictionary branch: the schema-level dictionary test red.
- Receipt binding not checked: the unbound-file test red.
- Pin set edited (out-of-core FK loses PANDAS_ATTRS): `test_leak_set_on_base` red.
- Wrong expected `route_reason`: both tests of the cell red as plain failures, not xfail.
- CSV scanner finds nothing: 4 seeded spelling cells red.
- Isolated cell run in-process (`isolate=False`): both isolated tests red.
- Auto-chunk threshold above the row count: both auto-chunk tests red (companion venv).
- AT-C0: skipping the `ARROW:schema` decode turns 4 of 5 original helper tests red.
- CE-9: writing the subset output through the Arrow adapter with the source schema attached turns
  the subset cell red.
