"""Tests for Prometheus recording rules generation."""

import tempfile
from pathlib import Path

import pytest
import yaml

from nthlayer_generate.recording_rules.models import (
    RecordingRule,
    RecordingRuleGroup,
    create_rule_groups,
)


class TestRecordingRuleModels:
    """Tests for recording rule data models."""

    def test_recording_rule_creation(self):
        """Test creating a recording rule."""
        rule = RecordingRule(
            record="my:metric:rate5m", expr="rate(my_metric_total[5m])", labels={"service": "test"}
        )

        assert rule.record == "my:metric:rate5m"
        assert rule.expr == "rate(my_metric_total[5m])"
        assert rule.labels == {"service": "test"}

    def test_recording_rule_to_dict(self):
        """Test converting recording rule to dict."""
        rule = RecordingRule(
            record="my:metric:rate5m",
            expr="rate(my_metric_total[5m])",
            labels={"service": "test", "env": "prod"},
        )

        result = rule.to_dict()

        assert result["record"] == "my:metric:rate5m"
        assert result["expr"] == "rate(my_metric_total[5m])"
        assert result["labels"] == {"service": "test", "env": "prod"}

    def test_recording_rule_without_labels(self):
        """Test recording rule without labels."""
        rule = RecordingRule(record="my:metric:rate5m", expr="rate(my_metric_total[5m])")

        result = rule.to_dict()

        assert "labels" not in result

    def test_recording_rule_group_creation(self):
        """Test creating a recording rule group."""
        group = RecordingRuleGroup(name="test_group", interval="30s")

        assert group.name == "test_group"
        assert group.interval == "30s"
        assert len(group.rules) == 0

    def test_recording_rule_group_add_rule(self):
        """Test adding rules to a group."""
        group = RecordingRuleGroup(name="test_group")

        rule1 = RecordingRule(record="metric1", expr="expr1")
        rule2 = RecordingRule(record="metric2", expr="expr2")

        group.add_rule(rule1)
        group.add_rule(rule2)

        assert len(group.rules) == 2
        assert group.rules[0] == rule1
        assert group.rules[1] == rule2

    def test_recording_rule_group_to_dict(self):
        """Test converting rule group to dict."""
        group = RecordingRuleGroup(name="test_group", interval="1m")
        group.add_rule(RecordingRule(record="metric1", expr="expr1"))

        result = group.to_dict()

        assert result["name"] == "test_group"
        assert result["interval"] == "1m"
        assert len(result["rules"]) == 1
        assert result["rules"][0]["record"] == "metric1"

    def test_recording_rule_group_to_yaml(self):
        """Test converting rule group to YAML."""
        group = RecordingRuleGroup(name="test_group", interval="30s")
        group.add_rule(
            RecordingRule(
                record="test:metric", expr="sum(rate(metric[5m]))", labels={"service": "test"}
            )
        )

        yaml_str = group.to_yaml()

        # Parse YAML to verify structure
        data = yaml.safe_load(yaml_str)

        assert "groups" in data
        assert len(data["groups"]) == 1
        assert data["groups"][0]["name"] == "test_group"
        assert data["groups"][0]["interval"] == "30s"

    def test_create_rule_groups_multiple(self):
        """Test creating YAML for multiple rule groups."""
        group1 = RecordingRuleGroup(name="group1")
        group1.add_rule(RecordingRule(record="metric1", expr="expr1"))

        group2 = RecordingRuleGroup(name="group2")
        group2.add_rule(RecordingRule(record="metric2", expr="expr2"))

        yaml_str = create_rule_groups([group1, group2])
        data = yaml.safe_load(yaml_str)

        assert len(data["groups"]) == 2
        assert data["groups"][0]["name"] == "group1"
        assert data["groups"][1]["name"] == "group2"


class TestRecordingRulesCommand:
    """Tests for generate-recording-rules CLI command."""

    def test_generates_rules_file(self):
        """Test that command generates recording rules YAML file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            service_file = tmpdir / "test-api.yaml"
            service_file.write_text("""
service:
  name: test-api
  team: platform
  tier: standard
  type: api

resources:
  - kind: SLO
    name: availability
    spec:
      objective: 99.9
      window: 30d
            """)

            output_file = tmpdir / "rules.yaml"

            from nthlayer_generate.cli.recording_rules import generate_recording_rules_command

            result = generate_recording_rules_command(
                str(service_file), output=str(output_file), environment=None, dry_run=False
            )

            assert result == 0
            assert output_file.exists()

            # Verify YAML is valid
            rules_data = yaml.safe_load(output_file.read_text())
            assert "groups" in rules_data
            assert len(rules_data["groups"]) >= 1

    def test_dry_run_doesnt_write_file(self):
        """Test that dry-run mode doesn't create files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            service_file = tmpdir / "test-api.yaml"
            service_file.write_text("""
service:
  name: test-api
  team: platform
  tier: standard
  type: api

resources:
  - kind: SLO
    name: availability
    spec:
      objective: 99.9
            """)

            output_file = tmpdir / "rules.yaml"

            from nthlayer_generate.cli.recording_rules import generate_recording_rules_command

            result = generate_recording_rules_command(
                str(service_file), output=str(output_file), environment=None, dry_run=True
            )

            assert result == 0
            assert not output_file.exists()  # No file in dry-run mode

    def test_environment_aware_rules(self):
        """Test that rules work with environment specs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            service_file = tmpdir / "test-api.yaml"
            service_file.write_text("""
service:
  name: test-api
  team: platform
  tier: standard
  type: api

resources:
  - kind: SLO
    name: availability
    spec:
      objective: 99.9
            """)

            env_dir = tmpdir / "environments"
            env_dir.mkdir()
            (env_dir / "prod.yaml").write_text("""
environment: prod
resources:
  - kind: SLO
    name: availability
    spec:
      objective: 99.99
            """)

            output_file = tmpdir / "rules.yaml"

            from nthlayer_generate.cli.recording_rules import generate_recording_rules_command

            result = generate_recording_rules_command(
                str(service_file), output=str(output_file), environment="prod", dry_run=False
            )

            assert result == 0
            assert output_file.exists()

            # Verify rules were generated
            rules_data = yaml.safe_load(output_file.read_text())
            assert len(rules_data["groups"]) >= 1


# --- manifest path (ported from the legacy builder's tests, opensrm-wo62.4.22) ---

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
# Every shipped legacy and srm/v1 manifest. The count is pinned so a moved
# examples directory fails here instead of leaving the loop empty.
SHIPPED = sorted((EXAMPLES / "services").glob("*.yaml")) + sorted(
    (EXAMPLES / "opensrm").glob("*.reliability.yaml")
)


def _load(path: Path):
    from nthlayer_common.manifest import load_manifest

    return load_manifest(path, suppress_deprecation_warning=True)


def _rules(path: Path):
    from nthlayer_generate.recording_rules import build_recording_rules_from_manifest

    return [r for g in build_recording_rules_from_manifest(_load(path)) for r in g.rules]


def test_shipped_corpus_is_present():
    assert len(SHIPPED) == 23, [p.name for p in SHIPPED]


@pytest.mark.parametrize("path", SHIPPED, ids=lambda p: p.name)
def test_shipped_rules_follow_prometheus_conventions(path: Path):
    """Every record is level:metric:operation style, no edge underscores."""
    rules = _rules(path)
    assert rules, f"{path.name} produced no recording rules"
    for rule in rules:
        assert ":" in rule.record, rule.record
        assert not rule.record.startswith("_"), rule.record
        assert not rule.record.endswith("_"), rule.record


@pytest.mark.parametrize("path", SHIPPED, ids=lambda p: p.name)
def test_shipped_rules_carry_the_service_label(path: Path):
    service = _load(path).name
    rules = _rules(path)
    assert rules, f"{path.name} produced no recording rules"
    for rule in rules:
        assert rule.labels.get("service") == service, (rule.record, rule.labels)


PAYMENT_API = EXAMPLES / "services" / "payment-api.yaml"


def _records_for_slo(path: Path, slo: str) -> set[str]:
    return {r.record for r in _rules(path) if r.labels.get("slo") == slo}


def test_availability_slo_rules():
    # payment-api.yaml declares an availability SLO with a 30d window.
    assert _records_for_slo(PAYMENT_API, "availability") >= {
        "slo:requests_total:30d",
        "slo:requests_success:30d",
        "slo:availability:ratio",
        "slo:error_budget_remaining:ratio",
    }


def test_latency_slo_rules():
    # payment-api.yaml declares latency-p95 (a legacy latency SLO with a
    # threshold, 30d window). Not an srm/v1 example: those write latency as
    # target: <ms>, which the v1 schema rejects (opensrm-jlbm).
    assert _records_for_slo(PAYMENT_API, "latency-p95") >= {
        "slo:latency_requests_total:30d",
        "slo:latency_requests_fast:30d",
        "slo:latency:ratio",
        "slo:http_request_duration_seconds:p95",
        "slo:http_request_duration_seconds:p99",
    }


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
