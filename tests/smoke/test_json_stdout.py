"""plan/apply JSON output: stdout carries the JSON and nothing else (opensrm-iiay).

Run as a subprocess on purpose. tests/conftest.py configures structlog at
WARNING, so an in-process test cannot see what a real `nthlayer` run writes:
before this bead the CLI never configured logging, and structlog's default
logger printed debug events (alert_template_loader_init, ...) to stdout ahead
of the JSON. These also stand in for the legacy quiet-mode tests deferred
from opensrm-wo62.4.22, which asserted the same contract one layer down.

payment-api.yaml has a postgres dependency, so plan and apply reach the alert
template loader that logged; api-minimal.yaml has none (see _helpers).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from _helpers import API_MINIMAL, PAYMENT_API, PROJECT_ROOT, run_nthlayer

pytestmark = pytest.mark.smoke

# (manifest, whether its plan includes alerts). The alerts case is the one
# that reached the alert template loader, whose debug events leaked.
MANIFESTS = [(PAYMENT_API, True), (API_MINIMAL, False)]
MANIFEST_IDS = [Path(m).name for m, _ in MANIFESTS]
# -v raises the log level to INFO; stdout must stay JSON either way.
VERBOSITY = pytest.mark.parametrize("verbose", [(), ("-v",)], ids=["default", "verbose"])


def _json_stdout(*args: str) -> object:
    result = run_nthlayer(*args)
    assert result.exit_code == 0, result
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        pytest.fail(f"stdout is not JSON ({exc}):\n{result.stdout[:600]}")


@VERBOSITY
@pytest.mark.parametrize(("manifest", "expects_alerts"), MANIFESTS, ids=MANIFEST_IDS)
def test_plan_json_stdout_is_only_json(
    manifest: str, expects_alerts: bool, verbose: tuple[str, ...]
) -> None:
    plan = _json_stdout("plan", manifest, "--format", "json", *verbose)
    assert ("alert_generation" in plan["checks"]) is expects_alerts, plan


# -v adds orchestration progress prints, which go to stderr in JSON mode
# (opensrm-f751).
@VERBOSITY
@pytest.mark.parametrize(("manifest", "expects_alerts"), MANIFESTS, ids=MANIFEST_IDS)
def test_apply_json_stdout_is_only_json(
    manifest: str, expects_alerts: bool, verbose: tuple[str, ...], tmp_path: Path
) -> None:
    # A real apply into tmp_path: --dry-run delegates to plan and ignores
    # --output json altogether (opensrm-wlt1).
    report = _json_stdout(
        "apply", manifest, "--output", "json", "--output-dir", str(tmp_path), *verbose
    )
    assert isinstance(report, dict) and not report.get("errors"), report
    assert ("alerts" in report["resources_created"]) is expects_alerts, report


def test_plan_json_stdout_survives_a_closed_stderr() -> None:
    """``2>&-`` (some CI wrappers and daemons): Python sets sys.stderr to None.

    Logging setup must not touch it in a way that fails, or the command dies
    before printing the JSON (R5 edge-cases, opensrm-iiay).
    """
    # The venv's own console script, not `uv run`: uv opens files of its own,
    # one of which lands on the freed fd 2, so the child would get a stderr.
    nthlayer = str(Path(sys.executable).with_name("nthlayer"))
    result = subprocess.run(
        ["sh", "-c", 'exec 2>&-; exec "$0" plan "$1" --format json', nthlayer, PAYMENT_API],
        stdout=subprocess.PIPE,
        text=True,
        timeout=60,
        cwd=str(PROJECT_ROOT),
    )
    assert result.returncode == 0, result.stdout[:600]
    json.loads(result.stdout)
