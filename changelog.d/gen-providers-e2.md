### Added (GEN-PROVIDERS, E2, 2026-11-23)

A generate column can now use a composite provider: `composite_person`, `composite_name_email`, `composite_city_state_zip`, `composite_address` and `composite_provider`. Each output is its own `type: provider` column, named by `field`. Columns of one table that share a `provider` and a `group` (default: the provider name) take their values from one draw per row, so an email is built from that row's first and last name and a ZIP belongs to that row's state. A second `group` in the same table gives a second person. `composite_custom` is still refused.

`decoy validate` refuses a composite column with no `field`, an unknown `field`, the same `field` twice in one group, and a group whose columns disagree on `locale` or `determinism`. A group's values do not change when you reorder, rename or add columns.

The six masking composites are now built from one descriptor table (`COMPOSITES` in `decoy_engine.generation.composite`), read by the registry binding, the wiring check, the masking handler and the column-access declarations. Masking output is unchanged; a new digest test pins the handler's output for all six composites in both modes.

New reason codes (all unreleased): `plan/generate_provider_field_unknown`, `plan/generate_provider_field_duplicate` and `plan/generate_provider_group_mismatch`. The registry version and manifests change at the release.
