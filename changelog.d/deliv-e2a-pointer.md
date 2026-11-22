### Added (managed delivery pointer, DELIV E2a, 2026-11-21)

`decoy_engine.publication` now exports `CurrentPointer`, `LocalPointerStore`, `PointerState`, `PointerResult`, `PointerStore`, `PointerUnreadable` and `read_value`. They read and swap one small pointer file under its F22 lock with a compare-and-swap on the raw bytes. The write uses a new private file-access label, `pointer`: it fsyncs the stage and the parent directory, and a parent fsync failure after the replace is reported as `uncertain`, not swallowed. No existing output changes.
