Status: record

# RATCHET-BURNDOWN guard ledger (slice BD-A0)

Date: 2026-11-28. Slice BD-A0 of `docs/plans/2026-11-28-ratchet-moved-keys-and-burndown.md`
(plan branch `plan/ratchet-burndown`, section 13). Docs only: no source or test file changes.

Owner decision, 2026-11-28: "Go with recommended on all ratchet questions". That sets OQ5 to a
reasoned floor per guard, signed in this ledger. Merging this PR signs the targets below.

Counts are entries in the guard's baseline file. Engine counts were read at engine main
`8414da35c`. CLI counts were read at CLI main `4ec3646e` (PR #427 merged) and equal the counts at
`2ca3bbd4`. Every count matches section 13 of the plan except the CLI engine-internal-allow
target (see "Difference from the plan").

Rules for every slice that uses this ledger:

- A target is a ceiling for the end of the owning slice. No baseline gains a key and no allow-list
  gains an entry.
- A slice that cannot reach its target stops and amends this ledger with the reason. It does not
  weaken a test.
- Each removed entry is routed through the guard's owner helper, not deleted by loosening the scan.

## Engine guards in 1.0 slices

| Guard (baseline) | Count | Owner helper | Target | Slice | Owning row |
|---|---|---|---|---|---|
| private-file-sinks | 17 | `open_private`, `precreate_private` (`execution/out_of_core/_scratch.py`), `write_private` (`fileaccess/_private.py`) | 6 or fewer; expected 3 | BD-E1 | RATCHET-BURNDOWN |
| table-kind-truth-tests | 26 modules (41 inline tests) | `generate_columns_of` (`config/_tables.py:485`) | 1 module: `config/_tables.py` | BD-E3 | RATCHET-BURNDOWN |
| lossless-int-columns | 17 | `lossless_int_columns`, `to_pandas_fk_safe` | 3 | BD-E2 | RATCHET-BURNDOWN |

Reasons:

- private-file-sinks. Three entries are the primitives themselves and stay: the quarantine
  `os.open` in `_quarantine_local.py`, `open_private` in `_scratch.py`, and the stage
  `tempfile.mkstemp` in `fileaccess/_local.py`. The other 14 write into an `open_private` or
  `precreate_private` file. That includes the pool-quality spool, which BD-E1 moves onto
  `open_private` so the file is 0600 by construction. The recognition rule in plan section 6.6
  routes those 14. The ceiling stays at 6 so the slice has room if a site does not match the rule.
- table-kind-truth-tests. The owner already moved to `config/_tables.py`. Every other module can
  call `generate_columns_of`. The one remaining module is the owner itself, which keeps its own
  inline test.
- lossless-int-columns. Three entries stay: `fk_columns_for_table` inside `_fk_keys.py` (the owner),
  the `adapter_fk_safe_columns` wrapper in `_chunked_carry.py` (the single carry adapter), and one
  pandas ingestion helper that the 14 other sites call. Slice BD-E2 must keep FK output bytes
  equal (plan test D1). If D1 shows a site cannot route, BD-E2 amends this row with the reason.

## Engine guards left for later amendments

These are not burned in 1.0. Each target is provisional and is confirmed or changed by the amendment
that plans its slice.

| Guard (baseline) | Count | Owner helper | Provisional target | Reason |
|---|---|---|---|---|
| canonical-json-choke-point | 12 | `_canonical` | 0 | every site can call the owner |
| snapshot-parse-single-owner | 11 (16 counting `max`) | `parse_snapshot_json` | 1 | the owner entry stays |
| group-by-single-reader | 6 | `group_by_sibling` | 1 | the owner entry (`execution/_runner.py`) stays |
| date-shift-window-reader | 14 (15 counting `max`) | `shift_window` | 14 | entries name other strategies (text_mask, windowed_date); narrow the scan, do not burn |
| metadata-carrier-allow | 14 | output writer metadata strip | 14 | entries are internal scratch schemas that are never published; narrow the scan |
| parquet-intermediate-writers | 8 (15 counting `max`) | private-file owner (below) | 8 | entries are intermediates read back inside the run; revisit after BD-E1 |
| column-shape-classifier | 6 | `classify_column` | 6 | entries are callers that record shape; no duplicate logic |

## CLI guards in 1.0 slices

| Guard (baseline) | Count | Owner | Target | Slice |
|---|---|---|---|---|
| engine-internal-allow | 10 | engine public API | 3 (the three `ci/engine_logging.py` entries stay) | BD-E4, BD-C2 |
| csv-read-allow | 1 | `cli/_sources.py` | 1 | BD-C1 |
| scan-call-allow | 1 | `cli/scanning/_engine_call.py::scan_descriptors` | 1 | BD-C1 |
| target-writes-allow | 1 | `cli/io/_targets.py` | 1 | BD-C1 |
| config-load-allow | 11 | `decoy._config_file.load_config_mapping` | 11 | BD-C1 |

Reasons:

- engine-internal-allow. Seven `cli/cockpit.py` entries read the live scheme, strategy and
  validator registries because there is no public listing. BD-E4 adds `list_mask_strategies`,
  `checksums.list_schemes` and `validators.list_validators`. BD-C2 then drops all seven after the
  CLI repins to that engine release. The three logging entries stay: the engine has no public
  switch for its file logger.
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
recommendation; `write_private` is already there).

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
logging and seven `cli/cockpit.py`. The three BD-E4 accessors replace all seven cockpit entries
(`SCALAR_HANDLERS` alone is five), so the floor by entry count is 3, not 7. This ledger uses 3.
BD-C2 can confirm this when it runs.
