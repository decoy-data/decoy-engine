"""Which earlier column of the same batch a generated column reads: the one sibling rule.

The option is the one the generate-options registry marks ``same_batch`` (a `windowed_date`
column's `anchor`, a conditional column's `condition_on`). Admission, window admission, the
windowed-date stream and the batch assembler (which keeps a sibling's values as a Python list)
all ask here, so the rule changes in one place.
"""

from __future__ import annotations

from typing import Any

from decoy_engine.config import same_batch_option


def sibling_input(col: dict[str, Any], type_: str | None = None) -> str | None:
    """The same-batch column `col` reads, or `None`; `type_` stands in for a missing `type` key."""
    option = same_batch_option(type_ if type_ is not None else col.get("type"))
    name = col.get(option) if option is not None else None
    return name if isinstance(name, str) else None


__all__ = ["sibling_input"]
