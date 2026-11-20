"""Tag census helpers (S7a): find every `"<name>/vN"` literal and say which class it is in.

A tag literal is a frozen format (contract 3.1), a frozen derivation label (contract 3.3, the
`DERIVATION_LABELS` table) or an internal tag (`INTERNAL_TAGS`, with a reason). The census reads
the source, not the registry, so a new literal fails until somebody classifies it. Tags built
with f-strings are a known limit: no literal exists to find.
"""

from __future__ import annotations

import re
from pathlib import Path

from decoy_engine.contracts import stability as st
from tests.sentry.layout import section

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src" / "decoy_engine"
CONTRACT = ROOT / "docs" / "compatibility-contract.md"

TAG = r"[a-z][a-z0-9._-]*/v[0-9]+"
LITERAL = re.compile(rf'"({TAG})"')
BARE = re.compile(TAG)
H31 = "### 3.1 Persisted artifact formats (the biggest surface)"
H33 = "### 3.3 The determinism guarantee (the silent one)"
LABELS_LEAD = "**Derivation labels (frozen).**"


def literals(text: str) -> set[str]:
    return set(LITERAL.findall(text))


def source_tags(root: Path = SRC) -> dict[str, list[str]]:
    """Every tag literal under `root`, with the files that hold it."""
    found: dict[str, list[str]] = {}
    for path in sorted(root.rglob("*.py")):
        for tag in literals(path.read_text(encoding="utf-8")):
            found.setdefault(tag, []).append(path.relative_to(root).as_posix())
    return found


def contract_3_1_tags(contract: str) -> set[str]:
    """Tags in contract 3.1: the code block and the prose after it."""
    return set(BARE.findall(section(contract, H31)))


def contract_3_3_labels(contract: str) -> set[str]:
    """The tags in the fenced block that follows the derivation-label lead line in 3.3."""
    body = section(contract, H33)
    assert LABELS_LEAD in body, "contract 3.3 lost its derivation-label list"
    block = body.split(LABELS_LEAD, 1)[1].split("```")[1]
    return set(BARE.findall(block))


def unclassified(
    found: set[str], frozen: set[str], labels: set[str], internal: set[str]
) -> set[str]:
    return found - frozen - labels - internal


def overlaps(frozen: set[str], labels: set[str], internal: set[str]) -> set[str]:
    return (frozen & labels) | (frozen & internal) | (labels & internal)


def classes() -> tuple[set[str], set[str], set[str]]:
    contract = CONTRACT.read_text(encoding="utf-8")
    return contract_3_1_tags(contract), set(st.DERIVATION_LABELS), set(st.INTERNAL_TAGS)
