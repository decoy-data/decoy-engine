Breaking: the two v0.16.0 route tombstones are removed from the reason registry; a record that names one now reads as `decoy/unknown_reason_from_future`.

### Removed (two route tombstones, RETIRED-NAME E1, 2026-11-16)

The registry no longer holds the two v0.16.0 route tombstones, the reasons that `route/post_scan_integrity_requested` and `route/post_scan_integrity` replaced. `reasons.find` returns `None` for them, and `reasons.route` no longer has their symbols. A persisted record that names one decodes as `decoy/unknown_reason_from_future`, with the original identity kept in its context. The registry version stays `1.29.0`.
