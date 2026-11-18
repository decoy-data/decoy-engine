### Added (several rules per nested column, 82-E3b, 2026-11-18)

A `nested` column can take `provider_config.rules`, a list of rules that each have a `target`, a child `strategy` and an optional `namespace`. Every rule matches on the parsed cell before anything is written, and each rule draws on its own identity. Two rules that reach the same position, or an ancestor and its descendant, fail the column. The single `target` and `strategy` form works as before.

New reason codes: `plan/nested_rules_and_target_both_set`, `plan/nested_rules_empty`, `plan/nested_rule_target_duplicate`, `plan/nested_rules_code_set_repeated` and `runtime/nested_rules_overlap`.
