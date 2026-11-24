"""One file-identity protocol for every file-backed lazy source in `decoy_engine.profile`.

A `LazySource` subclass that reads a plain file (CSV, fixed-width) has no footer, so it must
check the file's identity around its facts pass and its batch read. That protocol lives in
`profile/_lazy_identity.py` (`LazyFileIdentity`). A subclass that took its own stat, kept its own
fact cache or raised `lazy_source_changed` itself would be a second copy that can drift, and the
check that a copy forgets is the one that routes on one file and reads another.

Offenders, per module under `profile/` other than the helper: a `LazySource` subclass without
`LazyFileIdentity` among its bases (the Parquet `LazySource` in `_readers.py` is the base, with a
footer, and is exempt), a method named `_identity`, or a call to `lazy_source_changed`.
Every `LazySource` (the base included) that defines `iter_batches` or `open_batches` must call
`check_batch_rows` in that method, so the batch size is validated in one way. Names resolve
through import aliases, so `as` renames and `module.name` calls are seen.
"""

from __future__ import annotations

import ast
from pathlib import Path

from tests.sentry.safe_output._resolve import aliases as _aliases
from tests.sentry.safe_output._resolve import qualified as _qualified

SRC = Path(__file__).parents[2] / "src" / "decoy_engine"
PROFILE = SRC / "profile"
HELPER = "_lazy_identity.py"
BASE_MODULE = "_readers.py"
_BATCH_METHODS = {"iter_batches", "open_batches"}


def _is(qualified: str, name: str) -> bool:
    return qualified.rsplit(".", 1)[-1] == name


def _calls(node: ast.AST, aliases: dict[str, str], name: str) -> list[ast.Call]:
    return [
        c
        for c in ast.walk(node)
        if isinstance(c, ast.Call) and _is(_qualified(c.func, aliases), name)
    ]


def violations(source: str, *, is_base_module: bool = False) -> list[str]:
    """What a module under `profile/` does that bypasses the shared identity helper or the
    shared batch-size check. Names resolve through the module's imports and `X = Y` rebinding."""
    tree = ast.parse(source)
    aliases = _aliases(tree)
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            bases = [_qualified(b, aliases) for b in node.bases]
            is_lazy = any(_is(b, "LazySource") for b in bases) or (
                is_base_module and node.name == "LazySource"
            )
            has_helper = any(_is(b, "LazyFileIdentity") for b in bases)
            if is_lazy and not has_helper and not is_base_module:
                found.append(f"{node.lineno}: {node.name} subclasses LazySource without the helper")
            if is_lazy:
                for method in node.body:
                    if (
                        isinstance(method, ast.FunctionDef)
                        and method.name in _BATCH_METHODS
                        and not _calls(method, aliases, "check_batch_rows")
                    ):
                        found.append(
                            f"{method.lineno}: {node.name}.{method.name} skips check_batch_rows"
                        )
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "_identity":
            found.append(f"{node.lineno}: own _identity")
        elif isinstance(node, ast.Call) and _is(
            _qualified(node.func, aliases), "lazy_source_changed"
        ):
            found.append(f"{node.lineno}: calls lazy_source_changed")
    return found


def test_every_file_backed_lazy_source_uses_the_shared_identity_helper() -> None:
    offenders: dict[str, list[str]] = {}
    for path in sorted(PROFILE.glob("*.py")):
        if path.name == HELPER:
            continue
        found = violations(
            path.read_text(encoding="utf-8"), is_base_module=path.name == BASE_MODULE
        )
        if found:
            offenders[path.name] = found
    assert not offenders, f"file identity handled outside profile/{HELPER}: {offenders}"


def test_the_sentry_sees_the_helper_and_both_backends() -> None:
    helper = (PROFILE / HELPER).read_text(encoding="utf-8")
    assert {"own _identity", "calls lazy_source_changed"} <= {
        line.split(": ", 1)[1] for line in violations(helper)
    }
    for name in ("_lazy_csv.py", "_lazy_fixed_width.py"):
        text = (PROFILE / name).read_text(encoding="utf-8")
        assert "LazyFileIdentity" in text and "LazySource" in text


def test_the_walk_sees_a_seeded_violation_per_spelling() -> None:
    own_class = "class Mine(LazySource):\n    pass\n"
    assert violations(own_class) == ["1: Mine subclasses LazySource without the helper"]
    aliased_base = "from decoy_engine.profile._readers import LazySource as Base\nclass Mine(Base):\n    pass\n"
    assert violations(aliased_base) == ["2: Mine subclasses LazySource without the helper"]
    module_base = "import decoy_engine.profile._readers as r\nclass Mine(r.LazySource):\n    pass\n"
    assert len(violations(module_base)) == 1
    rebound = "from x import LazySource\nBase = LazySource\nclass Mine(Base):\n    pass\n"
    assert len(violations(rebound)) == 1
    dotted = "class Mine(_readers.LazySource):\n    pass\n"
    assert len(violations(dotted)) == 1
    assert violations("class Mine(LazyFileIdentity, LazySource):\n    pass\n") == []
    assert violations("class A:\n    def _identity(self):\n        return 1\n") == [
        "2: own _identity"
    ]
    assert violations("raise lazy_source_changed(t, 'x')\n") == ["1: calls lazy_source_changed"]
    assert violations("raise mod.lazy_source_changed(t, 'x')\n") == ["1: calls lazy_source_changed"]
    assert violations(own_class, is_base_module=True) == []
    assert violations("from x import lazy_source_changed as lazy_source_changed\n") == []


_GOOD = "class Mine(LazyFileIdentity, LazySource):\n    def {name}(self, batch_rows):\n{body}\n"


def test_a_batch_method_must_call_check_batch_rows() -> None:
    for name in ("iter_batches", "open_batches"):
        bare = _GOOD.format(name=name, body="        return batch_rows")
        assert violations(bare) == [f"2: Mine.{name} skips check_batch_rows"]
        direct = _GOOD.format(name=name, body="        check_batch_rows(batch_rows)")
        assert violations(direct) == []
        renamed = "from decoy_engine.profile._lazy_identity import check_batch_rows as ok\n" + (
            _GOOD.format(name=name, body="        ok(batch_rows)")
        )
        assert violations(renamed) == []
        modular = "import decoy_engine.profile._lazy_identity as ident\n" + _GOOD.format(
            name=name, body="        ident.check_batch_rows(batch_rows)"
        )
        assert violations(modular) == []
        helperless = f"class Mine(LazySource):\n    def {name}(self, n):\n        return n\n"
        assert len(violations(helperless)) == 2
    other = _GOOD.format(name="to_table", body="        return 1")
    assert violations(other) == []


def test_the_base_class_is_held_to_the_batch_size_rule() -> None:
    base = "class LazySource:\n    def iter_batches(self, n):\n        return n\n"
    assert violations(base, is_base_module=True) == [
        "2: LazySource.iter_batches skips check_batch_rows"
    ]
    assert violations(base) == []
