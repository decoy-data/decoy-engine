### Added (anonymity risk and utility report, V2-3.5, 2026-11-12)

V2 track, built ahead, opt-in by import only. `decoy_engine.anonymize.report.build_risk_utility_report`
builds the `risk-utility-report/v1` document for a release chosen by the enforcement search:
prosecutor re-identification risk (highest, average, records at risk above a required threshold),
journalist and marketer risk only against a supplied population table, the search's loss figures and
suppression counts, the chosen node and the privacy models met, and fixed statements of the
assumptions made and what the analysis does not establish. It is value-free, deterministic, and read
back by `RiskUtilityReportRead`, a reader derived from the writer through
`decoy_engine._value_free.derive_read`; a sample is locked in the compatibility corpus.
`decoy_engine.quality.anonymity` gains `measure_reidentification_risk`, `ReidentificationRiskReport`
and `check_risk_threshold`. No config key, strategy, catalog row, run behaviour or V1 file changes.
