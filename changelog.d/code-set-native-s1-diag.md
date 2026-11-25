### Fixed (code_set diagnostics, CODE-SET-NATIVE, 2026-11-25)

`code_set` error text, `codesets verify` reports and corpus evidence no longer carry URL credentials, a corpus label or an OS error message. A locator that starts with a URL scheme is shown without its userinfo, query and fragment, including a password that contains `@` and a Windows backslash form; a local path that only contains `:` and `@` is shown as written. An unsupported `mode` is refused when the column's config is read, so a column with no non-null row is refused too.
