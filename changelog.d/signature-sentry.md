### Added (public signature sentry, SIGNATURE-SENTRY E1, 2026-11-22)

A test now compares the public signatures with the newest release tag. A change to a frozen or experimental name that breaks a caller (a parameter removed, moved or made required, a default changed, an object removed) fails unless a `Breaking:` line in a `changelog.d` fragment names the object and, for a parameter, the parameter, in backticks. The tool is `griffelib`, a dev dependency, so nothing in the wheel changes.

`decoy_engine.plan` exports `NO_SOURCES` (frozen) and `SourceFacts` (experimental), so a caller of `compile_plan` can build its required `sources` argument from a public path. The 0.28.3 notes now list the `compile_plan` and `VaultWriter` signature breaks that release carried without a line.
