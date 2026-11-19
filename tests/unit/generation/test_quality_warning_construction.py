"""A `QualityWarning` is built evidence-ready: scalar detail, a named provider.

`EvidencePayload` refuses a warning whose `detail` holds a list, a dict or any non-scalar, or whose
`provider` is empty. The constructor now refuses them too, so a producer that drifts fails where
it builds the warning, not later in the CLI's evidence record. The type annotation is narrowed the
same way so mypy flags the producer first.
"""

from __future__ import annotations

import typing
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

import pytest

from decoy_engine.config._tables import ColumnConfig
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


@pytest.mark.parametrize(
    "value", [[1], ("a", 2), {"a": 1}, {"a"}, b"x", object(), [["a"]], [{"a": "b"}]]
)
def test_non_scalar_detail_is_refused(value: Any) -> None:
    with pytest.raises(TypeError) as caught:
        QualityWarning(code="c", provider="p", detail={"k": value})
    assert "k" in str(caught.value)  # names the key, never the value


def test_non_string_detail_key_is_refused() -> None:
    with pytest.raises(TypeError):
        QualityWarning(code="c", provider="p", detail={1: "x"})  # type: ignore[dict-item]


def test_the_refusal_never_echoes_the_value() -> None:
    with pytest.raises(TypeError) as caught:
        QualityWarning(code="c", provider="p", detail={"k": [["SECRET-VALUE"]]})
    assert "SECRET-VALUE" not in str(caught.value)


@pytest.mark.parametrize("provider", ["", None])
def test_empty_provider_is_refused(provider: Any) -> None:
    with pytest.raises(ValueError):
        QualityWarning(code="c", provider=provider)


def test_empty_column_is_refused_but_none_is_allowed() -> None:
    QualityWarning(code="c", provider="p", column=None)
    with pytest.raises(ValueError):
        QualityWarning(code="c", provider="p", column="")


_BAD_NAMES = [5, b"x", 1.5]


@pytest.mark.parametrize("bad", _BAD_NAMES)
def test_code_provider_and_column_must_be_plain_names(bad: Any) -> None:
    """A name is a non-empty str; a non-str is refused."""
    with pytest.raises(ValueError):
        QualityWarning(code=bad, provider="p")
    with pytest.raises(ValueError):
        QualityWarning(code="c", provider=bad)
    with pytest.raises(ValueError):
        QualityWarning(code="c", provider="p", column=bad)


@pytest.mark.parametrize("name", ["p" * 257, "é" * 5000, "a\x1fb", "a\nb", "nul\x00", "del\x7f"])
def test_every_name_the_config_admits_is_accepted(name: str) -> None:
    """The config admits any str as a column name, so the warning must build for it."""
    ColumnConfig(name=name, strategy="s")
    warning = QualityWarning(code="c", provider=name, column=name)
    assert warning.column == name


def test_the_refusal_names_no_value() -> None:
    with pytest.raises(ValueError) as caught:
        QualityWarning(code="c", provider=5, column="SECRET-VALUE")  # type: ignore[arg-type]
    assert "SECRET" not in str(caught.value)


@pytest.mark.parametrize(
    ("given", "stored"),
    [(["a", "b"], "a, b"), (("a",), "a"), ([], ""), (["x, y", "z"], "x, y, z")],
)
def test_a_list_of_names_is_joined_in_one_place(given: Any, stored: str) -> None:
    warning = QualityWarning(code="c", provider="p", detail={"names": given})
    assert warning.detail == {"names": stored}


def test_the_caller_dict_is_not_mutated() -> None:
    detail: dict[str, Any] = {"names": ["a", "b"]}
    QualityWarning(code="c", provider="p", detail=detail)
    assert detail == {"names": ["a", "b"]}


def test_detail_annotation_admits_scalars_and_name_lists_only() -> None:
    hints = typing.get_type_hints(QualityWarning)
    scalar = str | int | float | bool | None
    assert hints["detail"] == Mapping[str, scalar | list[str] | tuple[str, ...]]


def test_text_mask_sub_floor_warning_is_evidence_ready() -> None:
    warning = text_mask_sub_floor_warning({"us_zip": 3, "ssn": 1}, policy="mask", column="notes")
    assert warning.detail["total"] == 4
    assert warning.detail["by_detector"] == "ssn=1, us_zip=3"
    _accepted(warning)


def test_undeclared_output_columns_producer_is_evidence_ready() -> None:
    """The real `_output_projection` producer under the warn policy, end to end."""
    from types import SimpleNamespace

    from decoy_engine.execution._output_projection import enforce_output_projection

    seed = SimpleNamespace(per_column=(("kept", None),), per_group=())
    plan: Any = SimpleNamespace(seed_envelope=SimpleNamespace(per_table=(("t", seed),)))
    (warning,) = enforce_output_projection("t", ["kept", "zeta", "alpha"], plan, "warn")
    assert warning.code == "undeclared_output_columns"
    assert warning.detail == {"table": "t", "undeclared_columns": "alpha, zeta"}
    _accepted(warning)
