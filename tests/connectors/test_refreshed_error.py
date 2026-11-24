"""`connectors.refreshed_error` rebuilds a caught connector error with fixed text and keeps
its class and kind, so a retryable error never turns final (AT-A9, helper cases)."""

from __future__ import annotations

import pytest

from decoy_engine.sdk import ConnectorError, PermanentError, TransientError

MARK = "zz_marker_7f3a"


def _refreshed(exc: ConnectorError, provider: str) -> ConnectorError:
    from decoy_engine.connectors import refreshed_error

    return refreshed_error(exc, provider)


@pytest.mark.parametrize("cls", [TransientError, PermanentError])
@pytest.mark.parametrize("provider", ["S3", "GCS"])
def test_default_kind_keeps_the_class_and_the_kind(
    cls: type[ConnectorError], provider: str
) -> None:
    exc = cls(f"sdk text {MARK}")
    out = _refreshed(exc, provider)
    assert type(out) is cls and out.kind == "unexpected"
    assert str(out) == f"Unexpected {provider} error"
    assert MARK not in f"{out!s} {out!r} {out.args!r}"
    assert out.__cause__ is None and out.__context__ is None


@pytest.mark.parametrize(
    ("cls", "kind", "text"),
    [
        (TransientError, "transient", "S3 transient network or service error"),
        (PermanentError, "not_found", "S3 bucket or object not found"),
        (PermanentError, "access_denied", "S3 permission denied"),
        (PermanentError, "credentials", "S3 credentials unavailable or invalid"),
        (PermanentError, "source_changed", "S3 object changed during read"),
    ],
)
def test_a_kinded_error_keeps_class_and_kind_with_fixed_text(
    cls: type[ConnectorError], kind: str, text: str
) -> None:
    out = _refreshed(cls(MARK, kind=kind), "S3")  # type: ignore[arg-type]
    assert type(out) is cls and out.kind == kind and str(out) == text


def test_a_transient_kind_on_a_permanent_class_stays_permanent() -> None:
    out = _refreshed(PermanentError(MARK, kind="transient"), "GCS")
    assert type(out) is PermanentError and out.kind == "transient"


def test_the_text_comes_from_the_same_builder_as_sdk_translation() -> None:
    from decoy_engine.connectors._clients import gcs_error, s3_error

    for provider, translate in (("S3", s3_error), ("GCS", gcs_error)):
        raw = ValueError(MARK)
        translated = translate(raw)
        assert str(_refreshed(translated, provider)) == str(translated)


@pytest.mark.parametrize("cls", [TransientError, PermanentError])
def test_a_kind_outside_the_table_reads_as_unexpected_and_keeps_the_class(
    cls: type[ConnectorError],
) -> None:
    out = _refreshed(cls(f"sdk text {MARK}", kind="weird"), "S3")  # type: ignore[arg-type]
    assert type(out) is cls and out.kind == "unexpected"
    assert str(out) == "Unexpected S3 error"
    assert MARK not in f"{out!s} {out!r} {out.args!r}"


def _seeded_with_a_chain(exc: BaseException) -> BaseException:
    exc.__cause__ = ValueError(f"cause {MARK}")
    exc.__context__ = KeyError(f"context {MARK}")
    exc.add_note(f"note {MARK}")
    return exc


def _assert_unchained(fresh: BaseException) -> None:
    assert fresh.__cause__ is None and fresh.__context__ is None
    assert not getattr(fresh, "__notes__", [])
    assert MARK not in f"{fresh!s} {fresh!r} {fresh.args!r}"


def test_the_fresh_error_is_unchained_before_and_after_it_is_raised() -> None:
    from decoy_engine.fileaccess import classified_failure

    def reraise() -> None:
        try:
            raise _seeded_with_a_chain(PermanentError(f"sdk text {MARK}", kind="not_found"))
        except PermanentError as exc:
            fresh = _refreshed(exc, "S3")
        _assert_unchained(fresh)
        raise fresh from None

    with pytest.raises(PermanentError) as ei:
        reraise()
    _assert_unchained(ei.value)
    assert ei.value.__suppress_context__ is True

    def reclassify() -> None:
        try:
            raise _seeded_with_a_chain(MemoryError(MARK))
        except MemoryError as exc:
            result = classified_failure(exc)
        assert result is not None and result.fresh is not None
        _assert_unchained(result.fresh)
        raise result.fresh from None

    with pytest.raises(MemoryError) as mi:
        reclassify()
    _assert_unchained(mi.value)
