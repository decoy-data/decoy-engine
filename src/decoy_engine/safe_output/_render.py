"""Outbound failure text: ``SafeText`` and the one renderer that turns an exception into it.

A sink that prints a failure takes a ``SafeText``, never a ``str``. Three constructors build one:
``SafeText.const`` and ``SafeText.template`` (literals only, checked by a test that walks every
call) and ``render_failure`` (an exception rendered by its registry reason, its registered
value-free message, a coded cause, or its type label). Nothing else can mint one, so text that
reaches a sink was either written as a literal or chosen by this module.

The renderer reads a coded error through ``reason_from_exception``, never ``capture_failure``:
rendering a handled warning must not change which failure a run reports. Third-party and
unregistered exception text is never printed, only the type label. The registry covers engine
raise sites only; a host or CLI sink is held to ``SafeText`` by its own sentry.
"""

from __future__ import annotations

import os
import re
import string
from collections.abc import Mapping
from typing import final

from decoy_engine import reasons
from decoy_engine.reason_adapter import reason_from_exception
from decoy_engine.reasons import ReasonRecord, approve_name
from decoy_engine.safe_output._exception import safe_error_type

_TOKEN = object()
_WITHHELD = "<withheld>"
MAX_PATH_LEN = 512
MAX_MESSAGE_LEN = 500
TRUNCATED_MARKER = " [truncated]"
_MAX_CAUSE_DEPTH = 8


@final
class SafeText:
    """Text that is safe to print: a literal, an approved slot value, or a registry string."""

    __slots__ = ("_text",)
    _text: str

    def __init__(self, text: str, *, _token: object = None) -> None:
        if _token is not _TOKEN or type(text) is not str:
            raise TypeError("SafeText is built by const, template or render_failure only")
        object.__setattr__(self, "_text", text)

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("SafeText is frozen")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("SafeText is frozen")

    @property
    def text(self) -> str:
        return self._text

    def __str__(self) -> str:
        return self._text

    def __repr__(self) -> str:
        return f"SafeText({self._text!r})"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, SafeText) and other._text == self._text

    def __hash__(self) -> int:
        return hash(self._text)

    @classmethod
    def const(cls, literal: str) -> SafeText:
        """A string literal. The literal sentry rejects any other argument at the call site."""
        return cls(literal, _token=_TOKEN)

    @classmethod
    def template(
        cls,
        literal: str,
        *,
        names: Mapping[str, object] | None = None,
        paths: Mapping[str, object] | None = None,
        counts: Mapping[str, int] | None = None,
    ) -> SafeText:
        """A literal with ``{slot}`` fields filled from closed slot kinds.

        A name slot passes ``approve_name`` (shape only, so the literal sentry also refuses a
        value-tagged argument), a path slot must be a short printable locator, and a count slot
        takes a non-negative ``int``. A slot value that fails its check prints ``<withheld>``.
        A slot with no argument, an unused argument or a format spec is a programming error.
        """
        kinds: dict[str, str] = {}
        values: dict[str, object] = {}
        for kind, group in (("name", names), ("path", paths), ("count", counts)):
            for key, value in (group or {}).items():
                if key in kinds:
                    raise ValueError("a template slot is given twice")
                kinds[key], values[key] = kind, value
        out: list[str] = []
        used: set[str] = set()
        for text, field, spec, conversion in string.Formatter().parse(literal):
            out.append(text)
            if field is None:
                continue
            if spec or conversion or not field.isidentifier() or field not in kinds:
                raise ValueError("a template slot is a bare name with a matching argument")
            used.add(field)
            out.append(_slot_text(kinds[field], values[field]))
        if used != set(kinds):
            raise ValueError("a template argument has no slot")
        return cls("".join(out), _token=_TOKEN)

    @classmethod
    def _mint(cls, text: str) -> SafeText:
        """Renderer-owned text built from registry strings and approved parts."""
        return cls(text, _token=_TOKEN)


# A local display path has no scheme (a one-letter drive is not one), no userinfo and no query:
# those are the parts of a locator that carry credentials and signatures.
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]+:")


def _is_local_path(value: str) -> bool:
    return not (_SCHEME.match(value) or "://" in value or "@" in value or "?" in value)


def _slot_text(kind: str, value: object) -> str:
    if kind == "count":
        if type(value) is not int or value < 0:
            raise TypeError("a count slot takes a non-negative int")
        return str(value)
    if kind == "path":
        if isinstance(value, os.PathLike):
            value = os.fspath(value)
        ok = isinstance(value, str) and 0 < len(value) <= MAX_PATH_LEN and value.isprintable()
        return value if ok and isinstance(value, str) and _is_local_path(value) else _WITHHELD
    approved = approve_name(value)
    return approved if approved is not None else _WITHHELD


# Project exception classes whose own message is value-free: every raise of one passes no
# exception or data-value name and sits in no function that copies exception text. Seeded by
# that rule (tests/sentry/safe_output/_registry_rule.py), which the registry sentry re-runs, so a
# raise that later interpolates a value fails the sentry and the class must leave this list.
# Matched by exact type: a subclass or a same-named class elsewhere is not in the registry.
VALUE_FREE_CLASSES: frozenset[str] = frozenset(
    {
        "decoy_engine._canonical._json.CanonicalJsonError",
        "decoy_engine._canonical._json.StrictJsonError",
        "decoy_engine._canonical._strict_spec.SpecRefusedError",
        "decoy_engine.delivery.resume._plan.ResumeRefusedError",
        "decoy_engine.errors.ConfigRuleError",
        "decoy_engine.errors.DecoyError",
        "decoy_engine.errors.EnvFlagError",
        "decoy_engine.errors.FixedWidthParseError",
        "decoy_engine.errors.FixedWidthRecordOverlongError",
        "decoy_engine.errors.FpeChecksumError",
        "decoy_engine.errors.MaskKeyRequiredError",
        "decoy_engine.errors.ValidatorFailedError",
        "decoy_engine.execution._mixed_admission.MixedDeclineError",
        "decoy_engine.execution.native._chunk_schema.NativeChunkSchemaDriftError",
        "decoy_engine.execution.native._crypto_ext.CryptoExtensionUnavailableError",
        "decoy_engine.execution.native._crypto_ext.FpeConfigError",
        "decoy_engine.execution.native._pool_quality.PoolQualityError",
        "decoy_engine.execution.pipeline._cgroup.CgroupMappingError",
        "decoy_engine.fileaccess._types.FileAccessReadError",
        "decoy_engine.fileaccess._types.FileAccessUnavailable",
        "decoy_engine.fileaccess._types.LeafTooLarge",
        "decoy_engine.fileaccess._types.LockTimeout",
        "decoy_engine.io.bounded_reader.CsvMalformed",
        "decoy_engine.io.bounded_reader.CsvRecordExceedsMaxRowBytes",
        "decoy_engine.io.bounded_reader.UnsupportedColumnType",
        "decoy_engine.io.csv_framer.CsvRecordTooLarge",
        "decoy_engine.io.csv_framer.CsvUnterminatedQuote",
        "decoy_engine.keyprovider.MissingMaskSecret",
        "decoy_engine.keyprovider.WeakMaskSecret",
        "decoy_engine.profiling.bound_baseline.BaselineBindingError",
        "decoy_engine.profiling.scan_set_read.ScanSetReadError",
        "decoy_engine.publication._types.PublicationFailed",
        "decoy_engine.publication._types.PublicationRefused",
        "decoy_engine.reasons._identity.UnknownReasonError",
        "decoy_engine.secret_providers.vault.VaultClientConfigError",
        "decoy_engine.transforms._ff1.Ff1Error",
        "decoy_engine.transforms.windowed_date.WindowedDateError",
        "decoy_engine.transforms.windowed_date.WindowedDateParentAnchorNullError",
        "decoy_engine.validation.finding_review.ReviewConflictError",
        "decoy_engine.validation.finding_review.ReviewDismissRefusedError",
        "decoy_engine.validation.finding_review.ReviewIntegrityOffError",
        "decoy_engine.validation.starter_review.ReviewDuplicateError",
        "decoy_engine.validation.starter_review.ReviewEmptyTableError",
        "decoy_engine.validation.starter_review.ReviewStaleError",
        "decoy_engine.validation.starter_review.ReviewUnknownColumnError",
    }
)

# Reasons that say only "no specific reason known": an error that maps to one still has a message
# worth keeping when its class is registered, so it does not count as coded.
_GENERIC_REASONS = frozenset(
    (r.namespace, str(r))
    for r in (
        reasons.decoy.UNEXPECTED_ERROR,
        reasons.decoy.UNREGISTERED_REASON,
        reasons.config.UNTAGGED,
    )
)


def _coded_text(entry: ReasonRecord) -> str | None:
    """The registry summary plus the approved refs of a specific reason, else ``None``."""
    if (entry.namespace, entry.code) in _GENERIC_REASONS:
        return None
    ctx = entry.context
    refs: list[str] = []
    if ctx.object_ref is not None:
        refs.append(SafeText.template("object={ref}", names={"ref": ctx.object_ref}).text)
    if ctx.storage_ref is not None:
        refs.append(SafeText.template("storage={ref}", names={"ref": ctx.storage_ref}).text)
    return entry.summary + (f" ({', '.join(refs)})" if refs else "")


def _render_coded(exc: BaseException) -> SafeText | None:
    text = _coded_text(reason_from_exception(exc))
    return None if text is None else SafeText._mint(text)


def _render_registered(exc: BaseException) -> SafeText | None:
    cls = type(exc)
    if f"{cls.__module__}.{cls.__qualname__}" not in VALUE_FREE_CLASSES:
        return None
    message = "".join(c if c.isprintable() else " " for c in str(exc))
    if len(message) > MAX_MESSAGE_LEN:
        message = message[:MAX_MESSAGE_LEN] + TRUNCATED_MARKER
    return SafeText._mint(message) if message.strip() else None


def _render_cause(exc: BaseException) -> SafeText | None:
    seen = {id(exc)}
    cause = exc.__cause__
    while cause is not None and id(cause) not in seen and len(seen) <= _MAX_CAUSE_DEPTH:
        seen.add(id(cause))
        text = _coded_text(reason_from_exception(cause))
        if text is not None:
            return SafeText._mint(f"{safe_error_type(exc).value} caused by: {text}")
        cause = cause.__cause__
    return None


def _render_label(exc: BaseException) -> SafeText:
    return SafeText._mint(safe_error_type(exc).value)


def render_failure(exc: BaseException) -> SafeText:
    """The outbound text for ``exc``; never raises and never prints unregistered text.

    Picks the first of coded, registered, coded cause, then type label. A helper that fails
    (a registered class with a raising ``__str__``) falls back to the label, and a failing label
    to a fixed line, so a failure inside error handling cannot become a second failure.
    """
    try:
        for helper in (_render_coded, _render_registered, _render_cause):
            text = helper(exc)
            if text is not None:
                return text
    except Exception:
        pass
    try:
        return _render_label(exc)
    except Exception:
        return SafeText.const("Operation failed.")
