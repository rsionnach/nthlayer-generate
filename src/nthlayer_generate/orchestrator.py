"""Service orchestrator for unified apply workflow.

Coordinates generation of all resources (SLOs, alerts, dashboards, etc.)
from a single service definition file.

The handlers, plan builder and execution engine live in
nthlayer_generate.orchestration; this module holds the ServiceOrchestrator
facade and detect_resource_types, which decides what plan/apply generate.
"""

import time
from pathlib import Path
from typing import List, Optional

from nthlayer_common.manifest import ReliabilityManifest, load_manifest

from nthlayer_generate.core.errors import ConfigurationError
from nthlayer_generate.orchestration.engine import ExecutionEngine
from nthlayer_generate.orchestration.handlers import register_default_handlers
from nthlayer_generate.orchestration.plan_builder import PlanBuilder
from nthlayer_generate.orchestration.registry import OrchestratorContext, ResourceRegistry
from nthlayer_generate.orchestration.results import ApplyResult, PlanResult

# Re-export for backward compatibility
__all__ = [
    "ApplyResult",
    "PlanResult",
    "ServiceOrchestrator",
    "detect_resource_types",
]


def detect_resource_types(manifest: ReliabilityManifest) -> List[str]:
    """Resource types plan/apply generate for ``manifest`` (opensrm-wo62.4.5).

    The former ResourceDetector's rules (removed in 4.0.0, opensrm-wo62.4.6),
    read from the manifest instead of the raw YAML, so template-provided
    resources and every format count.
    Rob's rulings, recorded on opensrm-wo62.4.5: any dependency (caches and
    queues included) triggers alerts and the dashboard; ownership.pagerduty
    triggers pagerduty in any format; judgment thresholds without SLOs add
    recording rules only, the one generator that emits anything for them.
    """
    resources: List[str] = []

    if manifest.slos:
        resources += ["slos", "recording-rules", "backstage"]
    elif manifest.judgment_thresholds:
        resources.append("recording-rules")

    if manifest.dependencies:
        resources.append("alerts")

    if manifest.observability is not None or manifest.dependencies:
        resources.append("dashboard")

    if manifest.ownership is not None and manifest.ownership.pagerduty is not None:
        resources.append("pagerduty")

    return resources


class ServiceOrchestrator:
    """Orchestrates generation of all resources for a service.

    Thin facade that delegates to orchestration components.
    """

    def __init__(
        self,
        service_yaml: Path,
        env: Optional[str] = None,
        push_to_grafana: bool = False,
        prometheus_url: Optional[str] = None,
    ):
        self.service_yaml = service_yaml
        self.env = env
        self.push_to_grafana = push_to_grafana
        self.prometheus_url = prometheus_url
        self.manifest: Optional[ReliabilityManifest] = None
        self.service_name: Optional[str] = None
        self.output_dir: Optional[Path] = None
        self._registry = ResourceRegistry()
        register_default_handlers(self._registry)

    def _load_service(self) -> None:
        """Load the service once through nthlayer-common, after the env overlay."""
        if self.manifest is not None:
            return  # Already loaded

        self.manifest = load_manifest(
            self.service_yaml, environment=self.env, suppress_deprecation_warning=True
        )
        self.service_name = self.manifest.name

        # Set default output directory
        if self.output_dir is None:
            self.output_dir = Path("generated") / self.service_name

    def _build_context(self) -> OrchestratorContext:
        """Build the shared context for handlers."""
        if self.service_name is None or self.manifest is None or self.output_dir is None:
            raise ConfigurationError("service must be loaded before building context")
        return OrchestratorContext(
            service_yaml=self.service_yaml,
            manifest=self.manifest,
            service_name=self.service_name,
            output_dir=self.output_dir,
            env=self.env,
            prometheus_url=self.prometheus_url,
            push_to_grafana=self.push_to_grafana,
        )

    def plan(self) -> PlanResult:
        """Preview what resources would be generated (dry-run)."""
        try:
            self._load_service()
        except Exception as e:
            return PlanResult(
                service_name=self.service_yaml.stem,
                service_yaml=self.service_yaml,
                errors=[f"Failed to load service: {e}"],
            )

        if self.service_name is None or self.manifest is None:
            raise ConfigurationError("service must be loaded before planning")

        # Ensure output_dir is set for context building
        if self.output_dir is None:
            self.output_dir = Path("generated") / self.service_name

        resource_types = detect_resource_types(self.manifest)
        ctx = self._build_context()
        builder = PlanBuilder(self._registry)
        return builder.build(ctx, resource_types)

    def apply(
        self,
        skip: Optional[List[str]] = None,
        only: Optional[List[str]] = None,
        force: bool = False,
        verbose: bool = False,
    ) -> ApplyResult:
        """Generate all resources for the service."""
        start = time.time()

        try:
            self._load_service()
        except Exception as e:
            return ApplyResult(
                service_name=self.service_yaml.stem, errors=[f"Failed to load service: {e}"]
            )

        assert self.service_name is not None
        assert self.manifest is not None
        assert self.output_dir is not None

        # Create output directory and verify writability
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            test_file = self.output_dir / ".nthlayer_write_test"
            test_file.touch()
            test_file.unlink()
        except OSError as e:
            return ApplyResult(
                service_name=self.service_name,
                output_dir=self.output_dir,
                errors=[f"Output directory not writable: {e}"],
            )

        resource_types = self._get_filtered_resources(skip, only)
        ctx = self._build_context()
        engine = ExecutionEngine(self._registry)
        collector = engine.execute(ctx, resource_types, verbose=verbose)
        return collector.finalize(time.time() - start)

    def _get_filtered_resources(
        self, skip: Optional[List[str]], only: Optional[List[str]]
    ) -> List[str]:
        """Detect and filter resource types to generate."""
        assert self.manifest is not None
        resource_types = detect_resource_types(self.manifest)

        if only:
            resource_types = [r for r in resource_types if r in only]
        if skip:
            resource_types = [r for r in resource_types if r not in skip]

        return resource_types
