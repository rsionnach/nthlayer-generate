"""
Service specification parsing and validation.

The reliability-manifest model and loader (srm/v1, opensrm.nthlayer.io/v2
and legacy formats, auto-detected) live in nthlayer-common:

    from nthlayer_common.manifest import load_manifest

    manifest = load_manifest("service.yaml")

nthlayer-generate 3.0.0 stopped re-exporting ``load_manifest``,
``ReliabilityManifest``, ``SLODefinition`` and ``ManifestLoadError`` here
(opensrm-wo62.1); import them from ``nthlayer_common.manifest``.

nthlayer-generate 4.0.0 removed the legacy ``parse_service_file`` loader and
its ``ServiceContext``/``Resource`` re-exports here (opensrm-wo62.4.6); every
format, legacy ``service:`` files included, loads through ``load_manifest``.
"""
