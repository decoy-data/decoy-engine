"""Run pytest and enforce one rule: the selection must collect, must not skip, must pass.

CI steps that exist to prove a companion-gated test ran use this instead of grepping pytest's
output. It reads the junit XML pytest writes, so a skip is found by its test node and not by
words in a path or reason. A skip is allowed only when its node matches an `--allow-skip` glob
(the companion-absent cells that are meant to skip with the companion present). `--require-companion`
fails the step when the native companion did not load, so a green run cannot be an empty one.

    python scripts/ci/pytest_must_not_skip.py --require-companion \\
        --allow-skip '*::test_without_the_real_companion_*' -- tests/parity/native -q

Node keys are `<junit classname>::<test name>`, for example
`tests.parity.test_x.TestY::test_z[param]`. xfail outcomes are not skips.
"""

from __future__ import annotations

import argparse
import fnmatch
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from pathlib import Path


def violations(junit_xml: Path, allow_skip: Sequence[str] = ()) -> list[str]:
    """Return every way the report breaks the rule (empty list means it holds)."""
    cases = list(ET.parse(junit_xml).getroot().iter("testcase"))  # noqa: S314 - the report is pytest's own output
    problems: list[str] = []
    if not cases:
        problems.append("no tests were collected")
    for case in cases:
        key = f"{case.get('classname', '')}::{case.get('name', '')}"
        for skipped in case.findall("skipped"):
            if skipped.get("type") == "pytest.xfail":
                continue
            if not any(fnmatch.fnmatchcase(key, pat) for pat in allow_skip):
                reason = skipped.get("message", "")
                problems.append(f"unexpected skip: {key} ({reason})")
    return problems


def companion_problem() -> str | None:
    from decoy_engine.execution.native._companion_status import native_companion_status

    status = native_companion_status()
    return None if status.ok else f"the native companion did not load: {status}"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--allow-skip", action="append", default=[], metavar="GLOB")
    parser.add_argument("--require-companion", action="store_true")
    parser.add_argument("pytest_args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    pytest_args = [a for a in args.pytest_args if a != "--"]

    if args.require_companion and (problem := companion_problem()):
        print(f"FAIL: {problem}")
        return 1
    with tempfile.TemporaryDirectory() as tmp:
        xml_path = Path(tmp) / "junit.xml"
        cmd = [sys.executable, "-m", "pytest", f"--junitxml={xml_path}", "-rs", *pytest_args]
        rc = subprocess.call(cmd)  # noqa: S603 - argv is this interpreter plus the caller's pytest args
        if not xml_path.exists():
            print(f"FAIL: pytest wrote no report (exit {rc})")
            return rc or 1
        problems = violations(xml_path, args.allow_skip)
    for problem in problems:
        print(f"FAIL: {problem}")
    return rc or (1 if problems else 0)


if __name__ == "__main__":
    raise SystemExit(main())
