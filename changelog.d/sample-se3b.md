### Added (lazy fixed-width source, SAMPLE-SE3b, 2026-11-14)

`decoy_engine.profile.FixedWidthLazySource` reads a fixed-width file as bounded Arrow batches behind the `LazySource` surface, through the one fixed-width record parser. The schema comes from the layout, the row count is one framing pass, and a file that changes between the count and the read is refused with `runtime.lazy_source_changed`. Nothing in the run path uses it yet; it is the fixed-width backend for the stream route.
