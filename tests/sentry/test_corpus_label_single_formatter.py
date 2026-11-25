"""Sentry: every corpus path, label or provenance value that leaves the engine goes through
one formatter.

`_where(locator)` renders a corpus location, `_corpus_label(name)` a corpus label,
`provenance_summary(prov)` a provenance stamp; each applies the file-access policy or strips URL
credentials. The sentry reads the code_set modules with the shared outbound-text tagger
(`safe_output/_tagger.py`) and flags a corpus-shaped local reaching an outward sink any other
way:

- the arguments of a raised error (f-strings included),
- the arguments of a log call (so a `%r` argument counts),
- a returned value (so a dict return counts),
- the arguments of `CorpusVerifyReport(...)`,
- and, through the tagger's assignment tracking, a local assigned from such a value and used
  at one of those sinks (`path_display = str(path)`).

A new call site must use the formatters, or this sentry fails.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.sentry.safe_output import _tagger

SRC = Path(__file__).resolve().parents[2] / "src" / "decoy_engine" / "transforms"
FILES = ("_codeset_loader.py", "_codeset/_checks.py", "_codeset_config_checks.py", "code_set.py")
# Locals that hold a corpus locator, label, file-supplied provenance, or an exception.
CORPUS_RISKY = _tagger.SINK_RISKY | frozenset(
    {
        "name",
        "path",
        "resolved",
        "source",
        "stem",
        "handle",
        "config",
        "cfg",
        "prov",
        "provenance",
        "locator",
    }
)
# The formatters themselves are the reviewed boundary; they are not scanned.
FORMATTERS = frozenset({"_where", "_corpus_label", "provenance_summary", "corpus_stat_error"})
# Only these functions return text that leaves the engine (evidence and report values).
OUTWARD_RETURNS = frozenset({"describe_loaded_corpus", "verify_corpus"})
# Locals that hold field names or a registry member, never file or config text.
SAFE_LOCALS = frozenset({"missing", "stamp_defects", "reserved", "embedded", "other"})
_LOG_LEVELS = frozenset({"debug", "info", "warning", "error", "critical", "exception", "log"})


def _sinks(scope: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.expr]:
    sinks: list[ast.expr] = []
    for node in _tagger.own_nodes(scope):
        if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
            sinks += [*node.exc.args, *(k.value for k in node.exc.keywords)]
        elif isinstance(node, ast.Call):
            func = node.func
            if (isinstance(func, ast.Attribute) and func.attr in _LOG_LEVELS) or (
                isinstance(func, ast.Name) and func.id == "CorpusVerifyReport"
            ):
                sinks += [*node.args, *(k.value for k in node.keywords)]
        elif isinstance(node, ast.Return) and node.value and scope.name in OUTWARD_RETURNS:
            sinks.append(node.value)
    return sinks


def findings(source: str) -> list[str]:
    bad: list[str] = []
    for scope in ast.walk(ast.parse(source)):
        if not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if scope.name in FORMATTERS:
            continue
        own = _tagger.own_nodes(scope)
        risky = (CORPUS_RISKY | _tagger.tainted_names(own, CORPUS_RISKY)) - SAFE_LOCALS
        for sink in _sinks(scope):
            for hit in _tagger.risky_in(sink, risky):
                bad.append(f"{scope.name}: {hit} in {ast.unparse(sink)[:80]}")
    return bad


@pytest.mark.parametrize("filename", FILES)
def test_no_corpus_value_reaches_an_outward_sink_outside_the_formatters(filename: str) -> None:
    bad = findings((SRC / filename).read_text(encoding="utf-8"))
    assert not bad, f"{filename}: route through _where/_corpus_label/provenance_summary: {bad}"


@pytest.mark.parametrize(
    "seeded",
    [
        # the three regressions of Codex round 3, plus the older forms
        'def f(name):\n    _LOG.warning("label %r at %s", name, where)\n',
        'def describe_loaded_corpus(config):\n    return {"code_set": config.code_set}\n',
        'def g(path):\n    path_display = str(path)\n    raise E(message=f"at {path_display}")\n',
        'def h(name):\n    raise E(message=f"corpus {name!r}")\n',
        'def i(provenance):\n    raise E(message=f"for {provenance.corpus!r}")\n',
        "def j(path):\n    return CorpusVerifyReport(path=str(path))\n",
        "def l(locator):\n    raise ValueError(str(locator))\n",
        'def describe_loaded_corpus(record):\n    return {"s": record.provenance.source}\n',
        'def k(handle):\n    raise E(message=f"at {handle.display}")\n',
    ],
)
def test_the_sentry_fails_each_seeded_bypass(seeded: str) -> None:
    assert findings(seeded), seeded


def test_the_formatters_pass() -> None:
    clean = (
        "def f(name, path, exc, prov, config):\n"
        '    _LOG.warning("%r at %s", _corpus_label(name), _where(path))\n'
        '    return {"code_set": _corpus_label(config.code_set), **provenance_summary(prov)}\n'
        "def g(path, exc):\n"
        "    shown = _where(path)\n"
        '    raise E(message=f"at {shown} ({type(exc).__name__})")\n'
    )
    assert not findings(clean)
