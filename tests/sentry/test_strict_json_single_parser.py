"""One strict JSON parser: only `_canonical` hands `json` a duplicate-key or constant hook.

`strict_json_loads` is the choke point for refusing duplicate keys, NaN/Infinity and oversized
integers. A module outside `_canonical/` that passes `object_pairs_hook=` or `parse_constant=`
is a second copy of that rule, with its own gaps. There is no baseline and no allowlist.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).parents[2] / "src" / "decoy_engine"
OWNER_DIR = "_canonical/"
_HOOKS = frozenset({"object_pairs_hook", "parse_constant"})


def hook_calls(source: str) -> list[tuple[int, str]]:
    """(line, keyword) for every call that passes a strict-parse hook."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            found.extend((node.lineno, k.arg) for k in node.keywords if k.arg in _HOOKS)
    return found


def test_no_module_outside_canonical_passes_a_strict_parse_hook() -> None:
    offenders: dict[str, list[tuple[int, str]]] = {}
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        if rel.startswith(OWNER_DIR):
            continue
        hooks = hook_calls(path.read_text(encoding="utf-8"))
        if hooks:
            offenders[rel] = hooks
    assert not offenders, f"strict JSON parsing outside {OWNER_DIR}: {offenders}"


def test_the_sentry_sees_the_owner() -> None:
    owner = (SRC / "_canonical" / "_json.py").read_text(encoding="utf-8")
    assert {k for _, k in hook_calls(owner)} == _HOOKS


def test_seeded_violation_is_caught() -> None:
    seeded = (
        "import json\n"
        "def f(t):\n"
        "    return json.loads(t, object_pairs_hook=dict)\n"
        "def g(t):\n"
        "    return json.JSONDecoder(parse_constant=str).decode(t)\n"
    )
    assert hook_calls(seeded) == [(3, "object_pairs_hook"), (5, "parse_constant")]
    assert hook_calls("import json\njson.loads('{}')\n") == []
