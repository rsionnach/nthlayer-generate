"""validate's legacy route on nthlayer-common (opensrm-wo62.4.19).

Legacy files now load through ``load_manifest``, like srm/v1 and v2. The
resource checks (kind, duplicate name, unknown ``${var}``) run on the loaded
raw data, which is what ``parse_service_file`` used to return: the resources
after the env overlay, template expansion and substitution.

Expected values follow from the files, not from the validator:

- ``api-minimal.yaml`` declares only ``template: critical-api``; the builtin
  template (nthlayer-common legacy_templates/critical-api.yaml) has three
  resources: SLO availability, SLO latency-p95, PagerDuty primary.
- ``kind: Alerts`` is the invalid kind ``examples/uat/payment-api.yaml``
  declares (pinned in tests/golden/data/validate/uat__payment-api.json).
"""

from __future__ import annotations

import warnings
from pathlib import Path

from nthlayer_generate.specs.validator import validate_service_file

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"

VALID_KINDS = "Dependencies, DeploymentGate, Observability, PagerDuty, PolicyRules, SLO"


def _validate(path: Path, environment: str | None = None):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return validate_service_file(path, environment=environment)


def test_template_provided_resources_are_counted():
    path = EXAMPLES / "services" / "api-minimal.yaml"
    assert path.is_file()
    result = _validate(path)
    assert result.valid, result.errors
    assert result.resource_count == 3


def test_env_overlay_resources_are_checked(tmp_path: Path):
    # The base is valid; the qa overlay appends an Alerts resource, which is
    # only seen if the overlay is applied before the resource checks.
    base = tmp_path / "svc.yaml"
    base.write_text(
        "service:\n  name: svc\n  team: t\n  tier: critical\n  type: api\n"
        "resources:\n  - kind: SLO\n    name: availability\n"
        "    spec:\n      objective: 99.9\n"
    )
    (tmp_path / "environments").mkdir()
    (tmp_path / "environments" / "qa.yaml").write_text(
        "environment: qa\nresources:\n  - kind: Alerts\n    name: alert-rules\n"
        "    spec:\n      channel: ${SLACK_WEBHOOK}\n"
    )

    base_result = _validate(base)
    qa_result = _validate(base, "qa")

    assert base_result.valid, base_result.errors
    assert base_result.resource_count == 1
    assert qa_result.resource_count == 2
    assert qa_result.errors == [
        f"Resource Alerts/alert-rules: Invalid kind 'Alerts'. Must be one of: {VALID_KINDS}"
    ]
    assert qa_result.warnings == [
        "Resource 'Alerts/alert-rules': Uses unknown template variables: SLACK_WEBHOOK"
    ]


def test_known_variables_are_substituted_before_checking(tmp_path: Path):
    # ${service} is a known variable: common substitutes it, so nothing is
    # reported. ${b} and ${a} are unknown and reported once each, sorted.
    path = tmp_path / "svc.yaml"
    path.write_text(
        "service:\n  name: svc\n  team: t\n  tier: critical\n  type: api\n"
        "resources:\n  - kind: SLO\n    name: availability\n"
        "    spec:\n      objective: 99.9\n"
        "      description: '${service} ${b} ${a} ${b}'\n"
    )
    result = _validate(path)
    assert result.valid
    assert result.warnings == [
        "Resource 'SLO/availability': Uses unknown template variables: a, b"
    ]


def test_duplicate_names_are_sorted(tmp_path: Path):
    path = tmp_path / "svc.yaml"
    path.write_text(
        "service:\n  name: svc\n  team: t\n  tier: critical\n  type: api\n"
        "resources:\n"
        "  - kind: SLO\n    name: zeta\n    spec: {objective: 99.9}\n"
        "  - kind: SLO\n    name: zeta\n    spec: {objective: 99.0}\n"
        "  - kind: SLO\n    name: alpha\n    spec: {objective: 99.9}\n"
        "  - kind: SLO\n    name: alpha\n    spec: {objective: 99.0}\n"
    )
    result = _validate(path)
    assert not result.valid
    assert result.errors == ["Duplicate resource names: alpha, zeta"]


def test_malformed_resource_spec_is_a_validation_error(tmp_path: Path):
    # common's legacy loader raises a bare AttributeError on a non-mapping
    # spec (opensrm-wo62.4.10); validate reports it rather than crashing.
    path = tmp_path / "svc.yaml"
    path.write_text(
        "service:\n  name: svc\n  team: t\n  tier: critical\n  type: api\n"
        "resources:\n  - kind: SLO\n    name: availability\n    spec: [a, b]\n"
    )
    result = _validate(path)
    assert not result.valid
    assert len(result.errors) == 1
    assert result.errors[0].startswith("Unexpected error parsing file: ")


def test_missing_required_service_field_is_a_load_error(tmp_path: Path):
    path = tmp_path / "svc.yaml"
    path.write_text("service:\n  name: svc\n  tier: critical\n  type: api\n")
    result = _validate(path)
    assert not result.valid
    assert result.errors == ["service.team is required"]
