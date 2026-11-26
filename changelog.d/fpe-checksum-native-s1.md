### Changed (One FPE checksum decision, FPE-CHECKSUM-NATIVE-S1, 2026-11-25)

Every route that admits an fpe column now asks one function whether a checksum config may run natively. Today none may, so a checksum column still declines to the pandas oracle and its output does not change. The compiled kernel wrapper refuses a direct checksum call before the FFI with a value-free error.

An fpe charset or checksum scheme string no longer appears in plan, kernel or oracle error messages. The reason codes are unchanged. A checksum scheme that is not a string now declines with the coded reason instead of raising `TypeError` on the native routes. A nonempty list as the scheme still raises `TypeError` at plan validation.

Unmask refuses an unrecognized checksum scheme before any row work and never copies the configured string into its report. A nondigit in an NPI or ISBN-13 prefix raises a checksum error that does not quote it, and an oversized fixed-width cell is refused without a copy sized to the cell.

An over-length NPI or other fixed-width value now reports "more than N" instead of a count that was cut short by the memory bound. Plan compile, the cipher and unmask now classify an FPE checksum scheme in one place (`checksums.classify_fpe_scheme`), so an all-null `iban` column is refused by unmask just like a populated one. Each caller keeps its own error code.
