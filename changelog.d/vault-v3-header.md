Breaking: the vault file is now `decoy-vault/v3` and a `decoy-vault/v2` file no longer opens (`vault_format_unsupported`); re-run the mask with `--vault` to write a new one. `VaultWriter` takes a `PreparedSecret`, `VaultWriter(prepared, *, file_access=None)`, owns a clone of it, and has `close()`.

### Changed (authenticated, versioned vault header, F09 E1, 2026-11-20)

The vault is one libsodium secretstream (`crypto_secretstream_xchacha20poly1305`, through PyNaCl) with a closed-set JSON header bound to every segment as additional data. Each vault has its own key, derived with `vault-key/v2` and a random `vault_id`. The header records `key_version`, a key check value bound to `vault_id`, `entry_count` and `segment_rows`. A wrong secret gives `vault_key_mismatch` before any segment is decrypted and names the recorded key version. Once the key is right, any change, reorder, drop, duplicate or cut gives `vault_tampered` and returns no rows. A single entry over 64 MiB of Parquet gives `vault_entry_too_large` before any file is written. `load_vault` keeps its signature. The resume store's key check moved to one function, `key_check_value`, with byte-identical output.

#### Added: header API and reasons

`open_vault(path, prepared, *, vault=None, file_access=None)` returns an `OpenedVault` (`mapping`, `ambiguous_dropped`, `header`), where `header` is a `VaultHeader` of the non-secret fields (`format`, `key_version`, `vault_id`, `entry_count`, `ambiguous_dropped`, `segment_rows`). `VAULT_REFUSAL_CODES` names every code a vault read or write can raise. New reasons `runtime/vault_tampered` and `runtime/vault_entry_too_large`, pending.
