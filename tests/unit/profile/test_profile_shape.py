"""`ColumnProfile.shape`: in the hash, in the JSON, fail-closed on old or unknown tokens."""

from __future__ import annotations

import dataclasses
import json
import random

import pandas as pd
import pyarrow as pa
import pytest

from decoy_engine.contracts.column_shape import ColumnShape
from decoy_engine.profile import ColumnProfile, Profile, TableProfile, profile_hash
from decoy_engine.profile._serialize import profile_from_json, profile_to_json
from decoy_engine.profile._walk import walk_dataframe

S = ColumnShape


def _with_shape(profile: Profile, shape: ColumnShape) -> Profile:
    table = profile.tables[0]
    col = dataclasses.replace(table.columns[0], shape=shape)
    new_table = dataclasses.replace(table, columns=(col, *table.columns[1:]))
    return dataclasses.replace(profile, tables=(new_table, *profile.tables[1:]))


def test_default_shape_is_unknown(sample_column: ColumnProfile) -> None:
    assert sample_column.shape is S.UNKNOWN


def test_shape_in_profile_hash(sample_profile: Profile) -> None:
    # An Arrow date and a string both read as `object`, so dtype alone cannot tell them apart.
    as_text = _with_shape(sample_profile, S.TEXT)
    as_date = _with_shape(sample_profile, S.DATE)
    assert as_text.tables[0].columns[0].dtype == as_date.tables[0].columns[0].dtype
    assert profile_hash(as_text) != profile_hash(as_date)


def test_profile_round_trip_keeps_shape(sample_profile: Profile) -> None:
    profile = _with_shape(sample_profile, S.DECIMAL)
    loaded = profile_from_json(profile_to_json(profile))
    assert loaded == profile
    assert loaded.tables[0].columns[0].shape is S.DECIMAL
    assert profile_hash(loaded) == profile_hash(profile)


def test_old_profile_json_loads_shape_unknown(sample_profile: Profile) -> None:
    data = json.loads(profile_to_json(sample_profile))
    for table in data["tables"]:
        for col in table["columns"]:
            del col["shape"]
    loaded = profile_from_json(json.dumps(data))
    assert all(c.shape is S.UNKNOWN for t in loaded.tables for c in t.columns)


@pytest.mark.parametrize("token", ["bogus", "", 5, ["date"], None])
def test_unknown_stored_shape_refused(sample_profile: Profile, token: object) -> None:
    data = json.loads(profile_to_json(sample_profile))
    data["tables"][0]["columns"][0]["shape"] = token
    if token is None:
        # a null token is "absent": the same fail-closed default as a profile from before the field
        assert profile_from_json(json.dumps(data)).tables[0].columns[0].shape is S.UNKNOWN
        return
    with pytest.raises(ValueError, match="'shape'") as exc:
        profile_from_json(json.dumps(data))
    assert "bogus" not in str(exc.value)
    assert exc.value.__cause__ is None and exc.value.__context__ is None


def _walk(df: pd.DataFrame, schema: pa.Schema | None, fmt: str | None) -> TableProfile:
    return walk_dataframe(
        df,
        table_name="t",
        declared_pk_cols=frozenset(),
        fk_specs={},
        sample_rows=None,
        rng=random.Random(0),
        arrow_schema=schema,
        source_format=fmt,
    )


def test_walk_records_the_observed_shape() -> None:
    df = pd.DataFrame({"d": ["2024-01-01"], "s": ["x"], "n": [1]})
    schema = pa.schema([("d", pa.date32()), ("s", pa.string()), ("n", pa.int64())])
    shapes = {c.name: c.shape for c in _walk(df, schema, "parquet").columns}
    assert shapes == {"d": S.DATE, "s": S.TEXT, "n": S.INTEGER}


def test_walk_without_a_schema_is_unknown() -> None:
    df = pd.DataFrame({"n": [1]})
    assert _walk(df, None, None).columns[0].shape is S.UNKNOWN


def test_csv_format_is_text_even_when_the_reader_inferred_int() -> None:
    df = pd.DataFrame({"n": [1, 2]})
    schema = pa.schema([("n", pa.int64())])
    assert _walk(df, schema, "csv").columns[0].shape is S.TEXT
