"""NONFK-OOM choke points for the resident-fit decision (S4b).

G-4: the physical compiler only reads the stored verdict. Nothing under `execution/physical/`
imports the fact gatherer, the probe module or the host-memory detector.
G-8: one place builds the capacity refusal (`_errors.nonfk_full_frame_capacity_error`) and one
function compares the ceilings (`resident_fit_verdict`).

The scans cover the spellings a contributor would write by habit: plain, aliased, module and
attribute imports. Deliberate evasion is out of scope.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src" / "decoy_engine"
FORBIDDEN_NAMES = {"gather_resident_fit", "detect_effective_memory_bytes", "_probe"}
CODE_NAME = "NONFK_FULL_FRAME_CAPACITY_EXCEEDED"
BUILDER_FILE = SRC / "execution" / "_errors.py"
VERDICT_FILE = SRC / "execution" / "pipeline" / "_resident_fit.py"


def forbidden_imports(source: str) -> list[str]:
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom):
            parts = (node.module or "").split(".")
            names = {a.name for a in node.names}
            if FORBIDDEN_NAMES & (names | set(parts)):
                found.append(ast.unparse(node))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if FORBIDDEN_NAMES & set(alias.name.split(".")):
                    found.append(ast.unparse(node))
    return found


PHYSICAL = sorted((SRC / "execution" / "physical").glob("*.py"))


@pytest.mark.parametrize("path", PHYSICAL, ids=lambda p: p.name)
def test_g4_physical_modules_import_no_gatherer_probe_or_detector(path: Path) -> None:
    assert forbidden_imports(path.read_text(encoding="utf-8")) == []


@pytest.mark.parametrize(
    "source",
    [
        # mutation: call gather_resident_fit from _live_inputs.py
        "from decoy_engine.execution.pipeline._resident_fit import gather_resident_fit\n",
        "from decoy_engine.execution.pipeline._resident_fit import gather_resident_fit as g\n",
        "from decoy_engine.execution import _probe\n",
        "from decoy_engine.execution._probe import probe_peak_bytes\n",
        "import decoy_engine.execution._probe\n",
        "from decoy_engine.execution.out_of_core import detect_effective_memory_bytes as d\n",
        "from decoy_engine.execution.out_of_core._budget import detect_effective_memory_bytes\n",
    ],
)
def test_g4_seeded_imports_fail(source: str) -> None:
    assert forbidden_imports(source) != []


def refusal_constructions(source: str) -> list[int]:
    """Lines that build a coded error from the capacity code directly."""
    lines: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        callee = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
        mentions = any(
            isinstance(sub, ast.Attribute | ast.Name)
            and (getattr(sub, "attr", None) == CODE_NAME or getattr(sub, "id", None) == CODE_NAME)
            for kw in node.keywords
            for sub in ast.walk(kw.value)
        )
        if callee.endswith("Error") and mentions:
            lines.append(node.lineno)
    return lines


def test_g8_one_capacity_error_constructor() -> None:
    owners = {
        path.relative_to(SRC).as_posix(): refusal_constructions(path.read_text(encoding="utf-8"))
        for path in SRC.rglob("*.py")
    }
    built = {p: lines for p, lines in owners.items() if lines}
    assert list(built) == ["execution/_errors.py"]
    assert len(built["execution/_errors.py"]) == 1


@pytest.mark.parametrize(
    "source",
    [
        "raise ExecutionError(code=reasons.runtime.NONFK_FULL_FRAME_CAPACITY_EXCEEDED, message='')\n",
        "raise ExecutionError(message='', code=runtime.NONFK_FULL_FRAME_CAPACITY_EXCEEDED)\n",
        "e = mod.ExecutionError(code=NONFK_FULL_FRAME_CAPACITY_EXCEEDED)\n",
    ],
)
def test_g8_seeded_direct_constructions_fail(source: str) -> None:
    assert refusal_constructions(source) != []


def _uses(source: str, name: str) -> set[str]:
    """Names of the functions in `source` that mention `name`."""
    tree = ast.parse(source)
    users: set[str] = set()
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef):
            for sub in ast.walk(fn):
                if (isinstance(sub, ast.Name) and sub.id == name) or (
                    isinstance(sub, ast.Attribute) and sub.attr == name
                ):
                    users.add(fn.name)
    return users


def test_g8_only_the_verdict_function_compares_the_ceilings() -> None:
    verdict = VERDICT_FILE.read_text(encoding="utf-8")
    assert _uses(verdict, "admission_ceiling_bytes") == {"resident_fit_verdict"}
    assert _uses(verdict, "RESIDENT_ADMISSION_FRACTION") == {"admission_ceiling_bytes"}
    outside = [
        path.name
        for path in SRC.rglob("*.py")
        if path != VERDICT_FILE and "admission_ceiling_bytes" in path.read_text(encoding="utf-8")
    ]
    assert outside == []


def test_g8_the_runtime_phase_calls_the_verdict_and_the_shared_requirement() -> None:
    source = VERDICT_FILE.read_text(encoding="utf-8")
    assert "require_resident_fit" in _calls(source, "store_resident_fit")
    assert "resident_fit_verdict" in _calls(source, "gather_resident_fit")


def _calls(source: str, function: str) -> set[str]:
    for fn in ast.walk(ast.parse(source)):
        if isinstance(fn, ast.FunctionDef) and fn.name == function:
            return {
                c.func.id if isinstance(c.func, ast.Name) else getattr(c.func, "attr", "")
                for c in ast.walk(fn)
                if isinstance(c, ast.Call)
            }
    return set()
