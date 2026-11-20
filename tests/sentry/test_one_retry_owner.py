"""F02-E1 AT-E1-6: only ``connectors/_retry.py`` retries a connector failure.

Under ``connectors/``, ``profile/_cloud_readers.py``, ``subset/``, ``publication/`` and
``delivery/`` a sleep, an ``except TransientError`` inside a loop, or an ``except
ConnectorError`` followed by a second call of the same callee is a finding. The two named
state-checked resends are allowed by exact ``(path, function)``, never by file alone.

Covered spellings (accidental use only): ``time.sleep(``, ``sleep(`` after ``from time import
sleep``, ``import time as t``, ``except TransientError`` and tuples naming it, dotted forms.
Not covered: ``getattr``, dynamic imports, a sleep built at run time.
"""

from __future__ import annotations

import ast
from pathlib import Path

from tests.sentry._retry_scan import (
    PKG,
    canonical,
    dotted,
    import_bindings,
    package_of,
    rel,
    walk_with_scope,
)

SCOPES = (
    "connectors",
    "profile/_cloud_readers.py",
    "subset",
    "publication",
    "delivery",
)
OWNER = "connectors/_retry.py"
# The state-checked resends, by exact (path, function). The EC3 pointer-store entry
# `(publication/_object_pointer.py, <method>)` is added by whichever of F02-E1 and EC3 merges
# second; before that the file does not exist.
ALLOWED_RESENDS = frozenset({("connectors/_sftp_client.py", "_resolve_rename")})
# Any of these in a handler makes it a connector-failure handler.
_RETRYABLE = frozenset({"TransientError", "ConnectorError", "PermanentError"})


def _names_in_handler(handler_type: ast.expr | None, bindings: dict[str, str]) -> set[str]:
    if handler_type is None:
        return set()
    nodes = handler_type.elts if isinstance(handler_type, ast.Tuple) else [handler_type]
    found: set[str] = set()
    for node in nodes:
        name = dotted(node)
        if name:
            found.add(canonical(name, bindings).rsplit(".", 1)[-1])
    return found


def _callees(statements: list[ast.stmt]) -> set[str]:
    """Call identities: the callee plus the last attribute of its first dotted argument.

    The argument keeps ``s3_call(client.get_object, ...)`` and ``s3_call(body.read, ...)`` apart,
    since a wrapper callee runs whatever it is given. Only the last attribute counts, so the same
    operation on another receiver (``s3_call(client.put_object)`` then ``s3_call(single.put_object)``)
    is still the same call.
    """
    out: set[str] = set()
    for statement in statements:
        for node in ast.walk(statement):
            if isinstance(node, ast.Call):
                name = dotted(node.func)
                if name:
                    first = dotted(node.args[0]) if node.args else None
                    out.add(f"{name}({first.rsplit('.', 1)[-1] if first else ''})")
    return out


def _in_loop(parents: tuple[ast.AST, ...]) -> bool:
    """A loop encloses the handler within its own function (a nested ``def`` ends the search)."""
    for ancestor in reversed(parents):
        if isinstance(ancestor, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return False
        if isinstance(ancestor, (ast.For, ast.AsyncFor, ast.While)):
            return True
    return False


def _following(try_node: ast.Try, parents: tuple[ast.AST, ...]) -> list[ast.stmt]:
    """Statements that run after ``try_node`` in its own block and in every enclosing block."""
    out: list[ast.stmt] = []
    child: ast.AST = try_node
    for parent in reversed(parents[:-1]):
        for field in ("body", "orelse", "finalbody", "handlers"):
            siblings = getattr(parent, field, None)
            if isinstance(siblings, list) and child in siblings:
                out += siblings[siblings.index(child) + 1 :]
        if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
            break
        child = parent
    return out


def findings_in(source: str, path: str) -> list[str]:
    tree = ast.parse(source)
    bindings = import_bindings(tree, package_of(path))
    found: list[str] = []
    for node, function, parents in walk_with_scope(tree):
        if (
            isinstance(node, ast.Call)
            and path != OWNER
            and (target := dotted(node.func)) is not None
            and canonical(target, bindings) == "time.sleep"
        ):
            found.append(f"{path}:{node.lineno} sleep outside the executor")
        if not isinstance(node, ast.ExceptHandler):
            continue
        names = _names_in_handler(node.type, bindings)
        if not names & _RETRYABLE or (path, function) in ALLOWED_RESENDS or path == OWNER:
            continue
        if _in_loop(parents):
            found.append(f"{path}:{node.lineno} connector-error handler inside a loop")
        try_node = parents[-1]
        if not isinstance(try_node, ast.Try):
            continue
        again = list(node.body) + _following(try_node, parents)
        repeated = _callees(try_node.body) & _callees(again)
        if repeated:
            found.append(f"{path}:{node.lineno} resends {sorted(repeated)[0]} after a failure")
    return found


def _scoped_files() -> list[Path]:
    files: list[Path] = []
    for scope in SCOPES:
        target = PKG / scope
        files += sorted(target.rglob("*.py")) if target.is_dir() else [target]
    return [f for f in files if f.exists()]


def test_no_module_but_the_executor_retries() -> None:
    files = _scoped_files()
    assert any(rel(f) == OWNER for f in files)
    found = [msg for f in files for msg in findings_in(f.read_text("utf-8"), rel(f))]
    assert found == []


def test_walk_covers_every_scoped_directory() -> None:
    names = {rel(f).split("/")[0] for f in _scoped_files()}
    assert {"connectors", "subset", "publication", "delivery", "profile"} <= names


def test_seeded_spellings_are_flagged() -> None:
    seeds = {
        "loop": "for i in range(3):\n    try:\n        f()\n    except TransientError:\n        pass\n",
        "while": "while True:\n    try:\n        f()\n    except (ValueError, TransientError):\n        pass\n",
        "dotted": "while 1:\n    try:\n        f()\n    except sdk.TransientError:\n        pass\n",
        "sleep": "import time\ndef g():\n    time.sleep(1)\n",
        "alias": "import time as t\ndef g():\n    t.sleep(1)\n",
        "from": "from time import sleep\ndef g():\n    sleep(1)\n",
        "from_alias": "from time import sleep as nap\ndef g():\n    nap(1)\n",
        "resend": (
            "def g(c):\n    try:\n        c.put(1)\n    except ConnectorError:\n        c.put(1)\n"
        ),
        "resend_after": (
            "def g(c):\n    try:\n        c.put(1)\n    except ConnectorError:\n        pass\n"
            "    c.put(1)\n"
        ),
    }
    for name, source in seeds.items():
        assert findings_in(source, "connectors/x.py"), name
        assert findings_in(source, "publication/x.py"), name
        assert findings_in(source, "delivery/x.py"), name


def test_review_round_one_seeds_are_flagged() -> None:
    """Spellings the first version missed (Dennis round 1 on #681)."""
    seeds = {
        "loop_connector_error": (
            "def g(c):\n    for _ in range(3):\n        try:\n            return c.put(1)\n"
            "        except ConnectorError as e:\n            if e.kind != 'transient':\n"
            "                raise\n"
        ),
        "loop_continue": (
            "def g(c):\n    for _ in range(3):\n        try:\n            return c.put(1)\n"
            "        except ConnectorError:\n            continue\n"
        ),
        "loop_permanent_error": (
            "def g(c):\n    while True:\n        try:\n            return c.put(1)\n"
            "        except PermanentError:\n            continue\n"
        ),
        "relative_alias_in_loop": (
            "from ..sdk import TransientError as TE\n"
            "def g(c):\n    for i in range(3):\n        try:\n            c.f()\n"
            "        except TE:\n            pass\n"
        ),
        "wrapper_on_another_receiver": (
            "def g(c, single):\n    try:\n        return s3_call(c.put_object, 1)\n"
            "    except ConnectorError:\n        return s3_call(single.put_object, 1)\n"
        ),
        "resend_after_an_enclosing_if": (
            "def g(c, f):\n    if f:\n        try:\n            c.put(1)\n"
            "        except ConnectorError:\n            pass\n    c.put(1)\n"
        ),
    }
    for name, source in seeds.items():
        assert findings_in(source, "connectors/x.py"), name


def test_a_loop_in_an_outer_function_does_not_reach_a_nested_def() -> None:
    source = (
        "def outer(c):\n    for _ in range(3):\n        def inner():\n            try:\n"
        "                return c.get(1)\n            except ConnectorError:\n"
        "                return None\n        inner()\n"
    )
    assert findings_in(source, "connectors/x.py") == []


def test_the_same_wrapper_over_a_different_call_is_not_a_resend() -> None:
    source = (
        "def g(c, b):\n    try:\n        r = call(c.get)\n    except ConnectorError:\n"
        "        return None\n    return call(b.read)\n"
    )
    assert findings_in(source, "connectors/x.py") == []
    again = source.replace("b.read", "c.get")
    assert findings_in(again, "connectors/x.py")


def test_a_catch_without_a_second_call_is_not_a_finding() -> None:
    source = "def g(c):\n    try:\n        return c.get(1)\n    except ConnectorError:\n        return None\n"
    assert findings_in(source, "connectors/x.py") == []


def test_the_executor_is_the_only_allowed_sleeper_and_resends_are_exact() -> None:
    sleeper = "import time\ndef run():\n    time.sleep(1)\n"
    assert findings_in(sleeper, OWNER) == []
    assert findings_in(sleeper, "connectors/_other.py")
    resend = "def _resolve_rename(c):\n    try:\n        c.r()\n    except ConnectorError:\n        c.r()\n"
    assert findings_in(resend, "connectors/_sftp_client.py") == []
    # Same function name in another file, and another function in the same file, are findings.
    assert findings_in(resend, "connectors/sftp.py")
    other = resend.replace("_resolve_rename", "_other")
    assert findings_in(other, "connectors/_sftp_client.py")
