### Changed (starter_config reads model hits, INIT-SCAN-SCAFFOLD E2, 2026-11-26)

`starter_config` now reads `TableScan.model_hits`. With no confident regex match, the first high-band classifier hit writes the entry of its detector (`source="classifier"`, `live=False`); a date detector without a complete format still writes `redact`. A confident regex match always wins. Review-band classifier hits and NER hits never change an entry. Every hit adds one line of evidence to the column's note (model id, version, detector id, band or rate bucket, no cell text), and a hit that disagrees with the regex match says the regex was kept.

`ColumnSuggestion.live` now means a deterministic rule chose the entry (regex, declared key, integer-unique hash, fallback). It is false when a model chose it. Before, it meant "written into the config", which is true of every starter entry. `ColumnSuggestion.decided_by` is new and read-only: `declared_key`, `regex`, `classifier`, `integer_key` or `fallback`. `confident_matches` in `_starter_inference` is now the one rule for a confident regex match.

`starter_config` refuses a scan whose table carries `scan_header_suspect`, with the new config reason `config/starter_header_suspect` at `tables[<index>]`. The message names no table or column.
