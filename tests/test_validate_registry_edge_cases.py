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
