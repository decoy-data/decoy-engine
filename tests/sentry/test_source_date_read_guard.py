"""AT-V1 and AT-V8 guard (DATE-RANGE-SENTINEL S5, section 4.4b): no path hands Arrow source data
to pandas without the checked read.

The checked read in `decoy_engine.io` is the one date check. A function is a sink site when it
calls `to_pandas`, `to_pandas_fk_safe` or a name in `_CONVERSION_HELPERS` (the conversion
wrappers of `internal/pandas_compat.py`). Every sink site is either in `_SELF_CHECKED` (and still
calls its checks) or in `_DOWNSTREAM_FUNCTIONS` with a reason; the allowance is per function and
never per file, and it is not transitive: listing a function does not make its callers sinks. A
helper that takes a raw Arrow table and converts it (`_RAW_HELPER_CALLERS`) has its direct callers
pinned by (module, qualified function) at both ends, so a new caller cannot forward raw chunks.

`scan` takes the module texts as an argument (default: the repository files), so a test seeds a
bypass in memory. Covered shapes: direct calls, `from x import name as alias`, `import x as m`,
module-qualified calls, relative imports and same-module calls. Deliberate evasion (`getattr`,
`eval`, string-built names) is V2-LOG, per the recurring-defects catalog (class 5)."""

from __future__ import annotations

import ast
from collections.abc import Mapping
from pathlib import Path

import pytest

import decoy_engine

_SRC = Path(decoy_engine.__file__).parent
_SINKS = frozenset({"to_pandas", "to_pandas_fk_safe"})
# The conversion wrappers in `internal/pandas_compat.py`. The guard asserts this set equals the
# functions in that file that call `to_pandas`, so it cannot drift from the file.
_CONVERSION_HELPERS = frozenset(
    {"table_to_pandas", "table_to_pandas_exact_ints", "_working_categorical"}
)
_HELPERS_FILE = "internal/pandas_compat.py"
# Checks that return the data to use from here on. A bare call statement drops the repair.
_ANY_CHECK = frozenset(
    {
        "check_source_dates",
        "checked_batches",
        "check_resident_sources",
        "checked_loader",
        "checked_chunks",
    }
)
_STOP_AT = 40  # a larger allowlist is a design question to report, not to work around

Site = tuple[str, str]  # (module path under src/decoy_engine, qualified function name)

# A function that takes caller data and converts it, or hands it to the route that does, must call
# its check itself: site -> the checks it must call (all of them).
_SELF_CHECKED: dict[Site, set[str]] = {
    ("execution/_pipeline.py", "run_pipeline"): {"check_resident_sources", "checked_loader"},
    ("execution/_pandas_adapter.py", "PandasExecutionAdapter.run"): {"check_resident_sources"},
    ("execution/_sequential.py", "run_sequential"): {"checked_loader"},
    ("execution/out_of_core/_runner.py", "run_fk_out_of_core"): {"check_resident_sources"},
    ("execution/native/_chunked_entry.py", "_run_chunked"): {"checked_chunks"},
    ("execution/_chunked.py", "run_mask_pipeline_chunked"): {"checked_chunks"},
    ("profile/_readers.py", "OpenedLazyBatches.__init__"): {"checked_batches"},
    ("profile/_readers.py", "LazySource.to_table"): {"check_source_dates"},
    ("profile/_readers.py", "head_frame_from_batches"): {"check_source_dates"},
    ("profile/_cloud_readers.py", "_checked_frame"): {"check_source_dates"},
    ("profile/_readers_resident.py", "ResidentTableSource.sample_frame"): {"check_source_dates"},
    ("profile/_readers_resident.py", "ResidentTableSource.to_frame"): {"check_source_dates"},
}

# Sink sites that run on data one of the entries above already checked, or hold no source data.
_DOWNSTREAM_FUNCTIONS: dict[Site, str] = {
    (
        "execution/_chunked_carry.py",
        "CarryPlan.diagnose_adapter",
    ): "diagnoses a carried column of a checked chunk",
    ("execution/_chunked_profile.py", "empty_input_profile"): "an empty frame from a gated schema",
    (
        "execution/_chunked_profile.py",
        "walk_one_table",
    ): "raw-Arrow helper; its callers are pinned in _RAW_HELPER_CALLERS",
    (
        "execution/_fk_keys.py",
        "to_pandas_fk_safe",
    ): "the FK conversion wrapper; its callers pass checked tables",
    (
        "execution/_mixed_fk_bridge.py",
        "_write_back_fk_column",
    ): "frame built from checked run inputs",
    (
        "execution/_pipeline_finalize.py",
        "compute_fidelity_reports",
    ): "fidelity reports over checked inputs",
    (
        "execution/_pipeline_full_frame.py",
        "_raise_if_source_value_unrepresentable",
    ): "diagnoses a source `run` already checked",
    (
        "execution/_transforms_table.py",
        "to_transform_frame",
    ): "transform frame of a checked resident table",
    ("execution/_unified_slice_admission.py", "cheap_admission"): "admission over a checked source",
    (
        "execution/_unified_slice_evidence.py",
        "reconstruct_source_shaped_output",
    ): "output shaped from a checked source",
    (
        "execution/native/_bucket_perturb_ext.py",
        "native_bucket_perturb",
    ): "kernel helper over a checked chunk",
    (
        "execution/native/_bucket_perturb_ext.py",
        "native_range_exceeded",
    ): "kernel helper over a checked chunk",
    (
        "execution/native/_date_shift_ext.py",
        "native_date_shift",
    ): "kernel helper over a checked chunk",
    (
        "execution/native/_faker_null_mask.py",
        "faker_missing_mask",
    ): "kernel helper over a checked chunk",
    (
        "execution/native/_group_key_kernel.py",
        "_stringify_sibling",
    ): "kernel helper over a checked chunk",
    ("execution/native/_operator_step.py", "_preserved_mask"): "kernel helper over a checked chunk",
    ("execution/native/_when_mask.py", "when_mask"): "kernel helper over a checked chunk",
    (
        "execution/out_of_core/_bucket_native.py",
        "native_bucket_perturb_array",
    ): "out-of-core batch from a checked reader",
    (
        "execution/out_of_core/_mask_group_c.py",
        "_to_series",
    ): "out-of-core batch from a checked reader",
    (
        "execution/pipeline/_post_scan.py",
        "PostScanGate._column_suite",
    ): "post-scan over checked inputs",
    (
        "execution/pipeline/_post_scan.py",
        "PostScanGate._report_only",
    ): "post-scan over checked inputs",
    ("execution/pipeline/_source_types.py", "_expected_index"): "index of a checked source",
    (
        "generation/_numeric_typing.py",
        "generated_table_to_pandas",
    ): "generated output, no source data",
    (
        "internal/pandas_compat.py",
        "_working_categorical",
    ): "the conversion helper; callers pass checked tables",
    (
        "internal/pandas_compat.py",
        "table_to_pandas",
    ): "the conversion helper; callers pass checked tables",
    (
        "internal/pandas_compat.py",
        "table_to_pandas_exact_ints",
    ): "the conversion helper; callers pass checked tables",
    ("profile/_fixed_width_reader.py", "_empty_frame"): "builds an empty frame",
    (
        "profile/_readers.py",
        "ParquetFileSource.to_frame",
    ): "converts `LazySource.to_table`, which is checked",
    ("profile/_readers_resident.py", "_frame_of"): "receives data its caller checked",
    ("verification/postmask/_column_facts.py", "_series"): "post-mask facts of masked output",
}

# Helpers that take a raw Arrow table and convert it: helper -> its allowed direct callers, each
# with the provenance of the data it passes.
_RAW_HELPER_CALLERS: dict[Site, dict[Site, str]] = {
    ("execution/_chunked_profile.py", "walk_one_table"): {
        ("execution/_chunked_profile.py", "first_chunk_profile"): "first chunk, checked on entry",
        ("execution/_chunked_carry.py", "CarryPlan.diagnose_profile"): "checked chunk of a carry",
    },
}


def repository_texts() -> dict[str, str]:
    return {p.relative_to(_SRC).as_posix(): p.read_text() for p in sorted(_SRC.rglob("*.py"))}


def _functions(tree: ast.AST) -> dict[str, ast.AST]:
    found: dict[str, ast.AST] = {}

    def walk(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
                name = f"{prefix}{child.name}"
                found[name] = child
                walk(child, f"{name}.")
            else:
                walk(child, prefix)

    walk(tree, "")
    return found


def _module_of(rel: str, node: ast.ImportFrom) -> str | None:
    """The `src/decoy_engine`-relative path an import statement names, or None outside it."""
    if node.level:
        base = rel.split("/")[:-1]
        base = base[: len(base) - (node.level - 1)] if node.level > 1 else base
        parts = [*base, *(node.module.split(".") if node.module else [])]
    elif node.module and node.module.split(".")[0] == "decoy_engine":
        parts = node.module.split(".")[1:]
    else:
        return None
    return "/".join(parts)


class _Imports:
    """What each local name of one module refers to: a (module path, name) or a module path."""

    def __init__(self, rel: str, tree: ast.AST, modules: set[str]) -> None:
        self.names: dict[str, Site] = {}
        self.modules: dict[str, str] = {}
        self._rel = rel
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                target = _module_of(rel, node)
                if target is None:
                    continue
                for alias in node.names:
                    local = alias.asname or alias.name
                    submodule = f"{target}/{alias.name}"
                    if f"{submodule}.py" in modules:
                        self.modules[local] = f"{submodule}.py"
                    else:
                        self.names[local] = (self._file(target, modules), alias.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] == "decoy_engine" and alias.asname:
                        path = "/".join(alias.name.split(".")[1:])
                        self.modules[alias.asname] = self._file(path, modules)

    @staticmethod
    def _file(path: str, modules: set[str]) -> str:
        return f"{path}.py" if f"{path}.py" in modules else f"{path}/__init__.py"

    def resolve(self, call: ast.Call, modules: set[str]) -> Site | None:
        func = call.func
        if isinstance(func, ast.Name):
            if func.id in self.names:
                return self.names[func.id]
            return (self._rel, func.id)
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            module = self.modules.get(func.value.id)
            if module is not None:
                return (module, func.attr)
        return None


def _called_names(node: ast.AST) -> set[str]:
    names = set()
    for call in ast.walk(node):
        if isinstance(call, ast.Call):
            func = call.func
            names.add(func.id if isinstance(func, ast.Name) else getattr(func, "attr", ""))
    return names


def scan(texts: Mapping[str, str] | None = None) -> dict[str, list[str]]:
    """The guard's findings for `texts` (path under src/decoy_engine -> source), by kind."""
    texts = dict(repository_texts() if texts is None else texts)
    modules = set(texts)
    trees = {rel: ast.parse(text) for rel, text in texts.items()}
    found: dict[str, list[str]] = {
        "unchecked_sink": [],
        "dropped_check": [],
        "new_caller": [],
        "edges": [],
    }
    sites: set[Site] = set()
    for rel, tree in trees.items():
        imports = _Imports(rel, tree, modules)
        for qualname, func in _functions(tree).items():
            if isinstance(func, ast.ClassDef):
                continue
            site = (rel, qualname)
            calls = [n for n in ast.walk(func) if isinstance(n, ast.Call)]
            for call in calls:
                name = getattr(call.func, "id", None) or getattr(call.func, "attr", None)
                if name in _SINKS or name in _CONVERSION_HELPERS:
                    sites.add(site)
                resolved = imports.resolve(call, modules)
                if resolved is not None and resolved in _RAW_HELPER_CALLERS:
                    found["edges"].append(f"{rel}::{qualname} -> {resolved[0]}::{resolved[1]}")
                    if site not in _RAW_HELPER_CALLERS[resolved] and site != resolved:
                        found["new_caller"].append(
                            f"{rel}::{qualname} calls {resolved[0]}::{resolved[1]}"
                        )
            for stmt in ast.walk(func):
                if (
                    isinstance(stmt, ast.Expr)
                    and isinstance(stmt.value, ast.Call)
                    and (
                        getattr(stmt.value.func, "id", None)
                        or getattr(stmt.value.func, "attr", None)
                    )
                    in _ANY_CHECK
                ):
                    found["dropped_check"].append(f"{rel}::{qualname}")
    for site in sorted(sites):
        if site not in _SELF_CHECKED and site not in _DOWNSTREAM_FUNCTIONS:
            found["unchecked_sink"].append(f"{site[0]}::{site[1]}")
    found["dropped_check"] = sorted(set(found["dropped_check"]))
    return found


# --- the repository passes ----------------------------------------------------------------------


def test_the_repository_has_no_unchecked_sink_dropped_check_or_new_caller() -> None:
    found = scan()
    assert not found["unchecked_sink"], (
        "Arrow data reaches pandas here without `decoy_engine.io.check_source_dates`: call the "
        f"checked read, or list the function in _DOWNSTREAM_FUNCTIONS with a reason: {found['unchecked_sink']}"
    )
    assert not found["dropped_check"], f"a check result is dropped: {found['dropped_check']}"
    assert not found["new_caller"], (
        f"an unreviewed caller of a raw-Arrow helper: {found['new_caller']}"
    )


def test_every_listed_entry_still_exists_still_calls_its_check_and_is_still_a_sink() -> None:
    texts = repository_texts()
    trees = {rel: _functions(ast.parse(text)) for rel, text in texts.items()}
    for (rel, qualname), required in _SELF_CHECKED.items():
        func = trees.get(rel, {}).get(qualname)
        assert func is not None, f"{rel}::{qualname} is gone; update the guard"
        missing = required - _called_names(func)
        assert not missing, f"{rel}::{qualname} no longer calls {sorted(missing)}"
    for site in _DOWNSTREAM_FUNCTIONS:
        assert site in trees.get(site[0], {}), f"{site} is gone; drop it from _DOWNSTREAM_FUNCTIONS"
    for helper, callers in _RAW_HELPER_CALLERS.items():
        assert helper in {(r, q) for r, f in trees.items() for q in f}, f"{helper} is gone"
        for caller in callers:
            assert caller[1] in trees.get(caller[0], {}), f"{caller} is gone"


def test_the_pinned_caller_edges_are_the_ones_the_scan_resolves() -> None:
    """A guard that finds no edge pins nothing: both known callers of `walk_one_table` appear."""
    edges = set(scan()["edges"])
    pinned = {
        f"{rel}::{name} -> {helper[0]}::{helper[1]}"
        for helper, callers in _RAW_HELPER_CALLERS.items()
        for rel, name in callers
    }
    assert pinned <= edges


def test_the_allowlists_stay_small_and_the_helper_set_matches_the_file() -> None:
    assert len(_DOWNSTREAM_FUNCTIONS) <= _STOP_AT, "over 40 entries: stop and report"
    tree = _functions(ast.parse(repository_texts()[_HELPERS_FILE]))
    in_file = {
        name
        for name, func in tree.items()
        if not isinstance(func, ast.ClassDef) and _called_names(func) & _SINKS
    }
    assert in_file == set(_CONVERSION_HELPERS)
    assert set().union(*_SELF_CHECKED.values()) <= _ANY_CHECK


# --- seeded bypasses: each must fail the scan ---------------------------------------------------


def _seeded(
    extra: Mapping[str, str], append: Mapping[str, str] | None = None
) -> dict[str, list[str]]:
    texts = repository_texts()
    for rel, text in (append or {}).items():
        texts[rel] = texts[rel] + "\n" + text
    texts.update(extra)
    return scan(texts)


def test_seed_1_a_conversion_added_to_a_file_the_old_guard_exempted_as_a_whole() -> None:
    found = _seeded(
        {},
        {
            "execution/_pandas_adapter.py": "def _seeded_entry(source):\n    return source.to_pandas()\n"
        },
    )
    assert "execution/_pandas_adapter.py::_seeded_entry" in found["unchecked_sink"]


def test_seed_2_a_new_module_forwards_raw_chunks_to_the_conversion_helper() -> None:
    text = (
        "from decoy_engine.internal.pandas_compat import table_to_pandas_exact_ints\n\n\n"
        "def run_seeded(chunks):\n"
        "    return [table_to_pandas_exact_ints(c, columns=()) for c in chunks]\n"
    )
    found = _seeded({"execution/_seeded_forward.py": text})
    assert "execution/_seeded_forward.py::run_seeded" in found["unchecked_sink"]


def test_seed_3_a_check_call_used_as_a_bare_statement_drops_the_repair() -> None:
    text = (
        "from decoy_engine.io import check_source_dates\n\n\n"
        "def run_pipeline(t, n):\n"
        "    check_source_dates(t, table=n)\n"
        "    return t.to_pandas()\n"
    )
    found = _seeded({"execution/_seeded_bare.py": text})
    assert "execution/_seeded_bare.py::run_pipeline" in found["dropped_check"]


@pytest.mark.parametrize(
    "imports",
    [
        "from decoy_engine.execution._chunked_profile import walk_one_table\n\n\n"
        'def run_seeded(raw):\n    return walk_one_table(raw, table_name="t")\n',
        "from decoy_engine.execution._chunked_profile import walk_one_table as walk\n\n\n"
        'def run_seeded(raw):\n    return walk(raw, table_name="t")\n',
        "from decoy_engine.execution import _chunked_profile as cp\n\n\n"
        'def run_seeded(raw):\n    return cp.walk_one_table(raw, table_name="t")\n',
        "from ._chunked_profile import walk_one_table\n\n\n"
        'def run_seeded(raw):\n    return walk_one_table(raw, table_name="t")\n',
    ],
    ids=["plain", "alias", "module_alias", "relative"],
)
def test_seed_4_a_new_caller_of_the_raw_arrow_helper_is_named_with_its_callee(imports: str) -> None:
    found = _seeded({"execution/_seeded_walk.py": imports})
    assert found["new_caller"] == [
        "execution/_seeded_walk.py::run_seeded calls execution/_chunked_profile.py::walk_one_table"
    ]


def test_a_stale_allowance_fails_the_entry_check(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(_DOWNSTREAM_FUNCTIONS, ("execution/_gone.py", "gone"), "stale")
    with pytest.raises(AssertionError):
        test_every_listed_entry_still_exists_still_calls_its_check_and_is_still_a_sink()
