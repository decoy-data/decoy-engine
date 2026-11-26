"""One memory-failure text test, two callers (F25 G7-1, case 8b).

`is_memory_failure` and `resurface_scrubbed` must call the same text predicate. For an untyped
exception they agree on every string: both say yes or both say no. This holds today by the
shared helper; it is a guard against one caller growing its own marker list again.
"""

from __future__ import annotations

import pytest

from decoy_engine.fileaccess._errors import (
    GLIBC_TLS_OOM_MARKER,
    MEMORY_ERROR_MARKERS,
    MEMORY_ERROR_PATTERNS,
    is_memory_failure,
    resurface_scrubbed,
)

_CORPUS = [
    *MEMORY_ERROR_MARKERS,
    *(f"prefix {m} suffix" for m in MEMORY_ERROR_MARKERS),
    "Unknown error: Wrapping zz_cell failed",
    "x Wrapping zz_cell failed digital envelope routines",
    "Wrapping failed",
    "Unknown error: Wrapping",
    "digital envelope",
    "copy ctx",
    GLIBC_TLS_OOM_MARKER,
    "",
    "file could not be read",
    "zz_cell",
]


def test_the_corpus_holds_both_answers() -> None:
    """Non-vacuity: the agreement below is not 'no' on every string."""
    answers = {is_memory_failure(ValueError(t)) for t in _CORPUS}
    assert answers == {True, False}
    assert all(p.search("Unknown error: Wrapping zz_cell failed") for p in MEMORY_ERROR_PATTERNS)


@pytest.mark.parametrize("text", _CORPUS)
def test_the_two_callers_agree_on_every_untyped_exception(text: str) -> None:
    exc = ValueError(text)
    assert is_memory_failure(exc) == (resurface_scrubbed(exc) is not None)
