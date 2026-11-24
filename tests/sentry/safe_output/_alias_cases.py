"""The ways a class name can reach a call, shared by the literal sentry and the registry rule."""

from __future__ import annotations

# (prelude, expression naming the class). `pkg.mod` is never imported: resolution is lexical.
ALIAS_FORMS: list[tuple[str, str]] = [
    ("", "{N}"),
    ("from pkg.mod import {N} as AL\n", "AL"),
    ("import pkg.mod as pm\n", "pm.{N}"),
    ("import pkg\n", "pkg.mod.{N}"),
    ("Builder = {N}\n", "Builder"),
    ("from pkg.mod import {N} as AL\nBuilder = AL\n", "Builder"),
]
ALIAS_IDS = [
    "direct",
    "from_import_as",
    "module_as",
    "dotted",
    "rebinding",
    "import_then_rebinding",
]


def forms(name: str) -> list[tuple[str, str]]:
    return [(p.format(N=name), e.format(N=name)) for p, e in ALIAS_FORMS]
