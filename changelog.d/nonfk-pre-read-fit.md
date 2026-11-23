Breaking: a job with no foreign keys under `auto` is now refused with `nonfk_full_frame_capacity_exceeded` in three more places where it used to start and be killed for memory: before a lazy Parquet source is read whole, before a resident table is copied for its transforms, and after a mixed generate and mask job declines to the full-frame route.

### Added (resident fit before the read, the transform copy and a mixed decline, NONFK-OOM, 2026-11-23)

The no-FK capacity check now runs at the three points where the engine makes a whole-table copy
before it has chosen a route. All three use the same ceilings as the route check: only a strict
lower bound above the host or cgroup kill ceiling refuses, and a bound between 85% of it and the
ceiling runs as before.

- Before a lazy Parquet source is read whole (the `resident_fallback` read), the bound is the
  footer input bytes of the tables about to be read. A table the route may still run chunked is not
  charged a pandas copy; a vault run, which is forced to full-frame, is. A source with no footer is
  not priced.
- Before a resident table is copied to pandas for its transforms, the bound is every resident input
  byte plus that table's pandas copy. A bound in the gap between 85% and 100% of the ceiling caps
  the final verdict at `route/nonfk_full_frame_unverified`.
- When a mixed job declines after generation and continues on the full-frame route, the replaced
  decision is priced like any no-FK full-frame decision, with the generated tables counted at their
  input bytes, before the lazy mask sources are read.

`execution_mode` other than `auto` and any job with a foreign key are not priced. The CLI's own
whole read of a source is not covered here.
