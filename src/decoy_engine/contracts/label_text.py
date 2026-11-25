"""The one rule for text a user supplies as an output label.

A label reaches Arrow as a UTF-8 string scalar. A lone surrogate is valid Python text with no
UTF-8 form, so Arrow raises while it builds the scalar and the error args carry the whole label.
Every entry that takes a label (the strategy resolver, the plan check and the kernel) asks
``is_utf8_text`` first and refuses with a message that names no value.
"""

from __future__ import annotations

from typing import Any


def is_utf8_text(value: Any) -> bool:
    """True for a string that encodes as strict UTF-8 (no lone surrogate)."""
    if not isinstance(value, str):
        return False
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def is_mask_char(value: Any) -> bool:
    """True for one character that encodes as strict UTF-8 (a usable truncate mask)."""
    return isinstance(value, str) and len(value) == 1 and is_utf8_text(value)
