"""Legacy CLI cells: the formerly ``parse_service_file`` commands and plan/apply (wo62.4.2).

These pinned the wired legacy commands before wo62.4.3–4.5 and 4.19 moved
them onto nthlayer-common, so every output change those moves made was a
golden diff; generate 4.0.0 removed the legacy loader (opensrm-wo62.4.6). Each cell drives a command's Python entry point and pins its
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
  and ``EventOrchestrationManager`` are replaced by stubs that fail the cell
  if either is ever constructed.
* Grafana — ``push_grafana`` is off and ``GrafanaProvider`` (imported in the
  function body, so patched at its source) fails the cell if constructed.
* Prometheus — no URL in the environment; ``slo collect`` and
  ``recommend-metrics --check`` get a fixed stub (constant SLI, no
  discovered metrics). ``validate-slo`` runs offline.
* Kubernetes — the ownership provider's ``get_owner`` returns no signal.

Every manifest is a case (``_corpus.CASES``), and every command now loads
every format through nthlayer-common. The env-overlay family reruns the
commands that take ``--env`` over ``ENV_CASES``.
"""

from __future__ import annotations

import itertools
import json
import re
import types
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

from ._corpus import (
    CASES,
    ENV_CASES,
    ENV_IDS,
    ENVIRONMENTS,
    EX,
    FIXTURES,
    IDS,
    LEGACY,
    LEGACY_FIXTURES,
    REPO,
    SRM_V1,
    STAGING,
    V2,
    EnvCase,
    _error,
    no_user_templates,
    rules_as_sets,
)
from ._golden import check

# Wide enough that no line wraps whatever the checkout path; runs of box
# rules and padding are collapsed afterwards (Env.text).
CONSOLE_WIDTH = 10_000

# Environment that could steer a command at a live system or a secret.
SCRUBBED_ENV = (
    "PAGERDUTY_API_KEY",
    # payment-api-pagerduty-demo.yaml writes ${PAGERDUTY_INTEGRATION_KEY} and
    # ${PAGERDUTY_SRE_INTEGRATION_KEY}; specs/alerting.py fills ${VAR} from the
    # environment, so a real key could otherwise be pinned once the manifest
    # path is used.
    "PAGERDUTY_INTEGRATION_KEY",
    "PAGERDUTY_SRE_INTEGRATION_KEY",
    # examples/uat/payment-api.yaml: slack_webhook: "${NTHLAYER_SLACK_WEBHOOK_ALERT}".
    "NTHLAYER_SLACK_WEBHOOK_ALERT",
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
    """What a cell may use: the temp dir, captured stdout and monkeypatch.

    Not test_golden_cli.Env: ``files`` defaults to ``tmp/out`` and parses
    YAML as well as JSON; ``text`` collapses console-width padding; and
    ``stdout_json`` reads one JSON document.
    """

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

    def files(
        self, root: Path | None = None, rules_unordered: Callable[[str], bool] = lambda rel: False
    ) -> dict[str, Any]:
        """Every file under ``root`` (default tmp/out), parsed where JSON/YAML.

        YAML keeps its written order, except files ``rules_unordered`` names:
        their rules are pinned with ``rules_as_sets``, the form these goldens
        were recorded in while a ``list(set(...))`` extractor fed them (see
        ``_corpus.rules_as_sets``).
        """
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
                doc = yaml.safe_load(text)
                out[rel] = rules_as_sets(doc) if rules_unordered(rel) else doc
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
    no_user_templates(mp)
    for var in SCRUBBED_ENV:
        mp.delenv(var, raising=False)
    mp.setattr(ux, "has_gum", lambda: False)
    mp.setattr(ux.console, "_width", CONSOLE_WIDTH)
    mp.setattr(ux.console, "_force_terminal", False)
    # The console fixes its colour mode at import; FORCE_COLOR in the shell
    # would otherwise put ANSI codes into every text cell.
    mp.setattr(ux.console, "_color_system", None)
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
    return {"exit": code, "files": env.files(), "text": env.text()}


def generate_alerts(path: Path, env: Env, environment: str | None) -> Any:
    out = env.tmp / "out" / "alerts.yaml"
    code = generate_alerts_command(str(path), output=str(out), environment=environment)
    return {"exit": code, "files": env.files(rules_unordered=lambda rel: True), "text": env.text()}


def generate_loki_alerts(path: Path, env: Env, environment: str | None) -> Any:
    assert environment is None, "generate-loki-alerts takes no --env"
    out = env.tmp / "out" / "loki-alerts.yaml"
    code = generate_loki_command(str(path), output=str(out))
    return {
        "exit": code,
        "files": env.files(rules_unordered=lambda rel: True),
        "text": _sorted_dependencies(env.text()),
    }


def _sorted_dependencies(lines: list[str]) -> list[str]:
    """Pin the printed "Dependencies: a, b" line sorted.

    Recorded sorted while the legacy loki extractor returned list(set(...));
    the manifest path is declaration-ordered, so this is now a golden-format
    normalisation only (see ``_corpus.rules_as_sets``)."""
    prefix = "Dependencies: "
    return [
        prefix + ", ".join(sorted(line[len(prefix) :].split(", ")))
        if line.startswith(prefix)
        else line
        for line in lines
    ]


def generate_recording_rules(path: Path, env: Env, environment: str | None) -> Any:
    out = env.tmp / "out" / "recording-rules.yaml"
    code = generate_recording_rules_command(str(path), output=str(out), environment=environment)
    return {"exit": code, "files": env.files(), "text": env.text()}


def generate_dashboard(path: Path, env: Env, environment: str | None) -> Any:
    out = env.tmp / "out" / "dashboard.json"
    code = generate_dashboard_command(str(path), output=str(out), environment=environment)
    return {"exit": code, "files": env.files(), "text": env.text()}


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
    json_emitted = list(emitted)
    emitted.clear()
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
        # Recorded per call, so one call emitting cannot be filed under the other.
        "json": json_emitted,
        "check_json": list(emitted),
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


def apply(
    path: Path,
    env: Env,
    environment: str | None,
    *,
    skip: list[str] | None = None,
    only: list[str] | None = None,
) -> Any:
    env.discard_output()
    code = apply_command(
        str(path),
        env=environment,
        output_dir=str(env.tmp / "out"),
        output_format="json",
        skip=skip,
        only=only,
    )
    printed = env.capsys.readouterr().out
    # Handlers print progress lines before the JSON; the JSON is the last
    # top-level document, which print_apply_json writes starting at "{".
    start = printed.rfind("\n{\n") + 1 if "\n{\n" in printed else printed.find("{")
    return {
        "exit": code,
        "json": json.loads(printed[start:]),
        "preamble": _lines(printed[:start]),
        # alerts.yaml was recorded as a set (see _corpus.rules_as_sets); the
        # rest of apply's YAML keeps its written order.
        "files": env.files(rules_unordered=lambda rel: rel == "alerts.yaml"),
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


def _validate_slo_json(env: Env, **kwargs: Any) -> Any:
    env.discard_output()
    code = validate_slo_command(output_format="json", **kwargs)
    doc = json.loads(env.capsys.readouterr().out)
    for result in doc.get("results", []):
        for key in ("metrics", "found_metrics", "missing_metrics"):
            if isinstance(result.get(key), list):
                result[key] = sorted(result[key])
    return {"exit": code, "json": doc}


def validate_slo_demo(env: Env) -> Any:
    # --demo's canned results include an SLO with a missing metric, so this is
    # the one offline input that exits 1 (cli/validate_slo.py:417-419). No
    # manifest can: offline every extracted metric counts as found, and no
    # shipped manifest's SLO has the spec.query or
    # spec.objectives[0].indicator.spec.query the command reads, so every
    # manifest cell above extracts no metrics at all.
    return _validate_slo_json(env, service_file="unused.yaml", demo=True)


def _validate_env_dir(directory: Path) -> Callable[[Env], Any]:
    def cell(env: Env) -> Any:
        out: dict[str, Any] = {}
        for name in ENVIRONMENTS:
            env.discard_output()
            code = validate_env_command(name, directory=str(directory))
            out[name] = {"exit": code, "text": env.text()}
        return out

    return cell


# apply's --skip / --only filter (ServiceOrchestrator._get_filtered_resources). Every CELLS run
# passes neither, so without these the filter is unpinned. plan takes no
# filter. checkout-service plans slos, recording-rules, backstage, alerts,
# dashboard and pagerduty, so each filter visibly drops resources and files.
APPLY_FILTER_SERVICE = EX / "services" / "checkout-service.yaml"


def apply_skip(env: Env) -> Any:
    return apply(APPLY_FILTER_SERVICE, env, None, skip=["alerts", "dashboard"])


def apply_only(env: Env) -> Any:
    return apply(APPLY_FILTER_SERVICE, env, None, only=["slos", "pagerduty"])


def apply_only_and_skip(env: Env) -> Any:
    # only narrows first, then skip removes from what is left.
    return apply(APPLY_FILTER_SERVICE, env, None, only=["slos", "alerts"], skip=["alerts"])


def ownership_table_backstage(env: Env) -> Any:
    """The default table output, with a Backstage signal (R5 provenance).

    The corpus cell pins only --format json, and no fixture yields a
    Backstage signal (its env vars are scrubbed), so _print_ownership_table
    and its per-source details (ownership.py ~185-200) were unpinned. The
    provider is imported in the function body, so its get_owner is patched
    on the class at its source; generate's backstage module re-exports it.
    """
    from nthlayer_common.identity.ownership import OwnershipSignal, OwnershipSource

    async def backstage_owner(self: Any, service: str) -> OwnershipSignal:
        return OwnershipSignal(
            source=OwnershipSource.BACKSTAGE, owner="group:default/commerce", confidence=0.9
        )

    env.monkeypatch.setattr(
        "nthlayer_common.identity.ownership_providers.backstage."
        "BackstageOwnershipProvider.get_owner",
        backstage_owner,
    )
    env.discard_output()
    code = ownership_command(
        str(APPLY_FILTER_SERVICE),
        output_format="table",
        backstage_url="http://backstage.invalid",
        codeowners_root=str(env.tmp),
    )
    return {"exit": code, "text": env.text()}


# --- non-default formats and flags (opensrm-9dbl sweep) -----------------------
#
# The corpus cells above call each command one way: plan/apply/validate-slo/
# recommend-metrics/ownership as JSON, the generators without --dry-run. A
# mutation sweep of cli/ found every other renderer and flag unpinned; these
# cells pin each one once, on a shipped example that reaches the branch.

PD_DEMO_SERVICE = EX / "services" / "payment-api-pagerduty-demo.yaml"

# PagerDuty API failures as apply reports them ("Pagerduty generation failed:
# <message>"). Without --verbose, print_apply_summary cuts an error longer
# than 80 characters to 77 plus "..." (cli/apply.py:64-65): the long one is
# cut, the short one (75 characters reported) is kept whole; the boundary pair
# below pins the threshold itself.
PD_API_FAILURE_LONG = (
    "PagerDuty API returned 401 Unauthorized for POST /teams: "
    "the API key is invalid or has been revoked"
)
PD_API_FAILURE_SHORT = "PagerDuty API returned 503 Service Unavailable"
# cli/apply.py cuts an error longer than 80 characters to 77 + "...". The
# reported line is "Pagerduty generation failed: " (29 characters) + the
# message, so these two put it exactly at 80 (kept whole) and 81 (cut).
_PD_BOUNDARY_BASE = "PagerDuty API returned 429 Too Many Requests: "
PD_API_FAILURE_AT_LIMIT = _PD_BOUNDARY_BASE + "x" * (51 - len(_PD_BOUNDARY_BASE))
PD_API_FAILURE_OVER_LIMIT = _PD_BOUNDARY_BASE + "x" * (52 - len(_PD_BOUNDARY_BASE))


def plan_table(env: Env) -> Any:
    # The default table renderer (cli/plan.py:20-111). payment-api-pagerduty-demo
    # plans every resource kind, including all four PagerDuty sub-resources.
    env.discard_output()
    code = plan_command(str(PD_DEMO_SERVICE))
    return {"exit": code, "text": env.text()}


def plan_markdown(env: Env) -> Any:
    # plan_to_report through a non-JSON formatter (cli/plan.py:114-210).
    env.discard_output()
    code = plan_command(str(PD_DEMO_SERVICE), output_format="markdown")
    return {"exit": code, "text": env.text()}


def _apply_text(path: Path, env: Env, environment: str | None = None, **kwargs: Any) -> Any:
    # A stepping clock keeps the duration positive, so the " in Xs" suffix the
    # summary prints only for a duration above zero is always there.
    ticks = itertools.count(1000.0, 0.5)
    # Swap only the orchestrator's module reference (it uses time.time alone),
    # not time.time itself, which every other caller in the process shares.
    import nthlayer_generate.orchestrator as orchestrator

    env.monkeypatch.setattr(orchestrator, "time", types.SimpleNamespace(time=lambda: next(ticks)))
    env.discard_output()
    code = apply_command(str(path), env=environment, output_dir=str(env.tmp / "out"), **kwargs)
    # The summary line carries the duration ("in 0.3s").
    text = [re.sub(r" in \d+\.\ds\b", " in <duration>", line) for line in env.text()]
    return {"exit": code, "text": text}


def apply_text(env: Env) -> Any:
    # The default text summary (cli/apply.py:14-78).
    return _apply_text(APPLY_FILTER_SERVICE, env)


def apply_text_verbose(env: Env) -> Any:
    # --verbose adds the generated-file list with sizes (cli/apply.py:69-76).
    return _apply_text(APPLY_FILTER_SERVICE, env, verbose=True)


def apply_dry_run_env(env: Env) -> Any:
    # --dry-run is plan's table (cli/apply.py:27-28) and must keep --env:
    # search-api plans more resources in prod than in dev, so a dropped --env shows.
    case = next(c for c in ENV_CASES if c.id == "staged__search-api__env-prod")
    out = _apply_text(case.target(env.tmp), env, case.environment, dry_run=True)
    out["wrote"] = sorted(
        p.relative_to(env.tmp).as_posix()
        for p in env.tmp.rglob("*")
        if p.is_file() and not p.is_relative_to(env.tmp / STAGING)
    )
    return out


def _apply_pd_failure(message: str, verbose: bool = False) -> Callable[[Env], Any]:
    def cell(env: Env) -> Any:
        # With a key, the PagerDuty handler calls the API; make that call fail
        # so the summary's warning marker and error list are reached
        # (cli/apply.py:39-40, 59-66). No shipped example produces an error.
        def failing_manager(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError(message)

        env.monkeypatch.setenv("PAGERDUTY_API_KEY", "stub-key")
        env.monkeypatch.setattr(
            "nthlayer_generate.orchestration.handlers.PagerDutyResourceManager", failing_manager
        )
        return _apply_text(APPLY_FILTER_SERVICE, env, verbose=verbose)

    return cell


def _recommend_table(env: Env, **kwargs: Any) -> Any:
    env.discard_output()
    code = recommend_metrics_command(str(APPLY_FILTER_SERVICE), **kwargs)
    return {"exit": code, "text": env.text()}


def recommend_table(env: Env) -> Any:
    return _recommend_table(env)


def recommend_table_required(env: Env) -> Any:
    return _recommend_table(env, level="required")


def recommend_table_recommended_code(env: Env) -> Any:
    return _recommend_table(env, level="recommended", show_code=True)


def recommend_yaml(env: Env) -> Any:
    env.discard_output()
    code = recommend_metrics_command(str(APPLY_FILTER_SERVICE), output_format="yaml")
    out = env.capsys.readouterr().out
    # Raw stdout, not env.text(): its padding collapse would rewrite the YAML
    # indentation. The console header precedes the document on the same stream.
    return {"exit": code, "text": _lines(out)}


def validate_slo_table(env: Env) -> Any:
    # Offline, every SLO counts as found: the all-valid summary.
    env.discard_output()
    code = validate_slo_command(str(APPLY_FILTER_SERVICE))
    return {"exit": code, "text": env.text()}


def validate_slo_table_demo(env: Env) -> Any:
    # --demo has a missing metric: the Missing status and partial summary.
    env.discard_output()
    code = validate_slo_command("unused.yaml", demo=True)
    return {"exit": code, "text": env.text()}


def generate_slo_dry_run(env: Env) -> Any:
    env.discard_output()
    code = generate_slo_command(
        str(APPLY_FILTER_SERVICE), output_dir=str(env.tmp / "out"), dry_run=True
    )
    return {"exit": code, "files": env.files(), "text": env.text()}


def generate_slo_unsupported_format(env: Env) -> Any:
    # The CLI offers sloth/prometheus/openslo; only sloth is implemented.
    env.discard_output()
    code = generate_slo_command(
        str(APPLY_FILTER_SERVICE), output_dir=str(env.tmp / "out"), format="openslo"
    )
    return {"exit": code, "files": env.files(), "text": env.text()}


def generate_alerts_dry_run(env: Env) -> Any:
    env.discard_output()
    out = env.tmp / "out" / "alerts.yaml"
    code = generate_alerts_command(str(APPLY_FILTER_SERVICE), output=str(out), dry_run=True)
    return {"exit": code, "files": env.files(), "text": env.text()}


def generate_alerts_links(env: Env) -> Any:
    # --runbook-url, --notification-channel and --grafana-url reach the rules.
    env.discard_output()
    out = env.tmp / "out" / "alerts.yaml"
    code = generate_alerts_command(
        str(APPLY_FILTER_SERVICE),
        output=str(out),
        runbook_url="https://runbooks.example.invalid",
        notification_channel="slack",
        grafana_url="https://grafana.example.invalid",
    )
    # The written rule file is pinned as a set (see _corpus.rules_as_sets); the
    # printed preview is in the manifest's declaration order.
    return {"exit": code, "files": env.files(rules_unordered=lambda rel: True), "text": env.text()}


def generate_recording_rules_dry_run(env: Env) -> Any:
    env.discard_output()
    code = generate_recording_rules_command(str(APPLY_FILTER_SERVICE), dry_run=True)
    return {"exit": code, "files": env.files(env.tmp), "text": env.text()}


def generate_loki_dry_run(env: Env) -> Any:
    env.discard_output()
    code = generate_loki_command(str(APPLY_FILTER_SERVICE), dry_run=True)
    return {"exit": code, "files": env.files(env.tmp), "text": env.text()}


def generate_dashboard_dry_run(env: Env) -> Any:
    env.discard_output()
    code = generate_dashboard_command(str(APPLY_FILTER_SERVICE), dry_run=True)
    printed = env.capsys.readouterr().out
    # Raw stdout: the slice needs the unsplit text, and env.text() would collapse
    # runs of spaces inside JSON string values.
    start = printed.index("\n{") + 1
    end = printed.rindex("}") + 1
    return {
        "exit": code,
        "files": env.files(env.tmp),
        "dashboard": json.loads(printed[start:end]),
        "text": _lines(printed[:start]) + _lines(printed[end:]),
    }


def generate_dashboard_full_panels(env: Env) -> Any:
    # --full-panels changes only the "Mode:" log line today:
    # build_dashboard_from_manifest passes it through ManifestDashboardBuilder
    # to DashboardBuilderSDK, which stores self.full_panels and never reads it
    # (dashboards/builder_sdk.py:57).
    env.discard_output()
    out = env.tmp / "out" / "dashboard.json"
    code = generate_dashboard_command(str(APPLY_FILTER_SERVICE), output=str(out), full_panels=True)
    return {"exit": code, "files": env.files(), "text": env.text()}


def _ownership_demo(output_format: str) -> Callable[[Env], Any]:
    def cell(env: Env) -> Any:
        env.discard_output()
        code = ownership_command("unused.yaml", output_format=output_format, demo=True)
        if output_format == "json":
            return {"exit": code, "json": env.stdout_json()}
        return {"exit": code, "text": env.text()}

    return cell


SINGLETONS: dict[str, dict[str, Callable[[Env], Any]]] = {
    "cli_legacy_apply_filter": {
        "checkout-service__skip": apply_skip,
        "checkout-service__only": apply_only,
        "checkout-service__only_and_skip": apply_only_and_skip,
    },
    "cli_legacy_ownership_table": {"checkout-service__backstage": ownership_table_backstage},
    "cli_legacy_slo_list": {"repo": slo_list},
    "cli_legacy_validate_env_dir": {
        "examples": _validate_env_dir(EX),
        "examples__services": _validate_env_dir(EX / "services"),
    },
    "cli_legacy_validate_slo_exit": {
        "demo": validate_slo_demo,
    },
    "cli_legacy_plan_formats": {
        "payment-api-pagerduty-demo__table": plan_table,
        "payment-api-pagerduty-demo__markdown": plan_markdown,
    },
    "cli_legacy_apply_text": {
        "checkout-service": apply_text,
        "checkout-service__verbose": apply_text_verbose,
        "checkout-service__pagerduty_failure": _apply_pd_failure(PD_API_FAILURE_LONG),
        "checkout-service__pagerduty_failure__verbose": _apply_pd_failure(
            PD_API_FAILURE_LONG, verbose=True
        ),
        "checkout-service__pagerduty_failure_short": _apply_pd_failure(PD_API_FAILURE_SHORT),
        "checkout-service__pagerduty_failure_at_limit": _apply_pd_failure(PD_API_FAILURE_AT_LIMIT),
        "checkout-service__pagerduty_failure_over_limit": _apply_pd_failure(
            PD_API_FAILURE_OVER_LIMIT
        ),
        "staged__search-api__env-prod__dry_run": apply_dry_run_env,
    },
    "cli_legacy_recommend_metrics_formats": {
        "checkout-service__table": recommend_table,
        "checkout-service__table_required": recommend_table_required,
        "checkout-service__table_recommended_show_code": recommend_table_recommended_code,
        "checkout-service__yaml": recommend_yaml,
    },
    "cli_legacy_validate_slo_table": {
        "checkout-service": validate_slo_table,
        "demo": validate_slo_table_demo,
    },
    "cli_legacy_generator_flags": {
        "generate_slo__dry_run": generate_slo_dry_run,
        "generate_slo__format_openslo": generate_slo_unsupported_format,
        "generate_alerts__dry_run": generate_alerts_dry_run,
        "generate_alerts__links": generate_alerts_links,
        "generate_recording_rules__dry_run": generate_recording_rules_dry_run,
        "generate_loki_alerts__dry_run": generate_loki_dry_run,
        "generate_dashboard__dry_run": generate_dashboard_dry_run,
        "generate_dashboard__full_panels": generate_dashboard_full_panels,
    },
    "cli_legacy_ownership_demo": {
        "json": _ownership_demo("json"),
        "table": _ownership_demo("table"),
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


def test_isolate_hides_user_templates_above_the_cwd_and_the_manifest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """R5 edge-cases: a .nthlayer/templates above TMPDIR changed 141 cells.

    Both lookups are covered: generate's walks up from the cwd, and
    nthlayer-common's, which every CLI cell now loads through, walks up from
    the manifest. Corpus files live in the checkout, so ``~/.nthlayer/templates``
    is within common's reach (wo62.4.6).
    """
    import nthlayer_common.manifest.parser.loader as common_loader

    from nthlayer_generate.specs.custom_templates import CustomTemplateLoader

    templates = tmp_path / ".nthlayer" / "templates"
    templates.mkdir(parents=True)
    work = tmp_path / "work"
    work.mkdir()
    manifest = work / "services" / "service.yaml"
    manifest.parent.mkdir()
    manifest.write_text("service: {name: probe, team: t, tier: low}\n", encoding="utf-8")
    monkeypatch.chdir(work)
    # Anti-vacuity: unpatched, both walks find the dir above them.
    assert CustomTemplateLoader.find_templates_directory() is not None
    assert common_loader._find_template_dir(manifest) == templates.resolve()

    _isolate(Env(work, capsys, monkeypatch))
    assert CustomTemplateLoader.find_templates_directory() is None
    assert common_loader._find_template_dir(manifest) is None


def test_corpus_and_env_cases_are_non_empty() -> None:
    # A zero-case parametrise would leave these cells green and empty.
    assert CASES
    assert len(CASES) == len(SRM_V1) + len(LEGACY) + len(V2) + len(LEGACY_FIXTURES)
    assert len(ENV_CASES) == 10
    assert all(c.base.is_file() for c in ENV_CASES)


def test_legacy_fixtures_are_listed_and_name_their_branch() -> None:
    # A fixture file nobody lists is never run; one with no provenance header
    # cannot be checked against the branch it claims to reach.
    on_disk = sorted((FIXTURES / "legacy").rglob("*.yaml"))
    overlays = [p for p in on_disk if p.parent.name == "environments"]
    assert sorted(LEGACY_FIXTURES) == sorted(set(on_disk) - set(overlays))
    for p in on_disk:
        header = p.read_text(encoding="utf-8").split("\n\n", 1)[0]
        assert header.startswith("# TEST-ONLY golden fixture"), p.name
        # The branch is in generate or, since the legacy loader moved there,
        # in nthlayer-common (opensrm-wo62.4.6).
        assert "src/nthlayer_generate/" in header or "src/nthlayer_common/" in header, p.name
        assert "examples/" in header, p.name


def test_every_env_case_finds_an_overlay(tmp_path: Path) -> None:
    # An env case with no overlay file would pin the base output under an
    # env name and test nothing about the merge. This is the lookup the CLI
    # loads through (nthlayer-common), not generate's former EnvironmentLoader.
    from nthlayer_common.manifest.parser.legacy import find_environment_file

    for case in ENV_CASES:
        target = case.target(tmp_path / case.id)
        assert find_environment_file(target, case.environment), case.id
