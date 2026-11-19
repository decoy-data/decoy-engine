"""AT-11: every field a profile output type can hold has exactly one basis class.

Three roots are walked: the profile document (`profiling.types.ColumnProfile`), the persisted scan
core (`ScanSetCore`) and the planner profile (`profile._types.Profile`). A field added to any of
them without an entry in `FIELD_BASIS` fails here, so a number counted over a sample cannot land
without a decision about what it covers.
"""

from __future__ import annotations

import dataclasses
import typing
from collections.abc import Mapping
from typing import Any, get_type_hints

from pydantic import BaseModel, create_model

from decoy_engine.profile import _types as planner
from decoy_engine.profiling import _scan_core
from decoy_engine.profiling._basis import CARRIERS, FIELD_BASIS, BasisClass
from decoy_engine.profiling.types import ColumnProfile as DocumentProfile
from decoy_engine.profiling.types import FieldStats

ROOTS: dict[str, type] = {
    "document": DocumentProfile,
    "scan_core": _scan_core.ScanSetCore,
    "planner": planner.Profile,
}


def _is_model(obj: Any) -> bool:
    return isinstance(obj, type) and (dataclasses.is_dataclass(obj) or issubclass(obj, BaseModel))


def _hints(cls: type) -> dict[str, Any]:
    if issubclass(cls, BaseModel):
        return {name: info.annotation for name, info in cls.model_fields.items()}
    return get_type_hints(cls)


def _inner(hint: Any) -> list[type]:
    found = [hint] if _is_model(hint) else []
    for arg in typing.get_args(hint):
        found.extend(_inner(arg))
    return found


def reach(root: type) -> list[type]:
    """`root` and every model or dataclass nested in its field types, in discovery order."""
    found: list[type] = []

    def visit(cls: type) -> None:
        if cls in found:
            return
        found.append(cls)
        for hint in _hints(cls).values():
            for nested in _inner(hint):
                visit(nested)

    visit(root)
    return found


def check(
    root_name: str, root: type, registry: Mapping[tuple[str, str, str], BasisClass]
) -> list[str]:
    """Every reason `registry` does not cover `root` exactly, as names only."""
    problems: list[str] = []
    classes = reach(root)
    names = [c.__name__ for c in classes]
    problems += [f"two classes named {n}" for n in sorted(set(names)) if names.count(n) > 1]
    reached = {(root_name, c.__name__, f) for c in classes for f in _hints(c)}
    held = {k for k in registry if k[0] == root_name}
    problems += [f"unclassified {k[1]}.{k[2]}" for k in sorted(reached - held)]
    problems += [f"stale entry {k[1]}.{k[2]}" for k in sorted(held - reached)]
    carrier = CARRIERS[root_name]
    below = {c.__name__ for c in classes}
    needing = {k[1] for k in held if registry[k] in (BasisClass.SCANNED, BasisClass.CHECKED)}
    problems += [f"{t} is not under the carrier of {root_name}" for t in sorted(needing - below)]
    if registry.get(carrier) is not BasisClass.LABEL:
        problems.append(f"carrier {carrier} is not a labelled field")
    return problems


def test_every_reached_field_has_one_class_and_every_entry_is_reached() -> None:
    for name, root in ROOTS.items():
        assert check(name, root, FIELD_BASIS) == [], name


def test_the_carrier_of_each_root_is_a_real_field() -> None:
    for name, (root, type_name, field) in CARRIERS.items():
        assert root == name
        assert (root, type_name, field) in FIELD_BASIS
        assert any(c.__name__ == type_name and field in _hints(c) for c in reach(ROOTS[name]))


def test_a_field_added_to_the_document_stats_fails() -> None:
    hints = get_type_hints(FieldStats)
    extra = dataclasses.make_dataclass(
        "FieldStats",
        [
            (f.name, hints[f.name], dataclasses.field(default=None))
            for f in dataclasses.fields(FieldStats)
        ]
        + [("extra", int, dataclasses.field(default=None))],
    )
    root = dataclasses.make_dataclass("ColumnProfile", [("fields", list[extra])])  # type: ignore[valid-type]
    assert "unclassified FieldStats.extra" in check("document", root, FIELD_BASIS)


def test_a_field_added_to_a_scan_core_model_fails() -> None:
    fields: dict[str, Any] = {
        n: (i.annotation, i) for n, i in _scan_core.FieldCore.model_fields.items()
    }
    fields["extra"] = (int, 0)
    bigger = create_model("FieldCore", __config__=_scan_core.FieldCore.model_config, **fields)
    table = create_model("TableCore", fields=(list[bigger], ...))  # type: ignore[valid-type]
    root = create_model("ScanSetCore", tables=(list[table], ...))  # type: ignore[valid-type]
    assert "unclassified FieldCore.extra" in check("scan_core", root, FIELD_BASIS)


def test_a_field_added_to_the_planner_column_fails() -> None:
    hints = get_type_hints(planner.ColumnProfile)
    extra = dataclasses.make_dataclass(
        "ColumnProfile",
        [(f.name, hints[f.name]) for f in dataclasses.fields(planner.ColumnProfile)]
        + [("extra", int)],
        frozen=True,
    )
    table = dataclasses.make_dataclass("TableProfile", [("columns", tuple[extra, ...])])  # type: ignore[valid-type]
    root = dataclasses.make_dataclass("Profile", [("tables", tuple[table, ...])])  # type: ignore[valid-type]
    assert "unclassified ColumnProfile.extra" in check("planner", root, FIELD_BASIS)


def test_a_root_reaching_two_classes_with_one_name_fails() -> None:
    one = dataclasses.make_dataclass("Row", [("a", int)])
    two = dataclasses.make_dataclass("Row", [("b", int)])
    root = dataclasses.make_dataclass("Profile", [("x", one), ("y", two)])
    assert "two classes named Row" in check("planner", root, FIELD_BASIS)


def test_dropping_the_root_from_the_key_makes_the_two_column_profiles_collide() -> None:
    collapsed: dict[tuple[str, str], set[BasisClass]] = {}
    for (_, type_name, field), cls in FIELD_BASIS.items():
        collapsed.setdefault((type_name, field), set()).add(cls)
    assert collapsed[("ColumnProfile", "row_count")] == {BasisClass.LABEL, BasisClass.SOURCE}


def test_a_missing_registry_entry_fails() -> None:
    trimmed = dict(FIELD_BASIS)
    del trimmed[("scan_core", "TableCore", "key_candidates")]
    assert "unclassified TableCore.key_candidates" in check(
        "scan_core", ROOTS["scan_core"], trimmed
    )
