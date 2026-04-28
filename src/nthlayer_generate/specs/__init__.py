"""
Service specification parsing and validation.

Supports both OpenSRM format (apiVersion: srm/v1) and legacy NthLayer
format (service: + resources:) with automatic detection.

Recommended usage:
    from nthlayer_generate.specs import load_manifest

    manifest = load_manifest("service.yaml")

Legacy usage (still supported):
    from nthlayer_generate.specs import parse_service_file

    context, resources = parse_service_file("service.yaml")
"""

# Core public API
from nthlayer_generate.specs.loader import (
    ManifestLoadError,
    load_manifest,
)
from nthlayer_generate.specs.manifest import (
    ReliabilityManifest,
    SLODefinition,
)

# Legacy API (backward compatibility)
from nthlayer_generate.specs.parser import Resource, ServiceContext, parse_service_file

__all__ = [
    # Core API
    "load_manifest",
    "ReliabilityManifest",
    "SLODefinition",
    "ManifestLoadError",
    # Legacy API (backward compatibility)
    "parse_service_file",
    "ServiceContext",
    "Resource",
]
