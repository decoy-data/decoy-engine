"""The reason-code guard accepts a `WHEN_REFUSALS` row only through the rule in
`_reason_when_rows`: the real boundaries pass, and each way of smuggling another code in fails.
"""

from __future__ import annotations

import ast
import sys
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _reason_scan as scan
from test_reason_registry import Key, _scan, violations

_SITES = [
    ("execution/_when_gate.py", "code=codes.runtime,"),
    ("expressions/_when_parser.py", "code=codes.config,"),
    ("plan/_checks_when.py", "code=codes.plan,"),
]
_BIND = "= when_refusal_codes(refusal)"


def test_when_refusal_rows_are_registry_symbols() -> None:
    """The rule is safe only while every table value is a `reasons.<ns>.X` symbol."""
    tree = ast.parse((scan.SRC / "expressions/_when_parser.py").read_text(encoding="utf-8"))
    rows = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "WhenRefusalCodes"
    ]
    assert len(rows) == 2
    for call in rows:
        for kw in call.keywords:
            if kw.arg in ("config", "plan", "runtime"):
                chain = scan._chain(kw.value)
                assert chain and chain[0] == "reasons" and len(chain) == 3, ast.unparse(kw.value)


def _mutated(
    tmp_path: Path, rel: str, edit: tuple[str, str], *, all_hits: bool = False
) -> Counter[Key]:
    source = (scan.SRC / rel).read_text(encoding="utf-8")
    old, new = edit
    assert old in source, (rel, old)
    root = tmp_path / "decoy_engine"
    target = root / rel
    target.parent.mkdir(parents=True)
    target.write_text(source.replace(old, new) if all_hits else source.replace(old, new, 1))
    return violations(_scan(root), root)


def _red(found: Counter[Key], rel: str) -> bool:
    return any(k[0] == rel for k in found)


@pytest.mark.parametrize(("rel", "forwarded"), _SITES)
def test_the_real_when_boundaries_are_clean(rel: str, forwarded: str) -> None:
    assert not [k for k in violations(_scan()) if k[0] == rel]


@pytest.mark.parametrize(("rel", "forwarded"), _SITES)
def test_an_ad_hoc_literal_is_still_a_violation(tmp_path: Path, rel: str, forwarded: str) -> None:
    found = _mutated(tmp_path, rel, (forwarded, 'code="adhoc_when_literal",'))
    assert [k for k in found if k[0] == rel and k[4] == "literal"], rel


@pytest.mark.parametrize(("rel", "forwarded"), _SITES)
def test_bound_from_another_call_is_a_violation(tmp_path: Path, rel: str, forwarded: str) -> None:
    assert _red(_mutated(tmp_path, rel, (_BIND, "= other_call(refusal)")), rel)


@pytest.mark.parametrize(("rel", "forwarded"), _SITES)
def test_another_dynamic_value_is_a_violation(tmp_path: Path, rel: str, forwarded: str) -> None:
    assert _red(_mutated(tmp_path, rel, (forwarded, "code=other.code,")), rel)
    assert _red(_mutated(tmp_path / "again", rel, (forwarded, "code=exc.code,")), rel)


@pytest.mark.parametrize(("rel", "forwarded"), _SITES)
def test_a_rebinding_after_the_legitimate_assignment_is_a_violation(
    tmp_path: Path, rel: str, forwarded: str
) -> None:
    """Mutation (1): `codes = other_call(refusal)` after the legitimate assignment."""
    source = (scan.SRC / rel).read_text(encoding="utf-8")
    line = next(ln for ln in source.splitlines() if ln.strip().endswith(_BIND))
    indent = line[: len(line) - len(line.lstrip())]
    rebound = f"{line}\n{indent}codes = other_call(refusal)"
    assert _red(_mutated(tmp_path, rel, (line, rebound)), rel)


@pytest.mark.parametrize(("rel", "forwarded"), _SITES)
def test_the_legitimate_assignment_only_in_a_nested_function_is_a_violation(
    tmp_path: Path, rel: str, forwarded: str
) -> None:
    """Mutation (2): the outer binding comes from another call; the real one hides in a nested def."""
    source = (scan.SRC / rel).read_text(encoding="utf-8")
    line = next(ln for ln in source.splitlines() if ln.strip().endswith(_BIND))
    indent = line[: len(line) - len(line.lstrip())]
    hidden = (
        f"{line.replace(_BIND, '= other_call(refusal)')}\n"
        f"{indent}def _hidden(refusal):\n"
        f"{indent}    codes = when_refusal_codes(refusal)\n"
        f"{indent}    return codes"
    )
    assert _red(_mutated(tmp_path, rel, (line, hidden)), rel)


@pytest.mark.parametrize(("rel", "forwarded"), _SITES)
@pytest.mark.parametrize(
    "extra",
    [
        "codes += 1",
        "codes, _ = other_call(refusal)",
        "(codes := other_call(refusal))",
        "for codes in other_call(refusal): pass",
        "with other_call(refusal) as codes: pass",
        "global codes",
    ],
)
def test_any_other_binding_form_is_a_violation(
    tmp_path: Path, rel: str, forwarded: str, extra: str
) -> None:
    source = (scan.SRC / rel).read_text(encoding="utf-8")
    line = next(ln for ln in source.splitlines() if ln.strip().endswith(_BIND))
    indent = line[: len(line) - len(line.lstrip())]
    assert _red(_mutated(tmp_path, rel, (line, f"{line}\n{indent}{extra}")), rel)


@pytest.mark.parametrize(("rel", "forwarded"), _SITES)
def test_a_binding_inside_a_branch_or_after_the_site_is_a_violation(
    tmp_path: Path, rel: str, forwarded: str
) -> None:
    source = (scan.SRC / rel).read_text(encoding="utf-8")
    line = next(ln for ln in source.splitlines() if ln.strip().endswith(_BIND))
    indent = line[: len(line) - len(line.lstrip())]
    nested = f"{indent}if True:\n{indent}    {line.strip()}"
    assert _red(_mutated(tmp_path, rel, (line, nested)), rel)
