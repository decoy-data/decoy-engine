"""`read_scan_set`: the one reader of a parsed `scan-set/v1` document.

The tag rule and the read model live here so a consumer (the CLI, the bound baseline) never
re-implements them. `scan_set.py` holds the write model and is at its size cap, so the reader
sits beside it. The function takes an already-parsed document; parsing and any non-finite
policy belong to the caller's parser.

Every refusal is a `ScanSetReadError` with a closed `kind` and fixed text. The text never
carries the tag, a member name or a value, and the error is raised after the `except` block
closes so a validation error (which holds the input) is not chained.
"""

from __future__ import annotations

import re
from typing import Any, Final, Literal

from decoy_engine.errors import DecoyError
from decoy_engine.profiling._scan_core import ScanSetCoreRead
from decoy_engine.profiling.scan_set import SCAN_SET_SCHEMA

_Kind = Literal["missing_tag", "unsupported_tag", "invalid"]

# `scan-set/v1` or `scan-set/v1.<minor>`; fullmatch, so a trailing newline or text is refused.
_TAG: Final = re.compile(re.escape(SCAN_SET_SCHEMA) + r"(\.[0-9]+)?")
_TEXT: Final[dict[str, str]] = {
    "missing_tag": "the document has no scan_schema tag",
    "unsupported_tag": "the scan_schema tag is not a supported scan-set/v1 tag",
    "invalid": "the document is not a valid scan-set/v1 scan",
}


class ScanSetReadError(DecoyError, ValueError):
    """A scan document could not be read. Fixed text; `kind` says which rule refused it.

    A `ValueError` so callers that catch bad input as one idiom still do. Its reason is the
    fixed untagged config reason (`reason_adapter._FIXED`).
    """

    def __init__(self, kind: _Kind) -> None:
        super().__init__(_TEXT[kind])
        self.kind: _Kind = kind


def read_scan_set(data: object) -> dict[str, Any]:
    """The value-free core of a `scan-set/v1` (or `v1.<minor>`) document, as a dict.

    Unknown members are ignored, so a newer minor reads. A tag of another major, text after
    the tag or a missing tag is refused. The returned dict carries the major tag.
    """
    if not isinstance(data, dict):
        raise ScanSetReadError("invalid")
    if "scan_schema" not in data:
        raise ScanSetReadError("missing_tag")
    tag = data["scan_schema"]
    if not (isinstance(tag, str) and _TAG.fullmatch(tag)):
        raise ScanSetReadError("unsupported_tag")
    failed = False
    try:
        model = ScanSetCoreRead.model_validate({**data, "scan_schema": SCAN_SET_SCHEMA})
    except Exception:
        failed = True
    if failed:
        raise ScanSetReadError("invalid")
    dumped: dict[str, Any] = model.model_dump()
    return dumped
