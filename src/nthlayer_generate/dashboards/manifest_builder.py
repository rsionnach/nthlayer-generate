"""Dashboard builder for ReliabilityManifest.

Adapts ReliabilityManifest to the existing DashboardBuilderSDK by converting
manifest data to ServiceContext + Resources, then delegating.

Supports both OpenSRM and legacy formats through the unified manifest model.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import structlog
from nthlayer_common.manifest import ReliabilityManifest, SourceFormat

from nthlayer_generate.dashboards.builder_sdk import DashboardBuilderSDK
from nthlayer_generate.dashboards.templates import get_template_or_none
from nthlayer_generate.specs.context import service_context_from_manifest
from nthlayer_generate.specs.helpers import dependency_technology
from nthlayer_generate.specs.models import Resource, ServiceContext

logger = structlog.get_logger()

# Dependency types drawn from a technology template, and the key each is
# listed under in the Dependencies resource.
_TECHNOLOGY_SPEC_KEYS = {"database": "databases", "cache": "caches", "queue": "queues"}

# How a manifest declares a database's technology, by the format it was
# loaded from: where nthlayer-common's parsers read Dependency.database_type.
# The legacy loader takes it from the entry's ``type:`` (parser/loader.py),
# the srm/v1 parser from ``database_type`` (parser/v1.py). The v2 format has
# no type key on a dependency (opensrm spec/v2 AUTHORING.md 7.5), so it loads
# as an api dependency; a leftover ``type: database`` is still read, and has
# no key for its technology, hence no v2 hint. The legacy hint fits an entry
# under ``databases:``; one under the flat ``services:`` list has no such key.
_DECLARE_TECHNOLOGY_HINTS = {
    SourceFormat.LEGACY: "set type on the database entry",
    SourceFormat.SRM_V1: "set database_type on the dependency",
}


class ManifestDashboardBuilder:
    """Builds Grafana dashboards from ReliabilityManifest using Foundation SDK.

    Uses adapter pattern: converts manifest to ServiceContext + Resources,
    then delegates to DashboardBuilderSDK for actual panel generation.
    """

    def __init__(
        self,
        manifest: ReliabilityManifest,
        full_panels: bool = False,
        discovery_client: Any = None,
        enable_validation: bool = False,
        prometheus_url: Optional[str] = None,
        custom_metric_overrides: Optional[Dict[str, str]] = None,
        use_intent_templates: bool = True,
    ):
        """Initialize builder with manifest.

        Args:
            manifest: ReliabilityManifest instance
            full_panels: If True, use all template panels
            discovery_client: Optional for validation
            enable_validation: Whether to validate against discovered metrics
            prometheus_url: URL for metric discovery
            custom_metric_overrides: Dict of intent -> custom metric mappings
            use_intent_templates: Whether to use intent-based templates
        """
        self.manifest = manifest

        # Convert manifest to legacy types for delegation
        context = self._manifest_to_context()
        resources = self._manifest_to_resources(context)

        # Delegate to existing builder
        self._builder = DashboardBuilderSDK(
            service_context=context,
            resources=resources,
            full_panels=full_panels,
            discovery_client=discovery_client,
            enable_validation=enable_validation,
            prometheus_url=prometheus_url,
            custom_metric_overrides=custom_metric_overrides,
            use_intent_templates=use_intent_templates,
        )

    def build(self) -> Dict[str, Any]:
        """Build dashboard JSON.

        Returns:
            Dashboard JSON dictionary ready for Grafana API.
        """
        return self._builder.build()

    def _manifest_to_context(self):
        """Convert manifest to ServiceContext."""
        return service_context_from_manifest(self.manifest)

    def _manifest_to_resources(self, context: ServiceContext) -> List[Resource]:
        """Convert manifest SLOs and dependencies to Resources."""
        resources: List[Resource] = []

        # Convert SLOs
        for slo in self.manifest.slos:
            indicator: Dict[str, Any] = {}
            if slo.slo_type:
                indicator["type"] = slo.slo_type
            if slo.indicator_query:
                indicator["query"] = slo.indicator_query

            spec: Dict[str, Any] = {
                "objective": slo.target,
                "window": slo.window,
            }
            if indicator:
                spec["indicator"] = indicator

            resources.append(
                Resource(
                    kind="SLO",
                    name=slo.name,
                    spec=spec,
                    context=context,
                )
            )

        # Convert dependencies
        if self.manifest.dependencies:
            dep_spec: Dict[str, Any] = {
                "databases": [],
                "caches": [],
                "services": [],
                "queues": [],
            }
            for dep in self.manifest.dependencies:
                if dep.type in _TECHNOLOGY_SPEC_KEYS:
                    # One rule set with alerts and loki (wo62.4 D5,
                    # specs.helpers.dependency_technology): the declared
                    # technology; without one, a cache or queue is inferred
                    # from its name and then defaulted, a database is not.
                    technology = dependency_technology(dep)
                    if technology is None or get_template_or_none(technology) is None:
                        # Rob, 2026-10-28, and for databases 2026-10-29 (E6,
                        # opensrm-wo62.4.16): a technology with no dashboard
                        # template is left out with a warning, as alerts skip
                        # it, rather than failing the whole dashboard.
                        if technology is None:
                            # Nothing to look a template up by. Only a
                            # database gets here: a cache or queue is
                            # inferred from its name or defaulted.
                            fields: Dict[str, Any] = {
                                "dependency": dep.name,
                                "dependency_type": dep.type,
                                "technology": None,
                                "reason": "no_technology_declared",
                            }
                            hint = _DECLARE_TECHNOLOGY_HINTS.get(self.manifest.source_format)
                            if hint:
                                fields["hint"] = hint
                            logger.warning("dashboard_dependency_skipped", **fields)
                        else:
                            logger.warning(
                                "dashboard_dependency_skipped",
                                dependency=dep.name,
                                dependency_type=dep.type,
                                technology=technology,
                                reason="no_dashboard_template",
                            )
                        continue
                    dep_spec[_TECHNOLOGY_SPEC_KEYS[dep.type]].append(
                        {
                            "name": dep.name,
                            "type": technology,
                        }
                    )
                elif dep.type == "api":
                    dep_spec["services"].append(
                        {
                            "name": dep.name,
                            "type": dep.type,
                        }
                    )
                else:
                    logger.warning(
                        "Unknown dependency type '%s' for '%s', skipping",
                        dep.type,
                        dep.name,
                    )

            resources.append(
                Resource(
                    kind="Dependencies",
                    name="dependencies",
                    spec=dep_spec,
                    context=context,
                )
            )

        return resources


def build_dashboard_from_manifest(
    manifest: ReliabilityManifest,
    full_panels: bool = False,
    prometheus_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Build Grafana dashboard from ReliabilityManifest.

    Convenience wrapper: builds a ManifestDashboardBuilder for the manifest and
    returns its result.

    Args:
        manifest: ReliabilityManifest instance
        full_panels: Include all template panels
        prometheus_url: Optional Prometheus URL for metric discovery

    Returns:
        Dashboard JSON dictionary
    """
    builder = ManifestDashboardBuilder(
        manifest=manifest,
        full_panels=full_panels,
        prometheus_url=prometheus_url,
    )
    return builder.build()
