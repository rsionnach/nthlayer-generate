"""Legacy CLI cells: the ``parse_service_file`` commands and plan/apply (wo62.4.2).

These pin the wired legacy commands before wo62.4.3–4.5 move them onto
nthlayer-common. Each cell drives a command's Python entry point and pins its
exit code, the files it wrote under the temp dir (YAML/JSON parsed), and the
JSON it printed where it offers JSON.

Commands whose only result is console text (``slo show/list/collect``,
``diff-envs``, ``validate-env``, ``setup-pagerduty --dry-run``) have that
text pinned whole, never matched on: see ``Env.text``. The console is pinned
to plain Rich output — ``gum`` is hidden (ux.has_gum, which would otherwise
shell out on machines that have it) and the width is fixed wide enough that
no line wraps, so checkout path length cannot move a line break.

No cell reaches a network:

* PagerDuty — ``PAGERDUTY_API_KEY`` is unset; ``setup-pagerduty`` runs dry,
  without a key, and with ``PagerDutyClient`` replaced at its use site
  (cli/pagerduty.py imports it by name) by a recorder, so the arguments the
  command would send are pinned. plan/apply's ``PagerDutyResourceManager``
  is replaced by a stub that fails the cell if it is ever constructed.
* Grafana — ``push_grafana`` is off and ``GrafanaProvider`` (imported in the
  function body, so patched at its source) fails the cell if constructed.
* Prometheus — no URL in the environment; ``slo collect`` and
  ``recommend-metrics --check`` get a fixed stub (constant SLI, no
  discovered metrics). ``validate-slo`` runs offline.
* Kubernetes — the ownership provider's ``get_owner`` returns no signal.

As in the library cells, every manifest is a case (the legacy parser's
rejection of srm/v1 and v2 is pinned), and the env-overlay family reruns the
commands that take ``--env`` over ``ENV_CASES``.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from nthlayer_generate.cli import ux
from nthlayer_generate.cli.apply import apply_command
from nthlayer_generate.cli.dashboard import generate_dashboard_command
from nthlayer_generate.cli.environments import diff_envs_command, validate_env_command
from nthlayer_generate.cli.generate import generate_slo_command
from nthlayer_generate.cli.generate_alerts import generate_alerts_command
from nthlayer_generate.cli.generate_loki import generate_loki_command
from nthlayer_generate.cli.ownership import ownership_command
from nthlayer_generate.cli.pagerduty import setup_pagerduty_command
from nthlayer_generate.cli.plan import plan_command
from nthlayer_generate.cli.recommend_metrics import recommend_metrics_command
from nthlayer_generate.cli.recording_rules import generate_recording_rules_command
from nthlayer_generate.cli.slo import slo_collect_command, slo_list_command, slo_show_command
from nthlayer_generate.cli.validate_slo import validate_slo_command
from nthlayer_generate.integrations.pagerduty import PagerDutySetupResult
from nthlayer_generate.orchestrator import ServiceOrchestrator

from ._corpus import EX, REPO, _error
from ._golden import check
from .test_golden_legacy_generators import (
    CASES,
    ENV_CASES,
    ENV_IDS,
    ENVIRONMENTS,
    IDS,
    STAGING,
    EnvCase,
    rules_as_sets,
)

# Wide enough that no line wraps whatever the checkout path; runs of box
# rules and padding are collapsed afterwards (Env.text).
CONSOLE_WIDTH = 10_000

# Environment that could steer a command at a live system or a secret.
SCRUBBED_ENV = (
    "PAGERDUTY_API_KEY",
    "PAGERDUTY_FROM_EMAIL",
    "PROMETHEUS_URL",
    "NTHLAYER_PROMETHEUS_URL",
    "NTHLAYER_METRICS_USER",
    "NTHLAYER_METRICS_PASSWORD",
    "NTHLAYER_GRAFANA_URL",
    "NTHLAYER_GRAFANA_API_KEY",
    "NTHLAYER_GRAFANA_ORG_ID",
    "NTHLAYER_BACKSTAGE_URL",
    "NTHLAYER_BACKSTAGE_TOKEN",
    "NTHLAYER_K8S_NAMESPACE",
    "FORCE_COLOR",
    "NO_COLOR",
)

STUB_SLI = 0.9995


class Env:
    """What a cell may use: the temp dir, captured stdout and monkeypatch."""

    def __init__(
        self,
        tmp: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        self.tmp = tmp
        self.capsys = capsys
        self.monkeypatch = monkeypatch

    def discard_output(self) -> None:
        self.capsys.readouterr()

    def stdout_json(self) -> Any:
        """Stdout since the last read, as exactly one JSON document."""
        return json.loads(self.capsys.readouterr().out)

    def text(self) -> list[str]:
        """Stdout since the last read, as lines, for pinning whole.

        Trailing space is dropped, and runs of box-drawing rule or of padding
        (which only scale with the fixed console width) are collapsed, so the
        golden holds the words and their order, not 10,000 columns.
        """
        out = self.capsys.readouterr().out
        lines = []
        for line in out.splitlines():
            line = re.sub(r"─{3,}", "──", line.rstrip())
            lines.append(re.sub(r" {3,}", "  ", line))
        return lines

    def files(self, root: Path | None = None) -> dict[str, Any]:
        """Every file under ``root`` (default tmp/out), parsed where JSON/YAML."""
        root = root or self.tmp / "out"
        out: dict[str, Any] = {}
        if not root.is_dir():
            return out
        for p in sorted(root.rglob("*")):
            if not p.is_file():
                continue
            text = p.read_text(encoding="utf-8")
            rel = p.relative_to(root).as_posix()
            if p.suffix == ".json":
                out[rel] = json.loads(text)
            elif p.suffix in (".yaml", ".yml"):
                out[rel] = rules_as_sets(yaml.safe_load(text))
            else:
                out[rel] = text
        return out


# --- stubs --------------------------------------------------------------------


class _NoNetwork:
    """Fails the cell if a client that would reach a real API is built."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise AssertionError(f"{type(self).__name__} constructed in a golden cell")


class _RecordingPagerDutyClient:
    """Stands in for PagerDutyClient: records setup_service, reports success."""

    calls: list[dict[str, Any]]

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def __enter__(self) -> _RecordingPagerDutyClient:
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def setup_service(self, **kwargs: Any) -> PagerDutySetupResult:
        type(self).calls.append(kwargs)
        return PagerDutySetupResult(
            success=True,
            service_id="PSTUB01",
            service_url="https://example.invalid/services/PSTUB01",
            created_service=True,
        )


class _StubPrometheusProvider:
    """Returns one constant SLI for every query and records the queries."""

    queries: list[str]

    def __init__(self, url: str, username: Any = None, password: Any = None) -> None:
        self.url = url

    async def get_sli_value(self, query: str) -> float:
        type(self).queries.append(query)
        return STUB_SLI


def _isolate(env: Env) -> None:
    mp = env.monkeypatch
    for var in SCRUBBED_ENV:
        mp.delenv(var, raising=False)
    mp.setattr(ux, "has_gum", lambda: False)
    mp.setattr(ux.console, "_width", CONSOLE_WIDTH)
    mp.setattr(ux.console, "_force_terminal", False)
    mp.setattr(
        "nthlayer_generate.orchestration.handlers.PagerDutyResourceManager",
        type("PagerDutyResourceManager", (_NoNetwork,), {}),
    )
    mp.setattr(
        "nthlayer_generate.orchestration.handlers.EventOrchestrationManager",
        type("EventOrchestrationManager", (_NoNetwork,), {}),
    )
    mp.setattr(
        "nthlayer_generate.providers.grafana.GrafanaProvider",
        type("GrafanaProvider", (_NoNetwork,), {}),
    )
    mp.setattr(
        "nthlayer_generate.cli.pagerduty.PagerDutyClient",
        type("PagerDutyClient", (_NoNetwork,), {}),
    )

    async def no_k8s_owner(self: Any, service: str) -> None:
        return None

    mp.setattr(
        "nthlayer_common.identity.ownership_providers.kubernetes."
        "KubernetesOwnershipProvider.get_owner",
        no_k8s_owner,
    )
    mp.chdir(env.tmp)


# --- cells: (service file, env, environment) -> golden value ------------------


def generate_slo(path: Path, env: Env, environment: str | None) -> Any:
    code = generate_slo_command(str(path), output_dir=str(env.tmp / "out"), environment=environment)
    return {"exit": code, "files": env.files()}


def generate_alerts(path: Path, env: Env, environment: str | None) -> Any:
    out = env.tmp / "out" / "alerts.yaml"
    code = generate_alerts_command(str(path), output=str(out), environment=environment)
    return {"exit": code, "files": env.files()}


def generate_loki_alerts(path: Path, env: Env, environment: str | None) -> Any:
    assert environment is None, "generate-loki-alerts takes no --env"
    out = env.tmp / "out" / "loki-alerts.yaml"
    return {"exit": generate_loki_command(str(path), output=str(out)), "files": env.files()}


def generate_recording_rules(path: Path, env: Env, environment: str | None) -> Any:
    out = env.tmp / "out" / "recording-rules.yaml"
    code = generate_recording_rules_command(str(path), output=str(out), environment=environment)
    return {"exit": code, "files": env.files()}


def generate_dashboard(path: Path, env: Env, environment: str | None) -> Any:
    out = env.tmp / "out" / "dashboard.json"
    code = generate_dashboard_command(str(path), output=str(out), environment=environment)
    return {"exit": code, "files": env.files()}


def recommend_metrics(path: Path, env: Env, environment: str | None) -> Any:
    # The JSON is printed after the header on the same stream, so record the
    # value _output_json serialises rather than parse it out of console text.
    import nthlayer_generate.cli.recommend_metrics as rm

    emitted: list[dict[str, Any]] = []
    real_output_json = rm._output_json

    def recording_output_json(recommendation: Any) -> None:
        emitted.append(recommendation.to_dict())
        real_output_json(recommendation)

    env.monkeypatch.setattr(rm, "_output_json", recording_output_json)
    as_json = recommend_metrics_command(str(path), output_format="json", environment=environment)
    # --check against a Prometheus that has none of the metrics.
    env.monkeypatch.setattr(rm, "discover_service_metrics", lambda **kwargs: [])
    checked = recommend_metrics_command(
        str(path),
        prometheus_url="http://prometheus.invalid",
        output_format="json",
        check=True,
        environment=environment,
    )
    env.discard_output()
    return {
        "json_exit": as_json,
        "check_exit": checked,
        "json": emitted[0] if emitted else None,
        "check_json": emitted[1] if len(emitted) > 1 else None,
    }


def setup_pagerduty(path: Path, env: Env, environment: str | None) -> Any:
    no_key = setup_pagerduty_command(str(path), environment=environment)
    env.discard_output()
    dry = setup_pagerduty_command(
        str(path), api_key="stub-key", environment=environment, dry_run=True
    )
    dry_text = env.text()
    _RecordingPagerDutyClient.calls = []
    env.monkeypatch.setattr(
        "nthlayer_generate.cli.pagerduty.PagerDutyClient", _RecordingPagerDutyClient
    )
    stubbed = setup_pagerduty_command(str(path), api_key="stub-key", environment=environment)
    env.discard_output()
    return {
        "no_key_exit": no_key,
        "dry_run_exit": dry,
        "dry_run_text": dry_text,
        "stubbed_exit": stubbed,
        "setup_service_calls": _RecordingPagerDutyClient.calls,
    }


def validate_slo(path: Path, env: Env, environment: str | None) -> Any:
    env.discard_output()
    code = validate_slo_command(str(path), environment=environment, output_format="json")
    out = env.capsys.readouterr().out
    try:
        doc = json.loads(out)
    except ValueError:
        # Parse errors and "no SLOs" print a message, not JSON.
        return {"exit": code, "json": None, "text": _lines(out)}
    # extract_metric_names returns a set (cli/validate_slo.py:162), so the
    # metric lists follow PYTHONHASHSEED; pin them as sets.
    for result in doc.get("results", []):
        for key in ("metrics", "found_metrics", "missing_metrics"):
            if isinstance(result.get(key), list):
                result[key] = sorted(result[key])
    return {"exit": code, "json": doc}


def _lines(out: str) -> list[str]:
    return [line.rstrip() for line in out.splitlines()]


def ownership(path: Path, env: Env, environment: str | None) -> Any:
    env.discard_output()
    code = ownership_command(
        str(path),
        environment=environment,
        output_format="json",
        codeowners_root=str(env.tmp),
    )
    out = env.capsys.readouterr().out
    try:
        return {"exit": code, "json": json.loads(out)}
    except ValueError:
        return {"exit": code, "json": None, "text": _lines(out)}


def slo_show(path: Path, env: Env, environment: str | None) -> Any:
    env.discard_output()
    code = slo_show_command(path.stem, service_file=str(path))
    return {"exit": code, "text": env.text()}


def slo_collect(path: Path, env: Env, environment: str | None) -> Any:
    _StubPrometheusProvider.queries = []
    env.monkeypatch.setattr(
        "nthlayer_generate.providers.prometheus.PrometheusProvider", _StubPrometheusProvider
    )
    env.discard_output()
    code = slo_collect_command(
        path.stem, prometheus_url="http://prometheus.invalid", service_file=str(path)
    )
    return {"exit": code, "queries": _StubPrometheusProvider.queries, "text": env.text()}


def diff_envs(path: Path, env: Env, environment: str | None) -> Any:
    # _diff_dicts walks ``set(d1) | set(d2)`` (cli/environments.py:441), so
    # the order it prints spec differences in follows PYTHONHASHSEED. Hand
    # the command the same differences sorted by key; every difference is
    # still printed and pinned, only that arbitrary order is fixed.
    import nthlayer_generate.cli.environments as envs

    real_diff = envs._diff_dicts

    def sorted_diff(d1: dict, d2: dict, prefix: str = "") -> dict[str, tuple[Any, Any]]:
        return dict(sorted(real_diff(d1, d2, prefix).items()))

    env.monkeypatch.setattr(envs, "_diff_dicts", sorted_diff)
    out: dict[str, Any] = {}
    for a, b in (("dev", "prod"), ("dev", "staging"), ("staging", "prod")):
        env.discard_output()
        code = diff_envs_command(str(path), a, b, show_all=True)
        out[f"{a}..{b}"] = {"exit": code, "text": env.text()}
    return out


def validate_env(path: Path, env: Env, environment: str | None) -> Any:
    out: dict[str, Any] = {}
    for name in ENVIRONMENTS:
        env.discard_output()
        code = validate_env_command(name, service_file=str(path))
        out[name] = {"exit": code, "text": env.text()}
    return out


def plan(path: Path, env: Env, environment: str | None) -> Any:
    result = ServiceOrchestrator(path, env=environment).plan()
    env.discard_output()
    code = plan_command(str(path), env=environment, output_format="json")
    return {
        "plan": result,
        "success": result.success,
        "total_resources": result.total_resources,
        "json_exit": code,
        "json": env.stdout_json(),
    }


def apply(path: Path, env: Env, environment: str | None) -> Any:
    env.discard_output()
    code = apply_command(
        str(path), env=environment, output_dir=str(env.tmp / "out"), output_format="json"
    )
    printed = env.capsys.readouterr().out
    # Handlers print progress lines before the JSON; the JSON is the last
    # top-level document, which print_apply_json writes starting at "{".
    start = printed.rfind("\n{\n") + 1 if "\n{\n" in printed else printed.find("{")
    return {
        "exit": code,
        "json": json.loads(printed[start:]),
        "preamble": _lines(printed[:start]),
        "files": env.files(),
        # Anything written outside the output dir (relative default paths).
        "stray": sorted(
            p.relative_to(env.tmp).as_posix()
            for p in env.tmp.rglob("*")
            if p.is_file()
            and not p.is_relative_to(env.tmp / "out")
            and not p.is_relative_to(env.tmp / STAGING)
        ),
    }


CliCell = Callable[[Path, Env, "str | None"], Any]

CELLS: dict[str, CliCell] = {
    "cli_legacy_generate_slo": generate_slo,
    "cli_legacy_generate_alerts": generate_alerts,
    "cli_legacy_generate_loki_alerts": generate_loki_alerts,
    "cli_legacy_generate_recording_rules": generate_recording_rules,
    "cli_legacy_generate_dashboard": generate_dashboard,
    "cli_legacy_recommend_metrics": recommend_metrics,
    "cli_legacy_setup_pagerduty": setup_pagerduty,
    "cli_legacy_validate_slo": validate_slo,
    "cli_legacy_ownership": ownership,
    "cli_legacy_slo_show": slo_show,
    "cli_legacy_slo_collect": slo_collect,
    "cli_legacy_diff_envs": diff_envs,
    "cli_legacy_validate_env": validate_env,
    "cli_legacy_plan": plan,
    "cli_legacy_apply": apply,
}
ENV_CELLS: dict[str, CliCell] = {
    "cli_legacy_env_generate_slo": generate_slo,
    "cli_legacy_env_generate_alerts": generate_alerts,
    "cli_legacy_env_generate_recording_rules": generate_recording_rules,
    "cli_legacy_env_generate_dashboard": generate_dashboard,
    "cli_legacy_env_recommend_metrics": recommend_metrics,
    "cli_legacy_env_setup_pagerduty": setup_pagerduty,
    "cli_legacy_env_validate_slo": validate_slo,
    "cli_legacy_env_ownership": ownership,
    "cli_legacy_env_plan": plan,
    "cli_legacy_env_apply": apply,
}


# --- cells with no manifest axis ----------------------------------------------


def slo_list(env: Env) -> Any:
    # Scans services/ and examples/services/ under the cwd: run from the repo.
    env.monkeypatch.chdir(REPO)
    env.discard_output()
    code = slo_list_command()
    text = env.text()
    # Rows are sorted by (service, SLO) only, and several files declare the
    # same service and SLO, so ties keep Path.glob order, which the
    # filesystem decides. Pin the table body as a sorted multiset of rows.
    rule = "-" * 70
    if rule in text:
        start = text.index(rule) + 1
        end = text.index("", start) if "" in text[start:] else len(text)
        text[start:end] = sorted(text[start:end])
    return {"exit": code, "text": text}


def _validate_env_dir(directory: Path) -> Callable[[Env], Any]:
    def cell(env: Env) -> Any:
        out: dict[str, Any] = {}
        for name in ENVIRONMENTS:
            env.discard_output()
            code = validate_env_command(name, directory=str(directory))
            out[name] = {"exit": code, "text": env.text()}
        return out

    return cell


SINGLETONS: dict[str, dict[str, Callable[[Env], Any]]] = {
    "cli_legacy_slo_list": {"repo": slo_list},
    "cli_legacy_validate_env_dir": {
        "examples": _validate_env_dir(EX),
        "examples__services": _validate_env_dir(EX / "services"),
    },
}

GOLDEN_CELLS = {
    **{cell: tuple(IDS) for cell in CELLS},
    **{cell: tuple(ENV_IDS) for cell in ENV_CELLS},
    **{cell: tuple(ids) for cell, ids in SINGLETONS.items()},
}
SINGLETON_CASES = [(cell, sid) for cell, ids in sorted(SINGLETONS.items()) for sid in sorted(ids)]


def _check(cell: str, mid: str, run: Callable[[], Any], tmp: Path) -> None:
    try:
        value = run()
    except Exception as e:  # noqa: BLE001 — today's failure is the golden
        value = _error(e)
    check(cell, mid, value, tmp=tmp)


@pytest.mark.parametrize("cell", sorted(CELLS))
@pytest.mark.parametrize(("mid", "path"), CASES, ids=IDS)
def test_legacy_cli(
    cell: str,
    mid: str,
    path: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = Env(tmp_path, capsys, monkeypatch)
    _isolate(env)
    _check(cell, mid, lambda: CELLS[cell](path, env, None), tmp_path)


@pytest.mark.parametrize("cell", sorted(ENV_CELLS))
@pytest.mark.parametrize("case", ENV_CASES, ids=ENV_IDS)
def test_legacy_cli_env(
    cell: str,
    case: EnvCase,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = Env(tmp_path, capsys, monkeypatch)
    _isolate(env)
    path = case.target(tmp_path)
    _check(cell, case.id, lambda: ENV_CELLS[cell](path, env, case.environment), tmp_path)


@pytest.mark.parametrize(("cell", "sid"), SINGLETON_CASES)
def test_legacy_cli_singleton(
    cell: str,
    sid: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = Env(tmp_path, capsys, monkeypatch)
    _isolate(env)
    _check(cell, sid, lambda: SINGLETONS[cell][sid](env), tmp_path)
