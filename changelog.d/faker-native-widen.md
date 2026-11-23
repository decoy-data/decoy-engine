Breaking: person name, email, phone and address faker providers (and the synthetic account, member and plan ids) now run on the native and chunked routes; an empty or all-null chunked output column, and a deterministic column over an all-null or empty int/bool source on any route, is typed string, and a non-string custom provider under one of these names fails on the chunked route.

### Changed (faker providers run native, FAKER-NATIVE-WIDEN, 2026-11-23)

`person_name`, `person_full_name`, `person_email`, `person_phone`, `address_street`,
`address_city`, `address_state`, `address_zip`, `synthetic_account_number`,
`synthetic_member_id` and `synthetic_plan_id` join `person_first_name` and `person_last_name` on the
native route. Output values do not change. All four CLI templates now run their faker columns
native, and a deterministic faker column with a namespace and one of these providers is admitted on
the out-of-core route.
