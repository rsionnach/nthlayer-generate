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

import pytest

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


@pytest.mark.parametrize(
    "name_yaml,index",
    [("", 0), ("    name: ''\n", 0), ("    name: null\n", 0)],
    ids=["missing", "empty", "null"],
)
def test_nameless_resource_is_rejected(tmp_path: Path, name_yaml: str, index: int):
    # The legacy parser rejected a resource with no name, stopping at the
    # first (generate's specs/parser.py, removed in 4.0.0; ServiceParseError wrapping
    # specs/models.py Resource: "Resource name is required"). common loads
    # the missing/empty case and crashes on null for an SLO.
    path = tmp_path / "svc.yaml"
    path.write_text(
        "service:\n  name: svc\n  team: t\n  tier: critical\n  type: api\n"
        "resources:\n"
        "  - kind: SLO\n" + name_yaml + "    spec: {objective: 99.9}\n"
        "  - kind: SLO\n    spec: {objective: 99.0}\n"
    )
    result = _validate(path)
    assert not result.valid
    assert result.errors == [f"Invalid resource {index} in {path}: Resource name is required"]


def test_nameless_index_counts_only_the_files_own_resources(tmp_path: Path):
    # critical-api supplies three resources before the file's own; the
    # parser's index was into the file's list, so the first is 0.
    path = tmp_path / "svc.yaml"
    path.write_text(
        "service:\n  name: svc\n  team: t\n  tier: critical\n  type: api\n"
        "  template: critical-api\n"
        "resources:\n  - kind: Dependencies\n    spec: {}\n"
    )
    result = _validate(path)
    assert result.errors == [f"Invalid resource 0 in {path}: Resource name is required"]


def test_non_string_kind_is_an_invalid_kind(tmp_path: Path):
    path = tmp_path / "svc.yaml"
    path.write_text(
        "service:\n  name: svc\n  team: t\n  tier: critical\n  type: api\n"
        "resources:\n  - kind: [SLO]\n    name: x\n    spec: {}\n"
    )
    result = _validate(path)
    assert not result.valid
    assert result.errors == [
        f"Resource ['SLO']/x: Invalid kind '['SLO']'. Must be one of: {VALID_KINDS}"
    ]


def test_unreadable_env_overlay_is_a_validation_error(tmp_path: Path):
    base = tmp_path / "svc.yaml"
    base.write_text("service:\n  name: svc\n  team: t\n  tier: critical\n  type: api\n")
    (tmp_path / "environments" / "qa.yaml").mkdir(parents=True)  # a directory, not a file
    result = _validate(base, "qa")
    assert not result.valid
    assert len(result.errors) == 1


@pytest.mark.parametrize("name_yaml", ["", "    name: null\n"], ids=["missing", "null"])
def test_nameless_resource_added_by_overlay_is_rejected(tmp_path: Path, name_yaml: str):
    # The parser checked names after the env overlay merge (generate
    # specs/parser.py: EnvironmentMerger, then Resource). A new overlay
    # resource is appended after the file's, so it is resource 1 here.
    base = tmp_path / "svc.yaml"
    base.write_text(
        "service:\n  name: svc\n  team: t\n  tier: critical\n  type: api\n"
        "resources:\n  - kind: SLO\n    name: a\n    spec: {objective: 99.9}\n"
    )
    (tmp_path / "environments").mkdir()
    (tmp_path / "environments" / "dev.yaml").write_text(
        "environment: dev\nresources:\n  - kind: SLO\n" + name_yaml
        + "    spec: {objective: 99.0}\n"
    )
    assert _validate(base).valid
    result = _validate(base, "dev")
    assert result.errors == [f"Invalid resource 1 in {base}: Resource name is required"]


@pytest.mark.parametrize("name", ["0", "false"])
def test_falsy_name_is_nameless(tmp_path: Path, name: str):
    # The parser's Resource rejected any falsy name (`not self.name`).
    path = tmp_path / "svc.yaml"
    path.write_text(
        "service:\n  name: svc\n  team: t\n  tier: critical\n  type: api\n"
        f"resources:\n  - kind: SLO\n    name: {name}\n    spec: {{objective: 99.9}}\n"
    )
    assert _validate(path).errors == [f"Invalid resource 0 in {path}: Resource name is required"]


def test_missing_kind_is_rejected_before_name(tmp_path: Path):
    # The parser's Resource checked a falsy kind first ("Resource kind is
    # required"), then the name.
    path = tmp_path / "svc.yaml"
    path.write_text(
        "service:\n  name: svc\n  team: t\n  tier: critical\n  type: api\n"
        "resources:\n  - spec: {objective: 99.9}\n"
    )
    assert _validate(path).errors == [f"Invalid resource 0 in {path}: Resource kind is required"]


def test_env_without_an_environment_is_not_an_unknown_variable(tmp_path: Path):
    # ${env} is a known variable (generate specs/template.py at 44fc4de) but
    # common substitutes it only when an environment is given, so with none
    # it is still in the spec and must not be reported.
    path = tmp_path / "svc.yaml"
    path.write_text(
        "service:\n  name: svc\n  team: t\n  tier: critical\n  type: api\n"
        "resources:\n  - kind: SLO\n    name: availability\n"
        "    spec:\n      objective: 99.9\n      description: 'deploy-${env}'\n"
    )
    result = _validate(path)
    assert result.valid
    assert result.warnings == []


def test_unknown_variables_inside_lists_are_reported(tmp_path: Path):
    # The old check recursed into lists as well as mappings.
    path = tmp_path / "svc.yaml"
    path.write_text(
        "service:\n  name: svc\n  team: t\n  tier: critical\n  type: api\n"
        "resources:\n  - kind: SLO\n    name: availability\n"
        "    spec:\n      objective: 99.9\n      channels: ['${CHANNEL}']\n"
    )
    assert _validate(path).warnings == [
        "Resource 'SLO/availability': Uses unknown template variables: CHANNEL"
    ]


@pytest.mark.parametrize(
    ("template", "valid"),
    [("critical-api", True), ("nonexistent-template", False)],
)
def test_unknown_template_is_rejected(tmp_path: Path, template: str, valid: bool):
    # Ported from the legacy parser's test_unknown_template_error
    # (opensrm-wo62.4.6). The known-template row is the control: the same
    # file validates, so the rejection is about the template name alone.
    path = tmp_path / "svc.yaml"
    path.write_text(
        f"service:\n  name: svc\n  team: t\n  tier: critical\n  type: api\n  template: {template}\n"
    )
    result = _validate(path)
    assert result.valid is valid, result.errors
    if not valid:
        assert len(result.errors) == 1, result.errors
        assert template in result.errors[0]
