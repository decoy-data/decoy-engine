"""Sentry helpers for the F31 safe-output audit: the shared AST name tagger."""

from tests.sentry.safe_output._tagger import (
    RISKY_NAMES,
    SINK_RISKY,
    own_nodes,
    risky_in,
    tainted_names,
)

__all__ = ["RISKY_NAMES", "SINK_RISKY", "own_nodes", "risky_in", "tainted_names"]
