"""AT-D1: docs/reasons.md names its consumers, and every reason symbol it names exists."""

from __future__ import annotations

import re
from pathlib import Path

from decoy_engine import reasons

_DOC = Path(__file__).parents[3] / "docs" / "reasons.md"


def _consumers_section() -> str:
    text = _DOC.read_text(encoding="utf-8")
    match = re.search(r"^## Consumers\n(.*?)(?=^## )", text, re.M | re.S)
    assert match, "docs/reasons.md has no 'Consumers' section"
    return match.group(1)


def test_consumers_section_names_the_platform_projection() -> None:
    assert "APPROVED_ERROR_MESSAGES" in _consumers_section()


def test_named_reason_symbols_resolve_in_the_registry() -> None:
    symbols = re.findall(r"`reasons\.(\w+)\.([A-Z0-9_]+)`", _consumers_section())
    assert symbols, "the Consumers section names no reasons.<ns>.<NAME> symbol"
    for namespace, name in symbols:
        group = getattr(reasons, namespace, None)
        assert group is not None, f"reasons.{namespace} does not exist"
        assert hasattr(group, name), f"reasons.{namespace}.{name} does not exist"
