"""Read a vault file back into `{(namespace, masked): source}`."""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa

from decoy_engine import fileaccess, reasons
from decoy_engine._opaque import OpaqueBox
from decoy_engine.determinism import SEED_PROTOCOL_VERSION
from decoy_engine.fileaccess import (
    FileAccess,
    FileAccessUnavailable,
    FileHandle,
    FileRequest,
    FileRole,
)
from decoy_engine.vault._format import (
    _MAGIC,
    _SCHEMA,
    VAULT_FORMAT_VERSION,
    VaultError,
    _fernet,
    _key_size,
    _read_frame,
    _unreadable,
)


@fileaccess.entry_point
def load_vault(
    path: str | Path | None,
    mask_key: bytes,
    *,
    vault: FileHandle | None = None,
    file_access: FileAccess | None = None,
) -> tuple[dict[tuple[str, str], str], int]:
    """Decrypt a vault file into `{(namespace, masked): source}`.

    DE-02: `mask_key` is the keyed-mask IKM the vault was written under (the
    32-byte KeyProvider root). A shorter key, such as the 8-byte `job_seed`
    an older engine keyed vaults on, is refused before the file is read.

    `vault` is a handle the policy issued for the vault file and takes the place of `path`;
    a path string is accepted only under the ambient CLI policy and raises
    `FileAccessUnavailable` under any other.

    Returns the map plus the recorded `ambiguous_dropped` count.

    Raises:
        VaultError: ``code='vault_crypto_not_installed'`` when the
            `cryptography` package is missing;
            ``code='weak_mask_secret'`` when `mask_key` is not the 32-byte
            mask root, as bytes (checked before the file is read);
            ``code='vault_unreadable'`` when the file is missing or not
            a vault; ``code='vault_format_unsupported'`` on a format
            version this engine does not consume;
            ``code='vault_protocol_version_mismatch'`` when the vault was
            written under a different `SEED_PROTOCOL_VERSION` (cross-version
            unmask is not supported);
            ``code='vault_key_mismatch'`` when `mask_key` does not
            decrypt the file (wrong config/secret for this vault).
    """
    # Build the Fernet first so a missing cryptography extra fails with
    # vault_crypto_not_installed even when the file is absent (preserves the
    # pre-streaming ordering the absent-dep contract test pins). Building the
    # object only derives the key; it does not decrypt. The key's size is read inside the
    # boxing statement, because the key must be boxed and dropped before anything else runs.
    key = OpaqueBox(mask_key, size := _key_size(mask_key))
    del mask_key  # a traceback keeps this frame: the key must not be among its locals
    fernet = _fernet(key, size)
    handle = vault
    if handle is None:
        if path is None or not fileaccess.is_ambient():
            raise FileAccessUnavailable(
                "load_vault needs a vault handle from the policy; a path string is accepted "
                "only under the ambient policy"
            )
        handle = fileaccess.current().open_read(
            FileRequest(FileRole.VAULT, "read", str(path), "vault")
        )
    shown = handle.display
    try:
        blob = handle.read_all()
    except OSError as exc:
        if fileaccess.keeps_class(exc):
            raise
        raise VaultError(
            code=reasons.runtime.VAULT_UNREADABLE,
            message=f"vault file {shown!r} could not be read: {exc}",
        ) from exc
    finally:
        if vault is None:
            handle.close()
    if not blob.startswith(_MAGIC):
        raise _unreadable(f"{shown!r} is not a decoy vault file (bad magic header).")

    # Parse + validate the UNENCRYPTED header before any decrypt: a version mismatch then
    # gets a clear typed error, not an opaque InvalidToken (it does not restore compatibility).
    header_bytes, offset = _read_frame(blob, len(_MAGIC))
    try:
        header = json.loads(header_bytes)
        if type(header.get("ambiguous_dropped", 0)) is not int:  # also bool, str, null
            raise ValueError("ambiguous_dropped")
    except (ValueError, UnicodeDecodeError, AttributeError) as exc:  # AttributeError: not a dict
        raise _unreadable(f"vault {shown!r} has an unreadable header") from exc
    fmt = header.get("format")
    if fmt != VAULT_FORMAT_VERSION:
        raise VaultError(
            code=reasons.runtime.VAULT_FORMAT_UNSUPPORTED,
            message=(
                f"vault {shown!r} declares format {fmt!r}; this engine "
                f"consumes {VAULT_FORMAT_VERSION!r}."
            ),
        )
    vault_version = header.get("seed_protocol_version")
    if vault_version != SEED_PROTOCOL_VERSION:
        raise VaultError(
            code=reasons.runtime.VAULT_PROTOCOL_VERSION_MISMATCH,
            message=(
                f"vault {shown!r} was written under seed protocol version "
                f"{vault_version!r}; this engine runs version {SEED_PROTOCOL_VERSION!r}. "
                f"Cross-version unmask is not supported; re-mask under this engine "
                f"or use an engine at protocol version {vault_version!r}."
            ),
        )
    ambiguous: int = header.get("ambiguous_dropped", 0)

    import pyarrow.parquet as pq
    from cryptography.fernet import InvalidToken

    mapping: dict[tuple[str, str], str] = {}
    while offset < len(blob):
        token, offset = _read_frame(blob, offset)
        try:
            payload = fernet.decrypt(token)
        except InvalidToken as exc:
            raise VaultError(
                code=reasons.runtime.VAULT_KEY_MISMATCH,
                message=(
                    "the key does not decrypt this vault; open it with the mask secret "
                    "of the run that wrote it."
                ),
            ) from exc
        rows = None  # the raise is outside the `except`, so no cause or context carries values
        try:
            chunk = pq.read_table(pa.BufferReader(payload))
            if chunk.schema.equals(_SCHEMA) and not any(c.null_count for c in chunk.columns):
                rows = list(zip(*(c.to_pylist() for c in chunk.columns), strict=True))
        except (pa.ArrowException, KeyError, ValueError):
            pass
        if rows is None:
            raise _unreadable("vault chunk is malformed")
        known = len(mapping)
        mapping.update({(ns, m): src for ns, m, src in rows})
        if len(mapping) != known + len(rows):  # the writer folds duplicates, so one is corruption
            raise _unreadable("vault holds a duplicate entry")
    return mapping, ambiguous
