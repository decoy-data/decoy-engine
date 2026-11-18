"""F13 structural leak sentry: run the Semgrep ruleset when Semgrep is installed.

CI always runs it (`.github/workflows/security.yml`, job `secret-provider-semgrep`); locally this
test skips when `semgrep` is not on PATH so the base dev env needs no extra tool.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RULES = ROOT / ".semgrep" / "f13-secret-providers.yml"

needs_semgrep = pytest.mark.skipif(shutil.which("semgrep") is None, reason="semgrep not installed")

# One seeded consumer file per way to reach the AWS provider module directly.
AWS_IMPORT_SPELLINGS = [
    "from decoy_engine.secret_providers.aws import AwsSecretsManagerProvider",
    "from decoy_engine.secret_providers.aws import AwsSecretsManagerProvider as P",
    "from decoy_engine.secret_providers import aws",
    "import decoy_engine.secret_providers.aws",
    "import decoy_engine.secret_providers.aws as aws_module",
]


def _scan(target: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 -- fixed argv, no shell
        ["semgrep", "--config", str(RULES), "--metrics=off", "--error", str(target)],  # noqa: S607
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )


@needs_semgrep
def test_engine_source_is_clean() -> None:
    result = _scan(ROOT / "src" / "decoy_engine")
    assert result.returncode == 0, result.stdout[-2000:]


def test_consumer_rule_lists_every_aws_import_spelling() -> None:
    """Runs without semgrep: the rule file names each spelling that reaches the AWS module."""
    text = RULES.read_text(encoding="utf-8")
    for pattern in (
        "from decoy_engine.secret_providers.aws import $X",
        "from decoy_engine.secret_providers import aws",
        "import decoy_engine.secret_providers.aws",
    ):
        assert f"- pattern: {pattern}\n" in text, pattern


@needs_semgrep
@pytest.mark.parametrize("line", AWS_IMPORT_SPELLINGS)
def test_a_consumer_importing_the_aws_provider_is_refused(line: str, tmp_path: Path) -> None:
    seeded = tmp_path / "src" / "decoy_engine" / "execution" / "seeded.py"
    seeded.parent.mkdir(parents=True)
    seeded.write_text(line + "\n", encoding="utf-8")
    result = subprocess.run(  # noqa: S603 -- fixed argv, no shell
        ["semgrep", "--config", str(RULES), "--metrics=off", "--error", str(tmp_path)],  # noqa: S607
        capture_output=True,
        text=True,
        cwd=tmp_path,
        check=False,
    )
    assert result.returncode != 0, line
