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
_RETRYABLE = frozenset({"TransientError", "ConnectorError"})


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
    """Call identities: the callee plus its first argument when that is a dotted name.

    The first argument keeps ``s3_call(client.get_object, ...)`` and ``s3_call(body.read, ...)``
    apart, since a wrapper callee runs whatever it is given.
    """
    out: set[str] = set()
    for statement in statements:
        for node in ast.walk(statement):
            if isinstance(node, ast.Call):
                name = dotted(node.func)
                if name:
                    first = dotted(node.args[0]) if node.args else None
                    out.add(f"{name}({first or ''})")
    return out


def findings_in(source: str, path: str) -> list[str]:
    tree = ast.parse(source)
    bindings = import_bindings(tree)
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
        if "TransientError" in names and any(isinstance(p, (ast.For, ast.While)) for p in parents):
            found.append(f"{path}:{node.lineno} except TransientError inside a loop")
        try_node = parents[-1]
        if not isinstance(try_node, ast.Try):
            continue
        again = list(node.body)
        block = parents[-2] if len(parents) > 1 else None
        for field in ("body", "orelse", "finalbody", "handlers"):
            siblings = getattr(block, field, None)
            if isinstance(siblings, list) and try_node in siblings:
                again += siblings[siblings.index(try_node) + 1 :]
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
