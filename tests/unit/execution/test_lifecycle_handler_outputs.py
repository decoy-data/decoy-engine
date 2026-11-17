"""F24 84-E1 (AT-E1-30): the output a strategy handler declares is the output it writes.

The lifecycle estimate reads each handler's declaration (`output_is_input`,
`output_string_width`) instead of keeping strategy names or widths of its own. These cells run
the handlers and compare every written cell with the declaration, so the two cannot drift.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pyarrow as pa
import pytest

from decoy_engine.execution import PandasExecutionAdapter
from decoy_engine.execution._strategies import SCALAR_HANDLERS
from decoy_engine.execution._strategies._hash import HashStrategyHandler
from decoy_engine.execution._strategies._passthrough import PassthroughHandler
from decoy_engine.execution._strategies._redact import RedactHandler
from decoy_engine.plan._types import ColumnSeed, SeedEnvelope, TableSeed
from decoy_engine.providers_v2 import get_default_registry
from decoy_engine.relationships._graph import RelationshipGraph
from decoy_engine.relationships._namespace import NamespaceRegistry

_SRC = Path(__file__).resolve().parents[3] / "src" / "decoy_engine" / "execution" / "pipeline"
_SEED = (0x55).to_bytes(8, "big")


def _seed(strategy: str, config: tuple[tuple[str, Any], ...]) -> ColumnSeed:
    return ColumnSeed(
        namespace="ns" if strategy == "hash" else None,
        strategy=strategy,
        provider=strategy,
        backend_type="faker",
        backend_version="v",
        cardinality_mode="reuse",
        deterministic=strategy == "hash",
        provider_config=config,
        coherent_with=(),
    )


def _run(strategy: str, config: tuple[tuple[str, Any], ...]) -> tuple[list[Any], ColumnSeed]:
    seed = _seed(strategy, config)
    plan = SimpleNamespace(
        seed_envelope=SeedEnvelope(
            job_seed=_SEED, per_table=(("t", TableSeed(per_column=(("n", seed),), per_group=())),)
        )
    )
    table = pa.table({"n": pa.array([7, 123456789, None, 42], type=pa.int64())})
    result = PandasExecutionAdapter().run_single(
        plan,
        table,
        registry=get_default_registry(),
        relationship_graph=RelationshipGraph(edges=(), ordering=()),
        namespace_registry=NamespaceRegistry(bindings=()),
    )
    return result.output.column("n").to_pylist(), seed


@pytest.mark.parametrize(
    "config",
    [(), (("truncate", 12),), (("truncate", 100),)],
    ids=["default", "truncate-12", "truncate-100"],
)
def test_hash_declares_the_width_it_writes(config: tuple[tuple[str, Any], ...]) -> None:
    cells, seed = _run("hash", config)
    width = HashStrategyHandler().output_string_width(seed.provider_config)
    written = [c for c in cells if c is not None]
    assert len(written) == 3
    assert {len(c.encode("utf-8")) for c in written} == {width}
    assert cells[2] is None


@pytest.mark.parametrize(
    "config",
    [(), (("redact_with", "XX"),), (("redact_with", "é"),)],
    ids=["default", "ascii", "two-byte-char"],
)
def test_redact_declares_the_width_it_writes(config: tuple[tuple[str, Any], ...]) -> None:
    cells, seed = _run("redact", config)
    width = RedactHandler().output_string_width(seed.provider_config)
    written = [c for c in cells if c is not None]
    assert len(written) == 3
    assert {len(c.encode("utf-8")) for c in written} == {width}
    assert cells[2] is None


def test_redact_declares_nothing_for_a_value_that_is_not_text() -> None:
    assert RedactHandler().output_string_width((("redact_with", 5),)) is None


def test_the_hash_width_is_capped_at_the_digest_length() -> None:
    assert HashStrategyHandler().output_string_width((("truncate", 100),)) == 64
    assert HashStrategyHandler().output_string_width((("truncate", 12),)) == 12


def test_passthrough_returns_the_frame_unchanged_and_says_so() -> None:
    cells, _ = _run("passthrough", ())
    assert cells == [7, 123456789, None, 42]
    assert PassthroughHandler.output_is_input is True


def test_no_other_handler_declares_an_output_without_a_parity_case() -> None:
    covered = {"hash": "output_string_width", "redact": "output_string_width"}
    for name, handler in SCALAR_HANDLERS.items():
        declares_input = getattr(handler, "output_is_input", False)
        declares_width = hasattr(handler, "output_string_width")
        if name == "passthrough":
            assert declares_input and not declares_width
        elif name in covered:
            assert declares_width and not declares_input
        else:
            assert not declares_input and not declares_width, name


@pytest.mark.parametrize("module", ["_lifecycle.py", "_lifecycle_inputs.py"])
def test_the_lifecycle_modules_hold_no_strategy_name(module: str) -> None:
    tree = ast.parse((_SRC / module).read_text())
    literals = {
        n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
    }
    assert literals.isdisjoint(SCALAR_HANDLERS), sorted(literals & set(SCALAR_HANDLERS))
