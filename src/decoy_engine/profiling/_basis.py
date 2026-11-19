"""What a profile number was counted over: the basis rule, the key rule and the field registry.

A profile built from a prefix of a table has null and distinct counts of that prefix. Three
facts say what a number covers, and each lives here once:

- `read_basis` decides `whole` or `sample` from the strategy, the cap and whether the read proved
  it reached the end of the source (the `ProfileSource.sample_frame` contract in `profile/`).
- `claim_keys` is the only place a key is claimed, and only from a `whole` read.
- `FIELD_BASIS` gives every field of every profile output type one `BasisClass`, so a new field
  cannot land without a decision about what it was counted over. A sentry walks the three roots
  and compares them with this mapping.

At run time this module imports only `enum`, `types` and `typing`: `profiling.types` and
`profiling._scan_core` import `Basis` from it, and planner types are named by string.
"""

from __future__ import annotations

import types
from enum import Enum
from typing import TYPE_CHECKING, Final, Literal

if TYPE_CHECKING:
    from decoy_engine.profiling.types import ColumnProfile

__all__ = [
    "CARRIERS",
    "FIELD_BASIS",
    "Basis",
    "BasisClass",
    "claim_keys",
    "key_claim_allowed",
    "read_basis",
]

Basis = Literal["whole", "sample"]


def read_basis(strategy: str, cap: int | None, reached_end: bool) -> Basis:
    """`whole` when every row of the source was read, else `sample`.

    A full strategy or no cap reads everything. Otherwise only `reached_end` (the caller saw the
    source end before the cap) proves it.
    """
    return "whole" if strategy == "full" or cap is None or reached_end else "sample"


def key_claim_allowed(whole: bool, claimed: bool) -> bool:
    """The one key rule: a key claim needs a whole read; an empty claim is always fine.

    The scan, the persisted scan core (write and read) and the planner profile all call it, so
    "no key from a sample" has one definition.
    """
    return whole or not claimed


def claim_keys(profile: ColumnProfile) -> tuple[str, ...]:
    """Columns that are keys: no nulls and all values distinct, claimed from a whole read only."""
    scanned = profile.row_count
    if scanned <= 0 or not key_claim_allowed(profile.basis == "whole", True):
        return ()
    return tuple(
        f.name for f in profile.fields if f.null_count == 0 and f.distinct_count == scanned
    )


class BasisClass(Enum):
    """How a field relates to the rows a profile scanned."""

    SCANNED = "scanned"  # counted over the scanned rows; the carrier says how many
    SOURCE = "source"  # a fact of the whole source, with its own label
    CHECKED = "checked"  # a claim that needs exact counts; empty unless the basis is whole
    LABEL = "label"  # identity, configuration or metadata


_Key = tuple[str, str, str]


def _entries(root: str, type_name: str, **groups: str) -> dict[_Key, BasisClass]:
    """`groups` maps a class name to the space-separated field names that have it."""
    return {
        (root, type_name, name): BasisClass[group.upper()]
        for group, names in groups.items()
        for name in names.split()
    }


_DOCUMENT = (
    _entries(
        "document",
        "ColumnProfile",
        scanned="reid_risk_columns reid_risk_score quasi_identifier_groups k_anonymity",
        label="source_label row_count sample_strategy sample_row_cap fields basis "
        "engine_version generated_at",
    )
    | _entries(
        "document",
        "FieldStats",
        label="name row_count dtype_raw",
        scanned="inferred_type null_count null_rate distinct_count unique_rate is_likely_unique "
        "min_value max_value mean_value min_length max_length avg_length date_min date_max "
        "date_format invalid_count sample_invalid casing_pattern format_pattern alphabet "
        "value_set_size_class numeric_range_class mode_value mode_freq top_values "
        "detector_matches sentinels pii_score distribution detection_trail domain",
    )
    | _entries("document", "TopValue", scanned="value count pct")
    | _entries(
        "document",
        "DetectorMatch",
        scanned="detector_id match_rate sample_misses format_pattern confidence domain",
    )
    | _entries("document", "SentinelFlag", scanned="kind value count note")
    | _entries("document", "Distribution", scanned="kind data labels min max mean")
    | _entries("document", "DetectionSignal", scanned="signal confidence winner ml skipped")
)

_SCAN_CORE = (
    _entries(
        "scan_core",
        "TableCore",
        scanned="reid_risk_score quasi_identifier_groups",
        checked="key_candidates",
        source="row_count row_count_exact",
        label="name descriptor sample_strategy sample_row_cap basis scanned_rows fields warnings",
    )
    | _entries(
        "scan_core",
        "FieldCore",
        scanned="dtype null_count null_rate distinct_count pii_score pii_candidate "
        "detector_hits leading_zero_count model_hits",
        label="name",
    )
    | _entries(
        "scan_core",
        "ModelHitCore",
        scanned="band rate_bucket",
        label="source detector_id model",
    )
    | _entries("scan_core", "ModelRefCore", label="id version")
    | _entries("scan_core", "WarningRefCore", label="namespace code")
    | _entries(
        "scan_core",
        "RelationshipFactsCore",
        source="children parent_rows parent_null_key_rows parent_duplicate_excess",
        label="parent parent_columns status exact bounded warnings",
    )
    | _entries(
        "scan_core",
        "ChildFactsCore",
        source="rows null_key_rows orphan_rows orphan_distinct_keys",
        label="table columns",
    )
    | _entries("scan_core", "RegexRunCore", label="source model")
    | _entries("scan_core", "ModelRunCore", label="source model")
    | _entries(
        "scan_core",
        "ScanSetCore",
        label="scan_schema engine_version scanned_at tables relationships detectors",
    )
)

# The planner types are named by string, so `profiling` takes no edge into `profile`. On a
# first-chunk profile `TableProfile.row_count` and `row_count_exact` describe the chunk, not the
# source (`execution/capacity.py` reads `row_count_exact`, so it is not flipped); no route
# serializes that profile.
_PLANNER = (
    _entries(
        "planner",
        "ColumnProfile",
        scanned="dtype null_count distinct_count avg_length max_length",
        checked="is_candidate_key_sampled",
        source="row_count",
        label="name sampled declared_pk is_fk fk_target pii_class",
    )
    | _entries("planner", "TableProfile", source="row_count row_count_exact", label="name columns")
    | _entries(
        "planner",
        "Profile",
        label="schema_version tables relationships profiled_at decoy_engine_version profile_seed",
    )
    | _entries(
        "planner",
        "Relationship",
        label="parent_table parent_columns child_table child_columns namespace",
    )
)

# Keyed by (root, type name, field name): two roots hold a class named `ColumnProfile` whose
# `row_count` means different things. The root, not the module path, so a module split keeps keys.
FIELD_BASIS: Final = types.MappingProxyType(_DOCUMENT | _SCAN_CORE | _PLANNER)

# The field that carries the basis of each root, as (root, type name, field name).
CARRIERS: Final = types.MappingProxyType(
    {
        "document": ("document", "ColumnProfile", "basis"),
        "scan_core": ("scan_core", "TableCore", "basis"),
        "planner": ("planner", "ColumnProfile", "sampled"),
    }
)
