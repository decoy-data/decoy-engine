"""Docs-truth sentry for the strategy pages.

Collisions: deterministic `faker` is a keyed many-to-one pick, so no strategy page may say
distinct source values always map to distinct masked values. Only `fpe` is one-to-one, and an
untruncated `hash` or `tokenize` is collision-resistant, not one-to-one.

Registry agreement (row 24za): `docs/strategies.md` has a section for every user-facing mask
strategy, says what the `format_error` strategies do with an unparseable cell, and no keyed
section says its derivation reads `job_seed`. Keyed masking draws from `mask_key` only.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
STRATEGIES = ROOT / "docs" / "strategies.md"
DETERMINISM = ROOT / "docs" / "determinism.md"
TOKEN_VAULT = ROOT / "docs" / "security" / "token-vault.md"
JOB_SEED_BASELINE = ROOT / "tests" / "sentry" / "baselines" / "strategy-docs-agree.json"

_FORBIDDEN = ("collision-free", "distinct source values map to distinct")


def _section(text: str, heading: str) -> str:
    """The body of the first `##` or `###` section titled `heading`, up to the next such heading."""
    start = re.search(rf"^#{{2,3}} {re.escape(heading)}\b.*$", text, flags=re.MULTILINE)
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


# --- registry agreement (24za) ---------------------------------------------------------------

_DETERMINISM_KEYED_SECTIONS = (
    "Keyed masking: mask_key, not job_seed",
    "FPE key and tweak model",
    "Deterministic shuffle and column names",
)
_NUMBER_WORD = re.compile(
    r"\b(?:\d+|zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen"
    r"|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty)(?:-\w+)?\b",
    re.IGNORECASE,
)
_PASS_THROUGH = re.compile(r"pass(?:es|ed)? through|left as-is", re.IGNORECASE)
_ROW_OUTCOME = re.compile(r"row error|quarantin|fails? the (?:job|run)", re.IGNORECASE)
_UNPARSEABLE = re.compile(r"unparseable|non-numeric|not numeric|not parse|invalid", re.IGNORECASE)


def _registry() -> tuple[set[str], set[str]]:
    """The user-facing mask strategy names, and every scalar handler name (nested included)."""
    spec = importlib.util.spec_from_file_location(
        "gen_capability_matrix", ROOT / "scripts" / "gen_capability_matrix.py"
    )
    assert spec and spec.loader
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    from decoy_engine.execution._strategies import SCALAR_HANDLERS

    return {name for name, _ in gen._mask_strategies()}, set(SCALAR_HANDLERS)


def _mask_part(text: str) -> str:
    """The `## Mask strategies` part of strategies.md, up to the generation part."""
    start = text.index("## Mask strategies")
    return text[start : text.index("\n## Generation strategies", start)]


def _headings(part: str) -> list[str]:
    return re.findall(r"^### (.+)$", part, flags=re.MULTILINE)


def _has_heading(headings: list[str], name: str) -> bool:
    return any(h == name or h.startswith(name + " ") for h in headings)


def _mask_section(text: str, name: str) -> str:
    """The body of a mask-strategy section, found inside the mask part only."""
    return _section(_mask_part(text), name)


_UNKEYED_DERIVE = re.compile(r"\bderive\((?!mask_key\b)")


def _job_seed_sentences(text: str, allowed: frozenset[str]) -> list[str]:
    """Sentences that read `job_seed` or name a `derive(` call keyed on anything but `mask_key`."""
    return [
        sentence
        for sentence in _sentences(text)
        if ("job_seed" in sentence or _UNKEYED_DERIVE.search(sentence)) and sentence not in allowed
    ]


def _allowed_sentences() -> frozenset[str]:
    data = json.loads(JOB_SEED_BASELINE.read_text(encoding="utf-8"))
    return frozenset(data["entries"])


def test_every_user_facing_strategy_has_a_section_and_no_count_is_stated() -> None:
    user_facing, all_handlers = _registry()
    part = _mask_part(STRATEGIES.read_text(encoding="utf-8"))
    headings = _headings(part)
    for name in sorted(user_facing):
        assert _has_heading(headings, name), f"strategies.md has no section for {name!r}"
    for name in sorted(all_handlers - user_facing):
        assert not _has_heading(headings, name), f"{name!r} is not a user-facing strategy"
    intro = part.split("\n### ", 1)[0]
    assert not _NUMBER_WORD.search(intro), "the mask strategies intro states a count"


def test_format_error_strategies_say_what_an_unparseable_cell_does() -> None:
    from decoy_engine.execution.native._capabilities import capabilities_for

    user_facing, _ = _registry()
    text = STRATEGIES.read_text(encoding="utf-8")
    checked = []
    for name in sorted(user_facing):
        if "format_error" not in capabilities_for(name).row_error_modes:
            continue
        checked.append(name)
        body = _mask_section(text, name)
        assert any(
            "`format_error`" in sentence and _ROW_OUTCOME.search(sentence)
            for sentence in _sentences(body)
        ), f"{name}: no sentence ties format_error to the row error outcome"
        for sentence in _sentences(body):
            if _PASS_THROUGH.search(sentence) and _UNPARSEABLE.search(sentence):
                raise AssertionError(f"{name}: unparseable cells pass through: {sentence}")
    assert checked, "no strategy declares format_error"


def test_keyed_sections_name_mask_key_not_job_seed() -> None:
    from decoy_engine.secret_providers._requirements import ALWAYS_KEYED_STRATEGIES

    user_facing, _ = _registry()
    allowed = _allowed_sentences()
    strategies = STRATEGIES.read_text(encoding="utf-8")
    bad: list[str] = []
    headings = _headings(_mask_part(strategies))
    for name in sorted(ALWAYS_KEYED_STRATEGIES & user_facing):
        if not _has_heading(headings, name):
            continue  # a missing section is the section-list test's finding
        bad += [
            f"strategies.md {name}: {s}"
            for s in _job_seed_sentences(_mask_section(strategies, name), allowed)
        ]
    determinism = DETERMINISM.read_text(encoding="utf-8")
    for heading in _DETERMINISM_KEYED_SECTIONS:
        bad += [
            f"determinism.md {heading}: {s}"
            for s in _job_seed_sentences(_section(determinism, heading), allowed)
        ]
    assert not bad, "keyed docs still read job_seed:\n" + "\n".join(bad)


def test_every_allowlisted_job_seed_sentence_is_still_in_the_docs() -> None:
    determinism = DETERMINISM.read_text(encoding="utf-8")
    flat = {
        s
        for heading in _DETERMINISM_KEYED_SECTIONS
        for s in _sentences(_section(determinism, heading))
    }
    for sentence in _allowed_sentences():
        assert sentence in flat, f"stale allowlist entry: {sentence}"


def test_the_job_seed_rule_sees_a_seeded_derivation() -> None:
    seeded = "The key is `derive(job_seed, namespace, value)`. Other text."
    assert _job_seed_sentences(seeded, frozenset()) == [
        "The key is `derive(job_seed, namespace, value)`."
    ]
    assert not _job_seed_sentences(
        seeded, frozenset({"The key is `derive(job_seed, namespace, value)`."})
    )


def test_the_pass_through_rule_sees_a_seeded_claim() -> None:
    sentence = "Non-numeric and null values pass through."
    assert _PASS_THROUGH.search(sentence) and _UNPARSEABLE.search(sentence)
    ok = "Null values are left as-is."
    assert not (_PASS_THROUGH.search(ok) and _UNPARSEABLE.search(ok))


def test_the_derive_rule_sees_a_derivation_keyed_on_seed() -> None:
    seeded = "The token is `derive(seed, namespace, value)`. Other text."
    assert _job_seed_sentences(seeded, frozenset()) == [
        "The token is `derive(seed, namespace, value)`."
    ]
    assert not _job_seed_sentences(
        "The token is `derive(mask_key, namespace, value)`.", frozenset()
    )
