"""Public home of the Arrow-to-pandas conversion names (SOURCE-READ-BOUNDARY S1b).

A thin wrapper, like `decoy_engine.providers`: the implementation stays in
`decoy_engine.internal.pandas_compat`, so the root package imports from here and not from
`internal`. The three names are experimental; each takes a required `on_unrepresentable(column)`
callback that must raise.
"""

from __future__ import annotations

from decoy_engine.internal.pandas_compat import (
    arrow_to_frame,
    arrow_to_frame_pair,
    arrow_to_series,
)

__all__ = ["arrow_to_frame", "arrow_to_frame_pair", "arrow_to_series"]
