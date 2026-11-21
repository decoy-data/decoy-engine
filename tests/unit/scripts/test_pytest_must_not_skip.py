"""`scripts/ci/pytest_must_not_skip.py`: the one rule behind every companion-lane CI step.

A selection must collect, must not skip (except allow-listed nodes), and must pass. The
mutation cells flip one input each and expect the checker to go red.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from scripts.ci import pytest_must_not_skip as mns

REPO = Path(__file__).resolve().parents[3]


def _report(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "junit.xml"
    path.write_text(f"<testsuites><testsuite>{body}</testsuite></testsuites>", encoding="utf-8")
    return path


PASS = '<testcase classname="t.mod" name="test_a"/>'
SKIP = '<testcase classname="t.mod" name="test_b"><skipped message="needs x"/></testcase>'
XFAIL = (
    '<testcase classname="t.mod" name="test_c">'
    '<skipped type="pytest.xfail" message="known"/></testcase>'
)


def test_a_clean_report_holds(tmp_path: Path) -> None:
    assert mns.violations(_report(tmp_path, PASS + XFAIL)) == []


def test_mutation_an_empty_selection_goes_red(tmp_path: Path) -> None:
    assert mns.violations(_report(tmp_path, "")) == ["no tests were collected"]


def test_mutation_an_unexpected_skip_goes_red_whatever_its_path_or_reason_says(
    tmp_path: Path,
) -> None:
    found = mns.violations(_report(tmp_path, PASS + SKIP))
    assert len(found) == 1 and "t.mod::test_b" in found[0]


def test_an_allow_listed_node_may_skip_but_only_that_node(tmp_path: Path) -> None:
    report = _report(tmp_path, PASS + SKIP)
    assert mns.violations(report, ["*::test_b"]) == []
    assert mns.violations(report, ["*::test_other"]) != []


def _run(tmp_path: Path, test_source: str, *flags: str) -> subprocess.CompletedProcess[str]:
    case = tmp_path / "test_case.py"
    case.write_text(test_source, encoding="utf-8")
    cmd = [sys.executable, str(REPO / "scripts/ci/pytest_must_not_skip.py"), *flags]
    cmd += ["--", str(case), "-q", "-p", "no:cacheprovider", "--rootdir", str(tmp_path)]
    return subprocess.run(cmd, capture_output=True, text=True, cwd=tmp_path, check=False)  # noqa: S603 - fixed argv


def test_the_cli_exits_zero_on_a_clean_selection(tmp_path: Path) -> None:
    assert _run(tmp_path, "def test_ok():\n    pass\n").returncode == 0


def test_mutation_the_cli_exits_nonzero_when_a_test_skips(tmp_path: Path) -> None:
    src = "import pytest\n\n@pytest.mark.skip(reason='native')\ndef test_s():\n    pass\n"
    result = _run(tmp_path, src)
    assert result.returncode == 1 and "unexpected skip" in result.stdout


def test_the_cli_lets_an_allow_listed_skip_through(tmp_path: Path) -> None:
    src = "import pytest\n\n@pytest.mark.skip(reason='absent')\ndef test_s():\n    pass\n"
    src += "\ndef test_ok():\n    pass\n"
    assert _run(tmp_path, src, "--allow-skip", "*::test_s").returncode == 0
