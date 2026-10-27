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

Every cell runs with the working directory set to the temp dir, because the
legacy parser searches upward from the cwd for ``.nthlayer/templates``
(specs/custom_templates.py); a checkout-dependent cwd would make the golden
checkout-dependent.

``generate_loki_alerts_for_service_file`` takes no environment, so it has no
env-overlay cell.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from nthlayer_generate.dashboards.builder_sdk import build_dashboard
from nthlayer_generate.generators.alerts import generate_alerts_for_service
from nthlayer_generate.generators.sloth import generate_sloth_spec
from nthlayer_generate.loki.generator import generate_loki_alerts_for_service_file
from nthlayer_generate.metrics.recommender import recommend_metrics
from nthlayer_generate.recording_rules.builder import build_recording_rules
from nthlayer_generate.recording_rules.models import create_rule_groups
from nthlayer_generate.specs.parser import parse_service_file

from ._corpus import EX, LEGACY, SRM_V1, V2, _error, manifest_id
from ._golden import check

# Every manifest, loadable or not: the legacy parser's rejections are pinned.
CASES: tuple[tuple[str, Path], ...] = tuple((manifest_id(p), p) for p in SRM_V1 + LEGACY + V2)
IDS = [i for i, _ in CASES]


# --- environment-overlay cases ------------------------------------------------

ENVIRONMENTS = ("dev", "staging", "prod")
# Under the temp dir; kept apart so a cell listing what it wrote can skip it.
STAGING = "_staged"


class EnvCase:
    """A service file run with ``environment`` set.

    ``staged`` cases copy the service file into ``<tmp>/_staged/services/`` next to a
    copy of ``examples/environments/``: that directory has no service file
    beside it, so the overlay lookup (``{service_dir}/environments/...``,
    specs/environments.py:84) can only reach it from a staged layout. The
    layout is the one its README prescribes; the files are copied unchanged.
    """

    def __init__(self, base: Path, environment: str, *, staged: bool) -> None:
        self.base = base
        self.environment = environment
        self.staged = staged
        prefix = f"staged__{base.stem}" if staged else manifest_id(base)
        self.id = f"{prefix}__env-{environment}"

    def target(self, tmp: Path) -> Path:
        """The service file to pass to the command, staging it if needed."""
        if not self.staged:
            return self.base
        services = tmp / STAGING / "services"
        env_dir = services / "environments"
        env_dir.mkdir(parents=True, exist_ok=True)
        for overlay in sorted((EX / "environments").glob("*.yaml")):
            shutil.copy(overlay, env_dir / overlay.name)
        target = services / self.base.name
        shutil.copy(self.base, target)
        return target


ENV_CASES: tuple[EnvCase, ...] = (
    # examples/services/environments/{dev,staging,prod}.yaml, found in place.
    *(
        EnvCase(EX / "services" / "payment-api-with-envs.yaml", e, staged=False)
        for e in ENVIRONMENTS
    ),
    # examples/environments/: payment-api-{dev,prod}.yaml and search-api-prod.yaml
    # are service-specific; the rest fall through to the shared {env}.yaml.
    *(EnvCase(EX / "services" / "payment-api.yaml", e, staged=True) for e in ENVIRONMENTS),
    *(EnvCase(EX / "services" / "search-api.yaml", e, staged=True) for e in ENVIRONMENTS),
)
ENV_IDS = [c.id for c in ENV_CASES]


# --- normalisation ------------------------------------------------------------


def _read_yaml(path: Path | None) -> Any:
    """A written YAML file as structure; ``None`` when nothing was written."""
    if path is None or not path.is_file():
        return None
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def rules_as_sets(doc: Any) -> Any:
    """Sort each group's rules, and the groups, by full content.

    Both legacy dependency extractors return ``list(set(...))``
    (generators/alerts.py:74, loki/generator.py:341), so rule order follows
    PYTHONHASHSEED. Every rule is still pinned; only that arbitrary order is not.
    """
    if not isinstance(doc, dict) or not isinstance(doc.get("groups"), list):
        return doc
    for group in doc["groups"]:
        if isinstance(group, dict) and isinstance(group.get("rules"), list):
            group["rules"] = sorted(group["rules"], key=lambda r: json.dumps(r, sort_keys=True))
    doc["groups"] = sorted(doc["groups"], key=lambda g: json.dumps(g, sort_keys=True))
    return doc


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
GOLDEN_CELLS = {
    **{cell: tuple(IDS) for cell in CELLS},
    **{cell: tuple(ENV_IDS) for cell in ENV_CELLS},
}


def _run(fn: Cell, cell: str, mid: str, path: Path, tmp: Path, environment: str | None) -> None:
    try:
        value = fn(path, tmp, environment)
    except Exception as e:  # noqa: BLE001 — today's failure is the golden
        value = _error(e)
    check(cell, mid, value, tmp=tmp)


def test_corpus_and_env_cases_are_non_empty() -> None:
    # A zero-case parametrise would leave these cells green and empty.
    assert len(CASES) == len(SRM_V1) + len(LEGACY) + len(V2)
    assert len(ENV_CASES) == 9
    assert all(c.base.is_file() for c in ENV_CASES)


def test_every_env_case_finds_an_overlay(tmp_path: Path) -> None:
    # An env case with no overlay file would pin the base output under an
    # env name and test nothing about the merge.
    from nthlayer_generate.specs.environments import EnvironmentLoader

    for case in ENV_CASES:
        target = case.target(tmp_path / case.id)
        assert EnvironmentLoader.find_environment_file(target, case.environment), case.id


@pytest.mark.parametrize("cell", sorted(CELLS))
@pytest.mark.parametrize(("mid", "path"), CASES, ids=IDS)
def test_legacy(
    cell: str, mid: str, path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _run(CELLS[cell], cell, mid, path, tmp_path, None)


@pytest.mark.parametrize("cell", sorted(ENV_CELLS))
@pytest.mark.parametrize("case", ENV_CASES, ids=ENV_IDS)
def test_legacy_env(
    cell: str, case: EnvCase, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    path = case.target(tmp_path)
    _run(ENV_CELLS[cell], cell, case.id, path, tmp_path, case.environment)
