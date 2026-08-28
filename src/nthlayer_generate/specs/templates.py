"""Service template models for NthLayer.

Templates provide pre-configured service definitions that can be
reused across services with optional overrides.
"""

from dataclasses import dataclass
from typing import Dict, List

from nthlayer_common.manifest.models import (
    resolve_service_type,
    valid_service_types_phrase,
)

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
    type: str  # a manifest service type; aliases resolve in __post_init__
    resources: List[Resource]

    def __post_init__(self):
        if self.tier not in TIER_NAMES:
            raise ValueError(f"Invalid tier: {self.tier}. Valid: {', '.join(TIER_NAMES)}")

        # Templates and manifests share ONE vocabulary (opensrm-8qpd).
        #
        # Resolve rather than validate, exactly as ReliabilityManifest does.
        # It matters because cli/init.py takes `template.type` as the
        # manifest type when the author chose none, so an alias declared on
        # disk — background-job.yaml and pipeline.yaml both do — would
        # otherwise land in a document schema.json rejects. Normalising at
        # construction makes that path safe by construction rather than by a
        # guard at the write site.
        resolved_type = resolve_service_type(self.type)
        if resolved_type is None:
            raise ValueError(
                f"Invalid type: {self.type!r}. Must be one of: {valid_service_types_phrase()}."
            )
        self.type = resolved_type


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
