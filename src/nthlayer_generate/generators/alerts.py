"""Alert generator from awesome-prometheus-alerts.

Automatically generates production-ready alert rules based on service dependencies.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, List

import yaml
from nthlayer_common.manifest import ReliabilityManifest

from nthlayer_generate.alerts import AlertRule, AlertTemplateLoader
from nthlayer_generate.generators.judgment_threshold_alerts import (
    build_judgment_threshold_alerts,
)
from nthlayer_generate.specs.alerting import manifest_alerting
from nthlayer_generate.specs.helpers import (
    extract_dependency_technologies,
)

if TYPE_CHECKING:
    from nthlayer_generate.specs.alerting import AlertingConfig


def filter_by_tier(alerts: List[AlertRule], tier: str) -> List[AlertRule]:
    """Filter alerts by tier: critical=all, standard=critical+warning, low=critical only."""
    tier_lower = tier.lower()

    if tier_lower == "critical":
        # Critical services get all alerts
        return alerts
    elif tier_lower == "standard":
        # Standard services get critical + warning
        return [a for a in alerts if a.severity in ["critical", "warning"]]
    elif tier_lower == "low":
        # Low tier services get only critical alerts
        return [a for a in alerts if a.severity == "critical"]
    else:
        # Unknown tier, return all alerts
        return alerts


def generate_alerts_from_manifest(
    manifest: ReliabilityManifest,
    output_file: Path | None = None,
    runbook_url: str = "",
    notification_channel: str = "",
    routing: str | None = None,
    grafana_url: str = "",
    quiet: bool = False,
) -> List[AlertRule]:
    """Generate alerts from ReliabilityManifest.

    Args:
        manifest: ReliabilityManifest instance
        output_file: Optional output path for generated alerts
        runbook_url: Base URL for runbooks
        notification_channel: Notification channel (pagerduty, slack, etc.)
        routing: PagerDuty routing label. If None, uses manifest.support_model.
        grafana_url: Base URL for Grafana dashboards
        quiet: If True, suppress progress output

    Returns:
        List of generated AlertRule objects
    """
    deps = extract_dependency_technologies(manifest)
    alert_routing = routing or manifest.support_model

    threshold_alerts = [
        alert.customize_for_service(
            service_name=manifest.name,
            team=manifest.team,
            tier=manifest.tier,
            notification_channel=notification_channel,
            runbook_url=runbook_url,
            routing=alert_routing,
            grafana_url=grafana_url,
        )
        for alert in build_judgment_threshold_alerts(manifest)
    ]
    if threshold_alerts and not deps:
        # Skip the template path: its "no dependencies found" warning would
        # contradict the threshold alerts written below.
        dependency_alerts: List[AlertRule] = []
    else:
        dependency_alerts = _load_and_customize_alerts(
            service_name=manifest.name,
            team=manifest.team,
            tier=manifest.tier,
            dependencies=deps,
            # Written below, once the threshold alerts are appended.
            output_file=output_file if not threshold_alerts else None,
            runbook_url=runbook_url,
            notification_channel=notification_channel,
            routing=alert_routing,
            grafana_url=grafana_url,
            quiet=quiet,
            alerting_config=manifest_alerting(manifest),
        )
    if not threshold_alerts:
        return dependency_alerts

    # Appended after tier filtering, which only dependency templates pass
    # through: a declared bound is an explicit request, whatever the tier
    # (wo62.2 design §3 Q2).
    all_alerts = dependency_alerts + threshold_alerts
    if not quiet:
        print(f"✅ Added {len(threshold_alerts)} judgment-threshold alerts")
    if output_file:
        write_prometheus_yaml(all_alerts, output_file, manifest.name)
        if not quiet:
            print(f"   Written to: {output_file}")
    return all_alerts


def _load_and_customize_alerts(
    service_name: str,
    team: str,
    tier: str,
    dependencies: List[str],
    output_file: Path | None = None,
    runbook_url: str = "",
    notification_channel: str = "",
    routing: str = "",
    grafana_url: str = "",
    quiet: bool = False,
    alerting_config: AlertingConfig | None = None,
) -> List[AlertRule]:
    """Core alert generation logic shared by both APIs.

    Args:
        service_name: Name of the service
        team: Team owning the service
        tier: Service tier (critical, standard, low)
        dependencies: List of technology dependency names
        output_file: Optional output path for generated alerts
        runbook_url: Base URL for runbooks
        notification_channel: Notification channel
        routing: PagerDuty routing label
        grafana_url: Base URL for Grafana dashboards
        quiet: If True, suppress progress output
        alerting_config: Optional AlertingConfig with for_duration overrides

    Returns:
        List of generated AlertRule objects
    """
    if not dependencies:
        if not quiet:
            print("⚠️  No dependencies found in service definition")
            print("   Add a Dependencies resource to enable alert generation")
        return []

    if not quiet:
        print(f"📊 Loading alerts for dependencies: {', '.join(sorted(dependencies))}")

    # Load alerts for each dependency
    loader = AlertTemplateLoader()
    all_alerts = []
    stats = {}

    for dep in sorted(dependencies):
        try:
            alerts = loader.load_technology(dep)
            if not alerts:
                if not quiet:
                    print(f"   ⚠️  {dep}: No alerts found")
                stats[dep] = 0
                continue

            # Filter by tier
            filtered = filter_by_tier(alerts, tier)

            # Customize for service
            customized = []
            for alert in filtered:
                # Determine for_duration override from alerting config
                for_override = None
                if alerting_config and alerting_config.for_duration:
                    for_override = alerting_config.for_duration.get_for_severity(
                        alert.severity
                    )

                customized.append(
                    alert.customize_for_service(
                        service_name=service_name,
                        team=team,
                        tier=tier,
                        notification_channel=notification_channel,
                        runbook_url=runbook_url,
                        routing=routing,
                        grafana_url=grafana_url,
                        for_duration_override=for_override,
                    )
                )

            # Validate and fix common issues (label mismatches, missing 'for' duration)
            validated = []
            fixes_count = 0
            for alert in customized:
                fixed_alert, result = alert.validate_and_fix()
                validated.append(fixed_alert)
                if result.fixes_applied:
                    fixes_count += 1

            all_alerts.extend(validated)
            stats[dep] = len(validated)
            if not quiet:
                fix_info = f" ({fixes_count} fixed)" if fixes_count else ""
                print(f"   ✓ {dep}: {len(validated)} alerts{fix_info}")

        except Exception as e:
            if not quiet:
                print(f"   ❌ {dep}: Error loading alerts - {e}")
            stats[dep] = 0

    if not all_alerts:
        if not quiet:
            print("\n⚠️  No alerts generated")
        return []

    if not quiet:
        print(f"\n✅ Generated {len(all_alerts)} total alerts")
        print(f"   Breakdown: {', '.join(f'{k}={v}' for k, v in stats.items() if v > 0)}")

    # Write output if specified
    if output_file:
        write_prometheus_yaml(all_alerts, output_file, service_name)
        if not quiet:
            print(f"   Written to: {output_file}")

    return all_alerts


def write_prometheus_yaml(alerts: List[AlertRule], output_file: Path, service_name: str):
    """Write alerts to Prometheus YAML format.

    Groups alerts by technology for better organization.

    Args:
        alerts: List of AlertRule objects
        output_file: Path to output file
        service_name: Name of service (for group naming)
    """
    # Group by technology
    groups_dict: dict[str, list[dict[str, Any]]] = {}
    for alert in alerts:
        tech = alert.technology or "general"
        if tech not in groups_dict:
            groups_dict[tech] = []
        groups_dict[tech].append(alert.to_prometheus())

    # Create output structure
    output = {
        "groups": [
            {"name": f"{service_name}-{tech}", "rules": rules}
            for tech, rules in sorted(groups_dict.items())
        ]
    }

    # Ensure output directory exists
    output_file.parent.mkdir(parents=True, exist_ok=True)

    # Write to file with attribution header
    with open(output_file, "w") as f:
        # Add attribution header as comment
        f.write("# Alert rules generated by NthLayer\n")
        f.write("# Templates sourced from awesome-prometheus-alerts\n")
        f.write("# https://github.com/samber/awesome-prometheus-alerts\n")
        f.write("# Licensed under CC BY 4.0: https://creativecommons.org/licenses/by/4.0/\n")
        f.write("#\n")
        f.write(f"# Customized for service: {service_name}\n")
        f.write("# Customizations: service labels, runbook URLs, tier filtering\n")
        f.write("#\n\n")

        yaml.dump(output, f, default_flow_style=False, sort_keys=False, width=120)
