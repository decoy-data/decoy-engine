"""GCS size and generation come from one metadata view (F25 G7-1, case 12).

`_clients.gcs_pinned_version` reloads the blob every time, so the pair is never a cached
size next to a newer generation, and a missing value is `source_changed`. Both the connector
object stream and the profile reader go through it.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest

from decoy_engine.connectors import _clients, gcs
from decoy_engine.errors import ConnectorError
from decoy_engine.profile import _cloud_readers as cr


class _Blob:
    """A blob whose `reload` sets what the store would report; `None` leaves it unset."""

    def __init__(self, size: int | None, generation: int | None, cached: bool = False) -> None:
        self.reloads = 0
        self._after = (size, generation)
        self.size, self.generation = self._after if cached else (None, None)

    def reload(self, **_kw: Any) -> None:
        self.reloads += 1
        self.size, self.generation = self._after


class _Bucket:
    def __init__(self, blob: _Blob) -> None:
        self._blob = blob

    def blob(self, _name: str) -> _Blob:
        return self._blob


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    seen: list[Any] = []
    real = _clients.gcs_pinned_version

    def recording(blob: Any) -> tuple[int, int]:
        seen.append(blob)
        return real(blob)

    monkeypatch.setattr(_clients, "gcs_pinned_version", recording)
    return seen


def test_the_pair_is_reloaded_even_when_both_values_are_already_set() -> None:
    blob = _Blob(5, 9, cached=True)
    assert _clients.gcs_pinned_version(blob) == (5, 9)
    assert blob.reloads == 1


@pytest.mark.parametrize("missing", [(None, 9), (5, None), (None, None)])
def test_a_missing_value_after_reload_is_source_changed(missing: tuple[Any, Any]) -> None:
    with pytest.raises(ConnectorError) as info:
        _clients.gcs_pinned_version(_Blob(*missing))
    assert info.value.kind == "source_changed"


@pytest.mark.parametrize("missing", [(None, 9), (5, None)])
@pytest.mark.parametrize("caller", ["stream", "profile"])
def test_both_callers_reach_the_helper_and_refuse_a_missing_value(
    monkeypatch: pytest.MonkeyPatch, calls: list[Any], caller: str, missing: tuple[Any, Any]
) -> None:
    blob = _Blob(*missing, cached=True)
    with pytest.raises(ConnectorError) as info:
        if caller == "stream":
            list(gcs._stream_blob(lambda: _Bucket(blob), "k"))
        else:

            @contextmanager
            def client() -> Iterator[Any]:
                yield type("C", (), {"bucket": lambda _s, _n: _Bucket(blob)})()

            monkeypatch.setattr(_clients, "gcs_client", client)
            cr.GcsCsvSource({"bucket": "b", "object": "k", "format": "csv"}).to_frame()
    assert info.value.kind == "source_changed"
    assert calls == [blob]
