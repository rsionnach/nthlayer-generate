"""A bug in the manifest loader is not reported as a bad manifest (opensrm-wo62.4.25).

Since nthlayer-common 5.12.1 (opensrm-wo62.4.10), `load_manifest` raises only
OSError, ManifestLoadError or ValueError, and a malformed legacy file is a
ManifestLoadError naming the resource. Five commands used to catch
AttributeError (three of them TypeError as well) at that call, because the
loader raised those on a non-mapping resource spec. With the loader fixed,
those catches could only hide a defect in the loader as "your manifest is
wrong", so they are gone: the exception now reaches the caller.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from nthlayer_generate.cli.dashboard import generate_dashboard_command
from nthlayer_generate.cli.environments import diff_envs_command, validate_env_command
from nthlayer_generate.cli.generate import generate_slo_command
from nthlayer_generate.cli.generate_alerts import generate_alerts_command
from nthlayer_generate.specs.validator import validate_service_file

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "services" / "analytics-stream.yaml"
assert EXAMPLE.is_file(), EXAMPLE


def _dashboard(tmp_path):
    return generate_dashboard_command(str(EXAMPLE), output=str(tmp_path / "d.json"))


def _alerts(tmp_path):
    return generate_alerts_command(str(EXAMPLE), output=str(tmp_path / "alerts.yaml"))


def _slo(tmp_path):
    return generate_slo_command(str(EXAMPLE), output_dir=str(tmp_path))


def _diff_envs(tmp_path):
    return diff_envs_command(str(EXAMPLE), "dev", "prod")


def _validate_env(tmp_path):
    return validate_env_command("dev", service_file=str(EXAMPLE))


def _validate(tmp_path):
    return validate_service_file(EXAMPLE)


# (module whose `load_manifest` name the command looks up, how to run it,
#  the exception types its load boundary stopped catching)
LOAD_SITES = [
    pytest.param("nthlayer_generate.cli.dashboard", _dashboard, (AttributeError,), id="dashboard"),
    pytest.param("nthlayer_generate.cli.generate_alerts", _alerts, (AttributeError,), id="alerts"),
    pytest.param("nthlayer_generate.cli.generate", _slo, (AttributeError, TypeError), id="slo"),
    pytest.param(
        "nthlayer_generate.cli.environments",
        _diff_envs,
        (AttributeError, TypeError),
        id="diff-envs",
    ),
    pytest.param(
        "nthlayer_generate.cli.environments",
        _validate_env,
        (AttributeError, TypeError),
        id="validate-env",
    ),
    pytest.param(
        "nthlayer_generate.specs.validator",
        _validate,
        (AttributeError, TypeError),
        id="validate",
    ),
]
assert LOAD_SITES


@pytest.mark.parametrize(("module", "run", "no_longer_caught"), LOAD_SITES)
def test_a_loader_defect_reaches_the_caller(module, run, no_longer_caught, tmp_path):
    for exc_type in no_longer_caught:
        with patch(f"{module}.load_manifest", side_effect=exc_type("loader defect")) as load:
            with pytest.raises(exc_type, match="loader defect"):
                run(tmp_path)
        assert load.called, f"{module}.load_manifest was never reached"


@pytest.mark.parametrize(("module", "run", "no_longer_caught"), LOAD_SITES)
def test_the_unpatched_command_loads_the_example(module, run, no_longer_caught, tmp_path):
    # The same call with the real loader succeeds, so the test above fails
    # because of the injected exception and not because the call is wrong.
    result = run(tmp_path)
    assert result == 0 or getattr(result, "valid", False), result
