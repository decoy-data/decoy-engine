"""Every base runtime dependency in uv.lock installs from a wheel on every shipped platform.

Reads wheel tags from the lock only; it never installs or imports anything. Windows and macOS
smoke runs belong to WIN-FEAS and WIN-RUNNER. A package with no wheel for a platform would fall
back to a source build on a user's machine, which the engine does not support.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

from scripts.dev import licenses

_LOCK = Path(__file__).parents[2] / "uv.lock"

_PLATFORMS: dict[str, re.Pattern[str]] = {
    "win_amd64": re.compile(r"-win_amd64\.whl$"),
    "macos_arm64": re.compile(r"-macosx_\d+_\d+_(arm64|universal2)\.whl$"),
    "linux_x86_64": re.compile(r"-manylinux[^-]*_x86_64[^-]*\.whl$"),
    "linux_aarch64": re.compile(r"-manylinux[^-]*_aarch64[^-]*\.whl$"),
}

# Gaps that exist on main, each with the reason. A new base dependency may not be added here.
_ALLOWLIST: dict[tuple[str, str], str] = {}


def _wheel_names(pkg: dict) -> list[str]:
    return [w["url"].rsplit("/", 1)[-1] for w in pkg.get("wheels", [])]


def wheel_gaps(lock_text: str, allowlist: dict[tuple[str, str], str]) -> list[str]:
    """One line per (package, platform) with no wheel, for the base runtime closure."""
    lock = tomllib.loads(lock_text)
    closure = licenses._walk(lock, licenses._root(lock).get("dependencies", []))
    by_key = {(licenses.norm(p["name"]), p.get("version", "")): p for p in lock["package"]}
    gaps: list[str] = []
    for key in sorted(closure):
        names = _wheel_names(by_key[key])
        if any(n.endswith("-none-any.whl") for n in names):
            continue
        for platform, pattern in _PLATFORMS.items():
            if (*key, platform) in allowlist or key in allowlist:
                continue
            if not any(pattern.search(n) for n in names):
                gaps.append(f"{key[0]}=={key[1]}: no wheel for {platform}")
    return gaps


def test_base_closure_has_wheels_on_every_platform() -> None:
    assert wheel_gaps(_LOCK.read_text(encoding="utf-8"), _ALLOWLIST) == []


def test_pynacl_is_in_the_base_closure_and_not_allowlisted() -> None:
    lock = tomllib.loads(_LOCK.read_text(encoding="utf-8"))
    closure = licenses._walk(lock, licenses._root(lock).get("dependencies", []))
    assert "pynacl" in {name for name, _ in closure}
    assert "pynacl" not in {name for name, _ in _ALLOWLIST}


def test_linux_only_wheel_is_a_gap() -> None:
    lock = """
[[package]]
name = "decoy-engine"
version = "0"
source = { editable = "." }
dependencies = [{ name = "lonely" }]

[[package]]
name = "lonely"
version = "1"
source = { registry = "https://pypi.org/simple" }
wheels = [
    { url = "https://x/lonely-1-cp38-abi3-manylinux_2_17_x86_64.whl", hash = "sha256:00" },
]
"""
    gaps = wheel_gaps(lock, {})
    assert "lonely==1: no wheel for win_amd64" in gaps
    assert "lonely==1: no wheel for linux_aarch64" in gaps
    assert not any("linux_x86_64" in g for g in gaps)


def test_pure_python_wheel_needs_nothing_more() -> None:
    lock = """
[[package]]
name = "decoy-engine"
version = "0"
source = { editable = "." }
dependencies = [{ name = "pure" }]

[[package]]
name = "pure"
version = "1"
source = { registry = "https://pypi.org/simple" }
wheels = [{ url = "https://x/pure-1-py3-none-any.whl", hash = "sha256:00" }]
"""
    assert wheel_gaps(lock, {}) == []


@pytest.mark.parametrize("name", ["pynacl"])
def test_allowlist_never_holds_crypto_dependencies(name: str) -> None:
    assert name not in {n for n, _ in _ALLOWLIST}
