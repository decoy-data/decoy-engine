"""F13 §5 acceptance 1-3, 5, 7, 9: secret admission wins before any source is touched."""

from __future__ import annotations

import pytest

from decoy_engine import run_mask_chunked, run_mask_pipeline_chunked, run_pipeline
from decoy_engine.keyprovider import (
    KeyedStrategyRequiresSecret,
    MaskSecretError,
    SecretKeyProvider,
    SeedKeyProvider,
)
from tests._declared_schema import chunked_entry_kwargs
from tests.secret_providers._helpers import (
    ENGINE_VERSION,
    FAILURE_CLASSES,
    GOOD_SECRET,
    ProtocolProvider,
    TouchedSource,
    keyed_config,
    one_chunk,
    unkeyed_config,
)

CHUNKED = [
    pytest.param(run_mask_pipeline_chunked, id="run_mask_pipeline_chunked"),
    pytest.param(run_mask_chunked, id="run_mask_chunked"),
]


def _drain(entry, cfg, source, **kw):
    kw = {**chunked_entry_kwargs(entry, cfg, "t"), **kw}
    return list(entry(cfg, source, table="t", engine_version=ENGINE_VERSION, **kw))


@pytest.fixture
def profile_spy(monkeypatch):
    """Counts (and still performs) profile_source calls: the first protected read."""
    import decoy_engine.profile as profile_mod

    real = profile_mod.profile_source
    calls = []

    def spy(*a, **k):
        calls.append(1)
        return real(*a, **k)

    monkeypatch.setattr(profile_mod, "profile_source", spy)
    return calls


def test_missing_env_secret_fails_before_profiling(tmp_path, monkeypatch, profile_spy, registry):
    monkeypatch.delenv("F13_ABSENT", raising=False)
    cfg = keyed_config(tmp_path, mask_secret_ref="env:F13_ABSENT")
    # The CSV never exists: opening the source would raise a different error.
    with pytest.raises(MaskSecretError) as info:
        run_pipeline(cfg, engine_version=ENGINE_VERSION)
    assert info.value.code == "missing_mask_secret"
    assert profile_spy == []


@pytest.mark.parametrize("entry", CHUNKED)
@pytest.mark.parametrize(
    "ref, code",
    [
        ("kms:alias/x", "secret_provider_unknown"),
        ("env:F13_ABSENT", "missing_mask_secret"),
    ],
)
def test_chunked_admission_failures_never_touch_the_iterator(
    tmp_path, monkeypatch, registry, entry, ref, code
):
    monkeypatch.delenv("F13_ABSENT", raising=False)
    cfg = keyed_config(tmp_path, mask_secret_ref=ref)
    source = TouchedSource()
    with pytest.raises(MaskSecretError) as info:
        _drain(entry, cfg, source)
    assert info.value.code == code
    assert source.touched == 0


@pytest.mark.parametrize("entry", CHUNKED)
@pytest.mark.parametrize("code", sorted(FAILURE_CLASSES))
def test_provider_failure_classes_never_touch_the_iterator(tmp_path, registry, entry, code):
    registry.register(ProtocolProvider("fail", fail=FAILURE_CLASSES[code]))
    cfg = keyed_config(tmp_path, mask_secret_ref="fail:anything")
    source = TouchedSource()
    with pytest.raises(MaskSecretError) as info:
        _drain(entry, cfg, source)
    assert info.value.code == code
    assert source.touched == 0


@pytest.mark.parametrize("entry", CHUNKED)
def test_unknown_provider_is_fail_closed_with_no_fallback(tmp_path, registry, entry, monkeypatch):
    def boom(self):
        raise AssertionError("seed fallback ran")

    monkeypatch.setattr(SeedKeyProvider, "mask_key", boom)
    source = TouchedSource()
    cfg = keyed_config(tmp_path, mask_secret_ref="nope:thing")
    with pytest.raises(MaskSecretError) as info:
        _drain(entry, cfg, source)
    assert info.value.code == "secret_provider_unknown"
    assert source.touched == 0


@pytest.mark.parametrize("pre_ga", [True, False], ids=["pre-ga", "ga"])
@pytest.mark.parametrize("entry", CHUNKED)
def test_keyed_work_without_a_secret_never_falls_back(tmp_path, monkeypatch, entry, pre_ga):
    monkeypatch.setattr("decoy_engine.release.is_pre_ga", lambda: pre_ga)

    def boom(self):
        raise AssertionError("seed fallback ran")

    monkeypatch.setattr(SeedKeyProvider, "mask_key", boom)
    source = TouchedSource()
    with pytest.raises(KeyedStrategyRequiresSecret) as info:
        _drain(entry, keyed_config(tmp_path), source)
    assert info.value.code == "keyed_strategy_requires_secret"
    assert source.touched == 0


@pytest.mark.parametrize("pre_ga", [True, False], ids=["pre-ga", "ga"])
def test_run_pipeline_keyed_without_secret_never_falls_back(
    tmp_path, monkeypatch, pre_ga, profile_spy
):
    monkeypatch.setattr("decoy_engine.release.is_pre_ga", lambda: pre_ga)
    with pytest.raises(KeyedStrategyRequiresSecret):
        run_pipeline(keyed_config(tmp_path), engine_version=ENGINE_VERSION)
    assert profile_spy == []


def test_seed_key_provider_is_not_a_secret(tmp_path, profile_spy):
    with pytest.raises(KeyedStrategyRequiresSecret):
        run_pipeline(
            keyed_config(tmp_path),
            engine_version=ENGINE_VERSION,
            key_provider=SeedKeyProvider((7).to_bytes(8, "big")),
        )
    assert profile_spy == []


def test_unkeyed_work_needs_no_secret(tmp_path):
    source = TouchedSource()
    out = _drain(run_mask_pipeline_chunked, unkeyed_config(tmp_path), source)
    assert out and source.touched > 0


@pytest.mark.parametrize("entry", CHUNKED)
def test_lease_unsupported_reads_nothing_and_is_not_cached(tmp_path, registry, entry):
    prov = ProtocolProvider("lease", renewable=True)
    registry.register(prov)
    source = TouchedSource()
    with pytest.raises(MaskSecretError) as info:
        _drain(entry, keyed_config(tmp_path, mask_secret_ref="lease:x"), source)
    assert info.value.code == "secret_lease_unsupported"
    assert prov.resolve_calls == 0 and source.touched == 0


def test_one_provider_read_per_run_even_if_data_would_drift(tmp_path, registry):
    prov = ProtocolProvider("once", drift=True, value=b"k" * 40)
    registry.register(prov)
    cfg = keyed_config(tmp_path, mask_secret_ref="once:x?encoding=raw")
    _drain(run_mask_pipeline_chunked, cfg, [one_chunk(), one_chunk()])
    assert prov.resolve_calls == 1


def test_programmatic_provider_still_wins_over_the_ref(tmp_path, registry):
    prov = SecretKeyProvider(GOOD_SECRET)
    cfg = keyed_config(tmp_path, mask_secret_ref="nope:ignored")
    out = _drain(run_mask_pipeline_chunked, cfg, [one_chunk()], key_provider=prov)
    assert out


# --- date_shift refusal (roadmap row 24zb, E1) -------------------------------------------------
# An unkeyed date_shift is refused on every route before any source read. Most of these pass on
# main; each is red under a named mutation (plan section 6: M1 classifies date_shift unkeyed, M2
# and M3 drop the SeedKeyProvider checks).

_MARKER = "9999-12-31"
EXECUTION_MODES = ["auto", "stream", "sequential", "full_frame", "out_of_core"]


def _date_config(tmp_path, **kw):
    return keyed_config(tmp_path, strategy="date_shift", **kw)


def _write_marker_source(tmp_path) -> None:
    (tmp_path / "t.csv").write_text("email\n" + "\n".join([_MARKER] * 6) + "\n")


class _ShortDuckProvider:
    key_version = "duck"

    def mask_key(self) -> bytes:
        return b"8bytes!!"


@pytest.mark.parametrize("pre_ga", [True, False], ids=["pre-ga", "ga"])
@pytest.mark.parametrize("mode", EXECUTION_MODES)
def test_date_shift_run_pipeline_without_secret_is_refused_before_read(
    tmp_path, monkeypatch, profile_spy, pre_ga, mode
):
    monkeypatch.setattr("decoy_engine.release.is_pre_ga", lambda: pre_ga)
    _write_marker_source(tmp_path)
    cfg = _date_config(tmp_path)
    with pytest.raises(KeyedStrategyRequiresSecret) as info:
        run_pipeline(cfg, engine_version=ENGINE_VERSION, execution_mode=mode)
    assert info.value.code == "keyed_strategy_requires_secret"
    assert profile_spy == []
    assert not (tmp_path / "o.csv").exists()


@pytest.mark.parametrize("pre_ga", [True, False], ids=["pre-ga", "ga"])
@pytest.mark.parametrize("entry", CHUNKED)
def test_date_shift_chunked_without_secret_never_touches_the_source(
    tmp_path, monkeypatch, entry, pre_ga
):
    monkeypatch.setattr("decoy_engine.release.is_pre_ga", lambda: pre_ga)

    def boom(self):
        raise AssertionError("seed fallback ran")

    monkeypatch.setattr(SeedKeyProvider, "mask_key", boom)
    source = TouchedSource()
    with pytest.raises(KeyedStrategyRequiresSecret) as info:
        _drain(entry, _date_config(tmp_path), source)
    assert info.value.code == "keyed_strategy_requires_secret"
    assert source.touched == 0


@pytest.mark.parametrize(
    "provider",
    [
        pytest.param(SeedKeyProvider((7).to_bytes(8, "big")), id="seed-8-bytes"),
        pytest.param(SeedKeyProvider(b"s" * 32), id="seed-32-bytes"),
        pytest.param(_ShortDuckProvider(), id="duck-8-bytes"),
    ],
)
def test_date_shift_seed_or_short_provider_is_never_a_secret(tmp_path, profile_spy, provider):
    with pytest.raises(KeyedStrategyRequiresSecret) as info:
        run_pipeline(_date_config(tmp_path), engine_version=ENGINE_VERSION, key_provider=provider)
    assert info.value.code == "keyed_strategy_requires_secret"
    assert profile_spy == []


@pytest.mark.parametrize("pre_ga", [True, False], ids=["pre-ga", "ga"])
def test_date_shift_refusal_leaks_no_source_value(tmp_path, monkeypatch, caplog, pre_ga):
    from decoy_engine.keyprovider import KEY_REQUIRED_GUIDANCE

    monkeypatch.setattr("decoy_engine.release.is_pre_ga", lambda: pre_ga)
    _write_marker_source(tmp_path)
    caplog.set_level("DEBUG")
    with pytest.raises(KeyedStrategyRequiresSecret) as info:
        run_pipeline(_date_config(tmp_path), engine_version=ENGINE_VERSION)
    assert KEY_REQUIRED_GUIDANCE in str(info.value)
    assert _MARKER not in str(info.value)
    assert all(_MARKER not in r.getMessage() for r in caplog.records)
    assert info.value.__cause__ is None
    assert info.value.__context__ is None


def _date_plan_and_inputs():
    import pyarrow as pa

    from decoy_engine.execution._chunked_profile import first_chunk_profile
    from decoy_engine.plan import compile_plan
    from decoy_engine.providers_v2 import get_default_registry
    from decoy_engine.relationships import RelationshipGraph, build_namespace_registry

    table = pa.table({"d": ["2024-01-05", "2024-02-10", "2024-03-15"]})
    config = {
        "global_settings": {"seed": 7, "unconfigured_column_policy": "warn"},
        "tables": [
            {
                "name": "t",
                "columns": [{"name": "d", "strategy": "date_shift", "namespace": "d_ns"}],
                "provider_config": {"date_format": "%Y-%m-%d"},
            }
        ],
    }
    profile = first_chunk_profile(table, table="t", engine_version=ENGINE_VERSION)
    plan = compile_plan(config, profile, decoy_engine_version=ENGINE_VERSION, no_profile=True)
    return (
        plan,
        table,
        config,
        get_default_registry(),
        RelationshipGraph(edges=(), ordering=()),
        build_namespace_registry(config, profile),
    )


@pytest.mark.parametrize(
    "provider",
    [
        pytest.param(None, id="no-provider"),
        pytest.param(SeedKeyProvider(b"s" * 32), id="seed-32-bytes"),
    ],
)
@pytest.mark.parametrize("route", ["pandas", "sequential"])
def test_date_shift_adapter_routes_refuse_before_the_handler_runs(route, provider, monkeypatch):
    from decoy_engine.execution import _strategies as strategies_pkg
    from decoy_engine.execution._pandas_adapter import PandasExecutionAdapter
    from decoy_engine.execution._sequential import run_sequential

    ran = []
    handler = strategies_pkg.SCALAR_HANDLERS["date_shift"]
    real_run = type(handler).run
    monkeypatch.setattr(
        type(handler), "run", lambda self, *a, **k: ran.append(1) or real_run(self, *a, **k)
    )
    plan, table, config, registry, graph, namespaces = _date_plan_and_inputs()
    adapter = PandasExecutionAdapter()
    with pytest.raises(KeyedStrategyRequiresSecret) as info:
        if route == "pandas":
            adapter.run(
                plan,
                {"t": table},
                registry=registry,
                relationship_graph=graph,
                namespace_registry=namespaces,
                key_provider=provider,
            )
        else:
            run_sequential(
                adapter,
                plan,
                lambda _name: table,
                config=config,
                registry=registry,
                relationship_graph=graph,
                namespace_registry=namespaces,
                key_provider=provider,
            )
    assert info.value.code == "keyed_strategy_requires_secret"
    assert ran == []
