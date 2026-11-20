### Changed (masked int, decimal and binary columns keep large tables chunked, NONFK-OOM, 2026-11-20)

Under `auto`, a large non-FK table with a masked integer-with-nulls, decimal or binary column no
longer falls back to full-frame when the column uses `hash` (no `when:`), `redact` (a string
`redact_with`) or deterministic `faker` (integer sources only) and no other column reads it. The
output equals the full-frame result in type and value. Other strategies on these types, a `when:`
on the column and `chunked_dispatcher_enabled=False` keep the full-frame route.
