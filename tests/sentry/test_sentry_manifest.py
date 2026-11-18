"""AT-CI1 and AT-CI2: the local gate runs every sentry in ``SENTRIES`` exactly once.

``SENTRIES`` is the glob ``tests/sentry/**/test_*.py`` plus ``OUTSIDE_SENTRIES``.

``scripts/dev/gates.sh`` runs ``SENTRY_PATHS`` with its own ``-m`` filter. A sentry outside
those paths, or one a marker filter deselects, never runs at merge time, so this test reads
the same settings from gates.sh and asks pytest what it would collect. One sentry,
``LAYER_TEST``, is ignored by the sentry step and owned by the ``layers`` step, which runs it in
its own venv (LAYOUT E3); the two routes must partition ``SENTRIES`` with no gap or overlap.
"""

from __future__ import annotations

import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from tests.sentry.parallel._resources import parse_marker_expr

ROOT = Path(__file__).resolve().parents[2]
GATES = ROOT / "scripts" / "dev" / "gates.sh"

# Named sentries that live outside tests/sentry/.
OUTSIDE_SENTRIES = (
    "tests/secret_providers/test_leak_sentry.py",
    "tests/secret_providers/test_classifier_equivalence.py",
)


def sentry_files(root: Path) -> set[str]:
    """Every sentry test file under ``tests/sentry``, nested folders included."""
    return {p.relative_to(root).as_posix() for p in (root / "tests" / "sentry").rglob("test_*.py")}


# By the CODEMAP rule every test file under tests/sentry/ is a sentry, so the glob is the list.
SENTRIES = (*sorted(sentry_files(ROOT)), *OUTSIDE_SENTRIES)


def _array(name: str, text: str) -> list[str] | None:
    m = re.search(rf"^{name}=\(([^)]*)\)", text, re.MULTILINE)
    return shlex.split(m.group(1), comments=True) if m else None


def gates_sentry_paths(text: str | None = None) -> list[str]:
    paths = _array("SENTRY_PATHS", GATES.read_text(encoding="utf-8") if text is None else text)
    assert paths is not None, "gates.sh has no SENTRY_PATHS array"
    return paths


def gates_marker_expr() -> str:
    return parse_marker_expr(GATES.read_text(encoding="utf-8"))


def gates_layer_test(text: str) -> str:
    m = re.search(r"^LAYER_TEST=(\S+)$", text, re.MULTILINE)
    assert m, "gates.sh has no LAYER_TEST"
    return m.group(1)


def gates_ignores(text: str) -> list[str]:
    """Every path ``LAYER_IGNORE`` excludes, with ``$LAYER_TEST`` resolved.

    The array goes through the same ``_array`` (shlex) parser as SENTRY_PATHS, and both pytest
    spellings count: ``--ignore=PATH`` and ``--ignore PATH``.
    """
    layer = gates_layer_test(text)
    tokens = _array("LAYER_IGNORE", text)
    assert tokens is not None, "gates.sh has no LAYER_IGNORE array"
    paths: list[str] = []
    rest = iter(tokens)
    for token in rest:
        paths.append(next(rest, token) if token == "--ignore" else token.removeprefix("--ignore="))
    return [p.replace("$LAYER_TEST", layer) for p in paths]


def stray_ignores(text: str) -> int:
    """How many ``--ignore`` flags gates.sh has outside the ``LAYER_IGNORE`` array."""
    outside = re.sub(r"^LAYER_IGNORE=\([^)]*\)", "", text, flags=re.MULTILINE)
    return len(re.findall(r"--ignore\b", outside))


def route_findings(text: str) -> list[str]:
    """Why the ordinary and isolated sentry routes in ``text`` do not partition SENTRIES."""
    layer = gates_layer_test(text)
    found = []
    if layer not in SENTRIES:
        found.append(f"LAYER_TEST {layer} is not in SENTRIES")
    if gates_ignores(text) != [layer]:
        found.append(f"the only --ignore must be LAYER_TEST, got {gates_ignores(text)}")
    if stray_ignores(text):
        found.append("an --ignore outside LAYER_IGNORE hides tests from the route check")
    if not re.search(r"\bSTEPS=\S*\blayers\b", text):
        found.append("the default step list has no layers step")
    step = re.search(r"^\s+layers\) cmd=\(layer_step\b", text, re.MULTILINE)
    runs = re.search(
        r'^layer_step\(\) \{\n(?:.*\n)*?.*-m pytest "\$@" "\$LAYER_TEST"\n\}', text, re.MULTILINE
    )
    if not (step and runs):
        found.append("no layers step runs exactly $LAYER_TEST")
    if not re.search(r'\$\{LAYER_IGNORE\[@\]\+"\$\{LAYER_IGNORE\[@\]\}"\} \$\{SENTRY_PATHS', text):
        found.append("the sentry step does not apply LAYER_IGNORE")
    return found


def uncovered(sentries: tuple[str, ...], paths: list[str]) -> list[str]:
    return [
        s for s in sentries if not any(s == p or s.startswith(p.rstrip("/") + "/") for p in paths)
    ]


def test_outside_sentries_exist_and_the_manifest_has_no_duplicate() -> None:
    assert [s for s in OUTSIDE_SENTRIES if not (ROOT / s).is_file()] == []
    assert len(set(SENTRIES)) == len(SENTRIES)


def test_gates_sentry_paths_cover_every_sentry() -> None:
    assert uncovered(SENTRIES, gates_sentry_paths()) == []


def test_removing_a_sentry_path_is_detected() -> None:
    """AT-CI2: dropping a path from SENTRY_PATHS makes the coverage check fail."""
    paths = gates_sentry_paths()
    assert paths, "SENTRY_PATHS is empty"
    for dropped in paths:
        rest = [p for p in paths if p != dropped]
        assert uncovered(SENTRIES, rest), f"dropping {dropped} went unnoticed"
    seeded = (*SENTRIES, "tests/policy/test_seeded.py")
    assert uncovered(seeded, paths) == ["tests/policy/test_seeded.py"]


@pytest.fixture(scope="module")
def collected() -> set[str]:
    ignores = [f"--ignore={p}" for p in gates_ignores(GATES.read_text(encoding="utf-8"))]
    cmd = [
        sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider",
        "-m", gates_marker_expr(), *ignores, *gates_sentry_paths(),
    ]  # fmt: skip
    res = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)  # noqa: S603 - fixed argv, no shell
    assert res.returncode == 0, res.stdout[-2000:] + res.stderr[-2000:]
    return {line.split("::")[0] for line in res.stdout.splitlines() if "::" in line}


def test_gates_step_collects_every_sentry(collected: set[str]) -> None:
    layer = gates_layer_test(GATES.read_text(encoding="utf-8"))
    assert [s for s in SENTRIES if s not in collected and s != layer] == []
    assert layer not in collected, "the sentry step must not run the layer test"


def test_the_sentry_and_layers_routes_partition_the_sentries() -> None:
    assert route_findings(GATES.read_text(encoding="utf-8")) == []


def test_ignore_parse_reads_both_spellings() -> None:
    """``--ignore PATH`` and ``--ignore=PATH`` both reach the route check."""
    base = "LAYER_TEST=tests/sentry/a.py\n"
    for array in ("(--ignore $LAYER_TEST --ignore b.py)", "(--ignore=$LAYER_TEST --ignore=b.py)"):
        assert gates_ignores(f"{base}LAYER_IGNORE={array}\n") == ["tests/sentry/a.py", "b.py"]


def test_a_broken_route_split_is_detected() -> None:
    """AT-8: removing the layers step or ignoring a second sentry is red."""
    text = GATES.read_text(encoding="utf-8")
    no_step = re.sub(r"^\s+layers\) cmd=\(layer_step.*\n", "", text, flags=re.MULTILINE)
    assert "no layers step runs exactly $LAYER_TEST" in route_findings(no_step)
    no_default = re.sub(r"(STEPS=\S*?),layers", r"\1", text)
    assert "the default step list has no layers step" in route_findings(no_default)
    second = text.replace(
        "LAYER_IGNORE=(--ignore=$LAYER_TEST)",
        "LAYER_IGNORE=(--ignore=$LAYER_TEST --ignore=tests/sentry/test_ci_config.py)",
    )
    assert any("only --ignore" in f for f in route_findings(second))
    spaced = text.replace(
        "LAYER_IGNORE=(--ignore=$LAYER_TEST)",
        "LAYER_IGNORE=(--ignore $LAYER_TEST --ignore tests/sentry/test_ci_config.py)",
    )
    assert any("only --ignore" in f for f in route_findings(spaced))
    stray = text.replace(
        "LAYER_IGNORE=(--ignore=$LAYER_TEST)\n",
        "LAYER_IGNORE=(--ignore=$LAYER_TEST)\nX=(--ignore tests/sentry/test_ci_config.py)\n",
    )
    assert stray != text
    assert any("outside LAYER_IGNORE" in f for f in route_findings(stray))
    unignored = text.replace(
        '${LAYER_IGNORE[@]+"${LAYER_IGNORE[@]}"} ${SENTRY_PATHS', "${SENTRY_PATHS"
    )
    assert "the sentry step does not apply LAYER_IGNORE" in route_findings(unignored)


def test_a_nested_new_sentry_is_picked_up(tmp_path: Path) -> None:
    """AT-E1: the glob descends into sub-folders, so a new nested sentry needs no list edit."""
    nested = tmp_path / "tests" / "sentry" / "layout"
    nested.mkdir(parents=True)
    (nested / "test_new.py").write_text("", encoding="utf-8")
    assert sentry_files(tmp_path) == {"tests/sentry/layout/test_new.py"}
