Breaking: `nested` `provider_config.target` is limited to a closed RFC 9535 subset, so `compile_plan` and `run_config_only_checks` refuse `$..a`, filters, unions, a missing `$`, dot-quoted names, backticks and `$['*']` with the new reason `plan.nested_target_unsupported`; `[*]`, an index and a slice on an object or scalar cell fail with `nested_target_unwritable_container`, and `$.*` on an array now selects its items

### Changed (nested target grammar, NESTED-FREEZE, 2026-11-23)

A `nested` target is `$` followed by `.name`, `.*`, `['name']`, `[*]`, `[index]` or `[start:end:step]`. One function, `decoy_engine._nested_json.parse_target`, reads it for the plan check and the handler, and `TargetPath.find` evaluates it, so what a target selects no longer depends on the installed jsonpath-ng version (1.8 and 1.16 disagreed on an array selector applied to an object). A target outside the subset fails at compile and in `decoy validate` with the position and the form found.

An index selector on a JSON object cell now fails with `nested_target_unwritable_container` instead of a bare `KeyError`. An index past the end of an array selects nothing for that branch only. `$.*` on an array selects its items (jsonpath-ng 1.8 selected nothing). The overlap warning `nested_jsonpath_path_overlap` is no longer raised: no subset target can match a path and its prefix.
