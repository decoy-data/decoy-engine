Breaking: a plain run now gives an untouched list, large list, fixed-size list, struct or map column its source type, not an inferred one.

### Fixed (nested passthrough columns keep their type, CHUNKED-STRUCT, 2026-11-21)

`run_mask_pipeline_chunked` no longer raises `unhashable type: 'dict'` on a source with a struct,
list or map column that passes through, and a null-only chunk no longer breaks the concatenation.
An untouched nested column now keeps its source field type on every pandas rebuild route: an int32
struct field no longer widens, a large or fixed-size list no longer becomes `list`, and an all-null
column no longer becomes `null`. A table whose columns are all untouched maps or nested types keeps
its row count instead of raising `ArrowInvalid`.
