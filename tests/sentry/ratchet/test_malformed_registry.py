"""RG-E1: malformed registries are one finding on HEAD and one fail-closed line on BASE.

Every input in ``MALFORMED`` runs against both sides through ``load_side``. A HEAD run must name
the field-specific problem; a BASE run must print exactly one ``ratchet: FAIL`` line. Neither side
may print a traceback.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.sentry.ratchet.test_integrity import _commit, _red_from, _run_from
from tests.sentry.test_ratchet_check import (
    REG,
    A,
    _approve,
    _assert_red,
    _baseline,
    _grow,
    _registry,
    _run,
    _write,
)

B = "tests/sentry/baselines/b.json"


# --- review round 5: base registry errors, field types, one validation path ---------------------


def test_a_base_registry_with_a_duplicate_id_fails_closed(repo: Path) -> None:
    dup = f'[[sentry]]\nid = "a"\nbaseline = "{A}"\n\n[[sentry]]\nid = "a"\nbaseline = "{B}"\n'
    _write(repo, B, _baseline("a", ["m::f"]))
    _write(repo, REG, dup)
    base = _commit(repo, "base with a duplicate id")
    _write(repo, REG, _registry({"a": A}))
    (repo / B).unlink()
    _write(repo, A, _baseline("a", ["m::f", "m::g", "m::new"]))
    _red_from(repo, base, f"cannot read {REG} from the base commit")


def test_a_base_registry_with_a_shared_path_fails_closed(repo: Path) -> None:
    _write(repo, REG, _registry({"a": A, "a-twin": A}))
    base = _commit(repo, "base with a shared path")
    _write(repo, REG, _registry({"a": A}))
    _red_from(repo, base, f"cannot read {REG} from the base commit")


@pytest.mark.parametrize(
    "row",
    [
        'id = []\nbaseline = "tests/sentry/baselines/a.json"',
        'id = ""\nbaseline = "tests/sentry/baselines/a.json"',
        'id = "a"\nbaseline = 5',
        'id = "a"\nbaseline = "tests/sentry/baselines/a.json"\napproved_growth = "x"',
        'baseline = "tests/sentry/baselines/a.json"',
    ],
    ids=["id list", "id empty", "baseline int", "approved_growth str", "no id"],
)
def test_a_wrongly_typed_head_row_is_one_finding_not_a_traceback(repo: Path, row: str) -> None:
    _write(repo, REG, f"[[sentry]]\n{row}\n")
    res = _run(repo)
    assert res.returncode == 1, res.stdout + res.stderr
    assert "Traceback" not in res.stderr
    assert res.stderr.count("ratchet: FAIL") == 1, res.stderr


@pytest.mark.parametrize(
    "weak", ["owner 2026-11-24 TODO...........", "owner 2026-11-24 tbd!!!!!!!!!!!!"]
)
def test_a_padded_placeholder_approval_is_refused(repo: Path, weak: str) -> None:
    _grow(repo, "m::new")
    _approve(repo, [("m::new", weak)])
    _assert_red(repo, "approved_growth for m::new needs a decision")


# --- plan amendment A1: BASE and HEAD go through one loader -----------------------------------

ROW = f'[[sentry]]\nid = "a"\nbaseline = "{A}"\n'
DIR_FILE = "tests/sentry/baselines/dir/x.txt"
GOOD_DECISION = "owner 2026-11-24 a reason that is long enough"
MALFORMED: tuple[tuple[str, str, str], ...] = (
    (
        "duplicate id",
        ROW + f'\n[[sentry]]\nid = "a"\nbaseline = "{B}"\n',
        "sentry id a appears twice",
    ),
    ("shared path", ROW + f'\n[[sentry]]\nid = "t"\nbaseline = "{A}"\n', "share baseline"),
    ("id list", f'[[sentry]]\nid = []\nbaseline = "{A}"\n', "id must be a non-empty string"),
    ("id empty", f'[[sentry]]\nid = ""\nbaseline = "{A}"\n', "id must be a non-empty string"),
    ("id missing", f'[[sentry]]\nbaseline = "{A}"\n', "id must be a non-empty string"),
    ("baseline missing", '[[sentry]]\nid = "a"\n', "a: baseline must be a string path"),
    ("baseline int", '[[sentry]]\nid = "a"\nbaseline = 5\n', "a: baseline must be a string path"),
    ("bad toml", "this is = = broken\n", "is not valid TOML"),
    ("non-table rows", "sentry = [1]\n", "as an array of tables"),
    ("approval item int", ROW + "approved_growth = [5]\n", "a: approved_growth row has no key"),
    ("approved_growth str", ROW + 'approved_growth = "x"\n', "a: approved_growth must be a list"),
    (
        "approval key list",
        ROW + f'approved_growth = [{{ key = [], decision = "{GOOD_DECISION}" }}]\n',
        "a: approved_growth row has no key",
    ),
    (
        "approval no decision",
        ROW + 'approved_growth = [{ key = "m::n" }]\n',
        "approved_growth for m::n needs a decision",
    ),
    (
        "approval weak decision",
        ROW + 'approved_growth = [{ key = "m::n", decision = "owner 2026-11-24 xxxxxxxxxx" }]\n',
        "approved_growth for m::n needs a decision",
    ),
    ("unknown row field", ROW + 'bypass = "yes"\n', "a: unknown registry key bypass"),
    ("retired holds an int", ROW + "\n[retired]\nold = 5\n", "retired old:"),
    (
        "approval key not in the inventory",
        ROW + f'approved_growth = [{{ key = "m::nope", decision = "{GOOD_DECISION}" }}]\n',
        "a: stale approved_growth, m::nope is not in",
    ),
    ("huge integer", ROW + "big = " + "9" * 4500 + "\n", "is not valid TOML"),
    ("deep nesting", "x = " + "[" * 600 + "]" * 600 + "\n", "is not valid TOML"),
    (
        "baseline names a directory",
        '[[sentry]]\nid = "a"\nbaseline = "tests/sentry/baselines/dir"\n',
        "a: baseline tests/sentry/baselines/dir cannot be read or is not a baseline file",
    ),
    (
        "approval padded placeholder",
        ROW
        + 'approved_growth = [{ key = "m::n", decision = "owner 2026-11-24 TODO..........." }]\n',
        "approved_growth for m::n needs a decision",
    ),
)


@pytest.mark.parametrize("text, needle", [c[1:] for c in MALFORMED], ids=[c[0] for c in MALFORMED])
def test_a_malformed_head_registry_gives_its_own_diagnostic(
    repo: Path, text: str, needle: str
) -> None:
    _write(repo, B, _baseline("a", ["m::f"]))
    _write(repo, DIR_FILE, "x")
    _write(repo, REG, text)
    res = _run(repo)
    assert res.returncode == 1, res.stdout + res.stderr
    assert "Traceback" not in res.stderr
    assert needle in res.stderr, res.stderr


@pytest.mark.parametrize("text", [c[1] for c in MALFORMED], ids=[c[0] for c in MALFORMED])
def test_a_malformed_base_registry_fails_closed_with_one_line(repo: Path, text: str) -> None:
    _write(repo, B, _baseline("a", ["m::f"]))
    _write(repo, DIR_FILE, "x")
    _write(repo, REG, text)
    base = _commit(repo, "malformed base registry")
    _write(repo, REG, _registry({"a": A}))
    (repo / B).unlink()
    res = _run_from(repo, base)
    assert res.returncode == 1, res.stdout + res.stderr
    assert "Traceback" not in res.stderr
    assert res.stderr.count("ratchet: FAIL") == 1, res.stderr
    assert "cannot read " in res.stderr and " from the base commit" in res.stderr


def test_invalid_utf8_in_the_head_registry_is_one_finding(repo: Path) -> None:
    (repo / REG).write_bytes(b"\xff\xfe")
    res = _run(repo)
    assert res.returncode == 1, res.stdout + res.stderr
    assert "Traceback" not in res.stderr
    assert f"registry: {REG} cannot be read as UTF-8 text" in res.stderr


def test_invalid_utf8_in_the_base_registry_fails_closed(repo: Path) -> None:
    (repo / REG).write_bytes(b"\xff\xfe")
    base = _commit(repo, "binary base registry")
    _write(repo, REG, _registry({"a": A}))
    res = _run_from(repo, base)
    assert res.returncode == 1, res.stdout + res.stderr
    assert "Traceback" not in res.stderr
    assert res.stderr.count("ratchet: FAIL") == 1
    assert f"cannot read {REG} from the base commit" in res.stderr


@pytest.mark.parametrize(
    "body", ["not json", "[]", '{"entries": []}', "9" * 4500, "[" * 600 + "]" * 600]
)
def test_an_unreadable_head_baseline_is_one_finding_not_a_traceback(repo: Path, body: str) -> None:
    _write(repo, A, body)
    res = _run(repo)
    assert res.returncode == 1, res.stdout + res.stderr
    assert "Traceback" not in res.stderr
    assert f"a: baseline {A} cannot be read or is not a baseline file" in res.stderr


def test_a_duplicate_id_does_not_hide_an_unsafe_path(repo: Path) -> None:
    bad = "tests/sentry/baselines/../x.json"
    # The unsafe row comes first, so the later row of the same id overwrites its path.
    _write(repo, REG, f'[[sentry]]\nid = "a"\nbaseline = "{bad}"\n\n' + ROW)
    res = _run(repo)
    assert res.returncode == 1, res.stdout + res.stderr
    assert "sentry id a appears twice" in res.stderr
    assert f"baseline {bad} is outside" in res.stderr
