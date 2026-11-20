### Changed (gate verdict status and macOS path scope, fix24-e5, 2026-11-17)

CI only. A `gate-selfhosted.yml` dispatch now posts the commit status `engine-gate/verdict`, and
`required_checks.py verify --tier merge` requires it on the PR head. The macOS wheel legs in
`native-companion.yml` run only when a PR touches the native companion; the new check
`companion-wheel-macos-ok` stands in for the three per-leg checks.
