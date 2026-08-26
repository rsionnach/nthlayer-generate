"""
Data models for service specifications.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from nthlayer_common.manifest.models import resolve_service_type


@dataclass
class PagerDutyConfig:
    """PagerDuty-specific configuration for a service."""

    escalation_policy: str | None = None  # Use existing policy by name
    schedule: str | None = None  # Use existing schedule by name
    sre_escalation_policy: str | None = None  # SRE policy for routing overrides
    urgency: str | None = None  # Override: high | low | use_support_hours
    timezone: str = "America/New_York"


@dataclass
class ServiceContext:
    """
    Service-level context that applies to all resources.

    This is declared once at the top of the service YAML and
    all resources inherit this context implicitly.
    """

    name: str
    team: str
    tier: str
    type: str
    # Declared, not set in __post_init__: as a bare attribute it was
    # silently recomputed by dataclasses.replace(), so replacing an
    # unrelated field reverted the authored spelling to the resolved one.
    # None means "derive from `type`" — the ordinary construction path.
    authored_type: str | None = None
    support_model: str = "self"  # self | shared | sre | business_hours
    language: str | None = None
    framework: str | None = None
    template: str | None = None
    environment: str | None = None  # runtime environment (dev, staging, prod)
    pagerduty: PagerDutyConfig | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """
        Convert to dict for template variable substitution.

        Returns dict with keys for use in ${variable} templates.
        """
        result = {
            "service": self.name,
            "team": self.team,
            "tier": self.tier,
            "type": self.authored_type,
            "support_model": self.support_model,
            "language": self.language or "",
            "framework": self.framework or "",
        }

        # Add environment if specified
        if self.environment:
            result["env"] = self.environment

        return result

    def __post_init__(self) -> None:
        """Validate required fields."""
        # Two spellings, deliberately (opensrm-z3ab):
        #
        #   self.type      resolved — what internal branches compare against,
        #                  so code sees one spelling (hard rule 1).
        #   authored_type  exactly what the author wrote — what `${type}`
        #                  substitutes into generated PromQL.
        #
        # The split exists because `${type}` lands in user-authored label
        # matchers run against the Prometheus they already have. Rewriting
        # `web` to `x-web` there produces a matcher selecting zero series:
        # the SLO reads no-data and its burn-rate alerts never fire, while
        # the generated rules stay perfectly valid. That is a data-plane
        # change, and not ours to make.
        #
        # Resolve-or-keep, never raise: type validity is REPORTED by
        # specs/validator.py as a collected error, and raising here would
        # turn that into a crash.
        if self.authored_type is None:
            self.authored_type = self.type
        if self.type:
            self.type = resolve_service_type(self.type) or self.type

        if not self.name:
            raise ValueError("Service name is required")
        if not self.team:
            raise ValueError("Service team is required")
        if not self.tier:
            raise ValueError("Service tier is required")
        # `is None` / empty-string only: a falsy-but-present value like
        # `type: 0` or `type: []` is a WRONG type, not a missing one, and
        # reporting "is required" for it sends the author looking for an
        # absent line that is right there.
        if self.type is None or self.type == "":
            raise ValueError("Service type is required")


@dataclass
class Resource:
    """
    A resource within a service definition.

    Resources inherit the service context implicitly, so they don't
    need to repeat the service name.
    """

    kind: str
    spec: dict[str, Any]
    name: str | None = None
    context: ServiceContext | None = None

    @property
    def full_name(self) -> str:
        """
        Generate full resource name: service-name-resource-name.

        Examples:
            service=payment-api, name=availability → payment-api-availability
            service=payment-api, name=None → payment-api
        """
        if not self.context:
            raise ValueError("Resource has no context")

        if self.name:
            return f"{self.context.name}-{self.name}"
        return self.context.name

    @property
    def service_name(self) -> str:
        """Get service name from context."""
        if not self.context:
            raise ValueError("Resource has no context")
        return self.context.name

    def __post_init__(self) -> None:
        """Validate required fields."""
        if not self.kind:
            raise ValueError("Resource kind is required")
        if not self.name:
            raise ValueError("Resource name is required")
        if self.spec is None:
            raise ValueError("Resource spec is required")


# Valid resource kinds
VALID_RESOURCE_KINDS = {
    "SLO",
    "PagerDuty",
    "Dependencies",
    "Observability",
    "DeploymentGate",
    "PolicyRules",
}

# Valid service tiers (OpenSRM adds 'high' between critical and standard)
VALID_TIERS = {
    "critical",
    "high",  # NEW: OpenSRM tier between critical and standard
    "standard",
    "low",
}

# Service types are NOT defined here. nthlayer-common owns the rule: import
# VALID_SERVICE_TYPES / resolve_service_type from
# nthlayer_common.manifest.models, or from specs.manifest, which re-exports
# them (opensrm-z3ab).

# Valid support models
VALID_SUPPORT_MODELS = {
    "self",  # Team handles everything 24/7
    "shared",  # Team (business hours) + SRE (off-hours)
    "sre",  # SRE handles everything
    "business_hours",  # No off-hours support
}
