### Added (internal safe-text leaf, F31 AE1a1, 2026-11-24)

An internal `SafeText` type holds text that provably came from a string literal in the calling
code, so a row value can never be printed as safe text. A check that fails withholds the text and
logs one warning per call site with no value; under the test-only strict switch it raises instead.
No public name changes. Later F31 slices route error and log text through it.
