### Changed (windowed_date batches its date work, GEN-WINDOWED-BATCH, 2026-11-19)

`windowed_date` now derives the per-row keys in one batch, parses the anchors and formats the dates as vectors, and keeps the per-row numpy draw. Output is the same as before for every input: same dates, same errors, same messages. It is faster for string, `date`, naive `datetime` and naive `Timestamp` anchors. Anything else (mixed types, subclasses, time zones, windows past the nanosecond range) runs the earlier per-row loop.
