"""Docs-truth sentry for strategy claims about collisions.

Deterministic `faker` is a keyed many-to-one pick, so no strategy page may say distinct source
values always map to distinct masked values. Only `fpe` is one-to-one, and an untruncated `hash`
or `tokenize` is collision-resistant, not one-to-one.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
STRATEGIES = ROOT / "docs" / "strategies.md"
TOKEN_VAULT = ROOT / "docs" / "security" / "token-vault.md"

_FORBIDDEN = ("collision-free", "distinct source values map to distinct")


def _section(text: str, heading: str) -> str:
    """The body of the first `### <heading>` section, up to the next `##` or `###` heading."""
    start = re.search(rf"^### {re.escape(heading)}\b.*$", text, flags=re.MULTILINE)
    assert start, f"no section {heading!r}"
    rest = text[start.end() :]
    end = re.search(r"^#{2,3} ", rest, flags=re.MULTILINE)
    return rest[: end.start()] if end else rest


def _sentences(text: str) -> list[str]:
    flat = " ".join(text.split())
    return re.split(r"(?<=[.!?])\s+", flat)


def _claims() -> dict[str, str]:
    strategies = STRATEGIES.read_text(encoding="utf-8")
    return {
        "strategies.md faker": _section(strategies, "faker"),
        "strategies.md hash": _section(strategies, "hash"),
        "strategies.md Intentional collisions": _section(strategies, "Intentional collisions"),
        "security/token-vault.md": TOKEN_VAULT.read_text(encoding="utf-8"),
    }


def test_no_collision_free_claim_in_the_collision_sections() -> None:
    for name, text in _claims().items():
        flat = " ".join(text.split()).lower()
        for needle in _FORBIDDEN:
            assert needle not in flat, f"{name} still says {needle!r}"


def test_no_sentence_calls_hash_or_tokenize_one_to_one() -> None:
    for name, text in _claims().items():
        for sentence in _sentences(text):
            if "one-to-one" in sentence.lower():
                assert "`hash`" not in sentence, f"{name}: {sentence}"
                assert "`tokenize`" not in sentence, f"{name}: {sentence}"


def test_the_sentence_rule_sees_a_seeded_claim() -> None:
    seeded = "Untruncated `hash` and `tokenize` are one-to-one. Other text."
    hits = [s for s in _sentences(seeded) if "one-to-one" in s and "`hash`" in s]
    assert hits
