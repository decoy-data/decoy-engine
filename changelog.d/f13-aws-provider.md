### Added (AWS Secrets Manager mask secrets, row 83, 2026-11-18)

`aws-sm://<region>/<name>?version=<uuid>&field=<f>&encoding=<e>` reads the mask secret from AWS Secrets Manager through `decoy_engine.secret_providers.aws` (`boto3`, already in the `cloud` extra). The version is pinned; a stage label such as `AWSCURRENT` is refused. New reason code `secret_provider_unconfigured` and public error `SecretProviderConfigError`; `VaultClientConfigError` is now a subclass with its messages unchanged.

Behavior change: a `vault://` or `aws-sm://` reference with a raw control character (tab, newline, carriage return, any code below 0x20, or 0x7f) is now refused. `urlsplit` dropped tab, newline and carriage return before, so such a reference could name a different secret than it showed.
