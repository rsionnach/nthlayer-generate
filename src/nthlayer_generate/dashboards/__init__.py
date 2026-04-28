"""Grafana dashboard generation.

Automatically generate Grafana dashboards from service specifications.

Enhanced with Hybrid Model:
- Intent-based templates for exporter-agnostic dashboards
- Metric discovery and resolution
- Fallback chains and guidance panels
"""

from nthlayer_generate.dashboards.intents import (
    ALL_INTENTS,
    MetricIntent,
    get_intent,
    get_intents_for_technology,
    list_technologies,
)
from nthlayer_generate.dashboards.manifest_builder import (
    ManifestDashboardBuilder,
    build_dashboard_from_manifest,
)
from nthlayer_generate.dashboards.panel_spec import (
    GuidancePanelSpec,
    PanelSpec,
    PanelType,
    QuerySpec,
)
from nthlayer_generate.dashboards.resolver import (
    MetricResolver,
    ResolutionResult,
    ResolutionStatus,
    create_resolver,
)

__all__ = [
    # Manifest API (ReliabilityManifest)
    "ManifestDashboardBuilder",
    "build_dashboard_from_manifest",
    # Intent Registry
    "MetricIntent",
    "ALL_INTENTS",
    "get_intent",
    "get_intents_for_technology",
    "list_technologies",
    # Resolver
    "MetricResolver",
    "ResolutionResult",
    "ResolutionStatus",
    "create_resolver",
    # Panel Specs
    "PanelSpec",
    "QuerySpec",
    "PanelType",
    "GuidancePanelSpec",
]
