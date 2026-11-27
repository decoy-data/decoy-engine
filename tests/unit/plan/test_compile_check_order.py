"""AT-A3/A6: `check_unknown_provider` runs before `_build_seed_envelope` in `compile_plan`.

Characterization pin, not a behavior change: it states why the removed `_ProviderError` catch in
`_seed_envelope` and the removed `post_scan_resident_for` catch in the physical compiler were
dead, so a later reorder of the compile steps fails here instead of resurfacing as a raw error.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from decoy_engine.contracts.column_shape import NO_SOURCES
from decoy_engine.plan import PlanCompileError, _compile, compile_plan
from decoy_engine.profile import Profile


def _spy(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []
    for name in ("check_unknown_provider", "_build_seed_envelope"):
        real = getattr(_compile, name)

        def wrapper(*args: Any, _real: Any = real, _name: str = name, **kwargs: Any) -> Any:
            calls.append(_name)
            return _real(*args, **kwargs)

        monkeypatch.setattr(_compile, name, wrapper)
    return calls


def test_unknown_provider_check_runs_before_the_seed_envelope(
    simple_config: dict, simple_profile: Profile, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _spy(monkeypatch)
    compile_plan(simple_config, simple_profile, decoy_engine_version="0.1.0", sources=NO_SOURCES)
    assert calls.index("check_unknown_provider") < calls.index("_build_seed_envelope")


def test_an_unknown_provider_never_reaches_the_seed_envelope(
    simple_config: dict, simple_profile: Profile, monkeypatch: pytest.MonkeyPatch
) -> None:
    bad = copy.deepcopy(simple_config)
    bad["tables"][0]["columns"][0]["provider"] = "no_such_provider"
    calls = _spy(monkeypatch)
    with pytest.raises(PlanCompileError) as exc:
        compile_plan(bad, simple_profile, decoy_engine_version="0.1.0", sources=NO_SOURCES)
    assert exc.value.code == "unknown_provider"
    assert "_build_seed_envelope" not in calls
