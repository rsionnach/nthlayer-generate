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
import os
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
# -v raises the log level to INFO and, for apply, adds orchestration
# progress prints; stdout must stay JSON either way.
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
    # A real apply into tmp_path; --dry-run is covered separately below.
    report = _json_stdout(
        "apply", manifest, "--output", "json", "--output-dir", str(tmp_path), *verbose
    )
    assert isinstance(report, dict) and not report.get("errors"), report
    assert ("alerts" in report["resources_created"]) is expects_alerts, report


@VERBOSITY
@pytest.mark.parametrize(("manifest", "expects_alerts"), MANIFESTS, ids=MANIFEST_IDS)
def test_apply_dry_run_json_stdout_is_plan_json(
    manifest: str, expects_alerts: bool, verbose: tuple[str, ...], tmp_path: Path
) -> None:
    """--dry-run delegates to plan, so --output json yields plan's JSON (opensrm-wlt1)."""
    # Not tmp_path itself: run_nthlayer puts its fake HOME there.
    out_dir = tmp_path / "out"
    plan = _json_stdout(
        "apply", manifest, "--dry-run", "--output", "json", "--output-dir", str(out_dir), *verbose
    )
    assert ("alert_generation" in plan["checks"]) is expects_alerts, plan
    assert not out_dir.exists(), "dry-run wrote files"


@pytest.mark.parametrize(
    "command",
    [
        ("plan", PAYMENT_API, "--format", "json"),
        ("apply", PAYMENT_API, "--output", "json", "-v"),
    ],
    ids=["plan", "apply-verbose"],
)
def test_json_stdout_survives_a_closed_stderr(command: tuple[str, ...], tmp_path: Path) -> None:
    """``2>&-`` (some CI wrappers and daemons): Python sets sys.stderr to None.

    Logging setup must not fail on it (opensrm-iiay), and apply's redirect of
    its prints to stderr must drop them rather than raise (opensrm-f751).
    """
    if command[0] == "apply":
        command = (*command, "--output-dir", str(tmp_path))
    # The venv's own console script, not `uv run`: uv opens files of its own,
    # one of which lands on the freed fd 2, so the child would get a stderr.
    nthlayer = str(Path(sys.executable).with_name("nthlayer"))
    result = subprocess.run(
        ["sh", "-c", 'exec 2>&-; exec "$@"', "sh", nthlayer, *command],
        stdout=subprocess.PIPE,
        text=True,
        timeout=60,
        cwd=str(PROJECT_ROOT),
    )
    assert result.returncode == 0, result.stdout[:600]
    json.loads(result.stdout)


def test_apply_json_stdout_survives_an_unconditional_handler_warning(tmp_path: Path) -> None:
    """A handler print that does not depend on -v also goes to stderr.

    --push-grafana with Grafana unconfigured prints "Grafana not configured"
    (orchestration/handlers.py) with or without -v (opensrm-f751).
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("NTHLAYER_GRAFANA_")}
    result = subprocess.run(
        [
            str(Path(sys.executable).with_name("nthlayer")),
            "apply",
            PAYMENT_API,
            "--output",
            "json",
            "--push-grafana",
            "--output-dir",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(PROJECT_ROOT),
        env=env,
    )
    assert result.returncode == 0, result.stderr[:600]
    json.loads(result.stdout)
    assert "Grafana not configured" in result.stderr, result.stderr[:600]
