### Fixed (a table cannot take a reserved publication member name, F26-RESERVED-NAME, 2026-11-21)

`publish_unit` and `publish_tables` now refuse a table named like the publication stage marker (`.decoy-publication-stage`) as well as the descriptor (`_decoy_publication.json`), in any letter case, before any file is touched. Before, only the exact descriptor name was refused. The error text is unchanged and does not name the table. Both names now come from one exported set, `fileaccess.RESERVED_MEMBER_NAMES`.
