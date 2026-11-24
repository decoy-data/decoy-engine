"""Sentry: engine code copies exception text into other values; the count only goes down.

A copy is exception text moved into a raise message, return value, log call or other sink
(rules in `_copies.py`). BASELINE is the audited count. A new copy fails the test; so does a
removed copy while BASELINE is unchanged, so the number is lowered in the same change that
removes the copy. Never raise BASELINE to pass: render the cause by type or reuse an existing
reason code instead (docs/plans/2026-11-24-f31-audit.md, slice AE5).

Messages name files and rules only, never the copied text.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from tests.sentry.safe_output._copies import Copy, scan_source, scan_tree

BASELINE = 100
SRC = Path(__file__).resolve().parents[3] / "src" / "decoy_engine"


def _by_file(copies: list[Copy]) -> str:
    return ", ".join(f"{f}={n}" for f, n in sorted(Counter(c.file for c in copies).items()))


def verdict(copies: list[Copy], baseline: int) -> str | None:
    """None when the ratchet holds, else a value-free failure message."""
    if len(copies) > baseline:
        return (
            f"exception-text copies grew to {len(copies)} (baseline {baseline}). "
            f"Render the cause by type instead of copying it. Per file: {_by_file(copies)}"
        )
    if len(copies) < baseline:
        return (
            f"exception-text copies shrank to {len(copies)} (baseline {baseline}). "
            f"Lower BASELINE to {len(copies)} in this file."
        )
    return None


def test_engine_copies_match_baseline() -> None:
    message = verdict(scan_tree(SRC), BASELINE)
    assert message is None, message


def test_ratchet_fails_on_growth_and_on_unlowered_shrink() -> None:
    copy = Copy("a.py", 1, "str(exc)", "except", "raise")
    assert verdict([copy, copy], 1) is not None
    assert verdict([copy], 2) is not None
    assert verdict([copy], 1) is None


# Red seeds: each rule must fire on a scratch module, so a rule dropped from `_copies.py`
# turns exactly one of these red.
SEEDS = {
    "str(exc)": "try:\n    pass\nexcept ValueError as exc:\n    raise RuntimeError(str(exc))\n",
    "repr(exc)": "try:\n    pass\nexcept ValueError as exc:\n    x = repr(exc)\n",
    "format(exc)": "try:\n    pass\nexcept ValueError as exc:\n    x = format(exc)\n",
    "f{exc}": 'try:\n    pass\nexcept ValueError as exc:\n    raise RuntimeError(f"x {exc}")\n',
    "exc.message": "try:\n    pass\nexcept ValueError as exc:\n    x = exc.message\n",
    "exc.args": "try:\n    pass\nexcept ValueError as exc:\n    x = exc.args\n",
    "%exc": 'try:\n    pass\nexcept ValueError as exc:\n    x = "x %s" % exc\n',
    "traceback": "import traceback\ntry:\n    pass\nexcept ValueError:\n    x = traceback.format_exc()\n",
    "param": "def f(err):\n    return str(err)\n",
    "annotated param": "def f(boom: ValueError):\n    return f'{boom}'\n",
}


@pytest.mark.parametrize("form", sorted(SEEDS))
def test_seed_fires(form: str) -> None:
    copies = scan_source(SEEDS[form])
    assert copies, f"rule {form!r} did not fire"
    if form in ("param", "annotated param"):
        assert {c.binding for c in copies} == {"param"}
    else:
        assert form in {c.form for c in copies}


def test_seed_sinks() -> None:
    src = (
        "import logging\nlog = logging.getLogger('x')\n"
        "def f(exc):\n    log.error('%s', str(exc))\n    print(str(exc))\n"
        "    d = {'k': str(exc)}\n    raise ValueError(str(exc))\n"
    )
    assert [c.sink for c in scan_source(src)] == ["log", "terminal", "dict", "raise"]


def test_clean_code_is_not_a_copy() -> None:
    clean = (
        "try:\n    pass\nexcept ValueError as exc:\n"
        "    raise RuntimeError(type(exc).__name__) from exc\n"
        "def g(value):\n    return str(value)\n"
        "def h(exc):\n    return exc.code\n"
    )
    assert scan_source(clean) == []
