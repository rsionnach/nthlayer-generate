"""
PagerDuty setup command.
"""

from __future__ import annotations

import os

import structlog
from nthlayer_common.manifest import SourceFormat, load_manifest

from nthlayer_generate.cli.ux import console, error, header, info, success, warning

logger = structlog.get_logger()
from nthlayer_generate.integrations.pagerduty import PagerDutyClient


def setup_pagerduty_command(
    service_file: str,
    api_key: str | None = None,
    environment: str | None = None,
    dry_run: bool = False,
) -> int:
    """
    Setup PagerDuty integration for a service.

    Args:
        service_file: Path to service YAML file
        api_key: PagerDuty API key (or use PAGERDUTY_API_KEY env var)
        environment: Optional environment name (dev, staging, prod)
        dry_run: Preview what would be created without making changes

    Returns:
        Exit code (0 = success, 1 = error)
    """
    header("Setup PagerDuty Integration")
    console.print()

    if environment:
        console.print(f"[info]Environment:[/info] {environment}")
        console.print()

    # Get API key
    api_key = api_key or os.environ.get("PAGERDUTY_API_KEY")
    if not api_key:
        error("PagerDuty API key required")
        console.print()
        console.print("[muted]Provide via:[/muted]")
        console.print("  [muted]•[/muted] --api-key flag")
        console.print("  [muted]•[/muted] PAGERDUTY_API_KEY environment variable")
        console.print()
        console.print(
            "[muted]Get your API key at:[/muted] [info]https://support.pagerduty.com/docs/api-access-keys[/info]"
        )
        console.print()
        return 1

    # Parse service file with optional environment overrides
    try:
        manifest = load_manifest(
            service_file, environment=environment, suppress_deprecation_warning=True
        )
    except Exception as e:
        error(f"Error parsing service file: {e}")
        console.print()
        return 1

    ownership = manifest.ownership
    pagerduty = ownership.pagerduty if ownership else None

    if pagerduty is None:
        error(f"No PagerDuty configuration found in {service_file}")
        console.print()
        console.print("[muted]Add one. srm/v1 (spec.ownership):[/muted]")
        console.print("  pagerduty:")
        console.print("    service_id: PXXXXXX")
        console.print("    escalation_policy_id: PXXXXXX")
        console.print("[muted]Legacy service.yaml (resources):[/muted]")
        console.print("  - kind: PagerDuty")
        console.print("    name: primary")
        console.print("    spec:")
        console.print("      escalation_policy: my-policy")
        console.print("      urgency: high")
        console.print()
        return 1

    # The policy NAME is ownership.escalation in every format. For the legacy
    # format common also stores that name in PagerDutyConfig.escalation_policy_id
    # (nthlayer-common parser/loader.py _extract_ownership), so only srm/v1 and v2 have a real
    # ID there. No legacy example declares an ID; legacy read
    # spec.escalation_policy_id, which common does not carry.
    escalation_policy_name = ownership.escalation if ownership else None
    escalation_policy_id = (
        pagerduty.escalation_policy_id if manifest.source_format != SourceFormat.LEGACY else None
    )

    console.print(f"[bold]Service:[/bold] {manifest.name}")
    console.print(f"   [muted]Team:[/muted] {manifest.team}")
    console.print(f"   [muted]Tier:[/muted] {manifest.tier}")
    console.print()

    if dry_run:
        info("DRY RUN MODE - No changes will be made")
        console.print()
        console.print("[bold]Would create/verify:[/bold]")
        console.print(f"  [muted]•[/muted] PagerDuty service: {manifest.name}")

        if escalation_policy_name:
            console.print(f"  [muted]•[/muted] Escalation policy: {escalation_policy_name}")

        if manifest.team:
            console.print(f"  [muted]•[/muted] Team mapping: {manifest.team}")

        console.print()
        return 0

    # Setup PagerDuty
    console.print("[info]Setting up PagerDuty integration...[/info]")
    console.print()

    try:
        with PagerDutyClient(api_key) as client:
            # Prepare config
            urgency = pagerduty.urgency or "high"
            auto_resolve_timeout = pagerduty.auto_resolve_timeout

            # Check if we should create escalation policy
            create_ep_config = pagerduty.create_escalation_policy or None

            result = client.setup_service(
                service_name=manifest.name,
                team_name=manifest.team,
                escalation_policy_name=escalation_policy_name,
                escalation_policy_id=escalation_policy_id,
                urgency=urgency,
                auto_resolve_timeout=auto_resolve_timeout,
                create_escalation_policy_config=create_ep_config,
            )

        if not result.success:
            error(f"Setup failed: {result.error}")
            console.print()
            return 1

        # Display results
        if result.created_service:
            success("Created PagerDuty service")
        else:
            success("PagerDuty service already exists")

        console.print(f"   [muted]Service ID:[/muted] {result.service_id}")
        console.print(f"   [muted]Service URL:[/muted] [info]{result.service_url}[/info]")
        console.print()

        if result.created_escalation_policy:
            success("Created escalation policy")
            console.print(f"   [muted]Policy ID:[/muted] {result.escalation_policy_id}")
            console.print()

        if result.team_id:
            if result.created_team:
                success(f"Created team: {manifest.team}")
            else:
                success(f"Added to existing team: {manifest.team}")
            console.print(f"   [muted]Team ID:[/muted] {result.team_id}")
            console.print()

        if result.warnings:
            warning("Warnings:")
            for warn in result.warnings:
                console.print(f"   [warning]•[/warning] {warn}")
            console.print()

        success("PagerDuty setup complete!")
        console.print()
        console.print("[bold]Next steps:[/bold]")
        console.print(f"   [muted]1.[/muted] Visit: [info]{result.service_url}[/info]")
        console.print("   [muted]2.[/muted] Configure integrations (email, webhooks, etc.)")
        console.print(
            f"   [muted]3.[/muted] Test alerting with: "
            f"[info]nthlayer reslayer test-alert {manifest.name}[/info]"
        )
        console.print()

        return 0

    except Exception as e:
        error(f"Unexpected error: {e}")
        logger.error("pagerduty_setup_failed", err=str(e), exc_info=True)
        console.print()
        return 1
