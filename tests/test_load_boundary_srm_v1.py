"""A malformed srm/v1 manifest is reported, not raised (opensrm-wo62.4.25).

nthlayer-common 5.12.1 reports a malformed LEGACY file as a ManifestLoadError
(opensrm-wo62.4.10), but its srm/v1 and v2 branches still let AttributeError
and TypeError out of `load_manifest` (opensrm-wo62.4.28). The commands
therefore keep catching both at the load boundary, and these tests are what
says so: the catches go once common keeps its contract for every format
(opensrm-wo62.4.29), and these must pass then too.

Both fixtures are examples/opensrm/api-critical.reliability.yaml with one field
given a type the srm/v1 schema forbids: `metadata` must be a mapping and
`spec.dependencies` a list.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from nthlayer_generate.cli.dashboard import generate_dashboard_command
from nthlayer_generate.cli.environments import diff_envs_command, validate_env_command
from nthlayer_generate.cli.generate import generate_slo_command
from nthlayer_generate.cli.generate_alerts import generate_alerts_command
from nthlayer_generate.specs.validator import validate_service_file

API_CRITICAL = (
    Path(__file__).resolve().parents[1] / "examples" / "opensrm" / "api-critical.reliability.yaml"
)
assert API_CRITICAL.is_file(), API_CRITICAL


def _metadata_is_a_list(doc: dict) -> None:
    doc["metadata"] = []


def _dependencies_is_a_number(doc: dict) -> None:
    doc["spec"]["dependencies"] = 1


MALFORMED = [
    pytest.param(_metadata_is_a_list, id="metadata-is-a-list"),
    pytest.param(_dependencies_is_a_number, id="dependencies-is-a-number"),
]
assert MALFORMED

# Each returns True when the command reported a failure instead of raising.
COMMANDS = [
    pytest.param(
        lambda path, out: generate_dashboard_command(str(path), output=str(out / "d.json")) == 1,
        id="dashboard",
    ),
    pytest.param(
        lambda path, out: generate_alerts_command(str(path), output=str(out / "a.yaml")) == 1,
        id="alerts",
    ),
    pytest.param(
        lambda path, out: generate_slo_command(str(path), output_dir=str(out)) == 1, id="slo"
    ),
    pytest.param(
        lambda path, out: diff_envs_command(str(path), "dev", "prod") == 1, id="diff-envs"
    ),
    pytest.param(
        lambda path, out: validate_env_command("dev", service_file=str(path)) == 1,
        id="validate-env",
    ),
    pytest.param(lambda path, out: not validate_service_file(path).valid, id="validate"),
]
assert COMMANDS


def _write(tmp_path: Path, damage=None) -> Path:
    doc = yaml.safe_load(API_CRITICAL.read_text(encoding="utf-8"))
    if damage is not None:
        damage(doc)
    path = tmp_path / "service.reliability.yaml"
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    # validate-env only loads the manifest once it has found an overlay file.
    (tmp_path / "environments").mkdir()
    (tmp_path / "environments" / "dev.yaml").write_text("environment: dev\n", encoding="utf-8")
    return path


@pytest.mark.parametrize("reported_failure", COMMANDS)
@pytest.mark.parametrize("damage", MALFORMED)
def test_a_malformed_srm_v1_manifest_is_reported(damage, reported_failure, tmp_path):
    assert reported_failure(_write(tmp_path, damage), tmp_path)


@pytest.mark.parametrize("reported_failure", COMMANDS)
def test_the_undamaged_manifest_is_accepted(reported_failure, tmp_path):
    # The same file without the damage succeeds, so a failure above comes from
    # the damage and not from the way the command is called.
    assert not reported_failure(_write(tmp_path), tmp_path)
