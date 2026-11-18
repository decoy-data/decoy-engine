"""Static guard: the lock's certified DP profile is a row of ``_CERTIFIED_STACKS``.

``tests/_dp_cert.py`` turns a failed ``check_fit_environment`` into a skip of every ``dp_certified``
test, so a lock change that skips the re-pin would hide those tests on the VMs and the Mac. This
guard computes the profile fingerprint from ``uv.lock`` alone (``uv export`` plus PEP 508 markers
evaluated for the certified platform, in ``scripts/release/dp_rows.py``, which release prep also uses
to write the row) and fails on every gate host instead. It never skips.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest
import yaml
from scripts.release import dp_rows

from decoy_engine.quality import dp_provenance as dp
from tests.sentry._ci_lock_scan import ROOT

_RELEASE = re.compile(r"^\s*((?:--extra \w+ )+)--python ", re.MULTILINE)
_NEED_UV = dp_rows.NEED_UV
target_env = dp_rows.target_env


def lock_profile_python() -> str:
    return dp_rows.lock_profile_python(ROOT)


def _names(flags: str) -> list[str]:
    return sorted(flags.replace("--extra ", "").split())


def bootstrap_extras(text: str) -> list[str]:
    try:
        return dp_rows.bootstrap_extras(text)
    except dp_rows.DpRowError as err:
        raise AssertionError(str(err)) from None


def _lock_env_extras(workflow: str, job: str | None) -> list[str]:
    jobs = yaml.safe_load((ROOT / workflow).read_text(encoding="utf-8"))["jobs"]
    steps = jobs[job or next(iter(jobs))]["steps"]
    found = [s["with"]["extras"] for s in steps if "lock-env" in s.get("uses", "")]
    assert len(found) == 1, f"{workflow} must install the certified extras once"
    return sorted(found[0].split())


def other_copies() -> dict[str, list[str]]:
    release = (ROOT / "scripts/release/release_checks.sh").read_text(encoding="utf-8")
    found = _RELEASE.findall(release)
    assert len(found) == 1, "release_checks.sh must declare the certified extras once"
    return {
        "release_checks.sh": _names(found[0]),
        "ci.yml dp-certified-gate": _lock_env_extras(
            ".github/workflows/ci.yml", "dp-certified-gate"
        ),
        "dps-dependency-matrix.yml": _lock_env_extras(
            ".github/workflows/dps-dependency-matrix.yml", None
        ),
    }


def profile_fingerprint(root: Path, extras: list[str], python_full: str, uv: str | None) -> str:
    assert uv, _NEED_UV
    return dp_rows.profile_fingerprint(root, extras, python_full, uv)


def test_lock_profile_is_a_certified_row() -> None:
    py = lock_profile_python()
    extras = bootstrap_extras((ROOT / "scripts/dev/bootstrap.sh").read_text(encoding="utf-8"))
    got = profile_fingerprint(ROOT, extras, py, shutil.which("uv"))
    assert got in dp._CERTIFIED_STACKS[(dp.CERTIFIED_PLATFORM, f"{py}.final")], (
        f"uv.lock profile fingerprint {got} is not a certified row for {py}; re-pin "
        "_CERTIFIED_STACKS (keep released rows) in the same change as the lock"
    )


def test_certified_extras_copies_agree_with_bootstrap() -> None:
    reference = bootstrap_extras((ROOT / "scripts/dev/bootstrap.sh").read_text(encoding="utf-8"))
    assert {k: v for k, v in other_copies().items() if v != reference} == {}


def test_missing_uv_fails_with_the_required_tool_message() -> None:
    with pytest.raises(AssertionError, match="uv is required"):
        profile_fingerprint(ROOT, ["dev"], "3.10.20", None)


@pytest.mark.parametrize("junk", [")x", "; rm x)", " --python 3.10)"])
def test_extras_declaration_with_trailing_junk_is_refused(junk: str) -> None:
    with pytest.raises(AssertionError, match="not exactly"):
        bootstrap_extras(f"EXTRAS=(--extra dev --extra lint{junk}\n")
