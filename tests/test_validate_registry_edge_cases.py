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
SRM_V1_EXAMPLE = REPO / "examples" / "opensrm" / "api-critical.reliability.yaml"


def test_quoted_v2_availability_is_a_validation_error_not_a_traceback(tmp_path: Path) -> None:
    """Fixture: opensrm/spec/v2/examples/migration/api-full-v2.yaml with
    ``contracts[0].promise.availability`` (0.9995 there, a Ratio) quoted, the
    YAML-author mistake the schema rejects as a string. common's v2 parser
    refuses it at load since 5.12.3 (opensrm-f0co); before that the string
    reached the transitive-feasibility check, which only compares the promise
    once a dependency is critical, so one dependency is marked critical."""
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
    which value is not a ratio (common's load error, since opensrm-f0co)
    rather than echoing a comparison TypeError."""
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


def test_quoted_v2_availability_in_a_provider_is_refused_at_load(tmp_path: Path) -> None:
    """Fixture: api-full-v2.yaml renamed ``postgresql`` (``metadata.name`` and
    ``spec.service.name``, which common's v2 parser reads), with its
    ``promise.availability`` quoted. The v2 schema's ``promise.availability``
    is a Ratio, a number from 0 to 1 (opensrm/spec/v2/schema.json), and
    common's parser refuses anything else at load since 5.12.3
    (opensrm-f0co). So the provider never reaches a registry: the validator
    used to find the string there and name the service (opensrm-u8oo)."""
    import pytest
    from nthlayer_common.manifest import ManifestLoadError, load_manifest

    provider = yaml.safe_load(V2_EXAMPLE.read_text(encoding="utf-8"))
    provider["metadata"]["name"] = "postgresql"
    provider["spec"]["service"]["name"] = "postgresql"
    provider["spec"]["contracts"][0]["promise"]["availability"] = "0.9995"
    provider_path = tmp_path / "postgresql.yaml"
    provider_path.write_text(yaml.safe_dump(provider, sort_keys=False), encoding="utf-8")

    with pytest.raises(ManifestLoadError) as refused:
        load_manifest(provider_path)

    # The error names the field and shows the value as written.
    assert "promise.availability" in str(refused.value)
    assert "'0.9995'" in str(refused.value)
    assert not refused.value.backstop


def test_quoted_srm_v1_availability_in_the_registry_names_its_service(tmp_path: Path) -> None:
    """srm/v1 has no schema and common's parser stores ``spec.contract``'s
    availability as written (opensrm-ev8r is the open decision), so a quoted
    one still reaches the contract checks, and the validator must say whose
    it is. Fixture: the shipped examples/opensrm/api-critical.reliability.yaml
    twice. The provider is renamed ``postgres-primary``, after the example's
    first dependency (declared ``critical: true``), with its
    ``contract.availability`` (0.999 there) quoted; the consumer is the
    example unmodified."""
    from nthlayer_common.manifest import load_manifest

    from nthlayer_generate.specs.contracts import ContractRegistry
    from nthlayer_generate.specs.validator import validate_service_file

    provider = yaml.safe_load(SRM_V1_EXAMPLE.read_text(encoding="utf-8"))
    provider["metadata"]["name"] = "postgres-primary"
    provider["spec"]["contract"]["availability"] = "0.999"
    provider_path = tmp_path / "postgres-primary.reliability.yaml"
    provider_path.write_text(yaml.safe_dump(provider, sort_keys=False), encoding="utf-8")
    registry = ContractRegistry()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", TargetConventionWarning)
        registry.register(load_manifest(provider_path))
    assert registry.services == ["postgres-primary"]

    consumer_path = tmp_path / "payment-api.reliability.yaml"
    consumer_path.write_text(SRM_V1_EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", TargetConventionWarning)
        result = validate_service_file(consumer_path, contract_registry=registry)

    assert not result.valid
    assert len(result.errors) == 1
    assert "'postgres-primary'" in result.errors[0]
    assert "(contract registry)" in result.errors[0]
    assert "'0.999'" in result.errors[0]
