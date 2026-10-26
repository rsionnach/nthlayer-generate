"""
CLI command for migrating legacy NthLayer format to OpenSRM format.

Usage:
    nthlayer migrate service.yaml
    nthlayer migrate service.yaml --output /tmp/
    nthlayer migrate service.yaml --dry-run
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from nthlayer_common.manifest import SourceFormat, load_manifest

from nthlayer_generate.cli.ux import console, error, header, success, warning

if TYPE_CHECKING:
    from nthlayer_common.manifest import ReliabilityManifest


def _legacy_to_srm_v1(manifest: ReliabilityManifest) -> dict[str, Any]:
    """Serialise a legacy-loaded manifest as an srm/v1 document.

    A port of generate's ``ReliabilityManifest.to_dict`` (opensrm-wo62.1, D7)
    over nthlayer-common's model, for the fields common's legacy parser
    populates: name, team, tier, type, description, labels, annotations,
    SLOs, dependencies and ownership. ``contract`` and ``instrumentation``
    are not ported: a legacy ``service:`` file has neither, and migrate only
    serialises legacy input.

    ``type`` is the RESOLVED spelling, deliberately: this writes a FILE, and a
    file carries the canonical spelling the spec accepts (``x-web``, not
    ``web``). The authored spelling is for ``${type}`` substitution into
    queries, which is not this destination (opensrm-z3ab).
    """
    result: dict[str, Any] = {
        "apiVersion": "srm/v1",
        "kind": "ServiceReliabilityManifest",
        "metadata": {
            "name": manifest.name,
            "team": manifest.team,
            "tier": manifest.tier,
        },
        "spec": {
            "type": manifest.type,
        },
    }

    if manifest.description:
        result["metadata"]["description"] = manifest.description
    if manifest.labels:
        result["metadata"]["labels"] = manifest.labels
    if manifest.annotations:
        result["metadata"]["annotations"] = manifest.annotations

    if manifest.slos:
        result["spec"]["slos"] = {}
        for slo in manifest.slos:
            slo_data: dict[str, Any] = {
                "target": slo.target,
                "window": slo.window,
            }
            if slo.unit:
                slo_data["unit"] = slo.unit
            if slo.percentile:
                slo_data["percentile"] = slo.percentile
            if slo.description:
                slo_data["description"] = slo.description
            result["spec"]["slos"][slo.name] = slo_data

    if manifest.dependencies:
        result["spec"]["dependencies"] = [
            {
                "name": dep.name,
                "type": dep.type,
                "critical": dep.critical,
            }
            for dep in manifest.dependencies
        ]

    if manifest.ownership:
        ownership: dict[str, Any] = {"team": manifest.ownership.team}
        if manifest.ownership.slack:
            ownership["slack"] = manifest.ownership.slack
        if manifest.ownership.email:
            ownership["email"] = manifest.ownership.email
        if manifest.ownership.runbook:
            ownership["runbook"] = manifest.ownership.runbook
        result["spec"]["ownership"] = ownership

    return result


def register_migrate_parser(subparsers: argparse._SubParsersAction[Any]) -> None:
    """Register the migrate command parser."""
    migrate_parser = subparsers.add_parser(
        "migrate",
        help="Migrate legacy NthLayer service.yaml to OpenSRM format",
    )
    migrate_parser.add_argument(
        "service_yaml",
        help="Path to legacy service YAML file",
    )
    migrate_parser.add_argument(
        "--output",
        "-o",
        help="Output directory (default: same directory as input)",
    )
    migrate_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print migrated YAML without writing file",
    )
    migrate_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing files",
    )


def handle_migrate_command(args: argparse.Namespace) -> int:
    """Handle the migrate command."""
    return migrate_command(
        service_yaml=args.service_yaml,
        output_dir=getattr(args, "output", None),
        dry_run=getattr(args, "dry_run", False),
        force=getattr(args, "force", False),
    )


def migrate_command(
    service_yaml: str,
    output_dir: str | None = None,
    dry_run: bool = False,
    force: bool = False,
) -> int:
    """
    Migrate legacy NthLayer format to OpenSRM format.

    Args:
        service_yaml: Path to legacy service YAML file
        output_dir: Output directory (default: same directory as input)
        dry_run: If True, print output without writing file
        force: If True, overwrite existing files

    Returns:
        Exit code (0 for success, 1 for error)
    """
    input_path = Path(service_yaml)

    if not input_path.exists():
        error(f"File not found: {service_yaml}")
        return 1

    # Load manifest (auto-detects format)
    try:
        manifest = load_manifest(input_path, suppress_deprecation_warning=True)
    except Exception as e:
        error(f"Failed to parse {service_yaml}: {e}")
        return 1

    # Only legacy needs migrating: srm/v1 and v2 are both already OpenSRM.
    # Comparing with SRM_V1 instead would "migrate" a v2 file down to srm/v1
    # (spec §5.2 ruling on source_format).
    if manifest.source_format != SourceFormat.LEGACY:
        console.print()
        header(f"Migration: {manifest.name}")
        console.print()
        success("File is already in OpenSRM format. No migration needed.")
        console.print()
        return 0

    # Convert to OpenSRM format
    opensrm_data = _legacy_to_srm_v1(manifest)

    # Generate output YAML
    yaml_output = yaml.dump(
        opensrm_data,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
    )

    # Add header comment
    header_comment = (
        "# OpenSRM Service Reliability Manifest\n"
        "# Migrated from legacy NthLayer format\n"
        f"# Original file: {input_path.name}\n"
        "#\n"
        "# For more information, see:\n"
        "# https://github.com/rsionnach/opensrm\n"
        "#\n\n"
    )
    yaml_output = header_comment + yaml_output

    if dry_run:
        # Print to stdout
        console.print()
        header(f"Migration Preview: {manifest.name}")
        console.print()
        console.print("[muted]─" * 60 + "[/muted]")
        print(yaml_output)
        console.print("[muted]─" * 60 + "[/muted]")
        console.print()
        console.print("[muted]Run without --dry-run to write to file[/muted]")
        return 0

    # Determine output path
    if output_dir:
        output_path = Path(output_dir) / f"{manifest.name}.reliability.yaml"
    else:
        output_path = input_path.parent / f"{manifest.name}.reliability.yaml"

    # Check if output file exists
    if output_path.exists() and not force:
        error(f"Output file already exists: {output_path}")
        console.print("[muted]Use --force to overwrite[/muted]")
        return 1

    # Write output file
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            f.write(yaml_output)
    except Exception as e:
        error(f"Failed to write {output_path}: {e}")
        return 1

    # Print summary
    console.print()
    header(f"Migration Complete: {manifest.name}")
    console.print()

    console.print("  [success]✓[/success] Converted from legacy NthLayer format to OpenSRM")
    console.print()

    console.print("  [bold]Changes:[/bold]")
    console.print("    • Added apiVersion: srm/v1")
    console.print("    • Added kind: ServiceReliabilityManifest")
    console.print("    • Restructured metadata and spec sections")

    if manifest.type in ("background-job", "pipeline"):
        original_type = "background-job" if manifest.type == "worker" else "pipeline"
        console.print(f"    • Normalized service type: {original_type} → {manifest.type}")

    console.print()
    console.print(f"  [bold]Output:[/bold] {output_path}")
    console.print()

    # Show next steps
    console.print("  [bold]Next steps:[/bold]")
    console.print(f"    1. Review the migrated file: [info]{output_path}[/info]")
    console.print(f"    2. Validate: [info]nthlayer validate {output_path}[/info]")
    console.print(f"    3. Test: [info]nthlayer plan {output_path}[/info]")
    console.print()

    # Warn about legacy file
    warning(f"The legacy file ({input_path.name}) can be removed after validation")
    console.print()

    return 0
