Breaking: date_shift on a date column runs natively; a date outside years 1 to 9999 is a row error that keeps the source instead of failing the job.

### Changed (date_shift runs natively on date32 columns, DATE-SHIFT-TYPED S1, 2026-11-24)

A `date_shift` column whose plan shape is `DATE` over a `date32` source now runs on the compiled
index kernel on the unified slice, the chunked route and the sequential route. It needs a
namespace, and no `group_by`, `when:` or `preserve_values`. Offsets are unchanged: the key is the
date's ISO text, so a typed date and the same date held as ISO text get the same shift in one
namespace. The output keeps the `date32` type on every route, and the chunked schema rule pins it
to `date32` instead of `string`.

The oracle and the native route now share one arithmetic, `transforms.date_shift.shift_typed_days`.
A `date32` value outside years 1 to 9999, or one whose shift leaves that range, is a
`format_error` row error that keeps the source on the native routes. Before, that row failed
the job. The full-frame and sequential routes read the whole table through pandas, which cannot
hold such a date, so both fail the job with the coded error `full_frame_value_unrepresentable`,
which names the table and column and no value. Before, sequential failed with an uncoded pandas
error that quoted the year.

Two new route reason codes, registered unreleased: `date_shift_typed_preserve_not_native`
(`preserve_values` on a typed column) and `date_shift_typed_type_not_native` (a typed shape over a
resident type other than `date32`, such as `date64`). Both keep the column on the oracle.
