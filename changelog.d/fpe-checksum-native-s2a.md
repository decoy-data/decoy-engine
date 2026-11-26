### Changed (Companion check-digit arithmetic, FPE-CHECKSUM-NATIVE S2a, 2026-11-25)

The native companion now holds one Rust copy of the luhn, npi, ean13, gtin, isbn13 and vin check-digit rules, locked to `decoy_engine.checksums` by a generated known-answer corpus. The FPE kernel and the text_redact `pan` and `npi` detectors call it. No masked value and no detector result changes.
