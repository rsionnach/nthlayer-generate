"""CLI cells: the manifest-path commands over the corpus (spec §6.2).

Each cell drives a command's Python entry point (``*_command(...)``) and
pins what is observable without reading console text: exit codes, files the
command wrote (read back as structure where they are JSON or YAML), and
JSON a command printed to stdout (captured and parsed). Console tables and
messages are never asserted on.

The manifests are the same loadable set as ``test_golden_generators``
(``CASES``), so a manifest that starts or stops loading moves in or out of
these cells in step. A command that raises has that pinned as
``{"error": [type, message]}``, as in the generator cells.

``topology`` has no provider in a test (it needs a Prometheus URL), so it
exits 2 after the manifest load step; what is pinned is that exit code, and
that a manifest which no longer loads changes it.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from nthlayer_generate.cli.alerts import (
    alerts_evaluate_command,
    alerts_show_command,
    alerts_test_command,
)
from nthlayer_generate.cli.backstage import generate_backstage_command
from nthlayer_generate.cli.docs import generate_docs_command
from nthlayer_generate.cli.migrate import migrate_command
from nthlayer_generate.cli.simulate import simulate_command
from nthlayer_generate.cli.topology import topology_export_command
from nthlayer_generate.cli.validate import validate_command
from nthlayer_generate.dependencies import DependencyDiscovery
from nthlayer_generate.orchestration.handlers import PolicyHandler
from nthlayer_generate.orchestration.registry import OrchestratorContext
from nthlayer_generate.policies.engine import PolicyEngine
from nthlayer_generate.policies.models import PolicyReport

from ._corpus import EX
from ._golden import check
from .test_golden_generators import CASES, IDS, _error, _graph_from_declared_dependencies, _load

POLICIES = EX / "policies.yaml"


class Env:
    """What a cell may use: the temp dir and captured stdout."""

    def __init__(
        self,
        tmp: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        self.tmp = tmp
        self.capsys = capsys
        self.monkeypatch = monkeypatch

    def stdout_json(self) -> Any:
        """The JSON a command printed to stdout since the last call.

        Raises if stdout is not exactly one JSON document, so noise can never
        be pinned as a value.
        """
        return json.loads(self.capsys.readouterr().out)

    def discard_output(self) -> None:
        self.capsys.readouterr()

    def files(self, root: Path | None = None) -> dict[str, Any]:
        """Every file under ``root`` (default tmp), JSON/YAML parsed, else text."""
        root = root or self.tmp
        out: dict[str, Any] = {}
        for p in sorted(root.rglob("*")):
            if not p.is_file():
                continue
            text = p.read_text(encoding="utf-8")
            rel = p.relative_to(root).as_posix()
            if p.suffix == ".json":
                out[rel] = json.loads(text)
            else:
                out[rel] = text
        return out


# --- cells: (manifest path, env) -> golden value -----------------------------


def migrate(path: Path, env: Env) -> Any:
    out = env.tmp / "out"
    code = migrate_command(str(path), output_dir=str(out))
    # srm/v1 manifests are already migrated: exit 0 and nothing written.
    return {"exit": code, "files": env.files(out) if out.is_dir() else {}}


def validate(path: Path, env: Env) -> Any:
    return {
        "default": validate_command(str(path)),
        "strict": validate_command(str(path), strict=True),
        "policies": validate_command(str(path), policies=str(POLICIES)),
    }


def alerts_evaluate(path: Path, env: Env) -> Any:
    # no_notify is a no-op today: AlertPipeline hard-codes notify=False
    # (slos/pipeline.py:94). It is passed anyway so a notifier can never be hit.
    table = alerts_evaluate_command(str(path), no_notify=True)
    env.discard_output()  # drop the table so stdout holds only the JSON below
    as_json = alerts_evaluate_command(str(path), no_notify=True, output_format="json")
    return {"table_exit": table, "json_exit": as_json, "json": env.stdout_json()}


def alerts_show(path: Path, env: Env) -> Any:
    table = alerts_show_command(str(path))
    env.discard_output()
    as_json = alerts_show_command(str(path), output_format="json")
    return {"table_exit": table, "json_exit": as_json, "json": env.stdout_json()}


def alerts_test(path: Path, env: Env) -> Any:
    return {"exit": alerts_test_command(str(path), no_notify=True)}


def docs(path: Path, env: Env) -> Any:
    out = env.tmp / "out"
    code = generate_docs_command(str(path), output=str(out), include_adr=True, include_api=True)
    return {"exit": code, "files": env.files(out) if out.is_dir() else {}}


def backstage(path: Path, env: Env) -> Any:
    out = env.tmp / "out"
    code = generate_backstage_command(str(path), output=str(out))
    return {"exit": code, "files": env.files(out) if out.is_dir() else {}}


def simulate(path: Path, env: Env) -> Any:
    env.discard_output()
    code = simulate_command(str(path), seed=42, num_runs=200, output_format="json")
    # Exit 2 is an error (no JSON printed); only 0 and 1 carry a result.
    return {"exit": code, "json": env.stdout_json() if code in (0, 1) else None}


def topology(path: Path, env: Env) -> Any:
    # The command gates on a provider (a Prometheus URL) and then asks it for
    # the graph. Satisfy the gate with a URL and replace build_graph, so the
    # command runs load_manifest -> build_topology -> serialise with no
    # network. The graph is constructed input derived only from the
    # manifest's declared dependencies (as in the generator topology cell).
    # A manifest that stops loading changes the exit code to 2 and the file to null.
    async def build_graph(self: Any, names: Any) -> Any:
        return _graph_from_declared_dependencies(_load(path))

    env.monkeypatch.setenv("NTHLAYER_PROMETHEUS_URL", "http://prometheus.invalid")
    env.monkeypatch.setattr(DependencyDiscovery, "build_graph", build_graph)
    out = env.tmp / "topology.json"
    code = topology_export_command(str(path), output_file=str(out))
    return {"exit": code, "topology": json.loads(out.read_text()) if out.is_file() else None}


class _Detector:
    """Serves the shipped policies.yaml rules as a service's PolicyRules."""

    def get_resources_by_kind(self, kind: str) -> list[dict[str, Any]]:
        if kind != "PolicyRules":
            return []
        rules = yaml.safe_load(POLICIES.read_text(encoding="utf-8"))["rules"]
        return [{"spec": {"rules": rules}}]


def policy_handler(path: Path, env: Env) -> Any:
    # The handler returns only a count; record the report it evaluates so the
    # violations are pinned too.
    reports: list[PolicyReport] = []
    real_evaluate = PolicyEngine.evaluate

    def recording_evaluate(self: PolicyEngine, manifest: Any) -> PolicyReport:
        report = real_evaluate(self, manifest)
        reports.append(report)
        return report

    env.monkeypatch.setattr(PolicyEngine, "evaluate", recording_evaluate)
    ctx = OrchestratorContext(
        service_yaml=path,
        service_def={},
        service_name=path.stem,
        output_dir=env.tmp,
        env=None,
        detector=_Detector(),
    )
    count = PolicyHandler().generate(ctx)
    env.discard_output()
    return {"rules_evaluated": count, "reports": reports}


CELLS: dict[str, Callable[[Path, Env], Any]] = {
    "cli_migrate": migrate,
    "cli_validate": validate,
    "cli_alerts_evaluate": alerts_evaluate,
    "cli_alerts_show": alerts_show,
    "cli_alerts_test": alerts_test,
    "cli_docs": docs,
    "cli_backstage": backstage,
    "cli_simulate": simulate,
    "cli_topology": topology,
    "cli_policy_handler": policy_handler,
}
GOLDEN_CELLS = {cell: tuple(IDS) for cell in CELLS}


@pytest.mark.parametrize("cell", sorted(CELLS))
@pytest.mark.parametrize(("mid", "path"), CASES, ids=IDS)
def test_cli(
    cell: str,
    mid: str,
    path: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # No provider and no live Prometheus: the environment must not change a cell.
    for var in ("NTHLAYER_PROMETHEUS_URL", "NTHLAYER_METRICS_USER", "NTHLAYER_METRICS_PASSWORD"):
        monkeypatch.delenv(var, raising=False)
    env = Env(tmp_path, capsys, monkeypatch)
    try:
        value = CELLS[cell](path, env)
    except Exception as e:  # noqa: BLE001 — today's failure is the golden
        value = _error(e)
    check(cell, mid, value, tmp=tmp_path)
