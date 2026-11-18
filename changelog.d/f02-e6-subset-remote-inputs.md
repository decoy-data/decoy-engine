### Added (subset inputs for remote sources, F02-E6, 2026-11-18)

`subset_inputs_from_config(config, *, local_copies=None)` takes a mapping from table name to a local path. An `s3`, `gcs` or `sftp` source with a copy in that mapping becomes a local `SubsetSource` on the copy, so a caller can fetch the object first and subset it. Without a copy the source is still refused as `config.subset_source_type_unsupported`; the text now names the table only and no longer echoes the source type. A `file` source ignores the mapping. The caller owns fetching and removing each copy.

Three codes are registered ahead of the callers that raise them: `config/remote_uri_invalid` and `runtime/spool_disk_full` (the disk or quota for the local copy of a remote source is too small; listed in `CAPACITY_EXCLUSIONS` as disk, not memory, so it never maps to a capacity verdict), and the warning `warning/sftp_lock_not_removed`.
