"""Sentry: one classifier maps a type to a column shape, and only named files call it.

`contracts/column_shape.py` owns `classify_column` (what the data is) and `declared_shape` (what an
F06 declaration says). Three files may call them: the profile walk, which records the observed
shape, the plan's assembler, which joins config facts with the profile and the schemas, and the
scan, which records each column's shape for the starter. A fourth caller is a second place that decides what a type means, so it fails here. Within the plan,
profile, strategy and declared-casting packages no other module tests an Arrow type for a date,
timestamp or decimal: that test is a shape decision and goes through the classifier.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "decoy_engine"
HOME = "contracts/column_shape.py"

# function -> {path under src/decoy_engine: reason}
ALLOWED_CALLERS: dict[str, dict[str, str]] = {
    "classify_column": {
        "profile/_walk.py": "records the observed shape of each profiled column",
        "plan/checks/_column_shapes.py": "classifies a source schema the profile has no entry for",
        "profiling/scan_set.py": "the scan records each column's observed shape for the starter",
    },
    "declared_shape": {
        "plan/checks/_column_shapes.py": "maps an F06 declaration to its shape",
    },
    # The profile layer's wrapper over `classify_column`: a caller of it reaches the classifier.
    "observed_shape": {
        "profile/_walk.py": "the walk records each column's shape",
        "profile/arrow/_walk_arrow.py": "the Arrow twin of the walk records the same shape",
    },
}


SHAPE_PACKAGES = ("plan", "profile", "execution/_strategies", "declared_casting")
SHAPE_PREDICATE = re.compile(r"^is_(date|timestamp|decimal)")


MODULE = "decoy_engine.contracts.column_shape"
# Where a wrapper over the classifier is defined: the module it is imported from, and its file.
WRAPPERS: dict[str, tuple[str, str]] = {
    "observed_shape": ("decoy_engine.profile._walk", "profile/_walk.py")
}


def _call_sites(root: Path, name: str) -> set[str]:
    """Files that call `name` as the one this package owns. The execution package has an
    unrelated `classify_column` for memory estimates, so a call counts only when the file got
    the name from its home module, by import or through the module. The defining file of a
    wrapper counts its own calls."""
    module, home_file = WRAPPERS.get(name, (MODULE, HOME))
    found: set[str] = set()
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        if rel == HOME:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = {
            (a.asname or a.name)
            for n in ast.walk(tree)
            if isinstance(n, ast.ImportFrom) and n.module == module
            for a in n.names
            if a.name == name
        }
        if rel == home_file and name in WRAPPERS:
            imported.add(name)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            if (isinstance(fn, ast.Name) and fn.id in imported) or (
                isinstance(fn, ast.Attribute)
                and fn.attr == name
                and ast.unparse(fn.value).endswith(module.rsplit(".", 1)[-1])
            ):
                found.add(rel)
    return found


def _predicate_uses(root: Path) -> list[str]:
    found: list[str] = []
    for package in SHAPE_PACKAGES:
        for path in sorted((root / package).rglob("*.py")):
            rel = path.relative_to(root).as_posix()
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Attribute) and SHAPE_PREDICATE.match(node.attr):
                    found.append(f"{rel}:{node.lineno}")
                elif isinstance(node, ast.ImportFrom):
                    found += [
                        f"{rel}:{node.lineno}" for a in node.names if SHAPE_PREDICATE.match(a.name)
                    ]
    return found


@pytest.mark.parametrize("name", sorted(ALLOWED_CALLERS))
def test_only_the_named_files_call_the_classifier(name: str) -> None:
    assert _call_sites(SRC, name) == set(ALLOWED_CALLERS[name])


def test_every_allowance_has_a_reason() -> None:
    assert all(r.strip() for rows in ALLOWED_CALLERS.values() for r in rows.values())


def test_no_other_module_decides_a_shape_from_an_arrow_predicate() -> None:
    assert _predicate_uses(SRC) == []


def test_the_sentry_catches_a_planted_caller(tmp_path: Path) -> None:
    probe = tmp_path / "profile" / "arrow" / "_walk_arrow.py"
    probe.parent.mkdir(parents=True)
    probe.write_text(
        "from decoy_engine.contracts.column_shape import classify_column\n"
        "def f(t):\n    return classify_column(source_format=None, arrow_type=t)\n",
        encoding="utf-8",
    )
    assert _call_sites(tmp_path, "classify_column") == {"profile/arrow/_walk_arrow.py"}


def test_the_sentry_catches_a_planted_wrapper_caller(tmp_path: Path) -> None:
    probe = tmp_path / "plan" / "_x.py"
    probe.parent.mkdir()
    probe.write_text(
        "from decoy_engine.profile._walk import observed_shape\nx = observed_shape(t, None)\n",
        encoding="utf-8",
    )
    assert _call_sites(tmp_path, "observed_shape") == {"plan/_x.py"}


def test_a_same_named_function_from_elsewhere_is_not_counted(tmp_path: Path) -> None:
    probe = tmp_path / "execution" / "_mem.py"
    probe.parent.mkdir()
    probe.write_text(
        "from decoy_engine.execution._mem_estimate_arrow import classify_column\n"
        "x = classify_column(t)\n",
        encoding="utf-8",
    )
    assert _call_sites(tmp_path, "classify_column") == set()


def test_the_sentry_catches_a_call_through_the_module(tmp_path: Path) -> None:
    probe = tmp_path / "execution" / "_p.py"
    probe.parent.mkdir()
    probe.write_text(
        "from decoy_engine.contracts import column_shape\n"
        "x = column_shape.classify_column(source_format=None, arrow_type=t)\n",
        encoding="utf-8",
    )
    assert _call_sites(tmp_path, "classify_column") == {"execution/_p.py"}


def test_the_sentry_catches_a_planted_predicate(tmp_path: Path) -> None:
    probe = tmp_path / "plan" / "checks" / "_required_settings.py"
    probe.parent.mkdir(parents=True)
    probe.write_text("import pyarrow as pa\nx = pa.types.is_date32(t)\n", encoding="utf-8")
    assert _predicate_uses(tmp_path) == ["plan/checks/_required_settings.py:2"]
