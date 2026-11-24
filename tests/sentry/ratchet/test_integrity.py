"""RG-E1: ``ratchet_check.py`` rejects every way to drop a guard, a sentry file or a registry row.

Each case builds a scratch git repo, commits a base, edits the tree and runs the real script.
Sentry ids, keys and decisions are synthetic. The decision rows written here live only in
``tmp_path`` repos; they are fixtures, not owner sign-offs.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.sentry import _ratchet
from tests.sentry.layout import REGISTRY_PATH_CASES
from tests.sentry.ratchet import safe_path, sentry_set
from tests.sentry.test_ratchet_check import (
    REG,
    ROOT,
    SCRIPT,
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
from tests.sentry.test_sentry_manifest import ROOT as _ROOT
from tests.sentry.test_sentry_manifest import SENTRIES, sentry_files

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


@pytest.mark.parametrize(
    "how, needle",
    [("delete", "registry file is missing"), ("empty", "registry has no [[sentry]] rows")],
)
def test_registry_required_after_last_baseline_removed(repo: Path, how: str, needle: str) -> None:
    (repo / A).unlink()
    if how == "delete":
        (repo / REG).unlink()
    else:
        _write(repo, REG, "")
    _assert_red(repo, needle)


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
    "path, safe", [c[1:] for c in REGISTRY_PATH_CASES], ids=[c[0] for c in REGISTRY_PATH_CASES]
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


# --- review round 1: empty inventories, retired ids, head commit, waiver input, one predicate ---


def test_removed_id_with_an_empty_inventory_needs_a_retirement(two: Path) -> None:
    _write(two, A, _baseline("a", []))
    _commit(two, "a is empty")
    _drop_a(two)
    _assert_red(two, "a: removed from the registry")


def test_removed_id_with_an_empty_inventory_and_a_retirement_passes(two: Path) -> None:
    _write(two, A, _baseline("a", []))
    _commit(two, "a is empty")
    _drop_a(two, _tables(retired={"a": DECISION}))
    res = _run(two)
    assert res.returncode == 0, res.stdout + res.stderr


def test_a_retirement_does_not_admit_a_first_inventory(two: Path) -> None:
    n = "tests/sentry/baselines/n.json"
    (two / A).unlink()
    _write(two, n, _baseline("n", ["m::f", "m::g"]))
    _write(two, REG, _registry({"b": B, "n": n}) + _tables(retired={"a": DECISION}))
    _assert_red(two, "adds key(s): m::f, m::g")


def test_a_retirement_with_an_empty_new_sentry_passes(two: Path) -> None:
    n = "tests/sentry/baselines/n.json"
    (two / A).unlink()
    _write(two, n, _baseline("n", []))
    _write(two, REG, _registry({"b": B, "n": n}) + _tables(retired={"a": DECISION}))
    res = _run(two)
    assert res.returncode == 0, res.stdout + res.stderr


def test_a_retired_base_baseline_must_still_be_readable(two: Path) -> None:
    _unlink_object(two, A)
    _drop_a(two, _tables(retired={"a": DECISION}))
    _assert_red(two, f"cannot read {A} from the base commit")


def test_untracked_copy_of_a_deleted_sentry_file_does_not_pass(
    with_sentry: tuple[Path, str],
) -> None:
    repo, base = with_sentry
    _git(repo, "rm", "-q", SENTRY)
    _commit(repo, "delete")
    _write(repo, SENTRY, SENTRY_BODY)  # on disk, in no commit
    _red_from(repo, base, f"{SENTRY}: sentry test file was removed")


def test_uncommitted_manifest_edit_cannot_restore_an_outside_entry(repo: Path) -> None:
    _write(repo, MANIFEST, _manifest((OUTSIDE,)))
    _write(repo, OUTSIDE, SENTRY_BODY)
    base = _commit(repo, "outside sentry")
    _write(repo, MANIFEST, _manifest(()))
    _commit(repo, "drop the list entry")
    _write(repo, MANIFEST, _manifest((OUTSIDE,)))  # not committed
    _red_from(repo, base, f"{OUTSIDE}: sentry test file was removed")


def _run_env(repo: Path, waiver: str | None, flag: bool = True) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k != "RATCHET_SCHEMA_WAIVER"}
    if waiver is not None:
        env["RATCHET_SCHEMA_WAIVER"] = waiver
    extra = ["--schema-waiver-env"] if flag else []
    return subprocess.run(  # noqa: S603 - fixed argv, no shell
        [sys.executable, str(SCRIPT), "--root", str(repo), "--base", "HEAD", *extra],
        capture_output=True,
        text=True,
        env=env,
    )


def _new_field(repo: Path, with_decision: bool) -> None:
    extra = 'bypass = "yes"\n'
    _write(repo, REG, _registry({"a": A}) + extra)
    if with_decision:
        text = _registry({"a": A}).rstrip("\n") + '\nbypass = "yes"\n\n'
        _write(repo, REG, text + _tables(checker_change={"bypass": DECISION}))


def test_exact_waiver_with_a_checker_change_row_passes_and_is_reported(repo: Path) -> None:
    _new_field(repo, with_decision=True)
    res = _run_env(repo, json.dumps([["a", "bypass"]]))
    assert res.returncode == 0, res.stdout + res.stderr
    assert "a: registry key bypass waived by checker_change" in res.stdout


@pytest.mark.parametrize("waiver", [None, '[["a","other"]]', '[["z","bypass"]]'])
def test_waiver_for_another_pair_still_fails(repo: Path, waiver: str | None) -> None:
    _new_field(repo, with_decision=True)
    res = _run_env(repo, waiver)
    assert res.returncode == 1, res.stdout + res.stderr
    assert "a: unknown registry key bypass" in res.stdout + res.stderr


@pytest.mark.parametrize("waiver", ["not json", '[["a"]]', '{"a": "bypass"}', '[["a", 1]]'])
def test_malformed_waiver_input_is_reported_on_a_clean_registry(repo: Path, waiver: str) -> None:
    res = _run_env(repo, waiver)
    assert res.returncode == 1, res.stdout + res.stderr
    assert "RATCHET_SCHEMA_WAIVER is not a JSON list of [id, field] pairs" in res.stderr


def test_inherited_waiver_does_not_admit_a_field_on_the_head_run(repo: Path) -> None:
    _new_field(repo, with_decision=True)
    res = _run_env(repo, json.dumps([["a", "bypass"]]), flag=False)
    assert res.returncode == 1, res.stdout + res.stderr
    assert "a: unknown registry key bypass" in res.stdout + res.stderr


def test_malformed_waiver_in_the_environment_is_ignored_on_the_head_run(repo: Path) -> None:
    res = _run_env(repo, "not json", flag=False)
    assert res.returncode == 0, res.stdout + res.stderr


def test_waiver_without_a_checker_change_row_fails(repo: Path) -> None:
    _new_field(repo, with_decision=False)
    res = _run_env(repo, json.dumps([["a", "bypass"]]))
    assert res.returncode == 1, res.stdout + res.stderr
    assert "a: unknown registry key bypass" in res.stdout + res.stderr


def test_sentry_membership_has_one_definition() -> None:
    everything = [p.relative_to(_ROOT).as_posix() for p in (_ROOT / "tests").rglob("*")]
    manifest = (_ROOT / "tests/sentry/test_sentry_manifest.py").read_text(encoding="utf-8")
    assert sentry_set(everything, manifest) == set(SENTRIES)
    assert sentry_files(_ROOT) == {p for p in SENTRIES if p.startswith("tests/sentry/")}


@pytest.mark.parametrize("reason", ["x" * 14, "x" * 15, "todo", "n/a", "reviewed on 2026-11-04"])
def test_reason_predicate_is_shared_by_baselines_and_decisions(reason: str) -> None:
    weak = _ratchet.weak_reason(reason)
    base = _ratchet.parse_baseline(_baseline("a", ["k"], reason=reason))
    assert bool(_ratchet.reason_findings("p", base)) is weak
    if len(reason) >= 10:
        assert (_ratchet.decision_problem(f"owner 2026-11-24 {reason}") is not None) is weak


def test_untracked_copy_of_a_listed_outside_sentry_does_not_pass(repo: Path) -> None:
    _write(repo, MANIFEST, _manifest((OUTSIDE,)))
    _write(repo, OUTSIDE, SENTRY_BODY)
    base = _commit(repo, "outside sentry")
    _git(repo, "rm", "-q", OUTSIDE)
    _commit(repo, "delete the file, keep the list entry")
    _write(repo, OUTSIDE, SENTRY_BODY)  # on disk, in no commit
    _red_from(repo, base, f"{OUTSIDE}: sentry test file was removed")


def test_waiver_covers_only_its_own_field(repo: Path) -> None:
    rows = _registry({"a": A}).rstrip("\n") + '\nbypass = "yes"\nextra = "yes"\n\n'
    both = {"bypass": DECISION, "extra": DECISION}
    _write(repo, REG, rows + _tables(checker_change=both))
    res = _run_env(repo, json.dumps([["a", "bypass"]]))
    assert res.returncode == 1, res.stdout + res.stderr
    assert "a: unknown registry key extra" in res.stdout + res.stderr
    assert "unknown registry key bypass" not in res.stdout + res.stderr


def test_a_base_retired_row_with_a_non_string_value_fails_closed(two: Path) -> None:
    _write(two, REG, _registry({"a": A, "b": B}) + '[retired]\n"a" = 5\n')
    base = _commit(two, "non-string sign-off on base")
    _drop_a(two, _tables(retired={"a": DECISION}))
    _red_from(two, base, f"cannot read {REG} from the base commit")


def test_a_base_checker_change_row_with_a_non_string_value_fails_closed(repo: Path) -> None:
    _write(repo, REG, _registry({"a": A}) + '[checker_change]\n"bypass" = 5\n')
    base = _commit(repo, "non-string row on base")
    _new_field(repo, with_decision=True)
    _red_from(repo, base, f"cannot read {REG} from the base commit")


GLOB = "test_*.py"
# test_gate_pins asks "does this directory hold any test file", which is not membership.
GLOB_EXEMPT = ("tests/sentry/test_gate_pins.py", "test_every_pinned_path_exists_and_is_a_test")


def _glob_sites(sources: dict[str, str]) -> list[tuple[str, str, str]]:
    """``(file, enclosing function, call text)`` of every call that passes the sentry glob literal
    as a positional or keyword argument."""
    sites: list[tuple[str, str, str]] = []

    def walk(node: ast.AST, path: str, func: str) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func = node.name
        if isinstance(node, ast.Call):
            args = [*node.args, *(k.value for k in node.keywords)]
            if any(isinstance(a, ast.Constant) and a.value == GLOB for a in args):
                sites.append((path, func, ast.unparse(node)))
        for child in ast.iter_child_nodes(node):
            walk(child, path, func)

    for path, text in sorted(sources.items()):
        walk(ast.parse(text), path, "")
    return sites


def _unexempt(sites: list[tuple[str, str, str]]) -> list[tuple[str, str, str]]:
    """Drop the one exempt call; a second call of any shape, even in that function, stays."""
    kept, seen = [], False
    for site in sites:
        if site[:2] == GLOB_EXEMPT and not seen and "rglob" in site[2]:
            seen = True
        else:
            kept.append(site)
    return kept


def test_no_second_sentry_membership_predicate_exists() -> None:
    sources = {
        p.relative_to(_ROOT).as_posix(): p.read_text(encoding="utf-8")
        for top in ("tests", "scripts")
        for p in (_ROOT / top).rglob("*.py")
    }
    assert _unexempt(_glob_sites(sources)) == []


EXEMPT_FUNC = "def test_every_pinned_path_exists_and_is_a_test():\n"


def test_guard_sees_the_keyword_form_of_the_glob() -> None:
    seeded = {"tests/x.py": 'def f(root):\n    return root.rglob(pattern="test_*.py")\n'}
    assert _unexempt(_glob_sites(seeded)) != []


def test_guard_sees_a_second_glob_in_the_exempt_file() -> None:
    gate_pins = GLOB_EXEMPT[0]
    seeded = {
        gate_pins: EXEMPT_FUNC
        + '    t.rglob("test_*.py")\n\ndef other(t):\n    t.rglob("test_*.py")\n'
    }
    assert [s[1] for s in _unexempt(_glob_sites(seeded))] == ["other"]


def test_guard_sees_a_second_glob_in_the_exempt_function() -> None:
    seeded = {GLOB_EXEMPT[0]: EXEMPT_FUNC + '    t.rglob("test_*.py")\n    t.glob("test_*.py")\n'}
    assert len(_unexempt(_glob_sites(seeded))) == 1


def test_guard_accepts_the_one_exempt_call() -> None:
    seeded = {GLOB_EXEMPT[0]: EXEMPT_FUNC + '    t.rglob("test_*.py")\n'}
    assert _unexempt(_glob_sites(seeded)) == []


# --- review round 4: approval strength, head-side read errors, malformed head registry ----------


@pytest.mark.parametrize(
    "weak",
    [
        "owner 2026-11-24 xxxxxxxxxx",
        "owner 2026-11-24 todo todo.",
        "owner 2026-11-24 12345678901234",
    ],
)
def test_a_weak_approved_growth_decision_is_refused(repo: Path, weak: str) -> None:
    _grow(repo, "m::new")
    _approve(repo, [("m::new", weak)])
    _assert_red(repo, "approved_growth for m::new needs a decision")


def test_an_approved_growth_decision_of_fifteen_chars_passes(repo: Path) -> None:
    _grow(repo, "m::new")
    _approve(repo, [("m::new", "owner 2026-11-24 123456789012345")])
    res = _run(repo)
    assert res.returncode == 0, res.stdout + res.stderr


def test_a_head_tree_read_failure_says_head(repo: Path) -> None:
    _write(repo, MANIFEST, _manifest(()))
    base = _commit(repo, "manifest")
    _write(repo, MANIFEST, _manifest((OUTSIDE,)))
    _commit(repo, "manifest changes")
    _unlink_object(repo, MANIFEST)
    res = _run_from(repo, base)
    assert res.returncode == 1, res.stdout + res.stderr
    assert f"cannot read {MANIFEST} from the head commit" in res.stderr


@pytest.mark.parametrize(
    "text",
    ["this is = = broken\n", "[sentry]\nid = 'a'\n", "sentry = [1]\n", "sentry = 'a'\n"],
    ids=["bad toml", "single table", "row not a table", "not an array"],
)
def test_a_malformed_head_registry_is_one_finding_not_a_traceback(repo: Path, text: str) -> None:
    _write(repo, REG, text)
    res = _run(repo)
    assert res.returncode == 1, res.stdout + res.stderr
    assert "Traceback" not in res.stderr
    assert "registry: scripts/dev/sentry_registry.toml" in res.stderr
