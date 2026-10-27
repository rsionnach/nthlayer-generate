"""
Service specification parsing and validation.

The reliability-manifest model and loader (srm/v1, opensrm.nthlayer.io/v2
and legacy formats, auto-detected) live in nthlayer-common:

    from nthlayer_common.manifest import load_manifest

    manifest = load_manifest("service.yaml")

nthlayer-generate 3.0.0 stopped re-exporting ``load_manifest``,
``ReliabilityManifest``, ``SLODefinition`` and ``ManifestLoadError`` here
(opensrm-wo62.1); import them from ``nthlayer_common.manifest``.

Legacy usage (still supported):
    from nthlayer_generate.specs import parse_service_file

    context, resources = parse_service_file("service.yaml")
"""

# Legacy API (backward compatibility)
from nthlayer_generate.specs.parser import Resource, ServiceContext, parse_service_file

__all__ = [
    "parse_service_file",
    "ServiceContext",
    "Resource",
]
