from pathlib import Path

import pytest

from decoy_engine import fileaccess
from decoy_engine.fileaccess.adapters import arrow


def test_missing_staged_table_reports_the_path(tmp_path: Path) -> None:
    path = str(tmp_path / "missing.parquet")
    request = fileaccess.FileRequest(fileaccess.FileRole.TARGET_OUTPUT, "read", path, "output")
    with fileaccess.LocalFileAccess().open_read(request) as handle, pytest.raises(
        FileNotFoundError
    ) as error:
        arrow.read_staged_table(handle)
    assert str(error.value) == path
