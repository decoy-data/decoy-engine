"""AT-E7 and AT-E8: every signed-evidence refusal is a registered identity, and the adapter reads it.

The raised set is counted by an alias-resolving AST walk at build time, not by grep: every
production ``SignedEvidenceError(...)`` and every call to a wrapper that builds one takes a
``ReasonCode`` symbol, never a string. The wire tokens a conformance vector pins are one injective
table from those identities.
"""

from __future__ import annotations

import ast
import json
import pickle
from pathlib import Path

import pytest

from decoy_engine import reason_adapter, reasons
from decoy_engine.errors import DecoyError
from decoy_engine.reasons import ReasonCode, evidence
from decoy_engine.signed_evidence import SignedEvidenceError

ROOT = Path(__file__).resolve().parents[3]
PKG = ROOT / "src" / "decoy_engine" / "signed_evidence"
CORPUS = ROOT / "tests" / "fixtures" / "signed_evidence" / "v1" / "vectors"
RAISERS = {"SignedEvidenceError", "_err", "_bad", "_schema", "_refusal", "_fail"}
_NOT_SYMBOLS = {"INNER_CODES", "WIRE_IDENTITY", "WIRE_TOKEN"}
SYMBOLS = frozenset(n for n in dir(evidence) if n.isupper()) - _NOT_SYMBOLS


def _aliases(tree: ast.Module) -> set[str]:
    """Every local name that is a raiser, following ``e = _err`` style assignments to a fixpoint."""
    names = set(RAISERS)
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, (ast.Name, ast.Attribute)):
                src = node.value.id if isinstance(node.value, ast.Name) else node.value.attr
                if src in names:
                    for target in node.targets:
                        if isinstance(target, ast.Name) and target.id not in names:
                            names.add(target.id)
                            changed = True
    return names


def _typed_reason_names(tree: ast.Module) -> dict[int, set[str]]:
    """Per function id: the names annotated as a ``ReasonCode`` (parameters and local annotations)."""
    out: dict[int, set[str]] = {}
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        typed: set[str] = set()
        for arg in (*fn.args.args, *fn.args.kwonlyargs):
            if arg.annotation is not None and "ReasonCode" in ast.unparse(arg.annotation):
                typed.add(arg.arg)
        for node in ast.walk(fn):
            if (
                isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and "ReasonCode" in ast.unparse(node.annotation)
            ):
                typed.add(node.target.id)
        out[id(fn)] = typed
    return out


def _module_reason_dicts(tree: ast.Module) -> set[str]:
    return {
        node.target.id
        for node in tree.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and "ReasonCode" in ast.unparse(node.annotation)
    }


def _enclosing(tree: ast.Module) -> dict[int, ast.AST]:
    parent: dict[int, ast.AST] = {}
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for node in ast.walk(fn):
                parent[id(node)] = fn  # the innermost function wins: ast.walk is breadth first
    return parent


def _arg_ok(arg: ast.AST, typed: set[str], dicts: set[str], aliases: set[str]) -> bool:
    if isinstance(arg, ast.Attribute):
        if arg.attr == "identity":
            return True
        return isinstance(arg.value, ast.Name) and arg.value.id == "ev" and arg.attr in SYMBOLS
    if isinstance(arg, ast.BoolOp):
        return all(_arg_ok(v, typed, dicts, aliases) for v in arg.values)
    if isinstance(arg, ast.Subscript):
        return isinstance(arg.value, ast.Name) and arg.value.id in dicts
    return False


def string_code_sites(source: str) -> list[str]:
    """Raiser calls whose code argument is not a registered symbol (a literal, f-string or bare name)."""
    tree = ast.parse(source)
    aliases = _aliases(tree)
    typed_by_fn = _typed_reason_names(tree)
    dicts = _module_reason_dicts(tree)
    owner = _enclosing(tree)
    bad: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        if name not in aliases or not node.args:
            continue
        index = 0
        fn = owner.get(id(node))
        typed = typed_by_fn.get(id(fn), set()) if fn is not None else set()
        if not _arg_ok(node.args[index], typed, dicts, aliases):
            bad.append(f"line {node.lineno}: {ast.unparse(node.args[index])}")
    return bad


def test_every_production_raise_takes_a_registered_symbol() -> None:
    for path in sorted(PKG.glob("*.py")):
        if path.name == "_errors.py":
            continue
        assert string_code_sites(path.read_text(encoding="utf-8")) == [], path.name


@pytest.mark.parametrize(
    "source",
    [
        'def f():\n    raise SignedEvidenceError("SIGNING_FAILED")\n',
        "def _bad(code):\n    return SignedEvidenceError(code)\n",
        'def f(x):\n    raise _err(f"STATEMENT_{x}")\n',
        'e = _err\ndef f():\n    raise e("TOO_DEEP")\n',
        'def f(exc):\n    raise SignedEvidenceError(f"TRUST_POLICY_{exc.code}")\n',
        "def f(prefix, code):\n    return _fail(prefix + code)\n",
    ],
)
def test_the_walk_catches_each_seeded_raw_string(source: str) -> None:
    assert string_code_sites(source), source


@pytest.mark.parametrize(
    "source",
    [
        "def f():\n    raise SignedEvidenceError(ev.SIGNING_FAILED)\n",
        "_W: dict[ReasonCode, ReasonCode] = {ev.BOM: ev.STATEMENT_BOM}\ndef f(inner):\n    raise SignedEvidenceError(_W[inner])\n",
    ],
)
def test_the_walk_accepts_registered_symbols(source: str) -> None:
    assert string_code_sites(source) == [], source


def _evidence_identities() -> set[ReasonCode]:
    return {ReasonCode(s.code, s.namespace) for s in reasons.specs() if s.namespace == "evidence"}


def test_the_wire_table_is_total_and_injective_over_the_registered_identities() -> None:
    identities = _evidence_identities()
    assert set(evidence.WIRE_TOKEN) == identities and len(identities) > 100
    assert len(set(evidence.WIRE_TOKEN.values())) == len(evidence.WIRE_TOKEN)
    assert {evidence.WIRE_IDENTITY[t] for t in evidence.WIRE_TOKEN.values()} == identities
    for identity, token in evidence.WIRE_TOKEN.items():
        assert token == token.upper() and identity == identity.lower()
        assert evidence.WIRE_IDENTITY[token] == identity


def test_every_identity_resolves_in_1_30_with_a_fixed_summary() -> None:
    for identity in evidence.WIRE_TOKEN:
        spec = reasons.get("evidence", str(identity))
        assert spec.since == "1.30.0"
        assert spec.summary.startswith("Signed evidence was refused")


def test_the_corpus_raised_tokens_are_registered() -> None:
    raised: set[str] = set()
    for path in CORPUS.glob("*/expected.json"):
        doc = json.loads(path.read_text(encoding="utf-8"))
        if doc.get("load_error"):
            raised.add(doc["load_error"])
        if doc.get("schema") in {"MALFORMED", "UNSUPPORTED"}:
            raised.update(doc.get("reasons_include", []))
    assert raised, "the corpus names no raised token"
    assert raised <= set(evidence.WIRE_IDENTITY), sorted(raised - set(evidence.WIRE_IDENTITY))


def test_a_composite_token_is_a_row_of_its_own() -> None:
    inner = evidence.NOT_JSON
    assert (
        evidence.WIRE_TOKEN[evidence.wire_for(evidence.Prefix.STATEMENT, inner)]
        == "STATEMENT_NOT_JSON"
    )
    assert evidence.WIRE_TOKEN[
        evidence.wire_for(evidence.Prefix.EXPECTATIONS, evidence.TOO_LARGE)
    ] == ("EXPECTATIONS_TOO_LARGE")
    with pytest.raises(KeyError):
        evidence.wire_for(
            evidence.Prefix.ENVELOPE, evidence.BOM
        )  # mapped to NOT_JSON by the caller


def test_the_constructor_takes_a_symbol_or_a_known_wire_token_and_nothing_else() -> None:
    by_symbol = SignedEvidenceError(evidence.SIGNING_FAILED)
    by_token = SignedEvidenceError("SIGNING_FAILED")
    assert by_symbol.identity == by_token.identity == evidence.SIGNING_FAILED
    assert by_symbol.code == "SIGNING_FAILED" and str(by_symbol) == "SIGNING_FAILED"
    for bad in (
        "signing_failed",
        "NOT_A_TOKEN",
        "",
        5,
        None,
        ReasonCode("signing_failed", "runtime"),
    ):
        with pytest.raises(ValueError):
            SignedEvidenceError(bad)  # type: ignore[arg-type]


def test_the_error_is_a_decoy_error_with_no_cause_or_context_and_survives_pickle() -> None:
    err = SignedEvidenceError(evidence.STATEMENT_NOT_JSON, status="MALFORMED")
    assert isinstance(err, DecoyError)
    assert err.__cause__ is None and err.__context__ is None
    clone = pickle.loads(pickle.dumps(err))  # noqa: S301 -- own round trip
    assert (clone.code, clone.status, clone.identity) == (err.code, err.status, err.identity)


# -- AT-E8: the adapter reads the stored identity, never the uppercase token ----------------------


def test_the_adapter_resolves_the_exact_stored_identity() -> None:
    for identity in (
        evidence.SIGNING_FAILED,
        evidence.STATEMENT_NOT_JSON,
        evidence.BUNDLE_ROOT_MISSING,
    ):
        record = reason_adapter.reason_from_exception(SignedEvidenceError(identity))
        assert (record.namespace, record.code) == ("evidence", str(identity))
        assert record.code != reasons.decoy.UNREGISTERED_REASON


def test_the_adapter_does_not_classify_the_uppercase_code() -> None:
    err = SignedEvidenceError(evidence.SIGNING_FAILED)
    err.identity = "SIGNING_FAILED"  # type: ignore[assignment]  # a plain string is not a registered identity
    record = reason_adapter.reason_from_exception(err)
    assert (record.namespace, record.code) == ("decoy", str(reasons.decoy.UNREGISTERED_REASON))


def test_the_identified_family_is_in_the_adapter_tables() -> None:
    assert (
        "decoy_engine.signed_evidence._errors",
        "SignedEvidenceError",
    ) in reason_adapter._IDENTIFIED
    assert SignedEvidenceError in reason_adapter.registered_families()
    assert "SignedEvidenceError" in reason_adapter.registered_family_names()
    assert SignedEvidenceError in reason_adapter.loaded_families()


def test_every_identified_entry_names_its_defining_module() -> None:
    import importlib

    for module, name in reason_adapter._IDENTIFIED:
        assert getattr(importlib.import_module(module), name).__module__ == module


def test_each_module_table_equals_the_wire_for_product() -> None:
    from decoy_engine.signed_evidence import _catalog, _envelope, _expectations, _statement, _trust

    mods = {
        evidence.Prefix.STATEMENT: _statement,
        evidence.Prefix.TRUST_POLICY: _trust,
        evidence.Prefix.CATALOG: _catalog,
        evidence.Prefix.EXPECTATIONS: _expectations,
        evidence.Prefix.ENVELOPE: _envelope,
    }
    for prefix, mod in mods.items():
        expected = {}
        for inner in evidence.INNER_CODES:
            try:
                expected[inner] = evidence.wire_for(prefix, inner)
            except KeyError:
                continue
        assert expected == mod._WIRE, prefix
