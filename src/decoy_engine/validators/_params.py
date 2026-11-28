"""Value-free parameter parsing shared by every validator constructor.

Python's `float()`, `int()` and `re.compile()` errors echo the text they were given, and a config
value can be a credential. Every validator parameter that needs conversion goes through here, so
an entry point (`build_fold`, `validator_function`, a session) cannot reach a conversion that
skips the check. Messages name the validator and the parameter, never the value.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

from decoy_engine._config_text import (
    ConfigPosition,
    Expected,
    Name,
    Problem,
    Refusal,
    config_position,
    config_refusal,
)
from decoy_engine.errors import ConfigRuleError

__all__ = ["ParamError", "compile_pattern", "numeric_param"]


class _Why(Enum):
    """The three refusals a validator parameter can earn. `config_refusal` takes its problem,
    expectation and hint as literals, so each has its own call below."""

    NOT_AN_INTEGER = "integer"
    NOT_A_NUMBER = "number"
    BAD_PATTERN = "pattern"


@dataclass(frozen=True)
class _Refused:
    """What a refusal is about, kept so it can be rebuilt at a ``validators`` entry."""

    validator: str
    param: str
    why: _Why


def _position(index: int | None, param: str) -> ConfigPosition:
    if index is None:
        return config_position("params", Name(param))
    return config_position("validators", index, "params", Name(param))


def _refusal(refused: _Refused, position: ConfigPosition) -> Refusal:
    if refused.why is _Why.NOT_AN_INTEGER:
        return config_refusal(
            position,
            Problem.WRONG_TYPE,
            expected=Expected.INTEGER,
            names=(Name(refused.validator),),
        )
    if refused.why is _Why.NOT_A_NUMBER:
        return config_refusal(
            position, Problem.WRONG_TYPE, expected=Expected.NUMBER, names=(Name(refused.validator),)
        )
    return config_refusal(
        position, Problem.UNPARSEABLE, names=(Name(refused.validator),), hint="not a valid regex"
    )


def _error(refusal: Refusal, refused: _Refused) -> ParamError:
    error = ParamError(refusal.text)
    error.refused = refused
    return error


def _param_error(refused: _Refused, index: int | None) -> ParamError:
    """The refusal built through ``config_refusal``: the text names the entry, the parameter and
    the validator, never the value."""
    return _error(_refusal(refused, _position(index, refused.param)), refused)


class ParamError(ConfigRuleError):
    """A validator parameter is unusable. The message names the parameter, never its value.

    A ``ConfigRuleError``, so the reason adapter classifies it as a config failure."""

    refused: _Refused

    def at_entry(self, index: int) -> ParamError:
        """The same refusal located at ``validators`` entry ``index``, with no exception context."""
        return _param_error(self.refused, index)


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
    why = _Why.NOT_A_NUMBER if kind is float else _Why.NOT_AN_INTEGER
    if isinstance(value, str):
        # `int()` and `float()` echo the text they reject, so the failure is raised after the
        # handler with no exception context.
        parsed: Any = None
        try:
            parsed = kind(value)
        except ValueError:
            pass
        if parsed is None:
            raise _param_error(_Refused(validator, name, why), None)
        return parsed
    accepted = (int, float) if kind is float else (int,)
    if isinstance(value, bool) or not isinstance(value, accepted):
        raise _param_error(_Refused(validator, name, why), None)
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
        raise _param_error(_Refused(validator, "pattern", _Why.BAD_PATTERN), None)
    return compiled
