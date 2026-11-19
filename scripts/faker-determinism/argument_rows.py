"""Worker side of the argument grid: run each derived row for one locale through the production
forwarding seams (the reflected wrapper, the `address` override, `FakerAdapter.generate_batch` with
`ProviderSpec.extra`, the formula callable) and return one digest per row.

Only digests and exception class names leave this module; no generated value or message does.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable, Iterator
from typing import Any

from argument_grid import ARGUMENT_SEEDS, decode_descriptor, derive_grid

KINDS = (
    "changed",
    "removed",
    "added",
    "newly reproducible",
    "newly unstable",
    "newly calendar-dependent",
    "no longer calendar-dependent",
)


def diff_grid(locked: dict[str, Any], observed: dict[str, Any]) -> dict[str, list[str]]:
    """Grid rows grouped by the diff kinds, named by family, target and case id."""
    out: dict[str, list[str]] = {k: [] for k in KINDS}
    for case_id in sorted(set(locked) | set(observed)):
        row = observed.get(case_id) or locked[case_id]
        label = f"grid {row['family']} {row['target']} {case_id}"
        if case_id not in observed:
            out["removed"].append(label)
        elif case_id not in locked:
            out["added"].append(label)
        else:
            for f in sorted(locked[case_id]):
                if locked[case_id][f] != observed[case_id].get(f):
                    out["changed"].append(f"{label} {f}")
    return out


@contextlib.contextmanager
def _isolated_random() -> Iterator[None]:
    """Keep a row's global-RNG side effects out of later cells.

    Some parameters reseed the process-wide RNGs (`passport_gender(seed=...)`); left alone, that
    would make every later unseeded provider reproducible and hide the `unstable` cells."""
    import random

    from faker import generator

    states = (random.getstate(), generator.random.getstate())
    try:
        yield
    finally:
        random.setstate(states[0])
        generator.random.setstate(states[1])


class _RowRunner:
    """Runs grid rows for one locale through the production forwarding seams."""

    def __init__(self, locale: str, access: Any, faker_mod: Any) -> None:
        from decoy_engine.providers_v2 import FakerAdapter, ProviderSpec

        self.locale, self.spec_cls = locale, ProviderSpec
        self.fake = access.make_faker(locale)
        self.providers = access.get_faker_providers(self.fake, provider_snapshot={})
        self.scope = access.formula_scope(self.fake)
        self.adapter = FakerAdapter(locale)

    def draw(self, row: dict[str, Any], seed: int) -> list[Any]:
        args = [decode_descriptor(a) for a in row["arguments"]["args"]]
        kwargs = {k: decode_descriptor(v) for k, v in row["arguments"]["kwargs"].items()}
        family, target = row["family"], row["target"]
        if family == "adapter":
            spec = self.spec_cls(
                locale=self.locale,
                deterministic=False,
                namespace=None,
                seed=seed.to_bytes(8, "big"),
                extra=kwargs,
            )
            return list(self.adapter.generate_batch(target, spec=spec, count=1))
        self.fake.seed_instance(seed)
        fn = self.scope[target] if family == "formula" else self.providers[target]
        return [fn(*args, **kwargs)]


def argumented_cells(
    locale: str,
    access: Any,
    faker_mod: Any,
    *,
    digest: Callable[[list[Any]], str],
    cls: Callable[[BaseException | None], str],
    norm: Callable[[Any], Any],
) -> dict[str, Any]:
    """Each derived grid row of this locale at the argument seeds. The lock stores only the
    digest; the descriptor lives once in the top-level grid."""
    from unittest import mock

    adapter_fake = faker_mod.Faker(locale)
    cells: dict[str, Any] = {}
    with mock.patch.object(faker_mod, "Faker", return_value=adapter_fake):
        runner = _RowRunner(locale, access, faker_mod)
        for case_id, row in derive_grid(access, [locale]).items():
            values: list[Any] = []
            err = ""
            try:
                with _isolated_random():
                    for seed in ARGUMENT_SEEDS:
                        values += runner.draw(row, seed)
            except Exception as exc:
                suffix = f"/{cls(exc.__cause__)}" if row["family"] == "adapter" else ""
                err = f"raises:{cls(exc)}{suffix}"
            cells[case_id] = {"draws": err or digest([norm(v) for v in values])}
    return cells
