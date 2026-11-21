### Fixed (release stamp keeps the UNRELEASED import, STAMP-IMPORT, 2026-11-21)

The release stamp no longer deletes `from decoy_engine.reasons._types import UNRELEASED` from a reason module once its unreleased codes are stamped. Before, a branch that added a new `since=UNRELEASED` code to such a module merged clean and then raised `NameError` when `decoy_engine.reasons` loaded. Every reason spec module now keeps the import, ruff ignores the unused-import rule there, and a sentry fails if a spec module lacks it. No code, version or message changed.
