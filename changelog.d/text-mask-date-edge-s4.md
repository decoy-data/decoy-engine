### Fixed (text_mask date spans at the calendar edge, DATE-RANGE-SENTINEL S4, 2026-11-27)

A `text_mask` date span that the `date_shift` offset would move past year 1 or year 9999, such as `9999-12-31` with a positive offset, used to stop the run with a bare `OverflowError`. It now becomes the configured `token`, the same result as a date span that does not parse. The rest of the cell is masked as before. The token holds no part of the source date, and no log line or error names it.
