Status: record

# RATCHET-BURNDOWN guard ledger (slice BD-A0)

Date: 2026-11-28. Slice BD-A0 of `docs/plans/2026-11-28-ratchet-moved-keys-and-burndown.md`
(plan branch `plan/ratchet-burndown`, section 13). Docs only: no source or test file changes.

Owner decision, 2026-11-28: "Go with recommended on all ratchet questions". That sets OQ5 to a
reasoned floor per guard, signed in this ledger. Merging this PR signs the targets below.

Counts are entries in the guard's baseline file. Engine counts were read at engine main
`8414da35c`. CLI counts were read at CLI main `4ec3646e` (PR #427 merged) and equal the counts at
`2ca3bbd4`. Every count matches section 13 of the plan. Three targets differ from it: CLI
engine-internal-allow, private-file-sinks and lossless-int-columns (see "Difference from the plan").

Rules for every slice that uses this ledger:

- A target is a ceiling for the end of the owning slice. No baseline gains a key and no allow-list
  gains an entry.
- A slice that cannot reach its target stops and amends this ledger with the reason. It does not
  weaken a test.
- Each removed entry is routed through the guard's owner helper, not deleted by loosening the scan.

## Engine guards in 1.0 slices

| Guard (baseline) | Count | Owner helper | Target | Slice | Owning row |
|---|---|---|---|---|---|
| private-file-sinks | 17 | `open_private`, `precreate_private` (`execution/out_of_core/_scratch.py`), `write_private` (`fileaccess/_private.py`) | 14 | BD-E1 | RATCHET-BURNDOWN |
| table-kind-truth-tests | 26 modules (41 inline tests) | `generate_columns_of` (`config/_tables.py:485`) | 1 module: `config/_tables.py` | BD-E3 | RATCHET-BURNDOWN |
| lossless-int-columns | 17 | `lossless_int_columns`, `to_pandas_fk_safe` | 5 | BD-E2 | RATCHET-BURNDOWN |

Reasons:

- private-file-sinks. Three entries are the primitives themselves and stay: the quarantine
  `os.open` in `_quarantine_local.py`, `open_private` in `_scratch.py`, and the stage
  `tempfile.mkstemp` in `fileaccess/_local.py`. The other 14 write into an `open_private` or
  `precreate_private` file. The recognition rule in plan section 6.6 routes a write only when its
  sink is a `Name` bound exactly once by `open_private` (or its path is a `Name` bound exactly
  once by `precreate_private`) and is passed directly to the writer. Checked against engine main:
  - Routed, 3 entries. The pool-quality spool (`measure_pool_quality`), which BD-E1 moves onto
    `open_private`, and the two `pa.ipc.new_file` writes in `_external_sort.py` (`_write_run`,
    `_merge_group`), whose sink is the `with open_private(...) as sink` name.
  - Not routed by the rule as written, 11 entries. Three IPC writers in `_payload_store.py`
    (`RawParentKeySpill.__init__`, `SpillChildKeys.__init__`, `SpillPayloadStore.append`) pass the
    attribute `self._sink`, which is not a `Name`. Six DuckDB COPY calls in `_multi_parent.py` and
    `_relation.py` wrap `precreate_private(...)` in `_sql_string(...)` or pass it inline in the
    parameter list, so the path is not a `Name` bound once. Two `pq.ParquetWriter` calls in
    `stage_typed_sources` (`_stream.py`) take a `sink` that is first bound to `None` and then to
    `open_private(...)`, so it is bound twice.
  Remaining by the rule as written: 3 primitives + 11 not routed = 14. The target is 14.
  Fewer than 14 needs call-site rewrites that BD-E1 does not plan: a local handle in each payload
  store, a `Name` bound once to each `precreate_private(...)` result, and no `None` pre-binding of
  `sink`. If BD-E1 does those rewrites it amends this row with the new count. It does not widen
  the rule to reach a lower number.
- table-kind-truth-tests. The owner already moved to `config/_tables.py`. Every other module can
  call `generate_columns_of`. The one remaining module is the owner itself, which keeps its own
  inline test.
- lossless-int-columns. Keys are `helper::path::caller`, so a site leaves the baseline only when it
  stops naming the helper. Five entries stay:
  1. `fk_columns_for_table::execution/_fk_keys.py::lossless_int_columns`, the owner.
  2. `lossless_int_columns::execution/_chunked_carry.py::adapter_fk_safe_columns`, the single
     carry adapter.
  3. `lossless_int_columns_from_config::execution/_unified_slice_admission.py::cheap_admission`.
     Admission runs on the config before a compiled plan exists, so it cannot take the adapter's
     set.
  4. `to_pandas_fk_safe::execution/_unified_slice_admission.py::cheap_admission`. The same
     function converts the frame it admits.
  5. One existing `to_pandas_fk_safe` caller that BD-E2 designates as the ingestion helper the
     other sites call. BD-E2 must pick a function already in the baseline, because no baseline
     gains a key. The candidate is `to_transform_frame` in `execution/_transforms_table.py`.
  The other 12 entries are the `PandasExecutionAdapter.run` and `run_sequential` pairs, the three
  `adapter_fk_safe_columns` callers, and the remaining `to_pandas_fk_safe` callers. They route to
  entries 2 and 5. Slice BD-E2 must keep FK output bytes equal (plan test D1). If D1 shows a site
  cannot route, or no existing function can act as the helper, BD-E2 amends this row with the
  reason and the new count.

## Engine guards left for later amendments

These are not burned in 1.0. Each target is provisional and is confirmed or changed by the amendment
that plans its slice.

| Guard (baseline) | Count | Owner helper | Provisional target | Reason |
|---|---|---|---|---|
| canonical-json-choke-point | 12 | `_canonical` | 4 | four sites write indented stored documents for people (`profiling/model_pack/_packio.py::write_json`, `provenance.py::sign_pack`, `trainer.py::train_and_evaluate`, `subset/_api.py::run_subset`); the owner has no indent form. The other eight (stored lines, cache keys, executed payloads) are candidates to burn |
| snapshot-parse-single-owner | 11 (16 counting `max`) | `parse_snapshot_json` | 2 | the owner entry and `quality/dp_provenance.py::assert_lock_matches_installed`, which loads the TOML lock file (a TOML reader, not JSON) |
| group-by-single-reader | 6 | `group_by_sibling` | 3 | the owner entry (`execution/_runner.py`) and the two config-rejection readers in `execution/native/_operator_config_rejections.py` (`date_shift_config_rejection`, `group_key_config_rejection`), which validate the raw value to report the exact rejection reason |
| date-shift-window-reader | 14 (15 counting `max`) | `shift_window` | 14 | entries name other strategies (text_mask, windowed_date); narrow the scan, do not burn |
| metadata-carrier-allow | 14 | `attach_output_metadata` (`safe_output/_file_metadata.py`) | 14 | entries are internal scratch schemas that are never published, reuse of a schema that already went through `attach_output_metadata` (`_chunked_output_sink.py::_cast`, `_emit.py::reconcile_batch`, `_stream_join.py::_with_positional_row_nr`), or array casts to a type that the rule matches by mistake (`_emit.py::_fk_resident_column`, `_merged_column`, `_relation.py::_cast_masked_array`); narrow the scan, do not burn |
| parquet-intermediate-writers | 8 (15 counting `max`) | `write_output_table` and `output_parquet_writer` (`fileaccess/adapters/arrow.py`) own published Parquet; `fileaccess/_private.py` is not an owner here | 8 | entries are intermediates read back inside the run, never published; they stay outside the Arrow writers by design. Revisit after BD-E1 |
| column-shape-classifier | 6 | `classify_column` | 6 | entries are callers that record shape; no duplicate logic |

## CLI guards in 1.0 slices

| Guard (baseline) | Count | Owner | Target | Slice |
|---|---|---|---|---|
| engine-internal-allow | 10 | engine public API | 3 if BD-E4 meets the condition below, else 7 (the three `ci/engine_logging.py` entries stay) | BD-E4, BD-C2 |
| csv-read-allow | 1 | `cli/_sources.py` | 1 | BD-C1 |
| scan-call-allow | 1 | `cli/scanning/_engine_call.py::scan_descriptors` | 1 | BD-C1 |
| target-writes-allow | 1 | `cli/io/_targets.py` | 1 | BD-C1 |
| config-load-allow | 11 | `decoy._config_file.load_config_mapping` | 11 | BD-C1 |

Reasons:

- engine-internal-allow. Seven `cli/cockpit.py` entries read the live registries because there is
  no public listing: four for `SCALAR_HANDLERS` (the name, `.get`, `.items`, `.keys`), one for
  checksum `_KNOWN_SCHEMES`, two for validator `_REGISTRY` (the name, `.keys`). What each prints
  decides what replaces it.
  - `decoy list checksums` and `decoy list validators` print sorted names and a count. The BD-E4
    accessors `checksums.list_schemes` and `validators.list_validators` keep that output, so
    those three entries go.
  - `decoy list strategies`, `decoy show strategy` and `explain transforms` print the handler
    class name, and `show strategy` also prints the handler module and the first docstring line.
    A names-only `list_mask_strategies` cannot keep that output. Engine main already exports
    `strategy_catalog()`, but its `StrategyInfo` rows hold the name, options and requirements, not
    the class, module or summary.
  The four `SCALAR_HANDLERS` entries are therefore removed only if BD-E4 ships
  `list_mask_strategies` returning, per strategy, the name, the handler class name, the handler
  module and the docstring summary, and BD-C2 shows `list strategies` and `show strategy` output
  (table and `--json`) unchanged. With that, the target is 3. If BD-E4 ships names only, the
  four entries stay and the target is 7. BD-C2 reads which case applies and records it here.
  The three logging entries stay in both cases: the engine has no public switch for its file
  logger.
- csv-read-allow (`cli/gen/_fit.py::read_fit_csv`). A caller-named file with its own parse flags;
  not a declared source. Stays.
- scan-call-allow (`cli/init.py::_scaffold_from_file`). `decoy init` profiles its input for
  strategy inference. The init wizard is stopped (owner, 2026-11-19), so this stays.
- target-writes-allow (`api.py::_stage_source_entry`). Spools in-memory `data=` to a private temp
  Parquet read back as a source; not a target write. Stays.
- config-load-allow. All 11 entries are other kinds of input, each named in the sentry's `KINDS`
  table: CI manifest, source index, policy file, fixed-width layout file, user-editable project
  marker, and CLI-written text (six entries). None is a user pipeline config, so none routes
  through `load_config_mapping`. BD-C1 re-checks each reason against current code and records any
  that now route. The target stays 11 until that check finds one.

Plan section 13 listed these four CLI allow-lists as "named in BD-A0, set in BD-A0". This ledger
names the owners above. BD-C1 is a check-and-confirm slice unless it finds a site that routes.

## Private-file owner

The one private-file owner is `src/decoy_engine/fileaccess/_private.py` (the plan's
recommendation; `write_private` is already there). It owns private files only. It is not the
owner of published Parquet: `write_output_table` and `output_parquet_writer` in
`fileaccess/adapters/arrow.py` are, because they apply the output-metadata rules that private
file creation does not.

Today the private helpers are split across two modules: `open_private` and `precreate_private` in
`execution/out_of_core/_scratch.py`, and `write_private` in `fileaccess/_private.py`. The move is
a follow-up item, not 1.0 work. BD-E1 uses `open_private` where it is today. The recognition rule
keys on the helper name, so the later move needs only an import change.

Follow-up: consolidate `open_private` and `precreate_private` into `fileaccess/_private.py`. It is
not scheduled and has no row yet.

## Out of scope

- Census baselines and F31-owned lists.
- Engine module-size: deferred to STRUCTURE-REVIEW in 1.x (OQ3, decided 2026-11-28).
- Outbound-text guards (engine-exception-text-copies, config-refusal-text, CLI one-error-emitter,
  engine-reason-code-copies): F31-AUDIT.
- CLI gate-single-entry-allow (CONFIG-EXPLICIT C2) and CLI private-file-sinks (WIN-FEAS).

## Difference from the plan

Plan section 13 gives the CLI engine-internal-allow target as 7. The baseline has 10 entries: three
logging and seven `cli/cockpit.py`. This ledger sets 3, conditional on BD-E4 shipping a strategy
accessor that keeps the class, module and summary output (see the reasons above). If it does not,
the target is the plan's 7.

Plan section 13 gave a target of 6 or fewer, expected 3, for private-file-sinks, and 3 for
lossless-int-columns. This ledger sets 14 and 5, from the call-site check above. Neither is
above its current count of 17.
