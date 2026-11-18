"""AT-E2-5: every first-party digest in ``connectors/`` goes through ``_digest.py``."""

from __future__ import annotations

import ast
from pathlib import Path

CONNECTORS = Path(__file__).resolve().parents[2] / "src" / "decoy_engine" / "connectors"
HELPER = "_digest.py"


def hashlib_uses(text: str) -> list[int]:
    """Lines that import hashlib or use ``hashlib.<name>``, under any import spelling."""
    out: list[int] = []
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Import):
            hit = any(a.name.split(".")[0] == "hashlib" for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            hit = (node.module or "").split(".")[0] == "hashlib"
        else:
            hit = isinstance(node, ast.Name) and node.id == "hashlib"
        if hit:
            out.append(node.lineno)
    return sorted(set(out))


def test_the_helper_exists_and_is_the_only_hashlib_user() -> None:
    assert (CONNECTORS / HELPER).is_file()
    assert hashlib_uses((CONNECTORS / HELPER).read_text(encoding="utf-8"))
    bad = [
        f"{p.name}:{n}"
        for p in sorted(CONNECTORS.rglob("*.py"))
        if p.name != HELPER
        for n in hashlib_uses(p.read_text(encoding="utf-8"))
    ]
    assert not bad, bad


def test_a_seeded_file_is_flagged() -> None:
    for text in (
        "import hashlib\nhashlib.sha256()\n",
        "from hashlib import sha256\n",
        "import hashlib as hl\n",
        "x = hashlib.md5(b'')\n",
    ):
        assert hashlib_uses(text), text
    assert not hashlib_uses("import hmac\nx = 1\n")
