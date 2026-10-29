"""Concrete resource handlers for orchestration."""

import json
import os
from pathlib import Path
from typing import Any, Dict, List

import structlog
from nthlayer_common.manifest import PagerDutyConfig

from nthlayer_generate.alertmanager import generate_alertmanager_config
from nthlayer_generate.core.errors import ProviderError
from nthlayer_generate.orchestration.registry import OrchestratorContext, ResourceRegistry
from nthlayer_generate.pagerduty import EventOrchestrationManager, PagerDutyResourceManager

logger = structlog.get_logger()

# PagerDutyHandler's timezone when ownership.pagerduty sets none, in any
# format; common carries only what was authored (opensrm-wo62.4.13).
DEFAULT_PAGERDUTY_TIMEZONE = "America/New_York"


class SloHandler:
    """Handles SLO generation via Sloth."""

    @property
    def name(self) -> str:
        return "slos"

    @property
    def display_name(self) -> str:
        return "SLOs"

    def plan(self, ctx: OrchestratorContext) -> List[Dict[str, Any]]:
        return [
            {"name": slo.name, "objective": slo.target, "window": slo.window}
            for slo in ctx.manifest.slos
        ]

    def generate(self, ctx: OrchestratorContext) -> int:
        from nthlayer_generate.generators.sloth import generate_sloth_from_manifest

        if not ctx.manifest.slos:
            return 0

        result = generate_sloth_from_manifest(ctx.manifest, ctx.output_dir / "sloth")

        if not result.success:
            print(f"   ⚠️  SLO generation warning: {result.error}")
            return 0

        return result.slo_count


class AlertHandler:
    """Handles alert rule generation."""

    @property
    def name(self) -> str:
        return "alerts"

    @property
    def display_name(self) -> str:
        return "alerts"

    def plan(self, ctx: OrchestratorContext) -> List[Dict[str, Any]]:
        from nthlayer_generate.generators.alerts import generate_alerts_from_manifest

        try:
            alerts = generate_alerts_from_manifest(ctx.manifest, output_file=None, quiet=True)
            severity_counts: Dict[str, int] = {}
            for alert in alerts:
                severity = getattr(alert, "severity", "unknown")
                severity_counts[severity] = severity_counts.get(severity, 0) + 1

            return [
                {"severity": sev, "count": count} for sev, count in sorted(severity_counts.items())
            ]
        except Exception as e:
            logger.warning("alert_plan_failed", err=str(e), exc_info=True)
            return []

    def generate(self, ctx: OrchestratorContext) -> int:
        from nthlayer_generate.generators.alerts import generate_alerts_from_manifest

        output_file = ctx.output_dir / "alerts.yaml"
        alerts = generate_alerts_from_manifest(ctx.manifest, output_file=output_file, quiet=True)
        return len(alerts)


class DashboardHandler:
    """Handles dashboard generation and optional Grafana push."""

    @property
    def name(self) -> str:
        return "dashboard"

    @property
    def display_name(self) -> str:
        return "dashboard"

    def plan(self, ctx: OrchestratorContext) -> List[Dict[str, Any]]:
        return [
            {
                "name": f"{ctx.service_name}-dashboard",
                "panels": "12+",
                "description": "Auto-generated monitoring dashboard",
            }
        ]

    def generate(self, ctx: OrchestratorContext) -> int:
        from nthlayer_generate.dashboards.manifest_builder import build_dashboard_from_manifest

        # As generate-dashboard writes it (cli/dashboard.py): overview panels,
        # JSON with sorted keys.
        dashboard = build_dashboard_from_manifest(
            ctx.manifest, full_panels=False, prometheus_url=ctx.prometheus_url
        )
        output_file = ctx.output_dir / "dashboard.json"
        output_file.write_text(json.dumps(dashboard, indent=2, sort_keys=True))

        if ctx.push_to_grafana:
            _push_dashboard_to_grafana(output_file, ctx.service_name)

        return 1


class RecordingRulesHandler:
    """Handles recording rule generation from SLOs."""

    @property
    def name(self) -> str:
        return "recording-rules"

    @property
    def display_name(self) -> str:
        return "recording rules"

    def plan(self, ctx: OrchestratorContext) -> List[Dict[str, Any]]:
        from nthlayer_generate.recording_rules.manifest_builder import (
            build_recording_rules_from_manifest,
        )

        groups = build_recording_rules_from_manifest(ctx.manifest)

        if not groups:
            return []

        return [
            {"type": group.name, "count": len(group.rules), "interval": group.interval}
            for group in groups
        ]

    def generate(self, ctx: OrchestratorContext) -> int:
        from nthlayer_generate.recording_rules.manifest_builder import (
            build_recording_rules_from_manifest,
        )
        from nthlayer_generate.recording_rules.models import create_rule_groups

        output_file = ctx.output_dir / "recording-rules.yaml"
        groups = build_recording_rules_from_manifest(ctx.manifest)

        if not groups:
            with open(output_file, "w") as f:
                f.write("# No recording rules generated (no SLOs defined)\n")
            return 0

        yaml_output = create_rule_groups(groups)
        with open(output_file, "w") as f:
            f.write("# Recording rules generated by NthLayer\n")
            f.write("# Pre-computed SLO metrics for dashboard and alert performance\n")
            f.write("#\n\n")
            f.write(yaml_output)

        return sum(len(group.rules) for group in groups)


class PagerDutyHandler:
    """Handles PagerDuty service creation with tier-based defaults."""

    @property
    def name(self) -> str:
        return "pagerduty"

    @property
    def display_name(self) -> str:
        return "PagerDuty"

    def plan(self, ctx: OrchestratorContext) -> List[Dict[str, Any]]:
        manifest = ctx.manifest
        if manifest.ownership is None or manifest.ownership.pagerduty is None:
            return []

        team = manifest.team
        tier = manifest.tier
        support_model = manifest.support_model

        from nthlayer_generate.pagerduty.defaults import get_schedules_for_tier

        schedules = get_schedules_for_tier(tier)

        return [
            {"type": "team", "name": team},
            {"type": "schedules", "names": [f"{team}-{s}" for s in schedules]},
            {"type": "escalation_policy", "name": f"{team}-escalation"},
            {
                "type": "service",
                "name": ctx.service_name,
                "tier": tier,
                "support_model": support_model,
            },
        ]

    def generate(self, ctx: OrchestratorContext) -> int:
        api_key = os.environ.get("PAGERDUTY_API_KEY")
        default_from = os.environ.get("PAGERDUTY_FROM_EMAIL", "nthlayer@example.com")

        manifest = ctx.manifest
        team = manifest.team
        tier = manifest.tier
        support_model = manifest.support_model

        # common stores the keys as authored (opensrm-wo62.4.13, P4); the
        # timezone default is generate's.
        pagerduty = manifest.ownership.pagerduty if manifest.ownership else None
        if pagerduty is None:
            pagerduty = PagerDutyConfig()
        timezone = pagerduty.timezone or DEFAULT_PAGERDUTY_TIMEZONE
        sre_ep_id = pagerduty.sre_escalation_policy_id
        integration_key = pagerduty.integration_key
        sre_integration_key = pagerduty.sre_integration_key

        if not api_key:
            output_file = ctx.output_dir / "pagerduty-config.json"
            config = {
                "service_name": ctx.service_name,
                "team": team,
                "tier": tier,
                "support_model": support_model,
                "timezone": timezone,
                "resources_to_create": {
                    "team": team,
                    "schedules": [
                        f"{team}-primary",
                        f"{team}-secondary",
                        f"{team}-manager",
                    ],
                    "escalation_policy": f"{team}-escalation",
                    "service": ctx.service_name,
                },
                "note": "Set PAGERDUTY_API_KEY to create resources in PagerDuty",
            }
            with open(output_file, "w") as f:
                json.dump(config, f, indent=2, sort_keys=True)
            return 1

        with PagerDutyResourceManager(
            api_key=api_key,
            default_from=default_from,
        ) as manager:
            result = manager.setup_service(
                service_name=ctx.service_name,
                team=team,
                tier=tier,
                support_model=support_model,
                tz=timezone,
                sre_escalation_policy_id=sre_ep_id,
            )

        if not result.success:
            raise ProviderError(f"PagerDuty setup failed: {', '.join(result.errors)}")

        output_file = ctx.output_dir / "pagerduty-result.json"
        result_data = {
            "success": result.success,
            "team_id": result.team_id,
            "schedule_ids": result.schedule_ids,
            "escalation_policy_id": result.escalation_policy_id,
            "service_id": result.service_id,
            "service_url": result.service_url,
            "created_resources": result.created_resources,
            "warnings": result.warnings,
        }
        with open(output_file, "w") as f:
            json.dump(result_data, f, indent=2, sort_keys=True)

        if support_model in ("shared", "sre") and sre_ep_id and result.service_id:
            _setup_event_orchestration(
                api_key=api_key,
                default_from=default_from,
                service_id=result.service_id,
                sre_escalation_policy_id=sre_ep_id,
            )

        if integration_key:
            am_config = generate_alertmanager_config(
                service_name=ctx.service_name,
                team=team,
                pagerduty_integration_key=integration_key,
                support_model=support_model,
                tier=tier,
                sre_integration_key=sre_integration_key,
            )
            am_output = ctx.output_dir / "alertmanager.yaml"
            am_config.write(am_output)
            print(f"✅ Alertmanager config: {am_output}")

        return len(result.created_resources) or 1


class BackstageHandler:
    """Handles Backstage entity generation."""

    @property
    def name(self) -> str:
        return "backstage"

    @property
    def display_name(self) -> str:
        return "Backstage entity"

    def plan(self, ctx: OrchestratorContext) -> List[Dict[str, Any]]:
        return [
            {
                "type": "backstage_entity",
                "service": ctx.service_name,
                "team": ctx.manifest.team,
                "tier": ctx.manifest.tier,
                "slo_count": len(ctx.manifest.slos),
                "output": "backstage.json",
            }
        ]

    def generate(self, ctx: OrchestratorContext) -> int:
        from nthlayer_generate.generators.backstage import generate_backstage_from_manifest

        result = generate_backstage_from_manifest(ctx.manifest, ctx.output_dir)

        if not result.success:
            print(f"   ⚠️  Backstage generation warning: {result.error}")
            return 0

        return 1


def _push_dashboard_to_grafana(dashboard_file: Path, service_name: str) -> None:
    """Push generated dashboard to Grafana via API."""
    import asyncio
    import json
    import os

    from nthlayer_generate.providers.grafana import GrafanaProvider

    grafana_url = os.getenv("NTHLAYER_GRAFANA_URL")
    grafana_api_key = os.getenv("NTHLAYER_GRAFANA_API_KEY")
    grafana_org_id = int(os.getenv("NTHLAYER_GRAFANA_ORG_ID", "1"))

    if not grafana_url or not grafana_api_key:
        print("⚠️  Grafana not configured. Skipping push to Grafana.")
        print("   Set NTHLAYER_GRAFANA_URL and NTHLAYER_GRAFANA_API_KEY to enable auto-push.")
        return

    with open(dashboard_file) as f:
        dashboard_data = json.load(f)

    dashboard_json = dashboard_data.get("dashboard", {})

    if not dashboard_json:
        print("⚠️  Dashboard JSON is empty, skipping push")
        return

    provider = GrafanaProvider(url=grafana_url, token=grafana_api_key, org_id=grafana_org_id)
    dashboard_uid = dashboard_json.get("uid", service_name)

    print("📤 Pushing dashboard to Grafana...")

    async def do_push():
        """Push dashboard via async GrafanaProvider."""
        dashboard_resource = provider.dashboard(dashboard_uid)
        await dashboard_resource.apply(
            {
                "dashboard": dashboard_json,
                "folderUid": None,
                "title": dashboard_json.get("title", f"{service_name} Dashboard"),
            }
        )

    try:
        asyncio.run(do_push())
        print(f"✅ Dashboard pushed to Grafana: {grafana_url}/d/{dashboard_uid}")
    except Exception as e:
        logger.warning("grafana_push_failed", err=str(e), exc_info=True)
        print(f"⚠️  Failed to push dashboard to Grafana: {e}")
        print("   Dashboard file saved locally, you can import manually.")


def _setup_event_orchestration(
    api_key: str,
    default_from: str,
    service_id: str,
    sre_escalation_policy_id: str,
) -> None:
    """Set up Event Orchestration for alert routing overrides."""
    with EventOrchestrationManager(
        api_key=api_key,
        default_from=default_from,
    ) as orchestration:
        sre_rule = orchestration.create_sre_routing_rule(sre_escalation_policy_id)
        result = orchestration.setup_service_orchestration(
            service_id=service_id,
            routing_rules=[sre_rule],
        )
        if not result.success:
            print(f"⚠️  Event Orchestration setup failed: {result.error}")
        elif result.rules_created > 0:
            print(f"✅ Event Orchestration: {result.rules_created} routing rule(s) created")


def _policy_resources(ctx: OrchestratorContext) -> List[Dict[str, Any]]:
    """The manifest's ``kind: PolicyRules`` resources, from its raw data.

    detect_resource_types never plans "policy", so plan/apply do not reach
    this handler (pre-existing; opensrm-wo62.4.15 wires or deletes it).
    """
    resources = ctx.manifest.raw_data.get("resources") or []
    return [r for r in resources if isinstance(r, dict) and r.get("kind") == "PolicyRules"]


class PolicyHandler:
    """Evaluate policy rules against service spec."""

    @property
    def name(self) -> str:
        return "policy"

    @property
    def display_name(self) -> str:
        return "Policy Rules"

    def plan(self, ctx: OrchestratorContext) -> List[Dict[str, Any]]:
        policy_resources = _policy_resources(ctx)
        if not policy_resources:
            return []
        return [{"type": "policy", "action": "evaluate", "count": len(policy_resources)}]

    def generate(self, ctx: OrchestratorContext) -> int:
        from nthlayer_generate.policies.engine import PolicyEngine

        policy_resources = _policy_resources(ctx)
        if not policy_resources:
            return 0

        manifest = ctx.manifest
        engine = PolicyEngine()

        for resource in policy_resources:
            engine.add_rules(PolicyEngine.from_dict(resource.get("spec", {}))._rules)

        report = engine.evaluate(manifest)

        for v in report.violations:
            icon = "\u274c" if v.severity.value == "error" else "\u26a0\ufe0f"
            print(f"  {icon}  [{v.rule_name}] {v.message}")

        if report.passed:
            print(f"\u2705 Policy evaluation: {report.rules_evaluated} rules passed")

        return report.rules_evaluated


def register_default_handlers(registry: ResourceRegistry) -> None:
    """Register all built-in resource handlers."""
    registry.register(SloHandler())
    registry.register(AlertHandler())
    registry.register(DashboardHandler())
    registry.register(RecordingRulesHandler())
    registry.register(PagerDutyHandler())
    registry.register(BackstageHandler())
    registry.register(PolicyHandler())
