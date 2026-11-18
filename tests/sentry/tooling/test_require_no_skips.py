"""AT-E3-7: the SDK lane fails on a skipped cell, at collection or at run time, unless the test id
is on the named allowlist. Each case runs a child pytest so the plugin sees real reports."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
HIDE_HVAC = "import sys\nsys.modules['hvac'] = None\n"
CASES = {
    "tests/test_module_skip.py": HIDE_HVAC + "import pytest\npytest.importorskip('hvac')\n",
    "tests/test_run_skip.py": "import pytest\n\ndef test_x():\n    pytest.skip('no sdk')\n",
}
ALLOWED = {
    "tests/secret_providers/test_vault_live.py": (
        "import pytest\n\ndef test_live():\n    pytest.skip('no live vault')\n"
    )
}


def _run(
    tmp_path: Path, files: dict[str, str], *, enforce: bool
) -> subprocess.CompletedProcess[str]:
    for rel, text in files.items():
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    env = {k: v for k, v in os.environ.items() if k != "DECOY_REQUIRE_PROVIDER_SDKS"}
    env["PYTHONPATH"] = str(ROOT)
    if enforce:
        env["DECOY_REQUIRE_PROVIDER_SDKS"] = "1"
    return subprocess.run(  # noqa: S603 -- fixed argv, no shell
        [sys.executable, "-m", "pytest", "-p", "tests._require_no_skips", "-p", "no:cacheprovider",
         "-c", os.devnull, "--rootdir", str(tmp_path), "-q", str(tmp_path / "tests")],
        capture_output=True, text=True, cwd=tmp_path, env=env, check=False,
    )  # fmt: skip


@pytest.mark.parametrize("rel", sorted(CASES))
def test_a_skip_fails_the_session_when_the_lane_variable_is_set(tmp_path: Path, rel: str) -> None:
    result = _run(tmp_path, {rel: CASES[rel]}, enforce=True)
    assert result.returncode != 0, result.stdout[-1500:]
    assert "SDK cell did not run" in result.stdout


@pytest.mark.parametrize("rel", sorted(CASES))
def test_a_skip_is_still_a_skip_without_the_variable(tmp_path: Path, rel: str) -> None:
    result = _run(tmp_path, {rel: CASES[rel]}, enforce=False)
    assert result.returncode in (0, 5), result.stdout[-1500:]
    assert "skipped" in result.stdout


def test_an_allowlisted_id_still_skips_in_the_lane(tmp_path: Path) -> None:
    result = _run(tmp_path, ALLOWED, enforce=True)
    assert result.returncode == 0, result.stdout[-1500:]
    assert "1 skipped" in result.stdout


def test_the_sdk_lane_sets_the_variable_and_installs_semgrep_and_every_sdk_extra() -> None:
    lane = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())["jobs"][
        "secret-provider-sdks"
    ]
    assert str(lane["env"]["DECOY_REQUIRE_PROVIDER_SDKS"]) == "1"
    text = " ".join(f"{step.get('run', '')} {step.get('with', '')}" for step in lane["steps"])
    for needle in ("semgrep", "hashicorp-vault", "cloud", "tests/secret_providers"):
        assert needle in text, needle
