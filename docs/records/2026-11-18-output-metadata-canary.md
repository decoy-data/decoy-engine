Status: record

# OUTPUT-METADATA-LEAK E0: the canary matrix

Date: 2026-11-18. Branch `feat/metaleak-e0`, from engine main `ad36687a6`. Plan:
`docs/plans/2026-11-18-output-metadata-leak.md` (revision 3.1), slice E0, section 8.1.

## What was run

`tests/security/test_output_metadata_canary.py` on one Linux node (`VMRUN_LINUX=1 ~/bin/vm-run
engine <worktree> ...`, CPython 3.10 lock venv, pyarrow 24.0.0). Every source carries one canary
per carrier (schema key, key name, pandas `attrs`, column-index name, range-index name, forged
`creator` and `pandas_version`, field metadata and its key name, a nested child field, an
unregistered extension). `canaries_in` looks in the raw bytes, every footer key and value, the
decoded `ARROW:schema` and the parsed pandas blob.

## Matrix

"Leaks" lists the canaries found in the committed output file on the base. Each leaking cell is a
strict xfail; E1 removes the marker.

| Cell | Route and entry | Result on the base |
|---|---|---|
| CE-1 | out-of-core FK, `ParquetTransactionalSink` | leaks ATTRS, COLIDX, CREATOR, PDVER, RIDX, SCHEMA, SKEY |
| CE-2 | full_frame, results published by `publish_tables` | leaks ATTRS |
| CE-2 | sequential, `ParquetTransactionalSink` | leaks ATTRS |
| CE-3 | stream with a sink (lazy sources) | leaks ATTRS, COLIDX, CREATOR, PDVER, RIDX, SCHEMA, SKEY |
| CE-4 | auto-chunk native dispatcher, zero-row chunked | not run: needs the native companion, which no `vm-run` node has (cells skip) |
| CE-5 | resident with a `limit` transform | leaks ATTRS |
| CE-6 | mixed generate and mask | leaks ATTRS |
| CE-6 | isolated (`run_pipeline_isolated`, `output_dir`) | leaks ATTRS |
| CE-6 | F22 `publish_tables`, table straight from a canary source, with a struct child | leaks ATTRS, COLIDX, CREATOR, FIELD, FKEY, NESTED, PDVER, RIDX, SCHEMA, SKEY |
| CE-7 | unregistered extension column, full_frame | leaks ATTRS |
| CE-7 | unregistered extension column, out-of-core | leaks ATTRS, COLIDX, CREATOR, PDVER, RIDX, SCHEMA, SKEY |
| CE-8 | zero-row source, out-of-core | leaks ATTRS, COLIDX, CREATOR, PDVER, RIDX, SCHEMA, SKEY |
| CE-9 | subset (`run_subset`, Polars) | green: no canary |
| CE-10 | no engine CSV writer (AST guard) | green |

## Findings that change the plan's assumptions

- A resident route (full_frame, resident transforms, generate and mask) never writes through the
  sink: the sink is inert unless the run streamed. The plan names `run_pipeline(sink=...)` for
  these cells. They publish the returned tables through `publish_tables` instead, the engine's
  resident publisher. The sequential, stream and out-of-core cells use the sink as planned.
- Single-table jobs are not out-of-core eligible (`no_relationships`), so the extension and
  zero-row out-of-core cells use the FK job.
- Resident routes already drop most metadata through the pandas round trip. Only `attributes`
  survives there. The full set leaks on the out-of-core and stream routes (the carriers of
  section 5.1) and on the unmodified table of `publish_tables`.
- Field metadata (FIELD, FKEY, NESTED) reached an output only where a table is written unchanged.
  An unregistered extension marker did not reach any output (EXT never found), but the cells stay
  as guards.
- The choke point still covers every cell above, so the design in section 4 does not change. The
  list of writers in section 5.3 is complete for the cells run.

## Follow-ups

- CE-4 and the chunked zero-row cell need a node with the native companion. Run them there with
  `pytest tests/security/test_output_metadata_canary.py -rxX` before E1 flips the markers.
- Multi-parent and composite FK out-of-core (section 5.4) are not in E0. They reach the same
  writer as CE-1; E1 adds them when it adds the writer sentry.

## Mutations on the final head

- AT-C0: skipping the `ARROW:schema` decode turns four of the five helper tests red (field,
  nested, extension and table-level cells).
- CE-9: writing the subset table through the Arrow adapter with the source schema attached turns
  the subset cell red (leaks ATTRS, COLIDX, CREATOR, FIELD, FKEY, PDVER, RIDX, SCHEMA, SKEY).
