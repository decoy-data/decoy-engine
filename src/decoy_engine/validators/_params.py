"""Value-free parameter parsing shared by every validator constructor.

Python's `float()`, `int()` and `re.compile()` errors echo the text they were given, and a config
value can be a credential. Every validator parameter that needs conversion goes through here, so
an entry point (`build_fold`, `validator_function`, a session) cannot reach a conversion that
skips the check. Messages name the validator and the parameter, never the value.
"""

from __future__ import annotations

import re
from typing import Any

from decoy_engine.errors import ConfigRuleError

__all__ = ["ParamError", "compile_pattern", "numeric_param"]


class ParamError(ConfigRuleError):
    """A validator parameter is unusable. The message names the parameter, never its value.

    A ``ConfigRuleError``, so the reason adapter classifies it as a config failure."""

    def at_entry(self, index: int) -> ParamError:
        """The same refusal located at ``validators`` entry ``index``, with no exception context."""
        return ParamError(f"validators entry {index}: {self.message}")


def numeric_param(
    params: dict[str, Any], name: str, *, kind: type, default: float, validator: str
) -> Any:
    """Read ``params[name]`` as an int or a float, checked by type before any conversion.

    A string that parses as the number is accepted, because quoted YAML (``min_rows: "50"``)
    always worked.

    Raises:
        ParamError: The value is a bool, a string that is not a number, or not an int
            (``kind=int``) or int/float (``kind=float``). The message never carries the value.
    """
    if name not in params:
        return default
    value = params[name]
    noun = "a number" if kind is float else "an integer"
    if isinstance(value, str):
        # `int()` and `float()` echo the text they reject, so the failure is raised after the
        # handler with no exception context.
        parsed: Any = None
        try:
            parsed = kind(value)
        except ValueError:
            pass
        if parsed is None:
            raise ParamError(f"{validator} validator: params.{name} must be {noun}.")
        return parsed
    accepted = (int, float) if kind is float else (int,)
    if isinstance(value, bool) or not isinstance(value, accepted):
        raise ParamError(f"{validator} validator: params.{name} must be {noun}.")
    return kind(value)


def compile_pattern(pattern: str, *, validator: str) -> re.Pattern[str]:
    """Compile ``pattern`` with an error that never carries the pattern text.

    `re.error` messages can quote part of the pattern (an invalid group name does), so the
    failure is recorded in the handler and raised after it, with no exception context.

    Raises:
        ParamError: The pattern does not compile.
    """
    compiled: re.Pattern[str] | None = None
    try:
        compiled = re.compile(pattern)
    except re.error:
        pass
    if compiled is None:
        raise ParamError(f"{validator} validator: params.pattern is not a valid regex.")
    return compiled
