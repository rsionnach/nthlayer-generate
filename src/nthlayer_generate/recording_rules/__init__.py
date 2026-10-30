"""Prometheus recording rules generation.

Generate recording rules for efficient SLO calculations.

Built from nthlayer_common.manifest.ReliabilityManifest (the legacy
build_recording_rules was removed in 4.0.0, opensrm-wo62.4.6).
"""

from nthlayer_generate.recording_rules.manifest_builder import (
    ManifestRecordingRuleBuilder,
    build_recording_rules_from_manifest,
)
from nthlayer_generate.recording_rules.models import RecordingRule, RecordingRuleGroup

__all__ = [
    "RecordingRule",
    "RecordingRuleGroup",
    "build_recording_rules_from_manifest",
    "ManifestRecordingRuleBuilder",
]
