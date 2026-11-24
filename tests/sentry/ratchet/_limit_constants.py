"""The scalar bounds the sentries read, and the one reader that returns their live values.

``LIMITS`` maps ``(test file under tests/sentry, constant)`` to ``"max"`` (a cap) or ``"min"``
(a floor). The ``sentry-limits`` baseline mirrors it, so the ratchet sees a raised cap or a
lowered floor like any other loosened bound. Read by ``_baseline_sources.py``.
"""

from __future__ import annotations

import ast

# Each row names the line that compares against the constant (checked when it was added).
LIMITS: dict[tuple[str, str], str] = {
    ("test_module_size.py", "GOAL"): "max",  # an entry at or under GOAL needs no allowlist row
    ("test_module_size.py", "MAX"): "max",  # hard ceiling for new work
    ("test_module_size.py", "MARGIN"): "max",  # headroom added to a dense ceiling
    ("layout/test_package_fanout.py", "LIMIT"): "max",  # direct-module cap per package
    ("test_outbound_clients.py", "WALK_FLOOR"): "min",  # `>=` floor on files walked
    ("release/test_public_signatures.py", "HEAD_FLOOR"): "min",  # `>=` floor on public names
}


def read_int(source: str, constant: str) -> int:
    """The module-level ``NAME = <int>`` or ``NAME: int = <int>`` value in ``source``, by ``ast``.

    A bool is refused because ``isinstance(True, int)`` holds, as is any other value or a
    missing name; the module is never imported. The caller reads the file: this package holds
    checker code, whose reads all go through ``_integrity``.
    """
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names = [node.target.id]
        else:
            continue
        if constant in names:
            value = node.value
            if (
                isinstance(value, ast.Constant)
                and isinstance(value.value, int)
                and not isinstance(value.value, bool)
            ):
                return value.value
            raise ValueError(f"{constant} is not an integer literal")
    raise ValueError(f"{constant} is not assigned")


def key_of(file: str, constant: str) -> str:
    return f"{file}::{constant}"
