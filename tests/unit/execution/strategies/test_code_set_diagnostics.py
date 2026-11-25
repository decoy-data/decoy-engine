"""code_set review fixes: the mode is validated before any dispatch, and corpus diagnostics
never carry URL credentials (userinfo or query tokens)."""

from __future__ import annotations

import pathlib
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from decoy_engine.execution._strategies._code_set import CodeSetHandler
from decoy_engine.transforms.code_set import CodeSetConfig, apply_code_set
from tests._code_set_memo import make_ctx, make_seed

_PW = "ZQX-PASSWORD-7731"
_TOK = "ZQX-TOKEN-5519"
_URL = f"https://svc:{_PW}@host.example/corpus?token={_TOK}"


def _corpus(tmp_path: pathlib.Path) -> str:
    path = tmp_path / "ab.parquet"
    pq.write_table(
        pa.table(
            {
                "code": pa.array(["A01", "A02", "B01", "B02"], type=pa.string()),
                "chapter": pa.array(["A", "A", "B", "B"], type=pa.string()),
            }
        ),
        str(path),
    )
    return f"customer:{path}"


@pytest.mark.parametrize("chapter_preserve", [True, False])
def test_invalid_mode_is_refused_before_dispatch(
    tmp_path: pathlib.Path, chapter_preserve: bool
) -> None:
    cfg: dict[str, Any] = {
        "code_set": "ab",
        "mode": "maks",
        "chapter_preserve": chapter_preserve,
        "corpus_source": _corpus(tmp_path),
    }
    df = pd.DataFrame({"c": pd.Series(["A01"], dtype=object)})
    with pytest.raises(ValueError, match="unsupported mode"):
        CodeSetHandler().run(df, "c", make_seed(cfg), make_ctx())
    with pytest.raises(ValueError, match="unsupported mode"):
        apply_code_set(
            "A01",
            CodeSetConfig.from_dict(cfg),
            mode="maks",
            job_seed=b"k" * 8,
            namespace="cs",
        )


def test_version_pin_mismatch_hides_url_credentials(tmp_path: pathlib.Path) -> None:
    cfg = {
        "code_set": _URL,
        "mode": "mask",
        "chapter_preserve": False,
        "corpus_source": _corpus(tmp_path),
        "corpus_source_version": "9999",
    }
    df = pd.DataFrame({"c": pd.Series(["A01"], dtype=object)})
    with pytest.raises(Exception) as info:
        CodeSetHandler().run(df, "c", make_seed(cfg), make_ctx())
    assert getattr(info.value, "code", None) == "code_set_corpus_version_mismatch"
    text = str(info.value)
    assert _PW not in text
    assert _TOK not in text


def test_missing_url_source_hides_credentials() -> None:
    cfg = {
        "code_set": "ab",
        "mode": "mask",
        "chapter_preserve": False,
        "corpus_source": f"customer:s3://svc:{_PW}@bucket/key.parquet?token={_TOK}",
    }
    df = pd.DataFrame({"c": pd.Series(["A01"], dtype=object)})
    with pytest.raises(Exception) as info:
        CodeSetHandler().run(df, "c", make_seed(cfg), make_ctx())
    assert getattr(info.value, "code", None) == "code_set_corpus_path_not_found"
    text = str(info.value)
    assert _PW not in text
    assert _TOK not in text
