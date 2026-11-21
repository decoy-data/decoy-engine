"""Tag census helpers (S7a): find every `"<name>/vN"` literal and say which class it is in.

A tag literal is a frozen format (contract 3.1), a frozen derivation label (contract 3.3, the
`DERIVATION_LABELS` table), a declared-casting format id (the F06 registries, documented in
`docs/declared-casting.md`) or an internal tag (`INTERNAL_TAGS`, with a reason). The census
parses every `.py` file under `src` and reads each string or bytes constant, so comments and
docstrings never count and any quoting style is seen. A tag is a whole constant, or a constant that starts with the tag and then a non-letter
(`\\x00`, `:`), which covers the leading part of an f-string. Each tag has one or more
`/`-separated segments before `/vN`. Known limits (S7A-KL-2): tags built by
concatenation or formatted in the middle, and tags in Rust or YAML files, are outside the scan.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from decoy_engine.contracts import stability as st
from decoy_engine.contracts._declared_formats import OUTPUT_MODELS, PARSE_MODELS
from decoy_engine.contracts.declared_casting import ExactSentinelSetV1
from tests.sentry.layout import section

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src" / "decoy_engine"
CONTRACT = ROOT / "docs" / "compatibility-contract.md"

TAG = r"[a-z][a-z0-9._-]*(?:/[a-z0-9._-]+)*/v[0-9]+"
WHOLE = re.compile(TAG)
# A constant that starts with a tag and then a non-letter (`\x00`, `:`), e.g. a bytes label or the
# leading part of an f-string, still names a derivation label.
PREFIXED = re.compile(TAG + r"(?![a-z0-9._/-])")
H31 = "### 3.1 Persisted artifact formats (the biggest surface)"
H33 = "### 3.3 The determinism guarantee (the silent one)"
LABELS_LEAD = "**Derivation labels (frozen).**"
# Tags that contract 3.1 names only in prose, as the next version of a listed format. They are
# not in the code block, so each is allowed by name and must still appear in the section text.
PROSE_ONLY_3_1 = frozenset(
    {"distribution-snapshot/v2", "flagged-redacted/v2", "subset-manifest/v2"}
)


def _constants(node: ast.AST) -> list[str]:
    """Every str or bytes constant under `node`, decoded, including f-string literal parts."""
    out = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, (str, bytes)):
            value = sub.value
            out.append(
                value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value
            )
    return out


def literals(text: str) -> set[str]:
    """Tags in `text`: a constant that is one tag, or starts with a tag then a non-letter."""
    found: set[str] = set()
    for value in _constants(ast.parse(text)):
        if WHOLE.fullmatch(value):
            found.add(value)
        elif (m := PREFIXED.match(value)) is not None:
            found.add(m.group(0))
    return found


def source_tags(root: Path = SRC) -> dict[str, list[str]]:
    """Every tag literal under `root`, with the files that hold it."""
    found: dict[str, list[str]] = {}
    for path in sorted(root.rglob("*.py")):
        for tag in literals(path.read_text(encoding="utf-8")):
            found.setdefault(tag, []).append(path.relative_to(root).as_posix())
    return found


def contract_3_1_block(contract: str) -> str:
    """The one fenced code block of contract 3.1."""
    parts = section(contract, H31).split("```")
    assert len(parts) == 3, "contract 3.1 must hold exactly one code block"
    return parts[1]


def contract_3_1_tags(contract: str) -> set[str]:
    """Tags in the contract 3.1 code block, plus the allowlisted tags the prose names."""
    prose = section(contract, H31)
    named = {tag for tag in PROSE_ONLY_3_1 if tag in prose}
    return set(WHOLE.findall(contract_3_1_block(contract))) | named


def contract_3_3_labels(contract: str) -> set[str]:
    """The tags in the fenced block that follows the derivation-label lead line in 3.3."""
    body = section(contract, H33)
    assert LABELS_LEAD in body, "contract 3.3 lost its derivation-label list"
    block = body.split(LABELS_LEAD, 1)[1].split("```")[1]
    return set(WHOLE.findall(block))


def declared_format_ids() -> set[str]:
    """The declared-casting format ids: the F06 parse and output registries plus the sentinel set."""
    sentinel = ExactSentinelSetV1.model_fields["id"].annotation.__args__[0]  # type: ignore[union-attr]
    return set(PARSE_MODELS) | set(OUTPUT_MODELS) | {sentinel}


def unclassified(
    found: set[str], frozen: set[str], labels: set[str], internal: set[str], declared: set[str]
) -> set[str]:
    return found - frozen - labels - internal - declared


def overlaps(
    frozen: set[str], labels: set[str], internal: set[str], declared: set[str]
) -> set[str]:
    sets = (frozen, labels, internal, declared)
    return {tag for i, one in enumerate(sets) for other in sets[i + 1 :] for tag in one & other}


def classes() -> tuple[set[str], set[str], set[str], set[str]]:
    contract = CONTRACT.read_text(encoding="utf-8")
    return (
        contract_3_1_tags(contract),
        set(st.DERIVATION_LABELS),
        set(st.INTERNAL_TAGS),
        declared_format_ids(),
    )
