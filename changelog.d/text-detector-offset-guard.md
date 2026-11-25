### Fixed (native text_redact detector, TEXT-REDACT-RUST-SPLICE S0, 2026-11-24)

The Rust text_redact detector now declines a cell whose byte length does not fit its 32-bit offsets. `text_redact_candidates` and `text_mask_detect_splice` return their usual `None` decline for such a cell, and every released core already sends a declined cell to the Python path. Before this, a cell longer than 4 GiB could wrap an end offset and leave part of a match unredacted. The release wheel smoke test now also refuses a wheel built with the test-only `test-detector-offset-limit` feature.
