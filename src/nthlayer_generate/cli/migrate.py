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
from nthlayer_common.manifest import (
    SRM_V1_JUDGMENT_THRESHOLD_TYPES,
    V2_JUDGMENT_THRESHOLD_TYPES,
    SourceFormat,
    load_manifest,
)

from nthlayer_generate.cli.ux import console, error, header, success, warning

if TYPE_CHECKING:
    from nthlayer_common.manifest import JudgmentThreshold, ReliabilityManifest


# What srm/v1 can carry per threshold type, the inverse of nthlayer_common's
# srm_v1_threshold (manifest/thresholds.py): calibration is one ECE bound plus a
# window, over a fixed 10 bins; feedback_latency is one maximum_p50 over a fixed
# 30d window.
_SRM_V1_CALIBRATION_BINS = 10
_SRM_V1_FEEDBACK_LATENCY_WINDOW = "30d"

# schema.json's Duration units (``^[0-9]+(ms|s|m|h|d|w)$``), ``ms`` before ``s``
# and ``m`` so a suffix match takes the longest unit.
_DURATION_UNITS = ("ms", "s", "m", "h", "d", "w")

# common's lift caps an srm/v1 feedback_latency target at 2**53
# (thresholds._srm_v1_feedback_latency_bound).
_SRM_V1_MAX_WHOLE_TARGET = 2**53

# SLO names srm/v1 refuses: its parser sends every V2_JUDGMENT_THRESHOLD_TYPES
# name to thresholds.srm_v1_threshold (parser/v1.py), which lifts only
# SRM_V1_JUDGMENT_THRESHOLD_TYPES and rejects the rest (segments, stability,
# audit_backlog). common's legacy loader keeps these as classical SLOs.
_SRM_V1_REJECTED_SLO_NAMES = V2_JUDGMENT_THRESHOLD_TYPES - SRM_V1_JUDGMENT_THRESHOLD_TYPES

# Keys common's lift accepts on calibration/feedback_latency and then drops
# (thresholds._SRM_V1_THRESHOLD_KEYS), so the JudgmentThreshold no longer has them.
_LIFT_DROPPED_KEYS = ("description", "labels")


def _split_duration(value: str) -> tuple[int, str] | None:
    """``"90m"`` -> ``(90, "m")``: the inverse of common's ``f"{int(target)}{unit}"``.

    None when *value* is not a Duration.
    """
    for unit in _DURATION_UNITS:
        if value.endswith(unit):
            digits = value[: -len(unit)]
            if digits.isascii() and digits.isdigit():
                return int(digits), unit
            return None
    return None


def _threshold_to_srm_v1(
    threshold: JudgmentThreshold, lost: list[str]
) -> dict[str, Any] | None:
    """The srm/v1 ``spec.slos`` entry for *threshold*, or None if it has no srm/v1 form.

    Anything srm/v1 cannot express is appended to *lost* as a message naming the
    threshold and the bound, never dropped silently. No ``type`` key:
    srm/v1 rejects one on these names.
    """
    kind = threshold.type
    bounds = dict(threshold.bounds)
    entry: dict[str, Any] | None = None
    # A maximum_p50 already reported on its own needs no "no carriable bound".
    p50_reported = False
    if kind == "calibration":
        ece = bounds.pop("maximum_expected_calibration_error", None)
        if ece is not None:
            entry = {"target": ece}
            if threshold.measurement.window:
                entry["window"] = threshold.measurement.window
            if threshold.measurement.bins != _SRM_V1_CALIBRATION_BINS:
                lost.append(
                    f"calibration: bins={threshold.measurement.bins} (srm/v1 fixes "
                    f"{_SRM_V1_CALIBRATION_BINS})"
                )
    elif kind == "feedback_latency":
        p50 = bounds.pop("maximum_p50", None)
        # Digits and unit as written: common's lift emits
        # f"{int(target)}{unit}", so this is its exact inverse. Re-spelling in
        # seconds would change the bound ("90m" -> "5400s") and could pass the
        # lift's 2**53 cap.
        split = _split_duration(p50) if isinstance(p50, str) else None
        if split is not None and split[0] <= _SRM_V1_MAX_WHOLE_TARGET:
            entry = {"target": split[0], "unit": split[1]}
        elif split is not None:
            lost.append(
                f"feedback_latency: maximum_p50={p50!r} (srm/v1 caps the target "
                f"at 2**53)"
            )
        elif p50 is not None:
            lost.append(f"feedback_latency: maximum_p50={p50!r} (not a Duration)")
        p50_reported = p50 is not None and entry is None
    for bound in sorted(bounds):
        lost.append(f"{kind}: {bound}={bounds[bound]!r} (no srm/v1 form)")
    if kind not in ("calibration", "feedback_latency"):
        lost.append(f"{kind}: threshold type has no srm/v1 form")
    elif entry is None and not bounds and not p50_reported:
        lost.append(f"{kind}: no carriable bound")
    return entry


def _lift_dropped_fields(raw: Any) -> list[str]:
    """Messages for the keys common's lift dropped from legacy threshold resources.

    The lift reads ``description`` and ``labels`` on a calibration or
    feedback_latency SLO resource and keeps neither (_LIFT_DROPPED_KEYS), so
    they are reported from the source document rather than from the manifest.
    """
    resources = raw.get("resources") if isinstance(raw, dict) else None
    lost: list[str] = []
    for resource in resources if isinstance(resources, list) else []:
        if not isinstance(resource, dict) or resource.get("kind") != "SLO":
            continue
        name = resource.get("name")
        spec = resource.get("spec")
        if name not in SRM_V1_JUDGMENT_THRESHOLD_TYPES or not isinstance(spec, dict):
            continue
        for key in _LIFT_DROPPED_KEYS:
            if key in spec:
                lost.append(f"{name}: {key}={spec[key]!r} (dropped when loaded)")
    return lost


def _legacy_to_srm_v1(
    manifest: ReliabilityManifest, lost: list[str] | None = None
) -> dict[str, Any]:
    """Serialise a legacy-loaded manifest as an srm/v1 document.

    A port of generate's ``ReliabilityManifest.to_dict`` (opensrm-wo62.1, D7)
    over nthlayer-common's model, for the fields common's legacy parser
    populates: name, team, tier, type, description, labels, annotations,
    SLOs (with their ``type``, which to_dict omitted), dependencies and
    ownership. ``contract`` and ``instrumentation``
    are not ported: a legacy ``service:`` file has neither, and migrate only
    serialises legacy input.

    ``type`` is the RESOLVED spelling, deliberately: this writes a FILE, and a
    file carries the canonical spelling the spec accepts (``x-web``, not
    ``web``). The authored spelling is for ``${type}`` substitution into
    queries, which is not this destination (opensrm-z3ab).

    ``manifest.judgment_thresholds`` (calibration and feedback_latency, which
    common's legacy parser lifts out of ``slos``) are written back as srm/v1
    ``spec.slos`` entries. What srm/v1 cannot express is appended to *lost*
    (when given) rather than dropped silently [opensrm-wo62.1].
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

    if manifest.slos or manifest.judgment_thresholds:
        result["spec"]["slos"] = {}
        threshold_lost: list[str] = []
        for slo in manifest.slos:
            if slo.name in _SRM_V1_REJECTED_SLO_NAMES:
                # Written as an SLO, srm/v1 would refuse the whole file.
                threshold_lost.append(
                    f"{slo.name}: SLO target={slo.target!r} window={slo.window!r} "
                    f"(srm/v1 rejects '{slo.name}'; declare it in an "
                    f"opensrm.nthlayer.io/v2 manifest under spec.judgment_threshold)"
                )
                continue
            # ``type`` always: common's srm/v1 parser infers it only from a
            # few names and indicator shapes, and rejects the file otherwise
            # (``_infer_slo_type``) — six shipped legacy examples included.
            # Key order is the written file's order: ``type`` first. The
            # names srm/v1 lifts into thresholds (and rejects ``type`` on)
            # never reach here: common's legacy loader lifts them too.
            slo_data: dict[str, Any] = {"type": slo.slo_type}
            slo_data["target"] = slo.target
            slo_data["window"] = slo.window
            if slo.unit:
                slo_data["unit"] = slo.unit
            if slo.percentile:
                slo_data["percentile"] = slo.percentile
            if slo.description:
                slo_data["description"] = slo.description
            result["spec"]["slos"][slo.name] = slo_data
        for threshold in manifest.judgment_thresholds:
            entry = _threshold_to_srm_v1(threshold, threshold_lost)
            if entry is not None:
                result["spec"]["slos"][threshold.type] = entry
        if lost is not None:
            lost.extend(threshold_lost)
        if not result["spec"]["slos"]:
            del result["spec"]["slos"]

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
    lost: list[str] = []
    opensrm_data = _legacy_to_srm_v1(manifest, lost)
    # The file loaded above, so it is readable YAML.
    lost.extend(_lift_dropped_fields(yaml.safe_load(input_path.read_text(encoding="utf-8"))))
    for item in lost:
        warning(f"Judgment threshold not carried into srm/v1: {item}")

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
