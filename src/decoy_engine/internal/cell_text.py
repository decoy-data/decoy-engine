"""The one rule for reading a cell as text, shared by the detectors and the post-scan runner.

Bytes are decoded as UTF-8, as pandas `astype(str)` decodes them, so a byte-encoded email reads
as the email and not as Python's `b'...'` form. Bytes that are not UTF-8 raise
`UnreadableCellError`, whose text is fixed: a decode error names the cell's bytes.
"""

from __future__ import annotations


class UnreadableCellError(ValueError):
    """A cell that cannot be read as text. The text is fixed, so no cell bytes reach a finding,
    a report or a log."""

    def __init__(self) -> None:
        super().__init__("a cell could not be read as text")


def cell_text(value: object) -> str:
    """`value` as text: bytes decoded as UTF-8, anything else as `str`."""
    if not isinstance(value, (bytes, bytearray)):
        return str(value)
    try:
        text: str | None = bytes(value).decode("utf-8")
    except UnicodeError:
        text = None
    if text is None:
        # Raised outside the handler, so the decode error is not chained as its context.
        raise UnreadableCellError
    return text
