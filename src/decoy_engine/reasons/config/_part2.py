"""Catalog of the ``config`` namespace, part 2."""

from __future__ import annotations

from decoy_engine.reasons import _catalog
from decoy_engine.reasons._types import UNRELEASED

__all__ = [
    "CANONICAL_JSON_INVALID_STRING",
    "COLUMN_DUPLICATE",
    "CONFIG_VALUE_NOT_JSON",
    "DECLARED_TABLE_DROPPED",
    "ENTRY_INVALID",
    "ENV_FLAG_INVALID",
    "GENERATE_AGGREGATE_INPUT_NOT_NUMERIC",
    "GENERATE_AGGREGATE_READ_BEFORE_FILL",
    "GENERATE_COLUMN_DUPLICATE",
    "GENERATE_FITTED_REFERENCE_BOUNDS_CONFLICT",
    "GENERATE_FORMULA_INVALID",
    "GENERATE_OPTION_RANGE",
    "GENERATE_OPTION_TYPE",
    "GENERATE_OPTION_UNKNOWN",
    "GENERATE_OPTION_VALUE_UNKNOWN",
    "GENERATE_OUTPUT_TYPE_UNSUPPORTED",
    "GENERATE_PARENT_LOOKUP_KEY_NOT_UNIQUE",
    "GENERATE_PARENT_LOOKUP_SELF_REFERENCE",
    "GENERATE_PER_PARENT_BOUNDS_CONFLICT",
    "GENERATE_PER_PARENT_INFEASIBLE",
    "GENERATE_PER_PARENT_NULL_CONFLICT",
    "GENERATE_SELF_REFERENCE_KEY_INVALID",
    "GENERATE_SELF_REFERENCE_OPTION_UNSUPPORTED",
    "GENERATE_UNIQUE_CONFLICT",
    "GENERATE_UNIQUE_DOMAIN_TOO_SMALL",
    "GENERATE_UNIQUE_UNSUPPORTED",
    "GENERATE_WEIGHTS_INVALID",
    "KEY_COLUMN_NOT_JOIN_SAFE",
    "LOADER_TABLE_UNDECLARED",
    "NAMESPACE_PLACEHOLDER_UNSET",
    "PIPELINE_NAME_INVALID",
    "POLICY_BLOCK_INVALID",
    "POLICY_COLUMN_PARTIAL",
    "POLICY_FIELD_UNDECIDED",
    "POLICY_PROHIBITED",
    "POLICY_RULE_CONFLICT",
    "POLICY_SELECTOR_INVALID",
    "POLICY_SELECTOR_UNMATCHED",
    "POLICY_UNKNOWN_CLASSIFICATION",
    "POLICY_UNKNOWN_STRATEGY",
    "REMOTE_URI_INVALID",
    "SCAN_BASELINE_UNBOUND",
    "TABLE_DUPLICATE",
    "TARGET_SHARED_DESTINATION",
    "VARIABLE_UNKNOWN_SCOPE",
    "VARIABLE_UNRESOLVED",
]

_d = _catalog.config("decoy_engine.validation_result")

VARIABLE_UNKNOWN_SCOPE = _d("variable.unknown_scope", "Variable unknown scope.")
VARIABLE_UNRESOLVED = _d("variable.unresolved", "Variable unresolved.")

# Summaries double as the refusal text the config layer shows, so they never name a value.
_d = _catalog.config("CanonicalJsonError")

CANONICAL_JSON_INVALID_STRING = _d(
    "canonical_json_invalid_string",
    "Canonical JSON strings must contain only Unicode scalar values.",
    since="1.27.0",
)
CONFIG_VALUE_NOT_JSON = _d(
    "config_value_not_json",
    "A config value has a type JSON cannot hold; quote it as a string.",
    since="1.27.0",
)

_d = _catalog.config("PipelineValidationError")
TARGET_SHARED_DESTINATION = _d(
    "target_shared_destination",
    "Two or more targets write to one destination. Give each table its own target.",
    since="1.28.0",
)
COLUMN_DUPLICATE = _d(
    "column_duplicate",
    "Two columns in one table have the same name. List each column once.",
    since="1.32.0",
)
TABLE_DUPLICATE = _d(
    "table_duplicate",
    "Two tables in one config have the same name. Declare each table once.",
    since="1.32.0",
)
GENERATE_AGGREGATE_INPUT_NOT_NUMERIC = _d(
    "generate_aggregate_input_not_numeric",
    "Generate per-parent aggregate reads a child column that is not numeric; give it a numeric "
    "output_type or aggregate a numeric column.",
    since="1.32.0",
)
GENERATE_AGGREGATE_READ_BEFORE_FILL = _d(
    "generate_aggregate_read_before_fill",
    "Generate column reads a per-parent aggregate, which is filled only after every table exists.",
    since="1.32.0",
)
GENERATE_COLUMN_DUPLICATE = _d(
    "generate_column_duplicate",
    "Two generate columns in one table have the same name.",
    since="1.13.0",
)
GENERATE_FITTED_REFERENCE_BOUNDS_CONFLICT = _d(
    "generate_fitted_reference_bounds_conflict",
    "Generate reference column per-parent bounds cannot be combined with distribution fitted.",
    since="1.32.0",
)
GENERATE_FORMULA_INVALID = _d(
    "generate_formula_invalid",
    "Generate column formula is not a valid expression.",
    since="1.13.0",
)
GENERATE_OPTION_RANGE = _d(
    "generate_option_range",
    "Generate column option is outside its allowed range.",
    since="1.13.0",
)
GENERATE_OPTION_TYPE = _d(
    "generate_option_type",
    "Generate column option has the wrong type.",
    since="1.13.0",
)
GENERATE_OPTION_UNKNOWN = _d(
    "generate_option_unknown",
    "Generate column option is not known for this column type.",
    since="1.13.0",
)
GENERATE_OPTION_VALUE_UNKNOWN = _d(
    "generate_option_value_unknown",
    "Generate column option value is not one of the allowed choices.",
    since="1.13.0",
)
GENERATE_OUTPUT_TYPE_UNSUPPORTED = _d(
    "generate_output_type_unsupported",
    "Generate column type or target cannot carry the requested output type.",
    since="1.23.0",
)
GENERATE_PARENT_LOOKUP_KEY_NOT_UNIQUE = _d(
    "generate_parent_lookup_key_not_unique",
    "Generate column reads a parent row through a column that is not a reference to a sequence "
    "key with no null_probability.",
    since="1.32.0",
)
GENERATE_PARENT_LOOKUP_SELF_REFERENCE = _d(
    "generate_parent_lookup_self_reference",
    "Generate column reads a parent row through a reference to its own table.",
    since="1.32.0",
)
GENERATE_PER_PARENT_BOUNDS_CONFLICT = _d(
    "generate_per_parent_bounds_conflict",
    "Generate reference column min_per_parent is greater than its max_per_parent.",
    since="1.32.0",
)
GENERATE_PER_PARENT_INFEASIBLE = _d(
    "generate_per_parent_infeasible",
    "Generate reference column per-parent bounds cannot hold for its parent keys and row count.",
    since="1.32.0",
)
GENERATE_PER_PARENT_NULL_CONFLICT = _d(
    "generate_per_parent_null_conflict",
    "Generate column null_probability cannot be combined with a per-parent option.",
    since="1.32.0",
)
GENERATE_SELF_REFERENCE_KEY_INVALID = _d(
    "generate_self_reference_key_invalid",
    "Generate self-reference column must name an earlier sequence column of its own table with "
    "no null_probability.",
    since="1.32.0",
)
GENERATE_SELF_REFERENCE_OPTION_UNSUPPORTED = _d(
    "generate_self_reference_option_unsupported",
    "Generate self-reference column takes distribution random and an optional max_per_parent only.",
    since="1.32.0",
)
GENERATE_UNIQUE_CONFLICT = _d(
    "generate_unique_conflict",
    "Generate column unique cannot be combined with another option on the same column.",
    since="1.17.0",
)
GENERATE_UNIQUE_DOMAIN_TOO_SMALL = _d(
    "generate_unique_domain_too_small",
    "Generate column unique needs more distinct values than its domain holds.",
    since="1.17.0",
)
GENERATE_UNIQUE_UNSUPPORTED = _d(
    "generate_unique_unsupported",
    "Generate column type does not support unique.",
    since="1.17.0",
)
GENERATE_WEIGHTS_INVALID = _d(
    "generate_weights_invalid",
    "Generate column weights must be non-negative numbers with a positive total.",
    since="1.13.0",
)
PIPELINE_NAME_INVALID = _d(
    "pipeline_name_invalid",
    "Pipeline name must be 1 to 64 letters, digits, dot, dash or underscore, start with a letter or "
    "digit, not end in a dot and not be a Windows device name.",
    since="1.12.0",
)

# The variable name is a fixed engine constant; the refusal text never carries the value read.
_d = _catalog.config("EnvFlagError")

ENV_FLAG_INVALID = _d(
    "env_flag_invalid",
    "An environment flag has a value outside the accepted spellings.",
    since="1.27.0",
)

# A table whose strategies sit under `tables:` must reach the plan. The two refusals below keep a
# declared table from being echoed unmasked; texts name the table (a config key), never a value.
_d = _catalog.config("ConfigError")

LOADER_TABLE_UNDECLARED = _d(
    "loader_table_undeclared",
    "A table masked through a source loader needs a sources entry; without one the run would "
    "pass its rows through unmasked.",
    since="1.27.0",
)
DECLARED_TABLE_DROPPED = _d(
    "declared_table_dropped",
    "A table declared under tables has no work in the compiled plan; the run would pass its "
    "rows through unmasked.",
    since="1.27.0",
)

# The placeholder a starter pipeline writes where a declared relationship named no namespace.
# The text never carries the submitted value; the error location names the field.
NAMESPACE_PLACEHOLDER_UNSET = _d(
    "namespace_placeholder_unset",
    "A namespace still holds the placeholder a starter pipeline writes; set a real namespace.",
    since="1.27.0",
)

# Pipeline `policy` block refusals. Summaries name no config value; the error text adds rule ids
# and `table.column` names only.
_d = _catalog.config("PipelineValidationError")

POLICY_SELECTOR_INVALID = _d(
    "policy_selector_invalid",
    "A policy selector is empty, has an unknown key or holds a value outside the grammar.",
    since="1.30.0",
)
POLICY_UNKNOWN_CLASSIFICATION = _d(
    "policy_unknown_classification",
    "A classification is not one the engine knows.",
    since="1.30.0",
)
POLICY_UNKNOWN_STRATEGY = _d(
    "policy_unknown_strategy",
    "A policy names a masking strategy the engine does not know.",
    since="1.30.0",
)
POLICY_SELECTOR_UNMATCHED = _d(
    "policy_selector_unmatched",
    "A policy rule selects no mask column.",
    since="1.30.0",
)
POLICY_RULE_CONFLICT = _d(
    "policy_rule_conflict",
    "Two policy sources decide one column differently at the same precedence level.",
    since="1.30.0",
)
POLICY_FIELD_UNDECIDED = _d(
    "policy_field_undecided",
    "No policy level decides a mask column.",
    since="1.30.0",
)
POLICY_COLUMN_PARTIAL = _d(
    "policy_column_partial",
    "A column without a strategy sets keys that only a strategy can use.",
    since="1.30.0",
)
POLICY_BLOCK_INVALID = _d(
    "policy_block_invalid",
    "The policy block has a duplicate id, a prohibition without exactly one of forbid and "
    "require, or a value JSON cannot carry.",
    since="1.30.0",
)
POLICY_PROHIBITED = _d(
    "policy_prohibited",
    "A mask column's decided strategy breaks a policy prohibition.",
    since="1.30.0",
)
SCAN_BASELINE_UNBOUND = _d(
    "scan_baseline_unbound",
    "scan_baseline.on_drift: fail needs scan_baseline.sha256, so the baseline is bound.",
    since="1.30.0",
)

_d = _catalog.config("ConfigError")

REMOTE_URI_INVALID = _d(
    "remote_uri_invalid",
    "A remote source argument is not a valid s3://, gs:// or sftp:// URI.",
    since="1.30.0",
)

# INIT-WIZARD E1: the review's entry writer and its key-column rule. Both are repaired by the
# caller's input and name a column or an option key, never a value.
_d = _catalog.config("ReviewInputError")

ENTRY_INVALID = _d(
    "entry_invalid",
    "A column entry names an unknown strategy or option, or gives an option the wrong type or "
    "a value outside its choices, or leaves a required setting out.",
    since="1.31.0",
)
KEY_COLUMN_NOT_JOIN_SAFE = _d(
    "key_column_not_join_safe",
    "A column of a declared relationship cannot take a strategy that is not join-safe, or be "
    "dropped.",
    since="1.31.0",
)
