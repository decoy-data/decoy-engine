### Added (GEN-PROVIDERS, E1, 2026-11-17)

A generate column can now use `type: provider` with `provider: <name>`. The name is any scalar provider that masking can use: the nine synthetic identifiers (`synthetic_ssn`, `synthetic_ein`, `synthetic_npi`, `synthetic_ndc`, `synthetic_mrn`, `synthetic_pan`, `synthetic_icd10`, `synthetic_iban`, `synthetic_cusip`) and the Faker-backed names such as `person_phone`. Values come from the same adapters that masking uses, so an NPI or PAN has its check digit. An optional `locale` must be one the provider declares. `decoy validate` refuses an unknown provider, an unsupported locale and a composite provider. The composite providers need a later release. A provider column runs on the resident route, is refused in pinned mode, and does not take `unique`.

A `faker` column whose `faker_type` is a registry name now gets `generate_faker_type_is_domain_provider`, which points to `type: provider`.

#### Identifier locale scope

Each synthetic identifier now reads one locale constant for both its capability row and its generator. SSN, EIN, NPI and NDC stay `en_US` only. CUSIP declares `en_CA` and `en_US` and now refuses any other locale in `generate_random`. IBAN, PAN, ICD-10 and MRN declare every engine locale, because their output does not depend on it.

New reason codes (all unreleased): `plan/generate_provider_unknown`, `plan/generate_provider_unsupported`, `plan/generate_provider_field_required`, `plan/generate_provider_field_unexpected`, `plan/generate_provider_locale_unsupported`, `plan/generate_faker_type_is_domain_provider`, `plan/pinned_provider_unsupported` and `runtime/generation_provider_failed`. The registry version and manifests change at the release.

The support bundle `StrategyKind` enum gains `provider`, so a bundle can name a provider generate column.
