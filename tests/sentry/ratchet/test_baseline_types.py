"""RG-E1 A1: every baseline field has an exact type on both sides; nothing is coerced.

Each wrong-typed document runs on HEAD (a finding naming the baseline) and on BASE (one fail-closed
line, with HEAD repaired). The fixtures are synthetic and live only in scratch repos.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.sentry.ratchet.test_integrity import _commit, _run_from
from tests.sentry.test_ratchet_check import REASON, A, _baseline, _run, _write

GOOD = _baseline("a", ["m::f", "m::g"])


def _doc(**changes: object) -> str:
    entry: dict[str, object] = {"reason": REASON}
    entries = {"m::f": dict(entry), "m::g": dict(entry)}
    doc: dict[str, object] = {"sentry_id": "a", "created_in": "S0", "entries": entries}
    for name, value in changes.items():
        if name.startswith("entry_"):
            entries["m::f"][name.removeprefix("entry_")] = value
        else:
            doc[name] = value
    return json.dumps(doc)


WRONG_TYPES: tuple[tuple[str, str], ...] = (
    ("sentry_id null", _doc(sentry_id=None)),
    ("sentry_id number", _doc(sentry_id=1)),
    ("created_in number", _doc(created_in=5)),
    ("entries list", _doc(entries=[])),
    ("entry not an object", _doc(entries={"m::f": "x", "m::g": {"reason": REASON}})),
    ("reason null", _doc(entry_reason=None)),
    ("reason number", _doc(entry_reason=7)),
    ("category number", _doc(entry_category=3)),
    ("moved_from number", _doc(entry_moved_from=3)),
    ("max boolean", _doc(entry_max=True)),
    ("max quoted", _doc(entry_max="5")),
    ("max float", _doc(entry_max=5.0)),
    ("min boolean", _doc(entry_min=False)),
    ("min quoted", _doc(entry_min="1")),
)
IDS = [c[0] for c in WRONG_TYPES]


@pytest.mark.parametrize("body", [c[1] for c in WRONG_TYPES], ids=IDS)
def test_a_wrong_type_is_a_head_finding(repo: Path, body: str) -> None:
    _write(repo, A, body)
    res = _run(repo)
    assert res.returncode == 1, res.stdout + res.stderr
    assert "Traceback" not in res.stderr
    assert f"a: baseline {A} cannot be read or is not a baseline file" in res.stderr


@pytest.mark.parametrize("body", [c[1] for c in WRONG_TYPES], ids=IDS)
def test_a_wrong_type_on_the_base_fails_closed(repo: Path, body: str) -> None:
    _write(repo, A, body)
    base = _commit(repo, "wrong type on base")
    _write(repo, A, GOOD)
    res = _run_from(repo, base)
    assert res.returncode == 1, res.stdout + res.stderr
    assert res.stderr.count("ratchet: FAIL") == 1
    assert f"cannot read {A} from the base commit" in res.stderr


def test_exact_integers_and_strings_pass(repo: Path) -> None:
    _write(repo, A, _doc(entry_max=3, entry_min=1, entry_category="c", entry_moved_from="x"))
    res = _run(repo)
    assert res.returncode == 0, res.stdout + res.stderr
