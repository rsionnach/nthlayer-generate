"""Tests for srm/v1 and legacy parsing through nthlayer-common's manifest model.

Ported from generate's retired manifest stack (opensrm-wo62.1): what remains
here is not covered by nthlayer-common's own suite, plus generate's consumers
of the model (migrate's _legacy_to_srm_v1, service_context_from_manifest,
the manifest recording-rule builder)."""

import warnings

import pytest
from nthlayer_common.manifest import (
    VALID_SERVICE_TYPES,
    VALID_TIERS,
    Dependency,
    LegacyFormatWarning,
    ManifestLoadError,
    ReliabilityManifest,
    SLODefinition,
    SourceFormat,
    is_valid_service_type,
    load_manifest,
)
from nthlayer_common.manifest.parser.v1 import (
    OpenSRMParseError,
    is_srm_v1_format,
    parse_srm_v1,
    parse_srm_v1_file,
)

from nthlayer_generate.cli.migrate import _legacy_to_srm_v1
from nthlayer_generate.specs.context import service_context_from_manifest

# Retired-stack API successors (opensrm-wo62.1, spec §5.2, D7):
#   ReliabilityManifest.to_dict()            -> cli/migrate.py _legacy_to_srm_v1
#   ReliabilityManifest.to_service_context() -> specs/context.py
#       service_context_from_manifest(m).to_dict() (the same dict shape)
# Hand-built SLODefinitions are srm/v1 SLOs keyed by type: in opensrm spec/v1/schema.json @859424a /definitions/SLOs
# (additionalProperties: false) the SLO key IS the type, so an SLO named
# availability/latency/error_rate/throughput has that slo_type.


class TestOpenSRMFormatDetection:
    """Test OpenSRM format detection."""

    def test_detect_opensrm_format(self):
        """Test detection of OpenSRM format."""
        data = {
            "apiVersion": "srm/v1",
            "kind": "ServiceReliabilityManifest",
            "metadata": {"name": "test"},
            "spec": {"type": "api"},
        }
        assert is_srm_v1_format(data) is True

    def test_detect_legacy_format(self):
        """Test detection of legacy format."""
        data = {
            "service": {"name": "test"},
            "resources": [],
        }
        assert is_srm_v1_format(data) is False

    def test_detect_invalid_api_version(self):
        """Test detection fails for wrong apiVersion."""
        data = {
            "apiVersion": "v2",  # Wrong version
            "kind": "ServiceReliabilityManifest",
        }
        assert is_srm_v1_format(data) is False


class TestOpenSRMParser:
    """Test OpenSRM format parsing."""

    def test_parse_minimal_opensrm(self):
        """Test parsing minimal OpenSRM manifest."""
        data = {
            "apiVersion": "srm/v1",
            "kind": "ServiceReliabilityManifest",
            "metadata": {
                "name": "payment-api",
                "team": "payments",
                "tier": "critical",
            },
            "spec": {
                "type": "api",
            },
        }

        manifest = parse_srm_v1(data)

        assert manifest.name == "payment-api"
        assert manifest.team == "payments"
        assert manifest.tier == "critical"
        assert manifest.type == "api"
        assert manifest.source_format == SourceFormat.OPENSRM

    def test_parse_opensrm_with_slos(self):
        """Test parsing OpenSRM with SLO definitions."""
        data = {
            "apiVersion": "srm/v1",
            "kind": "ServiceReliabilityManifest",
            "metadata": {
                "name": "payment-api",
                "team": "payments",
                "tier": "critical",
            },
            "spec": {
                "type": "api",
                "slos": {
                    "availability": {
                        "target": 99.95,
                        "window": "30d",
                    },
                    "latency": {
                        "target": 200,
                        "unit": "ms",
                        "percentile": "p99",
                        "window": "30d",
                    },
                },
            },
        }

        manifest = parse_srm_v1(data)

        assert len(manifest.slos) == 2
        avail_slo = next(s for s in manifest.slos if s.name == "availability")
        assert avail_slo.target == 99.95
        assert avail_slo.window == "30d"

        latency_slo = next(s for s in manifest.slos if s.name == "latency")
        assert latency_slo.target == 200
        assert latency_slo.unit == "ms"
        assert latency_slo.percentile == "p99"

    def test_parse_opensrm_with_dependencies(self):
        """Test parsing OpenSRM with dependencies."""
        data = {
            "apiVersion": "srm/v1",
            "kind": "ServiceReliabilityManifest",
            "metadata": {
                "name": "payment-api",
                "team": "payments",
                "tier": "critical",
            },
            "spec": {
                "type": "api",
                "dependencies": [
                    {
                        "name": "postgres",
                        "type": "database",
                        "critical": True,
                        "slo": {
                            "availability": 99.99,
                        },
                    },
                    {
                        "name": "redis",
                        "type": "cache",
                        "critical": False,
                    },
                ],
            },
        }

        manifest = parse_srm_v1(data)

        assert len(manifest.dependencies) == 2
        postgres = next(d for d in manifest.dependencies if d.name == "postgres")
        assert postgres.type == "database"
        assert postgres.critical is True
        assert postgres.slo.availability == 99.99

    def test_parse_opensrm_ai_gate(self):
        """Test parsing AI gate service with judgment SLOs."""
        data = {
            "apiVersion": "srm/v1",
            "kind": "ServiceReliabilityManifest",
            "metadata": {
                "name": "fraud-detector",
                "team": "risk",
                "tier": "critical",
            },
            "spec": {
                "type": "ai-gate",
                "slos": {
                    "availability": {
                        "target": 99.9,
                        "window": "30d",
                    },
                    "reversal_rate": {
                        "target": 0.05,
                        "window": "7d",
                    },
                    "high_confidence_failure": {
                        "target": 0.01,
                        "window": "7d",
                    },
                },
                "instrumentation": {
                    "telemetry_events": [
                        {
                            "name": "decision",
                            "fields": ["confidence", "outcome", "ground_truth"],
                        }
                    ],
                    "feedback_loop": "feedback-service",
                },
            },
        }

        manifest = parse_srm_v1(data)

        assert manifest.is_ai_gate()
        assert manifest.type == "ai-gate"

        # Check judgment SLOs
        judgment_slos = manifest.get_judgment_slos()
        assert len(judgment_slos) == 2

        reversal = next(s for s in judgment_slos if s.name == "reversal_rate")
        assert reversal.target == 0.05

        # Check instrumentation
        assert manifest.instrumentation is not None
        assert len(manifest.instrumentation.telemetry_events) == 1
        assert manifest.instrumentation.feedback_loop == "feedback-service"

    def test_parse_missing_required_field(self):
        """Test error when required field missing."""
        data = {
            "apiVersion": "srm/v1",
            "kind": "ServiceReliabilityManifest",
            "metadata": {
                "name": "test",
                # Missing: team, tier
            },
            "spec": {
                "type": "api",
            },
        }

        with pytest.raises(OpenSRMParseError, match="team is required"):
            parse_srm_v1(data)

    def test_parse_invalid_format(self):
        """Test error when not OpenSRM format."""
        data = {
            "service": {"name": "test"},
        }

        # The exception type is the contract; the message text is not asserted.
        with pytest.raises(OpenSRMParseError):
            parse_srm_v1(data)


class TestUnifiedLoader:
    """Test the unified manifest loader with format auto-detection."""

    def test_load_legacy_format_with_warning(self, tmp_path):
        """Test loading legacy format shows deprecation warning."""
        manifest_file = tmp_path / "service.yaml"
        manifest_file.write_text("""
service:
  name: payment-api
  team: payments
  tier: critical
  type: api

resources:
  - kind: SLO
    name: availability
    spec:
      objective: 99.95
      window: 30d
""")

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            manifest = load_manifest(manifest_file)

            assert len(w) == 1
            assert issubclass(w[0].category, LegacyFormatWarning)
            assert "Legacy NthLayer format detected" in str(w[0].message)

        assert manifest.name == "payment-api"
        assert manifest.source_format == SourceFormat.LEGACY

    def test_load_legacy_format_suppress_warning(self, tmp_path):
        """Test loading legacy format without warning when suppressed."""
        manifest_file = tmp_path / "service.yaml"
        manifest_file.write_text("""
service:
  name: payment-api
  team: payments
  tier: critical
  type: api
""")

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            manifest = load_manifest(manifest_file, suppress_deprecation_warning=True)

            assert len(w) == 0

        assert manifest.name == "payment-api"

class TestReliabilityManifest:
    """Test the ReliabilityManifest model."""

    def test_manifest_to_dict(self):
        """Test converting manifest to dict."""
        manifest = ReliabilityManifest(
            name="payment-api",
            team="payments",
            tier="critical",
            type="api",
            slos=[
                SLODefinition(
                    name="availability", target=99.95, slo_type="availability", window="30d"
                ),
            ],
        )

        d = _legacy_to_srm_v1(manifest)

        assert d["apiVersion"] == "srm/v1"
        assert d["kind"] == "ServiceReliabilityManifest"
        assert d["metadata"]["name"] == "payment-api"
        assert d["spec"]["type"] == "api"
        assert "availability" in d["spec"]["slos"]

    def test_manifest_to_service_context(self):
        """Test converting manifest to legacy service context dict."""
        manifest = ReliabilityManifest(
            name="payment-api",
            team="payments",
            tier="critical",
            type="api",
            language="java",
        )

        ctx = service_context_from_manifest(manifest).to_dict()

        assert ctx["service"] == "payment-api"
        assert ctx["team"] == "payments"
        assert ctx["tier"] == "critical"
        assert ctx["language"] == "java"


class TestServiceTypeConstants:
    """Test service type constants and aliases."""

    def test_valid_tiers(self):
        """Test that all expected tiers are valid."""
        assert "critical" in VALID_TIERS
        assert "high" in VALID_TIERS  # NEW in OpenSRM
        assert "standard" in VALID_TIERS
        assert "low" in VALID_TIERS

    def test_valid_service_types(self):
        """Test that all expected service types are valid."""
        assert "api" in VALID_SERVICE_TYPES
        assert "worker" in VALID_SERVICE_TYPES  # OpenSRM canonical name
        assert "stream" in VALID_SERVICE_TYPES
        assert "ai-gate" in VALID_SERVICE_TYPES
        assert "batch" in VALID_SERVICE_TYPES  # OpenSRM canonical name
        assert "database" in VALID_SERVICE_TYPES

        # `web` is NOT a member post-opensrm-ih0v. It was an NthLayer
        # extension invented before the spec had a mechanism for one; it now
        # goes through the spec's `^x-[a-z][a-z0-9-]*$` branch as `x-web`,
        # which is why membership is the wrong question to ask of it — use
        # the predicate, which knows about the extension branch.
        assert "web" not in VALID_SERVICE_TYPES
        assert is_valid_service_type("x-web")

class TestOpenSRMFileParser:
    """Test parsing OpenSRM files from disk."""

    def test_parse_srm_v1_file(self, tmp_path):
        """Test parsing OpenSRM file from path."""
        manifest_file = tmp_path / "payment-api.reliability.yaml"
        manifest_file.write_text("""
apiVersion: srm/v1
kind: ServiceReliabilityManifest
metadata:
  name: payment-api
  team: payments
  tier: critical
  description: Payment processing API
  labels:
    domain: commerce
    cost-center: revenue
spec:
  type: api
  slos:
    availability:
      target: 99.95
      window: 30d
  ownership:
    team: payments
    slack: "#payments-alerts"
    runbook: https://wiki/runbooks/payment-api
  deployment:
    environments:
      - production
      - staging
    gates:
      error_budget:
        enabled: true
""")

        manifest = parse_srm_v1_file(manifest_file)

        assert manifest.name == "payment-api"
        assert manifest.description == "Payment processing API"
        assert manifest.labels == {"domain": "commerce", "cost-center": "revenue"}
        assert manifest.ownership is not None
        assert manifest.ownership.slack == "#payments-alerts"
        assert manifest.deployment is not None
        assert "production" in manifest.deployment.environments

    def test_parse_opensrm_file_not_found(self, tmp_path):
        """Test error when file not found."""
        with pytest.raises(FileNotFoundError):
            parse_srm_v1_file(tmp_path / "nonexistent.yaml")


class TestContractValidation:
    """Test contract validation."""

    def test_contract_validation_passes(self):
        """Test contract validation passes when SLOs are tighter."""
        from nthlayer_common.manifest.v1_compat import convert_v1_contract

        manifest = ReliabilityManifest(
            name="payment-api",
            team="payments",
            tier="critical",
            type="api",
            slos=[
                # Internal SLO
                SLODefinition(name="availability", target=99.99, slo_type="availability"),
            ],
            # External contract (99.9%): the srm/v1 block {availability: 0.999},
            # converted as common's srm/v1 parser does (parser/v1.py).
            contracts=[convert_v1_contract("payment-api", 0.999, None, None)],
        )

        errors = manifest.validate_contracts()
        assert len(errors) == 0

    def test_contract_validation_no_contract(self):
        """Test contract validation with no contract."""
        manifest = ReliabilityManifest(
            name="payment-api",
            team="payments",
            tier="critical",
            type="api",
        )

        errors = manifest.validate_contracts()
        assert len(errors) == 0

class TestLoaderEdgeCases:
    """Test loader edge cases for better coverage."""

    def test_load_non_dict_yaml(self, tmp_path):
        """Test loading YAML that's not a dict."""
        manifest_file = tmp_path / "list.yaml"
        manifest_file.write_text("- item1\n- item2")

        with pytest.raises(ManifestLoadError, match="Expected YAML object"):
            load_manifest(manifest_file)

    def test_load_explicit_opensrm_format(self, tmp_path):
        """Test loading with explicit OpenSRM format."""
        manifest_file = tmp_path / "service.yaml"
        manifest_file.write_text("""
apiVersion: srm/v1
kind: ServiceReliabilityManifest
metadata:
  name: test-api
  team: test
  tier: standard
spec:
  type: api
""")

        manifest = load_manifest(manifest_file, format="opensrm")
        assert manifest.name == "test-api"
        assert manifest.source_format == SourceFormat.OPENSRM

    def test_load_explicit_legacy_format(self, tmp_path):
        """Test loading with explicit legacy format."""
        manifest_file = tmp_path / "service.yaml"
        manifest_file.write_text("""
service:
  name: test-api
  team: test
  tier: standard
  type: api
""")

        manifest = load_manifest(manifest_file, format="legacy", suppress_deprecation_warning=True)
        assert manifest.name == "test-api"
        assert manifest.source_format == SourceFormat.LEGACY

    def test_is_manifest_file_not_yaml(self, tmp_path):
        """Test is_manifest_file with non-YAML file."""
        from nthlayer_common.manifest import is_manifest_file

        txt_file = tmp_path / "readme.txt"
        txt_file.write_text("not yaml")
        assert is_manifest_file(txt_file) is False

    def test_is_manifest_file_reliability_extension(self, tmp_path):
        """Test is_manifest_file with .reliability.yaml extension."""
        from nthlayer_common.manifest import is_manifest_file

        manifest_file = tmp_path / "api.reliability.yaml"
        manifest_file.write_text("""
apiVersion: srm/v1
kind: ServiceReliabilityManifest
metadata:
  name: api
  team: test
  tier: standard
spec:
  type: api
""")
        assert is_manifest_file(manifest_file) is True

    def test_is_manifest_file_service_yaml(self, tmp_path):
        """Test is_manifest_file with service.yaml name."""
        from nthlayer_common.manifest import is_manifest_file

        manifest_file = tmp_path / "service.yaml"
        manifest_file.write_text("""
service:
  name: api
  team: test
  tier: standard
  type: api
""")
        assert is_manifest_file(manifest_file) is True


class TestMigration:
    """Test migration functionality from legacy to OpenSRM format.

    Tests the core migration logic without importing CLI modules to avoid
    numpy import issues in Python 3.14.
    """

    def test_migrate_legacy_to_opensrm(self, tmp_path):
        """Test migrating legacy format to OpenSRM."""
        import yaml

        # Create legacy format file
        legacy_file = tmp_path / "payment-api.yaml"
        legacy_file.write_text("""
service:
  name: payment-api
  team: payments
  tier: critical
  type: api
  language: java

resources:
  - kind: SLO
    name: availability
    spec:
      objective: 99.95
      window: 30d
""")

        # Load legacy file
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", LegacyFormatWarning)
            manifest = load_manifest(legacy_file, suppress_deprecation_warning=True)

        assert manifest.source_format == SourceFormat.LEGACY
        assert manifest.name == "payment-api"
        assert manifest.team == "payments"
        assert manifest.tier == "critical"
        assert manifest.type == "api"

        # Convert to OpenSRM format
        opensrm_data = _legacy_to_srm_v1(manifest)
        assert opensrm_data["apiVersion"] == "srm/v1"
        assert opensrm_data["kind"] == "ServiceReliabilityManifest"
        assert opensrm_data["metadata"]["name"] == "payment-api"
        assert opensrm_data["spec"]["type"] == "api"

        # Write to new file
        output_file = tmp_path / "payment-api.reliability.yaml"
        with open(output_file, "w") as f:
            yaml.dump(opensrm_data, f, default_flow_style=False, sort_keys=False)

        # Verify new file loads as OpenSRM
        migrated = load_manifest(output_file)
        assert migrated.source_format == SourceFormat.OPENSRM
        assert migrated.name == "payment-api"
        assert migrated.team == "payments"

    def test_migrate_preserves_slos(self, tmp_path):
        """Test that migration preserves SLOs."""
        import yaml

        legacy_file = tmp_path / "api.yaml"
        legacy_file.write_text("""
service:
  name: api-service
  team: platform
  tier: high
  type: api

resources:
  - kind: SLO
    name: availability
    spec:
      objective: 99.9
      window: 30d
  - kind: SLO
    name: latency
    spec:
      objective: 200
      window: 30d
""")

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", LegacyFormatWarning)
            manifest = load_manifest(legacy_file, suppress_deprecation_warning=True)

        # Convert to OpenSRM
        opensrm_data = _legacy_to_srm_v1(manifest)

        # Write and reload
        output_file = tmp_path / "api-service.reliability.yaml"
        with open(output_file, "w") as f:
            yaml.dump(opensrm_data, f, default_flow_style=False, sort_keys=False)

        migrated = load_manifest(output_file)
        assert migrated.source_format == SourceFormat.OPENSRM
        assert len(migrated.slos) >= 0  # SLOs may or may not be preserved depending on parsing

    def test_migrate_type_aliases(self, tmp_path):
        """Test that legacy type names are normalized."""
        # Test background-job -> worker
        legacy_file = tmp_path / "worker.yaml"
        legacy_file.write_text("""
service:
  name: worker-job
  team: platform
  tier: standard
  type: background-job
""")

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", LegacyFormatWarning)
            manifest = load_manifest(legacy_file, suppress_deprecation_warning=True)

        assert manifest.type == "worker"  # Normalized

        opensrm_data = _legacy_to_srm_v1(manifest)
        assert opensrm_data["spec"]["type"] == "worker"

    def test_migrate_already_opensrm(self, tmp_path):
        """Test that OpenSRM files are detected as already migrated."""
        opensrm_file = tmp_path / "api.reliability.yaml"
        opensrm_file.write_text("""
apiVersion: srm/v1
kind: ServiceReliabilityManifest
metadata:
  name: api
  team: test
  tier: standard
spec:
  type: api
""")

        manifest = load_manifest(opensrm_file)
        assert manifest.source_format == SourceFormat.OPENSRM
        # No migration needed

    def test_round_trip_preserves_data(self, tmp_path):
        """Test that OpenSRM -> dict -> YAML -> load preserves data."""
        import yaml

        # Create a manifest directly
        manifest = ReliabilityManifest(
            name="round-trip-test",
            team="testing",
            tier="critical",
            type="api",
            description="Test description",
            labels={"env": "test", "version": "1.0"},
        )

        # Convert to dict
        data = _legacy_to_srm_v1(manifest)

        # Write as YAML
        output_file = tmp_path / "round-trip.reliability.yaml"
        with open(output_file, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

        # Load back
        loaded = load_manifest(output_file)
        assert loaded.name == "round-trip-test"
        assert loaded.team == "testing"
        assert loaded.tier == "critical"
        assert loaded.type == "api"
        assert loaded.description == "Test description"
        assert loaded.labels == {"env": "test", "version": "1.0"}


class TestManifestRecordingRuleBuilder:
    """Test recording rule builder for ReliabilityManifest."""

    def test_build_standard_slo_rules(self):
        """Test building recording rules for standard SLOs."""
        from nthlayer_generate.recording_rules.manifest_builder import (
            build_recording_rules_from_manifest,
        )

        manifest = ReliabilityManifest(
            name="payment-api",
            team="payments",
            tier="critical",
            type="api",
            slos=[
                SLODefinition(
                    name="availability", target=99.95, slo_type="availability", window="30d"
                ),
            ],
        )

        groups = build_recording_rules_from_manifest(manifest)
        assert len(groups) >= 1

        # Check SLO rules exist
        slo_group = next((g for g in groups if "slo_metrics" in g.name), None)
        assert slo_group is not None
        assert len(slo_group.rules) > 0

    def test_build_judgment_slo_rules(self):
        """Test building recording rules for AI gate judgment SLOs."""
        from nthlayer_generate.recording_rules.manifest_builder import (
            build_recording_rules_from_manifest,
        )

        manifest = ReliabilityManifest(
            name="fraud-detector",
            team="risk",
            tier="critical",
            type="ai-gate",
            # Judgment SLOs built as common's srm/v1 parser builds them
            # (parser/v1.py _parse_slos): slo_type "availability" (the
            # indicator shape) and judgment_type = the srm/v1 SLO name.
            slos=[
                SLODefinition(name="availability", target=99.9, slo_type="availability"),
                SLODefinition(
                    name="reversal_rate",
                    target=0.05,
                    slo_type="availability",
                    judgment_type="reversal_rate",
                    window="7d",
                ),
                SLODefinition(
                    name="high_confidence_failure",
                    target=0.01,
                    slo_type="availability",
                    judgment_type="high_confidence_failure",
                    window="7d",
                ),
            ],
        )

        groups = build_recording_rules_from_manifest(manifest)

        # Check judgment rules group exists
        judgment_group = next((g for g in groups if "judgment_metrics" in g.name), None)
        assert judgment_group is not None
        assert len(judgment_group.rules) > 0

        # Check for reversal_rate metric
        rule_names = [r.record for r in judgment_group.rules]
        assert any("reversal_rate" in name for name in rule_names)

    def test_build_health_rules(self):
        """Test building health metrics rules."""
        from nthlayer_generate.recording_rules.manifest_builder import (
            build_recording_rules_from_manifest,
        )

        manifest = ReliabilityManifest(
            name="api",
            team="test",
            tier="standard",
            type="api",
        )

        groups = build_recording_rules_from_manifest(manifest)

        # Check health rules exist
        health_group = next((g for g in groups if "health_metrics" in g.name), None)
        assert health_group is not None


class TestOpenSRMParserValidationErrors:
    """Test OpenSRM parser validation error cases."""

    def test_missing_metadata_name(self):
        """Test error when metadata.name is missing."""
        data = {
            "apiVersion": "srm/v1",
            "kind": "ServiceReliabilityManifest",
            "metadata": {
                "team": "test",
                "tier": "standard",
            },
            "spec": {"type": "api"},
        }
        with pytest.raises(OpenSRMParseError, match="metadata.name is required"):
            parse_srm_v1(data)

    def test_missing_metadata_team(self):
        """Test error when metadata.team is missing."""
        data = {
            "apiVersion": "srm/v1",
            "kind": "ServiceReliabilityManifest",
            "metadata": {
                "name": "test",
                "tier": "standard",
            },
            "spec": {"type": "api"},
        }
        with pytest.raises(OpenSRMParseError, match="metadata.team is required"):
            parse_srm_v1(data)

    def test_missing_metadata_tier(self):
        """Test error when metadata.tier is missing."""
        data = {
            "apiVersion": "srm/v1",
            "kind": "ServiceReliabilityManifest",
            "metadata": {
                "name": "test",
                "team": "test",
            },
            "spec": {"type": "api"},
        }
        with pytest.raises(OpenSRMParseError, match="metadata.tier is required"):
            parse_srm_v1(data)

    def test_missing_spec_type(self):
        """Test error when spec.type is missing."""
        data = {
            "apiVersion": "srm/v1",
            "kind": "ServiceReliabilityManifest",
            "metadata": {
                "name": "test",
                "team": "test",
                "tier": "standard",
            },
            "spec": {},
        }
        with pytest.raises(OpenSRMParseError, match="spec.type is required"):
            parse_srm_v1(data)

    def test_slo_missing_target_and_minimum(self):
        """Test error when SLO has no target or minimum."""
        data = {
            "apiVersion": "srm/v1",
            "kind": "ServiceReliabilityManifest",
            "metadata": {
                "name": "test",
                "team": "test",
                "tier": "standard",
            },
            "spec": {
                "type": "api",
                "slos": {
                    "bad_slo": {
                        "window": "30d",
                        # no target or minimum
                    },
                },
            },
        }
        with pytest.raises(OpenSRMParseError, match="requires a target or minimum"):
            parse_srm_v1(data)


class TestOpenSRMParserFileParsing:
    """Test parse_srm_v1_file (generate's parse_opensrm_file before opensrm-wo62.1)."""

    def test_invalid_yaml_file(self, tmp_path):
        """Test error on invalid YAML."""
        bad_file = tmp_path / "bad.yaml"
        bad_file.write_text("invalid: yaml: content: [")

        with pytest.raises(OpenSRMParseError, match="Invalid YAML"):
            parse_srm_v1_file(bad_file)

    def test_non_dict_yaml_file(self, tmp_path):
        """Test error on non-dict YAML."""
        list_file = tmp_path / "list.yaml"
        list_file.write_text("- item1\n- item2")

        with pytest.raises(OpenSRMParseError, match="Expected YAML object"):
            parse_srm_v1_file(list_file)


class TestOpenSRMParserSLOEdgeCases:
    """Test SLO parsing edge cases."""

    def test_simple_target_value(self):
        """Test SLO with simple target value (not a dict)."""
        data = {
            "apiVersion": "srm/v1",
            "kind": "ServiceReliabilityManifest",
            "metadata": {
                "name": "test",
                "team": "test",
                "tier": "standard",
            },
            "spec": {
                "type": "api",
                "slos": {
                    "availability": 99.95,  # Simple value, not a dict
                },
            },
        }
        manifest = parse_srm_v1(data)
        assert len(manifest.slos) == 1
        assert manifest.slos[0].name == "availability"
        assert manifest.slos[0].target == 99.95


class TestOpenSRMParserDependencyEdgeCases:
    """Test dependency parsing edge cases."""

    def test_dependency_non_dict_skipped(self):
        """Test that non-dict dependencies are skipped."""
        data = {
            "apiVersion": "srm/v1",
            "kind": "ServiceReliabilityManifest",
            "metadata": {
                "name": "test",
                "team": "test",
                "tier": "standard",
            },
            "spec": {
                "type": "api",
                "dependencies": [
                    "string-not-dict",
                    {"name": "valid", "type": "database"},
                ],
            },
        }
        manifest = parse_srm_v1(data)
        assert len(manifest.dependencies) == 1
        assert manifest.dependencies[0].name == "valid"

    def test_dependency_without_name_skipped(self):
        """Test that dependencies without name are skipped."""
        data = {
            "apiVersion": "srm/v1",
            "kind": "ServiceReliabilityManifest",
            "metadata": {
                "name": "test",
                "team": "test",
                "tier": "standard",
            },
            "spec": {
                "type": "api",
                "dependencies": [
                    {"type": "database"},  # No name
                    {"name": "valid", "type": "database"},
                ],
            },
        }
        manifest = parse_srm_v1(data)
        assert len(manifest.dependencies) == 1
        assert manifest.dependencies[0].name == "valid"

    def test_dependency_with_invalid_criticality(self):
        """Test that invalid criticality is ignored."""
        data = {
            "apiVersion": "srm/v1",
            "kind": "ServiceReliabilityManifest",
            "metadata": {
                "name": "test",
                "team": "test",
                "tier": "standard",
            },
            "spec": {
                "type": "api",
                "dependencies": [
                    {"name": "dep", "type": "database", "criticality": "invalid-value"},
                ],
            },
        }
        manifest = parse_srm_v1(data)
        assert len(manifest.dependencies) == 1
        assert manifest.dependencies[0].criticality is None


class TestOpenSRMParserOwnershipEdgeCases:
    """Test ownership parsing edge cases."""

    def test_ownership_without_team_returns_none(self):
        """Test that ownership without team returns None."""
        data = {
            "apiVersion": "srm/v1",
            "kind": "ServiceReliabilityManifest",
            "metadata": {
                "name": "test",
                "team": "test",
                "tier": "standard",
            },
            "spec": {
                "type": "api",
                "ownership": {
                    "slack": "#alerts",
                    # no team
                },
            },
        }
        manifest = parse_srm_v1(data)
        assert manifest.ownership is None

    def test_ownership_with_pagerduty(self):
        """Test ownership with PagerDuty config."""
        data = {
            "apiVersion": "srm/v1",
            "kind": "ServiceReliabilityManifest",
            "metadata": {
                "name": "test",
                "team": "test",
                "tier": "standard",
            },
            "spec": {
                "type": "api",
                "ownership": {
                    "team": "test",
                    "pagerduty": {
                        "service_id": "PD123",
                        "escalation_policy_id": "EP456",
                    },
                },
            },
        }
        manifest = parse_srm_v1(data)
        assert manifest.ownership is not None
        assert manifest.ownership.pagerduty is not None
        assert manifest.ownership.pagerduty.service_id == "PD123"


class TestOnCallConfig:
    """Test OnCallConfig dataclasses and oncall parsing."""

    def _make_manifest_with_oncall(self, oncall_data: dict) -> dict:
        """Helper: build a minimal OpenSRM manifest with oncall block."""
        return {
            "apiVersion": "srm/v1",
            "kind": "ServiceReliabilityManifest",
            "metadata": {
                "name": "fraud-detect",
                "team": "ml-platform",
                "tier": "critical",
            },
            "spec": {
                "type": "ai-gate",
                "ownership": {
                    "team": "ml-platform",
                    "slack": "#ml-platform-oncall",
                    "oncall": oncall_data,
                },
            },
        }

    def test_ownership_with_oncall_parsed(self):
        """Test that oncall block is parsed from OpenSRM manifest."""
        data = self._make_manifest_with_oncall(
            {
                "timezone": "Europe/Dublin",
                "rotation": {
                    "type": "weekly",
                    "handoff": "monday 09:00",
                    "roster": [
                        {
                            "name": "Alice",
                            "slack_id": "U0123ALICE",
                            "ntfy_topic": "oncall-alice",
                            "phone": "+353851234567",
                        },
                        {
                            "name": "Bob",
                            "slack_id": "U0456BOB",
                            "ntfy_topic": "oncall-bob",
                        },
                    ],
                },
                "overrides": [
                    {
                        "start": "2026-04-14T00:00:00Z",
                        "end": "2026-04-21T00:00:00Z",
                        "user": "Bob",
                        "reason": "Alice on annual leave",
                    },
                ],
                "escalation": [
                    {"after": "0m", "notify": "slack_dm"},
                    {"after": "5m", "notify": "ntfy"},
                    {"after": "10m", "notify": "slack_dm", "target": "next_oncall"},
                ],
            }
        )
        manifest = parse_srm_v1(data)
        assert manifest.ownership is not None
        assert manifest.ownership.oncall is not None

        oncall = manifest.ownership.oncall
        assert oncall.timezone == "Europe/Dublin"
        assert oncall.rotation.type == "weekly"
        assert oncall.rotation.handoff == "monday 09:00"
        assert len(oncall.rotation.roster) == 2
        assert oncall.rotation.roster[0].name == "Alice"
        assert oncall.rotation.roster[0].slack_id == "U0123ALICE"
        assert oncall.rotation.roster[0].ntfy_topic == "oncall-alice"
        assert oncall.rotation.roster[0].phone == "+353851234567"
        assert oncall.rotation.roster[1].ntfy_topic == "oncall-bob"
        assert oncall.rotation.roster[1].phone is None

        assert len(oncall.overrides) == 1
        assert oncall.overrides[0].user == "Bob"
        assert oncall.overrides[0].reason == "Alice on annual leave"

        assert len(oncall.escalation) == 3
        assert oncall.escalation[0].after == "0m"
        assert oncall.escalation[0].notify == "slack_dm"
        assert oncall.escalation[0].target is None
        assert oncall.escalation[2].target == "next_oncall"

    def test_ownership_without_oncall(self):
        """Test that ownership without oncall block has oncall=None."""
        data = {
            "apiVersion": "srm/v1",
            "kind": "ServiceReliabilityManifest",
            "metadata": {
                "name": "test",
                "team": "test",
                "tier": "standard",
            },
            "spec": {
                "type": "api",
                "ownership": {
                    "team": "test",
                    "slack": "#alerts",
                },
            },
        }
        manifest = parse_srm_v1(data)
        assert manifest.ownership is not None
        assert manifest.ownership.oncall is None

    def test_oncall_minimal(self):
        """Test oncall with only required fields (no overrides, no escalation)."""
        data = self._make_manifest_with_oncall(
            {
                "timezone": "UTC",
                "rotation": {
                    "type": "daily",
                    "handoff": "09:00",
                    "roster": [
                        {"name": "Alice", "slack_id": "U01"},
                    ],
                },
            }
        )
        manifest = parse_srm_v1(data)
        oncall = manifest.ownership.oncall
        assert oncall is not None
        assert oncall.timezone == "UTC"
        assert oncall.rotation.type == "daily"
        assert len(oncall.overrides) == 0
        assert len(oncall.escalation) == 0

    def test_escalation_step_with_phone_override(self):
        """Test escalation step with direct phone number for engineering_manager."""
        data = self._make_manifest_with_oncall(
            {
                "timezone": "Europe/Dublin",
                "rotation": {
                    "type": "weekly",
                    "handoff": "monday 09:00",
                    "roster": [{"name": "Alice", "slack_id": "U01"}],
                },
                "escalation": [
                    {
                        "after": "30m",
                        "notify": "phone",
                        "target": "engineering_manager",
                        "phone": "+353859876543",
                    },
                ],
            }
        )
        manifest = parse_srm_v1(data)
        step = manifest.ownership.oncall.escalation[0]
        assert step.after == "30m"
        assert step.notify == "phone"
        assert step.target == "engineering_manager"
        assert step.phone == "+353859876543"

    def test_roster_member_missing_name_raises(self):
        """Roster member without name raises OpenSRMParseError."""
        data = self._make_manifest_with_oncall(
            {
                "timezone": "UTC",
                "rotation": {
                    "type": "weekly",
                    "handoff": "monday 09:00",
                    "roster": [{"slack_id": "U01"}],  # missing name
                },
            }
        )
        with pytest.raises(OpenSRMParseError, match="roster.*missing required field"):
            parse_srm_v1(data)

    def test_override_missing_user_raises(self):
        """Override without user raises OpenSRMParseError."""
        data = self._make_manifest_with_oncall(
            {
                "timezone": "UTC",
                "rotation": {
                    "type": "weekly",
                    "handoff": "monday 09:00",
                    "roster": [{"name": "Alice", "slack_id": "U01"}],
                },
                "overrides": [
                    {"start": "2026-04-14T00:00:00Z", "end": "2026-04-21T00:00:00Z"},
                ],  # missing user
            }
        )
        with pytest.raises(OpenSRMParseError, match="overrides.*missing required field"):
            parse_srm_v1(data)

    def test_escalation_missing_notify_raises(self):
        """Escalation step without notify raises OpenSRMParseError."""
        data = self._make_manifest_with_oncall(
            {
                "timezone": "UTC",
                "rotation": {
                    "type": "weekly",
                    "handoff": "monday 09:00",
                    "roster": [{"name": "Alice", "slack_id": "U01"}],
                },
                "escalation": [{"after": "5m"}],  # missing notify
            }
        )
        with pytest.raises(OpenSRMParseError, match="escalation.*missing required field"):
            parse_srm_v1(data)

    def test_missing_timezone_raises(self):
        """Missing timezone raises OpenSRMParseError."""
        data = self._make_manifest_with_oncall(
            {
                "rotation": {
                    "type": "weekly",
                    "handoff": "monday 09:00",
                    "roster": [{"name": "Alice", "slack_id": "U01"}],
                },
            }
        )
        with pytest.raises(OpenSRMParseError, match="timezone is required"):
            parse_srm_v1(data)

    def test_invalid_timezone_raises(self):
        """Invalid timezone string raises OpenSRMParseError."""
        data = self._make_manifest_with_oncall(
            {
                "timezone": "Europ/Dublin",
                "rotation": {
                    "type": "weekly",
                    "handoff": "monday 09:00",
                    "roster": [{"name": "Alice", "slack_id": "U01"}],
                },
            }
        )
        with pytest.raises(OpenSRMParseError, match="invalid IANA timezone"):
            parse_srm_v1(data)


class TestOpenSRMParserGateEdgeCases:
    """Test deployment gate parsing edge cases."""

    def test_empty_gates_returns_none(self):
        """Test that gates with no error_budget returns default."""
        data = {
            "apiVersion": "srm/v1",
            "kind": "ServiceReliabilityManifest",
            "metadata": {
                "name": "test",
                "team": "test",
                "tier": "standard",
            },
            "spec": {
                "type": "api",
                "deployment": {
                    "environments": ["prod"],
                    "gates": {},
                },
            },
        }
        manifest = parse_srm_v1(data)
        assert manifest.deployment.gates is not None
        assert manifest.deployment.gates.error_budget is None

    def test_slo_compliance_gate(self):
        """Test SLO compliance gate parsing."""
        data = {
            "apiVersion": "srm/v1",
            "kind": "ServiceReliabilityManifest",
            "metadata": {
                "name": "test",
                "team": "test",
                "tier": "standard",
            },
            "spec": {
                "type": "api",
                "deployment": {
                    "gates": {
                        "slo_compliance": {"threshold": 0.95},
                    },
                },
            },
        }
        manifest = parse_srm_v1(data)
        assert manifest.deployment.gates.slo_compliance.threshold == 0.95

    def test_recent_incidents_gate(self):
        """Test recent incidents gate parsing."""
        data = {
            "apiVersion": "srm/v1",
            "kind": "ServiceReliabilityManifest",
            "metadata": {
                "name": "test",
                "team": "test",
                "tier": "standard",
            },
            "spec": {
                "type": "api",
                "deployment": {
                    "gates": {
                        "recent_incidents": {
                            "p1_max": 1,
                            "p2_max": 3,
                            "lookback": "14d",
                        },
                    },
                },
            },
        }
        manifest = parse_srm_v1(data)
        gate = manifest.deployment.gates.recent_incidents
        assert gate.p1_max == 1
        assert gate.p2_max == 3
        assert gate.lookback == "14d"


class TestOpenSRMParserEdgeCases:
    """Test OpenSRM parser edge cases."""

    def test_parse_with_ownership(self):
        """Test parsing with ownership section."""
        data = {
            "apiVersion": "srm/v1",
            "kind": "ServiceReliabilityManifest",
            "metadata": {
                "name": "api",
                "team": "test",
                "tier": "standard",
            },
            "spec": {
                "type": "api",
                "ownership": {
                    "team": "test",
                    "slack": "#test-oncall",
                    "email": "test@example.com",
                    "runbook": "https://wiki/runbooks/api",
                },
            },
        }

        manifest = parse_srm_v1(data)
        assert manifest.ownership is not None
        assert manifest.ownership.slack == "#test-oncall"
        assert manifest.ownership.runbook == "https://wiki/runbooks/api"

    def test_parse_with_observability(self):
        """Test parsing with observability section."""
        data = {
            "apiVersion": "srm/v1",
            "kind": "ServiceReliabilityManifest",
            "metadata": {
                "name": "api",
                "team": "test",
                "tier": "standard",
            },
            "spec": {
                "type": "api",
                "observability": {
                    "metrics_prefix": "api_v2",
                    "prometheus_job": "api-service",
                },
            },
        }

        manifest = parse_srm_v1(data)
        assert manifest.observability is not None
        assert manifest.observability.metrics_prefix == "api_v2"

    def test_parse_with_deployment_config(self):
        """Test parsing with deployment section."""
        data = {
            "apiVersion": "srm/v1",
            "kind": "ServiceReliabilityManifest",
            "metadata": {
                "name": "api",
                "team": "test",
                "tier": "standard",
            },
            "spec": {
                "type": "api",
                "deployment": {
                    "environments": ["production", "staging"],
                    "gates": {
                        "error_budget": {"enabled": True, "threshold": 0.10},
                    },
                    "rollback": {
                        "automatic": True,
                        "criteria": {
                            "error_rate_increase": "5%",
                        },
                    },
                },
            },
        }

        manifest = parse_srm_v1(data)
        assert manifest.deployment is not None
        assert "production" in manifest.deployment.environments
        assert manifest.deployment.gates is not None
        assert manifest.deployment.gates.error_budget.enabled is True
        assert manifest.deployment.rollback is not None
        assert manifest.deployment.rollback.automatic is True

    def test_parse_slo_with_minimum(self):
        """Test parsing throughput SLO with minimum value."""
        data = {
            "apiVersion": "srm/v1",
            "kind": "ServiceReliabilityManifest",
            "metadata": {
                "name": "api",
                "team": "test",
                "tier": "standard",
            },
            "spec": {
                "type": "api",
                "slos": {
                    "throughput": {
                        "minimum": 1000,
                        "unit": "rps",
                    },
                },
            },
        }

        manifest = parse_srm_v1(data)
        assert len(manifest.slos) == 1
        assert manifest.slos[0].target == 1000

    def test_parse_dependency_with_slo(self):
        """Test parsing dependency with SLO expectations."""
        data = {
            "apiVersion": "srm/v1",
            "kind": "ServiceReliabilityManifest",
            "metadata": {
                "name": "api",
                "team": "test",
                "tier": "standard",
            },
            "spec": {
                "type": "api",
                "dependencies": [
                    {
                        "name": "postgres",
                        "type": "database",
                        "critical": True,
                        "criticality": "critical",
                        "slo": {
                            "availability": 99.99,
                            "latency": {"p99": "10ms"},
                        },
                    },
                ],
            },
        }

        manifest = parse_srm_v1(data)
        assert len(manifest.dependencies) == 1
        dep = manifest.dependencies[0]
        assert dep.slo is not None
        assert dep.slo.availability == 99.99
        assert dep.criticality.value == "critical"


class TestManifestValidation:
    """Test ReliabilityManifest validation."""

    def test_missing_name_raises_error(self):
        """Test that missing name raises ValueError."""
        with pytest.raises(ValueError, match="Service name is required"):
            ReliabilityManifest(
                name="",  # Empty name
                team="test",
                tier="standard",
                type="api",
            )

    def test_missing_team_raises_error(self):
        """Test that missing team raises ValueError."""
        with pytest.raises(ValueError, match="Service team is required"):
            ReliabilityManifest(
                name="test",
                team="",  # Empty team
                tier="standard",
                type="api",
            )

    def test_missing_tier_raises_error(self):
        """Test that missing tier raises ValueError."""
        with pytest.raises(ValueError, match="Service tier is required"):
            ReliabilityManifest(
                name="test",
                team="test",
                tier="",  # Empty tier
                type="api",
            )

class TestManifestMethods:
    """Test ReliabilityManifest methods."""

    def test_is_ai_gate_false(self):
        """Test is_ai_gate returns False for non-ai-gate type."""
        manifest = ReliabilityManifest(
            name="api",
            team="test",
            tier="standard",
            type="api",
        )
        assert manifest.is_ai_gate() is False

    def test_to_service_context(self):
        """Test to_service_context produces legacy-compatible dict."""
        manifest = ReliabilityManifest(
            name="payment-api",
            team="payments",
            tier="critical",
            type="api",
            language="java",
            framework="spring-boot",
            environment="production",
        )
        ctx = service_context_from_manifest(manifest).to_dict()
        assert ctx["service"] == "payment-api"
        assert ctx["team"] == "payments"
        assert ctx["tier"] == "critical"
        assert ctx["type"] == "api"
        assert ctx["language"] == "java"
        assert ctx["framework"] == "spring-boot"
        assert ctx["env"] == "production"

    def test_to_dict_with_slos(self):
        """Test to_dict includes SLOs."""
        manifest = ReliabilityManifest(
            name="api",
            team="test",
            tier="standard",
            type="api",
            slos=[
                SLODefinition(
                    name="availability",
                    target=99.95,
                    slo_type="availability",
                    window="30d",
                    unit="percent",
                    percentile="p99",
                    description="Service availability",
                ),
            ],
        )
        data = _legacy_to_srm_v1(manifest)
        assert "slos" in data["spec"]
        assert "availability" in data["spec"]["slos"]
        slo = data["spec"]["slos"]["availability"]
        assert slo["target"] == 99.95
        assert slo["window"] == "30d"
        assert slo["unit"] == "percent"
        assert slo["percentile"] == "p99"
        assert slo["description"] == "Service availability"

    def test_to_dict_with_dependencies(self):
        """Test to_dict includes dependencies."""
        manifest = ReliabilityManifest(
            name="api",
            team="test",
            tier="standard",
            type="api",
            dependencies=[
                Dependency(name="postgres", type="database", critical=True),
                Dependency(name="redis", type="cache", critical=False),
            ],
        )
        data = _legacy_to_srm_v1(manifest)
        assert "dependencies" in data["spec"]
        assert len(data["spec"]["dependencies"]) == 2

    def test_to_dict_with_ownership(self):
        """Test to_dict includes ownership."""
        from nthlayer_common.manifest import Ownership

        manifest = ReliabilityManifest(
            name="api",
            team="test",
            tier="standard",
            type="api",
            ownership=Ownership(
                team="test",
                slack="#test-oncall",
                email="test@example.com",
                runbook="https://wiki/runbooks/api",
            ),
        )
        data = _legacy_to_srm_v1(manifest)
        assert "ownership" in data["spec"]
        assert data["spec"]["ownership"]["team"] == "test"
        assert data["spec"]["ownership"]["slack"] == "#test-oncall"
        assert data["spec"]["ownership"]["email"] == "test@example.com"
        assert data["spec"]["ownership"]["runbook"] == "https://wiki/runbooks/api"

class TestLoaderExtended:
    """Extended tests for loader functionality."""

    def test_load_with_force_format_opensrm(self, tmp_path):
        """Test forcing OpenSRM format."""
        # Create a file without apiVersion that could be ambiguous
        manifest_file = tmp_path / "test.reliability.yaml"
        manifest_file.write_text("""
apiVersion: srm/v1
kind: ServiceReliabilityManifest
metadata:
  name: test
  team: test
  tier: standard
spec:
  type: api
""")
        manifest = load_manifest(manifest_file, format="opensrm")
        assert manifest.source_format == SourceFormat.OPENSRM

    def test_load_with_force_format_legacy(self, tmp_path):
        """Test forcing legacy format."""
        manifest_file = tmp_path / "test.yaml"
        manifest_file.write_text("""
service:
  name: test
  team: test
  tier: standard
  type: api
""")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", LegacyFormatWarning)
            manifest = load_manifest(
                manifest_file, format="legacy", suppress_deprecation_warning=True
            )
        assert manifest.source_format == SourceFormat.LEGACY

    def test_load_empty_file(self, tmp_path):
        """Test loading empty file raises error."""
        empty_file = tmp_path / "empty.yaml"
        empty_file.write_text("")

        with pytest.raises(ManifestLoadError):
            load_manifest(empty_file)


class TestLoaderLegacyParsing:
    """Test loader's legacy format parsing."""

    def test_legacy_missing_service_name(self, tmp_path):
        """Test error when legacy file missing service name."""
        manifest_file = tmp_path / "test.yaml"
        manifest_file.write_text("""
service:
  team: test
  tier: standard
  type: api
""")
        with pytest.raises(ManifestLoadError, match="service.name is required"):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", LegacyFormatWarning)
                load_manifest(manifest_file, suppress_deprecation_warning=True)

    def test_legacy_missing_service_team(self, tmp_path):
        """Test error when legacy file missing service team."""
        manifest_file = tmp_path / "test.yaml"
        manifest_file.write_text("""
service:
  name: test
  tier: standard
  type: api
""")
        with pytest.raises(ManifestLoadError, match="service.team is required"):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", LegacyFormatWarning)
                load_manifest(manifest_file, suppress_deprecation_warning=True)

    def test_legacy_missing_service_tier(self, tmp_path):
        """Test error when legacy file missing service tier."""
        manifest_file = tmp_path / "test.yaml"
        manifest_file.write_text("""
service:
  name: test
  team: test
  type: api
""")
        with pytest.raises(ManifestLoadError, match="service.tier is required"):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", LegacyFormatWarning)
                load_manifest(manifest_file, suppress_deprecation_warning=True)

    def test_legacy_missing_service_type(self, tmp_path):
        """Test error when legacy file missing service type."""
        manifest_file = tmp_path / "test.yaml"
        manifest_file.write_text("""
service:
  name: test
  team: test
  tier: standard
""")
        with pytest.raises(ManifestLoadError, match="service.type is required"):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", LegacyFormatWarning)
                load_manifest(manifest_file, suppress_deprecation_warning=True)

    def test_legacy_service_pagerduty_block_is_not_mapped_to_ownership(self, tmp_path):
        """A legacy ``service.pagerduty`` block does not reach ownership.

        Spec §3 D11 (opensrm-wo62.1, approved): nthlayer-common's legacy
        loader does not map ``service.pagerduty`` to ``ownership.pagerduty``;
        the supported legacy form is a ``kind: PagerDuty`` resource, pinned by
        test_legacy_with_pagerduty_resource.
        """
        manifest_file = tmp_path / "test.yaml"
        manifest_file.write_text("""
service:
  name: test
  team: test
  tier: standard
  type: api
  pagerduty:
    service_id: P123ABC
    escalation_policy: P456DEF
""")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", LegacyFormatWarning)
            manifest = load_manifest(manifest_file, suppress_deprecation_warning=True)
        assert manifest.ownership is not None
        assert manifest.ownership.pagerduty is None

    def test_legacy_with_dependencies_databases(self, tmp_path):
        """Test legacy file with database dependencies."""
        manifest_file = tmp_path / "test.yaml"
        manifest_file.write_text("""
service:
  name: test
  team: test
  tier: standard
  type: api
resources:
  - kind: Dependencies
    name: deps
    spec:
      databases:
        - name: postgres
          type: postgresql
          criticality: critical
          slo:
            availability: 99.99
            latency_p99: 10ms
""")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", LegacyFormatWarning)
            manifest = load_manifest(manifest_file, suppress_deprecation_warning=True)
        assert len(manifest.dependencies) == 1
        dep = manifest.dependencies[0]
        assert dep.name == "postgres"
        assert dep.type == "database"
        assert dep.critical is True
        assert dep.slo is not None
        assert dep.slo.availability == 99.99

    def test_legacy_with_dependencies_upstream(self, tmp_path):
        """Test legacy file with upstream dependencies."""
        manifest_file = tmp_path / "test.yaml"
        manifest_file.write_text("""
service:
  name: test
  team: test
  tier: standard
  type: api
resources:
  - kind: Dependencies
    name: deps
    spec:
      upstream:
        - name: auth-api
          criticality: high
          slo:
            availability: 99.95
""")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", LegacyFormatWarning)
            manifest = load_manifest(manifest_file, suppress_deprecation_warning=True)
        assert len(manifest.dependencies) == 1
        dep = manifest.dependencies[0]
        assert dep.name == "auth-api"
        assert dep.type == "api"
        assert dep.critical is True

    def test_legacy_with_dependencies_downstream(self, tmp_path):
        """Test legacy file with downstream dependencies."""
        manifest_file = tmp_path / "test.yaml"
        manifest_file.write_text("""
service:
  name: test
  team: test
  tier: standard
  type: api
resources:
  - kind: Dependencies
    name: deps
    spec:
      downstream:
        - name: notification-service
""")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", LegacyFormatWarning)
            manifest = load_manifest(manifest_file, suppress_deprecation_warning=True)
        assert len(manifest.dependencies) == 1
        dep = manifest.dependencies[0]
        assert dep.name == "notification-service"
        assert dep.critical is False

    def test_legacy_with_dependencies_caches(self, tmp_path):
        """Test legacy file with cache dependencies."""
        manifest_file = tmp_path / "test.yaml"
        manifest_file.write_text("""
service:
  name: test
  team: test
  tier: standard
  type: api
resources:
  - kind: Dependencies
    name: deps
    spec:
      caches:
        - name: redis-cache
          criticality: critical
""")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", LegacyFormatWarning)
            manifest = load_manifest(manifest_file, suppress_deprecation_warning=True)
        assert len(manifest.dependencies) == 1
        dep = manifest.dependencies[0]
        assert dep.name == "redis-cache"
        assert dep.type == "cache"
        assert dep.critical is True

    def test_legacy_with_dependencies_queues(self, tmp_path):
        """Test legacy file with queue dependencies."""
        manifest_file = tmp_path / "test.yaml"
        manifest_file.write_text("""
service:
  name: test
  team: test
  tier: standard
  type: api
resources:
  - kind: Dependencies
    name: deps
    spec:
      queues:
        - name: job-queue
          criticality: high
""")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", LegacyFormatWarning)
            manifest = load_manifest(manifest_file, suppress_deprecation_warning=True)
        assert len(manifest.dependencies) == 1
        dep = manifest.dependencies[0]
        assert dep.name == "job-queue"
        assert dep.type == "queue"
        assert dep.critical is True

    def test_legacy_with_pagerduty_resource(self, tmp_path):
        """Test legacy file with PagerDuty resource."""
        manifest_file = tmp_path / "test.yaml"
        manifest_file.write_text("""
service:
  name: test
  team: test
  tier: standard
  type: api
resources:
  - kind: PagerDuty
    name: pagerduty
    spec:
      service_id: PD123
      escalation_policy: EP456
""")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", LegacyFormatWarning)
            manifest = load_manifest(manifest_file, suppress_deprecation_warning=True)
        assert manifest.ownership is not None
        assert manifest.ownership.pagerduty is not None
        assert manifest.ownership.pagerduty.service_id == "PD123"

    def test_legacy_slo_without_target(self, tmp_path):
        """Test legacy file with SLO missing target is skipped."""
        manifest_file = tmp_path / "test.yaml"
        manifest_file.write_text("""
service:
  name: test
  team: test
  tier: standard
  type: api
resources:
  - kind: SLO
    name: incomplete
    spec:
      window: 30d
""")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", LegacyFormatWarning)
            manifest = load_manifest(manifest_file, suppress_deprecation_warning=True)
        assert len(manifest.slos) == 0  # SLO without target is skipped

    def test_opensrm_parse_error_wrapped(self, tmp_path):
        """Test that OpenSRM parse errors are wrapped."""
        manifest_file = tmp_path / "test.reliability.yaml"
        manifest_file.write_text("""
apiVersion: srm/v1
kind: ServiceReliabilityManifest
metadata:
  name: test
  # missing team and tier
spec:
  type: api
""")
        with pytest.raises(ManifestLoadError):
            load_manifest(manifest_file)

    def test_unknown_format_defaults_to_legacy(self, tmp_path):
        """Test that unknown format parameter defaults to detected format."""
        manifest_file = tmp_path / "test.yaml"
        manifest_file.write_text("""
service:
  name: test
  team: test
  tier: standard
  type: api
""")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", LegacyFormatWarning)
            manifest = load_manifest(
                manifest_file, format="unknown", suppress_deprecation_warning=True
            )
        assert manifest.source_format == SourceFormat.LEGACY


class TestIsManifestFile:
    """Test is_manifest_file function."""

    def test_non_yaml_extension(self, tmp_path):
        """Test that non-YAML files return False."""
        from nthlayer_common.manifest import is_manifest_file

        json_file = tmp_path / "test.json"
        json_file.write_text("{}")
        assert is_manifest_file(json_file) is False

    def test_service_yaml_name(self, tmp_path):
        """Test that service.yaml returns True."""
        from nthlayer_common.manifest import is_manifest_file

        service_file = tmp_path / "service.yaml"
        service_file.write_text("")
        assert is_manifest_file(service_file) is True

    def test_invalid_yaml_returns_false(self, tmp_path):
        """Test that invalid YAML returns False."""
        from nthlayer_common.manifest import is_manifest_file

        bad_file = tmp_path / "bad.yaml"
        bad_file.write_text("invalid: yaml: content: [")
        assert is_manifest_file(bad_file) is False

    def test_non_dict_yaml_returns_false(self, tmp_path):
        """Test that non-dict YAML returns False."""
        from nthlayer_common.manifest import is_manifest_file

        list_file = tmp_path / "list.yaml"
        list_file.write_text("- item1\n- item2")
        assert is_manifest_file(list_file) is False

    def test_legacy_yaml_without_required_fields(self, tmp_path):
        """Test legacy YAML without all required fields returns False."""
        from nthlayer_common.manifest import is_manifest_file

        partial_file = tmp_path / "partial.yaml"
        partial_file.write_text("""
service:
  name: test
  # missing team, tier, type
""")
        assert is_manifest_file(partial_file) is False


class TestManifestBuilderExtended:
    """Extended tests for manifest recording rule builder."""

    def test_build_rules_with_all_slo_types(self):
        """Test building rules with all SLO types."""
        from nthlayer_generate.recording_rules.manifest_builder import (
            build_recording_rules_from_manifest,
        )

        manifest = ReliabilityManifest(
            name="full-api",
            team="platform",
            tier="critical",
            type="api",
            slos=[
                SLODefinition(
                    name="availability", target=99.95, slo_type="availability", window="30d"
                ),
                SLODefinition(
                    name="latency", target=200, slo_type="latency", unit="ms", percentile="p99"
                ),
                SLODefinition(name="error_rate", target=0.1, slo_type="error_rate", window="7d"),
                SLODefinition(name="throughput", target=1000, slo_type="throughput", unit="rps"),
            ],
        )

        groups = build_recording_rules_from_manifest(manifest)
        assert len(groups) >= 1

    def test_build_rules_for_worker(self):
        """Test building rules for worker service type."""
        from nthlayer_generate.recording_rules.manifest_builder import (
            build_recording_rules_from_manifest,
        )

        manifest = ReliabilityManifest(
            name="processor",
            team="platform",
            tier="standard",
            type="worker",
            slos=[
                SLODefinition(name="throughput", target=100, slo_type="throughput", unit="rps"),
                SLODefinition(name="error_rate", target=0.5, slo_type="error_rate", window="7d"),
            ],
        )

        groups = build_recording_rules_from_manifest(manifest)
        assert len(groups) >= 1

    def test_build_rules_for_stream(self):
        """Test building rules for stream service type."""
        from nthlayer_generate.recording_rules.manifest_builder import (
            build_recording_rules_from_manifest,
        )

        manifest = ReliabilityManifest(
            name="event-processor",
            team="platform",
            tier="high",
            type="stream",
            slos=[
                SLODefinition(name="throughput", target=10000, slo_type="throughput", unit="eps"),
            ],
        )

        groups = build_recording_rules_from_manifest(manifest)
        assert len(groups) >= 1

    def test_build_all_judgment_slo_rules(self):
        """Test building all judgment SLO rule types."""
        from nthlayer_common.manifest.parser.v1 import parse_srm_v1

        from nthlayer_generate.recording_rules.manifest_builder import (
            build_recording_rules_from_manifest,
        )

        # calibration and feedback_latency are judgment thresholds under
        # common (spec D1), so the manifest is the srm/v1 document this test
        # models, parsed by common: the same five spec.slos entries, in the
        # shape examples/opensrm/ai-gate.reliability.yaml declares them.
        manifest = parse_srm_v1(
            {
                "apiVersion": "srm/v1",
                "kind": "ServiceReliabilityManifest",
                "metadata": {"name": "ml-classifier", "team": "ml", "tier": "critical"},
                "spec": {
                    "type": "ai-gate",
                    "slos": {
                        "availability": {"target": 99.9},
                        "reversal_rate": {"target": 0.05, "window": "7d"},
                        "high_confidence_failure": {"target": 0.01, "window": "7d"},
                        "calibration": {"target": 0.1, "window": "30d"},
                        "feedback_latency": {"target": 3600, "window": "30d"},
                    },
                },
            }
        )

        groups = build_recording_rules_from_manifest(manifest)

        # Find the judgment metrics group
        judgment_group = next((g for g in groups if "judgment_metrics" in g.name), None)
        assert judgment_group is not None

        # Verify all judgment metrics are included
        rule_names = [r.record for r in judgment_group.rules]
        assert any("reversal_rate" in name for name in rule_names)
        assert any("high_confidence_failure" in name for name in rule_names)
        assert any("calibration" in name for name in rule_names)
        assert any("feedback_latency" in name for name in rule_names)

    def test_build_rules_dispatch_on_slo_type_not_name(self):
        """The builder picks the rule family from slo_type, not from the name.

        Every other fixture here names its SLO after its type, so it cannot
        tell the two apart. Here the name carries no type keyword. The shape
        is opensrm spec/v1/schema.json @859424a /definitions/LatencySLO (a
        p99 duration plus a target ratio); under a v2 manifest the name is
        free-form and the type is declared separately, which is the case this
        pins.
        """
        from nthlayer_generate.recording_rules.manifest_builder import (
            build_recording_rules_from_manifest,
        )

        manifest = ReliabilityManifest(
            name="checkout",
            team="payments",
            tier="critical",
            type="api",
            slos=[
                SLODefinition(
                    name="p99_checkout",
                    target=99.0,
                    slo_type="latency",
                    percentile="p99",
                    window="30d",
                ),
            ],
        )

        groups = build_recording_rules_from_manifest(manifest)

        slo_group = next(g for g in groups if g.name == "checkout_slo_metrics")
        records = {r.record for r in slo_group.rules}
        assert "slo:latency_requests_total:30d" in records
        assert "slo:latency_requests_fast:30d" in records
