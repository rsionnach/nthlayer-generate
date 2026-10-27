"""R5 edge-cases for opensrm-wo62.1: validate over registries and quoted values."""

from __future__ import annotations

import warnings
from pathlib import Path

import yaml
from nthlayer_common.manifest.target_validation import TargetConventionWarning

from nthlayer_generate.cli.validate import validate_command

REPO = Path(__file__).resolve().parents[1]
V2_EXAMPLE = (
    REPO.parent / "opensrm" / "spec" / "v2" / "examples" / "migration" / "api-full-v2.yaml"
)


def test_quoted_v2_availability_is_a_validation_error_not_a_traceback(tmp_path: Path) -> None:
    """Fixture: opensrm/spec/v2/examples/migration/api-full-v2.yaml with
    ``contracts[0].promise.availability`` (0.9995 there, a Ratio) quoted, the
    YAML-author mistake the schema rejects as a string. The example declares
    no dependency ``criticality``; the transitive-feasibility check only
    compares the promise once a dependency is critical (parser/v2.py
    ``criticality`` -> ``critical``), so one dependency is marked critical."""
    data = yaml.safe_load(V2_EXAMPLE.read_text(encoding="utf-8"))
    data["spec"]["contracts"][0]["promise"]["availability"] = "0.9995"
    data["spec"]["dependencies"][0]["criticality"] = "critical"
    manifest = tmp_path / "payment-api.yaml"
    manifest.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    rc = validate_command(str(manifest), registry_dir=str(tmp_path))

    assert rc != 0


def test_registry_loads_do_not_emit_target_convention_warnings() -> None:
    """The registry only reads contracts. Fixture: the shipped srm/v1
    examples/opensrm/ directory, scanned as the registry while one file is
    validated; the validated file's own load is allowed to warn, so compare
    against validating with no registry."""
    target = str(REPO / "examples" / "opensrm" / "ai-gate.reliability.yaml")

    def count(registry_dir: str | None) -> int:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            validate_command(target, registry_dir=registry_dir)
        return sum(issubclass(w.category, TargetConventionWarning) for w in caught)

    assert count(str(REPO / "examples" / "opensrm")) == count(None)


def test_quoted_availability_error_names_the_field(tmp_path: Path) -> None:
    """Same fixture as above, through validate_service_file: the error says
    which value is not a number rather than echoing a comparison TypeError."""
    from nthlayer_generate.specs.contracts import ContractRegistry
    from nthlayer_generate.specs.validator import validate_service_file

    data = yaml.safe_load(V2_EXAMPLE.read_text(encoding="utf-8"))
    data["spec"]["contracts"][0]["promise"]["availability"] = "0.9995"
    data["spec"]["dependencies"][0]["criticality"] = "critical"
    manifest = tmp_path / "payment-api.yaml"
    manifest.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    result = validate_service_file(manifest, contract_registry=ContractRegistry())

    assert not result.valid
    assert len(result.errors) == 1
    assert "promise.availability" in result.errors[0]
    assert "'0.9995'" in result.errors[0]


def test_unrelated_type_error_propagates(monkeypatch, tmp_path: Path) -> None:
    """A TypeError from generate's own code is a bug, not an invalid file.
    Fixture: the unmodified api-full-v2.yaml, which validates."""
    import pytest

    from nthlayer_generate.specs import validator

    def broken(_manifest: object) -> None:
        raise TypeError("bug in generate")

    monkeypatch.setattr(validator, "_MockContext", broken)
    manifest = tmp_path / "payment-api.yaml"
    manifest.write_text(V2_EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")

    with pytest.raises(TypeError, match="bug in generate"):
        validator.validate_service_file(manifest)


def test_contract_check_type_error_with_numeric_availabilities_propagates(
    monkeypatch, tmp_path: Path
) -> None:
    """The TypeError catch is for non-numeric availability input only. With
    every availability a number (the unmodified api-full-v2.yaml, an empty
    registry), a TypeError from a contract check is a bug and propagates."""
    import pytest

    from nthlayer_generate.specs import validator
    from nthlayer_generate.specs.contracts import ContractRegistry

    def broken(*_args: object) -> list[str]:
        raise TypeError("bug in a contract check")

    monkeypatch.setattr(validator, "validate_dependency_expectations", broken)
    manifest = tmp_path / "payment-api.yaml"
    manifest.write_text(V2_EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")

    with pytest.raises(TypeError, match="bug in a contract check"):
        validator.validate_service_file(manifest, contract_registry=ContractRegistry())


def test_quoted_availability_in_the_registry_names_its_service(tmp_path: Path) -> None:
    """Fixture: api-full-v2.yaml twice. The provider is renamed ``postgresql``
    (``metadata.name`` and ``spec.service.name``, which common's v2 parser reads)
    after the example's first dependency, ``resource:default/postgresql``, with its
    ``promise.availability`` quoted; the consumer is the example with that
    dependency marked critical, as in the first test of this file."""
    from nthlayer_common.manifest import load_manifest

    from nthlayer_generate.specs.contracts import ContractRegistry
    from nthlayer_generate.specs.validator import validate_service_file

    provider = yaml.safe_load(V2_EXAMPLE.read_text(encoding="utf-8"))
    provider["metadata"]["name"] = "postgresql"
    provider["spec"]["service"]["name"] = "postgresql"
    provider["spec"]["contracts"][0]["promise"]["availability"] = "0.9995"
    provider_path = tmp_path / "postgresql.yaml"
    provider_path.write_text(yaml.safe_dump(provider, sort_keys=False), encoding="utf-8")
    registry = ContractRegistry()
    registry.register(load_manifest(provider_path))

    consumer = yaml.safe_load(V2_EXAMPLE.read_text(encoding="utf-8"))
    consumer["spec"]["dependencies"][0]["criticality"] = "critical"
    consumer_path = tmp_path / "payment-api.yaml"
    consumer_path.write_text(yaml.safe_dump(consumer, sort_keys=False), encoding="utf-8")

    result = validate_service_file(consumer_path, contract_registry=registry)

    assert not result.valid
    assert len(result.errors) == 1
    assert "'postgresql'" in result.errors[0]
    assert "'0.9995'" in result.errors[0]
