### Added (public renames table, FREEZE-S7c, 2026-11-20)

Contract section 1 now holds one table of public renames since the 0.11.0 taxonomy split: old name, new name, kind, engine version. It covers the detection symbols, the 0.17.0 config and wire names, the route reason codes and the custom provider folder variable. A test checks the table shape and that each new symbol imports and each old one does not. No code changes.
