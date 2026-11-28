### Fixed (Fixed native type error text, F31-AE6, 2026-11-25)

When a keyed-hash or index derivation rejects a column whose Arrow type the native kernel does not admit, the `GenerationError` message is now the fixed text `the native kernel does not admit the input column type`. The error code `native_type_not_admitted` is unchanged. The message no longer carries the Arrow type, so struct field names and field metadata values from the caller's data cannot reach logs or error reports. The error also no longer chains the native exception as its cause or context.
