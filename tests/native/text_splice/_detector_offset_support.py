"""Harness for the text_redact detector offset guard (TEXT-REDACT-RUST-SPLICE S0).

The production offset limit is u32::MAX bytes, so the guard cannot be hit with a real cell. A
companion built with the crate feature `test-detector-offset-limit` lowers it to 64 bytes. This
module builds that wheel once and runs a snippet in a child process that sees only that wheel
and a chosen copy of the engine source, so the same wheel can be paired with the head source
(AT-3) or with the core as it was before S0 (AT-11, an "old core with a new wheel").
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
CRATE = REPO / "decoy-engine-native"
MATURIN = "maturin==1.15.0"  # the version native-companion.yml builds release wheels with

# The engine as it was one commit before S0 (origin/main when S0 was cut). AT-11 runs that core
# against the new wheel, so it must not move with later commits.
OLD_CORE_SHA = "9f7bb1f4ad6f3ff95ad3328606cf1059ecb35aea"

LIMIT = 64  # DETECTOR_OFFSET_LIMIT under the test feature
OVERSIZED_EMAIL = "a" * (LIMIT - 5) + "@b.com"  # 65 bytes, one over the test limit
LIMIT_EMAIL = "a" * (LIMIT - 6) + "@b.com"  # 64 bytes, exactly the test limit: still eligible
SHORT_EMAIL = "a@b.com"


def build_tooling_missing() -> str | None:
    """Why the wheel cannot be built here, or None when it can."""
    if shutil.which("cargo") is None:
        return "cargo is not installed"
    if shutil.which("maturin") is None and shutil.which("uvx") is None:
        return "neither maturin nor uvx is installed"
    return None


def _maturin() -> list[str]:
    return ["maturin"] if shutil.which("maturin") else ["uvx", "--from", MATURIN, "maturin"]


def build_wheel_dir(out: Path, *, features: str | None) -> Path:
    """Build the companion (optionally with crate features) and unpack it under `out`."""
    wheels = out / "wheels"
    cmd = [
        *_maturin(),
        "build",
        "--manifest-path",
        str(CRATE / "Cargo.toml"),
        "--interpreter",
        sys.executable,
        "--out",
        str(wheels),
    ]
    if features:
        cmd += ["--features", features]
    subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=1500)  # noqa: S603 - fixed argument lists, no untrusted input
    (wheel,) = wheels.glob("decoy_engine_native-*.whl")
    unpacked = out / "unpacked"
    with zipfile.ZipFile(wheel) as zf:
        zf.extractall(unpacked)
    return unpacked


def _old_core_present() -> bool:
    probe = subprocess.run(  # noqa: S603 - fixed argument lists, no untrusted input
        ["git", "-C", str(REPO), "cat-file", "-e", f"{OLD_CORE_SHA}^{{commit}}"],  # noqa: S607 - fixed argument lists, no untrusted input
        capture_output=True,
    )
    return probe.returncode == 0


def export_old_core_src(out: Path, *, include_tests: bool = False) -> Path | None:
    """`src/` of the pre-S0 core from git history, or None when the commit is not available.

    A shallow checkout lacks the commit, so one depth-1 fetch is tried first. When the commit is
    still missing and the CI env var is set, this raises: a skipped AT-11 would hide the check.
    With `include_tests`, the old `tests/native` tree and its package files come too.
    """
    if not _old_core_present():
        subprocess.run(  # noqa: S603 - fixed argument lists, no untrusted input
            ["git", "-C", str(REPO), "fetch", "--depth=1", "origin", OLD_CORE_SHA],  # noqa: S607 - fixed argument lists, no untrusted input
            capture_output=True,
        )
    if not _old_core_present():
        if os.environ.get("CI"):
            raise AssertionError(
                f"CI needs commit {OLD_CORE_SHA} for AT-11 and it is not available"
            )
        return None
    out.mkdir(parents=True, exist_ok=True)
    paths = ["src"]
    if include_tests:
        paths += [
            "pyproject.toml",
            ":(glob)tests/*.py",
            "tests/native",
            "tests/snapshots/golden/mask_text_redact",
        ]
    archive = subprocess.run(  # noqa: S603 - fixed argument lists, no untrusted input
        ["git", "-C", str(REPO), "archive", OLD_CORE_SHA, *paths],  # noqa: S607 - fixed argument lists, no untrusted input
        check=True,
        capture_output=True,
    ).stdout
    subprocess.run(["tar", "-x", "-C", str(out)], input=archive, check=True)  # noqa: S603, S607 - fixed argument lists, no untrusted input
    return out / "src"


def run_old_suites(
    old_root: Path, *, wheel_dir: Path, tests: list[str]
) -> subprocess.CompletedProcess[str]:
    """Run old-core test files in a child pytest rooted at `old_root`, with `wheel_dir` first."""
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join([str(wheel_dir), str(old_root / "src")]),
    }
    return subprocess.run(  # noqa: S603 - fixed argument lists, no untrusted input
        [sys.executable, "-m", "pytest", *tests, "-q", "-p", "no:cacheprovider", "-m", "not perf"],
        cwd=old_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=1200,
    )


def run_snippet(snippet: str, *, wheel_dir: Path, core_src: Path) -> dict[str, object]:
    """Run `snippet` in a child process that imports `core_src` and the wheel in `wheel_dir`.

    The snippet prints one JSON document. The child asserts both import locations first, so a
    test can never pass against the wrong core or the wrong wheel.
    """
    guard = (
        "import json, sys\n"
        "import decoy_engine, decoy_engine_native._kernel as _k\n"
        f"assert decoy_engine.__file__.startswith({str(core_src)!r}), decoy_engine.__file__\n"
        f"assert _k.__file__.startswith({str(wheel_dir)!r}), _k.__file__\n"
    )
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(wheel_dir), str(core_src)])}
    done = subprocess.run(  # noqa: S603 - fixed argument lists, no untrusted input
        [sys.executable, "-c", guard + snippet],
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if done.returncode != 0:
        raise AssertionError(f"child failed ({done.returncode}):\n{done.stderr[-3000:]}")
    result: dict[str, object] = json.loads(done.stdout.strip().splitlines()[-1])
    return result
