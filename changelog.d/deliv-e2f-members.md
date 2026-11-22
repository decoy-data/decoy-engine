### Added (publication members, DELIV E2f, 2026-11-22)

`publish_unit` takes `members=[Member(path, role), ...]` beside `tables=`. A member can sit in a nested folder, be a CSV or fixed-width table, or have the role `quarantine` or `report`. In the `decoy-publication/v1` descriptor, `rows` is now `null` for every member that is not a `.parquet` table (the key stays required), and the path rule is shared by writer and reader: at most 8 components, no duplicate, no path that is a folder of another, no reserved name.

The publisher now refuses a stage that holds any entry no member names (a stray file, a link, a special file, an empty folder). `StageDir` gains `open_subdir` and `entries`, which never follow a link; `open_subdir` gives a read-only view.

A reader older than this release that meets a unit with `rows: null`, a `quarantine` or `report` member, or a nested path cannot load its descriptor and treats the folder as occupied, so it refuses and never overwrites the unit. Rerunning the same run id on such a reader refuses; a new run id is unaffected.
