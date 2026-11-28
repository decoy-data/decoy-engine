"""The root of the engine exception hierarchy, as a leaf.

`decoy_engine.errors` re-exports `DecoyError` and stays the public home of every typed
exception. The root lives here so a leaf package that `errors` itself imports (the reason
registry) can still derive its own exception from the engine base without an import cycle.
"""

from __future__ import annotations

from typing import Literal, NoReturn

# Closed set of connector failure classes. Only `transient` is retried; the rest are permanent.
ConnectorErrorKind = Literal[
    "access_denied",
    "not_found",
    "precondition_failed",
    "conflict",
    "wrong_region",
    "pointer_invalid",
    "transient",
    "credentials",
    "rejected",
    "source_changed",
    "digest_mismatch",
    "host_key_rejected",
    "unexpected",
]


class DecoyError(Exception):
    """Base class for all decoy_engine exceptions."""


# Pickles, tracebacks and `__module__` consumers keep seeing the public home, not this leaf.
DecoyError.__module__ = "decoy_engine.errors"


def raise_bare(error: BaseException) -> NoReturn:
    """Raise `error` with no inherited chain. A caller may reach an exported entry while handling
    its own exception (a secret-bearing decode error, say), which Python would attach as
    `__context__`; so the error is raised, caught, cleared and re-raised bare (A-4 AT-X1)."""
    try:
        raise error.with_traceback(None)
    except BaseException as fresh:
        fresh.__cause__ = None
        fresh.__context__ = None
        fresh.__suppress_context__ = True
        raise
