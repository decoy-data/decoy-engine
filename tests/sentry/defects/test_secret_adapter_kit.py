"""Every secret-provider adapter joins the shared contract kit (F13 shared rules, slice E3).

An AST walk of the public modules in ``src/decoy_engine/secret_providers/`` collects every class
with a class-level ``scheme`` string. The sentry fails when that set, or the ``_REMOTE_RULES``
keys, differ from the kit's harness keys; when a harness injects different failure codes than the
adapter's error map holds; or when an adapter module is missing from the semgrep consumer rule or
from ``file_access_modules.toml``. The seeded cases prove each rule can go red.
"""

from __future__ import annotations

import ast
from pathlib import Path

from decoy_engine.secret_providers import _errors
from decoy_engine.secret_providers._types import _REMOTE_RULES
from tests.secret_providers.adapters import _contract as kit
from tests.sentry.fa.rules import toml_reader

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / "src" / "decoy_engine" / "secret_providers"
RULES = (ROOT / ".semgrep" / "f13-secret-providers.yml").read_text(encoding="utf-8")
MODULES = toml_reader.loads(
    (ROOT / "tests" / "sentry" / "file_access_modules.toml").read_text(encoding="utf-8")
)
# Raised by a provider's factory or the registry, not by a read: no harness injects them.
NOT_READ_ERRORS = frozenset({"SecretProviderConfigError", "SecretProviderUnknown"})


def adapters(package: Path) -> dict[str, tuple[str, frozenset[str]]]:
    """scheme -> (module stem, registered codes of the read errors the module raises)."""
    found: dict[str, tuple[str, frozenset[str]]] = {}
    for path in sorted(package.glob("[a-z]*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        schemes = [
            stmt.value.value
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef)
            for stmt in node.body
            if isinstance(stmt, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "scheme" for t in stmt.targets)
            and isinstance(stmt.value, ast.Constant)
            and isinstance(stmt.value.value, str)
        ]
        names = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("_errors")
            for alias in node.names
        }
        codes = frozenset(
            str(getattr(_errors, name)().code)
            for name in names
            if name.startswith("Secret")
            and name not in NOT_READ_ERRORS
            and issubclass(getattr(_errors, name, object), _errors.SecretProviderError)
        )
        for scheme in schemes:
            found[scheme] = (path.stem, codes)
    return found


def findings(
    found: dict[str, tuple[str, frozenset[str]]],
    harness_codes: dict[str, frozenset[str]],
    remote_rules: set[str],
    rules_text: str,
    file_modules: set[str],
) -> list[str]:
    out = []
    for scheme, (module, codes) in sorted(found.items()):
        if scheme not in harness_codes:
            out.append(f"{scheme}: no harness in the contract kit")
        elif harness_codes[scheme] != codes:
            out.append(
                f"{scheme}: harness codes {sorted(harness_codes[scheme])} != {sorted(codes)}"
            )
        if f"- pattern: from decoy_engine.secret_providers.{module} import $X\n" not in rules_text:
            out.append(f"{module}: not in the semgrep consumer rule")
        if f"decoy_engine/secret_providers/{module}.py" not in file_modules:
            out.append(f"{module}: no file-access entry")
    out += [f"{s}: harness for no adapter" for s in sorted(set(harness_codes) - set(found))]
    out += [
        f"{s}: _REMOTE_RULES key without harness" for s in sorted(remote_rules - set(harness_codes))
    ]
    return out


def real_inputs():
    harnesses = {k: frozenset(h.failure_codes) for k, h in kit.harness_classes().items()}
    file_modules = {e["module"] for e in MODULES["operator_environment"]}
    return adapters(PACKAGE), harnesses, set(_REMOTE_RULES), RULES, file_modules


def test_every_adapter_has_a_harness_and_its_registrations() -> None:
    assert findings(*real_inputs()) == []
    assert set(real_inputs()[0]) == {"vault", "aws-sm"}  # positive control: the walk finds both


def test_a_module_with_a_scheme_and_no_harness_is_red(tmp_path: Path) -> None:
    (tmp_path / "newmod.py").write_text('class P:\n    scheme = "x"\n', encoding="utf-8")
    found, harnesses, remote, rules, files = real_inputs()
    found = {**found, **adapters(tmp_path)}
    assert any("x: no harness" in f for f in findings(found, harnesses, remote, rules, files))


def test_a_harness_missing_a_failure_code_is_red() -> None:
    found, harnesses, remote, rules, files = real_inputs()
    harnesses["vault"] = harnesses["vault"] - {"secret_expired"}
    assert any(
        "vault: harness codes" in f for f in findings(found, harnesses, remote, rules, files)
    )


def test_a_module_missing_its_semgrep_pattern_is_red() -> None:
    found, harnesses, remote, rules, files = real_inputs()
    rules = rules.replace("from decoy_engine.secret_providers.vault import $X", "")
    assert any(
        "vault: not in the semgrep" in f for f in findings(found, harnesses, remote, rules, files)
    )


def test_a_module_missing_its_file_access_entry_is_red() -> None:
    found, harnesses, remote, rules, files = real_inputs()
    files = files - {"decoy_engine/secret_providers/aws.py"}
    assert any("aws: no file-access" in f for f in findings(found, harnesses, remote, rules, files))


def test_a_remote_rule_without_a_harness_is_red() -> None:
    found, harnesses, remote, rules, files = real_inputs()
    assert any("zz:" in f for f in findings(found, harnesses, remote | {"zz"}, rules, files))
