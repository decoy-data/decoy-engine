"""The function-scoped physical-seam exception admits its units and nothing else."""

from __future__ import annotations

from pathlib import Path

from tests.sentry.layout._scoped_changes import (
    SCOPED_EXCEPTIONS,
    _units,
    changed_units,
    scoped_units,
)

ROOT = Path(__file__).resolve().parents[3]

OLD = '''"""Doc."""
import os
import resource

LIMIT = 1


def allowed(x):
    return x


def other(x):
    return x
'''


def test_an_unchanged_module_has_no_changed_unit() -> None:
    assert changed_units(OLD, OLD) == set()


def test_a_changed_function_is_reported_by_name() -> None:
    new = OLD.replace("def allowed(x):\n    return x", "def allowed(x):\n    return x + 1")
    assert changed_units(OLD, new) == {"allowed"}


def test_a_change_outside_the_entry_is_reported() -> None:
    new = OLD.replace("def other(x):\n    return x", "def other(x):\n    return None")
    assert changed_units(OLD, new) == {"other"}


def test_import_edits_group_into_one_unit() -> None:
    new = OLD.replace("import resource\n", "import signal\n")
    assert changed_units(OLD, new) == {"imports"}


def test_new_and_removed_units_are_reported() -> None:
    assert changed_units(OLD, OLD + "\nEXTRA = 2\n") == {"EXTRA"}
    assert changed_units(OLD, OLD.replace("LIMIT = 1\n", "")) == {"LIMIT"}
    assert changed_units(OLD, OLD + "\nif not WINDOWS:\n    X = 1\n") == {"if:not WINDOWS"}


def test_every_scoped_entry_names_a_file_and_a_reason() -> None:
    for rel, units in scoped_units().items():
        assert (ROOT / rel).is_file(), rel
        assert units
    assert all(len(reason) > 30 for reason in SCOPED_EXCEPTIONS.values())


def test_every_scoped_unit_exists_in_its_file() -> None:
    """A unit that no longer exists is dead: the entry must shrink instead of lingering."""
    for rel, units in scoped_units().items():
        live = set(_units((ROOT / rel).read_text(encoding="utf-8")))
        assert units <= live, sorted(units - live)
