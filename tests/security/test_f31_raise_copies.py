"""F31 AE5: an engine raise never copies the text of the exception it wraps.

Each case plants a canary where a library or engine exception would quote it, triggers one
rewritten raise site, and checks the re-raised exception: the class and reason code stay, and the
canary is in neither ``str()`` nor ``args``. The census half of the rule (no audit-bucket copy with
a ``raise`` sink) is ``tests/sentry/safe_output/test_exception_text_copy.py``.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pyarrow as pa
import pytest

from decoy_engine import reasons
from decoy_engine.detection.name_hints.loader import NameHintLoaderError, load_name_hint_terms
from decoy_engine.errors import ValidationError
from decoy_engine.execution._errors import ExecutionError, StrategyError
from decoy_engine.execution._strategies._bucket_perturb import _validated_config
from decoy_engine.execution.native._chunked_schema_rule import _safe_cast
from decoy_engine.expressions._lark_parser import compile_expr

CANARY = "DECOY_CANARY_F31_7Q4Z"


def _assert_value_free(exc: BaseException) -> None:
    assert CANARY not in str(exc)
    assert all(CANARY not in repr(a) for a in exc.args)


def test_chunked_cast_names_the_types_not_the_cell() -> None:
    column = pa.chunked_array([[CANARY]])
    with pytest.raises(ExecutionError) as info:
        _safe_cast(column, pa.int64(), table="t", name="c", chunk_index=0)
    assert info.value.code == reasons.runtime.CHUNKED_SCHEMA_MISMATCH
    assert "cannot be converted without loss" in str(info.value)
    _assert_value_free(info.value)


def test_bad_string_escape_gives_a_position_not_the_literal() -> None:
    with pytest.raises(ValidationError) as info:
        compile_expr(f'"\\xZZ{CANARY}"')
    assert "invalid string escape sequence" in str(info.value)
    _assert_value_free(info.value)


def test_parse_failure_does_not_echo_the_expression() -> None:
    with pytest.raises(ValidationError) as info:
        compile_expr(f"{CANARY} ++ 1 $$")
    assert "unsupported expression" in str(info.value)
    _assert_value_free(info.value)


def test_bucket_perturb_invalid_bucket_is_a_fixed_refusal() -> None:
    plan = SimpleNamespace(provider_config={"bucket": CANARY})
    with pytest.raises(StrategyError) as info:
        _validated_config(plan)  # type: ignore[arg-type]
    assert info.value.code == reasons.runtime.BUCKET_PERTURB_INVALID_CONFIG
    _assert_value_free(info.value)


def test_name_hint_yaml_error_drops_the_undefined_alias_name(tmp_path: Path) -> None:
    (tmp_path / "manifest.yaml").write_text(f"files:\n  - *{CANARY}\n", encoding="utf-8")
    with pytest.raises(NameHintLoaderError) as info:
        load_name_hint_terms(tmp_path)
    assert "could not parse" in str(info.value)
    _assert_value_free(info.value)
