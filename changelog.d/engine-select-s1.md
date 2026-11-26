### Added (impact map builder for test selection, ENGINE-SELECT S1, 2026-11-26)

`scripts/dev/impact_map.py build` now records, for every default test file, which src functions it
executes and which tracked repo files it opens or lists. Each file runs in its own process under
coverage (sysmon on Python 3.12, subprocesses included), and the audit hook proves it ran in every
child process. The map is a versioned `impact-map.json.gz`, written only when every file has an
outcome and the build venv matches the gates venv. `impact_select/_select_map.py` reads it and
refuses any map it cannot trust.

No engine behavior changes and `gates.sh` selection is unchanged. The selector that uses the map
comes in a later slice.
