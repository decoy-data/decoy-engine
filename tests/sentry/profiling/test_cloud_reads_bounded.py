"""S-G7: every cloud read in `profile/` asks for a bounded byte range (F25 G7-1).

A profile reader that pulls a whole object holds it in memory, so a large object can exhaust
the host. The bounded path is a ranged S3 `get_object`, a ranged `gcs_download` and a sized
`read`. This sentry scans `src/decoy_engine/profile/` and fails on:

- a `get_object` call, direct or passed to `s3_call`, without `Range=` or without `IfMatch=`
  (an unpinned range can mix two versions of the object);
- a `gcs_download` call without `start=` and `end=`, under any import alias;
- any `download_as_bytes`, `download_as_string` or `download_as_text` call;
- a `.read()` with no size, called directly or passed to another call (`s3_call(stream.read)`).

Aliases resolve through `tests.sentry.fa.resolve`. Named limit: a bound method stored in a
variable and called later is not seen; the seeded fixtures cover the realistic bypasses.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.sentry.fa.resolve import ProjectIndex, Scope, build_import_map, module_name, resolve

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
PROFILE = SRC / "decoy_engine" / "profile"
GCS_DOWNLOAD = "decoy_engine.connectors._clients.gcs_download"
WHOLE_DOWNLOADS = frozenset({"download_as_bytes", "download_as_string", "download_as_text"})


def _kw(call: ast.Call) -> set[str]:
    return {k.arg for k in call.keywords if k.arg is not None}


def _unsized_read(node: ast.AST) -> bool:
    return isinstance(node, ast.Attribute) and node.attr == "read"


def findings(text: str, module: str, is_package: bool = False) -> list[str]:
    """Unbounded cloud reads in one module's source text, as `line: reason` strings."""
    tree = ast.parse(text)
    index = ProjectIndex(package="decoy_engine")
    index.add(module, tree, is_package)
    scope = Scope(build_import_map(tree.body, module, is_package))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            scope.imports.update(build_import_map(node.body, module, is_package))
    out: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func, line = node.func, node.lineno
        attr = func.attr if isinstance(func, ast.Attribute) else None
        name = func.id if isinstance(func, ast.Name) else attr
        if attr in WHOLE_DOWNLOADS:
            out.append(f"{line}: whole-object {attr}")
        first = node.args[0] if node.args else None
        passed = first.attr if isinstance(first, ast.Attribute) else None
        if "get_object" in (attr, passed):
            how = "get_object" if attr == "get_object" else "get_object passed"
            missing = [k for k in ("Range", "IfMatch") if k not in _kw(node)]
            out.extend(f"{line}: {how} without {k}" for k in missing)
        if first is not None and _unsized_read(first) and len(node.args) < 2:
            out.append(f"{line}: read passed without a size")
        if attr == "read" and not node.args and not node.keywords:
            out.append(f"{line}: read() without a size")
        if name == "gcs_download" or resolve(func, scope, index) == GCS_DOWNLOAD:
            if not {"start", "end"} <= _kw(node):
                out.append(f"{line}: gcs_download without start= and end=")
    return out


def test_profile_cloud_reads_are_ranged() -> None:
    found: list[str] = []
    for path in sorted(PROFILE.rglob("*.py")):
        module = module_name(path, SRC)
        text = path.read_text(encoding="utf-8")
        for item in findings(text, module, path.name == "__init__.py"):
            found.append(f"{path.relative_to(ROOT)}:{item}")
    assert found == [], "unbounded cloud reads in profile/:\n" + "\n".join(found)


SEEDED = {
    "bare_read": "def f(stream):\n    return stream.read()\n",
    "s3_call_read": (
        "from decoy_engine.connectors import _clients\n"
        "def f(stream):\n    return _clients.s3_call(stream.read)\n"
    ),
    "aliased_gcs_download": (
        "from ..connectors import _clients as c\ndef f(blob):\n    return c.gcs_download(blob)\n"
    ),
    "download_as_bytes": "def f(blob):\n    return blob.download_as_bytes()\n",
    "get_object_no_range": (
        "def f(client, b, k):\n    return client.get_object(Bucket=b, Key=k, IfMatch='e')\n"
    ),
    "get_object_unpinned": (
        "from decoy_engine.connectors import _clients\n"
        "def f(client):\n"
        "    return _clients.s3_call(client.get_object, Bucket='b', Key='k', Range='bytes=0-1')\n"
    ),
}


# Each get_object seed lacks one keyword, so its finding must name that keyword.
_DIAGNOSTIC = {"get_object_no_range": "without Range", "get_object_unpinned": "without IfMatch"}


@pytest.mark.parametrize("case", sorted(SEEDED))
def test_seeded_bypass_is_caught(case: str) -> None:
    found = findings(SEEDED[case], "decoy_engine.profile._cloud_readers")
    assert found != []
    assert all(_DIAGNOSTIC.get(case, "") in item for item in found), found


def test_ranged_forms_pass() -> None:
    ok = (
        "from decoy_engine.connectors import _clients as c\n"
        "def f(client, blob, stream, n):\n"
        "    c.s3_call(client.get_object, Bucket='b', Key='k', Range='bytes=0-1', IfMatch='e')\n"
        "    c.s3_call(stream.read, n)\n"
        "    stream.read(n)\n"
        "    return c.gcs_download(blob, start=0, end=1, size=2, generation=3)\n"
    )
    assert findings(ok, "decoy_engine.profile._cloud_readers") == []
