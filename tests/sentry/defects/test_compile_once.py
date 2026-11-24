"""One compiled decision per entry, enforced two ways (plan revision 2.6, I1 and V1-4).

Static: every Python file under `execution/` is scanned for the calls that resolve a node
(`compile_work_order`, `build_work_list`, `parents_of`, `resolve_operation(s)`, `column_access`,
`declared_access`, the anchor-column walkers and `SURFACE_DECLARATIONS` reads). Each site must be
named in `ALLOWED` with its reason, by enclosing function and callee. A new site fails here until
it is named; dispatch, FK conversion and exact-integer registration are not allowed to have one.

Runtime (F4): once an entry's `compile_work_order` has returned, the resolution functions raise
unless an allowed independent site (guards, planning, carry) is on the stack.
"""

from __future__ import annotations

import ast
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pytest

from tests.unit.execution.when import _write_support as ws

SRC = Path(__file__).resolve().parents[3] / "src" / "decoy_engine" / "execution"
TRACKED = frozenset(
    {
        "compile_work_order",
        "compile_plan_order",
        "build_work_list",
        "parents_of",
        "resolve_operation",
        "resolve_operations",
        "column_access",
        "declared_access",
        "joint_mask_key_by_columns",
        "date_shift_group_columns",
        "source_anchor_columns",
        "SURFACE_DECLARATIONS",
    }
)

Site = tuple[str, str, str]  # (path under execution/, enclosing function, callee)

_COMPILE = "the compile entry builds the list, and the compiler resolves each node and its FK edges"
_ENTRY = "an entry point obtains the one compiled order for execution or classification"
_STANDALONE = "a direct call with no run compiles its own one-node order"
_CHUNK_ORDER = "a chunked helper reads only the ordered nodes of its own entry's plan"
_DECL_API = "the declaration API implements nested and gated access, creator and ordering queries"

ALLOWED: dict[Site, str] = {
    ("work_order/compile.py", "compile_work_order", "resolve_operations"): _COMPILE,
    ("work_order/compile.py", "compile_plan_order", "build_work_list"): _COMPILE,
    ("work_order/compile.py", "compile_plan_order", "compile_work_order"): _COMPILE,
    ("work_order/operations.py", "resolve_operations", "resolve_operation"): _COMPILE,
    ("work_order/operations.py", "resolve_operation", "parents_of"): _COMPILE,
    ("work_order/operations.py", "resolve_operation", "declared_access"): _COMPILE,
    (
        "work_order/operations.py",
        "entries_written",
        "column_access",
    ): "the carry side holds config entries and no work list",
    ("_pandas_adapter.py", "run", "build_work_list"): _ENTRY,
    ("_pandas_adapter.py", "run", "compile_work_order"): _ENTRY,
    ("_pandas_adapter.py", "_dispatch_mask_node", "compile_work_order"): _STANDALONE,
    ("_sequential.py", "run_sequential", "build_work_list"): _ENTRY,
    ("_sequential.py", "run_sequential", "compile_work_order"): _ENTRY,
    ("_planner.py", "classify_job", "build_work_list"): _ENTRY,
    ("_planner.py", "classify_job", "compile_work_order"): _ENTRY,
    ("_pipeline_routing_signals.py", "out_of_core_admission", "build_work_list"): (
        "builds the list and compiles the order for out-of-core admission"
    ),
    ("_pipeline_routing_signals.py", "out_of_core_admission", "compile_work_order"): (
        "builds the list and compiles the order for out-of-core admission"
    ),
    ("out_of_core/_preflight.py", "run_preflight", "compile_plan_order"): _ENTRY,
    ("_chunked_bucket_perturb.py", "bucket_perturb_source_columns", "compile_plan_order"): (
        _CHUNK_ORDER
    ),
    (
        "_chunked_bucket_perturb.py",
        "reject_bucket_perturb_missing_namespace",
        "compile_plan_order",
    ): _CHUNK_ORDER,
    ("_chunked_code_set.py", "code_set_source_columns", "compile_plan_order"): _CHUNK_ORDER,
    ("_chunked_code_set.py", "resolve_pinned_code_set_records", "compile_plan_order"): (
        _CHUNK_ORDER
    ),
    ("_chunked_group_key.py", "reject_unsafe_group_key_group_by_dtype", "compile_plan_order"): (
        _CHUNK_ORDER
    ),
    ("_chunked_text_mask.py", "text_mask_source_columns", "compile_plan_order"): _CHUNK_ORDER,
    ("_guards.py", "reject_null_bearing_int", "build_work_list"): (
        "independent guard: builds its own candidate list"
    ),
    ("_guards.py", "null_bearing_int_candidates", "parents_of"): "independent guard: FK exemption",
    ("_guards.py", "reject_gated_hash_on_integer", "build_work_list"): (
        "independent guard: builds its own candidate list"
    ),
    ("_guards.py", "reject_gated_hash_on_integer", "parents_of"): (
        "independent guard: FK exemption"
    ),
    ("physical/_compiler.py", "_build_nodes", "build_work_list"): (
        "physical planning enumerates the work nodes"
    ),
    ("physical/_shadow_fk.py", "classify_fk_node", "parents_of"): (
        "physical planning checks FK shadowing"
    ),
    ("native/_plan.py", "compile_native_plan", "build_work_list"): (
        "the native compiler enumerates nodes to attach native requirements"
    ),
    ("_transforms.py", "reject_config_references_stored_index", "column_access"): (
        "reads column access for the stored-index reference check"
    ),
    ("_mixed_static.py", "_mask_table_config", "column_access"): (
        "reads column access for mixed-route admission"
    ),
    ("_chunked_carry.py", "untouched_columns", "resolve_operations"): (
        "existing carry analysis resolves the write set; tracked through S2b"
    ),
    ("_fk_keys.py", "lossless_int_columns", "source_anchor_columns"): (
        "hands the compiled nodes to the anchor walkers; builds none"
    ),
    ("_runner.py", "_nodes", "build_work_list"): (
        "a standalone caller of the column walkers that holds no compiled nodes"
    ),
    ("_runner.py", "source_anchor_columns", "date_shift_group_columns"): (
        "projection of the same node list"
    ),
    ("_runner.py", "source_anchor_columns", "joint_mask_key_by_columns"): (
        "projection of the same node list"
    ),
    ("_column_access.py", "column_access", "declared_access"): _DECL_API,
    ("_column_access.py", "created_columns", "column_access"): _DECL_API,
    ("_column_access.py", "touched_columns", "column_access"): _DECL_API,
    ("_column_access.py", "declared_access", "SURFACE_DECLARATIONS"): _DECL_API,
    ("_column_access.py", "creates_own_target", "SURFACE_DECLARATIONS"): _DECL_API,
    ("_column_access.py", "scalar_creating_reads", "SURFACE_DECLARATIONS"): _DECL_API,
    ("_column_access.py", "_with_when", "SURFACE_DECLARATIONS"): _DECL_API,
    ("_column_access.py", "_nested", "SURFACE_DECLARATIONS"): _DECL_API,
    ("_column_access.py", "_predicate_reads", "SURFACE_DECLARATIONS"): _DECL_API,
}


def _name_of(node: ast.expr, alias: dict[str, str]) -> str | None:
    if isinstance(node, ast.Name):
        return alias.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        return alias.get(node.attr, node.attr)
    return None


def find_sites(source: str, relpath: str) -> set[Site]:
    """Every tracked call or registry read in `source`, by (path, enclosing function, callee).

    Handles `from x import name as alias` (relative or absolute), `import x as y` module
    qualification, bound and class-qualified method calls (`graph.parents_of`,
    `RelationshipGraph.parents_of`) and subscript or `.get` reads of the declaration registry."""
    tree = ast.parse(source)
    alias: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for item in node.names:
                if item.name in TRACKED and item.asname:
                    alias[item.asname] = item.name
    found: set[Site] = set()

    def visit(node: ast.AST, function: str) -> None:
        for child in ast.iter_child_nodes(node):
            here = (
                child.name
                if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef)
                else function
            )
            callee: str | None = None
            if isinstance(child, ast.Call):
                callee = _name_of(child.func, alias)
                if (
                    isinstance(child.func, ast.Attribute)
                    and child.func.attr == "get"
                    and _name_of(child.func.value, alias) == "SURFACE_DECLARATIONS"
                ):
                    callee = "SURFACE_DECLARATIONS"
            elif isinstance(child, ast.Subscript) and (
                _name_of(child.value, alias) == "SURFACE_DECLARATIONS"
            ):
                callee = "SURFACE_DECLARATIONS"
            if callee in TRACKED:
                found.add((relpath, here, callee))
            visit(child, here)

    visit(tree, "<module>")
    return found


def _all_sites() -> set[Site]:
    out: set[Site] = set()
    for path in SRC.rglob("*.py"):
        out |= find_sites(path.read_text(), path.relative_to(SRC).as_posix())
    return out


def test_every_resolution_site_is_named_with_its_reason() -> None:
    assert _all_sites() <= set(ALLOWED), sorted(_all_sites() - set(ALLOWED))


def test_every_allowed_site_still_exists() -> None:
    """A removed call leaves no stale reason behind."""
    assert set(ALLOWED) <= _all_sites(), sorted(set(ALLOWED) - _all_sites())


_SEEDS = {
    "dispatch": (
        "_pandas_adapter.py",
        "def _dispatch_mask_node(self, node, graph):\n    return graph.parents_of(node.table, node.columns)\n",
    ),
    "dispatch_class_qualified": (
        "_pandas_adapter.py",
        "def _dispatch_mask_node(self, node):\n    return RelationshipGraph.parents_of(g, 't', ())\n",
    ),
    "fk_conversion": (
        "_fk_keys.py",
        "def to_pandas_fk_safe(table, cols):\n    return build_work_list(plan, registry)\n",
    ),
    "exact_int_registration": (
        "_exact_int_sources.py",
        "def exact_int_faker_sources(table, nodes):\n    return resolve_operation(n, g)\n",
    ),
    "aliased_import": (
        "_exact_int_sources.py",
        "from decoy_engine.execution.work_order import resolve_operation as ro\n"
        "def exact_int_faker_sources(table, nodes):\n    return ro(n, g)\n",
    ),
    "module_qualified": (
        "_exact_int_sources.py",
        "import decoy_engine.execution.work_order as wo\n"
        "def exact_int_faker_sources(table, nodes):\n    return wo.resolve_operations(n, g)\n",
    ),
    "registry_read": (
        "_when_gate.py",
        "def run_with_when_gate(h):\n    return SURFACE_DECLARATIONS['scalar:redact']\n",
    ),
    "registry_get": (
        "_when_gate.py",
        "def run_with_when_gate(h):\n    return ca.SURFACE_DECLARATIONS.get('scalar:redact')\n",
    ),
}


@pytest.mark.parametrize("seed", sorted(_SEEDS))
def test_a_seeded_forbidden_call_is_found_and_not_allowed(seed: str) -> None:
    relpath, source = _SEEDS[seed]
    sites = find_sites(source, relpath)
    assert sites, seed
    assert not sites <= set(ALLOWED), seed


# ---------------------------------------------------------------------------
# F4: after the entry's compile, nothing but an allowed independent site resolves a node again.
# ---------------------------------------------------------------------------

_INDEPENDENT = {(path, fn) for (path, fn, _callee) in ALLOWED if not path.startswith("work_order/")}
_TRAPPED = (
    "build_work_list",
    "resolve_operation",
    "resolve_operations",
    "joint_mask_key_by_columns",
    "date_shift_group_columns",
    "source_anchor_columns",
)


def _allowed_on_stack() -> bool:
    frame = sys._getframe(2)
    while frame is not None:
        name = frame.f_code.co_filename.replace("\\", "/")
        if "/execution/" in name:
            rel = name.split("/execution/", 1)[1]
            if (rel, frame.f_code.co_name) in _INDEPENDENT:
                return True
        frame = frame.f_back  # type: ignore[assignment]
    return False


class _Traps:
    """Counts the entry's compiles and, once one returned, makes resolution raise."""

    def __init__(self) -> None:
        self.compiles = 0
        self.armed = False
        self.registered: list[dict[tuple[str, str], Any]] = []

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from decoy_engine.execution import _exact_int_sources as exact
        from decoy_engine.execution._pandas_adapter import PandasExecutionAdapter
        from decoy_engine.relationships import RelationshipGraph

        modules = [m for n, m in list(sys.modules.items()) if n.startswith("decoy_engine.")]
        for module in modules:
            for name in ("compile_work_order", "compile_plan_order"):
                original = getattr(module, name, None)
                if callable(original) and getattr(original, "__module__", "").endswith(
                    "work_order.compile"
                ):
                    monkeypatch.setattr(module, name, self._counting(original), raising=False)
            for name in _TRAPPED:
                original = getattr(module, name, None)
                if callable(original) and getattr(original, "__module__", "") != __name__:
                    monkeypatch.setattr(module, name, self._trap(original, name), raising=False)
        monkeypatch.setattr(
            RelationshipGraph,
            "parents_of",
            self._trap(RelationshipGraph.parents_of, "parents_of"),
        )
        real_register = exact.register_exact_int_sources

        def spy(ctx: Any, table: str, *args: Any, **kwargs: Any) -> None:
            real_register(ctx, table, *args, **kwargs)
            self.registered.append(dict(ctx.exact_int_sources))

        for module in modules:
            if getattr(module, "register_exact_int_sources", None) is real_register:
                monkeypatch.setattr(module, "register_exact_int_sources", spy)
        assert PandasExecutionAdapter

    def _counting(self, original: Callable[..., Any]) -> Callable[..., Any]:
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            result = original(*args, **kwargs)
            self.compiles += 1
            self.armed = True
            return result

        return wrapped

    def _trap(self, original: Callable[..., Any], name: str) -> Callable[..., Any]:
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            if self.armed and not _allowed_on_stack():
                raise AssertionError(f"{name} called after the entry's compile")
            return original(*args, **kwargs)

        wrapped.__module__ = getattr(original, "__module__", __name__)
        return wrapped


@pytest.fixture
def traps(monkeypatch: pytest.MonkeyPatch) -> Iterator[_Traps]:
    t = _Traps()
    t.install(monkeypatch)
    return t


def _case_21() -> tuple[Any, pa.Table, Any]:
    table = pa.table(
        {
            "parent": pa.array(["A", "B"]),
            "ref": pa.array(["A", "B"]),
            "z_secret": pa.array(["one", "two"]),
        }
    )
    plan = ws.plan(
        [
            ("parent", ws.seed("redact", provider_config=(("redact_with", "X"),))),
            ("ref", ws.bundle()),
            ("z_secret", ws.seed("redact", when="ref == 'A'")),
        ]
    )
    return plan, table, ws.fk_graph("parent", "ref")


def _gated_joint(tmp_path: Path) -> tuple[Any, pa.Table, Any]:
    ref = ws.reference(tmp_path / "r.parquet", city=["C0", "C1"], state=["S0", "S1"])
    plan = ws.plan(
        [
            ("a_status", ws.seed("redact")),
            ("city", ws.joint(ref, ["city", "state"], when="a_status == 'go'")),
        ]
    )
    frame = pd.DataFrame(
        {"k": ["k0", "k1"], "a_status": ["no", "go"], "city": ["c0", "c1"], "state": ["s0", "s1"]}
    )
    frame.index = pd.Index([7, 7])
    return plan, pa.Table.from_pandas(frame), ws.NO_GRAPH


@pytest.mark.parametrize("fixture", ["case_21", "gated_joint"])
@pytest.mark.parametrize("entry", ["run_single", "run_sequential", "classify_job"])
def test_dispatch_and_snapshots_use_the_compiled_order(
    fixture: str, entry: str, traps: _Traps, tmp_path: Path
) -> None:
    """F4. One compile per entry; no later resolution outside the named independent sites; the
    output (or the classification) is the expected one, checked separately."""
    plan, table, graph = _case_21() if fixture == "case_21" else _gated_joint(tmp_path)
    bound = (("ref",),) if fixture == "case_21" else (("k",),)
    if entry == "classify_job":
        result = ws.classify(plan, table, graph)
        assert result.mode
    else:
        run = ws.run if entry == "run_single" else ws.run_sequential
        out = run(plan, table, graph, bound=bound)
        if fixture == "case_21":
            assert out.column("ref").to_pylist() == ["X", "X"]
            assert out.column("z_secret").to_pylist() == ["REDACTED", "two"]
        else:
            assert out.column("city").to_pylist()[0] == "c0"
            assert out.column("city").to_pylist()[1] in {"C0", "C1"}
    assert traps.compiles == 1, (entry, traps.compiles)


@pytest.mark.parametrize("entry", ["run_single", "run_sequential"])
def test_exact_integer_registration_reads_compiled_writes(
    entry: str, traps: _Traps, tmp_path: Path
) -> None:
    """Registration ran with a nullable integer above 2**53 and an eligible deterministic Faker,
    and an earlier writer of the column prevents a stale registration. A per-node resolve inside
    registration would trip the armed trap."""
    big = [2**60, None, 2**60 + 1, 5]
    table = pa.table({"k": pa.array(list("abcd")), "n": pa.array(big, type=pa.int64())})
    faker = ws.seed(
        "faker",
        provider="person_email",
        backend_type="faker",
        cardinality_mode="reuse",
        deterministic=True,
        namespace="nm",
        provider_config=(("pool_size", 64),),
    )
    run = ws.run if entry == "run_single" else ws.run_sequential
    run(ws.plan([("n", faker)]), table, bound=(("n",),))
    assert traps.registered and ("t", "n") in traps.registered[-1]
    ref = ws.reference(tmp_path / "r.parquet", city=["JC"], n=[7])
    writer_first = ws.plan([("city", ws.joint(ref, ["city", "n"], when="k == 'a'")), ("n", faker)])
    traps.registered.clear()
    t2 = pa.table(
        {
            "k": pa.array(list("abcd")),
            "city": pa.array(["c0", "c1", "c2", "c3"]),
            "n": pa.array(big, type=pa.int64()),
        }
    )
    try:
        run(writer_first, t2, bound=(("n",),))
    except Exception:
        pass
    assert not traps.registered or ("t", "n") not in traps.registered[-1]
