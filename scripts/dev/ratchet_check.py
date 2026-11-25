"""Fail when a registered sentry baseline grows, is re-homed, or carries a weak reason.

Usage: ratchet_check.py [--root DIR] [--base REF] [--schema-waiver-env]
  --base   default: merge-base of origin/main and HEAD
A key may not be added, except a key the registry lists under that baseline's `approved_growth`
(an exact key plus a dated `owner YYYY-MM-DD ...` decision; stale or malformed rows fail), and that for sentries in REKEY_PER_SITE the
`permitted::<file>::<site>::<digest>` keys count per site: re-keying a site (same count, new
digest) passes and prints a review line; a higher count or a new site fails.
For sentries in REHOME_BY_BINDING, a `<file>.py::<qualname>::<name>` key may move to a new key
only when the new entry declares `moved_from: <old key>`, the old key has the same bound name,
was lost from this baseline, carries no numeric max, is claimed once, and the old site is
proven gone from the source (AST proof); the key count never grows.
The logic lives in tests/sentry/_ratchet.py so the unit tests and this gate step share it.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import sys
from pathlib import Path


def _load():
    # Loaded by path: the baseline tree being checked may be a scratch repo without the helper.
    path = Path(__file__).resolve().parents[2] / "tests" / "sentry" / "_ratchet.py"
    spec = importlib.util.spec_from_file_location("_ratchet", path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_ratchet"] = mod
    spec.loader.exec_module(mod)
    return mod


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    ap.add_argument("--base")
    ap.add_argument(
        "--schema-waiver-env",
        action="store_true",
        help="read RATCHET_SCHEMA_WAIVER (the extracted base checker only; the head run omits it)",
    )
    args = ap.parse_args(argv)
    base = args.base
    if not base:
        res = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["git", "-C", str(args.root), "merge-base", "origin/main", "HEAD"],  # noqa: S607
            capture_output=True,
            text=True,
        )
        if res.returncode != 0:
            print("ratchet: no merge base; run: git fetch origin main", file=sys.stderr)
            return 2
        base = res.stdout.strip()
    findings, report = _load().check(
        args.root,
        base,
        os.environ.get("RATCHET_SCHEMA_WAIVER") if args.schema_waiver_env else None,
    )
    for line in report:
        print(f"ratchet: {line}")
    for line in findings:
        print(f"ratchet: FAIL {line}", file=sys.stderr)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
