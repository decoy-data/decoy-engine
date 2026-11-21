"""Token vault: an encrypted source-to-masked map for one-way strategies.

`decoy_engine.unmask` reverses fpe columns algebraically (a keyed
bijection inverts); hash, faker, redact and the rest destroy or replace
information, so their unmask status is `irreversible`. The vault makes
a column reversible by RECORDING the mapping at mask time instead of
relying on mathematical invertibility -- the model commercial masking
tools call reversible tokenization (a token vault). Opt-in twice: the
column declares `vault: true` AND the operator passes a vault path; a
mask run never writes a vault otherwise.

Security model. The vault is a re-identification database: anyone
holding the vault file AND the run's mask key (the secret behind
`mask_secret_ref` / a programmatic `key_provider`) can recover every
vaulted source value. A vault is never keyed on the public job seed:
every key that writes, opens or is matched against a vault must be the
32-byte mask root, checked at construction and again at every write,
load and key-match, because an 8-byte public seed gives a KDF nothing to
amplify. Store the vault and the config separately, with the handling the
source data itself would get; never ship a vault alongside its masked output. The encryption is
Fernet from the `cryptography` package (AES-128-CBC + HMAC-SHA256,
encrypt-then-MAC, per the published Fernet spec) -- an audited AEAD
construction rather than anything hand-rolled, per the engine's
established-methodology rule. `cryptography` was promoted to a base
dependency at Task 5.2 (the FF1 cipher needs AES unconditionally, not
just vault); the `[vault]` extra is now a no-op compatibility alias, and
`decoy_engine` itself fails to import without `cryptography` installed.
The function-local imports below predate that promotion and stay as
defense in depth against a future split, not a live degrade path.

Key model. One key per job, domain-separated from every other engine
derivation by a fresh label: `derive(mask_key, "vault", b"vault-key/v1")`
(HKDF-style HMAC-SHA256 expansion, RFC 5869 model; the same envelope FPE
keys use with their own label). `mask_key` is the run's keyed-mask IKM --
the 32-byte `SecretKeyProvider` HKDF root of the configured secret (DE-02)
-- so the vault is bound to the run's masking key, never the public seed. A
vault written by an older engine under the 8-byte `job_seed` no longer opens
and is regenerated, together with its masked output, under a secret (pre-GA
hard delete; no migration). `derive` mixes `SEED_PROTOCOL_VERSION` into the
key, so a vault written under one protocol version is undecryptable under
another. The `decoy-vault/v2` file format stamps that version in its
unencrypted header, so a cross-version load fails with a clear
`vault_protocol_version_mismatch` rather than an opaque key error.

File format (`decoy-vault/v2`). Magic, then a length-prefixed unencrypted JSON header (`format`,
`seed_protocol_version`, `ambiguous_dropped`, chunk framing), then a sequence of length-prefixed
Fernet tokens, one per bounded chunk of sorted entries. Each chunk is serialized + encrypted
independently (F13), so the full plaintext table is never held as one serialized blob before
encryption.

Determinism boundary. Vault CONTENTS are a pure function of (config, sources): entries are sorted
before serialization. The vault FILE is not byte-reproducible because Fernet embeds a random IV and
a timestamp; reproducibility contracts apply to masked outputs, never to this artifact.

Ambiguity. Pooled strategies may map two source values to one masked
value (e.g. `cardinality_mode: reuse` faker with a small pool). A
masked value with conflicting sources cannot be inverted; `write()`
drops those keys and records the count in the unencrypted header
(`ambiguous_dropped`), and the unmask report surfaces it. Exact round
trips hold only for keys no other source value masked to; no strategy,
hash included, is collision-free unless it is unique-mode.

Package layout. `_format.py` owns the file layout and the cipher, `_writer.py` the writer and its
commit token, `_reader.py` the read path. This module re-exports the public names so
`from decoy_engine.vault import ...` is unchanged.
"""

from __future__ import annotations

from decoy_engine.internal.vault_entries import collect_vault_entries as collect_vault_entries
from decoy_engine.internal.vault_entries import iter_vault_columns as iter_vault_columns

# isort: off
# The import order is the definition order of the old single module (`_writer` first, because it
# opens with the TYPE_CHECKING block); isort would reorder it.
from decoy_engine.vault._writer import VaultCommit as VaultCommit
from decoy_engine.vault._writer import VaultWriter as VaultWriter
from decoy_engine.vault._writer import assert_vault_writer_keyed as assert_vault_writer_keyed
from decoy_engine.vault._writer import issue_commit as issue_commit
from decoy_engine.vault._writer import vault_writer_for_config as vault_writer_for_config
from decoy_engine.vault._format import VAULT_FORMAT_VERSION as VAULT_FORMAT_VERSION
from decoy_engine.vault._format import VAULT_KEY_LABEL as VAULT_KEY_LABEL
from decoy_engine.vault._format import VAULT_NAMESPACE as VAULT_NAMESPACE
from decoy_engine.vault._format import VaultError as VaultError
from decoy_engine.vault._reader import load_vault as load_vault
# isort: on

# The vault became a package; a module never needed `__all__`, a public package does (census).
__all__ = [
    "VAULT_FORMAT_VERSION",
    "VAULT_KEY_LABEL",
    "VAULT_NAMESPACE",
    "VaultCommit",
    "VaultError",
    "VaultWriter",
    "assert_vault_writer_keyed",
    "collect_vault_entries",
    "issue_commit",
    "iter_vault_columns",
    "load_vault",
    "vault_writer_for_config",
]
