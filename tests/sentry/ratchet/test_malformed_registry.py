"""RG-E1: malformed registries are one finding on HEAD and one fail-closed line on BASE.

Every input in ``MALFORMED`` runs against both sides through ``load_side``. A HEAD run must name
the field-specific problem; a BASE run must print exactly one ``ratchet: FAIL`` line. Neither side
may print a traceback.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from tests.sentry.ratchet.test_integrity import (
    _commit,
    _new_field,
    _red_from,
    _run_env,
    _run_from,
)
from tests.sentry.test_ratchet_check import (
    REASON,
    REG,
    A,
    _approve,
    _assert_red,
    _baseline,
    _git,
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
        "duplicate id, first baseline missing",
        '[[sentry]]\nid = "a"\nbaseline = "tests/sentry/baselines/gone.json"\n\n' + ROW,
        "a: registry points at tests/sentry/baselines/gone.json but there is no baseline file",
    ),
    (
        "approval key twice",
        ROW
        + "approved_growth = [\n"
        + f'  {{ key = "m::f", decision = "{GOOD_DECISION}" }},\n'
        + '  { key = "m::f", decision = "owner 2026-11-23 another reason that is long" },\n]\n',
        "a: approved_growth key m::f appears twice",
    ),
    (
        "path component too long",
        f'[[sentry]]\nid = "a"\nbaseline = "tests/sentry/baselines/{"x" * 300}.json"\n',
        "a: baseline tests/sentry/baselines/",
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


# --- A1 round 2: every baseline rule runs on both sides -----------------------------------------

GOOD = _baseline("a", ["m::f", "m::g"])
ENTRY = '{"reason": "reviewed on 2026-11-04, tracked for removal"}'
BROKEN_FILES: tuple[tuple[str, str, str], ...] = (
    ("wrong sentry_id", _baseline("other", ["m::f", "m::g"]), "sentry_id 'other' does not match"),
    ("one-char reason", _baseline("a", ["m::f", "m::g"], reason="x"), "reason for m::f is empty"),
    ("no entries field", '{"sentry_id": "a", "created_in": "S0"}', "cannot be read or is not a"),
    ("entries is a list", '{"sentry_id": "a", "entries": []}', "cannot be read or is not a"),
    (
        "duplicate entry key",
        f'{{"sentry_id": "a", "created_in": "S0", "entries": {{"m::f": {ENTRY}, "m::f": {ENTRY}}}}}',
        "cannot be read or is not a",
    ),
)


@pytest.mark.parametrize(
    "body, needle", [c[1:] for c in BROKEN_FILES], ids=[c[0] for c in BROKEN_FILES]
)
def test_a_bad_head_baseline_gives_its_own_diagnostic(repo: Path, body: str, needle: str) -> None:
    _write(repo, A, body)
    res = _run(repo)
    assert res.returncode == 1, res.stdout + res.stderr
    assert "Traceback" not in res.stderr
    assert needle in res.stderr, res.stderr


@pytest.mark.parametrize("body", [c[1] for c in BROKEN_FILES], ids=[c[0] for c in BROKEN_FILES])
def test_a_bad_base_baseline_fails_closed_even_when_head_fixes_it(repo: Path, body: str) -> None:
    _write(repo, A, body)
    base = _commit(repo, "bad base baseline")
    _write(repo, A, GOOD)
    res = _run_from(repo, base)
    assert res.returncode == 1, res.stdout + res.stderr
    assert "Traceback" not in res.stderr
    assert res.stderr.count("ratchet: FAIL") == 1, res.stderr
    assert "from the base commit" in res.stderr


def _link(repo: Path, rel: str, target: Path) -> None:
    (repo / rel).unlink()
    (repo / rel).symlink_to(target)


def test_a_head_baseline_symlink_is_refused(
    repo: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    outside = tmp_path_factory.mktemp("outside") / "a.json"
    outside.write_text(GOOD, encoding="utf-8")
    _link(repo, A, outside)
    res = _run(repo)
    assert res.returncode == 1, res.stdout + res.stderr
    assert f"a: baseline {A} cannot be read or is not a baseline file" in res.stderr


def test_a_head_registry_symlink_is_refused(
    repo: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    outside = tmp_path_factory.mktemp("outside") / "r.toml"
    outside.write_text(_registry({"a": A}), encoding="utf-8")
    _link(repo, REG, outside)
    res = _run(repo)
    assert res.returncode == 1, res.stdout + res.stderr
    assert f"registry: {REG} cannot be read as UTF-8 text" in res.stderr


def test_a_base_baseline_symlink_fails_closed(
    repo: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    outside = tmp_path_factory.mktemp("outside") / "a.json"
    outside.write_text(GOOD, encoding="utf-8")
    _link(repo, A, outside)
    base = _commit(repo, "symlinked baseline on base")
    (repo / A).unlink()
    _write(repo, A, GOOD)
    res = _run_from(repo, base)
    assert res.returncode == 1, res.stdout + res.stderr
    assert res.stderr.count("ratchet: FAIL") == 1
    assert f"cannot read {A} from the base commit" in res.stderr


def test_a_tracked_empty_base_registry_is_not_an_absent_one(repo: Path) -> None:
    _write(repo, REG, "")
    base = _commit(repo, "empty registry on base")
    _write(repo, REG, _registry({"a": A}))
    res = _run_from(repo, base)
    assert res.returncode == 1, res.stdout + res.stderr
    assert res.stderr.count("ratchet: FAIL") == 1
    assert f"cannot read {REG} from the base commit" in res.stderr


def test_an_absent_base_registry_admits_a_first_inventory(repo: Path) -> None:
    _git(repo, "rm", "-q", REG, A)
    base = _commit(repo, "no registry on base")
    _write(repo, A, GOOD)
    _write(repo, REG, _registry({"a": A}))
    res = _run_from(repo, base)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "first inventory" in res.stdout


def test_a_malformed_base_with_an_active_waiver_still_fails_closed(repo: Path) -> None:
    _write(repo, REG, _registry({"a": A}) + 'bypass = "yes"\n')
    base = _commit(repo, "unknown field on base")
    _new_field(repo, with_decision=True)
    res = _run_env(repo, json.dumps([["a", "bypass"]]), base=base)
    assert res.returncode == 1, res.stdout + res.stderr
    assert f"cannot read {REG} from the base commit" in res.stderr


def test_unexpected_input_is_one_finding_not_a_traceback(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.sentry import _ratchet

    def boom(*_args: object) -> None:
        raise RuntimeError("seeded")

    monkeypatch.setattr(_ratchet, "_check", boom)
    findings, _ = _ratchet.check(repo, "HEAD")
    assert findings == [
        "cannot complete the check: the registry or a baseline holds unexpected input"
    ]


# --- A1 after round 3: one reader for HEAD and BASE; the four real-CLI regressions --------------

ORPHAN = "tests/sentry/baselines/orphan.json"


def test_a_failed_head_listing_is_a_finding_not_an_empty_list(repo: Path) -> None:
    if os.geteuid() == 0:
        pytest.skip("root ignores directory permissions")
    _write(repo, ORPHAN, GOOD)
    _assert_red(repo, "not registered")  # the orphan is seen while the directory lists
    folder = repo / "tests/sentry/baselines"
    folder.chmod(0o111)  # files stay readable by name; listing gets EACCES
    try:
        res = _run(repo)
    finally:
        folder.chmod(0o755)
    assert res.returncode == 1, res.stdout + res.stderr
    assert "tests/sentry/baselines cannot be listed" in res.stderr


def test_a_head_baseline_directory_that_is_a_symlink_is_refused(
    repo: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    outside = tmp_path_factory.mktemp("outside") / "baselines"
    (repo / "tests/sentry/baselines").rename(outside)
    (repo / "tests/sentry/baselines").symlink_to(outside)
    res = _run(repo)
    assert res.returncode == 1, res.stdout + res.stderr
    assert f"a: baseline {A} cannot be read or is not a baseline file" in res.stderr


NUMERIC_ID = (
    '{"sentry_id": 1, "created_in": "S0", "entries": {"m::f": {"reason": "' + REASON + '"}}}'
)


def test_a_numeric_stored_identity_is_not_coerced_on_head(repo: Path) -> None:
    n = "tests/sentry/baselines/one.json"
    _write(repo, n, NUMERIC_ID)
    _write(repo, REG, _registry({"a": A, "1": n}))
    res = _run(repo)
    assert res.returncode == 1, res.stdout + res.stderr
    assert f"1: baseline {n} cannot be read or is not a baseline file" in res.stderr


def test_a_numeric_stored_identity_is_not_coerced_on_base(repo: Path) -> None:
    n = "tests/sentry/baselines/one.json"
    _write(repo, n, NUMERIC_ID)
    _write(repo, REG, _registry({"a": A, "1": n}))
    base = _commit(repo, "numeric identity on base")
    _write(repo, n, _baseline("1", ["m::f"]))
    res = _run_from(repo, base)
    assert res.returncode == 1, res.stdout + res.stderr
    assert f"cannot read {n} from the base commit" in res.stderr


@pytest.mark.parametrize("blank", ["", "  \n\t\n"], ids=["zero bytes", "whitespace"])
def test_an_empty_head_registry_fails_even_when_the_base_has_none(repo: Path, blank: str) -> None:
    _git(repo, "rm", "-q", REG, A)
    base = _commit(repo, "no registry and no baseline on base")
    _write(repo, REG, blank)
    res = _run_from(repo, base)
    assert res.returncode == 1, res.stdout + res.stderr
    assert f"registry: {REG} is empty" in res.stderr


def test_a_valid_first_inventory_passes_before_and_after_commit(repo: Path) -> None:
    _git(repo, "rm", "-q", REG, A)
    base = _commit(repo, "no registry and no baseline on base")
    _write(repo, A, GOOD)
    _write(repo, REG, _registry({"a": A}))
    assert _run_from(repo, base).returncode == 0
    committed = _commit(repo, "first inventory")
    assert _run_from(repo, committed).returncode == 0


def test_a_committed_orphan_baseline_fails_the_base_even_with_head_repaired(repo: Path) -> None:
    _write(repo, ORPHAN, GOOD)
    base = _commit(repo, "orphan on base")
    _git(repo, "rm", "-q", ORPHAN)
    res = _run_from(repo, base)
    assert res.returncode == 1, res.stdout + res.stderr
    assert res.stderr.count("ratchet: FAIL") == 1
    assert f"cannot read {ORPHAN} from the base commit" in res.stderr


def test_a_special_file_in_place_of_a_baseline_is_refused(repo: Path) -> None:
    (repo / A).unlink()
    os.mkfifo(repo / A)  # opening it would block, so the kind check must come first
    res = _run(repo)
    assert res.returncode == 1, res.stdout + res.stderr
    assert f"a: baseline {A} cannot be read or is not a baseline file" in res.stderr


def test_an_unreadable_listed_baseline_is_a_read_failure_not_absence(repo: Path) -> None:
    if os.geteuid() == 0:
        pytest.skip("root ignores file permissions")
    (repo / A).chmod(0o000)
    try:
        res = _run(repo)
    finally:
        (repo / A).chmod(0o644)
    assert res.returncode == 1, res.stdout + res.stderr
    assert f"a: baseline {A} cannot be read or is not a baseline file" in res.stderr
    assert "no baseline file" not in res.stderr


def test_an_unreadable_outside_sentry_parent_is_not_a_removal(repo: Path) -> None:
    if os.geteuid() == 0:
        pytest.skip("root ignores directory permissions")
    outside = "tests/other/test_leak.py"
    manifest = "tests/sentry/test_sentry_manifest.py"
    _write(repo, manifest, f"OUTSIDE_SENTRIES = ({outside!r},)\n")
    _write(repo, outside, "def test_x():\n    pass\n")
    base = _commit(repo, "outside sentry")
    (repo / "tests/other").chmod(0o000)
    try:
        res = _run_from(repo, base)
    finally:
        (repo / "tests/other").chmod(0o755)
    assert res.returncode == 1, res.stdout + res.stderr
    assert f"{outside}: sentry test file cannot be read at head" in res.stderr
    assert "was removed" not in res.stderr


def test_a_git_symlink_baseline_on_the_base_is_refused_even_if_its_text_is_valid(
    repo: Path,
) -> None:
    blob = subprocess.run(  # noqa: S603 - fixed argv, no shell
        ["git", "-C", str(repo), "hash-object", "-w", "--stdin"],  # noqa: S607
        input=GOOD,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    (repo / A).unlink()
    _git(repo, "update-index", "--add", "--cacheinfo", f"120000,{blob},{A}")
    _git(repo, "commit", "-q", "-m", "symlink baseline")
    base = _git(repo, "rev-parse", "HEAD")
    _git(repo, "rm", "-q", "--cached", A)
    _write(repo, A, GOOD)
    res = _run_from(repo, base)
    assert res.returncode == 1, res.stdout + res.stderr
    assert f"cannot read {A} from the base commit" in res.stderr


def test_an_unreadable_base_registry_is_not_a_first_inventory(repo: Path) -> None:
    _git(repo, "rm", "-q", A)
    (repo / REG).write_bytes(b"\xff\xfe")
    base = _commit(repo, "binary registry and no baseline on base")
    _write(repo, A, GOOD)
    _write(repo, REG, _registry({"a": A}))
    res = _run_from(repo, base)
    assert res.returncode == 1, res.stdout + res.stderr
    assert f"cannot read {REG} from the base commit" in res.stderr


FOLDER = "tests/sentry/baselines"


def _no_rows(repo: Path) -> None:
    _git(repo, "rm", "-r", "-q", "-f", FOLDER)
    _write(repo, REG, "# no sentries\n")


def test_a_file_at_the_baseline_folder_path_fails_the_base(repo: Path) -> None:
    _no_rows(repo)
    _write(repo, FOLDER, "not a folder\n")
    base = _commit(repo, "a file where the baseline folder belongs")
    (repo / FOLDER).unlink()
    res = _run_from(repo, base)
    assert res.returncode == 1, res.stdout + res.stderr
    assert f"cannot read {FOLDER} from the base commit" in res.stderr


def test_a_file_at_the_baseline_folder_path_fails_head(repo: Path) -> None:
    _no_rows(repo)
    base = _commit(repo, "no baselines on base")
    _write(repo, FOLDER, "not a folder\n")
    res = _run_from(repo, base)
    assert res.returncode == 1, res.stdout + res.stderr
    assert f"{FOLDER} cannot be listed" in res.stderr
