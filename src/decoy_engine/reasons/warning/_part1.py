"""Catalog of the ``warning`` namespace, part 1."""

from __future__ import annotations

from decoy_engine.reasons import _catalog
from decoy_engine.reasons._types import UNRELEASED as UNRELEASED

__all__ = [
    "CARDINALITY_COLLISIONS",
    "CARDINALITY_MATCH_DEVIATION",
    "DRIFT_NOT_CHECKED",
    "FIT_JOINT_CELLS_TRUNCATED",
    "FORMAT_RULE_VIOLATION",
    "FPE_JOIN_GROUP_ACTIVE",
    "FPE_PARTIAL_PLAINTEXT_DISCLOSURE",
    "GENERATION_CONDITION_PARENT_UNSEEN",
    "GENERATION_FIDELITY_BELOW_THRESHOLD",
    "GEO_GENERALIZE_CASCADE",
    "JOB_LOG_WRITE_FAILED",
    "LEAK_CHECK_COLUMN_NOT_CHECKED",
    "LEAK_CHECK_SKIP_BELOW_MIN_ROWS",
    "LEAK_CHECK_SKIP_EXEMPT",
    "LEAK_CHECK_SKIP_FK_CHILD",
    "LEAK_CHECK_SKIP_MISSING_COLUMN",
    "LEAK_CHECK_SKIP_PASSTHROUGH",
    "LEAK_CHECK_SKIP_TABLE_NOT_PRODUCED",
    "LEAK_CHECK_SKIP_WHEN",
    "LIBRARY_DEGRADED",
    "LIBRARY_DELETE_SKIPPED",
    "LIBRARY_WRITE_FAILED",
    "MIMESIS_LOCALE_FALLBACK",
    "NATIVE_COMPANION_MISSING",
    "NESTED_CELL_JSON_PARSE_ERROR",
    "NESTED_JSONPATH_PATH_OVERLAP",
    "ORPHAN_FK",
    "OUT_OF_CORE_CALLER_MANAGED_RESIDENCY",
    "POOL_DOMINATES_CACHE",
    "POST_SCAN_OUTPUT_UNREADABLE",
    "REFERENCE_PARENT_POOL_EMPTY",
    "SCAN_BASELINE_MISSING",
    "SCAN_CRASHED",
    "SCAN_HEADER_SUSPECT",
    "SCAN_KEY_TYPE_MISMATCH",
    "SEED_IGNORED_WITH_MASTER_KEY",
    "SFTP_LOCK_NOT_REMOVED",
    "SOURCE_VALUE_LEAK",
    "TEXT_MASK_SUB_FLOOR_SPAN_HANDLED",
    "TOP_CODE_GENERALIZED",
    "UNDECLARED_OUTPUT_COLUMNS",
    "VALIDATOR_SKIP_MISSING_COLUMN",
    "VALIDATOR_SKIP_MISSING_TABLE",
    "VALUE_REUSE_FIXED_POINT",
]

_d = _catalog.warning("QualityWarning")

CARDINALITY_COLLISIONS = _d("cardinality_collisions", "Cardinality collisions.", since="1.30.0")
CARDINALITY_MATCH_DEVIATION = _d("cardinality_match_deviation", "Cardinality match deviation.")
DRIFT_NOT_CHECKED = _d(
    "drift_not_checked",
    "scan_baseline.on_drift is not checked by decoy run yet; the run continues without a drift "
    "check.",
    since="1.33.0",
)
FIT_JOINT_CELLS_TRUNCATED = _d(
    "fit_joint_cells_truncated", "Fit joint cells truncated.", since="1.22.0"
)
FORMAT_RULE_VIOLATION = _d("format_rule_violation", "Format rule violation.")
FPE_JOIN_GROUP_ACTIVE = _d("fpe_join_group_active", "FPE join group active.")
FPE_PARTIAL_PLAINTEXT_DISCLOSURE = _d(
    "fpe_partial_plaintext_disclosure", "FPE partial plaintext disclosure."
)
GENERATION_CONDITION_PARENT_UNSEEN = _d(
    "generation_condition_parent_unseen",
    "Conditional column drew some rows from its overall counts.",
    since="1.22.0",
)
GENERATION_FIDELITY_BELOW_THRESHOLD = _d(
    "generation_fidelity_below_threshold",
    "Generated table scores below the fidelity warn threshold.",
    since="1.22.0",
)
GEO_GENERALIZE_CASCADE = _d("geo_generalize_cascade", "Geo generalize cascade.")
LEAK_CHECK_COLUMN_NOT_CHECKED = _d(
    "leak_check_column_not_checked",
    "A column that leak_check names was not checked, so the check says nothing about it.",
    since="1.35.0",
)
LEAK_CHECK_SKIP_BELOW_MIN_ROWS = _d(
    "leak_check_skip_below_min_rows",
    "leak_check skipped a column with fewer non-null cells than min_rows.",
    since="1.35.0",
)
LEAK_CHECK_SKIP_EXEMPT = _d(
    "leak_check_skip_exempt",
    "leak_check skipped a column the validator lists under params.exempt.",
    since="1.35.0",
)
LEAK_CHECK_SKIP_FK_CHILD = _d(
    "leak_check_skip_fk_child",
    "leak_check skipped a foreign-key child column; its values come from the parent.",
    since="1.35.0",
)
LEAK_CHECK_SKIP_MISSING_COLUMN = _d(
    "leak_check_skip_missing_column",
    "leak_check skipped a column that is missing from the output or the source.",
    since="1.35.0",
)
LEAK_CHECK_SKIP_PASSTHROUGH = _d(
    "leak_check_skip_passthrough",
    "leak_check skipped a column that keeps its source values by design.",
    since="1.35.0",
)
LEAK_CHECK_SKIP_TABLE_NOT_PRODUCED = _d(
    "leak_check_skip_table_not_produced",
    "leak_check skipped a table that this run did not produce.",
    since="1.35.0",
)
LEAK_CHECK_SKIP_WHEN = _d(
    "leak_check_skip_when",
    "leak_check skipped a column that carries a when predicate.",
    since="1.35.0",
)
VALIDATOR_SKIP_MISSING_COLUMN = _d(
    "validator_skip_missing_column",
    "A validator skipped a column that is missing from the table.",
    since="1.35.0",
)
VALIDATOR_SKIP_MISSING_TABLE = _d(
    "validator_skip_missing_table",
    "A validator skipped a table that this run did not produce.",
    since="1.35.0",
)
MIMESIS_LOCALE_FALLBACK = _d("mimesis_locale_fallback", "Mimesis locale fallback.")
NATIVE_COMPANION_MISSING = _d(
    "native_companion_missing",
    "No compiled kernel ran: a native kernel this run needs is not available, so masking ran "
    "in Python.",
    since="1.33.0",
)
NESTED_CELL_JSON_PARSE_ERROR = _d("nested_cell_json_parse_error", "Nested cell JSON parse error.")
NESTED_JSONPATH_PATH_OVERLAP = _d("nested_jsonpath_path_overlap", "Nested jsonpath path overlap.")
ORPHAN_FK = _d("orphan_fk", "Orphan FK.")
OUT_OF_CORE_CALLER_MANAGED_RESIDENCY = _d(
    "out_of_core_caller_managed_residency", "Out of core caller managed residency."
)
POOL_DOMINATES_CACHE = _d("pool_dominates_cache", "Pool dominates cache.")
POST_SCAN_OUTPUT_UNREADABLE = _d(
    "post_scan_output_unreadable",
    "The run wrote to a sink the post-scan gate cannot read back, so declared keys were not "
    "checked on the output.",
    since="1.27.0",
)
REFERENCE_PARENT_POOL_EMPTY = _d(
    "reference_parent_pool_empty",
    "Reference column is null because its parent column has no keys.",
    since="1.32.0",
)
# SCAN-CHECKS: `--evidence-out` asked to hash the pipeline's scan baseline and the file is gone. The
# run continues and the manifest records the path with a null fingerprint. Fixed, value-free text.
SCAN_BASELINE_MISSING = _catalog.warning("EvidenceManifest")(
    "scan_baseline_missing",
    "The scan baseline file could not be read, so the evidence manifest has no fingerprint for it.",
    since="1.30.0",
)
SCAN_CRASHED = _d("scan_crashed", "Scan crashed.")
SCAN_HEADER_SUSPECT = _d(
    "scan_header_suspect", "First row looks like data, not a header.", since="1.10.0"
)
SCAN_KEY_TYPE_MISMATCH = _d(
    "scan_key_type_mismatch", "Relationship key columns differ in type.", since="1.10.0"
)
SEED_IGNORED_WITH_MASTER_KEY = _d(
    "seed_ignored_with_master_key",
    "The job seed is not used for generated tables when a master key is set.",
    since="1.22.0",
)
SOURCE_VALUE_LEAK = _d("source_value_leak", "Source value leak.")
TEXT_MASK_SUB_FLOOR_SPAN_HANDLED = _d(
    "text_mask_sub_floor_span_handled", "Text mask sub floor span handled."
)
TOP_CODE_GENERALIZED = _d("top_code_generalized", "Top code generalized.")
UNDECLARED_OUTPUT_COLUMNS = _d("undeclared_output_columns", "Undeclared output columns.")
VALUE_REUSE_FIXED_POINT = _d("value_reuse_fixed_point", "Value reuse fixed point.")

# Events the CLI builds around the local record library; they are registered here because an
# unregistered code reaches the wire as `unregistered_reason`.
_d = _catalog.warning("LibraryEvent")

JOB_LOG_WRITE_FAILED = _d("job_log_write_failed", "Job log write failed.", since="1.20.0")
LIBRARY_DEGRADED = _d("library_degraded", "Library degraded.", since="1.20.0")
LIBRARY_DELETE_SKIPPED = _d("library_delete_skipped", "Library delete skipped.", since="1.20.0")
LIBRARY_WRITE_FAILED = _d("library_write_failed", "Library write failed.", since="1.20.0")
_d = _catalog.warning("ConnectorEvent")

SFTP_LOCK_NOT_REMOVED = _d(
    "sftp_lock_not_removed",
    "An SFTP lock file could not be removed after a run.",
    since="1.30.0",
)
