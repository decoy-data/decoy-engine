"""F02-E6: remote subset sources run against a caller-supplied local copy, and the new codes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from decoy_engine import errors, reasons
from decoy_engine.subset import subset_inputs_from_config
from decoy_engine.subset._errors import SubsetConfigError

_REMOTE = {
    "s3": {"type": "s3", "bucket": "secret-bucket", "key": "a/b.parquet", "format": "parquet"},
    "gcs": {"type": "gcs", "bucket": "secret-bucket", "key": "a/b.parquet", "format": "parquet"},
    "sftp": {
        "type": "sftp",
        "host": "secret-host.example",
        "path": "/a/b.parquet",
        "format": "parquet",
    },
}


def _config(src: dict[str, Any]) -> dict[str, Any]:
    return {
        "sources": {"t": src},
        "tables": [{"name": "t", "columns": [{"name": "x"}]}],
        "relationships": [],
        "subset": {
            "seeds": [{"table": "t", "mode": "keys", "key_columns": ["id"], "keys": [["b"]]}]
        },
    }


@pytest.mark.parametrize("kind", sorted(_REMOTE))
def test_remote_source_with_copy_becomes_local_path(kind: str, tmp_path: Path) -> None:
    copy = str(tmp_path / "t.parquet")
    sources, _rels, _seeds, _policy = subset_inputs_from_config(
        _config(_REMOTE[kind]), local_copies={"t": copy}
    )
    assert sources["t"].path == copy
    assert sources["t"].format == "parquet"


@pytest.mark.parametrize("kind", sorted(_REMOTE))
def test_remote_source_without_copy_is_refused_without_values(kind: str) -> None:
    for copies in (None, {}, {"other": "/x.parquet"}):
        with pytest.raises(SubsetConfigError) as ei:
            subset_inputs_from_config(_config(_REMOTE[kind]), local_copies=copies)
        assert ei.value.code == reasons.config.SUBSET_SOURCE_TYPE_UNSUPPORTED
        text = str(ei.value)
        for leak in ("secret-bucket", "secret-host", "a/b.parquet", kind):
            assert leak not in text.replace("subsetting only supports", "")


def test_file_source_ignores_copies() -> None:
    src = {"type": "file", "path": "/real/t.parquet", "format": "parquet"}
    sources, *_ = subset_inputs_from_config(_config(src), local_copies={"t": "/copy.parquet"})
    assert sources["t"].path == "/real/t.parquet"


def test_new_codes_are_registered_unreleased() -> None:
    for ns, code in (
        ("config", reasons.config.REMOTE_URI_INVALID),
        ("runtime", reasons.runtime.SPOOL_DISK_FULL),
        ("warning", reasons.warning.SFTP_LOCK_NOT_REMOVED),
    ):
        spec = reasons.get(ns, code)
        assert spec.since == reasons.UNRELEASED
    assert reasons.config.REMOTE_URI_INVALID == "remote_uri_invalid"
    assert reasons.runtime.SPOOL_DISK_FULL == "spool_disk_full"
    assert reasons.warning.SFTP_LOCK_NOT_REMOVED == "sftp_lock_not_removed"


def test_spool_disk_full_is_a_disk_exclusion_not_a_capacity_verdict() -> None:
    code = reasons.runtime.SPOOL_DISK_FULL
    assert errors.CAPACITY_EXCLUSIONS[code] == errors._DISK
    assert code not in errors.CAPACITY_REASON_CODES


def test_errors_module_stays_within_its_line_goal() -> None:
    lines = Path(errors.__file__).read_text(encoding="utf-8").count("\n")
    assert lines <= 600
