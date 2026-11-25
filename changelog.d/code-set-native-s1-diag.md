### Fixed (code_set diagnostics, CODE-SET-NATIVE, 2026-11-25)

`code_set` error text, `codesets verify` reports and corpus evidence no longer carry URL credentials, a corpus label or an OS error message. A locator that starts with a URL scheme is shown without its userinfo, query and fragment, including a password that contains `@` and a Windows backslash form; a local path that only contains `:` and `@` is shown as written. An unsupported `mode` is refused when the column's config is read, so a column with no non-null row is refused too.

A `code_set` `corpus_source: customer:<locator>` that holds URL userinfo, or a query or fragment on a remote URL, is refused at `decoy validate` and compile with `code_set_corpus_source_credentials`. The locator would otherwise be copied into the plan YAML. Clean URLs and local paths still pass.
