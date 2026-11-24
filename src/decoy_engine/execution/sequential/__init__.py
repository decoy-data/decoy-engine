"""Sequential-route modules that sit outside the frozen `execution` package."""

from __future__ import annotations

from typing import Any

__all__ = ["computed_faker_column"]


def __getattr__(name: str) -> Any:
    # Lazy: the module imports the sequential native ops, which import this package.
    if name == "computed_faker_column":
        from decoy_engine.execution.sequential._computed_faker import computed_faker_column

        return computed_faker_column
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
