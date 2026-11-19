### Fixed (engine imports and opens files on Windows, EW1, 2026-11-18)

Every open flag the engine uses now comes from one module, `fileaccess/_osflags.py`. On POSIX the
values are the same as before. On Windows the POSIX-only flags are 0, and file descriptors open in
binary mode and are not inherited, so a file with the bytes 0x0A, 0x0D or 0x1A reads back as
written. `import decoy_engine` no longer fails on Windows. `RootedFileAccess` raises
`FileAccessUnavailable` where the platform has no directory descriptors.
