"""SFTP reads stream in 1 MiB pieces (F25 G7-1, B12).

SFTP has no profile table reader in 1.0; its connector `open` is the only object read. This
pins that `open` asks paramiko for at most 1 MiB per read and never for the whole file.
"""

from __future__ import annotations

import io
from typing import Any

import pytest

MiB = 1 << 20


class _RemoteFile(io.BytesIO):
    def __init__(self, data: bytes, sizes: list[int | None]) -> None:
        super().__init__(data)
        self._sizes = sizes

    def read(self, size: int | None = -1) -> bytes:
        self._sizes.append(size)
        return super().read(size)


class _Sftp:
    def __init__(self, data: bytes, sizes: list[int | None]) -> None:
        self._data, self._sizes = data, sizes

    def stat(self, path: str) -> Any:
        return None

    def open(self, path: str, mode: str) -> _RemoteFile:
        assert mode == "rb"
        return _RemoteFile(self._data, self._sizes)


class _Client:
    def close(self) -> None:
        pass


def test_open_reads_one_mib(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("paramiko")
    from decoy_engine.connectors import sftp as sftp_mod

    data = bytes(range(256)) * (3 * MiB // 256 + 5)
    sizes: list[int | None] = []
    monkeypatch.setattr(sftp_mod, "_open_sftp", lambda config: (_Client(), _Sftp(data, sizes)))
    config = sftp_mod.SFTPConfig(host="h", username="u", password="p")
    chunks = list(sftp_mod.SFTPFileSource(config).open("f"))

    assert b"".join(chunks) == data
    assert max(len(c) for c in chunks) == MiB
    assert sizes and all(s == MiB for s in sizes)
