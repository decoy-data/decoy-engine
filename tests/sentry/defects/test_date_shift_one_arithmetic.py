"""One date arithmetic: `transforms.date_shift.shift_typed_days` is the only code under
`execution/` that adds calendar days to a typed date or re-attaches a zone.

A second copy of that arithmetic is how the oracle and the native route drift apart: the old
oracle added `timedelta(days=...)` per cell and raised where the native route kept the source.
The rule flags, in every `execution/**/*.py` function:

- `timedelta(days=...)` or `datetime.timedelta(days=...)`;
- any `.tz_localize(...)` call;
- `assume_timezone(...)` and `local_timestamp(...)`, under any module prefix.

`pd.to_timedelta` is out of scope on purpose: the text path and `bucket_perturb` use it for
text and bucket arithmetic, not typed-shape arithmetic. The allowlist is the baseline file
(`date-shift-one-arithmetic`); the ratchet fails a new entry without an owner decision.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src" / "decoy_engine"
BASELINE = ROOT / "tests" / "sentry" / "baselines" / "date-shift-one-arithmetic.json"
_ZONE_CALLS = frozenset({"tz_localize", "assume_timezone", "local_timestamp"})


def _name(func: ast.expr) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _forbidden(call: ast.Call) -> bool:
    name = _name(call.func)
    if name in _ZONE_CALLS:
        return True
    return name == "timedelta" and any(k.arg == "days" for k in call.keywords)


def scan(source: str, rel: str = "m.py") -> set[str]:
    """`<rel>::<qualified function>` for every scope that makes a forbidden call."""
    found: set[str] = set()

    def walk(node: ast.AST, scope: tuple[str, ...]) -> None:
        for child in ast.iter_child_nodes(node):
            inner = scope
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                inner = (*scope, child.name)
            if isinstance(child, ast.Call) and _forbidden(child):
                found.add(f"{rel}::{'.'.join(scope) or '<module>'}")
            walk(child, inner)

    walk(ast.parse(source), ())
    return found


def _allowed() -> set[str]:
    return set(json.loads(BASELINE.read_text())["entries"])


def _scan_execution() -> set[str]:
    found: set[str] = set()
    for path in sorted((SRC / "execution").rglob("*.py")):
        found |= scan(path.read_text(), path.relative_to(SRC).as_posix())
    return found


def test_execution_has_one_date_arithmetic() -> None:
    unexpected = _scan_execution() - _allowed()
    assert unexpected == set(), "add calendar days only through shift_typed_days"


def test_every_allowlist_entry_still_matches_a_site() -> None:
    assert _allowed() <= _scan_execution(), "drop the allowlist entry its fix removed"


@pytest.mark.parametrize(
    "bad",
    [
        "import datetime\ndef f(d, n):\n    return d + datetime.timedelta(days=n)\n",
        "from datetime import timedelta\ndef f(d, n):\n    return d + timedelta(days=n)\n",
        "def f(s, tz):\n    return s.dt.tz_localize(tz)\n",
        "import pyarrow.compute as pc\ndef f(a, tz):\n    return pc.assume_timezone(a, tz)\n",
        "import pyarrow\ndef f(a, tz):\n    return pyarrow.compute.assume_timezone(a, tz)\n",
        "import pyarrow.compute as pc\ndef f(a):\n    return pc.local_timestamp(a)\n",
        "from datetime import timedelta\nSHIFT = timedelta(days=3)\n",
    ],
)
def test_the_scan_catches_each_seeded_case(bad: str) -> None:
    assert scan(bad)


@pytest.mark.parametrize(
    "ok",
    [
        "import pandas as pd\ndef f(s, n):\n    return s + pd.to_timedelta(n, unit='D')\n",
        "from datetime import timedelta\ndef f(s):\n    return timedelta(seconds=s)\n",
    ],
)
def test_the_scan_leaves_text_and_non_day_arithmetic_alone(ok: str) -> None:
    assert scan(ok) == set()
