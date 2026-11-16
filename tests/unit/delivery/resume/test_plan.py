"""AT-P1 to AT-P5: `plan_resume`, the pure keep and rerun decision.

Plan `f23-plan` 4.7 and 7.1 (slice E2). The decision is a function of the stored run record, the
current fingerprint and table entries, and one `TableCheck` per table, so each cell builds those
by hand and asserts the plan or the refusal field.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from decoy_engine.delivery.resume import (
    ResumeRefusedError,
    RunFingerprint,
    RunRecord,
    TableCheck,
    TableEntry,
    plan_resume,
)
from decoy_engine.reason_adapter import reason_from_exception
from decoy_engine.reasons.decoy import (
    RESUME_CHECKPOINT_INVALID,
    RESUME_FINGERPRINT_CHANGED,
    RESUME_SOURCE_CHANGED,
)

OK = TableCheck(record_valid=True, artifact_ok=True, source_ok=True, path_ok=True)
NO_RECORD = TableCheck(record_valid=False, artifact_ok=False, source_ok=False, path_ok=False)
BAD_ARTIFACT = TableCheck(record_valid=True, artifact_ok=False, source_ok=True, path_ok=True)
SOURCE_CHANGED = TableCheck(record_valid=True, artifact_ok=True, source_ok=False, path_ok=True)


def _digest(kind: str, index: int) -> str:
    return "sha256:" + f"{kind}{index}".encode().hex().ljust(64, "0")[:64]


def _entries(count: int = 5) -> tuple[TableEntry, ...]:
    return tuple(TableEntry(i, _digest("n", i), _digest("b", i)) for i in range(count))


def _fingerprint() -> RunFingerprint:
    return RunFingerprint(
        config_hash="c" * 64,
        components=(("decoy-cli", "1.0.0"), ("decoy-engine", "0.23.0")),
        key_check="0123456789abcdef",
        key_version="v1",
        chunk_size=50000,
    )


def _stored(entries: tuple[TableEntry, ...] | None = None) -> RunRecord:
    return RunRecord(
        run_id="20261116T101500123456Z-0a1b2c3d",
        invocation_id="0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d",
        operation_id="run-0a1b2c3d",
        route="chunked",
        fingerprint=_fingerprint(),
        tables=_entries() if entries is None else entries,
    )


def _refusal(*args: Any) -> ResumeRefusedError:
    with pytest.raises(ResumeRefusedError) as caught:
        plan_resume(*args)
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    return caught.value


def test_keep_and_rerun() -> None:
    """AT-P1: records for tables 1 to 3 of 5 keep 1 to 3 and rerun 4 and 5."""
    checks = {0: OK, 1: OK, 2: OK}
    plan = plan_resume(_stored(), _fingerprint(), _entries(), checks)
    assert plan.keep == (0, 1, 2)
    assert plan.rerun == (3, 4)
    assert plan.warnings == ()


def test_keep_rule_has_no_relationship_closure() -> None:
    """A later table with a record is kept even when an earlier one has none."""
    plan = plan_resume(_stored(), _fingerprint(), _entries(), {1: OK, 3: OK})
    assert plan.keep == (1, 3)
    assert plan.rerun == (0, 2, 4)


def test_an_invalid_record_reruns_without_a_warning() -> None:
    plan = plan_resume(_stored(), _fingerprint(), _entries(), {0: OK, 1: NO_RECORD, 2: OK})
    assert plan.keep == (0, 2)
    assert plan.rerun == (1, 3, 4)
    assert plan.warnings == ()


def test_nothing_to_rerun_keeps_every_table() -> None:
    """A crash between the last record and the bind leaves a store with nothing left to run."""
    plan = plan_resume(_stored(), _fingerprint(), _entries(), dict.fromkeys(range(5), OK))
    assert plan.keep == (0, 1, 2, 3, 4)
    assert plan.rerun == ()


def test_no_tables_plans_nothing() -> None:
    plan = plan_resume(_stored(()), _fingerprint(), (), {})
    assert (plan.keep, plan.rerun, plan.warnings) == ((), (), ())


_FINGERPRINT_CHANGES = {
    "config_hash": "d" * 64,
    "components": (("decoy-cli", "1.0.1"), ("decoy-engine", "0.23.0")),
    "key_check": "fedcba9876543210",
    "key_version": "v2",
    "chunk_size": 25000,
}


@pytest.mark.parametrize("name", sorted(_FINGERPRINT_CHANGES))
def test_fingerprint_refusal(name: str) -> None:
    """AT-P2: each fingerprint field that differs alone refuses, and names that field."""
    current = dataclasses.replace(_fingerprint(), **{name: _FINGERPRINT_CHANGES[name]})
    error = _refusal(_stored(), current, _entries(), dict.fromkeys(range(5), OK))
    assert error.code == RESUME_FINGERPRINT_CHANGED
    assert error.field == name


def test_fingerprint_refusal_covers_every_fingerprint_field() -> None:
    names = {f.name for f in dataclasses.fields(RunFingerprint)}
    assert names == set(_FINGERPRINT_CHANGES)


def test_binding_refusal() -> None:
    """AT-P2: a table binding that differs refuses with `bindings`."""
    current = list(_entries())
    current[2] = dataclasses.replace(current[2], binding_digest=_digest("changed", 2))
    error = _refusal(_stored(), _fingerprint(), tuple(current), {0: OK, 1: OK, 2: OK})
    assert error.code == RESUME_FINGERPRINT_CHANGED
    assert error.field == "bindings"


def test_a_moved_placed_path_refuses_with_bindings() -> None:
    """AT-P2: a stored table whose placed path differs from the current plan's refuses with
    `bindings`, ahead of a source change on another table. M-P2c: ignore `path_ok`."""
    moved = dataclasses.replace(OK, path_ok=False)
    error = _refusal(_stored(), _fingerprint(), _entries(), {0: OK, 1: moved, 2: SOURCE_CHANGED})
    assert error.code == RESUME_FINGERPRINT_CHANGED
    assert error.field == "bindings"
    # No record means no kept file, so there is no path to compare.
    assert plan_resume(_stored(), _fingerprint(), _entries(), {0: OK, 1: NO_RECORD}).rerun == (
        1,
        2,
        3,
        4,
    )


def test_a_run_level_difference_wins_over_a_table_one() -> None:
    current = dataclasses.replace(_fingerprint(), chunk_size=1)
    changed = list(_entries())
    changed[0] = dataclasses.replace(changed[0], binding_digest=_digest("changed", 0))
    error = _refusal(_stored(), current, tuple(changed), {})
    assert error.field == "chunk_size"


def test_source_changed_refuses() -> None:
    """AT-P3: a changed or a missing source refuses, whatever the other tables say."""
    # The caller folds "changed" and "missing" into one `source_ok=False`; either position refuses.
    for index in (0, 4):
        error = _refusal(_stored(), _fingerprint(), _entries(), {index: SOURCE_CHANGED})
        assert error.code == RESUME_SOURCE_CHANGED
        assert error.field is None
    both = TableCheck(record_valid=True, artifact_ok=False, source_ok=False, path_ok=True)
    assert _refusal(_stored(), _fingerprint(), _entries(), {0: both}).code == RESUME_SOURCE_CHANGED


def test_a_source_check_means_nothing_without_a_record() -> None:
    """No record: the table runs from the current source, so its source check is not asked."""
    plan = plan_resume(_stored(), _fingerprint(), _entries(), {0: NO_RECORD})
    assert plan.rerun == (0, 1, 2, 3, 4)


def test_artifact_bad_reruns() -> None:
    """AT-P4: a missing or a digest-mismatched kept file reruns the table with the warning."""
    checks = {0: OK, 1: BAD_ARTIFACT, 2: OK, 3: BAD_ARTIFACT, 4: OK}
    plan = plan_resume(_stored(), _fingerprint(), _entries(), checks)
    assert plan.keep == (0, 2, 4)
    assert plan.rerun == (1, 3)
    assert [(w.code, w.index) for w in plan.warnings] == [
        (RESUME_CHECKPOINT_INVALID, 1),
        (RESUME_CHECKPOINT_INVALID, 3),
    ]


def test_table_set_changed() -> None:
    """AT-P5: a renamed table, an added or dropped table and a reordered set all refuse."""
    entries = _entries()
    renamed = list(entries)
    renamed[1] = dataclasses.replace(renamed[1], name_digest=_digest("renamed", 1))
    swapped = list(entries)
    swapped[0], swapped[1] = swapped[1], swapped[0]
    reindexed = [
        dataclasses.replace(entries[0], index=1),
        dataclasses.replace(entries[1], index=0),
        *entries[2:],
    ]
    cases = {
        "renamed": tuple(renamed),
        "reordered": tuple(swapped),
        "swapped_indexes": tuple(reindexed),
        "dropped": entries[:-1],
        "added": (*entries, TableEntry(5, _digest("n", 5), _digest("b", 5))),
    }
    for name, current in cases.items():
        error = _refusal(_stored(), _fingerprint(), current, dict.fromkeys(range(5), OK))
        assert (error.code, error.field) == (RESUME_FINGERPRINT_CHANGED, "tables"), name


def test_a_missing_check_is_a_table_without_a_record() -> None:
    plan = plan_resume(_stored(), _fingerprint(), _entries(), {4: OK})
    assert (plan.keep, plan.rerun) == ((4,), (0, 1, 2, 3))


def test_the_refusal_is_value_free_and_registered() -> None:
    error = ResumeRefusedError(RESUME_FINGERPRINT_CHANGED, "bindings")
    assert str(error) == "resume refused: resume_fingerprint_changed (bindings)"
    assert str(ResumeRefusedError(RESUME_SOURCE_CHANGED)) == "resume refused: resume_source_changed"
    rebuild, args, *_ = error.__reduce__()
    clone = rebuild(*args)
    assert (clone.code, clone.field) == (error.code, error.field)
    with pytest.raises(ValueError, match="invalid reason code"):
        ResumeRefusedError("resume_not_a_code")
    with pytest.raises(ValueError, match="invalid reason code"):
        ResumeRefusedError("not a code\n")
    for bad in ("Bindings", "bind ings", "a" * 40, "bindings\n", "/etc/passwd", ""):
        with pytest.raises(ValueError, match="invalid field"):
            ResumeRefusedError(RESUME_SOURCE_CHANGED, bad)


def test_the_refusal_maps_to_its_registered_reason() -> None:
    # The CLI reads the outcome through the adapter, never a copy of the code string.
    record = reason_from_exception(ResumeRefusedError(RESUME_FINGERPRINT_CHANGED, "bindings"))
    assert record.code == RESUME_FINGERPRINT_CHANGED
