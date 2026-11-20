### Added (international check-digit schemes, V1P-2.1, 2026-11-06)

- `decoy_engine.checksums.validate` and `calc_check_digit` accept nine national identifier schemes:
  `gb_nhs`, `ca_sin`, `in_aadhaar`, `au_tfn`, `de_idnr`, `fr_nir`, `es_dni`, `es_nie` and
  `it_codice_fiscale`, validated through python-stdnum (already a core dependency). A malformed body
  raises `ValueError`; an NHS or TFN body with no valid check digit raises `ValueError`.
- No V1 behavior changes: FPE checksum mode keeps its seven schemes (`checksums._FPE_CHECKSUM_SCHEMES`)
  and refuses the new ones with the existing `plan.fpe_checksum_unknown_scheme`, whose message now
  says "unknown or FPE-unsupported" and lists the FPE schemes. The built-in validator names are
  unchanged.
- V1+ is the track of post-CLI-V1 features built ahead of time without changing V1 behavior. Plan:
  `docs/plans/2026-11-06-v1plus-p2.1-check-digit-schemes.md`.
