### Added (Array bucketize and top_code kernels, BTN-S1K, 2026-11-25)

Bucketize and top_code now have shared array kernels that give the same labels as the pandas strategies. They are available for native and out-of-core integration and are not yet used by those paths. A bucketize value outside the supported range becomes a row error. A bucketize integer width of 2**53 or more is now refused by the plan check. A float width works on any integer dtype, and top_code prints its labels from the integer source.

Plan checks and kernels refuse a label or truncate mask character that has no UTF-8 form. The error messages for top_code bounds, presets and labels, and for truncate, name the column and the rule but no longer repeat the submitted value.
