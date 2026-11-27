"""Every Faker locale's cold provider build fits its entry in the provider-init table.

Each locale is opened in a fresh interpreter with no bytecode cache, the cold case: Python
compiles the locale's provider modules, and the compile is the transient peak. tracemalloc
counts the bytes held after the build and the peak while it ran.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

import decoy_engine
from decoy_engine.generation.pool import provider_init_bound, provider_init_bytes

_WORKER = """
import gc, json, sys, tempfile, tracemalloc
sys.pycache_prefix = tempfile.mkdtemp()
sys.dont_write_bytecode = True
from decoy_engine.internal.faker_setup import get_faker_providers, make_faker
gc.collect()
tracemalloc.start()
base = tracemalloc.get_traced_memory()[0]
steps = []
for locale in sys.argv[1:]:
    get_faker_providers(make_faker(locale), provider_snapshot={})
    gc.collect()
    held, peak = tracemalloc.get_traced_memory()
    steps.append([held - base, peak - base])
held, _ = tracemalloc.get_traced_memory()
tracemalloc.reset_peak()
get_faker_providers(make_faker(sys.argv[-1]), provider_snapshot={})
gc.collect()
again, again_peak = tracemalloc.get_traced_memory()
print(json.dumps({"steps": steps, "instance": again - held, "instance_peak": again_peak - held}))
"""


def _cold(*locales: str) -> dict[str, Any]:
    out = subprocess.run(  # noqa: S603 -- fixed argv, test-only
        [sys.executable, "-c", _WORKER, *locales],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(Path(decoy_engine.__file__).parents[1])},
        timeout=300,
    )
    assert out.returncode == 0, out.stderr[-2000:]
    result: dict[str, Any] = json.loads(out.stdout.strip().splitlines()[-1])
    return result


@pytest.mark.serial
def test_every_locale_cold_build_fits_its_bound() -> None:
    from faker.config import AVAILABLE_LOCALES

    locales = sorted(AVAILABLE_LOCALES)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = dict(zip(locales, pool.map(_cold, locales), strict=True))
    over = []
    for locale, result in results.items():
        held, peak = result["steps"][0]
        retained, transient = provider_init_bound(locale)
        if held > retained or peak > transient:
            over.append((locale, held, peak, retained, transient))
        assert result["instance_peak"] <= provider_init_bytes({locale}, 2) - provider_init_bytes(
            {locale}, 1
        )
    assert over == []


@pytest.mark.serial
@pytest.mark.parametrize("order", [("de_AT", "it_IT"), ("it_IT", "de_AT")])
def test_two_heavy_locales_opened_cold_fit_the_run_charge(order: tuple[str, str]) -> None:
    """Codex V1-2: the pair peaked at 66 MB against a 32 MiB ceiling."""
    result = _cold(*order)
    peak = max(step[1] for step in result["steps"])
    assert peak <= provider_init_bytes(set(order), 2)
