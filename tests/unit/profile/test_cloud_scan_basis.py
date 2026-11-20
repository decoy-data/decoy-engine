"""AT-18: a scan of a wide cloud CSV reads the 10,000 rows it asked for and says it is a sample.

Before E0 the leading 1 MiB window gave about 3,500 rows, and the scan claimed keys from them.
"""

from __future__ import annotations

from typing import Any

from decoy_engine.profiling import scan_set_to_dict, scan_sources
from tests.unit.profile.test_sample_frame_contract import (  # noqa: F401
    BUCKET,
    MIB,
    Env,
    _csv_bytes,
    _gcs,
    env,
)


def _table(descriptor: dict[str, Any]) -> dict[str, Any]:
    scan = scan_sources({"t": descriptor})
    return scan_set_to_dict(scan, detail=False)["tables"][0]


def _check(table: dict[str, Any]) -> None:
    assert table["basis"] == "sample" and table["scanned_rows"] == 10_000
    assert table["row_count_exact"] is False and table["key_candidates"] == []


def test_a_wide_s3_csv_scans_ten_thousand_rows(env: Env) -> None:  # noqa: F811
    data = _csv_bytes(25_000)
    assert len(data) > 4 * MIB
    env.s3.put_object(Bucket=BUCKET, Key="k.csv", Body=data)
    _check(
        _table(
            {
                "type": "s3",
                "format": "csv",
                "bucket": BUCKET,
                "key": "k.csv",
                "region": "us-east-1",
            }
        )
    )


def test_a_wide_gcs_csv_scans_ten_thousand_rows(env: Env) -> None:  # noqa: F811
    data = _csv_bytes(25_000)
    assert len(data) > 4 * MIB
    _gcs(env, data)
    _check(_table({"type": "gcs", "format": "csv", "bucket": BUCKET, "object": "o"}))


def test_a_small_cloud_csv_is_a_whole_read(env: Env) -> None:  # noqa: F811
    env.s3.put_object(Bucket=BUCKET, Key="s.csv", Body=_csv_bytes(500))
    table = _table(
        {
            "type": "s3",
            "format": "csv",
            "bucket": BUCKET,
            "key": "s.csv",
            "region": "us-east-1",
        }
    )
    assert table["basis"] == "whole" and table["scanned_rows"] == 500
    assert table["row_count"] == 500 and table["row_count_exact"] is True
