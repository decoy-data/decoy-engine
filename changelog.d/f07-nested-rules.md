### Added (several rules per nested column, 82-E3b, 2026-11-18)

A `nested` column can take `provider_config.rules`, a list of rules that each have a `target`, a child `strategy` and an optional `namespace`. Every rule matches on the parsed cell before anything is written, and each rule draws on its own identity. Two rules that reach the same position, or an ancestor and its descendant, fail the column. A rule takes only `target`, `strategy`, `strategy_config` and `namespace`, and a `faker` rule can name its own provider. The single `target` and `strategy` form works as before.

New reason codes: `plan/nested_rules_and_target_both_set`, `plan/nested_rules_empty`, `plan/nested_rule_target_duplicate`, `plan/nested_rules_code_set_repeated` and `plan/nested_rule_key_unknown`, `plan/nested_rule_namespace_invalid`, `plan/nested_rule_faker_provider_missing` and `runtime/nested_rules_overlap`.
