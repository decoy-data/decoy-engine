"""One output-metadata choke point (OUTPUT-METADATA-LEAK E1): a published Parquet file is written
only by an output writer of the Arrow adapter, and each output writer applies `safe_output`.

The scan walks `src/decoy_engine` and finds every call that can write a Parquet file: the pyarrow
writers, the two adapter writers, the Polars and pandas writers by attribute name, and an
`execute()` or `sql()` call whose SQL text is a `COPY ... TO` into Parquet. The SQL text joins
string literals and f-string parts and resolves a name bound to a module-level string constant,
also through `from m import NAME as alias`. A hit passes only when it sits in an output writer
(`write_output_table`, `output_parquet_writer`), in a raw primitive of the adapters, or in a row
of `baselines/parquet-intermediate-writers.json`: an intermediate file Decoy never publishes, or
the subset output, which Polars writes without source metadata. The baseline is shrink-only
(`scripts/dev/ratchet_check.py`), keyed by module and function, with the count of hits it excuses.

Named limits: attribute-name matching (`write_parquet`, `sink_parquet`, `to_parquet`) does not
know the receiver; a SQL text built by a call or read from a variable that is not a module
constant is not seen; `getattr` and `exec` evasion is not modelled.
"""

from __future__ import annotations

import ast
import json
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import pytest

from tests.sentry.defects import _defect_scan as scan

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
BASELINE = ROOT / "tests" / "sentry" / "baselines" / "parquet-intermediate-writers.json"
ARROW = "decoy_engine/fileaccess/adapters/arrow.py"
POLARS = "decoy_engine/fileaccess/adapters/polars.py"

QUALIFIED = frozenset(
    {
        "pyarrow.parquet.write_table",
        "pyarrow.parquet.ParquetWriter",
        "pyarrow.parquet.write_to_dataset",
        "pyarrow.parquet.write_metadata",
        "pyarrow.dataset.write_dataset",
        "decoy_engine.fileaccess.adapters.arrow.write_table",
        "decoy_engine.fileaccess.adapters.arrow.parquet_writer",
        "decoy_engine.fileaccess.adapters.polars.write_parquet",
    }
)
ATTRIBUTE_WRITERS = frozenset({"to_parquet", "write_parquet", "sink_parquet"})
SQL_CALLS = frozenset({"execute", "sql"})
COPY_TO_PARQUET = re.compile(
    r"\bCOPY\b[\s\S]*?\bTO\b[\s\S]*?(\bFORMAT\s+PARQUET\b|\.parquet\b)", re.IGNORECASE
)

# The output writers (allowed callers of the raw primitives) and the primitives themselves.
OUTPUT_WRITERS = {
    (ARROW, "write_output_table"): "output_table",
    (ARROW, "output_parquet_writer"): "output_schema",
}
PRIMITIVES = frozenset(
    {(ARROW, "write_table"), (ARROW, "parquet_writer"), (POLARS, "write_parquet")}
)
CATEGORIES = frozenset({"intermediate", "published-polars"})


@dataclass(frozen=True)
class Hit:
    path: str
    function: str
    watch: str
    line: int

    @property
    def key(self) -> str:
        return f"{self.path}::{self.function}"


def _imports(tree: ast.Module, mod: str, is_pkg: bool) -> dict[str, str]:
    """Every name an import binds, at any depth, plus plain re-bindings of a dotted name."""
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                out[a.asname or a.name.split(".")[0]] = a.name if a.asname else a.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom):
            base = scan.resolve_from(mod, is_pkg, node)
            for a in node.names:
                out[a.asname or a.name] = f"{base}.{a.name}" if base else a.name
    for _ in range(3):  # a re-binding of a re-binding; bounded so a self-referencing name ends
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target, chain = node.targets[0], scan.attr_chain(node.value)
                if isinstance(target, ast.Name) and chain and chain[0] in out:
                    if target.id != chain[0]:
                        out[target.id] = ".".join([out[chain[0]], *chain[1:]])
    return out


def _dotted(node: ast.AST, imports: dict[str, str]) -> str | None:
    chain = scan.attr_chain(node)
    if not chain:
        return None
    return ".".join([imports.get(chain[0], chain[0]), *chain[1:]])


def _text(node: ast.AST, mod: str, imports: dict[str, str], consts: dict[str, str]) -> str:
    """The constant text of a SQL argument; what cannot be resolved reads as empty."""
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else ""
    if isinstance(node, ast.JoinedStr):
        return "".join(_text(v, mod, imports, consts) for v in node.values)
    if isinstance(node, ast.FormattedValue):
        return _text(node.value, mod, imports, consts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _text(node.left, mod, imports, consts) + _text(node.right, mod, imports, consts)
    if isinstance(node, ast.Name):
        return consts.get(f"{mod}.{node.id}") or consts.get(imports.get(node.id, ""), "")
    return ""


def _own_constants(tree: ast.Module, mod: str) -> dict[str, str]:
    """Module-level `NAME = "text"` bindings of this module, keyed like the project table."""
    return {
        f"{mod}.{node.targets[0].id}": node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    }


def hits_in(source: str, rel: str, consts: dict[str, str]) -> list[Hit]:
    """Every Parquet-writing call in one module, with its enclosing qualified function."""
    tree = ast.parse(source)
    mod = rel.removesuffix(".py").replace("/", ".").removesuffix(".__init__")
    imports = _imports(tree, mod, rel.endswith("__init__.py"))
    consts = {**consts, **_own_constants(tree, mod)}
    owner = scan._enclosing(tree)
    found: list[Hit] = []
    for call in (n for n in ast.walk(tree) if isinstance(n, ast.Call)):
        target = _dotted(call.func, imports)
        watch = None
        if target in QUALIFIED:
            watch = target
        elif isinstance(call.func, ast.Attribute):
            if call.func.attr in ATTRIBUTE_WRITERS:
                watch = f"attr:{call.func.attr}"
            elif call.func.attr in SQL_CALLS and call.args:
                if COPY_TO_PARQUET.search(_text(call.args[0], mod, imports, consts)):
                    watch = "sql:copy-to-parquet"
        if watch:
            found.append(Hit(rel, owner.get(id(call), "") or "<module>", watch, call.lineno))
    return found


@lru_cache(maxsize=1)
def _index() -> scan.ModuleIndex:
    return scan.ModuleIndex(SRC / "decoy_engine")


def _consts() -> dict[str, str]:
    return {f"{m}.{n}": v for (m, n), v in _index().consts.items()}


@lru_cache(maxsize=1)
def _all_hits() -> tuple[Hit, ...]:
    index = _index()
    consts = _consts()
    out: list[Hit] = []
    for path in index.trees:
        rel = path.relative_to(SRC).as_posix()
        out.extend(hits_in(path.read_text(encoding="utf-8"), rel, consts))
    return tuple(out)


def _is_allowed(hit: Hit) -> bool:
    return (hit.path, hit.function) in OUTPUT_WRITERS or (hit.path, hit.function) in PRIMITIVES


def _baseline() -> dict[str, dict[str, object]]:
    doc = json.loads(BASELINE.read_text(encoding="utf-8"))
    assert doc["sentry_id"] == "parquet-intermediate-writers"
    return dict(doc["entries"])


def test_every_parquet_write_is_an_output_writer_or_baselined() -> None:
    found = Counter(h.key for h in _all_hits() if not _is_allowed(h))
    baseline = _baseline()
    new = sorted(k for k in found if k not in baseline)
    assert not new, "Parquet write outside an output writer and the baseline:\n" + "\n".join(new)
    stale = sorted(k for k in baseline if k not in found)
    assert not stale, "baseline rows no longer match a write (delete them):\n" + "\n".join(stale)
    moved = {k: (found[k], baseline[k]["max"]) for k in found if found[k] != baseline[k]["max"]}
    assert not moved, f"hit count differs from the recorded max (found, max): {moved}"


def test_baseline_rows_are_reviewed() -> None:
    for key, entry in _baseline().items():
        path, _, function = key.partition("::")
        assert (SRC / path).is_file() and function, key
        assert entry["category"] in CATEGORIES, key
        assert isinstance(entry["max"], int) and entry["max"] >= 1, key
        reason = str(entry["reason"])
        assert len(reason) >= 15 and not reason.lower().startswith(("todo", "review")), key


def test_the_published_polars_row_is_the_subset_output() -> None:
    rows = {k for k, e in _baseline().items() if e["category"] == "published-polars"}
    assert {k.partition("::")[0] for k in rows} == {"decoy_engine/subset/_materialize.py"}


def test_the_scan_sees_the_seven_copy_statements_in_three_functions() -> None:
    copies = [h for h in _all_hits() if h.watch == "sql:copy-to-parquet"]
    assert len(copies) == 7
    assert {h.key for h in copies} == {
        "decoy_engine/execution/out_of_core/_relation.py::_build_relation",
        "decoy_engine/execution/out_of_core/_multi_parent.py::merge_parent_relations",
        "decoy_engine/connectors/postgres_snapshot.py::_export_relation",
    }


# -- the output writers must apply the rule -------------------------------------------------------


def _calls_name(fn: ast.AST, name: str) -> bool:
    return any(
        isinstance(n, ast.Call)
        and (
            (isinstance(n.func, ast.Name) and n.func.id == name)
            or (isinstance(n.func, ast.Attribute) and n.func.attr == name)
        )
        for n in ast.walk(fn)
    )


def writer_findings(source: str, rel: str = ARROW) -> list[str]:
    """Each output writer in `source` that does not call its `safe_output` function."""
    tree = ast.parse(source)
    funcs = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    out = []
    for (path, name), needed in OUTPUT_WRITERS.items():
        if path != rel:
            continue
        if name not in funcs:
            out.append(f"{name}: missing")
        elif not _calls_name(funcs[name], needed):
            out.append(f"{name}: does not call {needed}")
    return out


def test_the_output_writers_call_the_sanitizer() -> None:
    assert writer_findings((SRC / ARROW).read_text(encoding="utf-8")) == []


def test_a_writer_that_skips_the_sanitizer_is_seen() -> None:
    skipping = (
        "def write_output_table(table, txn, component):\n"
        "    write_table(table, txn, component)\n"
        "def output_parquet_writer(txn, component, schema):\n"
        "    return parquet_writer(txn, component, output_schema(schema))\n"
    )
    assert writer_findings(skipping) == ["write_output_table: does not call output_table"]


# -- seeded bypasses: one cell per covered spelling ------------------------------------------------

PQ = "import pyarrow.parquet as pq\n"
SEEDED: dict[str, tuple[str, str]] = {
    "direct_attribute": (
        PQ + "def f(t, p):\n    pq.write_table(t, p)\n",
        "pyarrow.parquet.write_table",
    ),
    "from_import_alias": (
        "from pyarrow.parquet import write_table as w\ndef f(t, p):\n    w(t, p)\n",
        "pyarrow.parquet.write_table",
    ),
    "module_alias": (
        "import pyarrow.parquet as parquet_mod\ndef f(t, p):\n    parquet_mod.write_table(t, p)\n",
        "pyarrow.parquet.write_table",
    ),
    "plain_pyarrow_chain": (
        "import pyarrow as pa\ndef f(t, p):\n    pa.parquet.write_table(t, p)\n",
        "pyarrow.parquet.write_table",
    ),
    "rebinding": (
        PQ + "w = pq.write_table\ndef f(t, p):\n    w(t, p)\n",
        "pyarrow.parquet.write_table",
    ),
    "function_local_import": (
        "def f(t, p):\n    from pyarrow.parquet import write_table\n    write_table(t, p)\n",
        "pyarrow.parquet.write_table",
    ),
    "parquet_writer_class": (
        PQ + "def f(s, p):\n    return pq.ParquetWriter(p, s)\n",
        "pyarrow.parquet.ParquetWriter",
    ),
    "adapter_call": (
        "from decoy_engine.fileaccess.adapters import arrow as arrow_adapter\n"
        "def f(t, txn):\n    arrow_adapter.write_table(t, txn, 'x')\n",
        "decoy_engine.fileaccess.adapters.arrow.write_table",
    ),
    "adapter_writer_import": (
        "from decoy_engine.fileaccess.adapters.arrow import parquet_writer\n"
        "def f(txn, s):\n    return parquet_writer(txn, 'x', s)\n",
        "decoy_engine.fileaccess.adapters.arrow.parquet_writer",
    ),
    "polars_adapter": (
        "from decoy_engine.fileaccess.adapters import polars as polars_adapter\n"
        "def f(frame, txn):\n    polars_adapter.write_parquet(frame, txn, 'x')\n",
        "decoy_engine.fileaccess.adapters.polars.write_parquet",
    ),
    "write_dataset": (
        "import pyarrow.dataset as ds\ndef f(t, p):\n    ds.write_dataset(t, p)\n",
        "pyarrow.dataset.write_dataset",
    ),
    "write_to_dataset": (
        PQ + "def f(t, p):\n    pq.write_to_dataset(t, p)\n",
        "pyarrow.parquet.write_to_dataset",
    ),
    "write_metadata": (
        PQ + "def f(s, p):\n    pq.write_metadata(s, p)\n",
        "pyarrow.parquet.write_metadata",
    ),
    "sink_parquet": ("def f(lf, p):\n    lf.sink_parquet(p)\n", "attr:sink_parquet"),
    "polars_write_parquet": ("def f(df, p):\n    df.write_parquet(p)\n", "attr:write_parquet"),
    "duckdb_relation_write_parquet": (
        "def f(rel, p):\n    rel.write_parquet(p)\n",
        "attr:write_parquet",
    ),
    "pandas_to_parquet": ("def f(df, p):\n    df.to_parquet(p)\n", "attr:to_parquet"),
    "copy_plain_literal": (
        "def f(conn):\n    conn.execute(\"COPY t TO 'x' (FORMAT PARQUET)\")\n",
        "sql:copy-to-parquet",
    ),
    "copy_sql_call": (
        "def f(conn):\n    conn.sql(\"copy (select 1) to 'x' (format parquet)\")\n",
        "sql:copy-to-parquet",
    ),
    "copy_extension_only": (
        "def f(conn):\n    conn.execute(\"COPY t TO 'x.parquet'\")\n",
        "sql:copy-to-parquet",
    ),
    "copy_format_in_imported_constant": (
        "from decoy_engine.execution.out_of_core._duckdb import PRIVATE_COPY as _PC\n"
        'def f(conn, dest):\n    conn.execute(f"COPY t TO {dest} ({_PC})")\n',
        "sql:copy-to-parquet",
    ),
    "copy_format_in_local_constant": (
        "FMT = 'FORMAT PARQUET'\ndef f(conn, dest):\n    conn.execute(f\"COPY t TO {dest} ({FMT})\")\n",
        "sql:copy-to-parquet",
    ),
    "copy_split_across_fstring_parts": (
        "def f(conn, sel, dest):\n"
        '    conn.execute(f"COPY (SELECT {sel}) " f"TO {dest} (FORMAT parquet, ROW_GROUP_SIZE 5)")\n',
        "sql:copy-to-parquet",
    ),
    "reference_passed_to_guard": (
        PQ + "def f(t, fh):\n    guarded(1, 2, pq.write_table, t, fh)\n",
        "pyarrow.parquet.write_table",
    ),
    "partial_of_writer": (
        "import functools\n" + PQ + "def f(t, p):\n    functools.partial(pq.write_table, t)(p)\n",
        "pyarrow.parquet.write_table",
    ),
    "attribute_reference_passed": (
        "def f(df, fh):\n    guarded(1, 2, df.write_parquet, fh)\n",
        "attr:write_parquet",
    ),
    "copy_quoted_format": (
        "def f(conn):\n    conn.execute(\"COPY t TO 'x' (FORMAT 'PARQUET')\")\n",
        "sql:copy-to-parquet",
    ),
    "copy_str_format_call": (
        'def f(conn, dest):\n    conn.execute("COPY t TO {} (FORMAT PARQUET)".format(dest))\n',
        "sql:copy-to-parquet",
    ),
    "copy_local_variable": (
        "def f(conn, dest):\n"
        '    sql = f"COPY t TO {dest} (FORMAT PARQUET)"\n'
        "    conn.execute(sql)\n",
        "sql:copy-to-parquet",
    ),
    "copy_concatenated": (
        "def f(conn, dest):\n    conn.execute('COPY t TO ' + dest + ' (FORMAT PARQUET)')\n",
        "sql:copy-to-parquet",
    ),
}


@pytest.mark.parametrize("cell", SEEDED)
def test_a_seeded_bypass_is_seen(cell: str) -> None:
    source, watch = SEEDED[cell]
    found = hits_in(source, "decoy_engine/seeded.py", _consts())
    assert [h.watch for h in found] == [watch], found
    assert not _is_allowed(found[0])


@pytest.mark.parametrize(
    "source",
    [
        PQ + "def f(p):\n    return pq.read_table(p)\n",
        "def f(conn):\n    conn.execute(\"COPY t TO 'x.csv' (FORMAT CSV)\")\n",
        "def f(conn):\n    conn.execute('SELECT 1')\n",
        "def f(df, p):\n    df.to_csv(p)\n",
    ],
)
def test_a_read_or_non_parquet_write_is_not_a_hit(source: str) -> None:
    assert hits_in(source, "decoy_engine/seeded.py", _consts()) == []
