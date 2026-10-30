"""
Tests for alert generation module.
"""

from pathlib import Path

import pytest

from nthlayer_generate.alerts import AlertRule, AlertTemplateLoader


def test_alert_rule_from_dict():
    """Test parsing alert rule from dict"""
    data = {
        "alert": "PostgresqlDown",
        "expr": "pg_up == 0",
        "for": "0m",
        "labels": {"severity": "critical"},
        "annotations": {"summary": "Postgresql down", "description": "Postgresql instance is down"},
    }

    alert = AlertRule.from_dict(data, technology="postgres", category="databases")

    assert alert.name == "PostgresqlDown"
    assert alert.expr == "pg_up == 0"
    assert alert.severity == "critical"
    assert alert.is_critical()
    assert alert.is_down_alert()


def test_alert_rule_customize():
    """Test customizing alert for a service"""
    alert = AlertRule(
        name="PostgresqlDown",
        expr="pg_up == 0",
        severity="critical",
        summary="DB is down",
        description="Database unavailable",
        technology="postgres",
    )

    customized = alert.customize_for_service(
        service_name="search-api",
        team="platform",
        tier=1,
        notification_channel="pagerduty",
        runbook_url="https://runbooks.example.com",
    )

    assert customized.labels["service"] == "search-api"
    assert customized.labels["team"] == "platform"
    assert customized.labels["tier"] == "1"
    assert customized.annotations["channel"] == "pagerduty"
    assert "runbooks.example.com/search-api/PostgresqlDown" in customized.annotations["runbook"]


def test_alert_rule_customize_with_grafana_url():
    """Test customizing alert with Grafana dashboard URL"""
    alert = AlertRule(
        name="PostgresqlDown",
        expr="pg_up == 0",
        severity="critical",
        technology="postgres",
    )

    customized = alert.customize_for_service(
        service_name="payment-api",
        team="payments",
        tier="critical",
        grafana_url="https://grafana.example.com",
    )

    assert "dashboard" in customized.annotations
    assert customized.annotations["dashboard"] == (
        "https://grafana.example.com/d/payment-api-overview?var-service=payment-api"
    )


def test_alert_rule_customize_grafana_url_trailing_slash():
    """Test that trailing slash in grafana_url is handled correctly"""
    alert = AlertRule(name="TestAlert", expr="up == 0", severity="warning")

    customized = alert.customize_for_service(
        service_name="my-service",
        team="platform",
        tier="standard",
        grafana_url="https://grafana.example.com/",  # trailing slash
    )

    # Should not have double slash
    assert "//d/" not in customized.annotations["dashboard"]
    assert customized.annotations["dashboard"] == (
        "https://grafana.example.com/d/my-service-overview?var-service=my-service"
    )


def test_alert_rule_customize_without_grafana_url():
    """Test that dashboard annotation is not added when grafana_url is empty"""
    alert = AlertRule(name="TestAlert", expr="up == 0", severity="warning")

    customized = alert.customize_for_service(
        service_name="my-service",
        team="platform",
        tier="standard",
    )

    assert "dashboard" not in customized.annotations


def test_alert_rule_to_prometheus():
    """Test converting alert to Prometheus format"""
    alert = AlertRule(
        name="TestAlert",
        expr="up == 0",
        duration="5m",
        severity="warning",
        labels={"env": "prod"},
        annotations={"summary": "Test alert"},
    )

    prometheus_format = alert.to_prometheus()

    assert prometheus_format["alert"] == "TestAlert"
    assert prometheus_format["expr"] == "up == 0"
    assert prometheus_format["for"] == "5m"
    assert prometheus_format["labels"]["env"] == "prod"
    assert prometheus_format["annotations"]["summary"] == "Test alert"


def test_alert_template_loader_postgres():
    """Test loading PostgreSQL alerts"""
    loader = AlertTemplateLoader()
    alerts = loader.load_technology("postgres")

    # Should load at least 10 PostgreSQL alerts
    assert len(alerts) >= 10

    # Check first alert
    assert alerts[0].technology == "postgres"
    assert alerts[0].category == "databases"

    # Should have critical alerts
    critical_alerts = [a for a in alerts if a.is_critical()]
    assert len(critical_alerts) > 0

    # Should have a "Down" alert
    down_alerts = [a for a in alerts if a.is_down_alert()]
    assert len(down_alerts) > 0


def test_filter_by_tier():
    """Test tier-based alert filtering"""
    from nthlayer_generate.alerts import AlertRule
    from nthlayer_generate.generators.alerts import filter_by_tier

    alerts = [
        AlertRule(name="Critical", expr="up==0", severity="critical", technology="postgres"),
        AlertRule(name="Warning", expr="up==1", severity="warning", technology="postgres"),
        AlertRule(name="Info", expr="up==2", severity="info", technology="postgres"),
    ]

    # Critical tier: all alerts
    filtered = filter_by_tier(alerts, "critical")
    assert len(filtered) == 3

    # Standard tier: critical + warning
    filtered = filter_by_tier(alerts, "standard")
    assert len(filtered) == 2
    assert all(a.severity in ["critical", "warning"] for a in filtered)

    # Low tier: only critical
    filtered = filter_by_tier(alerts, "low")
    assert len(filtered) == 1
    assert filtered[0].severity == "critical"


def test_alert_template_loader_caching():
    """Test that loader caches results"""
    loader = AlertTemplateLoader()

    # First load
    alerts1 = loader.load_technology("postgres")

    # Second load (should be cached)
    alerts2 = loader.load_technology("postgres")

    # Should be same objects (cached)
    assert alerts1 is alerts2


def test_alert_template_loader_aliases():
    """Test technology name aliases"""
    loader = AlertTemplateLoader()

    # All these should work (using _ prefix for unused results)
    pg_alerts = loader.load_technology("postgres")
    _postgresql_alerts = loader.load_technology("postgresql")
    _pg_short_alerts = loader.load_technology("pg")

    # Should all return alerts (exact match depends on implementation)
    assert len(pg_alerts) > 0


def test_alert_template_loader_unknown_technology():
    """Test loading unknown technology"""
    loader = AlertTemplateLoader()
    alerts = loader.load_technology("unknown-tech-xyz")

    # Should return empty list, not raise error
    assert alerts == []


@pytest.mark.skip("Requires full template library")
def test_list_available_technologies():
    """Test listing all available technologies"""
    loader = AlertTemplateLoader()
    techs = loader.list_available_technologies()

    # Should include postgres, redis, etc.
    assert "postgres" in techs
    assert len(techs) > 10


# --- Alert Validation Tests ---


class TestPromQLLabelExtraction:
    """Tests for PromQL label extraction from expressions."""

    def test_by_clause_extracts_labels(self):
        """Test that by() clause labels are extracted."""
        from nthlayer_generate.alerts.validator import extract_promql_output_labels

        expr = "sum by (namespace, datname) (pg_stat_database_xact_rollback)"
        labels = extract_promql_output_labels(expr)

        assert labels == {"namespace", "datname"}

    def test_without_clause_marks_removed(self):
        """Test that without() clause marks labels as removed."""
        from nthlayer_generate.alerts.validator import extract_promql_output_labels

        expr = "count without (instance, job) (redis_connected_slaves)"
        labels = extract_promql_output_labels(expr)

        # Should return negative markers for removed labels
        assert labels == {"!instance", "!job"}

    def test_bare_aggregation_returns_empty(self):
        """Test that bare aggregation (no by/without) returns empty set."""
        from nthlayer_generate.alerts.validator import extract_promql_output_labels

        expr = "count(redis_instance_info{role='master'})"
        labels = extract_promql_output_labels(expr)

        assert labels == set()

    def test_no_aggregation_returns_none(self):
        """Test that no aggregation returns None (all labels preserved)."""
        from nthlayer_generate.alerts.validator import extract_promql_output_labels

        expr = "pg_up == 0"
        labels = extract_promql_output_labels(expr)

        assert labels is None

    def test_multiple_by_clauses(self):
        """Test expressions with multiple by() clauses."""
        from nthlayer_generate.alerts.validator import extract_promql_output_labels

        expr = "sum by (a) (x) / sum by (b, c) (y)"
        labels = extract_promql_output_labels(expr)

        assert labels == {"a", "b", "c"}


class TestAnnotationLabelExtraction:
    """Tests for extracting label references from annotations."""

    def test_extracts_label_references(self):
        """Test extraction of {{ $labels.xxx }} patterns."""
        from nthlayer_generate.alerts.validator import extract_annotation_label_refs

        annotations = {
            "summary": "Alert on {{ $labels.instance }}",
            "description": "Service {{ $labels.service }} has {{ $labels.job }} issue",
        }

        labels = extract_annotation_label_refs(annotations)
        assert labels == {"instance", "service", "job"}

    def test_no_labels_returns_empty(self):
        """Test annotations with no label references."""
        from nthlayer_generate.alerts.validator import extract_annotation_label_refs

        annotations = {
            "summary": "Static alert message",
            "description": "Value is {{ $value }}",
        }

        labels = extract_annotation_label_refs(annotations)
        assert labels == set()


class TestAlertValidation:
    """Tests for alert validation and fixing."""

    def test_fixes_invalid_label_reference_by_clause(self):
        """Test fixing invalid label reference when by() removes it."""
        alert = AlertRule(
            name="PostgresqlHighRollbackRate",
            expr="sum by (namespace, datname) (pg_stat_database_xact_rollback) > 0.02",
            duration="0m",
            severity="warning",
            annotations={
                "summary": "High rollback rate (instance {{ $labels.instance }})",
                "description": "Database {{ $labels.datname }} has issues",
            },
            technology="postgres",
        )

        fixed, result = alert.validate_and_fix()

        # Should have issues
        assert not result.is_valid
        assert len(result.issues) > 0
        assert len(result.fixes_applied) > 0

        # instance should be removed, datname should remain
        assert "{{ $labels.instance }}" not in fixed.annotations["summary"]
        assert "{{ $labels.datname }}" in fixed.annotations["description"]

    def test_fixes_invalid_label_reference_without_clause(self):
        """Test fixing invalid label when without() removes it."""
        alert = AlertRule(
            name="RedisDisconnectedSlaves",
            expr="count without (instance, job) (redis_connected_slaves) > 0",
            duration="0m",
            severity="warning",
            annotations={
                "summary": "Redis disconnected (instance {{ $labels.instance }})",
            },
            technology="redis",
        )

        fixed, result = alert.validate_and_fix()

        # Should detect and fix instance label
        assert not result.is_valid
        assert "{{ $labels.instance }}" not in fixed.annotations["summary"]

    def test_fixes_zero_duration(self):
        """Test fixing 'for: 0m' duration."""
        alert = AlertRule(
            name="TestAlert",
            expr="up == 0",
            duration="0m",
            severity="critical",
            annotations={"summary": "Test"},
            technology="postgres",
        )

        fixed, result = alert.validate_and_fix()

        # Should fix duration
        assert "1m" == fixed.duration
        assert any("for" in fix for fix in result.fixes_applied)

    def test_preserves_valid_alert(self):
        """Test that valid alerts are not modified."""
        alert = AlertRule(
            name="PostgresqlDown",
            expr="pg_up == 0",
            duration="5m",
            severity="critical",
            annotations={
                "summary": "Postgresql down (instance {{ $labels.instance }})",
            },
            technology="postgres",
        )

        fixed, result = alert.validate_and_fix()

        # No aggregation = all labels preserved, valid duration
        assert result.is_valid
        assert len(result.fixes_applied) == 0
        assert fixed.annotations == alert.annotations
        assert fixed.duration == alert.duration

    def test_fixes_bare_aggregation_label_refs(self):
        """Test fixing labels when bare aggregation removes all."""
        alert = AlertRule(
            name="RedisMissingMaster",
            expr="count(redis_instance_info{role='master'}) < 1",
            duration="5m",
            severity="critical",
            annotations={
                "summary": "Redis missing master (instance {{ $labels.instance }})",
            },
            technology="redis",
        )

        fixed, result = alert.validate_and_fix()

        # count() removes all labels
        assert not result.is_valid
        assert "{{ $labels.instance }}" not in fixed.annotations["summary"]


class TestAlertRuleFromDictMalformed:
    """Negative-contract tests for malformed alert template dicts."""

    def test_missing_alert_key_raises_key_error(self):
        """Test that missing 'alert' key raises KeyError."""
        data = {"expr": "up == 0", "for": "5m"}
        with pytest.raises(KeyError):
            AlertRule.from_dict(data)

    def test_missing_expr_key_raises_key_error(self):
        """Test that missing 'expr' key raises KeyError."""
        data = {"alert": "TestAlert", "for": "5m"}
        with pytest.raises(KeyError):
            AlertRule.from_dict(data)

    def test_empty_dict_raises_key_error(self):
        """Test that empty dict raises KeyError."""
        with pytest.raises(KeyError):
            AlertRule.from_dict({})

    def test_none_input_raises_type_error(self):
        """Test that None input raises TypeError."""
        with pytest.raises(TypeError):
            AlertRule.from_dict(None)

    def test_non_dict_input_raises_attribute_error(self):
        """Test that non-dict input raises AttributeError."""
        with pytest.raises((AttributeError, TypeError)):
            AlertRule.from_dict("not a dict")

    def test_none_alert_name_accepted(self):
        """Test that None as alert name is accepted (no type validation)."""
        data = {"alert": None, "expr": "up == 0"}
        alert = AlertRule.from_dict(data)
        assert alert.name is None

    def test_labels_wrong_type_raises(self):
        """Test that non-dict labels causes error on .get() access."""
        data = {"alert": "Test", "expr": "up == 0", "labels": "not-a-dict"}
        with pytest.raises(AttributeError):
            AlertRule.from_dict(data)


class TestForDurationOverride:
    def test_customize_applies_for_duration(self) -> None:
        """for_duration override replaces AlertRule.duration during customization."""
        from nthlayer_generate.alerts.models import AlertRule

        alert = AlertRule(
            name="PostgresqlDown",
            expr="pg_up == 0",
            duration="5m",
            severity="critical",
        )
        customized = alert.customize_for_service(
            service_name="payment-api",
            team="payments",
            tier="critical",
            for_duration_override="2m",
        )
        assert customized.duration == "2m"

    def test_customize_no_override_keeps_original(self) -> None:
        """Without for_duration_override, original duration is preserved."""
        from nthlayer_generate.alerts.models import AlertRule

        alert = AlertRule(
            name="PostgresqlDown",
            expr="pg_up == 0",
            duration="5m",
            severity="critical",
        )
        customized = alert.customize_for_service(
            service_name="payment-api",
            team="payments",
            tier="critical",
        )
        assert customized.duration == "5m"

    def test_customize_none_override_keeps_original(self) -> None:
        """Explicitly passing None keeps original duration."""
        from nthlayer_generate.alerts.models import AlertRule

        alert = AlertRule(
            name="PostgresqlDown",
            expr="pg_up == 0",
            duration="5m",
            severity="critical",
        )
        customized = alert.customize_for_service(
            service_name="payment-api",
            team="payments",
            tier="critical",
            for_duration_override=None,
        )
        assert customized.duration == "5m"


def test_manifest_alerts_go_through_validation():
    """A template's ``for: 0m`` is raised to 1m on the manifest path.

    Ported from the legacy TestAlertValidationIntegration (opensrm-wo62.4.22).
    alerts/templates/brokers/rabbitmq.yaml ships two ``for: 0m`` rules, and
    examples/services/email-worker.yaml depends on rabbitmq, so validation
    has a real zero to fix.
    """
    from nthlayer_common.manifest import load_manifest

    from nthlayer_generate.generators.alerts import generate_alerts_from_manifest

    zero_durations = {"0m", "0s", ""}
    zero_rules_in_template = {
        rule.name
        for rule in AlertTemplateLoader().load_technology("rabbitmq")
        if rule.duration in zero_durations
    }
    assert zero_rules_in_template, "rabbitmq.yaml no longer ships a for: 0m rule; pick another"

    manifest = load_manifest(
        Path(__file__).resolve().parents[1] / "examples" / "services" / "email-worker.yaml",
        suppress_deprecation_warning=True,
    )
    durations = {
        alert.name: alert.duration for alert in generate_alerts_from_manifest(manifest, quiet=True)
    }

    assert {name: durations.get(name) for name in zero_rules_in_template} == dict.fromkeys(
        zero_rules_in_template, "1m"
    )
    assert not [name for name, duration in durations.items() if duration in zero_durations]
