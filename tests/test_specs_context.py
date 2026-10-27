"""service_context_from_manifest over nthlayer-common's model (opensrm-wo62.1, D7).

It replaces generate's ``ReliabilityManifest.as_service_context()`` with the
same mapping. The manifests here are loaded with nthlayer-common's loader
directly: the helper takes common's model on both sides of the switch.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from nthlayer_common.manifest import load_manifest

from nthlayer_generate.specs.context import service_context_from_manifest

EX = Path(__file__).resolve().parents[1] / "examples"
API_BASIC = EX / "opensrm" / "api-basic.reliability.yaml"  # f252974
API_CRITICAL = EX / "opensrm" / "api-critical.reliability.yaml"  # f252974


def test_authored_type_survives_into_the_service_context(tmp_path: Path) -> None:
    """opensrm-z3ab through common: an alias-authored type keeps its authored
    spelling for ``${type}`` and resolves for comparisons.

    Fixture: examples/opensrm/api-basic.reliability.yaml @f252974 with
    ``spec.type`` rewritten ``api`` -> ``web`` (an input alias in
    nthlayer-common's SERVICE_TYPE_ALIASES, resolving to ``x-web``; README
    "Upgrading: type: web becomes x-web").
    """
    data = yaml.safe_load(API_BASIC.read_text(encoding="utf-8"))
    data["spec"]["type"] = "web"
    path = tmp_path / "user-api.reliability.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    context = service_context_from_manifest(load_manifest(path))

    assert context.authored_type == "web"
    assert context.type == "x-web"
    assert context.to_dict()["type"] == "web"  # what ${type} substitutes


def test_service_context_carries_identity_and_pagerduty_escalation() -> None:
    # examples/opensrm/api-critical.reliability.yaml: payment-api / payments /
    # critical / api; ownership.pagerduty.escalation_policy_id: P456DEF.
    context = service_context_from_manifest(load_manifest(API_CRITICAL))

    assert (context.name, context.team, context.tier, context.type) == (
        "payment-api",
        "payments",
        "critical",
        "api",
    )
    assert context.authored_type == "api"
    assert context.pagerduty is not None
    assert context.pagerduty.escalation_policy == "P456DEF"


def test_service_context_without_pagerduty_has_none() -> None:
    # examples/opensrm/api-basic.reliability.yaml declares no ownership.
    assert service_context_from_manifest(load_manifest(API_BASIC)).pagerduty is None
