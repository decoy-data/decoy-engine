### Added (native companion missing notice, NATIVE-MISSING-WARN E1, 2026-11-21)

`ExecutionResult` gains `native_fallback_code`. It is `native_companion_missing` when the compiled plan needs a compiled kernel (hash, faker, categorical, bucket_perturb, group_key, date_shift or fpe columns) and none of the kernels it needs is available, so masking ran in Python. It is `None` otherwise. `run_pipeline` sets it after the route returns, so every route reports the same way, and a caller such as the CLI can print one notice. The field is hidden from `repr`, not compared and never written to the result document, so outputs and documents are byte-identical to before.

The new reason `warning/native_companion_missing` is pending. `run_pipeline_isolated` does not carry the field.
