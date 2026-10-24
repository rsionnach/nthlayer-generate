"""ServiceContext from nthlayer-common's ReliabilityManifest (opensrm-wo62.1, D7).

Replaces generate's ``ReliabilityManifest.as_service_context()`` with the same
mapping, over common's model: the dashboard builder and the metric recommender
still consume the legacy ``ServiceContext``.
"""

from __future__ import annotations

from nthlayer_common.manifest import ReliabilityManifest

from nthlayer_generate.specs.models import PagerDutyConfig, ServiceContext


def service_context_from_manifest(manifest: ReliabilityManifest) -> ServiceContext:
    """Build the legacy ``ServiceContext`` for *manifest*.

    ``authored_type`` is carried explicitly. ``ServiceContext`` derives it from
    whatever ``type`` it is handed, so passing only the resolved value would
    recompute it and lose the authored spelling on every manifest -> context
    hop (opensrm-z3ab): ``${type}`` must keep substituting what the author
    wrote.

    PagerDuty comes from ``ownership.pagerduty``; only the escalation policy
    maps onto the legacy config, as before.
    """
    pagerduty = None
    if manifest.ownership and manifest.ownership.pagerduty:
        pagerduty = PagerDutyConfig(
            escalation_policy=manifest.ownership.pagerduty.escalation_policy_id,
        )

    return ServiceContext(
        name=manifest.name,
        team=manifest.team,
        tier=manifest.tier,
        type=manifest.type,
        authored_type=manifest.authored_type,
        support_model=manifest.support_model,
        language=manifest.language,
        framework=manifest.framework,
        environment=manifest.environment,
        pagerduty=pagerduty,
    )
