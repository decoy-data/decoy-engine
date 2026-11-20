"""One carrier rule (OUTPUT-METADATA-LEAK E2): source metadata reaches a schema in memory only
through `attach_output_metadata(schema, meta)`.

Two checks over `src/decoy_engine`, both pure AST:

1. Schema-metadata argument. The `metadata=` keyword (or second positional) of `pa.schema`, the
   `metadata=` keyword of `pa.record_batch` and `from_arrays`, and the argument of
   `replace_schema_metadata` and `with_metadata` must be `None` or a literal. A local name, a
   `.metadata` read or a dict merge fails. `sanitized_schema_metadata` may be called only inside
   `safe_output/`.
2. Whole-schema reuse. On output-bound modules (the carrier sites of the plan and
   `execution/out_of_core/`), the `schema=` argument of `Table.from_arrays`, `Table.from_batches`,
   `record_batch`, `RecordBatch.from_arrays` and `pa.table` (and a schema argument of
   `Table.cast`) must be a value of `output_schema(...)` or `attach_output_metadata(...)`, or a
   schema shown metadata-free in the same function (`pa.schema(fields)` with no metadata, or
   `remove_metadata()`). Re-using `x.schema` or a source schema fails, unless the (module,
   function) is a row of `baselines/metadata-carrier-allow.json`: a same-object rebuild that keeps
   only what the object already carried. The baseline is shrink-only.

Named limits: a schema reached through a call this scan does not know, a `getattr` and a
`**kwargs` spelling are not modelled; field-level `metadata=` on `pa.field` is out of scope (the
writers strip field metadata).
"""

from __future__ import annotations

import ast
import json
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from tests.sentry.defects import _defect_scan as scan

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src" / "decoy_engine"
BASELINE = ROOT / "tests" / "sentry" / "baselines" / "metadata-carrier-allow.json"

SAFE_OUTPUT = "safe_output/"
OUTPUT_BOUND = (
    "execution/out_of_core/",
    "execution/_transforms_table.py",
    "execution/_faker_degenerate_pin.py",
    "execution/_chunked_output_sink.py",
)
SANITIZED = frozenset({"output_schema", "attach_output_metadata"})
SCHEMA_KEYWORD_CALLS = frozenset({"from_arrays", "from_batches", "record_batch", "table"})
METADATA_CALLS = frozenset({"schema", "record_batch", "from_arrays"})
METADATA_SETTERS = frozenset({"replace_schema_metadata", "with_metadata"})
SEEDED = "execution/out_of_core/_x.py"


@dataclass(frozen=True)
class Finding:
    path: str
    function: str
    rule: str
    line: int

    @property
    def key(self) -> str:
        return f"decoy_engine/{self.path}::{self.function}"


def _callee(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    if isinstance(call.func, ast.Name):
        return call.func.id
    return None


def _is_literal(node: ast.expr) -> bool:
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, ast.Dict):
        return all(
            k is not None and _is_literal(k) and _is_literal(v)
            for k, v in zip(node.keys, node.values, strict=True)
        )
    return False


def _metadata_argument(call: ast.Call) -> ast.expr | None:
    name = _callee(call)
    if name in METADATA_SETTERS:
        return call.args[0] if call.args else None
    if name in METADATA_CALLS:
        for kw in call.keywords:
            if kw.arg == "metadata":
                return kw.value
        if name == "schema" and len(call.args) > 1:
            return call.args[1]
    return None


def _schema_argument(call: ast.Call) -> ast.expr | None:
    name = _callee(call)
    if name in SCHEMA_KEYWORD_CALLS:
        for kw in call.keywords:
            if kw.arg == "schema":
                return kw.value
        return None
    if name == "cast" and call.args:
        arg = call.args[0]
        named = arg.attr if isinstance(arg, ast.Attribute) else getattr(arg, "id", "")
        return arg if named.endswith("schema") else None
    return None


def _metadata_free_call(call: ast.Call) -> bool:
    """`pa.schema(fields)` with no metadata, or `x.remove_metadata()`."""
    name = _callee(call)
    if name == "remove_metadata":
        return True
    return name == "schema" and _metadata_argument(call) is None and len(call.args) <= 1


def _assignments(fn: ast.AST) -> dict[str, list[ast.expr]]:
    out: dict[str, list[ast.expr]] = {}
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    out.setdefault(target.id, []).append(node.value)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value:
            out.setdefault(node.target.id, []).append(node.value)
    return out


def _clean_schema(node: ast.expr, assigned: dict[str, list[ast.expr]], depth: int = 0) -> bool:
    """True when `node` is a sanitized or provably metadata-free schema in this function."""
    if depth > 6:
        return False
    if isinstance(node, ast.Call):
        return _callee(node) in SANITIZED or _metadata_free_call(node)
    if isinstance(node, ast.Name) and node.id in assigned:
        return all(_clean_schema(v, assigned, depth + 1) for v in assigned[node.id])
    return False


def findings_in(source: str, rel: str) -> list[Finding]:
    tree = ast.parse(source)
    owner = scan._enclosing(tree)
    in_safe_output = rel.startswith(SAFE_OUTPUT)
    bound = rel.startswith(OUTPUT_BOUND)
    scopes = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    assigned_by_scope = {owner.get(id(s), getattr(s, "name", "")): _assignments(s) for s in scopes}
    module_assigned = _assignments(tree)
    out: list[Finding] = []
    for call in ast.walk(tree):
        if not isinstance(call, ast.Call):
            continue
        where = owner.get(id(call), "")
        assigned = assigned_by_scope.get(where, module_assigned)
        if not in_safe_output:
            if _callee(call) == "sanitized_schema_metadata":
                out.append(Finding(rel, where or "<module>", "sanitizer-outside", call.lineno))
            meta = _metadata_argument(call)
            if meta is not None and not _is_literal(meta):
                out.append(Finding(rel, where or "<module>", "metadata-argument", call.lineno))
        schema = _schema_argument(call) if bound else None
        if schema is not None and not _clean_schema(schema, assigned):
            out.append(Finding(rel, where or "<module>", "whole-schema-reuse", call.lineno))
    return out


@lru_cache(maxsize=1)
def _all_findings() -> tuple[Finding, ...]:
    found: list[Finding] = []
    for path in scan.source_files(SRC):
        rel = path.relative_to(SRC).as_posix()
        found.extend(findings_in(path.read_text(encoding="utf-8"), rel))
    return tuple(found)


def _baseline() -> dict[str, dict[str, object]]:
    doc = json.loads(BASELINE.read_text(encoding="utf-8"))
    assert doc["sentry_id"] == "metadata-carrier-allow"
    return dict(doc["entries"])


def test_metadata_reaches_a_schema_only_through_attach_output_metadata() -> None:
    bad = [f for f in _all_findings() if f.rule != "whole-schema-reuse"]
    assert not bad, (
        "source metadata reaches a schema without attach_output_metadata:\n"
        + "\n".join(f"{f.path}:{f.line} {f.function} ({f.rule})" for f in bad)
    )


def test_whole_schema_reuse_is_baselined() -> None:
    found = Counter(f.key for f in _all_findings() if f.rule == "whole-schema-reuse")
    baseline = _baseline()
    new = sorted(k for k in found if k not in baseline)
    assert not new, "whole-schema reuse outside the baseline:\n" + "\n".join(new)
    stale = sorted(k for k in baseline if k not in found)
    assert not stale, "baseline rows no longer match a site (delete them):\n" + "\n".join(stale)
    moved = {k: (found[k], baseline[k]["max"]) for k in found if found[k] != baseline[k]["max"]}
    assert not moved, f"site count differs from the recorded max (found, max): {moved}"


def test_baseline_rows_are_reviewed() -> None:
    for key, entry in _baseline().items():
        path, _, function = key.partition("::")
        assert (SRC.parent / path).is_file() and function, key
        assert isinstance(entry["max"], int) and entry["max"] >= 1, key
        reason = str(entry["reason"])
        assert len(reason) >= 15 and not reason.lower().startswith(("todo", "review")), key


def test_the_e2_sites_call_attach_output_metadata() -> None:
    modules = {
        "execution/out_of_core/_rewrite_pass.py",
        "execution/out_of_core/_stream_driver_support.py",
        "execution/out_of_core/_mask.py",
        "execution/out_of_core/_emit.py",
        "execution/out_of_core/_batch_join.py",
        "execution/out_of_core/_stream_join_cursors.py",
        "execution/_transforms_table.py",
        "execution/_faker_degenerate_pin.py",
    }
    for rel in modules:
        assert "attach_output_metadata" in (SRC / rel).read_text(encoding="utf-8"), rel


# -- seeded bypasses: each one must fail -----------------------------------------------------------


def _rules(source: str, rel: str = SEEDED) -> list[str]:
    return [f.rule for f in findings_in(source, rel)]


def test_a_direct_metadata_read_is_seen() -> None:
    src = "def f(fields, batch):\n    return pa.schema(fields, metadata=batch.schema.metadata)\n"
    assert _rules(src) == ["metadata-argument"]


def test_a_local_variable_is_seen() -> None:
    src = (
        "def f(table, out):\n"
        "    meta = dict(table.schema.metadata)\n"
        "    return out.replace_schema_metadata(meta)\n"
    )
    assert _rules(src) == ["metadata-argument"]


def test_a_dict_merge_is_seen() -> None:
    src = "def f(table, extra):\n    return table.replace_schema_metadata({**extra})\n"
    assert _rules(src) == ["metadata-argument"]


def test_none_and_literals_pass() -> None:
    src = (
        "def f(table):\n"
        "    a = table.replace_schema_metadata(None)\n"
        "    return a.replace_schema_metadata({b'k': b'v'})\n"
    )
    assert _rules(src) == []


def test_the_sanitizer_is_private_to_safe_output() -> None:
    src = "def f(m, s):\n    return sanitized_schema_metadata(m, for_schema=s)\n"
    assert _rules(src) == ["sanitizer-outside"]
    assert _rules(src, "safe_output/_x.py") == []


def test_a_source_schema_in_from_arrays_is_seen() -> None:
    src = (
        "def f(cols, source_schema):\n    return pa.Table.from_arrays(cols, schema=source_schema)\n"
    )
    assert _rules(src) == ["whole-schema-reuse"]


def test_a_batch_schema_in_record_batch_is_seen() -> None:
    src = "def f(arrays, batch):\n    return pa.record_batch(arrays, schema=batch.schema)\n"
    assert _rules(src) == ["whole-schema-reuse"]


def test_a_cast_to_a_source_schema_is_seen() -> None:
    src = "def f(table, source_schema):\n    return table.cast(source_schema)\n"
    assert _rules(src) == ["whole-schema-reuse"]


def test_attached_and_metadata_free_schemas_pass() -> None:
    src = (
        "def f(arrays, fields, batch, src):\n"
        "    a = attach_output_metadata(pa.schema(fields), batch.schema.metadata)\n"
        "    b = pa.schema(fields)\n"
        "    c = src.schema.remove_metadata()\n"
        "    pa.record_batch(arrays, schema=a)\n"
        "    pa.record_batch(arrays, schema=b)\n"
        "    pa.record_batch(arrays, schema=c)\n"
        "    return pa.Table.from_arrays(arrays, schema=output_schema(src.schema))\n"
    )
    assert _rules(src) == []


def test_whole_schema_reuse_is_scoped_to_output_bound_modules() -> None:
    src = "def f(arrays, batch):\n    return pa.record_batch(arrays, schema=batch.schema)\n"
    assert _rules(src, "profile/_x.py") == []
