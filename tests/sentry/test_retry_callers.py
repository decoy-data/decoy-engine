"""F02-E1 AT-E1-9: every caller of ``run_retrying`` is pinned by exact ``(path, function)``.

The 4.1 table of the F02 plan names the only operations the executor may wrap. A new caller adds
a row to that table and to ``PINNED`` in the same change. Covered spellings: the bare name,
``from ... import run_retrying as x``, ``_retry.run_retrying`` and ``import ..._retry as r``.
"""

from __future__ import annotations

import ast

from tests.sentry._retry_scan import (
    PKG,
    RETRY_MODULE,
    canonical,
    dotted,
    import_bindings,
    rel,
    walk_with_scope,
)

TARGET = f"{RETRY_MODULE}.run_retrying"
# Expected set after F02-E5 is in the plan (4.1); each slice pins what exists at its head.
PINNED = frozenset({("connectors/s3.py", "_stream_object")})


def callers_in(source: str, path: str) -> set[tuple[str, str]]:
    tree = ast.parse(source)
    bindings = import_bindings(tree)
    out: set[tuple[str, str]] = set()
    for node, function, _ in walk_with_scope(tree):
        if not isinstance(node, ast.Call):
            continue
        name = dotted(node.func)
        if name and canonical(name, bindings) == TARGET:
            out.add((path, function))
    return out


def test_the_callers_are_exactly_the_pinned_set() -> None:
    found: set[tuple[str, str]] = set()
    for file in sorted(PKG.rglob("*.py")):
        if rel(file) != "connectors/_retry.py":
            found |= callers_in(file.read_text("utf-8"), rel(file))
    assert found == PINNED


def test_every_spelling_is_seen() -> None:
    seeds = [
        "from decoy_engine.connectors._retry import run_retrying\ndef f():\n    run_retrying(g)\n",
        "from decoy_engine.connectors._retry import run_retrying as rr\ndef f():\n    rr(g)\n",
        "from decoy_engine.connectors import _retry\ndef f():\n    _retry.run_retrying(g)\n",
        "import decoy_engine.connectors._retry as r\ndef f():\n    r.run_retrying(g)\n",
        "import decoy_engine.connectors._retry\ndef f():\n"
        "    decoy_engine.connectors._retry.run_retrying(g)\n",
    ]
    for source in seeds:
        assert callers_in(source, "connectors/x.py") == {("connectors/x.py", "f")}, source


def test_a_seeded_caller_in_another_function_of_an_allowed_file_is_a_finding() -> None:
    source = (
        "from decoy_engine.connectors._retry import run_retrying\n"
        "def _stream_object():\n    run_retrying(g)\n"
        "def put_if():\n    run_retrying(g)\n"
    )
    found = callers_in(source, "connectors/s3.py")
    assert found == {("connectors/s3.py", "_stream_object"), ("connectors/s3.py", "put_if")}
    assert found - PINNED == {("connectors/s3.py", "put_if")}
