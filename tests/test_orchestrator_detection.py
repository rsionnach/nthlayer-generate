"""plan/apply detection from the ReliabilityManifest (opensrm-wo62.4.5).

Every case is a committed manifest. Each expected list follows from what the
file declares and from Rob's rulings (recorded on opensrm-wo62.4.5), not
from the detector's code:

- slos, recording-rules, backstage: the manifest has SLOs (the legacy
  "SLO resources" rule, now read after template expansion);
- E5: judgment thresholds alone add recording-rules only;
- E1: alerts when the manifest has any dependency (caches and queues count);
- dashboard: an Observability presence or any dependency;
- E2: pagerduty when ``ownership.pagerduty`` is set, in any format;
- E4: detection reads the manifest after the env overlay.

The order is the former legacy ResourceDetector's (removed in 4.0.0):
slos, recording-rules, backstage, alerts, dashboard, pagerduty.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest
from nthlayer_common.manifest import load_manifest

from nthlayer_generate.orchestrator import ServiceOrchestrator, detect_resource_types

REPO = Path(__file__).resolve().parents[1]
EXAMPLES = REPO / "examples"
LEGACY_FIXTURES = REPO / "tests" / "golden" / "fixtures" / "legacy"
V2_EXAMPLES = REPO.parent / "opensrm" / "spec" / "v2" / "examples"

ALL_SIX = ["slos", "recording-rules", "backstage", "alerts", "dashboard", "pagerduty"]
SLO_TRIO = ["slos", "recording-rules", "backstage"]

CASES = [
    # Legacy: SLO, Dependencies (database), Observability and PagerDuty resources.
    (EXAMPLES / "services" / "checkout-service.yaml", ALL_SIX),
    # Legacy, `template: critical-api` and no resources of its own. The
    # template supplies SLOs and a PagerDuty resource; the raw-YAML detector
    # saw none of them.
    (EXAMPLES / "services" / "api-minimal.yaml", SLO_TRIO + ["pagerduty"]),
    # Legacy, queue-only Dependencies (E1: the legacy rule counted only
    # databases, services and external_apis).
    (
        EXAMPLES / "services" / "notification-service.yaml",
        SLO_TRIO + ["alerts", "dashboard", "pagerduty"],
    ),
    # Legacy, an Observability resource and no Dependencies: the dashboard
    # rests on Observability presence alone.
    (LEGACY_FIXTURES / "notification-observability-only.yaml", SLO_TRIO + ["dashboard"]),
    # srm/v1, ownership.pagerduty, dependencies and an observability block.
    (EXAMPLES / "opensrm" / "api-critical.reliability.yaml", ALL_SIX),
    # srm/v1, SLOs only: no dependencies, observability or pagerduty.
    (EXAMPLES / "opensrm" / "api-basic.reliability.yaml", SLO_TRIO),
    # srm/v1, api and queue dependencies, no observability or pagerduty.
    (EXAMPLES / "opensrm" / "worker.reliability.yaml", SLO_TRIO + ["alerts", "dashboard"]),
]

V2_CASES = [
    # v2, SLOs and an api dependency.
    ("migration/api-full-v2.yaml", SLO_TRIO + ["alerts", "dashboard"]),
    # v2, judgment thresholds and no SLOs (E5).
    ("judgment-thresholds/all-five-types.yaml", ["recording-rules"]),
]


def _load(path: Path, environment: str | None = None):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return load_manifest(path, environment=environment, suppress_deprecation_warning=True)


@pytest.mark.parametrize("path,expected", CASES, ids=lambda c: getattr(c, "stem", None))
def test_detect_resource_types(path: Path, expected: list[str]):
    assert path.is_file(), f"corpus file missing: {path}"
    assert detect_resource_types(_load(path)) == expected


@pytest.mark.parametrize("rel,expected", V2_CASES, ids=[r for r, _ in V2_CASES])
def test_detect_resource_types_v2(rel: str, expected: list[str]):
    # The spec examples live in the sibling opensrm checkout. A missing file
    # fails rather than skips (CLAUDE.md: a skipped seam is a silent pass).
    path = V2_EXAMPLES / rel
    assert path.is_file(), f"opensrm spec example missing: {path}"
    assert detect_resource_types(_load(path)) == expected


def test_orchestrator_plans_from_overlaid_manifest(tmp_path: Path):
    # E4: the overlay is applied before detection. The base declares no
    # Dependencies; the overlay adds one, so alerts appear only under --env.
    base = tmp_path / "svc.yaml"
    base.write_text(
        "service:\n  name: svc\n  team: t\n  tier: critical\n  type: api\n"
        "resources:\n  - kind: SLO\n    name: availability\n"
        "    spec:\n      objective: 99.9\n"
    )
    env_dir = tmp_path / "environments"
    env_dir.mkdir()
    (env_dir / "prod.yaml").write_text(
        "environment: prod\nresources:\n  - kind: Dependencies\n    name: upstream\n"
        "    spec:\n      databases:\n        - name: db\n          type: postgres\n"
    )

    base_plan = ServiceOrchestrator(base).plan()
    prod_plan = ServiceOrchestrator(base, env="prod").plan()

    assert base_plan.errors == []
    assert prod_plan.errors == []
    assert list(base_plan.resources) == SLO_TRIO
    assert list(prod_plan.resources) == SLO_TRIO + ["alerts", "dashboard"]


def test_orchestrator_service_name_comes_from_manifest(tmp_path: Path):
    path = tmp_path / "file-stem.yaml"
    path.write_text("service:\n  name: real-name\n  team: t\n  tier: low\n  type: api\n")
    result = ServiceOrchestrator(path).plan()
    assert result.service_name == "real-name"
    assert result.resources == {}


def test_orchestrator_reports_load_failure(tmp_path: Path):
    # The manifest model requires service.team; the raw-YAML loader did not.
    path = tmp_path / "bad.yaml"
    path.write_text("service:\n  name: bad\n  tier: low\n  type: api\n")
    result = ServiceOrchestrator(path).plan()
    assert result.service_name == "bad"
    assert len(result.errors) == 1
    assert result.errors[0].startswith("Failed to load service: ")
