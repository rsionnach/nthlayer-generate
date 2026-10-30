"""
Code generators for various formats.

Generates SLO configs, Prometheus rules, etc. from service definitions.

Built from nthlayer_common.manifest.ReliabilityManifest (the legacy
ServiceContext/Resource builders were removed in 4.0.0, opensrm-wo62.4.6).
"""

from nthlayer_generate.generators.alerts import generate_alerts_from_manifest
from nthlayer_generate.generators.sloth import (
    SlothGenerationResult,
    generate_sloth_from_manifest,
)

__all__ = [
    "SlothGenerationResult",
    "generate_sloth_from_manifest",
    "generate_alerts_from_manifest",
]
