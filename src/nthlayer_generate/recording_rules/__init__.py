"""Prometheus recording rules generation.

Generate recording rules for efficient SLO calculations.

Supports both legacy (ServiceContext, Resources) and manifest
(nthlayer_common.manifest.ReliabilityManifest) APIs.
"""

from nthlayer_generate.recording_rules.builder import build_recording_rules
from nthlayer_generate.recording_rules.manifest_builder import (
    ManifestRecordingRuleBuilder,
    build_recording_rules_from_manifest,
)
from nthlayer_generate.recording_rules.models import RecordingRule, RecordingRuleGroup

__all__ = [
    "RecordingRule",
    "RecordingRuleGroup",
    # Legacy API
    "build_recording_rules",
    # Manifest API (nthlayer_common.manifest.ReliabilityManifest)
    "build_recording_rules_from_manifest",
    "ManifestRecordingRuleBuilder",
]
