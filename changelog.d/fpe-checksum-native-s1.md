### Changed (One FPE checksum decision, FPE-CHECKSUM-NATIVE-S1, 2026-11-25)

Every route that admits an fpe column now asks one function whether a checksum config may run natively. Today none may, so a checksum column still declines to the pandas oracle and its output does not change. The compiled kernel wrapper refuses a direct checksum call before the FFI with a value-free error.

An fpe charset or checksum scheme string no longer appears in plan, kernel or oracle error messages. The reason codes are unchanged. A checksum scheme that is not a string now declines with the coded reason instead of raising `TypeError`.
