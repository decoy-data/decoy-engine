"""Cross-table generation: the shapes a child column takes from its parent table.

`_cardinality` holds the reference-pool check every non-fitted route calls, the per-parent
bounds repair and the extra arguments a reference draw is called with; `_inherit` copies a
parent row's column through a foreign key. Callers import the names from this package.
"""

from __future__ import annotations

from decoy_engine.generation.relational._cardinality import (
    apply_cardinality_bounds,
    check_fitted_bounds,
    check_reference_pool,
    reference_draw_extras,
    reference_policies,
)
from decoy_engine.generation.relational._inherit import inherit_types, inherit_values

__all__ = [
    "apply_cardinality_bounds",
    "check_fitted_bounds",
    "check_reference_pool",
    "inherit_types",
    "inherit_values",
    "reference_draw_extras",
    "reference_policies",
]
