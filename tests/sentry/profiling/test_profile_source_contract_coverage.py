"""Every reader class that defines `sample_frame` is in the conformance matrix (AT-0b).

A reader added later (Azure, SFTP) cannot merge until `READER_MATRIX` in
`tests/unit/profile/test_sample_frame_contract.py` lists it, and the matrix proves the
"short only at end of source" contract for it. The walk imports each module and counts a class
only in the module that defines it, so a re-export is not a second definition.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
import types

import pytest

from tests.unit.profile.test_sample_frame_contract import READER_MATRIX, SAMPLE_TABLE_MATRIX

ROOTS = ("decoy_engine.profile", "decoy_engine.profiling")


# Each reader method with the conformance matrix that must list every class defining it.
MATRICES = {"sample_frame": READER_MATRIX, "sample_table": SAMPLE_TABLE_MATRIX}


def owned_readers(modules: list[types.ModuleType], method: str = "sample_frame") -> set[str]:
    """Classes whose own body defines `method`, named `module.Class`. Protocols are
    interfaces, not readers."""
    found: set[str] = set()
    for module in modules:
        for obj in vars(module).values():
            if (
                inspect.isclass(obj)
                and obj.__module__ == module.__name__
                and method in obj.__dict__
                and not getattr(obj, "_is_protocol", False)
            ):
                found.add(f"{module.__name__}.{obj.__name__}")
    return found


def _scanned_modules() -> list[types.ModuleType]:
    modules: list[types.ModuleType] = []
    for root in ROOTS:
        package = importlib.import_module(root)
        modules.append(package)
        for info in pkgutil.walk_packages(package.__path__, prefix=f"{root}."):
            modules.append(importlib.import_module(info.name))
    return modules


@pytest.mark.parametrize("method", sorted(MATRICES))
def test_every_reader_is_in_the_conformance_matrix(method: str) -> None:
    assert owned_readers(_scanned_modules(), method) == set(MATRICES[method])


@pytest.mark.parametrize("method", sorted(MATRICES))
def test_a_reader_missing_from_the_matrix_is_caught(method: str) -> None:
    module = types.ModuleType("seeded_module")
    Seeded = type("Seeded", (), {method: lambda self, sample_rows: None})
    Seeded.__module__ = module.__name__
    module.Seeded = Seeded  # type: ignore[attr-defined]
    assert owned_readers([module], method) - set(MATRICES[method]) == {"seeded_module.Seeded"}
    other = next(m for m in MATRICES if m != method)
    assert owned_readers([module], other) == set()  # a class is judged by the method it defines


def test_a_re_export_is_not_a_second_definition() -> None:
    from decoy_engine.profile._cloud_readers import S3CsvSource

    module = types.ModuleType("reexport_module")
    module.S3CsvSource = S3CsvSource  # type: ignore[attr-defined]
    assert owned_readers([module]) == set()


def test_a_protocol_is_not_a_reader() -> None:
    from decoy_engine.profile import _readers

    assert "decoy_engine.profile._readers.ProfileSource" not in owned_readers([_readers])


@pytest.mark.parametrize("name", sorted(READER_MATRIX))
def test_matrix_names_resolve_to_classes(name: str) -> None:
    module_name, _, cls = name.rpartition(".")
    assert inspect.isclass(getattr(importlib.import_module(module_name), cls))
