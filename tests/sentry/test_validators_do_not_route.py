"""A `validators:` block never changes the route (EXPECT-OFF-ROUTE, plan section 5 and V9).

Walks the syntax tree of every module under `src/decoy_engine/execution/` and fails on a read of
the validator list: a `validators` subscript or `.get`, a name, parameter, attribute or keyword
spelled like the list, a truthiness test of it, or an import of a private `decoy_engine.validators`
module. Lifecycle code goes through the public session helpers, which this guard does not see.

`S3_PENDING` pins each read that remains, by module, kind and enclosing function, with a count.
Those reads feed the sequential and out-of-core route choice that slice S3 migrates. The pin is
exact: a new read anywhere fails, including a second read in a function already listed, and a
pinned read that is gone fails until its entry is removed, so the list only shrinks.
"""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

import pytest

EXECUTION = Path(__file__).resolve().parents[2] / "src" / "decoy_engine" / "execution"

_NAMES = frozenset({"validators", "validators_requested", "config_validators", "validators_config"})
_PREFIXES = ("validators_ooc_",)
_KEY = "validators"
_PRIVATE_PREFIX = "decoy_engine." + "validators" + "._"

# Each read still allowed, as (module, kind, enclosing function) -> count. The count may only go
# down; a new site, even in a listed module or function, fails. Every remaining read feeds a route
# decision or a streamed-route check that slice S3 migrates.
S3_PENDING: dict[tuple[str, str, str], int] = {
    # Output-mode choice for streamed sinks: S3.
    ("_chunked_output_sink.py", "get", "decide_output_mode"): 1,
    # Bounded-memory estimate mirrors the routing decline: S3.
    ("_job_estimate.py", "keyword validators", "_estimate"): 1,
    ("_job_estimate.py", "get", "_estimate"): 1,
    # Builds the routing inputs for decide_execution_route: S3.
    ("_pipeline_context.py", "keyword validators", "build_run_context"): 1,
    ("_pipeline_context.py", "get", "build_run_context"): 1,
    ("_pipeline_context.py", "keyword validators", "decide_route"): 1,
    ("_pipeline_context.py", "get", "decide_route"): 1,
    # Multi-table gate for the streamed lane: S3.
    ("_pipeline_multi_table.py", "get", "_job_gates_hold"): 1,
    # The decline itself and the D3a out-of-core lift: S3.
    ("_pipeline_routing.py", "parameter validators", "_sequential_eligible"): 1,
    ("_pipeline_routing.py", "name validators", "_sequential_eligible"): 1,
    ("_pipeline_routing.py", "parameter validators", "bounded_admission"): 1,
    ("_pipeline_routing.py", "keyword validators", "bounded_admission"): 1,
    ("_pipeline_routing.py", "name validators", "bounded_admission"): 1,
    ("_pipeline_routing.py", "parameter validators", "decide_execution_route"): 1,
    ("_pipeline_routing.py", "parameter validators_ooc_safe", "decide_execution_route"): 1,
    ("_pipeline_routing.py", "name validators_ooc_ready", "decide_execution_route"): 2,
    ("_pipeline_routing.py", "name validators_ooc_safe", "decide_execution_route"): 1,
    ("_pipeline_routing.py", "keyword validators", "decide_execution_route"): 3,
    ("_pipeline_routing.py", "name validators", "decide_execution_route"): 3,
    # Signal resolution forwarding to decide_execution_route: S3.
    ("_pipeline_routing_signals.py", "parameter validators", "resolve_execution_route"): 1,
    ("_pipeline_routing_signals.py", "keyword validators", "resolve_execution_route"): 1,
    ("_pipeline_routing_signals.py", "name validators", "resolve_execution_route"): 1,
    ("_pipeline_routing_signals.py", "keyword validators_ooc_safe", "resolve_execution_route"): 1,
    ("_pipeline_routing_signals.py", "name validators_ooc_safe", "resolve_execution_route"): 1,
    # Transform admission forwards to the routing decline: S3.
    ("_transforms_admission.py", "parameter validators", "check_rejections_before_preparation"): 1,
    ("_transforms_admission.py", "keyword validators", "check_rejections_before_preparation"): 1,
    ("_transforms_admission.py", "name validators", "check_rejections_before_preparation"): 1,
    ("_transforms_prepare.py", "parameter validators", "prepare_transform_sources"): 1,
    ("_transforms_prepare.py", "keyword validators", "prepare_transform_sources"): 1,
    ("_transforms_prepare.py", "name validators", "prepare_transform_sources"): 1,
    # The lane's physical plan must compile the route runtime takes, which still declines: S3.
    ("_unified_slice.py", "keyword validators", "_execute_admitted"): 1,
    ("_unified_slice.py", "get", "_execute_admitted"): 1,
    # Capacity estimate mirrors the routing decline: S3.
    ("capacity.py", "keyword validators", "estimate_job_capacity"): 2,
    ("capacity.py", "get", "estimate_job_capacity"): 2,
    # The out-of-core route's own batch validation: S3.
    ("out_of_core/_rewrite_pass.py", "parameter validators", "_stream_table"): 1,
    ("out_of_core/_rewrite_pass.py", "name validators", "rewritten"): 1,
    ("out_of_core/_runner.py", "name validators", "run_fk_out_of_core"): 3,
    ("out_of_core/_stream_driver.py", "parameter validators", "stream_table"): 1,
    ("out_of_core/_stream_driver.py", "name validators", "stream_table"): 1,
    ("out_of_core/_validate_batch.py", "get", "admitted_validators"): 1,
    ("out_of_core/_validate_batch.py", "get", "validators_ooc_safe"): 1,
    ("out_of_core/_validate_batch.py", "get", "build_validator_collector"): 1,
    # The physical plan replays decide_execution_route on captured inputs: S3.
    ("physical/_compiler.py", "keyword validators", "layer1_route"): 1,
    ("physical/_compiler.py", "attribute validators", "layer1_route"): 1,
    ("physical/_compiler.py", "keyword validators", "out_of_core_not_ready_reason"): 1,
    ("physical/_compiler.py", "attribute validators", "out_of_core_not_ready_reason"): 1,
    ("physical/_inputs.py", "name validators", "PhysicalPlanInputs"): 1,
    ("physical/_live_inputs.py", "parameter validators", "build_live_physical_plan_inputs"): 1,
    ("physical/_live_inputs.py", "keyword validators", "build_live_physical_plan_inputs"): 1,
    ("physical/_live_inputs.py", "name validators", "build_live_physical_plan_inputs"): 1,
    ("physical/_snapshot.py", "name config_validators", "capture_physical_plan_inputs"): 3,
    ("physical/_snapshot.py", "get", "capture_physical_plan_inputs"): 1,
    ("physical/_snapshot.py", "keyword validators", "capture_physical_plan_inputs"): 2,
    # Lazy-input boundedness mirrors the routing decline: S3.
    ("pipeline/_lazy_input.py", "keyword validators", "_relationship_job_is_bounded"): 1,
    ("pipeline/_lazy_input.py", "get", "_relationship_job_is_bounded"): 1,
}


def _is_validator_name(name: str) -> bool:
    return name in _NAMES or name.startswith(_PREFIXES)


def violations(source: str) -> list[str]:
    """Every validator-list read in `source`, as `line: kind`."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        line = getattr(node, "lineno", 0)
        if isinstance(node, ast.Name) and _is_validator_name(node.id):
            found.append(f"{line}: name {node.id}")
        elif isinstance(node, ast.arg) and _is_validator_name(node.arg):
            found.append(f"{line}: parameter {node.arg}")
        elif isinstance(node, ast.Attribute) and _is_validator_name(node.attr):
            found.append(f"{line}: attribute {node.attr}")
        elif isinstance(node, ast.keyword) and node.arg and _is_validator_name(node.arg):
            found.append(f"{line}: keyword {node.arg}")
        elif isinstance(node, ast.Subscript) and _constant(node.slice) == _KEY:
            found.append(f"{line}: subscript")
        elif isinstance(node, ast.Call) and _call_reads_key(node):
            found.append(f"{line}: get")
        elif isinstance(node, ast.ImportFrom) and _private_validators_import(node):
            found.append(f"{line}: private import")
    return found


def _constant(node: ast.AST) -> object:
    return node.value if isinstance(node, ast.Constant) else None


def _call_reads_key(node: ast.Call) -> bool:
    func = node.func
    if isinstance(func, ast.Attribute) and func.attr == "get" and node.args:
        return _constant(node.args[0]) == _KEY
    if isinstance(func, ast.Name) and func.id == "getattr" and len(node.args) >= 2:
        value = _constant(node.args[1])
        return isinstance(value, str) and _is_validator_name(value)
    return False


def _private_validators_import(node: ast.ImportFrom) -> bool:
    module = node.module or ""
    return module.startswith(_PRIVATE_PREFIX)


def sites(source: str) -> Counter[tuple[str, str]]:
    """Each read in `source` as (kind, enclosing function), counted; `<module>` at top level."""
    tree = ast.parse(source)
    scopes = [
        (node.lineno, node.end_lineno or node.lineno, node.name)
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
    found: Counter[tuple[str, str]] = Counter()
    for entry in violations(source):
        line_text, kind = entry.split(": ", 1)
        line = int(line_text)
        enclosing = [s for s in scopes if s[0] <= line <= s[1]]
        name = min(enclosing, key=lambda s: s[1] - s[0])[2] if enclosing else "<module>"
        found[(kind, name)] += 1
    return found


def _scan() -> Counter[tuple[str, str, str]]:
    hits: Counter[tuple[str, str, str]] = Counter()
    for path in sorted(EXECUTION.rglob("*.py")):
        rel = str(path.relative_to(EXECUTION))
        for (kind, name), count in sites(path.read_text()).items():
            hits[(rel, kind, name)] += count
    return hits


def test_no_read_beyond_the_pinned_sites() -> None:
    extra = _scan() - Counter(S3_PENDING)
    assert dict(extra) == {}


def test_the_pinned_sites_all_still_read_it() -> None:
    stale = Counter(S3_PENDING) - _scan()
    assert dict(stale) == {}


def test_a_new_site_in_a_listed_function_fails() -> None:
    seeded = (
        'def _execute_admitted(config):\n    if config.get("validators"):\n        return None\n'
    )
    assert sites(seeded) == Counter({("get", "_execute_admitted"): 1})


@pytest.mark.parametrize(
    "snippet",
    [
        'x = config.get("validators")',
        'x = config["validators"]',
        'x = ctx.config.get("validators")',
        'x = cfg.get("validators", [])',
        "def f(validators): pass",
        "if validators:\n    pass",
        "x = bool(validators)",
        "x = not validators",
        "x = len(validators)",
        'x = getattr(ctx, "validators_requested")',
        "x = ctx.validators_requested",
        "f(validators_ooc_safe=True)",
        "from decoy_engine." + "validators._registry import validate",
    ],
)
def test_the_scan_sees_each_seeded_spelling(snippet: str) -> None:
    assert violations(snippet), snippet


def test_the_scan_passes_the_public_import() -> None:
    assert violations("from decoy_engine.validators import ValidationSession") == []
