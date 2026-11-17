"""The provider generate path reuses masking's adapters; it carries no kernel of its own.

An AST scan of the modules that draw provider values. After resolving import aliases it refuses
any use of a keyed-draw or RNG primitive, any concrete identifier adapter and any private
identifier or composite module. The only identifier-package name allowed is the public
`IdentifierError`; adapters come from the registry and composites from the public `COMPOSITES`.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[3] / "src" / "decoy_engine"
MODULES = ("generation/kinds/_provider.py",)
FORBIDDEN_TOKENS = frozenset({"derive", "derive_value", "default_rng", "Faker", "seed_instance"})
IDENTIFIERS = "decoy_engine.providers_v2.identifiers"
ALLOWED_IDENTIFIER_NAMES = frozenset({"IdentifierError"})


def scan(source: str) -> list[str]:
    """Problems found in `source`, as short fixed strings."""
    tree = ast.parse(source)
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in FORBIDDEN_TOKENS:
            found.append(f"token {node.id}")
        elif isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_TOKENS:
            found.append(f"token {node.attr}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                if alias.name in FORBIDDEN_TOKENS:
                    found.append(f"import {alias.name}")
                if module == IDENTIFIERS and alias.name not in ALLOWED_IDENTIFIER_NAMES:
                    found.append(f"identifier import {alias.name}")
                if module.startswith(IDENTIFIERS + "._"):
                    found.append(f"private identifier module {module}")
                if module.startswith("decoy_engine.generation.composite._"):
                    found.append(f"private composite module {module}")
                if alias.name.startswith("_") and module.startswith(IDENTIFIERS):
                    found.append(f"private identifier name {alias.name}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(IDENTIFIERS + "._"):
                    found.append(f"private identifier module {alias.name}")
    return found


@pytest.mark.parametrize("module", MODULES)
def test_the_provider_draw_modules_are_clean(module: str) -> None:
    path = SRC / module
    assert path.exists(), module
    assert scan(path.read_text()) == []


@pytest.mark.parametrize(
    "bad",
    [
        "from decoy_engine.determinism import derive_value as dv\ndv()",
        "import numpy as np\nnp.random.default_rng()",
        "from faker import Faker\nFaker()",
        "from decoy_engine.providers_v2.identifiers import NpiAdapter\nNpiAdapter()",
        "from decoy_engine.providers_v2.identifiers._errors import IdentifierError",
        "from decoy_engine.generation.composite._person import CompositePerson",
        "x.seed_instance(1)",
    ],
)
def test_the_scan_catches_the_realistic_bypasses(bad: str) -> None:
    assert scan(bad)


def test_the_scan_allows_the_public_error() -> None:
    assert scan("from decoy_engine.providers_v2.identifiers import IdentifierError") == []
