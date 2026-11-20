"""Sentry: the Faker version has one fact and every copy of it agrees (AT-P1).

`pyproject.toml`'s `faker==` pin is the fact. `uv.lock` and `NOTICE` are generated from it. The
output lock's `faker_version` and the F0 parity fixture's `PINNED_FAKER_VERSION` record the version a
capture was taken under, so a capture under a different version is stale.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[3]
_VERSION = re.compile(r"\d+\.\d+\.\d+")


def _lock_tool() -> Any:
    """The output-lock tool, whose `pinned_faker` is the one reader of the pin."""
    path = ROOT / "scripts" / "faker-determinism" / "output_lock.py"
    spec = importlib.util.spec_from_file_location("output_lock", path)
    assert spec is not None and spec.loader is not None
    sys.path.insert(0, str(path.parent))
    try:
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.path.remove(str(path.parent))
    return mod


def _pyproject() -> str:
    return _lock_tool().pinned_faker()


def _uv_lock() -> str:
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    [version] = [p["version"] for p in lock["package"] if p["name"] == "faker"]
    return str(version)


def _notice() -> str:
    found = re.findall(
        r"^\s*faker==(\S+)\s", (ROOT / "NOTICE").read_text(encoding="utf-8"), re.MULTILINE
    )
    assert len(found) == 1, "NOTICE must list faker once"
    return found[0]


def _output_lock() -> str:
    path = ROOT / "scripts" / "faker-determinism" / "output_lock.json"
    return str(json.loads(path.read_text(encoding="utf-8"))["faker_version"])


def _f0() -> str:
    text = (ROOT / "tests" / "parity" / "_f0_fixtures.py").read_text(encoding="utf-8")
    [version] = re.findall(r'^PINNED_FAKER_VERSION = "([^"]+)"', text, re.MULTILINE)
    return version


COPIES = {
    "pyproject.toml": _pyproject,
    "uv.lock": _uv_lock,
    "NOTICE": _notice,
    "scripts/faker-determinism/output_lock.json": _output_lock,
    "tests/parity/_f0_fixtures.py": _f0,
}


EXPECTED_COPIES = (
    "pyproject.toml",
    "uv.lock",
    "NOTICE",
    "scripts/faker-determinism/output_lock.json",
    "tests/parity/_f0_fixtures.py",
)


def disagreeing(versions: dict[str, str], fact: str) -> list[str]:
    """Names of the copies that are not a full `X.Y.Z` string equal to the fact."""
    return [name for name, v in versions.items() if _VERSION.fullmatch(v) is None or v != fact]


def test_copies_agree() -> None:
    versions = {name: read() for name, read in COPIES.items()}
    assert disagreeing(versions, versions["pyproject.toml"]) == [], (
        "the Faker version differs between copies; move them together in one change: "
        f"{sorted(versions)}"
    )


@pytest.mark.parametrize("name", EXPECTED_COPIES)
def test_a_seeded_disagreement_names_the_file(name: str) -> None:
    assert name in COPIES, "a copy dropped out of the checked set"
    versions = {n: "40.23.0" for n in COPIES}
    versions[name] = "40.31.0"
    assert disagreeing(versions, "40.23.0") == [name]


def test_a_partial_version_is_not_a_copy() -> None:
    assert disagreeing({"NOTICE": "40.23"}, "40.23") == ["NOTICE"]
    assert disagreeing({"NOTICE": "40.23.0\n"}, "40.23.0\n") == ["NOTICE"]
