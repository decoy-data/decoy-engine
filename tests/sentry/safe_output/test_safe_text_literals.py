"""F31 AE1 sentry: ``SafeText`` is built from literals and approved slots only.

`SafeText.const` and `.template` must receive string literals, so the text a sink prints was
written in source and reviewed there. A template's slot arguments are checked with the shared
tagger: a name, path or count taken from an exception or a data value (`row["name"]`) fails,
because `approve_name` checks shape only and a person's name passes it. Nothing outside
`safe_output/_render.py` may construct a `SafeText` any other way.
"""

from __future__ import annotations

import ast
import string
from pathlib import Path

import pytest

from tests.sentry.safe_output._alias_cases import ALIAS_IDS, forms
from tests.sentry.safe_output._resolve import aliases, last, names_class, qualified
from tests.sentry.safe_output._scopes import exposes, iter_scopes
from tests.sentry.safe_output._tagger import risky_in

SRC = Path(__file__).resolve().parents[3] / "src" / "decoy_engine"
_RENDER_MODULE = "safe_output/_render.py"
_SLOT_KINDS = ("names", "paths", "counts")


def _is_str_literal(node: ast.expr | None) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def _slots(literal: str) -> set[str] | None:
    try:
        return {f for _, f, _, _ in string.Formatter().parse(literal) if f is not None}
    except ValueError:
        return None


def _template_findings(call: ast.Call, risky: frozenset[str]) -> list[str]:
    found: list[str] = []
    if len(call.args) != 1 or not _is_str_literal(call.args[0]):
        return ["template takes one string literal"]
    keys: set[str] = set()
    for kw in call.keywords:
        if kw.arg not in _SLOT_KINDS:
            found.append(f"template argument {kw.arg!r} is not a slot kind")
            continue
        if not isinstance(kw.value, ast.Dict) or any(
            k is None or not _is_str_literal(k) for k in kw.value.keys
        ):
            found.append(f"{kw.arg} must be a dict display with literal keys")
            continue
        for key, value in zip(kw.value.keys, kw.value.values, strict=True):
            keys.add(ast.literal_eval(key))  # type: ignore[arg-type]
            hits = risky_in(value, risky)
            if hits or exposes(value, risky):
                found.append(
                    f"slot {ast.literal_eval(key)!r} takes a tagged value {sorted(set(hits))}"
                )  # type: ignore[arg-type]
    literal = ast.literal_eval(call.args[0])
    if _slots(literal) != keys:
        found.append("template slots and arguments differ")
    return found


_PRIVATE = frozenset({"_mint", "_TOKEN"})
_CONSTRUCTORS = frozenset({"const", "template"})


def _private_reference(node: ast.AST) -> bool:
    """`_mint` anywhere, or `_TOKEN` taken from the renderer module (other modules own a `_TOKEN`)."""
    if isinstance(node, ast.Attribute):
        return node.attr == "_mint" or (
            node.attr == "_TOKEN" and ast.unparse(node.value).endswith("_render")
        )
    if isinstance(node, ast.Name):
        return node.id == "_mint"
    if isinstance(node, ast.ImportFrom):
        return any(
            a.name == "_mint" or (a.name == "_TOKEN" and (node.module or "").endswith("_render"))
            for a in node.names
        )
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getattr":
        return any(
            isinstance(a, ast.Constant) and a.value in ("_mint", "_TOKEN") for a in node.args
        )
    return isinstance(node, ast.Constant) and node.value == "_mint"


def literal_findings(source: str, rel_path: str) -> list[str]:
    """Every `SafeText` construction in `source` that is not a literal or an approved slot.

    Names resolve through the shared resolver (imports, rebindings, qualified names). Any
    `.const` or `.template` call outside the renderer is checked whatever its receiver is, so a
    stored `SafeText` instance or a rebound classmethod cannot dodge the literal rule.
    """
    tree = ast.parse(source)
    in_render = rel_path == _RENDER_MODULE
    risky: frozenset[str] = frozenset().union(*(r for _, _, r in iter_scopes(tree)))
    known = aliases(tree)

    def is_safe_text(node: ast.expr) -> bool:
        return names_class(node, known, "SafeText")

    direct = {id(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
    found: list[str] = []
    for node in ast.walk(tree):
        where = f"{rel_path}:{getattr(node, 'lineno', 0)}"
        if not in_render and _private_reference(node):
            found.append(f"{where}: reference to a renderer-private name")
        if isinstance(node, ast.Attribute) and is_safe_text(node.value):
            if node.attr in _CONSTRUCTORS and id(node) not in direct:
                found.append(f"{where}: SafeText.{node.attr} used other than as a direct call")
        if not isinstance(node, ast.Call):
            continue
        if is_safe_text(node.func) and not in_render:
            found.append(f"{where}: SafeText(...) built directly")
        if (
            isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and node.args
            and is_safe_text(node.args[0])
        ):
            found.append(f"{where}: getattr on SafeText")
        target = qualified(node.func, known)
        tail = node.func.attr if isinstance(node.func, ast.Attribute) else last(target)
        if tail in _CONSTRUCTORS and (
            isinstance(node.func, ast.Attribute) or "SafeText" in target.split(".")
        ):
            if tail == "const":
                if len(node.args) != 1 or node.keywords or not _is_str_literal(node.args[0]):
                    found.append(f"{where}: const takes one string literal")
            else:
                found += [f"{where}: {m}" for m in _template_findings(node, risky)]
    return found


def test_every_safe_text_is_a_literal_or_an_approved_slot() -> None:
    found: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        found += literal_findings(path.read_text(encoding="utf-8"), rel)
    assert not found, "SafeText must be built from literals and approved slots only: " + "; ".join(
        found
    )


def test_the_renderer_itself_is_scanned() -> None:
    text = (SRC / _RENDER_MODULE).read_text(encoding="utf-8")
    assert "SafeText.template(" in text and literal_findings(text, _RENDER_MODULE) == []


@pytest.mark.parametrize(
    "source",
    [
        "def f(exc):\n    return SafeText.const(str(exc))\n",
        "def f(x):\n    return SafeText.const(x)\n",
        "def f():\n    return SafeText.const(f'a {1}')\n",
        "def f():\n    return SafeText.const('a', 'b')\n",
        "def f(row):\n    return SafeText.template('column {name}', names={'name': row['name']})\n",
        "def f(exc):\n    return SafeText.template('x {p}', paths={'p': str(exc)})\n",
        "def f(value):\n    return SafeText.template('x {n}', counts={'n': value})\n",
        "def f(cell):\n    v = cell\n    return SafeText.template('c {a}', names={'a': v})\n",
        "def f(a):\n    return SafeText.template(a, names={})\n",
        "def f(a):\n    return SafeText.template('c {a}', **a)\n",
        "def f(a):\n    return SafeText.template('c {a}', names=a)\n",
        "def f(a):\n    return SafeText.template('c {a} {b}', names={'a': 'x'})\n",
        "def f(a):\n    return SafeText.template('c', names={'a': 'x'})\n",
        "def f(a):\n    return SafeText.template('c', labels={'a': 'x'})\n",
        "def f(a):\n    return SafeText('x', _token=a)\n",
        "def f(a):\n    return SafeText._mint(a)\n",
        "from decoy_engine import safe_output\ndef f(x):\n    return safe_output.SafeText.const(x)\n",
        "from decoy_engine.safe_output import _render\ndef f(x):\n    return _render.SafeText._mint(x)\n",
        "from decoy_engine.safe_output import SafeText as ST\ndef f(x):\n    return ST.const(x)\n",
        "def f(x):\n    return getattr(SafeText, '_mint')(x)\n",
        "def f(x):\n    c = SafeText.const\n    return c(x)\n",
        "from decoy_engine.safe_output._render import SafeText as S, _TOKEN\ndef f(x):\n    return S(x, _token=_TOKEN)\n",
        "g = lambda exc: SafeText.const(str(exc))\n",
    ],
    ids=[
        "const_str_exc",
        "const_name",
        "const_fstring",
        "const_two_args",
        "value_in_name_slot",
        "exc_in_path_slot",
        "value_in_count_slot",
        "tainted_assignment",
        "template_not_literal",
        "starstar",
        "slot_dict_not_display",
        "slot_without_argument",
        "argument_without_slot",
        "unknown_kind",
        "direct_construction",
        "mint_outside_renderer",
        "qualified_const",
        "module_qualified_mint",
        "aliased_const",
        "getattr_mint",
        "const_stored_then_called",
        "aliased_direct_with_token",
        "lambda",
    ],
)
def test_sentry_catches_a_bad_construction(source: str) -> None:
    assert literal_findings(source, "scratch/_x.py")


@pytest.mark.parametrize(
    "source",
    [
        "def f():\n    return SafeText.const('a fixed line')\n",
        "def f(col, n):\n    return SafeText.template('c {c} {n}', names={'c': col}, counts={'n': n})\n",
        "def f(ctx):\n    return SafeText.template('o={r}', names={'r': ctx.object_ref})\n",
        "def f(p):\n    return SafeText.template('in {p}', paths={'p': p})\n",
    ],
)
def test_sentry_passes_a_clean_construction(source: str) -> None:
    assert literal_findings(source, "scratch/_x.py") == []


def test_the_renderer_may_mint() -> None:
    assert literal_findings("def f(t):\n    return SafeText._mint(t)\n", _RENDER_MODULE) == []


@pytest.mark.parametrize(("prelude", "expr"), forms("SafeText"), ids=ALIAS_IDS)
def test_every_alias_of_safe_text_is_checked(prelude: str, expr: str) -> None:
    bad = f"{prelude}def f(row):\n    return {expr}.const(row[0])\n"
    good = f"{prelude}def f():\n    return {expr}.const('fixed')\n"
    assert literal_findings(bad, "scratch/_x.py")
    assert literal_findings(good, "scratch/_x.py") == []


@pytest.mark.parametrize(
    "source",
    [
        "def f(row):\n    s = SafeText.const('a')\n    return s.const(row[0])\n",
        "def f(row):\n    return make().template('x {n}', counts={'n': int(row['pin'])})\n",
        "def f(account):\n    return SafeText.template('c {a}', names={'a': account.password})\n",
        "def f(row):\n    return SafeText.template('c {a}', names={'a': [p for p in row][0]})\n",
        "def f(x):\n    return SafeText.template('n {n}', counts={'n': int(x)})\n",
    ],
    ids=["stored_instance", "other_receiver", "value_attribute", "comprehension", "int_conversion"],
)
def test_sentry_catches_a_value_through_another_route(source: str) -> None:
    assert literal_findings(source, "scratch/_x.py")


def test_private_exemption_needs_the_full_renderer_path() -> None:
    src = "def f(t):\n    return SafeText._mint(t)\n"
    assert literal_findings(src, _RENDER_MODULE) == []
    assert literal_findings(src, "other/" + _RENDER_MODULE)
