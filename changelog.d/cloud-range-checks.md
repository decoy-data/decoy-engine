### Fixed (S3 ranged reads are checked before the body is read, F25 G7-1, 2026-11-25)

A profile read of an S3 object accepted any answer to a range request. A store that ignored the
range and sent the whole object, or answered other bytes, was read as if it were the bytes asked
for. S3 and GCS now share one check: the answer must be a 206 whose `Content-Range` is exactly the
range asked and whose `Content-Length`, when sent, matches. Anything else stops the read with the
existing `unexpected` connector error before a byte of the body is read. GCS size and generation
come from one metadata reload in the connector stream and in the profile reader.

A CSV sample or schema read over a wide window parses as it did before the value-free change, so
its memory use is the same as before. A column that mixes numbers and text is still read as text in
`schema()`. Parquet `to_frame` keeps `attrs` from the file metadata, as `pandas.read_parquet` does.
