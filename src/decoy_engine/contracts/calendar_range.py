"""Stub for the red run: the error class only, no admission yet."""

from __future__ import annotations

from decoy_engine import reasons
from decoy_engine.errors import DecoyError


class FittedRangeError(DecoyError):
    code: str = reasons.plan.GENERATION_UNBOUNDED_COLUMN

    def __init__(self, *, prop: str) -> None:
        self.prop = prop
        super().__init__(f"[{self.code}] {prop}")
