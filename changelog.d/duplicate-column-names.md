Breaking: a config that lists the same column name twice in one table's `columns` is now refused when it is validated. Before, the later entry won on every lane, so `[{name: s, strategy: redact}, {name: s, strategy: passthrough}]` shipped `s` unmasked and the redact entry was dropped without a message. Names are compared exactly, the same rule the source-schema checks use. The same name in two different tables is still allowed. No shipped example, template or fixture config listed a column twice.

### Fixed (one duplicate-name check for mask and generate columns, DUP-COLS, 2026-11-20)

The `TableConfig` validator that refused repeated generate columns now covers `columns` too, with one scan for both. The generate case keeps `config/generate_column_duplicate`. New reason, pending: `config/column_duplicate`, reported at `tables[i].columns[j].name` for the second and each later repeat.
