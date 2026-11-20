"""AT-C0: the canary finder sees every carrier, including ones absent from the raw bytes."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from tests.security import _metadata_canary as mc


def _cols() -> dict[str, pa.Array]:
    return {"a": pa.array(["x", "y"]), "n": pa.array([1, 2], pa.int64())}


def test_finds_every_table_level_canary(tmp_path: Path) -> None:
    path = tmp_path / "t.parquet"
    pq.write_table(mc.canary_table(_cols()), path)
    found = mc.canaries_in(path)
    assert {
        mc.SCHEMA,
        mc.ATTRS,
        mc.FIELD,
        mc.COLIDX,
        mc.RIDX,
        mc.SKEY,
        mc.FKEY,
        mc.CREATOR,
        mc.PDVER,
        mc.PANDAS_ATTRS,
    } <= found


def test_field_canary_is_absent_from_raw_bytes_but_found(tmp_path: Path) -> None:
    schema = pa.schema([pa.field("a", pa.string(), metadata={b"k": mc.FIELD.encode()})])
    path = tmp_path / "f.parquet"
    pq.write_table(pa.table({"a": ["x"]}, schema=schema), path)
    assert mc.FIELD.encode() not in path.read_bytes(), "base64 hides the field canary"
    assert mc.canaries_in(path) == {mc.FIELD}


def test_nested_child_canary_found(tmp_path: Path) -> None:
    child = pa.field("c", pa.string(), metadata={b"k": mc.NESTED.encode()})
    typ = pa.struct([child])
    path = tmp_path / "n.parquet"
    pq.write_table(pa.table({"s": pa.array([{"c": "v"}], typ)}), path)
    assert mc.canaries_in(path) == {mc.NESTED}


def test_extension_canary_found(tmp_path: Path) -> None:
    table = mc.canary_table(_cols(), field_meta_on=(), extension_column="a")
    path = tmp_path / "e.parquet"
    pq.write_table(table, path)
    assert mc.EXT in mc.canaries_in(path)


def test_clean_file_has_no_canary(tmp_path: Path) -> None:
    path = tmp_path / "c.parquet"
    pq.write_table(pa.table(_cols()), path)
    assert mc.canaries_in(path) == set()


def test_pandas_attrs_footer_key_found_from_a_real_to_parquet(tmp_path: Path) -> None:
    frame = pd.DataFrame({"a": ["x"]})
    frame.attrs["note"] = "attrs-value"
    path = tmp_path / "attrs.parquet"
    frame.to_parquet(path)
    assert b"PANDAS_ATTRS" in pq.ParquetFile(path).metadata.metadata
    assert mc.canaries_in(path) == {mc.PANDAS_ATTRS}


def test_dictionary_value_child_is_walked() -> None:
    """Parquet refuses a nested dictionary value, so this is a schema-level guard."""
    child = pa.field("c", pa.string(), metadata={b"k": mc.NESTED.encode()})
    schema = pa.schema([pa.field("d", pa.dictionary(pa.int8(), pa.struct([child])))])
    assert mc.NESTED.encode() in mc.schema_texts(schema)


def test_a_file_the_receipt_does_not_bind_is_refused(tmp_path: Path) -> None:
    import uuid

    import pytest

    from decoy_engine import fileaccess
    from decoy_engine.fileaccess import FileRequest, FileRole
    from decoy_engine.publication import PublicationRequest
    from decoy_engine.publication._publish import publish_tables

    out = fileaccess.capture().output_dir(
        FileRequest(FileRole.TARGET_OUTPUT, "write", str(tmp_path / "pub"), "targets.path")
    )
    receipt = publish_tables(
        out, {"t": pa.table(_cols())}, PublicationRequest(uuid.uuid4().hex), suffix=".parquet"
    )
    published = tmp_path / "pub" / "t.parquet"
    mc.assert_bound_by_receipt([published], receipt)
    elsewhere = tmp_path / "other.parquet"
    pq.write_table(pa.table({"a": ["z"], "n": [9]}), elsewhere)
    with pytest.raises(AssertionError, match="not an artifact"):
        mc.assert_bound_by_receipt([elsewhere], receipt)
    with pytest.raises(AssertionError, match="no published receipt"):
        mc.assert_bound_by_receipt([published], None)
