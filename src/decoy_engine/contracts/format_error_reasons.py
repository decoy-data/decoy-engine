"""The reason text of a strategy's row error, one entry per strategy.

A row error's ``reason`` never embeds the cell value. Each text has exactly one owner here, so a
caller names the strategy and cannot copy or mistype the wording. This module imports only the
standard library.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

__all__ = ["format_error_reason"]

_REASONS: Mapping[str, str] = MappingProxyType(
    {
        "bucketize": "value is out of range under bucketize",
    }
)


def format_error_reason(strategy: str) -> str:
    """The row-error reason text for ``strategy``.

    A strategy with no entry is an invariant error: the caller asked for a reason nobody owns.
    """
    try:
        return _REASONS[strategy]
    except KeyError:
        raise LookupError(
            f"no format-error reason is registered for strategy {strategy!r}"
        ) from None
