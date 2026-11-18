### Changed (Vault adapter conformance, F13 E3, 2026-11-18)

The Vault provider now reads only values frozen when it is built: address, token, namespace, CA bundle path, client certificate and proxies. `REQUESTS_CA_BUNDLE`, proxy variables, `~/.netrc` and `VAULT_TOKEN` set after build no longer change a read. A client with an empty address is refused at build (`secret_provider_unconfigured`). An empty token stays allowed and sends no token header, so the Vault Agent proxy pattern keeps working. Build the provider per run.

`client_from_env` now reads `~/.vault-token` once, after every other setting is checked, when `VAULT_TOKEN` is unset. An unreadable file raises `VaultClientConfigError` with fixed text.

Vault failures are raised after their handlers close, so no exception carries a cause or context.
