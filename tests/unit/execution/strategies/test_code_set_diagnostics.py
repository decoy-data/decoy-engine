"""code_set review fixes: the mode is validated before any dispatch, and corpus diagnostics
never carry URL credentials (userinfo or query tokens)."""

from __future__ import annotations

import pathlib
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from decoy_engine._locator import locator_carries_credentials, without_url_credentials
from decoy_engine.execution._strategies._code_set import CodeSetHandler
from decoy_engine.transforms.code_set import CodeSetConfig, apply_code_set
from tests._code_set_memo import customer_corpus, make_ctx, make_seed

_PW = "ZQX-PASSWORD-7731"
_TOK = "ZQX-TOKEN-5519"
_URL = f"https://svc:{_PW}@host.example/corpus?token={_TOK}"


def _corpus(tmp_path: pathlib.Path) -> str:
    return customer_corpus(tmp_path, filename="ab.parquet")


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


@pytest.mark.parametrize(
    ("locator", "expected"),
    [
        ("https://svc:p@ss@host.example/c?token=T", "https://host.example/c?<redacted>"),
        ("https://host?email=x@y&token=T", "https://<redacted>"),
        ("https:\\\\svc:pw@host\\c\\f?token=T", "https://host/c/f?<redacted>"),
        ("s3:/u:p@h/k", "s3:/h/k"),
        ("https://h/p#access_token=T", "https://h/p#<redacted>"),
        ("/tmp/archive:/alice@local/file?rev=1", "/tmp/archive:/alice@local/file?rev=1"),
        ("C:\\data\\a@b.parquet", "C:\\data\\a@b.parquet"),
        ("\\\\server\\share\\a@b", "\\\\server\\share\\a@b"),
        ("  https://svc:pw@host/c?t=T", "  https://host/c?<redacted>"),
        ("failed at https://svc:pw@host/c?t=T now", "failed at https://<redacted>"),
        ("a/https://user:pw@host", "<redacted>"),
        ("https://svc:pa/ss@host/c?t=T", "https://<redacted>"),
        ("https://svc:p?w@host/c", "https://<redacted>"),
        ("https://svc:p#w@host/c", "https://<redacted>"),
        ("//svc:p@ss@host/c.parquet?t=T", "//host/c.parquet?<redacted>"),
        ("\\\\svc:pw@host\\c.parquet", "//host/c.parquet"),
        ("//server/share/a@b.parquet", "//server/share/a@b.parquet"),
        ("https:\\\\host\\c.parquet", "https://host/c.parquet"),
    ],
)
def test_url_redactor_shapes(locator: str, expected: str) -> None:
    assert without_url_credentials(locator) == expected


@pytest.mark.parametrize(
    "locator",
    [
        "https://svc:{pw}@host/c?token={tok}",
        "https://svc:pa/{pw}@host/c?token={tok}",
        "https://svc:pa?{pw}@host/c?token={tok}",
        "https://svc:pa#{pw}@host/c",
        "https://svc:pa@{pw}@host/c#{tok}",
        "  https://svc:{pw}@host/c?token={tok}",
        "cannot read https://svc:{pw}@host/c?token={tok} (denied)",
        "https:\\\\svc:{pw}@host\\c?token={tok}",
        "s3:/svc:{pw}@host/c?token={tok}",
        "s3://svc:pa {pw}@host/c?token={tok}",
        "https://host/c ?token={tok}",
        "https://svc:pa {pw}@host/c ?token={tok}",
    ],
)
def test_url_redactor_never_keeps_canaries(locator: str) -> None:
    out = without_url_credentials(locator.format(pw=_PW, tok=_TOK))
    assert _PW not in out
    assert _TOK not in out


@pytest.mark.parametrize(
    "locator",
    [
        "a/https://user:{pw}@host/c?token={tok}",
        "/srv/x-s3://user:{pw}@host/c",
        "a\\\\https:\\\\user:{pw}@host\\c",
        "prefix/https://host/c?token={tok}",
    ],
)
def test_url_after_a_path_separator_is_suppressed_whole(locator: str) -> None:
    out = without_url_credentials(locator.format(pw=_PW, tok=_TOK))
    assert _PW not in out
    assert _TOK not in out


def _no_secret(text: str) -> None:
    assert _PW not in text
    assert _TOK not in text


def test_verify_corpus_report_hides_url_credentials() -> None:
    from decoy_engine.transforms._codeset_loader import verify_corpus

    report = verify_corpus(pathlib.Path(f"https://svc:{_PW}@host.example/c.parquet?token={_TOK}"))
    assert not report.ok
    _no_secret(report.path)
    _no_secret(" ".join(report.problems))


def test_unreadable_parquet_error_names_type_not_text(tmp_path: pathlib.Path) -> None:
    from decoy_engine.transforms._codeset_loader import verify_corpus

    bad = tmp_path / "bad.parquet"
    bad.write_bytes(b"not parquet " + _PW.encode())
    report = verify_corpus(bad)
    assert not report.ok
    problems = " ".join(report.problems)
    assert "Arrow" in problems
    assert "Parquet magic" not in problems
    assert "__context__" not in problems


def test_unknown_shipped_name_hides_credentials() -> None:
    with pytest.raises(Exception) as info:
        CodeSetConfig.from_dict({"code_set": _URL})
    assert getattr(info.value, "code", None) == "code_set_corpus_not_found"
    _no_secret(str(info.value))


def test_partial_provenance_and_evidence_hide_credentials(tmp_path: pathlib.Path) -> None:
    from decoy_engine.transforms.code_set import describe_loaded_corpus

    partial = tmp_path / "p.parquet"
    pq.write_table(
        pa.table(
            {"code": pa.array(["Z01", "Z02"], type=pa.string())},
            metadata={b"decoy_corpus": b"x", b"source": b"Some Source"},
        ),
        str(partial),
    )
    cfg = CodeSetConfig.from_dict({"code_set": _URL, "corpus_source": f"customer:{partial}"})
    with pytest.raises(Exception) as info:
        describe_loaded_corpus(cfg)
    assert getattr(info.value, "code", None) == "code_set_corpus_missing_provenance"
    _no_secret(str(info.value))
    assert info.value.__context__ is None

    full = tmp_path / "f.parquet"
    pq.write_table(
        pa.table(
            {"code": pa.array(["Z01", "Z02"], type=pa.string())},
            metadata={
                b"decoy_corpus": b"x",
                b"source": b"s",
                b"source_version": b"1",
                b"effective_date": b"2026-01-01",
                b"license": b"l",
            },
        ),
        str(full),
    )
    cfg = CodeSetConfig.from_dict({"code_set": _URL, "corpus_source": f"customer:{full}"})
    _no_secret(repr(describe_loaded_corpus(cfg)))


def test_second_stat_and_read_errors_hide_credentials(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from decoy_engine.transforms import _codeset_loader as loader

    class _BoomError(OSError):
        pass

    def _raise(*_a: Any, **_k: Any) -> None:
        raise _BoomError(f"https://svc:{_PW}@host/x?token={_TOK}")

    monkeypatch.setattr(loader.arrow_adapter, "read_table", _raise)
    cfg = CodeSetConfig.from_dict({"code_set": "ab", "corpus_source": _corpus(tmp_path)})
    with pytest.raises(Exception) as info:
        describe_loaded_corpus_for(cfg)
    assert getattr(info.value, "code", None) == "code_set_corpus_read_error"
    _no_secret(str(info.value))
    assert info.value.__context__ is None and info.value.__cause__ is None


def describe_loaded_corpus_for(cfg: CodeSetConfig) -> Any:
    from decoy_engine.transforms.code_set import describe_loaded_corpus

    return describe_loaded_corpus(cfg)


def test_invalid_mode_refused_with_no_live_row(tmp_path: pathlib.Path) -> None:
    cfg: dict[str, Any] = {
        "code_set": "ab",
        "mode": "maks",
        "chapter_preserve": True,
        "corpus_source": _corpus(tmp_path),
    }
    for values in ([None, None], []):
        df = pd.DataFrame({"c": pd.Series(values, dtype=object)})
        with pytest.raises(ValueError, match="unsupported mode"):
            CodeSetHandler().run(df, "c", make_seed(cfg), make_ctx())
    with pytest.raises(ValueError, match="unsupported mode"):
        CodeSetHandler().preflight(make_seed(cfg), make_ctx())


@pytest.mark.parametrize(
    ("exc_type", "err"),
    [(PermissionError, 13), (OSError, 5)],  # 5 is EIO: a generic OSError, not a subclass
)
def test_first_stat_translates_every_oserror_value_free(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, exc_type: type[OSError], err: int
) -> None:

    def _boom(self: Any, *a: Any, **k: Any) -> Any:
        raise exc_type(err, f"denied {_PW}", f"/x/{_TOK}")

    monkeypatch.setattr(pathlib.Path, "stat", _boom)
    cfg = CodeSetConfig.from_dict(
        {"code_set": "ab", "corpus_source": f"customer:{tmp_path}/{_TOK}.parquet"}
    )
    with pytest.raises(Exception) as info:
        describe_loaded_corpus_for(cfg)
    assert getattr(info.value, "code", None) == "code_set_corpus_read_error"
    assert _PW not in str(info.value)
    assert info.value.__context__ is None and info.value.__cause__ is None


def test_verify_corpus_problems_never_carry_the_file_stem(tmp_path: pathlib.Path) -> None:
    from decoy_engine.transforms._codeset_loader import verify_corpus

    partial = tmp_path / f"x?token={_TOK}.parquet"
    pq.write_table(
        pa.table(
            {"code": pa.array(["Z01", "Z02"], type=pa.string())},
            metadata={b"decoy_corpus": b"x", b"source": b"Some Source"},
        ),
        str(partial),
    )
    report = verify_corpus(partial)
    assert not report.ok
    assert "missing" in " ".join(report.problems)
    # The policy-rendered location is the only place the file name may appear.
    assert _TOK not in " ".join(report.problems).replace(report.path, "")


_PREFIXED = f"a/https://svc:{_PW}@host.example/c.parquet?token={_TOK}"


def test_load_path_keeps_the_configured_locator_for_display() -> None:
    # `Path` collapses the doubled separator, which hid the URL from the redactor.
    cfg = CodeSetConfig.from_dict({"code_set": "ab", "corpus_source": f"customer:{_PREFIXED}"})
    with pytest.raises(Exception) as info:
        describe_loaded_corpus_for(cfg)
    assert getattr(info.value, "code", None) == "code_set_corpus_path_not_found"
    _no_secret(str(info.value))


def test_verify_corpus_keeps_the_given_locator_for_display() -> None:
    from decoy_engine.transforms._codeset_loader import verify_corpus

    report = verify_corpus(_PREFIXED)
    assert not report.ok
    _no_secret(report.path)
    _no_secret(" ".join(report.problems))


def test_no_provenance_warning_hides_a_credential_label(
    tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture
) -> None:
    cfg = CodeSetConfig.from_dict({"code_set": _URL, "corpus_source": _corpus(tmp_path)})
    with caplog.at_level("DEBUG"):
        describe_loaded_corpus_for(cfg)
    assert any("no provenance" in r.getMessage() for r in caplog.records)
    for rec in caplog.records:
        _no_secret(rec.getMessage())


def test_file_supplied_provenance_never_enters_error_text() -> None:
    from decoy_engine.transforms._codeset._checks import _validate_provenance
    from decoy_engine.transforms._codeset_provenance import CodeSetProvenance

    def stamp(corpus: str, version: str, is_seed: str) -> CodeSetProvenance:
        return CodeSetProvenance(
            corpus=corpus,
            corpus_version=version,
            source="s",
            source_url="",
            license="l",
            citation="",
            source_version="1",
            effective_date="2026-01-01",
            is_seed=False,
            raw_is_seed=is_seed,
        )

    for bad in (stamp(_PW, "2.0", "true"), stamp("icd10", _TOK, _PW)):
        with pytest.raises(Exception) as info:
            _validate_provenance("icd10", "where", bad, is_shipped=True)
        _no_secret(str(info.value))
    assert "corpus_version" in str(info.value)


def test_success_path_provenance_is_stripped_of_url_credentials(tmp_path: pathlib.Path) -> None:
    from decoy_engine.transforms._codeset_loader import verify_corpus
    from decoy_engine.transforms.code_set import describe_loaded_corpus

    path = tmp_path / "p.parquet"
    pq.write_table(
        pa.table(
            {"code": pa.array(["Z01", "Z02"], type=pa.string())},
            metadata={
                b"decoy_corpus": b"x",
                b"source": f"https://svc:{_PW}@host/a?token={_TOK}".encode(),
                b"source_version": b"1",
                b"effective_date": b"2026-01-01",
                b"license": b"l",
            },
        ),
        str(path),
    )
    _no_secret(repr(verify_corpus(path).provenance))
    cfg = CodeSetConfig.from_dict({"code_set": "x", "corpus_source": f"customer:{path}"})
    _no_secret(repr(describe_loaded_corpus(cfg)))


def test_both_stat_sites_classify_not_a_directory_the_same_way() -> None:
    from decoy_engine.transforms._codeset._checks import corpus_stat_error

    for exc in (NotADirectoryError(20, "x"), FileNotFoundError(2, "x")):
        first = corpus_stat_error(exc, "p")
        second = corpus_stat_error(exc, "p")
        assert first.code == second.code == "code_set_corpus_path_not_found"
    assert corpus_stat_error(OSError(5, _PW), "p").code == ("code_set_corpus_read_error")


def test_verify_corpus_given_a_path_object_hides_the_prefixed_url() -> None:
    from decoy_engine.transforms._codeset_loader import verify_corpus

    # `Path` collapses `https://` to `https:/`; the redactor still recognises a remote scheme.
    report = verify_corpus(pathlib.Path(_PREFIXED))
    assert not report.ok
    _no_secret(report.path)
    _no_secret(" ".join(report.problems))


def test_schema_error_never_lists_column_names(tmp_path: pathlib.Path) -> None:
    from decoy_engine.transforms._codeset_loader import verify_corpus

    path = tmp_path / "nocode.parquet"
    pq.write_table(pa.table({f"https://svc:{_PW}@host": pa.array(["a"])}), str(path))
    report = verify_corpus(path)
    assert not report.ok
    _no_secret(" ".join(report.problems))


def test_provenance_text_with_a_url_marker_is_withheld(tmp_path: pathlib.Path) -> None:
    from decoy_engine.transforms._codeset_loader import verify_corpus

    path = tmp_path / "p2.parquet"
    pq.write_table(
        pa.table(
            {"code": pa.array(["Z01", "Z02"], type=pa.string())},
            metadata={
                b"decoy_corpus": b"x",
                b"source": f"//archive:{_PW}@repo.invalid/data".encode(),
                b"source_version": b"1",
                b"effective_date": b"2026-01-01",
                b"license": b"Internal",
            },
        ),
        str(path),
    )
    prov = verify_corpus(path).provenance
    assert prov is not None
    assert prov["source"] == "<redacted>"
    assert prov["license"] == "Internal"


def test_a_shipped_load_diagnostic_does_not_print_none() -> None:
    from decoy_engine.transforms import _codeset_loader

    shown = _codeset_loader._where(None)
    assert shown != "None"


@pytest.mark.parametrize(
    "locator",
    [
        "//svc:{pw}@host/c.parquet",
        "\\\\svc:{pw}@host\\c.parquet",
        "//svc:pa@{pw}@host/c.parquet?t={tok}",
    ],
)
def test_network_path_userinfo_is_redacted_on_every_surface(locator: str) -> None:
    from decoy_engine.transforms._codeset_loader import verify_corpus

    raw = locator.format(pw=_PW, tok=_TOK)
    _no_secret(without_url_credentials(raw))
    report = verify_corpus(raw)
    assert not report.ok
    _no_secret(report.path)
    _no_secret(" ".join(report.problems))
    cfg = CodeSetConfig.from_dict({"code_set": "ab", "corpus_source": f"customer:{raw}"})
    with pytest.raises(Exception) as info:
        describe_loaded_corpus_for(cfg)
    _no_secret(str(info.value))


@pytest.mark.parametrize(
    ("locator", "carries"),
    [
        ("https://svc:pw@host/c", True),
        ("https://host/c?token=T", True),
        ("https://host/c#frag", True),
        ("//svc:pw@host/c", True),
        ("https:\\\\host\\c.parquet", False),
        ("s3:/bucket/c.parquet", False),
        ("//server/share/a@b.parquet", False),
        ("/tmp/archive:/alice@local/file?rev=1", False),
        ("C:\\data\\c.parquet", False),
    ],
)
def test_carries_credentials_ignores_separator_normalisation(locator: str, carries: bool) -> None:
    assert locator_carries_credentials(locator) is carries


def test_a_credential_free_license_url_is_published(tmp_path: pathlib.Path) -> None:
    from decoy_engine.transforms._codeset_loader import verify_corpus

    path = tmp_path / "lic.parquet"
    pq.write_table(
        pa.table(
            {"code": pa.array(["Z01", "Z02"], type=pa.string())},
            metadata={
                b"decoy_corpus": b"x",
                b"source": b"https://example.org/source",
                b"source_version": b"1",
                b"effective_date": b"2026-01-01",
                b"license": b"https://creativecommons.org/licenses/by/4.0/",
            },
        ),
        str(path),
    )
    prov = verify_corpus(path).provenance
    assert prov is not None
    assert prov["license"] == "https://creativecommons.org/licenses/by/4.0/"
    assert prov["source"] == "https://example.org/source"
