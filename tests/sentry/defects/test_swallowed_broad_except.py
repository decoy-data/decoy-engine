"""24zi class guard: a broad handler that keeps going (`swallowed-broad-except`).

The predicate is `_swallowed_except.swallowed_sites`; its rules and covered shapes are listed in
that module. The baseline `tests/sentry/baselines/swallowed-broad-except.json` holds one entry per
`src/` file with a counted site, `{"reason", "max"}`. A count above `max`, a file with sites and
no entry, and a count below `max` all fail, so every fix shrinks the baseline in its own PR and
no headroom is left for a new site. `scripts/dev/ratchet_check.py` refuses a new key or a raised
`max` against the merge base.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from tests.sentry.defects._swallowed_except import swallowed_sites

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
BASELINE = ROOT / "tests" / "sentry" / "baselines" / "swallowed-broad-except.json"
MIN_REASON = 15


def _count(source: str) -> int:
    return len(swallowed_sites(ast.parse(source)))


def _tree_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    for path in sorted(SRC.rglob("*.py")):
        n = len(swallowed_sites(ast.parse(path.read_text(encoding="utf-8"))))
        if n:
            counts[path.relative_to(ROOT).as_posix()] = n
    return counts


def _entries() -> dict[str, dict[str, object]]:
    doc = json.loads(BASELINE.read_text(encoding="utf-8"))
    assert doc["sentry_id"] == "swallowed-broad-except"
    return doc["entries"]  # type: ignore[no-any-return]


SEEDED = {
    "bare_except_pass": ("try:\n    f()\nexcept:\n    pass\n", 1),
    "exception_logged": ("try:\n    f()\nexcept Exception:\n    log('x')\n", 1),
    "tuple_with_exception": ("try:\n    f()\nexcept (ValueError, Exception):\n    pass\n", 1),
    "base_exception_continue": (
        "for x in y:\n    try:\n        f()\n    except BaseException:\n        continue\n",
        1,
    ),
    "builtins_attribute": ("try:\n    f()\nexcept builtins.Exception:\n    pass\n", 1),
    "contextlib_suppress": (
        "import contextlib\nwith contextlib.suppress(Exception):\n    f()\n",
        1,
    ),
    "bare_suppress": ("with suppress(BaseException):\n    f()\n", 1),
    "suppress_narrow": ("with suppress(OSError):\n    f()\n", 0),
    "wrapped_from": (
        "try:\n    f()\nexcept Exception as e:\n    raise Wrapped() from e\n",
        0,
    ),
    "conditional_raise": ("try:\n    f()\nexcept Exception:\n    if bad:\n        raise\n", 0),
    "saved_then_raised": (
        "def g():\n    try:\n        f()\n    except Exception as e:\n        err = e\n    raise err\n",
        0,
    ),
    "saved_never_raised": (
        "def g():\n    try:\n        f()\n    except Exception as e:\n        err = e\n    return 1\n",
        1,
    ),
    "raise_only_in_nested_def": (
        "try:\n    f()\nexcept Exception:\n    def h():\n        raise X\n",
        1,
    ),
    "narrow_handler": ("try:\n    f()\nexcept ValueError:\n    pass\n", 0),
    "raise_after_finally": (
        "def g():\n    try:\n        f()\n    except Exception as e:\n        err = e\n"
        "    finally:\n        close()\n    raise err\n",
        0,
    ),
    "raise_before_try": (
        "def g():\n    if early:\n        raise err\n    try:\n        f()\n"
        "    except Exception as e:\n        err = e\n",
        1,
    ),
    "saved_outside_handler": (
        "def g():\n    err = None\n    try:\n        f()\n    except Exception:\n        pass\n"
        "    raise err\n",
        1,
    ),
    "raise_inside_try_body": (
        "def g():\n    try:\n        f()\n        raise err\n    except Exception as e:\n"
        "        err = e\n",
        1,
    ),
}


@pytest.mark.parametrize("name", sorted(SEEDED))
def test_seeded_cell(name: str) -> None:
    source, expected = SEEDED[name]
    assert _count(source) == expected


def test_every_src_file_count_equals_its_baseline_max() -> None:
    entries = _entries()
    counts = _tree_counts()
    unlisted = sorted(set(counts) - set(entries))
    assert not unlisted, f"files with a swallowing broad handler and no baseline entry: {unlisted}"
    stale = sorted(set(entries) - set(counts))
    assert not stale, f"baseline entries for files with no site left (delete the key): {stale}"
    over = {f: (n, entries[f]["max"]) for f, n in counts.items() if n > entries[f]["max"]}
    assert not over, f"new swallowing broad handlers (count, max): {over}"
    under = {f: n for f, n in counts.items() if n < entries[f]["max"]}
    assert not under, f"a handler was fixed; lower max to the count: {under}"


def test_every_baseline_entry_has_a_real_reason_and_an_integer_max() -> None:
    for path, row in _entries().items():
        reason = row["reason"]
        assert isinstance(reason, str) and len(reason) >= MIN_REASON, path
        assert type(row["max"]) is int and row["max"] > 0, path
