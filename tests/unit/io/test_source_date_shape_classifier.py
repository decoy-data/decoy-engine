"""One admitted-date-shape classifier, and no unclassified layout passing as date-free
(DATE-RANGE-SENTINEL S5 remediation, design items)."""

from __future__ import annotations

from typing import Any

import pyarrow as pa
import pytest

from decoy_engine._arrow_types import (
    is_admitted_date_shape,
    is_date_dictionary,
    is_unclassified,
    type_nodes,
)
from decoy_engine.internal import pandas_compat
from decoy_engine.io import SourceDateTypeUnsupportedError, check_source_dates, source_dates
from decoy_engine.safe_output import _date_buffers, own_date_columns


class _Unknown:
    """A layout a later pyarrow could add: an id no predicate knows, no value type, no fields."""

    id = -999
    num_fields = 0


class _UnknownWithDate:
    id = -998
    num_fields = 1

    def field(self, i: int) -> Any:
        return pa.field("when", pa.date32())


_PASS_CONTROLS = [
    pa.time32("s"),
    pa.time64("us"),
    pa.duration("ms"),
    pa.month_day_nano_interval(),
    pa.decimal128(10, 2),
    pa.null(),
    pa.bool_(),
    pa.int64(),
    pa.float32(),
    pa.string(),
    pa.large_binary(),
    pa.binary(4),
]


def test_an_unknown_layout_is_unclassified_and_a_known_control_is_not() -> None:
    assert is_unclassified(_Unknown())  # type: ignore[arg-type]
    assert not any(is_unclassified(t) for t in _PASS_CONTROLS)
    assert not any(
        is_unclassified(t) for t in (pa.date32(), pa.timestamp("us"), pa.list_(pa.int8()))
    )


def test_an_unknown_layout_with_fields_is_walked_for_dates() -> None:
    nodes = list(type_nodes(_UnknownWithDate()))  # type: ignore[arg-type]
    assert any(pa.types.is_date32(n) for n in nodes)


def test_the_source_read_refuses_an_unclassified_layout_and_passes_the_controls() -> None:
    assert source_dates._holds_dates(_Unknown())  # type: ignore[arg-type]
    assert not any(source_dates._holds_dates(t) for t in _PASS_CONTROLS)
    for t in _PASS_CONTROLS:
        table = pa.table({"c": pa.nulls(2, t)}) if t != pa.null() else pa.table({"c": pa.nulls(2)})
        assert check_source_dates(table, table="t") is table


def test_the_classifier_names_a_plain_date_and_a_top_level_date_dictionary_only() -> None:
    day = pa.dictionary(pa.int8(), pa.date32())
    assert is_admitted_date_shape(pa.date32()) and is_admitted_date_shape(day)
    assert is_date_dictionary(day) and not is_date_dictionary(pa.date32())
    assert not is_admitted_date_shape(pa.dictionary(pa.int8(), pa.string()))
    assert not is_admitted_date_shape(pa.list_(pa.date32()))


def _dictionary_table(entries: list[Any]) -> pa.Table:
    column = pa.DictionaryArray.from_arrays(
        pa.array([0, 0], pa.int8()), pa.array(entries, pa.date32())
    )
    return pa.table({"d": column})


def test_the_read_asks_the_shared_classifier(monkeypatch: pytest.MonkeyPatch) -> None:
    table = _dictionary_table([0, 1])
    assert check_source_dates(table, table="t") is table
    monkeypatch.setattr(source_dates, "is_admitted_date_shape", lambda t: False)
    with pytest.raises(SourceDateTypeUnsupportedError):
        check_source_dates(table, table="t")


def test_the_output_ownership_asks_the_shared_classifier(monkeypatch: pytest.MonkeyPatch) -> None:
    table = _dictionary_table([0, 1])
    assert own_date_columns(table) is not table
    monkeypatch.setattr(_date_buffers, "is_admitted_date_shape", lambda t: False)
    assert own_date_columns(table) is table


def test_the_pandas_conversion_asks_the_shared_classifier(monkeypatch: pytest.MonkeyPatch) -> None:
    table = _dictionary_table([0, None, 1])
    assert str(pandas_compat.table_to_pandas(table)["d"].dtype) == "category"
    monkeypatch.setattr(pandas_compat, "is_date_dictionary", lambda t: False)
    with pytest.raises(ValueError, match="null"):  # pandas' own refusal of a null category
        pandas_compat.table_to_pandas(table)
