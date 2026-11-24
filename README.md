# decoy-engine

`decoy-engine` is the Python library behind Decoy, a tool that masks real data and generates
synthetic data for test environments. It validates a pipeline config, compiles it into a frozen
plan, and runs the plan on tabular data (CSV, Parquet, Arrow, pandas, Polars). The output is
deterministic: the same input, seed and keys give the same result.

The engine is source-available under the Functional Source License (FSL-1.1-ALv2): use it for anything, including production, except building a competing product, and each release becomes Apache-2.0 two years after it ships. The engine has no network or auth surface of its own. It is a
library that you call from your own code.

Most people use Decoy through the [`decoy` CLI](https://github.com/decoy-data/decoy), which drives
this engine from a shell. Read this page if you want to embed the engine in your own Python tool
or work on the engine itself.

## Status

The engine is at version 0.28.4. Each CLI release pins one exact engine version
(`decoy-engine==X.Y.Z`). The CLI 1.0.0 release is targeted for the end of December 2026. When it
ships, the surfaces listed in [docs/frozen-surfaces.md](docs/frozen-surfaces.md) are frozen under
the rules in [docs/compatibility-contract.md](docs/compatibility-contract.md). Until then they can
still change. The roadmap for version 1 is
[docs/ROADMAP.md in the CLI repository](https://github.com/decoy-data/decoy/blob/main/docs/ROADMAP.md),
and `CHANGELOG.md` lists every change.

The engine is built for one user on one machine. The version 1 threat model is accidental leaks.
It does not defend against a hostile process in the same Python interpreter.

## Install

In version 1 the engine reaches users inside the `decoy` CLI bundle. The bundle holds the matched
engine, the native companion and the CLI. Install the CLI bundle with the steps in the
[CLI install guide](https://github.com/decoy-data/decoy/blob/main/docs/install.md). There is no
separate engine install step, and a public engine package comes later.

To work on the engine, install from a clone. [CONTRIBUTING.md](CONTRIBUTING.md) has the full
setup, and `scripts/dev/bootstrap.sh` builds the exact locked environment:

```sh
git clone https://github.com/decoy-data/decoy-engine && cd decoy-engine
pip install -e ".[dev]"
```

Python 3.10, 3.11 and 3.12 are supported. pandas, Polars and PyArrow install as dependencies.
[docs/native/supported-matrix.md](docs/native/supported-matrix.md) lists the supported systems.

### Optional extras

| Extra | Adds |
|-------|------|
| `cloud` | S3 and GCS connectors (`boto3`, `google-cloud-storage`). `gcs` is an alias. |
| `sftp` | The SFTP connector (`paramiko`). |
| `ner` | spaCy detection of person names and locations for `text_redact`. The language model is a separate download: [docs/guides/free-text-ner.md](docs/guides/free-text-ner.md). |
| `mimesis` | Mimesis as an alternative provider backend. |
| `geo` | H3 indexing for `geo_generalize` on latitude and longitude. |
| `hashicorp-vault` | The HashiCorp Vault secret provider. |

The `vault` extra installs nothing. It is kept as an alias so older install lines still work.

### Native companion

`decoy-engine-native` is a separate, optional Rust package in this repository
([`decoy-engine-native/`](decoy-engine-native/README.md)). It holds two compiled kernels: keyed
hashing (HKDF-SHA256 then HMAC-SHA256) and the deterministic index for faker pools. They produce
the same bytes as the Python code and exist for speed. Without the companion, the engine uses its
pandas path for those columns. The result is correct and slower. The CLI bundle always includes
the companion. The engine has no `native` extra yet, because the companion has no package release.
Build it from a clone with `maturin develop` inside `decoy-engine-native/`. Wheels are built for
Linux x86-64, Linux ARM64, macOS arm64 and Windows x86-64 on Python 3.10 to 3.12.

## Quickstart

Validate a config dict, load the source tables, and run the pipeline in one call. This example
reads `people.csv`, which has `email` and `ssn` columns.

```python
import pyarrow.csv as pacsv

from decoy_engine import PipelineConfig, run_pipeline

config_dict = {
    "version": 2,
    "global_settings": {"seed": 42},
    "sources": {
        "people": {"type": "file", "format": "csv", "has_header": True, "path": "./people.csv"},
    },
    "tables": [
        {
            "name": "people",
            "columns": [
                {"name": "email", "strategy": "faker", "provider": "person_email"},
                {"name": "ssn", "strategy": "redact"},
            ],
        }
    ],
    "targets": {
        "people": {"type": "file", "format": "csv", "path": "./people_masked.csv"},
    },
}

# 1. Validate once. Downstream code does not validate again.
config = PipelineConfig.model_validate(config_dict).model_dump()

# 2. Load the source tables, keyed by table name.
sources = {"people": pacsv.read_csv("people.csv")}

# 3. Run the pipeline: profile, compile, wire relationships, execute.
result = run_pipeline(config, sources, engine_version="0.28.4")

# result.outputs["people"] is the masked pyarrow.Table.
masked = result.outputs["people"]
```

The test `tests/integration/golden/test_execution_e2e.py` is the reference for a complete caller
(the `_run` helper). [docs/quickstart.md](docs/quickstart.md) and [docs/recipes.md](docs/recipes.md)
show the same flow with YAML and the CLI.

## Public API

The full public surface is `decoy_engine.__all__`. These are the entry points most callers need:

| Symbol | Use |
|--------|-----|
| `PipelineConfig` | The strict pipeline-config schema. Validate once with `PipelineConfig.model_validate(yaml).model_dump()`. |
| `run_pipeline(config, sources, engine_version=...)` | Run a whole pipeline (validate, profile, compile, execute). Returns an `ExecutionResult` with `.outputs[table]`. |
| `run_mask_chunked(config, chunks, table=..., engine_version=...)` | Mask one table chunk by chunk, for input that does not fit in memory. |
| `compile_plan(config, profile, decoy_engine_version=...)` | Compile a validated config and a profile into a frozen `Plan`. This is the lower-level path. |
| `generate_tables(...)` | Build tables from a schema, for `mode: generate` configs. |
| `profile_columns(...)` | Profile source columns: distributions, PII detectors, sentinels. |
| `validate_config(...)` | Return a `ValidationResult` without raising. |

Anything not in `__all__`, and anything under `decoy_engine.internal`, is private and can change
without a version bump. `decoy_engine.sdk` is the public connector SDK (`FileSource`, `FileSink`).
The engine has 24 mask strategies and many generate types. [docs/strategies.md](docs/strategies.md)
describes each one, and the generated [capability matrix](docs/capability-matrix.md) is the
authoritative list.

Generation streams for most column kinds. A `unique` column and a column with `min_per_parent` or
`max_per_parent` need all rows of the column in memory. The engine refuses them with a coded reason when
they exceed the memory budget. See [docs/guides/generate-uniqueness.md](docs/guides/generate-uniqueness.md).

## Repository layout

| Path | Contents |
|------|----------|
| `src/decoy_engine/config/` | `PipelineConfig` and the source, target and relationship models. |
| `src/decoy_engine/plan/` | `compile_plan` and the frozen `Plan`. |
| `src/decoy_engine/execution/` | `run_pipeline`, the routes, the strategy handlers and the native bridge. |
| `src/decoy_engine/generation/` | Generation, composite providers and value pools. |
| `src/decoy_engine/providers_v2/` | The provider registry and identifier adapters (NPI, SSN, EIN, MRN, NDC). |
| `src/decoy_engine/relationships/` | The relationship graph, namespaces and orphan policy. |
| `src/decoy_engine/detection/`, `profiling/`, `verification/` | PII detectors, profiling and post-mask checks. |
| `src/decoy_engine/connectors/` | File connectors for S3, GCS and SFTP. |
| `decoy-engine-native/` | The optional Rust companion. |
| `tests/integration/golden/` | End-to-end caller examples. |

[CODEMAP.md](CODEMAP.md) has the full map, and `src/decoy_engine/_MAP.md` is the per-package index.

## Documentation

- [docs/index.md](docs/index.md): the start page for all engine docs.
- [docs/strategies.md](docs/strategies.md), [docs/relationships.md](docs/relationships.md), [docs/declared-casting.md](docs/declared-casting.md), [docs/determinism.md](docs/determinism.md): how masking, foreign keys, parsing and seeds work.
- [docs/what-we-cannot-prove.md](docs/what-we-cannot-prove.md): the limits of what Decoy guarantees.
- [docs/compatibility-contract.md](docs/compatibility-contract.md) and [docs/frozen-surfaces.md](docs/frozen-surfaces.md): which surfaces freeze and how they change.
- [docs/security/](docs/security): token vault, key derivation, secret providers and file-access policy.
- [CHANGELOG.md](CHANGELOG.md): release notes.

## Contributing and security

[CONTRIBUTING.md](CONTRIBUTING.md) explains how to build, test and propose changes. Report a
vulnerability privately as described in [SECURITY.md](SECURITY.md). The trademark policy is
[TRADEMARKS.md](TRADEMARKS.md).

## License

Functional Source License, Version 1.1, Apache 2.0 Future License
(FSL-1.1-ALv2). You may use, modify and redistribute the engine for any
purpose except a Competing Use: offering it, or something substantially
similar built from it, to others as a commercial product or service.
Internal production use is allowed. Each release converts to the Apache
License 2.0 on the second anniversary of its release. FSL is
source-available, not OSI open source.

See `LICENSE`, `NOTICE`, `TRADEMARKS.md`, and the plain-English
[licensing FAQ](https://github.com/decoy-data/decoy/blob/main/LICENSING.md).
Releases published before the switch to FSL stay under the Apache License
2.0 they shipped with.
