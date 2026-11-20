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

Field metadata: the `metadata=` keyword (or fourth positional) of `pa.field` and the argument of
`Field.with_metadata` follow the same rule, because a field built from a source field's metadata
carries source text to a column the job rewrote. A carried field is kept with `Field.with_type`.

Named limits: a schema reached through a call this scan does not know, a `getattr` and a
`**kwargs` spelling are not modelled.
"""

from __future__ import annotations

import ast
import json
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import pytest

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
SEEDED = "execution/out_of_core/_x.py"

# Constructors that take schema metadata: callee -> (keyword, positional index) of `metadata`.
METADATA_SLOT: dict[str, int] = {
    "schema": 1,
    "field": 3,
    "record_batch": 3,
    "table": 3,
    "from_arrays": 3,
    "from_pydict": 2,
    "from_pylist": 2,
}
METADATA_SETTERS = frozenset({"replace_schema_metadata", "with_metadata"})
# Constructors that take a schema: callee -> positional index of `schema`.
SCHEMA_SLOT: dict[str, int] = {
    "record_batch": 2,
    "table": 2,
    "from_arrays": 2,
    "from_batches": 1,
    "from_pydict": 1,
    "from_pylist": 1,
    "from_pandas": 1,
}
# A cast argument that is a type, not a schema: `x.type`, `pa.int64()` and the like.
TYPE_ATTRS = ("type", "dtype")


@dataclass(frozen=True)
class Finding:
    path: str
    function: str
    rule: str
    line: int

    @property
    def key(self) -> str:
        return f"decoy_engine/{self.path}::{self.function}"


def _imports(tree: ast.Module) -> dict[str, str]:
    """Name -> dotted origin for imports and plain rebindings (`Table = pa.Table`, `mk = pa.schema`),
    at any depth. A name bound twice keeps its first binding."""
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                out.setdefault(
                    a.asname or a.name.split(".")[0], a.name if a.asname else a.name.split(".")[0]
                )
        elif isinstance(node, ast.ImportFrom) and node.module:
            for a in node.names:
                out.setdefault(a.asname or a.name, f"{node.module}.{a.name}")
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target, chain = node.targets[0], scan.attr_chain(node.value)
                if (
                    isinstance(target, ast.Name)
                    and chain
                    and chain[0] in out
                    and target.id not in out
                ):
                    out[target.id] = ".".join([out[chain[0]], *chain[1:]])
                    changed = True
    return out


def _callee(call: ast.Call, imports: dict[str, str]) -> tuple[str | None, bool]:
    """The called name resolved through imports and rebindings, and whether it resolves into
    pyarrow. `from pyarrow import schema as s; s(...)` is `schema`; `x.cast(...)` is `cast`."""
    chain = scan.attr_chain(call.func)
    if not chain:
        # A method on a call result (`pa.field(...).with_metadata(m)`): the name is the attribute.
        if isinstance(call.func, ast.Attribute):
            return call.func.attr, False
        return None, False
    dotted = ".".join([imports.get(chain[0], chain[0]), *chain[1:]])
    return dotted.rsplit(".", 1)[-1], dotted.split(".")[0] == "pyarrow"


def _is_literal(node: ast.expr) -> bool:
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, ast.Dict):
        return all(
            k is not None and _is_literal(k) and _is_literal(v)
            for k, v in zip(node.keys, node.values, strict=True)
        )
    return False


def _arg(call: ast.Call, keyword: str, position: int) -> ast.expr | None:
    for kw in call.keywords:
        if kw.arg == keyword:
            return kw.value
    return call.args[position] if len(call.args) > position else None


def _metadata_argument(call: ast.Call, name: str | None) -> ast.expr | None:
    if name in METADATA_SETTERS:
        return call.args[0] if call.args else None
    if name in METADATA_SLOT:
        return _arg(call, "metadata", METADATA_SLOT[name])
    return None


def _schema_argument(call: ast.Call, name: str | None) -> ast.expr | None:
    if name == "from_batches" and "RecordBatchReader" in (scan.attr_chain(call.func) or []):
        return _arg(call, "schema", 0)
    if name in SCHEMA_SLOT:
        return _arg(call, "schema", SCHEMA_SLOT[name])
    if name == "cast" and call.args:
        return call.args[0]
    return None


def _named_like_schema(node: ast.expr) -> bool:
    text = node.attr if isinstance(node, ast.Attribute) else getattr(node, "id", "")
    return text.lower().endswith(("schema", "schemas"))


def _is_a_type(node: ast.expr, imports: dict[str, str]) -> bool:
    """A cast argument that cannot be a schema: a `.type` read or a pyarrow type constructor."""
    if isinstance(node, ast.Attribute) and node.attr.endswith(TYPE_ATTRS):
        return True
    if isinstance(node, ast.Name) and node.id.endswith(TYPE_ATTRS):
        return True
    if isinstance(node, ast.Call):
        name, in_pyarrow = _callee(node, imports)
        return in_pyarrow and name not in ("schema", "Schema")
    return False


def _fields_list(node: ast.expr, assigned: dict[str, list[ast.expr]], params: set[str]) -> bool:
    """True when `node` is a list of fields built here, so `pa.schema(node)` carries no metadata.
    A `.schema` read, a name ending in `schema` and a function parameter may be schema-valued."""
    if isinstance(node, (ast.List, ast.ListComp, ast.Tuple, ast.GeneratorExp)):
        return True
    if isinstance(node, ast.Name) and not _named_like_schema(node) and node.id not in params:
        values = assigned.get(node.id) or []
        return bool(values) and all(_fields_list(v, assigned, params) for v in values)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "list":
        return (
            bool(node.args)
            and not _named_like_schema(node.args[0])
            and not (isinstance(node.args[0], ast.Attribute) and node.args[0].attr == "schema")
        )
    return False


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


def _parameters(fn: ast.AST) -> set[str]:
    if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return set()
    a = fn.args
    names = [*a.posonlyargs, *a.args, *a.kwonlyargs]
    return {p.arg for p in [*names, *filter(None, [a.vararg, a.kwarg])]}


def _clean_schema(
    node: ast.expr,
    assigned: dict[str, list[ast.expr]],
    params: set[str],
    imports: dict[str, str],
    depth: int = 0,
) -> bool:
    """True when `node` is a sanitized or provably metadata-free schema in this function."""
    if depth > 6:
        return False
    if isinstance(node, ast.Constant) and node.value is None:
        return True
    if isinstance(node, ast.Call):
        name, _ = _callee(node, imports)
        if name in SANITIZED or name == "remove_metadata":
            return True
        if name == "schema":
            arg = node.args[0] if node.args else _arg(node, "fields", 0)
            return (
                _metadata_argument(node, name) is None
                and len(node.args) <= 1
                and arg is not None
                and _fields_list(arg, assigned, params)
            )
        return False
    if isinstance(node, ast.Name) and node.id in assigned and node.id not in params:
        return all(
            _clean_schema(v, assigned, params, imports, depth + 1) for v in assigned[node.id]
        )
    return False


def findings_in(source: str, rel: str) -> list[Finding]:
    tree = ast.parse(source)
    owner = scan._enclosing(tree)
    imports = _imports(tree)
    in_safe_output = rel.startswith(SAFE_OUTPUT)
    bound = rel.startswith(OUTPUT_BOUND)
    scopes = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    scope_info = {
        owner.get(id(s), getattr(s, "name", "")): (_assignments(s), _parameters(s)) for s in scopes
    }
    module_info = (_assignments(tree), set[str]())
    out: list[Finding] = []
    for call in ast.walk(tree):
        if not isinstance(call, ast.Call):
            continue
        where = owner.get(id(call), "")
        assigned, params = scope_info.get(where, module_info)
        name, _ = _callee(call, imports)
        label = where or "<module>"
        if not in_safe_output:
            if name == "sanitized_schema_metadata":
                out.append(Finding(rel, label, "sanitizer-outside", call.lineno))
            meta = _metadata_argument(call, name)
            if meta is not None and not _is_literal(meta):
                out.append(Finding(rel, label, "metadata-argument", call.lineno))
        schema = _schema_argument(call, name) if bound else None
        if schema is None:
            continue
        if name == "cast" and _is_a_type(schema, imports):
            continue
        if not _clean_schema(schema, assigned, params, imports):
            out.append(Finding(rel, label, "whole-schema-reuse", call.lineno))
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


@pytest.mark.parametrize(
    "call",
    [
        "pa.field(f.name, c.type, f.nullable, f.metadata)",
        "pa.field(f.name, c.type, metadata=f.metadata)",
        "pa.field(f.name, c.type, metadata=dict(f.metadata))",
        "pa.field(f.name, c.type).with_metadata(f.metadata)",
    ],
    ids=["positional", "keyword", "merged", "with-metadata"],
)
def test_a_field_built_from_source_field_metadata_is_seen(call: str) -> None:
    assert _rules(f"def f(f, c):\n    return {call}\n") == ["metadata-argument"]


def test_a_literal_or_absent_field_metadata_passes() -> None:
    src = (
        "def f(f, c):\n"
        "    a = pa.field(f.name, c.type, f.nullable)\n"
        "    b = pa.field(f.name, c.type, metadata={b'k': b'v'})\n"
        "    return f.with_type(c.type), a, b\n"
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
        "def f(arrays, batch, src):\n"
        "    fields = [pa.field('a', pa.int64())]\n"
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


# -- seeded cells for the spellings the first scan missed ------------------------------------------


@pytest.mark.parametrize(
    "source",
    [
        "def f(a, batch):\n    return pa.record_batch(a, schema=pa.schema(batch.schema))\n",
        "def f(a, source_schema):\n    return pa.record_batch(a, schema=pa.schema(source_schema))\n",
        "def f(a, fields):\n    return pa.record_batch(a, schema=pa.schema(fields))\n",
        "def f(a, b):\n    s = pa.schema(b.schema)\n    return pa.record_batch(a, schema=s)\n",
    ],
    ids=["schema-attr", "schema-name", "parameter", "assigned-schema-attr"],
)
def test_pa_schema_of_a_schema_value_is_not_clean(source: str) -> None:
    assert _rules(source) == ["whole-schema-reuse"]


@pytest.mark.parametrize(
    "call",
    [
        "pa.Table.from_pandas(df, schema=src.schema)",
        "pa.RecordBatch.from_pandas(df, schema=src.schema)",
        "pa.Table.from_pylist(rows, schema=src.schema)",
        "pa.RecordBatch.from_pylist(rows, schema=src.schema)",
        "pa.Table.from_pydict(data, schema=src.schema)",
        "pa.RecordBatch.from_pydict(data, schema=src.schema)",
        "pa.table(data, schema=src.schema)",
        "pa.Table.from_pandas(df, src.schema)",
        "pa.Table.from_arrays(cols, None, src.schema)",
    ],
)
def test_every_constructor_that_takes_a_schema_is_checked(call: str) -> None:
    assert _rules(f"def f(src, df, rows, data, cols):\n    return {call}\n") == [
        "whole-schema-reuse"
    ]


@pytest.mark.parametrize(
    "call",
    [
        "pa.table(data, metadata=m)",
        "pa.Table.from_pydict(data, metadata=m)",
        "pa.Table.from_pylist(rows, metadata=m)",
        "pa.RecordBatch.from_pydict(data, metadata=m)",
        "pa.Table.from_arrays(cols, None, None, m)",
        "pa.record_batch(cols, None, None, m)",
        "pa.schema(fields, m)",
    ],
)
def test_every_metadata_slot_is_checked(call: str) -> None:
    src = f"def f(m, data, rows, cols, fields):\n    return {call}\n"
    assert _rules(src) == ["metadata-argument"]


@pytest.mark.parametrize(
    "arg", ["source_schema", "batch.schema", "target", "self._schema", "make_schema(x)"]
)
def test_every_cast_argument_is_checked(arg: str) -> None:
    src = f"def f(table, source_schema, batch, target, x):\n    return table.cast({arg})\n"
    assert _rules(src) == ["whole-schema-reuse"]


@pytest.mark.parametrize("arg", ["field.type", "pa.int64()", "col_dtype", "pa.timestamp('us')"])
def test_a_cast_to_a_type_passes(arg: str) -> None:
    src = f"import pyarrow as pa\ndef f(col, field, col_dtype):\n    return col.cast({arg})\n"
    assert _rules(src) == []


@pytest.mark.parametrize(
    ("source", "rule"),
    [
        (
            "from pyarrow import schema as s\ndef f(m, x):\n    return s(x, metadata=m)\n",
            "metadata-argument",
        ),
        (
            "import pyarrow as pyarrow2\ndef f(m, x):\n    return pyarrow2.schema(x, metadata=m)\n",
            "metadata-argument",
        ),
        (
            "import pyarrow as pa\nmk = pa.schema\ndef f(m, x):\n    return mk(x, metadata=m)\n",
            "metadata-argument",
        ),
        (
            "from pyarrow import record_batch as rb\ndef f(a, b):\n    return rb(a, schema=b.schema)\n",
            "whole-schema-reuse",
        ),
        (
            "import pyarrow as pa\nTable = pa.Table\ndef f(c, src):\n    return Table.from_arrays(c, schema=src.schema)\n",
            "whole-schema-reuse",
        ),
        (
            "from pyarrow import Table as T\ndef f(df, src):\n    return T.from_pandas(df, schema=src.schema)\n",
            "whole-schema-reuse",
        ),
        (
            "from pyarrow import schema as s\ndef f(b):\n    x = s(b.schema)\n    return pa.record_batch([], schema=x)\n",
            "whole-schema-reuse",
        ),
        (
            "from pyarrow import RecordBatchReader as R\ndef f(src, b):\n    return R.from_batches(src.schema, b)\n",
            "whole-schema-reuse",
        ),
    ],
    ids=[
        "from-import-alias",
        "module-alias",
        "rebinding",
        "record-batch-alias",
        "class-rebinding",
        "class-alias",
        "alias-then-use",
        "reader-alias",
    ],
)
def test_aliased_spellings_are_seen(source: str, rule: str) -> None:
    assert _rules(source) == [rule]


# -- one fixture per way a schema gets metadata (every form must be flagged) -----------------------

FORM_FIXTURES = {
    "pa.schema(x, metadata=)": (
        "import pyarrow as pa\ndef f(m, x):\n    return pa.schema(x, metadata=m)\n",
        "metadata-argument",
    ),
    "pa.field(metadata=)": (
        "import pyarrow as pa\ndef f(src, c):\n    return pa.field(src.name, c.type, metadata=src.metadata)\n",
        "metadata-argument",
    ),
    "pa.field(name, type, nullable, m)": (
        "import pyarrow as pa\ndef f(src, c):\n    return pa.field(src.name, c.type, src.nullable, src.metadata)\n",
        "metadata-argument",
    ),
    "from pyarrow import field": (
        "from pyarrow import field\ndef f(src, c):\n    return field(src.name, c.type, metadata=src.metadata)\n",
        "metadata-argument",
    ),
    "Field.with_metadata": (
        "import pyarrow as pa\ndef f(src, c):\n    return pa.field('a', c.type).with_metadata(src.metadata)\n",
        "metadata-argument",
    ),
    "pa.schema(x, m)": (
        "import pyarrow as pa\ndef f(m, x):\n    return pa.schema(x, m)\n",
        "metadata-argument",
    ),
    "Table.from_pandas(schema=)": (
        "import pyarrow as pa\ndef f(df, src):\n    return pa.Table.from_pandas(df, schema=src.schema)\n",
        "whole-schema-reuse",
    ),
    "Table.from_pylist(schema=)": (
        "import pyarrow as pa\ndef f(r, src):\n    return pa.Table.from_pylist(r, schema=src.schema)\n",
        "whole-schema-reuse",
    ),
    "Table.from_pylist(metadata=)": (
        "import pyarrow as pa\ndef f(r, m):\n    return pa.Table.from_pylist(r, metadata=m)\n",
        "metadata-argument",
    ),
    "Table.from_pydict(schema=)": (
        "import pyarrow as pa\ndef f(d, src):\n    return pa.Table.from_pydict(d, schema=src.schema)\n",
        "whole-schema-reuse",
    ),
    "Table.from_pydict(metadata=)": (
        "import pyarrow as pa\ndef f(d, m):\n    return pa.Table.from_pydict(d, metadata=m)\n",
        "metadata-argument",
    ),
    "pa.table(metadata=)": (
        "import pyarrow as pa\ndef f(d, m):\n    return pa.table(d, metadata=m)\n",
        "metadata-argument",
    ),
    "from_arrays positional metadata": (
        "import pyarrow as pa\ndef f(c, m):\n    return pa.Table.from_arrays(c, None, None, m)\n",
        "metadata-argument",
    ),
    "cast(schema)": (
        "import pyarrow as pa\ndef f(t, src):\n    return t.cast(src.schema)\n",
        "whole-schema-reuse",
    ),
    "cast(schema with metadata)": (
        "import pyarrow as pa\ndef f(t, fields, m):\n    return t.cast(pa.schema(fields, metadata=m))\n",
        "metadata-argument",
    ),
    "import pyarrow as p": (
        "import pyarrow as p\ndef f(m, x):\n    return p.schema(x, metadata=m)\n",
        "metadata-argument",
    ),
    "from pyarrow import table": (
        "from pyarrow import table\ndef f(d, m):\n    return table(d, metadata=m)\n",
        "metadata-argument",
    ),
    "from pyarrow import table, schema reuse": (
        "from pyarrow import table\ndef f(d, src):\n    return table(d, schema=src.schema)\n",
        "whole-schema-reuse",
    ),
}


@pytest.mark.parametrize(("source", "rule"), FORM_FIXTURES.values(), ids=list(FORM_FIXTURES))
def test_every_metadata_form_is_flagged(source: str, rule: str) -> None:
    assert rule in _rules(source)
