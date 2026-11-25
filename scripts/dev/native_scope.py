"""Path scope and verdict for the macOS companion wheel legs (native-companion.yml).

    native_scope.py changes --event EVENT --base SHA --head SHA >> "$GITHUB_OUTPUT"
    toJSON(needs) | native_scope.py judge

`changes` prints one line, `native=true` or `native=false`. It is `false` for a push to main
(the PR that merged it already built the legs) and for a pull request diff that touched none of the
native paths. Every other case is `true`: a schedule or dispatch run, a missing sha, a git error. A wrong `true` costs one macOS run; a wrong `false` would
let a native change merge without its wheel build.

`judge` reads the `needs` context of the aggregator job on stdin and exits 0 only when
`native-changes` succeeded and either native is exactly `true` and the macOS legs succeeded, or
native is exactly `false` and the legs were skipped. Everything else exits 1, so a skipped leg
cannot pass for a green one. The decision is here, not in a workflow expression, so a test covers
the whole truth table. Stdlib only: the hosted runner calls it with the system python3.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable, Sequence
from typing import Any

NATIVE_DIR = "decoy-engine-native/"
NATIVE_FILES = frozenset(
    {".github/workflows/native-companion.yml", "scripts/dev/lock_version.sh", "uv.lock"}
)
SCOPE_JOB = "native-changes"
LEGS_JOB = "companion-wheel-macos"

Runner = Callable[[Sequence[str]], str]


def _run_git(argv: Sequence[str]) -> str:
    return subprocess.run(  # noqa: S603 - fixed argv, no shell
        list(argv), check=True, capture_output=True, text=True
    ).stdout


def is_native(path: str) -> bool:
    return path.startswith(NATIVE_DIR) or path in NATIVE_FILES


def native_changed(event: str, base: str, head: str, run: Runner = _run_git) -> bool:
    if event == "push":
        return False
    if event != "pull_request" or not base or not head:
        return True
    # -z keeps a non-ASCII path unquoted, so the prefix test still sees it. --no-renames lists
    # both sides of a rename, so a file moved out of the native directory still matches.
    argv = ["git", "diff", "--name-only", "--no-renames", "-z", f"{base}...{head}"]
    try:
        out = run(argv)
    except Exception:
        return True
    return any(is_native(p) for p in out.split("\0") if p)


def native_line(event: str, base: str, head: str, run: Runner = _run_git) -> str:
    return f"native={'true' if native_changed(event, base, head, run) else 'false'}"


def _need(needs: Any, name: str) -> dict[str, Any] | None:
    got = needs.get(name) if isinstance(needs, dict) else None
    return got if isinstance(got, dict) else None


def judge(needs: Any) -> list[str]:
    """Problems that keep the aggregator red; empty when the legs match the path scope."""
    scope, legs = _need(needs, SCOPE_JOB), _need(needs, LEGS_JOB)
    if scope is None or legs is None:
        return [f"needs has no usable {SCOPE_JOB} and {LEGS_JOB} entries"]
    problems = []
    if scope.get("result") != "success":
        problems.append(f"{SCOPE_JOB}: result is not success")
    outputs = scope.get("outputs")
    native = outputs.get("native") if isinstance(outputs, dict) else None
    result = legs.get("result")
    if native == "true":
        if result != "success":
            problems.append(f"{LEGS_JOB}: native paths changed and the legs did not succeed")
    elif native == "false":
        if result != "skipped":
            problems.append(f"{LEGS_JOB}: no native path changed and the legs were not skipped")
    else:
        problems.append(f"{SCOPE_JOB}: output native is neither true nor false")
    return problems


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    ch = sub.add_parser("changes")
    ch.add_argument("--event", required=True)
    ch.add_argument("--base", default="")
    ch.add_argument("--head", default="")
    sub.add_parser("judge")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.cmd == "changes":
        print(native_line(args.event, args.base, args.head))
        return 0
    try:
        needs = json.loads(sys.stdin.read())
    except ValueError:
        print("native_scope: stdin is not JSON", file=sys.stderr)
        return 1
    problems = judge(needs)
    for line in problems:
        print(line)
    if not problems:
        print("native scope and macOS legs agree")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
