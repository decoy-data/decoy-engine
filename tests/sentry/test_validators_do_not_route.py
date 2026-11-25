"""A `validators:` block never changes the route (EXPECT-OFF-ROUTE, plan section 5 and V9).

Walks the syntax tree of every module under `src/decoy_engine/execution/` and fails on a read of
the validator list: a `validators` subscript or `.get`, a name, parameter, attribute or keyword
spelled like the list, a truthiness test of it, or an import of a private `decoy_engine.validators`
module. Lifecycle code goes through the public session helpers, which this guard does not see.

`S3_PENDING` lists the modules that still hold a read because the streamed and bounded routes
(slice S3) have not been migrated yet. It may only shrink: a module outside it with a read fails,
and a module inside it with no read fails, so the list cannot go stale.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

EXECUTION = Path(__file__).resolve().parents[2] / "src" / "decoy_engine" / "execution"

_NAMES = frozenset({"validators", "validators_requested", "config_validators", "validators_config"})
_PREFIXES = ("validators_ooc_",)
_KEY = "validators"
_PRIVATE_PREFIX = "decoy_engine." + "validators" + "._"

S3_PENDING: frozenset[str] = frozenset(
    {
        "_chunked_output_sink.py",
        "_job_estimate.py",
        "_pipeline_context.py",
        "_pipeline_multi_table.py",
        "_pipeline_routing.py",
        "_pipeline_routing_signals.py",
        "_transforms_admission.py",
        "_transforms_prepare.py",
        "_unified_slice.py",
        "capacity.py",
        "out_of_core/_rewrite_pass.py",
        "out_of_core/_runner.py",
        "out_of_core/_stream_driver.py",
        "out_of_core/_validate_batch.py",
        "physical/_compiler.py",
        "physical/_inputs.py",
        "physical/_live_inputs.py",
        "physical/_snapshot.py",
        "pipeline/_lazy_input.py",
    }
)


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


def _scan() -> dict[str, list[str]]:
    hits: dict[str, list[str]] = {}
    for path in sorted(EXECUTION.rglob("*.py")):
        found = violations(path.read_text())
        if found:
            hits[str(path.relative_to(EXECUTION))] = found
    return hits


def test_no_module_outside_the_pending_list_reads_the_validator_list() -> None:
    offenders = {rel: found for rel, found in _scan().items() if rel not in S3_PENDING}
    assert offenders == {}


def test_the_pending_list_holds_only_modules_that_still_read_it() -> None:
    stale = sorted(S3_PENDING - set(_scan()))
    assert stale == []


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
