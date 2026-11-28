"""Plan-compile check for fpe columns (Sprint 2 honesty pack, S6, GATE-1 Q4).

Added as its own module for the same reason as `_checks_bucketize.py`: avoid
growing `plan/_checks.py` past its size ceiling (see the SP-10 comment in
`tests/sentry/test_module_size.py`).

Discovery 0.1 (guide section 0.1, DISCOVERY 2, 2026-07-04): `_fpe.py:70`
(pre-slice) returned `df, []`, a silent whole-column passthrough (V1
behavior), when the resolved charset has fewer than 2 distinct characters.
This is the same fail-open shape #13 closed for truncate/bucketize/
categorical (a masking strategy must never silently pass the source column
through on a bad config). This module rejects the shape at compile time,
before any row is masked; `FpeStrategyHandler.run` additionally raises
`StrategyError` on the same shape as a defense-in-depth backstop.

Task 5.2 (FF1 primitive swap, plan v2 body): a custom charset with a
duplicate symbol used to be silently deduplicated before this length check
ever ran. FF1 requires an ordered, duplicate-free alphabet (a duplicate would
make decode ambiguous); a duplicate is now its own rejected shape
(`fpe_charset_duplicate_symbols`), checked BEFORE the length check, not
folded into it.

Task 5.2 P6-final: a custom charset is also restricted to printable ASCII
(0x21-0x7E), rejected as `fpe_charset_non_ascii`. Every named entry in
`_CHARSETS` already satisfies this, so only a literal charset spec can ever
trip it. Restricting to this range sidesteps Unicode grapheme segmentation
entirely (one code point is one symbol, trivially, within it).

Reuses `_CHARSETS` / `check_charset_unique` / `check_charset_ascii_printable`
from `transforms/fpe.py` as the single source of truth for named charsets and
these two rules (no duplicated table or check to drift out of sync).

This module exports `check_fpe_charset_config` and `check_fpe_checksum_scheme`.
"""

from __future__ import annotations

from typing import Any

from decoy_engine import reasons
from decoy_engine._config_text import Name, Problem, config_position, config_refusal
from decoy_engine._error_base import raise_bare
from decoy_engine.errors import FpeUnencryptableError
from decoy_engine.plan._errors import refusal_error
from decoy_engine.transforms.fpe import (
    _CHARSETS,
    FPE_CHARSET_DUPLICATE_TEXT,
    FPE_CHARSET_NON_ASCII_TEXT,
    check_charset_ascii_printable,
    check_charset_unique,
)


def check_fpe_charset_config(config: dict[str, Any]) -> None:
    """Reject fpe columns whose resolved charset has a duplicate symbol,
    a non-ASCII character, or fewer than 2 distinct characters.

    Compile-check ownership table row #25 (Sprint 2 honesty pack S6,
    GATE-1 Q4, 2026-07-04; duplicate-symbol and ASCII rules added Task 5.2).
    Mirrors `FpeStrategyHandler.run` exactly: the charset resolves via
    `_CHARSETS.get(charset_spec, charset_spec)` (a named charset, e.g.
    "digits", or a literal charset string), taken AS GIVEN (no silent
    dedup). A duplicate symbol is rejected outright (FF1's alphabet must be
    ordered and unique); a non-ASCII character is rejected (custom fpe
    charsets are restricted to printable ASCII, 0x21-0x7E); fewer than 2
    distinct characters is degenerate: `fpe_encrypt_value`'s FF1 permutation
    has no non-trivial domain to permute over, and the pre-slice handler
    behavior was to skip masking the whole column, which is guaranteed to
    leave it unmasked at run today.

    Config-only (no profile, no source data): safe to run in both compile
    branches and in `run_config_only_checks`. Validation never mutates
    (per engine rule).

    Args:
        config: Raw pipeline config dict.

    Raises:
        PlanCompileError: the resolved charset has a duplicate symbol, a
            non-ASCII character, or fewer than 2 distinct characters.
    """
    tables = config.get("tables", []) if isinstance(config.get("tables"), list) else []
    for table_entry in tables:
        if not isinstance(table_entry, dict):
            continue
        table_name = table_entry.get("name", "?")
        for col_entry in table_entry.get("columns", []) or []:
            if not isinstance(col_entry, dict):
                continue
            if col_entry.get("strategy") != "fpe":
                continue
            col_name = col_entry.get("name", "?")
            pc = col_entry.get("provider_config")
            if not isinstance(pc, dict):
                pc = {}

            charset_spec = pc.get("charset", "digits")
            resolved = _CHARSETS.get(charset_spec, charset_spec)
            if not isinstance(resolved, str):
                resolved = str(resolved)
            at_charset = config_position(
                "tables", Name(table_name), "columns", Name(col_name), "provider_config", "charset"
            )
            duplicate = False
            try:
                check_charset_unique(charset_spec, resolved)
            except FpeUnencryptableError:
                duplicate = True
            if duplicate:
                duplicate_refusal = config_refusal(
                    at_charset, Problem.NOT_ALLOWED, hint=FPE_CHARSET_DUPLICATE_TEXT
                )
                raise_bare(
                    refusal_error(reasons.plan.FPE_CHARSET_DUPLICATE_SYMBOLS, duplicate_refusal)
                )
            non_ascii = False
            try:
                check_charset_ascii_printable(resolved)
            except FpeUnencryptableError:
                non_ascii = True
            if non_ascii:
                ascii_refusal = config_refusal(
                    at_charset, Problem.NOT_ALLOWED, hint=FPE_CHARSET_NON_ASCII_TEXT
                )
                raise_bare(refusal_error(reasons.plan.FPE_CHARSET_NON_ASCII, ascii_refusal))
            if len(resolved) < 2:
                degenerate_refusal = config_refusal(
                    at_charset,
                    Problem.NOT_ALLOWED,
                    hint=(
                        "the fpe charset has fewer than 2 distinct characters. A degenerate "
                        "charset leaves the column unmasked at run; use a named charset "
                        "(digits/alpha/ALPHA/alphanum/ALPHANUM) or a literal charset with at "
                        "least 2 distinct characters"
                    ),
                )
                raise_bare(refusal_error(reasons.plan.FPE_CHARSET_DEGENERATE, degenerate_refusal))


def check_fpe_checksum_scheme(config: dict[str, Any]) -> None:
    """Reject FPE columns whose ``checksum`` param is unknown, unsupported, or charset-incompatible.

    Compile-check ownership table row #15 (SP-04 / P5.INFRA.1 remediation).

    Three failure modes caught here:

    1. Unknown scheme (typo, e.g. ``checksum: ibna``): Decoy forbids silent
       misconfiguration passthrough.  Any value not in
       ``checksums.classify_fpe_scheme`` raises with code
       ``fpe_checksum_unknown_scheme``.

    2. IBAN (``checksum: iban``): per-country BBAN structure enforced by
       ``stdnum.iban.validate`` cannot be satisfied by a format-preservation
       permutation.  Raises with code ``fpe_checksum_iban_unsupported``.
       IBAN columns may still use ``checksums.validate('iban', ...)`` for
       validation-only use cases; only the FPE mode is rejected here.

    3. Charset incompatible with scheme (e.g. ``checksum: vin`` with a
       digits-only charset): a charset that cannot represent the scheme's
       required alphabet causes values to pass through unmasked at runtime.
       With ``preserve_separators=True`` (the default), missing characters are
       treated as separators; the extracted body falls below the scheme's L1
       min-length guard and the value is returned verbatim.  Raises with code
       ``fpe_checksum_charset_incompatible``.  A charset that is a strict
       superset of the required alphabet is accepted: the runtime already
       constrains the permutation to the scheme's own alphabet.

    Config-only (no profile, no source data): safe to run in --no-profile
    mode and in ``run_config_only_checks``.
    """
    from decoy_engine.checksums import classify_fpe_scheme, required_charset

    tables = config.get("tables", []) if isinstance(config.get("tables"), list) else []
    for table_entry in tables:
        if not isinstance(table_entry, dict):
            continue
        table_name = table_entry.get("name", "?")
        for col_entry in table_entry.get("columns", []) or []:
            if not isinstance(col_entry, dict):
                continue
            if col_entry.get("strategy") != "fpe":
                continue
            provider_config = col_entry.get("provider_config") or {}
            checksum = (
                provider_config.get("checksum") if isinstance(provider_config, dict) else None
            )
            if not checksum:
                continue
            col_name = col_entry.get("name", "?")
            verdict = classify_fpe_scheme(checksum)
            at_checksum = config_position(
                "tables", Name(table_name), "columns", Name(col_name), "provider_config", "checksum"
            )
            if verdict == "unknown":
                unknown_refusal = config_refusal(
                    at_checksum,
                    Problem.NOT_ALLOWED,
                    hint=(
                        "strategy fpe has an unknown checksum scheme. Check for typos; valid "
                        "fpe checksum schemes are luhn, npi, vin, isbn13, ean13, gtin "
                        "(iban is not supported for FPE mode)"
                    ),
                )
                raise_bare(refusal_error(reasons.plan.FPE_CHECKSUM_UNKNOWN_SCHEME, unknown_refusal))
            if verdict == "unsupported":
                iban_refusal = config_refusal(
                    at_checksum,
                    Problem.NOT_ALLOWED,
                    hint=(
                        "strategy fpe does not support checksum 'iban': per-country BBAN "
                        "structure (enforced by stdnum.iban.validate) cannot be satisfied by a "
                        "format-preservation permutation. Use validate-only or a different "
                        "strategy for IBAN columns"
                    ),
                )
                raise_bare(refusal_error(reasons.plan.FPE_CHECKSUM_IBAN_UNSUPPORTED, iban_refusal))
            # Charset-vs-scheme compatibility: a charset missing characters
            # required by the scheme causes values to pass through unmasked
            # (silent no-op).  Fail closed at compile.
            charset_spec = (
                provider_config.get("charset", "digits")
                if isinstance(provider_config, dict)
                else "digits"
            )
            charset_str = _CHARSETS.get(str(charset_spec), str(charset_spec))
            charset_set = frozenset(charset_str)
            required = required_charset(checksum)
            if required is not None:
                missing = required - charset_set
                if missing:
                    at_charset = config_position(
                        "tables",
                        Name(table_name),
                        "columns",
                        Name(col_name),
                        "provider_config",
                        "charset",
                    )
                    incompatible_refusal = config_refusal(
                        at_charset,
                        Problem.MISMATCH,
                        hint=(
                            "strategy fpe: the charset is missing characters the checksum "
                            "scheme requires. A charset that cannot represent the scheme "
                            "alphabet causes source values to pass through unmasked (silent "
                            "no-op). Use a charset that is a superset of the scheme alphabet "
                            "(e.g. 'ALPHANUM' for vin, 'digits' for luhn/npi/ean13/isbn13/gtin)"
                        ),
                    )
                    raise_bare(
                        refusal_error(
                            reasons.plan.FPE_CHECKSUM_CHARSET_INCOMPATIBLE, incompatible_refusal
                        )
                    )
