"""Legacy library cells: the ``parse_service_file`` builders over the corpus (wo62.4.2).

These pin the legacy entry points *before* wo62.4.3–4.5 switch them onto
nthlayer-common, so every output change that switch makes is a golden diff.

Two families of cells:

* ``legacy_*`` — each legacy builder over every manifest in the corpus
  (srm/v1, legacy ``service:`` and OpenSRM v2). The set is not filtered by
  what loads: the legacy parser rejects srm/v1 and v2 today, and that
  rejection is pinned as ``{"error": [type, message]}``. A manifest the
  switch starts accepting is then a golden diff, not a silently new case.
* ``legacy_env_*`` — the same builders run with an environment set, over the
  shipped environment overlays (see ``ENV_CASES``). No other golden covers
  the overlay merge.
* ``legacy_dashboard_no_intent`` — ``DashboardBuilderSDK`` with
  ``use_intent_templates=False``, the only way to reach its hardcoded health
  panels (dashboards/builder_sdk.py:361-480): ``build_dashboard`` always
  finds an intent template, falling back to "http".

Both families also run over ``LEGACY_FIXTURES`` (``_corpus``): test-only
inputs that reach legacy branches no shipped example reaches.

Every cell runs with the working directory set to the temp dir, because the
legacy parser searches upward from the cwd for ``.nthlayer/templates``
(specs/custom_templates.py); a checkout-dependent cwd would make the golden
checkout-dependent.

``generate_loki_alerts_for_service_file`` takes no environment, so it has no
env-overlay cell.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from nthlayer_generate.dashboards.builder_sdk import DashboardBuilderSDK, build_dashboard
from nthlayer_generate.generators.alerts import generate_alerts_for_service
from nthlayer_generate.generators.sloth import generate_sloth_spec
from nthlayer_generate.loki.generator import generate_loki_alerts_for_service_file
from nthlayer_generate.metrics.recommender import recommend_metrics
from nthlayer_generate.recording_rules.builder import build_recording_rules
from nthlayer_generate.recording_rules.models import create_rule_groups
from nthlayer_generate.specs.parser import parse_service_file

from ._corpus import (
    CASES,
    ENV_CASES,
    ENV_IDS,
    IDS,
    LEGACY,
    LEGACY_FIXTURES,
    EnvCase,
    _error,
    manifest_id,
    no_user_templates,
    rules_as_sets,
)
from ._golden import check

# Legacy-format inputs only: srm/v1 and v2 fail to parse before any builder.
NO_INTENT_CASES: tuple[tuple[str, Path], ...] = tuple(
    (manifest_id(p), p) for p in LEGACY + LEGACY_FIXTURES
)
NO_INTENT_IDS = [i for i, _ in NO_INTENT_CASES]


# --- normalisation ------------------------------------------------------------


def _read_yaml(path: Path | None) -> Any:
    """A written YAML file as structure; ``None`` when nothing was written."""
    if path is None or not path.is_file():
        return None
    return yaml.safe_load(path.read_text(encoding="utf-8"))


# --- cells: (service file, tmp, environment) -> golden value ------------------


def sloth(path: Path, tmp: Path, environment: str | None) -> Any:
    result = generate_sloth_spec(path, tmp / "out", environment=environment)
    if not result.success:
        return {"error": result.error, "service": result.service}
    return {"slo_count": result.slo_count, "spec": _read_yaml(result.output_file)}


def alerts(path: Path, tmp: Path, environment: str | None) -> Any:
    out = tmp / "alerts.yaml"
    rules = generate_alerts_for_service(path, output_file=out, environment=environment, quiet=True)
    # No file is written when no alerts are generated; that pins as null.
    return {"count": len(rules), "file": rules_as_sets(_read_yaml(out))}


def recording_rules(path: Path, tmp: Path, environment: str | None) -> Any:
    context, resources = parse_service_file(path, environment=environment)
    return yaml.safe_load(create_rule_groups(build_recording_rules(context, resources)))


def dashboard(path: Path, tmp: Path, environment: str | None) -> Any:
    context, resources = parse_service_file(path, environment=environment)
    return build_dashboard(context, resources)


def metrics(path: Path, tmp: Path, environment: str | None) -> Any:
    context, _resources = parse_service_file(path, environment=environment)
    return recommend_metrics(context).to_dict()


def loki(path: Path, tmp: Path, environment: str | None) -> Any:
    assert environment is None, "the legacy loki path takes no environment"
    alerts_, ruler_file = generate_loki_alerts_for_service_file(path, tmp)
    return {"count": len(alerts_), "file": rules_as_sets(_read_yaml(ruler_file))}


def dashboard_no_intent(path: Path, tmp: Path, environment: str | None) -> Any:
    context, resources = parse_service_file(path, environment=environment)
    return DashboardBuilderSDK(context, resources, use_intent_templates=False).build()


Cell = Callable[[Path, Path, "str | None"], Any]

CELLS: dict[str, Cell] = {
    "legacy_sloth": sloth,
    "legacy_alerts": alerts,
    "legacy_recording_rules": recording_rules,
    "legacy_dashboard": dashboard,
    "legacy_metrics": metrics,
    "legacy_loki": loki,
}
ENV_CELLS: dict[str, Cell] = {
    "legacy_env_sloth": sloth,
    "legacy_env_alerts": alerts,
    "legacy_env_recording_rules": recording_rules,
    "legacy_env_dashboard": dashboard,
    "legacy_env_metrics": metrics,
}
NO_INTENT_CELL = "legacy_dashboard_no_intent"
GOLDEN_CELLS = {
    **{cell: tuple(IDS) for cell in CELLS},
    **{cell: tuple(ENV_IDS) for cell in ENV_CELLS},
    NO_INTENT_CELL: tuple(NO_INTENT_IDS),
}


def _run(fn: Cell, cell: str, mid: str, path: Path, tmp: Path, environment: str | None) -> None:
    try:
        value = fn(path, tmp, environment)
    except Exception as e:  # noqa: BLE001 — today's failure is the golden
        value = _error(e)
    check(cell, mid, value, tmp=tmp)


@pytest.mark.parametrize("cell", sorted(CELLS))
@pytest.mark.parametrize(("mid", "path"), CASES, ids=IDS)
def test_legacy(
    cell: str, mid: str, path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    no_user_templates(monkeypatch)
    _run(CELLS[cell], cell, mid, path, tmp_path, None)


@pytest.mark.parametrize(("mid", "path"), NO_INTENT_CASES, ids=NO_INTENT_IDS)
def test_legacy_dashboard_no_intent(
    mid: str, path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    no_user_templates(monkeypatch)
    _run(dashboard_no_intent, NO_INTENT_CELL, mid, path, tmp_path, None)


@pytest.mark.parametrize("cell", sorted(ENV_CELLS))
@pytest.mark.parametrize("case", ENV_CASES, ids=ENV_IDS)
def test_legacy_env(
    cell: str, case: EnvCase, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    no_user_templates(monkeypatch)
    path = case.target(tmp_path)
    _run(ENV_CELLS[cell], cell, case.id, path, tmp_path, case.environment)
