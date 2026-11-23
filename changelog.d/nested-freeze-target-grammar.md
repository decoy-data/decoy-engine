Breaking: `nested` `provider_config.target` accepts only a closed RFC 9535 subset, so `compile_plan` and `run_config_only_checks` now refuse with the new reason `plan.nested_target_unsupported` what used to compile: `$..x` and `$..*`, filters, `,` unions, a target without `$`, dot-quoted names, backtick selectors, `|`, `&` and `where`, `$['*']`, a slice step below 1, leading-zero and `-0` indexes, blank space outside a quoted name, and member names with `-` or `@` or a leading digit; `$.*` on an array cell now selects its items (it selected nothing); `[*]`, an index and a slice on an object or scalar cell fail with `nested_target_unwritable_container` (an index on an object was a bare `KeyError`); an index past the end of an array selects nothing for that branch; `nested_jsonpath_path_overlap` is no longer raised; the `jsonpath-ng` requirement is removed

### Changed (nested target grammar, NESTED-FREEZE, 2026-11-23)

A `nested` target is `$` followed by `.name`, `.*`, `['name']`, `[*]`, `[index]` or `[start:end:step]`. One function, `decoy_engine._nested_json.parse_target`, reads it for the plan check and the handler, and `TargetPath.find` evaluates it, so what a target selects no longer depends on a JSONPath library (jsonpath-ng 1.8 and 1.16 disagreed on an array selector applied to an object). A target outside the subset fails at compile and in `decoy validate` with the position and the form found. No shipped doc, example, CLI or platform config used a refused form.

The overlap warning `nested_jsonpath_path_overlap` is no longer raised: no subset target can match a path and its prefix.

The engine no longer imports jsonpath-ng, so the requirement, its mypy override and its NOTICE line are gone.
