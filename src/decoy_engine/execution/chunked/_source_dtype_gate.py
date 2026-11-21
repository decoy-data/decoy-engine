"""The planner's source-dtype gate for the chunked lane.

A source column the pandas round trip alters per chunk keeps a table off the lane. A carried
passthrough column (`_chunked_carry.carried_columns`) never reaches pandas, so its type cannot
alter anything and the gate skips it.
"""

from __future__ import annotations

from collections.abc import Collection
from typing import TYPE_CHECKING

import pyarrow.types as pat

if TYPE_CHECKING:
    from decoy_engine.execution._chunked_input import SourceFacts


def unstable_source_columns(
    facts: SourceFacts,
    *,
    declared_stable: Collection[str] = (),
    declared_bad: Collection[str] = (),
    carried: Collection[str] = (),
) -> list[str]:
    """Labels of the source columns whose pandas round trip is not chunk-stable.

    `declared_*` are the F06 declared-cast columns, judged by the type the cast leaves; a
    `carried` column is exempt, whatever its type."""
    unstable = [f"{n} (declared, no output_format)" for n in sorted(declared_bad)]
    skip = {*declared_stable, *declared_bad, *carried}
    for schema_field in facts.schema:
        t = schema_field.type
        if schema_field.name in skip:
            continue
        if pat.is_integer(t):
            # pandas widens int+null to float PER FRAME, so a null-free chunk keeps int64
            # while a null-bearing one becomes float64; only a null-free integer column
            # round-trips chunk-stably.
            if (facts.null_count(schema_field.name) or 0) > 0:
                unstable.append(f"{schema_field.name} (integer with nulls)")
        elif not (
            pat.is_string(t)
            or pat.is_large_string(t)
            or pat.is_floating(t)
            or pat.is_boolean(t)
            or pat.is_temporal(t)
            or pat.is_null(t)
        ):
            unstable.append(f"{schema_field.name} ({t})")
    return unstable
