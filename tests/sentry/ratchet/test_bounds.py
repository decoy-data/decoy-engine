"""RG-E2: ratchet bounds. A cap may not rise and a floor may not fall unless an owner decision
new in the diff names the key; a guard key (``sentry-limits``) may not be dropped either.

Each case builds a scratch git repo, commits a base, edits the tree and runs the real script.
Sentry ids, keys and decisions are synthetic fixtures, not owner sign-offs. ``# red-before``
tests fail on the pre-slice checker; ``# pin`` tests guard against over-blocking.
"""

from __future__ import annotations

import ast
import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from tests.sentry import _ratchet
from tests.sentry.ratchet import _limit_constants as lc
from tests.sentry.ratchet.test_integrity import _commit, _red_from, _run_from
from tests.sentry.test_baseline_registry import UPPER, module_int_constants, refused_constants
from tests.sentry.test_ratchet_check import REG, ROOT, A, _assert_red, _run, _write

D1 = "owner 2026-11-24 the cap rises because a reviewed module grew"
D2 = "owner 2026-11-24 reworded text that must not re-arm an old approval"
GUARD = "sentry-limits"
LIM = f"tests/sentry/baselines/{GUARD}.json"
GOAL = "test_module_size.py::GOAL"
FLOOR = "test_outbound_clients.py::WALK_FLOOR"
NEW = "layout/test_new.py::NEW_LIMIT"
REASON = "reviewed on 2026-11-24, tracked for removal"


def _bl(sid: str, entries: dict[str, dict[str, int]]) -> str:
    body = {k: {"reason": REASON, **bound} for k, bound in entries.items()}
    return json.dumps({"sentry_id": sid, "created_in": "S0", "entries": body})


def _reg(rows: dict[str, tuple[str, list[tuple[str, str]]]], tables: str = "") -> str:
    out = ""
    for sid, (path, approvals) in rows.items():
        out += f'[[sentry]]\nid = "{sid}"\nbaseline = "{path}"\n'
        if approvals:
            body = ", ".join(f'{{ key = "{k}", decision = "{d}" }}' for k, d in approvals)
            out += f"approved_growth = [{body}]\n"
        out += "\n"
    return out + tables


def _retired_growth(sid: str, rows: list[tuple[str, str]]) -> str:
    body = ", ".join(f'{{ key = "{k}", decision = "{d}" }}' for k, d in rows)
    return f'[retired_growth]\n"{sid}" = [{body}]\n'


def _limits_repo(
    repo: Path,
    entries: dict[str, dict[str, int]],
    approvals: list[tuple[str, str]] | None = None,
    sid: str = "sentry-limits",
) -> Path:
    """Replace the fixture sentry with one bounded sentry and commit it as the base."""
    (repo / A).unlink()
    path = f"tests/sentry/baselines/{sid}.json"
    _write(repo, path, _bl(sid, entries))
    _write(repo, REG, _reg({sid: (path, approvals or [])}))
    _commit(repo, "bounded base")
    return repo


def _set(
    repo: Path, entries: dict[str, dict[str, int]], approvals: Sequence[tuple[str, str]] = ()
) -> None:
    _write(repo, LIM, _bl("sentry-limits", entries))
    _write(repo, REG, _reg({"sentry-limits": (LIM, list(approvals))}))


BASE = {GOAL: {"max": 600}, FLOOR: {"min": 146}}


# --- raised ceilings ---------------------------------------------------------------------------


def test_max_raise_with_approved_growth_passes(repo: Path) -> None:  # red-before
    _limits_repo(repo, {"m::f": {"max": 5}}, sid="a")
    _write(repo, A, _bl("a", {"m::f": {"max": 6}}))
    _write(repo, REG, _reg({"a": (A, [("m::f", D1)])}))
    res = _run(repo)
    assert res.returncode == 0, res.stdout + res.stderr
    assert f"approved raise m::f ({D1})" in res.stdout


def test_max_raise_with_approval_already_on_base_fails(repo: Path) -> None:  # pin
    _limits_repo(repo, {"m::f": {"max": 5}}, [("m::f", D1)], sid="a")
    _write(repo, A, _bl("a", {"m::f": {"max": 6}}))
    _assert_red(repo, "max raised or dropped for key(s): m::f")


def test_reworded_base_approval_does_not_exempt_a_raise(repo: Path) -> None:  # pin
    _limits_repo(repo, {"m::f": {"max": 5}}, [("m::f", D1)], sid="a")
    _write(repo, A, _bl("a", {"m::f": {"max": 6}}))
    _write(repo, REG, _reg({"a": (A, [("m::f", D2)])}))
    _assert_red(repo, "max raised or dropped for key(s): m::f")


def _raise_real(repo: Path, sid: str) -> None:
    """Base is the committed baseline as it is today; head adds one to a key's ``max``."""
    name = f"{sid}.json"
    doc = json.loads((ROOT / "tests/sentry/baselines" / name).read_text(encoding="utf-8"))
    (repo / A).unlink()
    path = f"tests/sentry/baselines/{name}"
    _write(repo, path, json.dumps(doc))
    _write(repo, REG, _reg({sid: (path, [])}))
    _commit(repo, "real baseline")
    key = sorted(doc["entries"])[0]
    doc["entries"][key]["max"] = doc["entries"][key].get("max", 0) + 1
    _write(repo, path, json.dumps(doc))
    _assert_red(repo, "max raised or dropped for key(s)")


def test_module_size_ceiling_raise_needs_approval(repo: Path) -> None:  # red-before
    _raise_real(repo, "module-size")


def test_log_interpolation_count_raise_needs_approval(repo: Path) -> None:  # red-before
    _raise_real(repo, "log-interpolation")


def test_locator_waiver_count_raise_needs_approval(repo: Path) -> None:  # red-before
    _raise_real(repo, "locator-waivers")


def test_limit_raise_without_approval_fails(repo: Path) -> None:  # AT-RI5, red-before
    _limits_repo(repo, BASE)
    _set(repo, {GOAL: {"max": 650}, FLOOR: {"min": 146}})
    _assert_red(repo, f"max raised or dropped for key(s): {GOAL}")


def test_floor_lowered_without_approval_fails(repo: Path) -> None:  # red-before
    _limits_repo(repo, BASE)
    _set(repo, {GOAL: {"max": 600}, FLOOR: {"min": 140}})
    _assert_red(repo, f"min lowered or dropped for key(s): {FLOOR}")


def test_floor_lowered_with_a_fresh_approval_passes(repo: Path) -> None:  # red-before
    _limits_repo(repo, BASE)
    _set(repo, {GOAL: {"max": 600}, FLOOR: {"min": 140}}, [(FLOOR, D1)])
    res = _run(repo)
    assert res.returncode == 0, res.stdout + res.stderr
    assert f"approved raise {FLOOR} ({D1})" in res.stdout


def test_floor_raised_passes(repo: Path) -> None:  # pin
    _limits_repo(repo, BASE)
    _set(repo, {GOAL: {"max": 600}, FLOOR: {"min": 150}})
    res = _run(repo)
    assert res.returncode == 0, res.stdout + res.stderr


# --- guard keys --------------------------------------------------------------------------------


def test_removed_limit_key_needs_approval(repo: Path) -> None:  # red-before
    _limits_repo(repo, BASE)
    _set(repo, {GOAL: {"max": 600}})
    _assert_red(repo, f"guard key {FLOOR} was dropped without a fresh approved_growth row")


def test_fresh_guard_deletion_passes_then_merged_approval_is_not_stale(
    repo: Path,
) -> None:  # red-before
    _limits_repo(repo, BASE)
    _set(repo, {GOAL: {"max": 600}}, [(FLOOR, D1)])
    first = _run(repo)
    assert first.returncode == 0, first.stdout + first.stderr
    assert f"approved guard removal {FLOOR} ({D1})" in first.stdout
    _commit(repo, "deletion merged")
    _set(repo, {GOAL: {"max": 590}}, [(FLOOR, D1)])  # the next PR keeps the row and lowers a cap
    res = _run(repo)
    assert res.returncode == 0, res.stdout + res.stderr


def test_stray_fresh_approval_for_a_key_that_never_existed_fails(repo: Path) -> None:  # pin
    _limits_repo(repo, BASE)
    _set(repo, BASE, [("layout/test_gone.py::GONE", D1)])
    _assert_red(repo, "stale approved_growth, layout/test_gone.py::GONE")


def test_added_limit_key_is_not_growth(repo: Path) -> None:  # red-before
    _limits_repo(repo, BASE)
    _set(repo, {**BASE, NEW: {"max": 7}})
    res = _run(repo)
    assert res.returncode == 0, res.stdout + res.stderr


def test_added_key_on_an_ordinary_sentry_is_still_growth(repo: Path) -> None:  # pin
    _limits_repo(repo, {"m::f": {"max": 5}}, sid="a")
    _write(repo, A, _bl("a", {"m::f": {"max": 5}, "m::new": {"max": 1}}))
    _assert_red(repo, "m::new")


def _two_sentries(repo: Path) -> Path:
    """Base with the guard and a second sentry, so retiring the guard leaves a registry."""
    _limits_repo(repo, BASE)
    _write(repo, A, _bl("a", {"m::f": {"max": 5}}))
    _write(repo, REG, _reg({"sentry-limits": (LIM, []), "a": (A, [])}))
    _commit(repo, "second sentry")
    return repo


def _retire_guard(repo: Path, rows: list[tuple[str, str]], retired: bool = True) -> None:
    (repo / LIM).unlink(missing_ok=True)
    tables = ""
    if retired:
        tables += f'[retired]\n"sentry-limits" = "{D1}"\n\n'
    if rows:
        tables += _retired_growth("sentry-limits", rows)
    _write(repo, REG, _reg({"a": (A, [])}, tables))


def test_retired_guard_requires_every_lost_key_approval(repo: Path) -> None:  # red-before
    _two_sentries(repo)
    _retire_guard(repo, [(GOAL, D1)])
    _assert_red(repo, f"guard key {FLOOR} was dropped with its retired id without")
    _retire_guard(repo, [(GOAL, D1), (FLOOR, D1)])
    res = _run(repo)
    assert res.returncode == 0, res.stdout + res.stderr
    assert f"decision retired_growth sentry-limits {GOAL}" in res.stdout


def test_retired_guard_without_a_retired_decision_fails(repo: Path) -> None:  # red-before
    _two_sentries(repo)
    _retire_guard(repo, [(GOAL, D1), (FLOOR, D1)], retired=False)
    _assert_red(repo, "sentry-limits: guard sentry removed without a fresh [retired] decision")


def test_retired_growth_row_for_an_unretired_id_fails(repo: Path) -> None:  # red-before
    _two_sentries(repo)
    _write(
        repo,
        REG,
        _reg({"sentry-limits": (LIM, []), "a": (A, [])}, _retired_growth("a", [("m::f", D1)])),
    )
    _assert_red(repo, "retired_growth row for a m::f is not a lost key of a guard id retired")


def test_guard_sentry_renamed_with_a_dropped_key_fails(repo: Path) -> None:  # red-before
    _limits_repo(repo, BASE)
    (repo / LIM).unlink()
    path = "tests/sentry/baselines/sentry-limits-v2.json"
    _write(repo, path, _bl("sentry-limits-v2", {GOAL: {"max": 600}}))
    _write(repo, REG, _reg({"sentry-limits-v2": (path, [])}))
    _assert_red(repo, "sentry-limits: guard sentry removed without a fresh [retired] decision")


def test_a_second_pr_cannot_move_a_base_approval_into_retired_growth(
    repo: Path,
) -> None:  # red-before
    """An approval on base under ``approved_growth`` is not fresh when it reappears under
    ``retired_growth``: freshness compares (id, key) across both locations."""
    _limits_repo(repo, BASE, [(FLOOR, D1)])
    (repo / LIM).unlink()
    _write(repo, A, _bl("a", {"m::f": {"max": 5}}))
    tables = f'[retired]\n"sentry-limits" = "{D1}"\n\n' + _retired_growth(
        "sentry-limits", [(GOAL, D1), (FLOOR, D2)]
    )
    _write(repo, REG, _reg({"a": (A, [])}, tables))
    _assert_red(repo, f"guard key {FLOOR} was dropped with its retired id without")


# --- reading the live constants ----------------------------------------------------------------


REFUSAL = "{} must be one module-level NAME = <int> statement"


def test_read_int_handles_annassign_and_refuses_bool() -> None:  # red-before
    src = "PLAIN = 600\nTYPED: int = 601\n"
    assert lc.read_int(src, "PLAIN") == 600
    assert lc.read_int(src, "TYPED") == 601
    for line, name in [
        ("FLAG = True", "FLAG"),
        ("TEXT = '5'", "TEXT"),
        ("CALL = int('5')", "CALL"),
        ("GOAL = (600, 1)", "GOAL"),
        ("GOAL = 300 * 2", "GOAL"),
        ("MIN_ROWS = 59 - 1", "MIN_ROWS"),
        ("GOAL, OTHER = f()", "GOAL"),
        ("F = -True", "F"),
        ("X = 'a'", "MISSING"),
    ]:
        with pytest.raises(ValueError) as caught:
            lc.read_int(line + "\n", name)
        assert str(caught.value) == REFUSAL.format(name)
        assert module_int_constants({"test_x.py": line + "\n"}) == set()


def test_read_int_ignores_locals() -> None:  # pin
    local = "GOAL = 600\n\ndef f():\n    GOAL = 1\n    return [GOAL for GOAL in range(2)]\n"
    assert lc.read_int(local, "GOAL") == 600
    assert lc.read_int("GOAL = 600\nXS = [GOAL for GOAL in range(2)]\n", "GOAL") == 600


# One row per Python form that binds or hides a bound. ``map`` is the expected UPPER_CASE
# candidates: the int a plain name reads, or None for a refused one (fail closed, no value read).
CONSTANT_FORMS: dict[str, tuple[str, dict[str, int | None]]] = {
    "codex-r3-starred": (
        "TAIL = (58, 0)\n*prefix, MIN_ROWS, end = 0, 59, *TAIL\n",
        {"MIN_ROWS": None},
    ),
    "codex-r3-later-rebind": ("MIN_ROWS = 59\nMIN_ROWS = max(1, MIN_ROWS)\n", {"MIN_ROWS": None}),
    "codex-r3-subscript-rebind": (
        "MIN_ROWS = 59\ncounts = {}\ncounts[MIN_ROWS], MIN_ROWS = 1, 2\n",
        {"MIN_ROWS": None},
    ),
    "codex-r3-subscript-key": (
        "MIN_ROWS = 59\ncounts = {}\ncounts[MIN_ROWS], total = range(2)\n",
        {"MIN_ROWS": 59},
    ),
    "attribute target": (
        "MIN_ROWS = 59\nns = f()\nns.MIN_ROWS, total = 1, 2\n",
        {"MIN_ROWS": 59},
    ),
    "tuple literal": ("MIN_A, MIN_B = 59, 1186\n", {"MIN_A": None, "MIN_B": None}),
    "nested tuple": (
        "(A, (MIN_B, C)) = 1, (2, 3)\n",
        {"A": None, "C": None, "MIN_B": None},
    ),
    "tuple rebind": ("GOAL = 600\nGOAL, OTHER = 900, 1\n", {"GOAL": None, "OTHER": None}),
    "starred": ("*GOAL, B = 1, 2, 3\n", {"B": None, "GOAL": None}),
    "chained": ("OTHER = GOAL = 7\n", {"GOAL": None, "OTHER": None}),
    "augmented": ("GOAL = 600\nGOAL += 300\n", {"GOAL": None}),
    "augmented only": ("GOAL += 1\n", {"GOAL": None}),
    "walrus": ("GOAL = 600\n(GOAL := 900)\n", {"GOAL": None}),
    "walrus in comprehension": ("GOAL = 600\n[(GOAL := 9) for _ in [1]]\n", {"GOAL": None}),
    "for target": ("GOAL = 600\nfor GOAL in [900]:\n    pass\n", {"GOAL": None}),
    "for over a literal": ("for GOAL in range(3):\n    pass\n", {"GOAL": None}),
    "with target": ("GOAL = 600\nwith open('x') as GOAL:\n    pass\n", {"GOAL": None}),
    "first match capture": (
        "match 58:\n    case MIN_ROWS: pass\nassert len(rows) >= MIN_ROWS\n",
        {"MIN_ROWS": None},
    ),
    "wildcard overwrite": ("GOAL = 59\nfrom sentry_fixture import *\n", {"GOAL": None}),
    "subscript walrus": (
        "GOAL = 59\ncounts = {}\ncounts[(GOAL := 58)] = 0\n",
        {"GOAL": None},
    ),
    "import rebind": ("GOAL = 600\nfrom os import sep as GOAL\n", {"GOAL": None}),
    "def rebind": ("GOAL = 600\n\ndef GOAL():\n    pass\n", {"GOAL": None}),
    "except alias": (
        "GOAL = 600\ntry:\n    pass\nexcept Exception as GOAL:\n    pass\n",
        {"GOAL": None},
    ),
    "del": ("GOAL = 600\ndel GOAL\n", {"GOAL": None}),
    "global rebind": (
        "GOAL = 600\n\ndef f():\n    global GOAL\n    GOAL = 900\n",
        {"GOAL": None},
    ),
    "inside if": ("if True:\n    GOAL = 600\n", {"GOAL": None}),
    "second plain": ("GOAL = 600\nGOAL = 900\n", {"GOAL": None}),
    "bare annotation after": ("GOAL = 600\nGOAL: int\n", {"GOAL": None}),
    "wrong annotation": ("GOAL: float = 600\n", {"GOAL": None}),
    "unary plus": ("F = +5\n", {"F": None}),
    "double minus": ("F = --5\n", {"F": None}),
    "plain": ("GOAL = 600\n", {"GOAL": 600}),
    "annotated": ("GOAL: int = 601\n", {"GOAL": 601}),
    "negative": ("_F = -5\n", {"_F": -5}),
    "local of the same name": (
        "GOAL = 600\n\ndef f():\n    GOAL = 1\n    return [GOAL for GOAL in range(2)]\n",
        {"GOAL": 600},
    ),
    "module comprehension target": (
        "GOAL = 600\nXS = [GOAL for GOAL in range(2)]\n",
        {"GOAL": 600},
    ),
    "class attribute": ("GOAL = 600\n\nclass C:\n    GOAL = 1\n", {"GOAL": 600}),
}


@pytest.mark.parametrize("row", CONSTANT_FORMS, ids=list(CONSTANT_FORMS))
def test_constant_grammar_seed_table(row: str) -> None:  # red-before
    source, expected = CONSTANT_FORMS[row]
    upper = {n: v for n, v in lc.int_constants(ast.parse(source)).items() if UPPER.fullmatch(n)}
    assert upper == expected
    found = module_int_constants({"test_x.py": source})
    assert found == {("test_x.py", n) for n in expected}
    for name, value in expected.items():
        if value is None:
            with pytest.raises(ValueError) as caught:
                lc.read_int(source, name)
            assert str(caught.value) == REFUSAL.format(name)
        else:
            assert lc.read_int(source, name) == value
    assert refused_constants({"test_x.py": source}) == sorted(
        f"test_x.py::{n} must be one module-level NAME = <int> statement"
        for n, v in expected.items()
        if v is None
    )


def test_bound_loosened_reads_both_directions() -> None:  # red-before
    assert _ratchet.bound_loosened({"max": 6}, {"max": 5})
    assert _ratchet.bound_loosened({}, {"max": 5})
    assert _ratchet.bound_loosened({"min": 4}, {"min": 5})
    assert _ratchet.bound_loosened({}, {"min": 5})
    assert not _ratchet.bound_loosened({"max": 5}, {"max": 5})
    assert not _ratchet.bound_loosened({"min": 6}, {"min": 5})
    assert not _ratchet.bound_loosened({"max": 1, "min": 1}, {})


def test_unreachable_base_still_fails_closed_with_bounds(repo: Path) -> None:  # pin
    _limits_repo(repo, BASE)
    _red_from(repo, "0" * 40, "base commit not found")
    assert _run_from(repo, "HEAD").returncode == 0


# --- a guard successor, checked in process (GUARD_KEYS names one id, so no scratch repo has one) --


def _retire(heirs: list[dict[str, object]], rows: dict[str, str]) -> list[str]:
    helper = _ratchet._bounds()
    found, _ = helper.retired_guards_findings(
        ["g"],
        {"g": {"a::A": {"max": 5}, "b::B": {"min": 9}}},
        heirs,
        ({"g": rows}, {}),
        {"g"},
        _ratchet.bound_loosened,
    )
    return found


def test_a_guard_successor_retains_the_keys_it_holds_within_bound() -> None:  # red-before
    assert _retire([{"a::A": {"max": 5}, "b::B": {"min": 10}}], {}) == []


def test_a_guard_successor_with_a_loosened_bound_does_not_retain_the_key() -> None:  # red-before
    found = _retire([{"a::A": {"max": 6}, "b::B": {"min": 9}}], {})
    assert len(found) == 1 and "a::A was dropped with its retired id" in found[0]


def test_a_guard_successor_never_excuses_another_missing_key() -> None:  # red-before
    found = _retire([{"a::A": {"max": 5}}], {})
    assert len(found) == 1 and "b::B was dropped with its retired id" in found[0]


# --- the consumer of an imported bound ---------------------------------------------------------

HOME = "_faker_lock_lists"
IMPORT = "from tests.sentry.dependencies._faker_lock_lists import EN_US_DIGEST_FLOOR\n"
CONSUMERS = {
    "arithmetic": IMPORT + "def f(d):\n    assert len(d) >= EN_US_DIGEST_FLOOR - 1\n",
    "rebound after import": IMPORT + "EN_US_DIGEST_FLOOR = 252\n",
    "rebound in a branch": IMPORT + "if True:\n    EN_US_DIGEST_FLOOR = 1\n",
    "aliased import": "from tests.sentry.dependencies._faker_lock_lists import EN_US_DIGEST_FLOOR as F\n",
    "import from elsewhere": "from tests.sentry.other import EN_US_DIGEST_FLOOR\n",
    "attribute read": "import m\n\ndef f(d):\n    assert len(d) >= m.EN_US_DIGEST_FLOOR\n",
    "passed on": IMPORT + "def f(d):\n    assert len(d) >= min(EN_US_DIGEST_FLOOR, 1)\n",
    "walrus": IMPORT + "(EN_US_DIGEST_FLOOR := 1)\n",
}


@pytest.mark.parametrize("source", CONSUMERS.values(), ids=CONSUMERS.keys())
def test_a_consumer_that_lowers_or_shadows_the_bound_is_caught(source: str) -> None:  # red-before
    assert lc.consumer_problems(source, "EN_US_DIGEST_FLOOR", HOME)


def test_a_plain_consumer_and_a_non_consumer_pass() -> None:  # pin
    ok = IMPORT + "def f(d):\n    assert len(d) >= EN_US_DIGEST_FLOOR\n"
    assert lc.consumer_problems(ok, "EN_US_DIGEST_FLOOR", HOME) == []
    assert lc.consumer_problems("EN_US_DIGEST_FLOOR = 1\n", "EN_US_DIGEST_FLOOR", HOME) == []


@pytest.mark.parametrize("field_index", [0, 1], ids=["first_field", "second_field"])
def test_the_faker_consumer_enforces_the_recorded_floor(field_index: int) -> None:  # red-before
    """At the recorded floor the check passes; one pair below it fails, whichever of the two
    fields is invalidated. A consumer that counts only one field, lowers or re-derives the
    constant makes the second half pass and this test red."""
    import copy

    from tests.sentry.dependencies import _faker_output_lock_support as support

    floor = json.loads((ROOT / LIM).read_text("utf-8"))["entries"][
        "dependencies/_faker_lock_lists.py::EN_US_DIGEST_FLOOR"
    ]["min"]
    locales = copy.deepcopy(support._load_lock()["locales"])
    fields = support._fields("reflected")
    assert len(fields) == 2
    have = sum(all(len(c[f]) == 64 for f in fields) for c in locales["en_US"]["reflected"].values())
    assert have >= floor
    _degrade_to(locales, fields[field_index], fields, have - floor)
    support._check_anchors_and_floor(locales)
    _degrade_to(locales, fields[field_index], fields, 1)
    with pytest.raises(AssertionError):
        support._check_anchors_and_floor(locales)


def _degrade_to(locales: dict, field: str, fields: tuple[str, ...], count: int) -> None:
    from tests.sentry.dependencies._faker_lock_lists import ANCHORS

    anchors = {n for loc, s, n in ANCHORS if loc == "en_US" and s == "reflected"}
    done = 0
    for name, cell in locales["en_US"]["reflected"].items():
        if done == count:
            return
        if name not in anchors and all(len(cell[f]) == 64 for f in fields):
            cell[field] = "x"
            done += 1
    assert done == count


def test_read_int_reads_signed_literals() -> None:  # red-before
    assert lc.read_int("_F = -5\n", "_F") == -5
