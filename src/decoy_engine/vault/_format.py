"""The vault file layout: magic, framing, the key floor and the Fernet cipher (`decoy-vault/v2`).

One module owns the format and the crypto so the rest of the package never touches either.
See the package docstring for the security model and the file format.
"""

from __future__ import annotations

import base64
from typing import Any

import pyarrow as pa

from decoy_engine import reasons
from decoy_engine._opaque import OpaqueBox
from decoy_engine.determinism import derive
from decoy_engine.errors import DecoyError

VAULT_FORMAT_VERSION = "decoy-vault/v2"
VAULT_NAMESPACE = "vault"
# Key model is unchanged across the v1 -> v2 format bump, so the derivation
# label stays at v1: only the file LAYOUT and the protocol-version stamping
# changed, not how the key is derived. Bumping the label would re-key every
# vault for no security reason.
VAULT_KEY_LABEL: bytes = b"vault-key/v1"

# decoy-vault/v2 framing: magic, then length-prefixed unencrypted header JSON,
# then a sequence of length-prefixed Fernet tokens (one per chunk). The 4-byte
# big-endian length prefix is the same idiom the determinism layer uses
# (determinism/_derive.py, generators/derivation.py).
_MAGIC = b"DCYVAULT2\n"
_CHUNK_ROWS = 65536
_INSTALL_HINT = "pip install 'decoy-engine[vault]'"


_SCHEMA = pa.schema([(n, pa.string()) for n in ("namespace", "masked", "source")])


def _unreadable(message: str) -> VaultError:
    return VaultError(code=reasons.runtime.VAULT_UNREADABLE, message=message)


def _frame(block: bytes) -> bytes:
    """Length-prefix a block: 4-byte big-endian length || block."""
    return len(block).to_bytes(4, "big") + block


def _read_frame(blob: bytes, offset: int) -> tuple[bytes, int]:
    """Read one length-prefixed block at `offset`; return (block, next_offset).

    Raises VaultError(vault_unreadable) on truncation so a corrupt/short file
    fails cleanly instead of slicing past the end.
    """
    if offset + 4 > len(blob):
        raise _unreadable("vault file truncated (length prefix)")
    length = int.from_bytes(blob[offset : offset + 4], "big")
    start = offset + 4
    end = start + length
    if end > len(blob):
        raise _unreadable("vault file truncated (block body)")
    return blob[start:end], end


class VaultError(DecoyError):
    """Vault read/write failure. Machine-readable code."""

    def __init__(self, *, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


# Every provider's mask root is 32 bytes of HKDF output, and `derive` takes no other strong key
# length, so a longer key would pass a minimum and then fail at the first write or load.
_VAULT_KEY_BYTES = 32

_WEAK_KEY_MESSAGE = (
    f"the vault key must be the {_VAULT_KEY_BYTES}-byte mask root of a secret, as bytes; a "
    "vault is never keyed on the job seed. Build the writer with "
    "vault_writer_for_config(config, key_provider=...) or global_settings.mask_secret_ref."
)


def _key_size(key: object) -> int:
    # A `str` or any other non-bytes key counts as size 0, so it fails the floor like a short key.
    return len(key) if isinstance(key, (bytes, bytearray)) else 0


def _require_vault_key(size: int) -> None:
    """Refuse with `weak_mask_secret` unless the vault key's size (`_key_size`) is the mask root's.

    Callers pass only the size, so the key never becomes a local of this frame. The refusal text
    is fixed.
    """
    if size != _VAULT_KEY_BYTES:
        raise VaultError(code=reasons.runtime.WEAK_MASK_SECRET, message=_WEAK_KEY_MESSAGE)


def _fernet(mask_key: OpaqueBox, size: int) -> Any:
    # The Fernet key derives from the run's mask root. The floor is checked after the crypto
    # import and before the derive, so every write and load refuses a short key before any file
    # is touched. The IKM arrives boxed with its size beside it, so the key is opened once, in
    # the derive call, and the derived key is never a local (`_opaque`).
    try:
        from cryptography.fernet import Fernet
    except ImportError as exc:
        raise VaultError(
            code=reasons.runtime.VAULT_CRYPTO_NOT_INSTALLED,
            message=(
                f"the vault needs the `cryptography` package; install the "
                f"vault extra: {_INSTALL_HINT}"
            ),
        ) from exc
    _require_vault_key(size)
    return Fernet(
        base64.urlsafe_b64encode(derive(mask_key.open()[0], VAULT_NAMESPACE, VAULT_KEY_LABEL))
    )
