### Fixed (Test-flight failure text carries no cell values, TEST-FLIGHT-FIX bucket-perturb-date-format, 2026-11-25)

The test-flight assertion message and `report.md` now show the exception type name for a job error and the invariant name with a fixed category for a failed invariant. They no longer print the raw error or detail text, which could quote a cell value into the CI log. The checks run in the default suite.
