"""A `QualityWarning` is built evidence-ready: scalar detail, a named provider.

`EvidencePayload` refuses a warning whose `detail` holds a list, a dict or any non-scalar, or whose
`provider` is empty. The constructor now refuses them too, so a producer that drifts fails where
it builds the warning, not later in the CLI's evidence record. The type annotation is narrowed the
same way so mypy flags the producer first.
"""

from __future__ import annotations

import typing
from copy import deepcopy
from typing import Any

import pytest

from decoy_engine.execution.native._text_mask_route import text_mask_sub_floor_warning
from decoy_engine.generation.pool._events import QualityWarning
from tests.unit.records._helpers import corpus, make


def _accepted(warning: QualityWarning) -> None:
    manifest = deepcopy(corpus("evidence-cli-local-1.json"))
    manifest["warnings"] = [
        {
            "code": warning.code,
            "provider": warning.provider,
            "column": warning.column,
            "detail": dict(warning.detail),
        }
    ]
    make("evidence", manifest, labels={})  # raises RecordError when the model refuses


@pytest.mark.parametrize("value", ["s", 1, 1.5, True, None])
def test_scalar_detail_is_accepted(value: Any) -> None:
    QualityWarning(code="c", provider="p", column="col", detail={"k": value})


@pytest.mark.parametrize("value", [["a"], ("a",), {"a": 1}, {"a"}, b"x", object()])
def test_non_scalar_detail_is_refused(value: Any) -> None:
    with pytest.raises(TypeError) as caught:
        QualityWarning(code="c", provider="p", detail={"k": value})
    assert "k" in str(caught.value)  # names the key, never the value


def test_non_string_detail_key_is_refused() -> None:
    with pytest.raises(TypeError):
        QualityWarning(code="c", provider="p", detail={1: "x"})  # type: ignore[dict-item]


def test_the_refusal_never_echoes_the_value() -> None:
    with pytest.raises(TypeError) as caught:
        QualityWarning(code="c", provider="p", detail={"k": ["SECRET-VALUE"]})
    assert "SECRET-VALUE" not in str(caught.value)


@pytest.mark.parametrize("provider", ["", None])
def test_empty_provider_is_refused(provider: Any) -> None:
    with pytest.raises(ValueError):
        QualityWarning(code="c", provider=provider)


def test_empty_column_is_refused_but_none_is_allowed() -> None:
    QualityWarning(code="c", provider="p", column=None)
    with pytest.raises(ValueError):
        QualityWarning(code="c", provider="p", column="")


def test_detail_annotation_is_the_scalar_union() -> None:
    hints = typing.get_type_hints(QualityWarning)
    assert hints["detail"] == dict[str, str | int | float | bool | None]


def test_text_mask_sub_floor_warning_is_evidence_ready() -> None:
    warning = text_mask_sub_floor_warning({"us_zip": 3, "ssn": 1}, policy="mask", column="notes")
    assert warning.detail["total"] == 4
    assert warning.detail["by_detector"] == "ssn=1, us_zip=3"
    _accepted(warning)
