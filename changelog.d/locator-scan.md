### Added (locator credential recognizer, LOCATOR-CREDENTIALS E-S1, 2026-11-25)

`decoy_engine.safe_output` gains `scan_locator`, `LocatorScan` and `LocatorKind`: one recognizer that decides whether a file locator carries credentials (userinfo, a non-empty query or fragment, an authority that is not a host) and returns the text to show and the text safe to publish to a third party.

`fileaccess.shown` now returns the locator with credentials replaced by `<redacted>` under the ambient policy. Engine messages that showed a credential-bearing URL now show it redacted. Nothing outside the replaced span changes: case, separators and backslashes stay as written.
