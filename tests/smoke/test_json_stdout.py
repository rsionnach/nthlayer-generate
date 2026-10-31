"""plan/apply JSON output: stdout carries the JSON and nothing else (opensrm-iiay).

Run as a subprocess on purpose. tests/conftest.py configures structlog at
WARNING, so an in-process test cannot see what a real `nthlayer` run writes:
before this bead the CLI never configured logging, and structlog's default
logger printed debug events (alert_template_loader_init, ...) to stdout ahead
of the JSON. These also stand in for the legacy quiet-mode tests deferred
from opensrm-wo62.4.22, which asserted the same contract one layer down.

payment-api.yaml has a postgres dependency, so plan and apply reach the alert
template loader that logged; api-minimal.yaml has none.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from _helpers import PROJECT_ROOT, run_nthlayer

pytestmark = pytest.mark.smoke

SERVICES = PROJECT_ROOT / "examples" / "services"
WITH_DEPENDENCY = str(SERVICES / "payment-api.yaml")
WITHOUT_DEPENDENCY = str(SERVICES / "api-minimal.yaml")


def _json_stdout(*args: str) -> object:
    result = run_nthlayer(*args)
    assert result.exit_code == 0, result
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        pytest.fail(f"stdout is not JSON ({exc}):\n{result.stdout[:600]}")


@pytest.mark.parametrize("verbose", [(), ("-v",)], ids=["default", "verbose"])
@pytest.mark.parametrize(
    "manifest", [WITH_DEPENDENCY, WITHOUT_DEPENDENCY], ids=lambda m: Path(m).name
)
def test_plan_json_stdout_is_only_json(manifest: str, verbose: tuple[str, ...]) -> None:
    plan = _json_stdout("plan", manifest, "--format", "json", *verbose)
    if manifest == WITH_DEPENDENCY:
        # The dependency is what reaches the alert template loader.
        assert "alerts" in json.dumps(plan), plan


@pytest.mark.parametrize(
    "manifest", [WITH_DEPENDENCY, WITHOUT_DEPENDENCY], ids=lambda m: Path(m).name
)
def test_apply_json_stdout_is_only_json(manifest: str, tmp_path: Path) -> None:
    # A real apply into tmp_path: --dry-run delegates to plan and ignores
    # --output json altogether (opensrm-wlt1).
    result = _json_stdout("apply", manifest, "--output", "json", "--output-dir", str(tmp_path))
    assert isinstance(result, dict) and not result.get("errors"), result
