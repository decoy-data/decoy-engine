### Fixed (release stamp keeps the UNRELEASED import, STAMP-IMPORT, 2026-11-21)

The release stamp no longer deletes `from decoy_engine.reasons._types import UNRELEASED` from a reason module once its unreleased codes are stamped. Before, a branch that added a new `since=UNRELEASED` code to such a module merged clean and then raised `NameError` when `decoy_engine.reasons` loaded. Every reason module now binds it as the re-export `UNRELEASED as UNRELEASED`, so the unused-import rule stays on, and a sentry fails if a module lacks that binding. No code, version or message changed.
