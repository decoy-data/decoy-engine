Breaking: `bucketize` with an integer width now turns a finite value of magnitude 2**53 or more, and any infinity, into a `format_error` row error with a null cell. A float width on an `int64[pyarrow]` column now labels a large value instead of raising.

### Fixed (bucketize range errors and float-width integer sources, BUCKET-TOPCODE-NATIVE S1a, 2026-11-24)

Three byte changes in the `bucketize` handler. None of them moves a plan hash or a seed.

- B2: with an integer width, a finite value whose float64 magnitude is at least 2**53 gives one `format_error` row error with the reason `value is out of range under bucketize` and a null cell. Before, the label was rounded or the cast failed with no code.
- B3: with an integer width, positive and negative infinity give the same row error and null cell. Before, the cast failed with no code. A valid NaN is still ordinary missing and gives no error. With quarantine on, the row leaves the main output. With the fail policy, the job fails before it publishes.
- B4: with a float width, an integer source of any pandas dtype is converted to float64 with round-to-nearest before the division. An `int64[pyarrow]` value of magnitude above 2**53 used to raise `ArrowInvalid` with the value in the message. It now gets the label NumPy `int64` and nullable `Int64` already had: 9007199254740993 at width 2.5 gives lower `9007199254740992.0`. Values below 2**53 and float sources are unchanged.

The range exit uses one function, `kernel.integer_width_exit_mask`, and one limit, `contracts.bucketize_width.EXACT_INT_BOUND`, which the `top_code` handler and compile check now share. The reason text has one owner, `contracts/format_error_reasons.py`.
