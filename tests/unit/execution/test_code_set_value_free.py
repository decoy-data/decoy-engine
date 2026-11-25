"""Value-free fatal errors for the code_set handler (CODE-SET S1 review round 1).

Every job-fatal error raised through the public handler must carry its field name and reason
code but no configured or input value. Each test plants a distinctive canary where the value
would be rendered and asserts it is absent from ``str(exc)``, ``exc.args`` and all log records.
"""

from __future__ import annotations

import logging
import pathlib
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from decoy_engine.execution._adapter import StrategyContext
from decoy_engine.execution._strategies._code_set import CodeSetHandler
from decoy_engine.generation.pool._cache import PoolCache
from decoy_engine.plan._errors import PlanCompileError
from decoy_engine.plan._types import ColumnSeed
from decoy_engine.relationships._graph import RelationshipGraph
from decoy_engine.relationships._namespace import NamespaceRegistry
from decoy_engine.transforms.code_set import CodeSetConfig, apply_code_set, resolve_corpus_record

_CANARY = "ZQX-CANARY-9931"


def _ctx() -> StrategyContext:
    return StrategyContext(
        registry=None,  # type: ignore[arg-type]
        pool_cache=PoolCache(),
        relationship_graph=RelationshipGraph(edges=(), ordering=()),
        namespace_registry=NamespaceRegistry(bindings=()),
        job_seed=(0x77).to_bytes(8, "big"),
    )


def _plan(cfg: dict[str, Any]) -> ColumnSeed:
    return ColumnSeed(
        namespace="cs",
        strategy="code_set",
        provider="code_set",
        backend_type="faker",
        backend_version="v",
        cardinality_mode="reuse",
        deterministic=False,
        provider_config=tuple(cfg.items()),
        coherent_with=(),
    )


def _corpus(tmp_path: pathlib.Path, codes: list[str], chapters: list[str]) -> str:
    path = tmp_path / "c.parquet"
    pq.write_table(
        pa.table(
            {
                "code": pa.array(codes, type=pa.string()),
                "chapter": pa.array(chapters, type=pa.string()),
            }
        ),
        str(path),
    )
    return f"customer:{path}"


def _assert_value_free(exc: BaseException, caplog: pytest.LogCaptureFixture, code: str) -> None:
    assert getattr(exc, "code", None) == code
    assert _CANARY not in str(exc)
    assert all(_CANARY not in repr(a) for a in exc.args)
    assert all(_CANARY not in r.getMessage() for r in caplog.records)


def _run_expect_raise(
    cfg: dict[str, Any], values: list[str], caplog: pytest.LogCaptureFixture
) -> BaseException:
    df = pd.DataFrame({"c": pd.Series(values, dtype=object)})
    with caplog.at_level(logging.DEBUG), pytest.raises(Exception) as info:
        CodeSetHandler().run(df, "c", _plan(cfg), _ctx())
    return info.value


def test_single_row_corpus_error_is_value_free(
    tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture
) -> None:
    cfg = {
        "code_set": "one",
        "mode": "mask",
        "chapter_preserve": False,
        "corpus_source": _corpus(tmp_path, [_CANARY], ["A"]),
    }
    exc = _run_expect_raise(cfg, [_CANARY], caplog)
    _assert_value_free(exc, caplog, "code_set_single_row_corpus")


def _scalar_error(cfg: dict[str, Any], value: str) -> PlanCompileError:
    """Per-value codes are recorded as row errors by the handler, but the scalar public entry
    point raises them with a message a caller may print."""
    code_cfg = CodeSetConfig.from_dict(cfg)
    record = resolve_corpus_record(code_cfg)
    with pytest.raises(PlanCompileError) as info:
        apply_code_set(value, code_cfg, mode="mask", job_seed=b"k" * 8, corpus_record=record)
    return info.value


def test_sole_member_bucket_error_is_value_free(
    tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture
) -> None:
    cfg = {
        "code_set": "ab",
        "mode": "mask",
        "chapter_preserve": True,
        "corpus_source": _corpus(tmp_path, ["A01", "A02", _CANARY], ["A", "A", "Q"]),
    }
    exc = _scalar_error(cfg, _CANARY)
    _assert_value_free(exc, caplog, "code_set_sole_member_bucket")


def test_chapter_absent_error_is_value_free(
    tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture
) -> None:
    cfg = {
        "code_set": "ab",
        "mode": "mask",
        "chapter_preserve": True,
        "corpus_source": _corpus(tmp_path, ["A01", "A02"], ["A", "A"]),
    }
    exc = _scalar_error(cfg, _CANARY)
    _assert_value_free(exc, caplog, "code_set_chapter_absent")


def test_version_pin_mismatch_is_value_free(
    tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture
) -> None:
    cfg = {
        "code_set": "ab",
        "mode": "mask",
        "corpus_source_version": _CANARY,
        "corpus_source": _corpus(tmp_path, ["A01", "A02"], ["A", "A"]),
    }
    exc = _run_expect_raise(cfg, ["A01"], caplog)
    _assert_value_free(exc, caplog, "code_set_corpus_version_mismatch")


def test_list_valued_version_pin_is_value_free(
    tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture
) -> None:
    cfg = {
        "code_set": "ab",
        "mode": "mask",
        "corpus_source_version": [_CANARY],
        "corpus_source": _corpus(tmp_path, ["A01", "A02"], ["A", "A"]),
    }
    exc = _run_expect_raise(cfg, ["A01"], caplog)
    _assert_value_free(exc, caplog, "code_set_corpus_source_version_invalid")


def test_unsupported_mode_is_value_free(
    tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture
) -> None:
    cfg = {
        "code_set": "ab",
        "mode": _CANARY,
        "corpus_source": _corpus(tmp_path, ["A01", "A02"], ["A", "A"]),
    }
    exc = _run_expect_raise(cfg, ["A01"], caplog)
    assert _CANARY not in str(exc)
    assert all(_CANARY not in repr(a) for a in exc.args)
    assert all(_CANARY not in r.getMessage() for r in caplog.records)
