"""AT-E5: the engine layer placement and the alias-aware import walk that replace the standalone contract.

OQ-4 folded the verifier into the engine. The package may import only the engine owners it needs
(``_canonical``, ``_error_base``, ``reasons``, ``fileaccess``), the standard library, ``joserfc``,
``rfc8785`` and ``cryptography``, and no data library directly. The walk resolves ``import`` and
``from`` aliases, so ``import decoy_engine.execution as e`` and ``from decoy_engine import execution``
are caught the same as ``from decoy_engine.execution import x``.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

import decoy_engine.signed_evidence as se

PKG = Path(__file__).resolve().parents[3] / "src" / "decoy_engine" / "signed_evidence"
ALLOWED_ENGINE = {"_canonical", "_error_base", "reasons", "fileaccess"}
ALLOWED_THIRD_PARTY = {"joserfc", "rfc8785", "cryptography"}
HEAVY = {"pandas", "numpy", "pyarrow", "polars", "duckdb", "yaml", "pydantic", "sqlalchemy"}

#: The facade: what a caller uses (plan note 10), plus two names the gated suites import.
FACADE = {
    "EVIDENCE_FILENAME",
    "SIGNATURE_FILENAME",
    "MAX_EXPECTATIONS_BYTES",
    "MAX_POLICY_BYTES",
    "MAX_SIGNATURE_BYTES",
    "MAX_STATEMENT_BYTES",
    "ArtifactStatus",
    "CheckStatus",
    "ExitClass",
    "ExpectedArtifact",
    "Expectations",
    "HistoricalAuthorization",
    "HistoricalDecision",
    "IdentityBinding",
    "LocalEs256Signer",
    "Purpose",
    "ReleaseVerdict",
    "RequiredCatalog",
    "SchemaStatus",
    "SignatureStatus",
    "SignedBundle",
    "SignedEvidenceError",
    "SigningIdentity",
    "TrustPolicy",
    "TrustStatus",
    "VerificationContext",
    "VerificationResult",
    "der_to_p1363",
    "open_signed_bundle",
    "parse_expectations",
    "sign_evidence",
    "verify_signed_bundle",
    "verify_signed_evidence",
}


def direct_imports(source: str) -> tuple[set[str], set[str]]:
    """``(engine owners, other top-level packages)`` named by one module, aliases resolved."""
    engine: set[str] = set()
    other: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                if parts[0] == "decoy_engine":
                    engine.add(parts[1] if len(parts) > 1 else "<root>")
                else:
                    other.add(parts[0])
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            parts = node.module.split(".")
            if parts[0] == "decoy_engine":
                if len(parts) > 1:
                    engine.add(parts[1])
                else:  # ``from decoy_engine import fileaccess`` names the owner in the alias list
                    engine.update(a.name for a in node.names)
            else:
                other.add(parts[0])
    return engine, other


def violations(source: str) -> list[str]:
    engine, other = direct_imports(source)
    bad = [f"engine:{n}" for n in sorted(engine - ALLOWED_ENGINE)]
    allowed = set(sys.stdlib_module_names) | ALLOWED_THIRD_PARTY | {"__future__"}
    bad += [f"third:{n}" for n in sorted(other - allowed)]
    bad += [f"heavy:{n}" for n in sorted(other & HEAVY)]
    return bad


def test_every_module_imports_only_the_allowed_owners() -> None:
    for path in sorted(PKG.glob("*.py")):
        assert violations(path.read_text(encoding="utf-8")) == [], path.name


def test_the_package_uses_the_owners_it_is_allowed() -> None:
    used: set[str] = set()
    for path in PKG.glob("*.py"):
        used |= direct_imports(path.read_text(encoding="utf-8"))[0]
    assert {"_canonical", "fileaccess"} <= used <= ALLOWED_ENGINE


@pytest.mark.parametrize(
    "source",
    [
        "from decoy_engine.execution import run_pipeline\n",
        "import decoy_engine.execution as e\n",
        "from decoy_engine import execution\n",
        "from decoy_engine import execution as ex\n",
        "import pyarrow\n",
        "import pyarrow.parquet as pq\n",
        "from pandas import DataFrame\n",
        "import numpy as np\n",
        "import requests\n",
    ],
)
def test_each_seeded_import_turns_the_guard_red(source: str) -> None:
    assert violations(source), source


@pytest.mark.parametrize(
    "source",
    [
        "from decoy_engine import fileaccess\n",
        "from decoy_engine._canonical import jcs_bytes\n",
        "import decoy_engine.reasons\n",
        "import rfc8785\nfrom joserfc.jwk import ECKey\nimport hashlib\n",
    ],
)
def test_the_allowed_spellings_pass(source: str) -> None:
    assert violations(source) == [], source


def test_the_package_has_the_planned_number_of_direct_modules() -> None:
    names = sorted(p.name for p in PKG.glob("*.py"))
    assert len(names) == 21, names
    assert {"_bundle.py", "_expectations.py"} <= set(names)


def test_the_public_boundary_is_exactly_the_facade() -> None:
    assert set(se.__all__) == FACADE
    assert len(se.__all__) == len(set(se.__all__))
    for name in ("hash_file_under", "ReleasePermit", "StrictReleaseEvaluator", "SignedEvidence"):
        assert not hasattr(se, name)


def test_the_layer_config_places_signed_evidence_with_its_snapshot() -> None:
    root = PKG.parents[2]
    config = (root / ".importlinter").read_text(encoding="utf-8")
    assert "run_result : signed_evidence" in config
    snapshot = (root / "tests" / "sentry" / "layout" / "test_import_layers.py").read_text(
        encoding="utf-8"
    )
    assert "run_result : signed_evidence" in snapshot
