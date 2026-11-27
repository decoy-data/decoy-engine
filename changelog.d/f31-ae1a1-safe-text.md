### Added (internal safe-text leaf, F31 AE1a1, 2026-11-24)

An internal `SafeText` type holds text written as a string literal in the calling code. An AST
sentry fails the build for any call that passes anything else, so a row value cannot become safe
text. At run time a refusal withholds the text and logs one warning per call site with no value;
under the test-only strict switch it raises instead.
No public name changes. Later F31 slices route error and log text through it.
