"""CLI command for migrating srm/v1 and opensrm/v1 manifests to opensrm.nthlayer.io/v2.

Usage::

    nthlayer migrate-manifest service.yaml
    nthlayer migrate-manifest service.yaml --output service.v2.yaml
    nthlayer migrate-manifest service.yaml --dry-run
    nthlayer migrate-manifest service.yaml --allow-lossy --service-type api

Acceptance (opensrm-b22.2): converts every demo spec; output round-trips
through the v2 parser without loss of canonical fields.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml
from nthlayer_common.manifest.opensrm_v1 import (
    convert_opensrm_v1_to_v2,
    is_opensrm_v1_format,
)
from nthlayer_common.manifest.parser.v2 import OpenSRMV2ParseError, parse_opensrm_v2
from nthlayer_common.manifest.v1_compat import convert_v1_to_v2

from nthlayer_generate.cli.ux import console, error, header, success, warning


def register_migrate_manifest_parser(
    subparsers: argparse._SubParsersAction[Any],
) -> None:
    """Register the migrate-manifest command parser."""
    p = subparsers.add_parser(
        "migrate-manifest",
        help="Migrate an srm/v1 or opensrm/v1 manifest to opensrm.nthlayer.io/v2",
    )
    p.add_argument("manifest", help="Path to srm/v1 or opensrm/v1 manifest YAML")
    p.add_argument(
        "--output",
        "-o",
        help="Output path for the v2 manifest (default: alongside input as *.v2.yaml)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the v2 YAML to stdout without writing a file",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing output file",
    )
    p.add_argument(
        "--allow-lossy",
        action="store_true",
        help=(
            "Write the v2 manifest even though some opensrm/v1 fields have no v2 "
            "equivalent (they are listed)"
        ),
    )
    p.add_argument(
        "--service-type",
        help="spec.service.type to use when an opensrm/v1 manifest has no spec.type",
    )


def handle_migrate_manifest_command(args: argparse.Namespace) -> int:
    return migrate_manifest_command(
        manifest_path=args.manifest,
        output_path=getattr(args, "output", None),
        dry_run=getattr(args, "dry_run", False),
        force=getattr(args, "force", False),
        allow_lossy=getattr(args, "allow_lossy", False),
        service_type=getattr(args, "service_type", None),
    )


def migrate_manifest_command(
    manifest_path: str,
    output_path: str | None = None,
    dry_run: bool = False,
    force: bool = False,
    allow_lossy: bool = False,
    service_type: str | None = None,
) -> int:
    """Convert an srm/v1 or opensrm/v1 manifest to opensrm.nthlayer.io/v2 and verify round-trip.

    An opensrm/v1 manifest with fields that have no v2 equivalent is refused
    unless ``allow_lossy``; fields converted under an assumption only warn.

    Returns 0 on success, 1 on error.
    """
    in_path = Path(manifest_path)
    if not in_path.exists():
        error(f"Manifest not found: {manifest_path}")
        return 1

    try:
        with open(in_path) as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        error(f"Invalid YAML in {manifest_path}: {exc}")
        return 1

    if not isinstance(data, dict):
        error(f"Manifest is not a YAML object: {manifest_path}")
        return 1

    if data.get("apiVersion") == "opensrm.nthlayer.io/v2":
        success(f"{in_path.name} is already opensrm.nthlayer.io/v2 — no migration needed.")
        return 0

    api_version = data.get("apiVersion")
    if is_opensrm_v1_format(data):
        source = "opensrm/v1"
        try:
            result = convert_opensrm_v1_to_v2(data, service_type=service_type)
        except ValueError as exc:
            error(f"Cannot convert {manifest_path}: {exc}")
            return 1
        for field in result.unmapped:
            if field.kind == "dropped":
                warning(f"Not migrated: {field.path} — {field.reason}")
            else:
                warning(f"Converted with an assumption: {field.path} — {field.reason} (check it)")
        if result.lossy and not allow_lossy:
            dropped = sum(1 for f in result.unmapped if f.kind == "dropped")
            error(
                f"{dropped} field(s) in {manifest_path} have no v2 equivalent; "
                "nothing written. Re-run with --allow-lossy to write the v2 manifest without them."
            )
            return 1
        v2_data = result.manifest
    elif api_version == "srm/v1":
        source = "srm/v1"
        try:
            v2_data = convert_v1_to_v2(data)
        except ValueError as exc:
            error(f"Cannot convert {manifest_path}: {exc}")
            return 1
    else:
        error(f"Cannot convert {manifest_path}: apiVersion {api_version!r} is not srm/v1 or opensrm/v1")
        return 1

    # Round-trip verification: the converted manifest must parse via the
    # v2 parser. If parsing fails, the migration produced bad output —
    # surface that loudly rather than writing a broken file.
    try:
        parse_opensrm_v2(v2_data, base_dir=in_path.parent)
    except OpenSRMV2ParseError as exc:
        error(f"Converted manifest fails v2 parse: {exc}")
        return 1

    yaml_text = (
        f"# OpenSRM v2 manifest (migrated from {source})\n"
        f"# Source: {in_path.name}\n"
        "# Generated by `nthlayer migrate-manifest`.\n\n"
        + yaml.safe_dump(v2_data, default_flow_style=False, sort_keys=False)
    )

    if dry_run:
        header(f"Migration preview: {in_path.name}")
        console.print()
        print(yaml_text)
        return 0

    out_path = Path(output_path) if output_path else in_path.with_suffix(".v2.yaml")
    if out_path.exists() and not force:
        error(f"Output file exists: {out_path} — use --force to overwrite")
        return 1

    _warn_relative_refs(v2_data, in_path, out_path)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(yaml_text)

    success(f"Migrated {in_path.name} → {out_path}")
    return 0


def _warn_relative_refs(v2_data: dict[str, Any], in_path: Path, out_path: Path) -> None:
    """Warn when a relative openslo $ref will resolve differently from the output.

    The refs were resolved (and verified) against the input's directory; the
    written manifest keeps them verbatim, so a different output directory
    changes what they point at.
    """
    if out_path.parent.resolve() == in_path.parent.resolve():
        return
    slos = (v2_data.get("spec") or {}).get("slo")
    for item in slos if isinstance(slos, list) else []:
        ref = item.get("$ref") if isinstance(item, dict) else None
        if isinstance(ref, str) and "://" not in ref and not Path(ref).is_absolute():
            warning(
                f"openslo $ref {ref!r} is relative and now resolves against {out_path.parent}, "
                f"not {in_path.parent}; copy the file or fix the path"
            )
