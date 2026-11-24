"""RG-E1: ``ratchet_check.py`` rejects every way to drop a guard, a sentry file or a registry row.

Each case builds a scratch git repo, commits a base, edits the tree and runs the real script.
Sentry ids, keys and decisions are synthetic. The decision rows written here live only in
``tmp_path`` repos; they are fixtures, not owner sign-offs.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.sentry.layout import BASELINE_PATH_CASES
from tests.sentry.ratchet._integrity import safe_path
from tests.sentry.test_ratchet_check import (
    REG,
    ROOT,
    SCRIPT,
    A,
    _assert_red,
    _baseline,
    _git,
    _registry,
    _run,
    _write,
)

B = "tests/sentry/baselines/b.json"
DECISION = "owner 2026-11-24 sentry superseded by another rule"
BASELINE_DIR = "tests/sentry/baselines"


def _commit(repo: Path, message: str = "step") -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _tables(**tables: dict[str, str]) -> str:
    """TOML text for decision tables such as ``[retired]``; keys are quoted."""
    out = ""
    for name, rows in tables.items():
        out += f"[{name}]\n" + "".join(f'"{k}" = "{v}"\n' for k, v in rows.items()) + "\n"
    return out


def _run_from(repo: Path, base: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed argv, no shell
        [sys.executable, str(SCRIPT), "--root", str(repo), "--base", base],
        capture_output=True,
        text=True,
    )


def _red_from(repo: Path, base: str, needle: str) -> None:
    res = _run_from(repo, base)
    assert res.returncode == 1, res.stdout + res.stderr
    assert needle in res.stdout + res.stderr


@pytest.fixture
def two(repo: Path) -> Path:
    """Base with two registered inventories, ``a`` and ``b``."""
    _write(repo, B, _baseline("b", ["m::h"]))
    _write(repo, REG, _registry({"a": A, "b": B}))
    _commit(repo, "second inventory")
    return repo


def _drop_a(repo: Path, extra: str = "") -> None:
    (repo / A).unlink()
    _write(repo, REG, _registry({"b": B}) + extra)


# --- removed ids ------------------------------------------------------------------------------


def test_removed_registry_row_without_retirement_fails(two: Path) -> None:
    _drop_a(two)
    _assert_red(two, "a: removed from the registry")


def test_removed_row_with_unrelated_empty_new_sentry_fails(two: Path) -> None:
    (two / A).unlink()
    z = "tests/sentry/baselines/z.json"
    _write(two, z, _baseline("z", []))
    _write(two, REG, _registry({"b": B, "z": z}))
    _assert_red(two, "a: removed from the registry")


def test_removed_registry_row_with_dated_retirement_passes(two: Path) -> None:
    _drop_a(two, _tables(retired={"a": DECISION}))
    res = _run(two)
    assert res.returncode == 0, res.stdout + res.stderr


def test_row_replaced_by_new_id_keeping_keys_passes(two: Path) -> None:
    _write(two, A, _baseline("a2", ["m::f", "m::g"]))
    _write(two, REG, _registry({"a2": A, "b": B}))
    res = _run(two)
    assert res.returncode == 0, res.stdout + res.stderr


def _two_donors(repo: Path, a_keys: list[str], b_keys: list[str]) -> None:
    _write(repo, A, _baseline("a", a_keys))
    _write(repo, B, _baseline("b", b_keys))
    _write(repo, REG, _registry({"a": A, "b": B}))
    _commit(repo, "donors")


def test_two_removed_ids_cannot_share_one_successor_key(repo: Path) -> None:
    _two_donors(repo, ["m::f"], ["m::f"])
    (repo / B).unlink()
    (repo / A).unlink()
    c = "tests/sentry/baselines/c.json"
    _write(repo, c, _baseline("c", ["m::f"]))
    _write(repo, REG, _registry({"c": c}))
    _assert_red(repo, "m::f has more than one removed donor")


def test_split_cannot_copy_one_allowance_to_two_successors(repo: Path) -> None:
    (repo / A).unlink()
    c1, c2 = "tests/sentry/baselines/c1.json", "tests/sentry/baselines/c2.json"
    _write(repo, c1, _baseline("c1", ["m::f"]))
    _write(repo, c2, _baseline("c2", ["m::f", "m::g"]))
    _write(repo, REG, _registry({"c1": c1, "c2": c2}))
    _assert_red(repo, "m::f")


def test_split_dividing_one_inventory_passes(repo: Path) -> None:
    (repo / A).unlink()
    c1, c2 = "tests/sentry/baselines/c1.json", "tests/sentry/baselines/c2.json"
    _write(repo, c1, _baseline("c1", ["m::f"]))
    _write(repo, c2, _baseline("c2", ["m::g"]))
    _write(repo, REG, _registry({"c1": c1, "c2": c2}))
    assert _run(repo).returncode == 0


def test_restored_id_requires_fresh_retirement(two: Path) -> None:
    # The sign-off is already on the base table; the row was restored and is dropped again.
    _write(two, REG, _registry({"a": A, "b": B}) + _tables(retired={"a": DECISION}))
    _commit(two, "restored")
    _drop_a(two, _tables(retired={"a": DECISION}))
    _assert_red(two, "a: removed from the registry")


def test_restored_file_requires_fresh_retirement(repo: Path) -> None:
    gone = "tests/sentry/test_gone.py"
    _write(repo, gone, "def test_x() -> None:\n    pass\n")
    _write(repo, REG, _registry({"a": A}) + _tables(retired_files={gone: DECISION}))
    _commit(repo, "restored file")
    (repo / gone).unlink()
    _assert_red(repo, f"{gone}: sentry test file was removed")


@pytest.mark.parametrize("text", ["owner 2026-11-24 todo", "owner 2026-11-24 short text"])
def test_retirement_with_placeholder_reason_fails(two: Path, text: str) -> None:
    _drop_a(two, _tables(retired={"a": text}))
    _assert_red(two, "retired a:")


# --- the registry file itself -------------------------------------------------------------------


def test_deleted_registry_file_fails(repo: Path) -> None:
    (repo / REG).unlink()
    _assert_red(repo, "registry")


def test_emptied_registry_file_fails(repo: Path) -> None:
    _write(repo, REG, "")
    _assert_red(repo, "registry")


@pytest.mark.parametrize("how", ["delete", "empty"])
def test_registry_required_after_last_baseline_removed(repo: Path, how: str) -> None:
    (repo / A).unlink()
    if how == "delete":
        (repo / REG).unlink()
    else:
        _write(repo, REG, "")
    res = _run(repo)
    assert res.returncode == 1, res.stdout + res.stderr
    assert "registry" in res.stdout + res.stderr


# --- sentry files -------------------------------------------------------------------------------

SENTRY = "tests/sentry/test_alpha.py"
SENTRY_BODY = "def test_alpha() -> None:\n    assert 1 + 1 == 2\n"


@pytest.fixture
def with_sentry(repo: Path) -> tuple[Path, str]:
    _write(repo, SENTRY, SENTRY_BODY)
    return repo, _commit(repo, "sentry file")


def test_deleted_sentry_file_fails(with_sentry: tuple[Path, str]) -> None:
    repo, base = with_sentry
    _git(repo, "rm", "-q", SENTRY)
    _commit(repo, "delete")
    _red_from(repo, base, f"{SENTRY}: sentry test file was removed")


def test_renamed_sentry_file_passes(with_sentry: tuple[Path, str]) -> None:
    repo, base = with_sentry
    _git(repo, "mv", SENTRY, "tests/sentry/test_beta.py")
    _commit(repo, "rename")
    res = _run_from(repo, base)
    assert res.returncode == 0, res.stdout + res.stderr


def test_sentry_file_renamed_out_of_the_sentry_set_fails(with_sentry: tuple[Path, str]) -> None:
    repo, base = with_sentry
    (repo / "tests/unit").mkdir(parents=True)
    _git(repo, "mv", SENTRY, "tests/unit/test_alpha.py")
    _commit(repo, "rename out")
    _red_from(repo, base, f"{SENTRY}: sentry test file was removed")


MANIFEST = "tests/sentry/test_sentry_manifest.py"
OUTSIDE = "tests/other/test_leak.py"


def _manifest(entries: tuple[str, ...]) -> str:
    return f"OUTSIDE_SENTRIES = {entries!r}\n"


def test_deleted_outside_sentry_file_with_its_list_entry_fails(repo: Path) -> None:
    _write(repo, MANIFEST, _manifest((OUTSIDE,)))
    _write(repo, OUTSIDE, SENTRY_BODY)
    base = _commit(repo, "outside sentry")
    _git(repo, "rm", "-q", OUTSIDE)
    _write(repo, MANIFEST, _manifest(()))
    _commit(repo, "drop both")
    _red_from(repo, base, f"{OUTSIDE}: sentry test file was removed")


def test_outside_sentry_dropped_from_the_list_but_kept_on_disk_fails(repo: Path) -> None:
    _write(repo, MANIFEST, _manifest((OUTSIDE,)))
    _write(repo, OUTSIDE, SENTRY_BODY)
    base = _commit(repo, "outside sentry")
    _write(repo, MANIFEST, _manifest(()))
    _commit(repo, "drop the list entry")
    _red_from(repo, base, f"{OUTSIDE}: sentry test file was removed")


def test_deleted_sentry_file_with_fresh_retired_files_decision_passes(
    with_sentry: tuple[Path, str],
) -> None:
    repo, base = with_sentry
    (repo / SENTRY).unlink()
    _write(repo, REG, _registry({"a": A}) + _tables(retired_files={SENTRY: DECISION}))
    _commit(repo, "retire file")
    res = _run_from(repo, base)
    assert res.returncode == 0, res.stdout + res.stderr


# --- registry schema ----------------------------------------------------------------------------


def test_unknown_registry_key_fails(repo: Path) -> None:
    _write(repo, REG, _registry({"a": A}) + 'bypass = "yes"\n')
    _assert_red(repo, "a: unknown registry key bypass")


def test_unknown_top_level_table_is_ignored(repo: Path) -> None:
    _write(repo, REG, _registry({"a": A}) + "[future]\nx = 1\n")
    res = _run(repo)
    assert res.returncode == 0, res.stdout + res.stderr


@pytest.mark.parametrize("table", ["retired", "retired_files", "checker_change"])
def test_decision_table_value_must_be_a_decision_string(repo: Path, table: str) -> None:
    _write(repo, REG, _registry({"a": A}) + _tables(**{table: {"x": "not a decision"}}))
    _assert_red(repo, f"{table} x:")


def test_decision_with_a_trailing_newline_is_refused(repo: Path) -> None:
    text = "owner 2026-11-24 enough reason text\\n"  # a TOML escape, so the value ends in a newline
    _write(repo, REG, _registry({"a": A}) + _tables(retired={"x": text}))
    _assert_red(repo, "retired x:")


# --- baseline paths -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path, safe", [c[1:] for c in BASELINE_PATH_CASES], ids=[c[0] for c in BASELINE_PATH_CASES]
)
def test_safe_path_table(path: str, safe: bool) -> None:
    assert safe_path(path, BASELINE_DIR) is safe


@pytest.mark.parametrize(
    "bad, where",
    [
        ("tests/sentry/baselines/../../src/x.json", "tests/src/x.json"),
        ("tests/sentry/baselines/a\\b.json", "tests/sentry/baselines/a\\b.json"),
    ],
    ids=["dotdot", "backslash"],
)
def test_dotdot_and_backslash_below_baseline_dir_fail(repo: Path, bad: str, where: str) -> None:
    _write(repo, where, _baseline("n", ["m::one"]))
    _write(repo, REG, _registry({"a": A, "n": bad.replace("\\", "\\\\")}))
    _assert_red(repo, "is outside")


def test_absolute_and_outside_baseline_paths_fail(repo: Path) -> None:
    _write(repo, "docs/example.json", _baseline("n", ["m::one"]))
    _write(repo, "tests/sentry/baselines-old/x.json", _baseline("o", ["m::two"]))
    absolute = str(repo / "docs/example.json")
    for sid, path in (
        ("n", "docs/example.json"),
        ("o", "tests/sentry/baselines-old/x.json"),
        ("p", absolute),
    ):
        _write(repo, REG, _registry({"a": A, sid: path}))
        res = _run(repo)
        assert res.returncode == 1, (path, res.stdout, res.stderr)
        assert "is outside" in res.stdout + res.stderr


# --- reads of the base tree fail closed ---------------------------------------------------------


def _unlink_object(repo: Path, rel: str) -> None:
    sha = _git(repo, "rev-parse", f"HEAD:{rel}")
    (repo / ".git" / "objects" / sha[:2] / sha[2:]).unlink()


def test_listed_base_registry_read_failure_fails(repo: Path) -> None:
    _unlink_object(repo, REG)
    _assert_red(repo, f"cannot read {REG} from the base commit")


def test_listed_base_baseline_read_failure_fails(repo: Path) -> None:
    _unlink_object(repo, A)
    _write(repo, A, _baseline("a", []))
    _assert_red(repo, f"cannot read {A} from the base commit")


def test_unreachable_base_sha_fails(repo: Path) -> None:
    res = _run_from(repo, "0" * 40)
    assert res.returncode == 1, res.stdout + res.stderr
    assert "base commit not found" in res.stdout + res.stderr


# --- new baselines and the decision report ------------------------------------------------------


def test_new_baseline_without_created_in_fails(repo: Path) -> None:
    n = "tests/sentry/baselines/n.json"
    _write(repo, n, json.dumps({"sentry_id": "n", "entries": {"m::one": {"reason": "r" * 20}}}))
    _write(repo, REG, _registry({"a": A, "n": n}))
    _assert_red(repo, "n.json: new baseline has no created_in")


def test_baseline_already_on_base_may_lack_created_in(repo: Path) -> None:
    _write(repo, A, json.dumps({"sentry_id": "a", "entries": {"m::f": {"reason": "r" * 20}}}))
    _commit(repo, "old baseline without the field")
    assert _run(repo).returncode == 0


def test_new_decision_rows_are_reported(two: Path) -> None:
    other = "owner 2026-11-24 checker field added for the test"
    _drop_a(two, _tables(retired={"a": DECISION}, checker_change={"x": other}))
    res = _run(two)
    assert res.returncode == 0, res.stdout + res.stderr
    assert f"ratchet: decision retired a: {DECISION}" in res.stdout
    assert f"ratchet: decision checker_change x: {other}" in res.stdout


def test_decision_row_already_on_base_is_not_reported_again(two: Path) -> None:
    _write(two, REG, _registry({"a": A, "b": B}) + _tables(checker_change={"x": DECISION}))
    _commit(two, "decision on base")
    res = _run(two)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "decision checker_change" not in res.stdout


def test_live_registry_passes_against_origin_main() -> None:
    res = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [sys.executable, str(SCRIPT), "--root", str(ROOT)], capture_output=True, text=True
    )
    if res.returncode == 2:
        pytest.skip("no merge base with origin/main in this checkout")
    assert res.returncode == 0, res.stdout + res.stderr
