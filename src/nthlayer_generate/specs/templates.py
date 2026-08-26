"""Service template models for NthLayer.

Templates provide pre-configured service definitions that can be
reused across services with optional overrides.
"""

from dataclasses import dataclass
from typing import Dict, List

from nthlayer_generate.core.tiers import TIER_NAMES

from .models import Resource


@dataclass
class ServiceTemplate:
    """Pre-configured service template.

    Templates contain default resources (SLOs, PagerDuty, etc.) that can be
    applied to services and optionally overridden.
    """

    name: str  # e.g., "critical-api"
    description: str
    tier: str  # critical | standard | low
    type: str  # api | background-job | pipeline | web | database
    resources: List[Resource]

    def __post_init__(self):
        if self.tier not in TIER_NAMES:
            raise ValueError(f"Invalid tier: {self.tier}. Valid: {', '.join(TIER_NAMES)}")

        # TEMPLATE types, a separate vocabulary from manifest service types
        # — note `background-job` and `pipeline`, which are manifest ALIASES
        # rather than manifest types. opensrm-z3ab briefly changed `web` here
        # to `x-web` and broke both ends of the lookup: templates declaring
        # `web` stopped loading, and ones declaring `x-web` were never
        # matched, because cli/init.py's SERVICE_TYPE_TO_TEMPLATE_TYPE still
        # maps to `web`. Whether templates and manifests should share a
        # vocabulary at all is opensrm-8qpd; until then this table stays
        # internally consistent.
        valid_types = ["api", "background-job", "pipeline", "web", "database"]
        if self.type not in valid_types:
            raise ValueError(f"Invalid type: {self.type}")


@dataclass
class TemplateRegistry:
    """Registry of available service templates."""

    templates: Dict[str, ServiceTemplate]

    def get(self, name: str) -> ServiceTemplate | None:
        """Get template by name.

        Args:
            name: Template name (e.g., "critical-api")

        Returns:
            ServiceTemplate if found, None otherwise
        """
        return self.templates.get(name)

    def list(self) -> List[ServiceTemplate]:
        """List all available templates.

        Returns:
            List of ServiceTemplate objects sorted by name
        """
        return sorted(self.templates.values(), key=lambda t: t.name)

    def exists(self, name: str) -> bool:
        """Check if template exists.

        Args:
            name: Template name

        Returns:
            True if template exists
        """
        return name in self.templates
