Breaking: `ValidatorFinding` gains `failing_row_count` and lists at most `FINDING_INDEX_CAP` (10,000) row positions in `failing_row_indices` (all of them under quarantine `validation_fail`); `ValidationReport` gains `results` and its `elapsed_ms` is the time spent folding rows; `parent_window_respected` parses each date column with the format of its first value that pandas would use, and a parent table without its key or window column raises `ValidatorStateError` instead of a pyarrow `KeyError`.

### Changed (job-level validators are folds with exact counts, EXPECT-OFF-ROUTE S1, 2026-11-23)

Each validator now takes rows span by span and keeps an exact failing count with at most 10,000
listed row positions. The count is `failing_row_count` on every finding. Quarantine
`validation_fail` lists every failing row, because quarantine removes exactly those rows. A
whole-table `validate()` call gives the same findings, wording and order as before for any
finding under the cap. `ValidationReport.results` has one `ValidatorResult` per configured entry
(`passed`, `failed` or `skipped`), and `ValidationSession` is the public way to feed it batches.
The keyed validators (`fk_intact`, `parent_window_respected`, `reconciliation_holds`) accept their
parent and child tables in either order. `parent_window_respected` now guesses one date format
for each column from its first value that is not null or a null string, so a column that mixes formats gives the same
verdict at any chunk size. `leak_check` records every column and table it does not check. Each
skip has a registered code: `warning/leak_check_skip_passthrough`, `warning/leak_check_skip_fk_child`,
`warning/leak_check_skip_when`, `warning/leak_check_skip_exempt`,
`warning/leak_check_skip_missing_column`, `warning/leak_check_skip_below_min_rows` and
`warning/leak_check_skip_table_not_produced`. A column that
`leak_check` names in `columns:` and then skips raises a `QualityWarning`,
`warning/leak_check_column_not_checked`, in `quality_metrics["validation"]["warnings"]`; the run still
passes. The new runtime codes are `runtime/validator_key_state_over_budget` and
`runtime/validator_source_pairing_mismatch`, `runtime/validator_column_missing` (a parent table lacks a key or window column) and `runtime/validator_span_repeated` (a whole-table validator was given a table in several batches), all raised as `ValidatorStateError`. A validator that checked a column or table that is not there now reports it in `ValidatorResult.skipped` with `warning/validator_skip_missing_column` or `warning/validator_skip_missing_table`, and an entry that checked nothing has status `skipped`. No route changes in this
slice.
