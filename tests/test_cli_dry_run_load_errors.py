"""docs/backstage --dry-run report a manifest that fails to load (opensrm-wo62.1).

nthlayer-common wraps srm/v1 and v2 parse errors in ``ManifestLoadError``
(parser/loader.py), which is neither a ValueError nor any other type the
commands caught before the switch. An invalid manifest must give exit 1 and
an error message, not a traceback.

Fixture: examples/opensrm/api-basic.reliability.yaml @f252974 with
``spec.slos.availability.target`` set to the string ``"abc"``. The OpenSRM v1
schema (opensrm spec/v1/schema.json @d39818b, ``AvailabilitySLO.target`` ->
``#/definitions/Ratio``) requires a number, so the edited file is invalid by
the schema, not just by the code under test.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from nthlayer_generate.cli.backstage import generate_backstage_command
from nthlayer_generate.cli.docs import generate_docs_command

API_BASIC = (
    Path(__file__).resolve().parents[1] / "examples" / "opensrm" / "api-basic.reliability.yaml"
)


@pytest.fixture
def invalid_target(tmp_path: Path) -> Path:
    data = yaml.safe_load(API_BASIC.read_text())
    data["spec"]["slos"]["availability"]["target"] = "abc"
    path = tmp_path / "api-basic.reliability.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return path


def test_docs_dry_run_reports_a_load_error(invalid_target: Path, tmp_path: Path) -> None:
    code = generate_docs_command(str(invalid_target), output=str(tmp_path / "out"), dry_run=True)
    assert code == 1


def test_backstage_dry_run_reports_a_load_error(invalid_target: Path, tmp_path: Path) -> None:
    code = generate_backstage_command(
        str(invalid_target), output=str(tmp_path / "out"), dry_run=True
    )
    assert code == 1
