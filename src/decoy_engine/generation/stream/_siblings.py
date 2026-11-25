"""Which earlier column of the same batch a generated column reads: the one sibling rule.

A `windowed_date` column reads its `anchor`; a conditional `categorical` or `statistical` column
reads the column its `condition_on` names. Admission, window admission, the windowed-date stream
and the batch assembler (which keeps a sibling's values as a Python list) all ask here, so the
rule changes in one place.
"""

from __future__ import annotations

from typing import Any

_SIBLING_OPTION = {
    "windowed_date": "anchor",
    "categorical": "condition_on",
    "statistical": "condition_on",
}


def sibling_input(col: dict[str, Any]) -> str | None:
    """The name of the same-batch column `col` reads, or `None` when it reads none."""
    option = _SIBLING_OPTION.get(str(col.get("type")))
    if option is None:
        return None
    name = col.get(option)
    return name if isinstance(name, str) else None


__all__ = ["sibling_input"]
