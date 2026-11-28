"""GEN-STREAM-ALL S1a A2: the take path and the moved batch assembler change no output byte.

The digests were captured at engine `origin/main` `9f7bb1f4a`, before `pool_take` and
`generation/stream/_batches.py` existed, for each legacy pooled type at 120,000 rows with
`null_probability: 0.1`: the Arrow IPC stream of the resident table (every buffer, including
the bytes under null slots) and the Parquet file the bounded sink commits.
"""

from __future__ import annotations

import ast
import hashlib
import importlib
from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest

import decoy_engine
from decoy_engine.generation import _faker_pool, _streamed
from tests.parity import _f0_fixtures as fx
from tests.parity._fr0_support import run_resident, run_streamed
from tests.unit.generation.stream._support import LEGACY_TEN, faker_config, ipc_bytes

MAIN_IPC_DIGESTS = {
    "first_name": "a901f04459da4eadeb7fdf262cdf3df134667e59a2bf5fd1f72b06ff8a6765e9",
    "last_name": "e544bda354662c917cffc372f0ed09225c2ad2c43347d8454511823df908f610",
    "name": "1504f1879a28f676fd074a0854b8decfd169aac34f4b118fb07884431b22e33f",
    "prefix": "ffd48aa3aa2eed3f2ea1ebe2d65826c7dd7924df71a955ca959ba8ad435e2c7e",
    "suffix": "e4d110583f389bd253255b49a45d9157e4f88f8e079c8eb27399e057bb05667b",
    "city": "15c5bcdd640af1303e3cdcc417ac21f58723f87ff005e03ec9ff48059b27e239",
    "state": "d05764069002aafb56cc6e11403960729beebcae290a145e7abb03d93adb4516",
    "country": "44e85b4bdf8ac97b6e85e2b6d68f00790ae484aacb8905aeb93453140209c1b5",
    "job": "d201fc26f3cccc88883d2c3a78159f364226ce52e3a282c123051745ae8912a9",
    "company": "16b6d1a12105e05334ce2b16ccacc153558f5db1cba6c8c737432be73e20e9e8",
}
MAIN_PARQUET_DIGESTS = {
    "company": "4f769961da88437c828bc247d501840dc8eed7a4d32dc27152fe421afba6327d",
    "first_name": "68b7617d1daf8fc3ddf4bc852e172aba259aefc3c124a53ca555bb6de94cedb4",
    "state": "415d56c1427b30e60eedb5e53dc66d7ec326a3d9318f4150c687f0eec33b47f6",
}
_ROWS = 120_000


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_every_legacy_type_has_a_captured_digest() -> None:
    assert set(MAIN_IPC_DIGESTS) == set(LEGACY_TEN)


@pytest.mark.parametrize("faker_type", LEGACY_TEN)
def test_resident_ipc_buffers_equal_the_pre_take_digest(faker_type: str) -> None:
    cfg = faker_config(faker_type, _ROWS, null_probability=0.1)
    table = run_resident(cfg, batch_rows=4096)["t"]
    assert _sha(ipc_bytes(table)) == MAIN_IPC_DIGESTS[faker_type]


@pytest.mark.parametrize("faker_type", sorted(MAIN_PARQUET_DIGESTS))
def test_sink_parquet_and_ipc_bytes_equal_the_pre_take_digest(
    faker_type: str, tmp_path: Path
) -> None:
    cfg = faker_config(faker_type, _ROWS, null_probability=0.1)
    _, tables = run_streamed(cfg, tmp_path)
    assert _sha((tmp_path / "t.parquet").read_bytes()) == MAIN_PARQUET_DIGESTS[faker_type]
    assert _sha(ipc_bytes(tables["t"])) == MAIN_IPC_DIGESTS[faker_type]


@pytest.mark.parametrize("null_probability", [0.1, 0.5, 1.0])
def test_a_null_slot_holds_no_value_bytes(null_probability: float) -> None:
    """The masked Arrow column has the buffers of the same values built from a list."""
    cfg = faker_config("city", _ROWS, null_probability=null_probability)
    column = run_resident(cfg, batch_rows=4096)["t"].column("v")
    rebuilt = pa.chunked_array(
        [pa.array(chunk.to_pylist(), type=chunk.type) for chunk in column.chunks], type=column.type
    )
    as_table = pa.table({"v": column})
    assert ipc_bytes(as_table) == ipc_bytes(pa.table({"v": rebuilt}))


def test_the_assembler_lives_in_the_stream_package() -> None:
    batches = importlib.import_module("decoy_engine.generation.stream._batches")
    assert callable(getattr(batches, "table_batches", None))
    assert callable(getattr(batches, "check_width", None))
    assert not hasattr(_streamed, "_table_batches")
    assert not hasattr(_streamed, "_check_width")


def _count(monkeypatch: pytest.MonkeyPatch, name: str) -> list[int]:
    calls: list[int] = []
    real = getattr(_faker_pool.PooledSelector, name)

    def spy(self: Any, size: int) -> Any:
        calls.append(size)
        return real(self, size)

    monkeypatch.setattr(_faker_pool.PooledSelector, name, spy)
    return calls


def test_a_plain_pooled_column_reaches_the_batch_as_an_arrow_array_with_no_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    takes = _count(monkeypatch, "take")
    selects = _count(monkeypatch, "select")
    run_resident(faker_config("city", _ROWS), batch_rows=40_000)
    assert sum(takes) == _ROWS
    assert selects == []


def test_a_collected_key_column_still_hands_the_batch_a_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A referenced parent column feeds a key collector, which reads Python values."""
    selects = _count(monkeypatch, "select")
    parent = fx.table("parent", _ROWS, [{"name": "k", "type": "faker", "faker_type": "city"}])
    child = fx.table(
        "child",
        10,
        [
            {
                "name": "pk",
                "type": "reference",
                "reference_table": "parent",
                "reference_column": "k",
            }
        ],
    )
    run_resident(fx.config([parent, child]), batch_rows=40_000)
    assert sum(selects) == _ROWS


def test_the_declared_width_bound_is_enforced_on_the_arrow_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pool value over the `city` cap (256 bytes) is caught when the batch is assembled, and
    the message names the column, never the value."""
    from decoy_engine.generation._budget_ledger import GenerationBudgetExceeded
    from decoy_engine.generation._streamed import run_generation
    from tests.parity._fr0_support import prepared_config

    real = _faker_pool.build_pool_values

    def wide(*args: Any, **kwargs: Any) -> Any:
        values, exact, custom = real(*args, **kwargs)
        return ["w" * 400, *values[1:]], exact, custom

    monkeypatch.setattr(_faker_pool, "build_pool_values", wide)
    selects = _count(monkeypatch, "select")
    config = prepared_config(faker_config("city", _ROWS))
    with pytest.raises(GenerationBudgetExceeded) as err:
        run_generation(config, budget_bytes=1 << 30, batch_rows=40_000)
    assert err.value.code == "value_exceeds_declared_bound"
    assert "wwww" not in str(err.value)
    assert selects == []


def _module_path(src: Path, module: str) -> Path | None:
    base = src.joinpath(*module.split("."))
    for candidate in (base / "__init__.py", base.with_suffix(".py")):
        if candidate.is_file():
            return candidate
    return None


def _module_level_imports(src: Path, module: str) -> set[str]:
    """Engine modules `module` imports when it loads: not under TYPE_CHECKING, not in a function."""
    path = _module_path(src, module)
    if path is None:
        return set()
    package = module if path.name == "__init__.py" else module.rpartition(".")[0]
    found: set[str] = set()

    def visit(body: list[ast.stmt]) -> None:
        for node in body:
            if isinstance(node, ast.If):
                if "TYPE_CHECKING" not in ast.unparse(node.test):
                    visit(node.body)
                visit(node.orelse)
            elif isinstance(node, ast.Try):
                for block in (node.body, node.orelse, node.finalbody):
                    visit(block)
                for handler in node.handlers:
                    visit(handler.body)
            elif isinstance(node, ast.Import):
                found.update(a.name for a in node.names if a.name.startswith("decoy_engine"))
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level:
                    parts = package.split(".")[: len(package.split(".")) - node.level + 1]
                    base = ".".join([*parts, base] if base else parts)
                if base.startswith("decoy_engine"):
                    for alias in node.names:
                        sub = f"{base}.{alias.name}"
                        found.add(sub if _module_path(src, sub) else base)

    visit(ast.parse(path.read_text(encoding="utf-8")).body)
    return found


def test_the_stream_package_has_no_import_cycle() -> None:
    """`stream` loads `_batches` lazily: `_batches` imports `_column_streams`, which imports
    `stream`. A runtime import passes even with the eager import, since Python hands back the
    partly built module, so this reads the module-level imports instead."""
    src = Path(decoy_engine.__file__).parents[1]
    start = "decoy_engine.generation.stream"
    seen: set[str] = set()
    pending = [(name, [start, name]) for name in _module_level_imports(src, start)]
    while pending:
        module, chain = pending.pop()
        assert module != start, " -> ".join(chain)
        if module not in seen:
            seen.add(module)
            pending += [(n, [*chain, n]) for n in _module_level_imports(src, module)]
    assert "decoy_engine.generation.stream._siblings" in seen
