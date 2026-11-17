### Deprecated (workflow reason tombstones, WFR-E1, 2026-11-17)

The platform workflow reasons are retired with the workflows. `platform/workflow_restart_interrupted`, `platform/workflow_step_not_run` and `platform/workflow_step_failed` keep their code, symbol and text and still resolve, so a stored record that names one still reads. Each now carries `deprecated_in` and points at a live reason: `platform/startup_failed`, `platform/job_cancelled` and `platform/job_failed`. The declarations moved to `reasons/platform/_retired.py`. Release prep stamps the deprecation.
