"""Tests for validate-slo CLI command."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from nthlayer_generate.cli.validate_slo import (
    PROMQL_FUNCTIONS,
    SLOValidationResult,
    create_demo_slo_results,
    extract_metric_names,
    validate_slo_command,
)


class TestExtractMetricNames:
    """Tests for PromQL metric extraction."""

    def test_extract_simple_metric(self):
        """Test extracting simple metric name."""
        query = 'http_requests_total{service="payment"}'
        metrics = extract_metric_names(query)
        assert "http_requests_total" in metrics

    def test_extract_metric_with_rate(self):
        """Test extracting metric from rate function."""
        query = 'rate(http_requests_total{service="payment"}[5m])'
        metrics = extract_metric_names(query)
        assert "http_requests_total" in metrics
        assert "rate" not in metrics

    def test_extract_histogram_metric(self):
        """Test extracting histogram metric."""
        query = "histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))"
        metrics = extract_metric_names(query)
        assert "http_request_duration_seconds_bucket" in metrics
        assert "histogram_quantile" not in metrics

    def test_extract_multiple_metrics(self):
        """Test extracting multiple metrics from complex query."""
        query = """
        sum(rate(http_requests_total{status="200"}[5m]))
        /
        sum(rate(http_requests_total[5m]))
        """
        metrics = extract_metric_names(query)
        assert "http_requests_total" in metrics

    def test_exclude_promql_functions(self):
        """Test that PromQL functions are excluded."""
        query = "sum(rate(http_requests_total[5m]))"
        metrics = extract_metric_names(query)

        assert "sum" not in metrics
        assert "rate" not in metrics
        assert "http_requests_total" in metrics

    def test_extract_with_labels(self):
        """Test extraction with complex label selectors."""
        query = 'http_requests_total{service="payment", method=~"GET|POST"}'
        metrics = extract_metric_names(query)
        assert "http_requests_total" in metrics

    def test_empty_query(self):
        """Test with empty query."""
        metrics = extract_metric_names("")
        assert len(metrics) == 0

    def test_query_with_numbers(self):
        """Test query with literal numbers."""
        query = "http_requests_total > 100"
        metrics = extract_metric_names(query)
        assert "http_requests_total" in metrics

    def test_promql_functions_list(self):
        """Test that PROMQL_FUNCTIONS is comprehensive."""
        common_functions = ["sum", "rate", "avg", "max", "min", "histogram_quantile"]
        for func in common_functions:
            assert func in PROMQL_FUNCTIONS


class TestSLOValidationResult:
    """Tests for SLOValidationResult dataclass."""

    def test_create_result(self):
        """Test creating validation result."""
        result = SLOValidationResult(
            slo_name="test-slo",
            query="rate(http_requests_total[5m])",
            metrics=["http_requests_total"],
            found_metrics=["http_requests_total"],
            missing_metrics=[],
            all_found=True,
        )

        assert result.slo_name == "test-slo"
        assert result.all_found is True

    def test_result_to_dict(self):
        """Test serialization to dict."""
        result = SLOValidationResult(
            slo_name="test-slo",
            query="test query",
            metrics=["metric1", "metric2"],
            found_metrics=["metric1"],
            missing_metrics=["metric2"],
            all_found=False,
        )

        data = result.to_dict()
        assert data["slo_name"] == "test-slo"
        assert data["all_found"] is False
        assert "metric2" in data["missing_metrics"]


class TestDemoSLOResults:
    """Tests for demo SLO results."""

    def test_create_demo_results(self):
        """Test demo results are created."""
        results = create_demo_slo_results()
        assert len(results) == 3

    def test_demo_has_mixed_results(self):
        """Test demo includes both valid and invalid SLOs."""
        results = create_demo_slo_results()

        valid = [r for r in results if r.all_found]
        invalid = [r for r in results if not r.all_found]

        assert len(valid) >= 1
        assert len(invalid) >= 1

    def test_demo_result_structure(self):
        """Test demo results have proper structure."""
        results = create_demo_slo_results()

        for result in results:
            assert result.slo_name
            assert result.query
            assert isinstance(result.metrics, list)


class TestValidateSLOCommand:
    """Tests for validate-slo CLI command."""

    def test_demo_mode_table(self, capsys):
        """Test demo mode with table output."""
        exit_code = validate_slo_command(
            service_file="dummy.yaml",
            demo=True,
        )

        # Exit code 1 because demo has missing metrics
        assert exit_code == 1
        captured = capsys.readouterr()
        assert "SLO Metric Validation" in captured.out
        assert "payment-api" in captured.out

    def test_demo_mode_json(self, capsys):
        """Test demo mode with JSON output."""
        exit_code = validate_slo_command(
            service_file="dummy.yaml",
            output_format="json",
            demo=True,
        )

        assert exit_code == 1
        captured = capsys.readouterr()
        data = json.loads(captured.out)

        assert data["service"] == "payment-api"
        assert "results" in data
        assert len(data["results"]) == 3
        assert data["all_valid"] is False

    def test_demo_shows_found_metrics(self, capsys):
        """Test that found metrics are shown."""
        validate_slo_command(
            service_file="dummy.yaml",
            demo=True,
        )

        captured = capsys.readouterr()
        assert "Found" in captured.out

    def test_demo_shows_missing_metrics(self, capsys):
        """Test that missing metrics are shown."""
        validate_slo_command(
            service_file="dummy.yaml",
            demo=True,
        )

        captured = capsys.readouterr()
        assert "Missing" in captured.out
        assert "http_errors_total" in captured.out

    def test_invalid_service_file(self):
        """Test with nonexistent service file returns error exit code."""
        exit_code = validate_slo_command(
            service_file="/nonexistent/path.yaml",
            demo=False,
        )
        assert exit_code == 2

    def test_service_file_without_slos(self, tmp_path):
        """A service with no SLOs exits 0 without validating anything."""
        service_file = tmp_path / "service.yaml"
        service_file.write_text("""
service:
  name: test-service
  team: test-team
  tier: standard
  type: api

resources: []
""")

        with patch("nthlayer_generate.cli.validate_slo.validate_slo_metrics") as validate:
            exit_code = validate_slo_command(
                service_file=str(service_file),
                demo=False,
            )

        assert exit_code == 0
        validate.assert_not_called()


class TestMetricExtractionEdgeCases:
    """Tests for edge cases in metric extraction."""

    def test_aggregation_with_by_clause(self):
        """Test extraction with by/without clauses."""
        query = "sum by (service) (rate(http_requests_total[5m]))"
        metrics = extract_metric_names(query)
        assert "http_requests_total" in metrics
        assert "by" not in metrics

    def test_binary_operators(self):
        """Test extraction with binary operators."""
        query = "http_requests_total / http_requests_failed_total"
        metrics = extract_metric_names(query)
        # The second metric may or may not be captured depending on context
        assert "http_requests_total" in metrics

    def test_offset_modifier(self):
        """Test extraction with offset modifier."""
        query = "http_requests_total offset 1h"
        metrics = extract_metric_names(query)
        assert "http_requests_total" in metrics
        assert "offset" not in metrics

    def test_subquery(self):
        """Test extraction from subquery."""
        query = "max_over_time(rate(http_requests_total[5m])[1h:5m])"
        metrics = extract_metric_names(query)
        assert "http_requests_total" in metrics

    def test_metric_with_colon(self):
        """Test metric names with colons (recording rules)."""
        query = 'job:http_requests_total:rate5m{job="api"}'
        metrics = extract_metric_names(query)
        assert "job:http_requests_total:rate5m" in metrics


# --- ratio-shaped SLOs (opensrm-tuwx) ---------------------------------------
#
# Fixture provenance. The legacy shape, spec.indicators[].success_ratio with a
# total_query and a good_query, is the one the shipped examples under
# examples/services/ use (documented in README.md, "success_ratio"); they are
# loaded from disk, unmodified. The OpenSLO shape is the envelope of
# opensrm/spec/v2/examples/services/api.yaml with an inline OpenSLO v1 SLO
# whose ratioMetric follows the vendored excerpt
# nthlayer-common/tests/fixtures/openslo/ratio-metric-v1.md ("{good, total},
# {bad, total} or raw"; a Prometheus metricSource's spec.query).

SERVICES = Path(__file__).resolve().parents[1] / "examples" / "services"

# (shipped file, SLO name, the one metric both of its ratio queries read)
SHIPPED_RATIO_SLOS = [
    ("checkout-service.yaml", "checkout-service-availability", "http_requests_total"),
    ("identity-service.yaml", "identity-service-availability", "http_requests_total"),
    (
        "notification-worker.yaml",
        "notification-worker-delivery-success",
        "notifications_sent_total",
    ),
]

# The shipped examples read one metric on both sides of the ratio, so they
# cannot tell "both queries are read" from "one of them is". This one can.
_LEGACY_DISTINCT_RATIO = """\
apiVersion: nthlayer.dev/v1
kind: Service

service:
  name: ledger-api
  team: payments
  tier: critical
  type: api

resources:
  - kind: SLO
    name: availability
    spec:
      objective: 99.9
      window: 30d
      indicators:
        - type: availability
          success_ratio:
            total_query: sum(rate(ledger_requests_total{service="ledger-api"}[5m]))
            good_query: sum(rate(ledger_requests_succeeded_total{service="ledger-api"}[5m]))
"""

_V2_BAD_TOTAL = """\
apiVersion: opensrm.nthlayer.io/v2
kind: ServiceManifest
metadata:
  name: checkout-api
  namespace: default
  labels:
    domain: commerce
    tier: critical
spec:
  owner:
    group: "group:default/sre-checkout"
  service:
    name: checkout-api
    type: api
  slo:
    - apiVersion: openslo/v1
      kind: SLO
      metadata:
        name: checkout-availability
      spec:
        service: checkout-api
        budgetingMethod: Occurrences
        indicator:
          metadata:
            name: availability
          spec:
            ratioMetric:
              counter: true
              bad:
                metricSource:
                  type: Prometheus
                  spec:
                    query: sum(rate(checkout_failures_total{service="checkout-api"}[5m]))
              total:
                metricSource:
                  type: Prometheus
                  spec:
                    query: sum(rate(checkout_requests_total{service="checkout-api"}[5m]))
        timeWindow:
          - duration: 28d
            isRolling: true
        objectives:
          - displayName: "99.95% of checkout sessions served successfully"
            target: 0.9995
"""


def _run_json(capsys, service_file, **kwargs):
    """Run validate-slo in JSON mode; return (exit code, parsed document)."""
    capsys.readouterr()
    code = validate_slo_command(service_file=str(service_file), output_format="json", **kwargs)
    return code, json.loads(capsys.readouterr().out)


def _result(doc, slo_name):
    matches = [r for r in doc["results"] if r["slo_name"] == slo_name]
    assert len(matches) == 1, f"expected one result for {slo_name}, got {len(matches)}"
    return matches[0]


class TestRatioShapedSLOs:
    """An SLO that carries its query as a ratio is validated, not skipped."""

    @pytest.fixture(autouse=True)
    def _offline(self, monkeypatch):
        monkeypatch.delenv("PROMETHEUS_URL", raising=False)

    def test_shipped_ratio_slos_are_listed(self):
        """Guard the parametrize list: an empty one collects nothing."""
        assert len(SHIPPED_RATIO_SLOS) == 3
        for file_name, _slo, _metric in SHIPPED_RATIO_SLOS:
            assert (SERVICES / file_name).is_file()

    @pytest.mark.parametrize(("file_name", "slo_name", "metric"), SHIPPED_RATIO_SLOS)
    def test_shipped_legacy_success_ratio_is_validated(self, capsys, file_name, slo_name, metric):
        code, doc = _run_json(capsys, SERVICES / file_name)

        result = _result(doc, slo_name)
        assert result["metrics"] == [metric]
        assert result["found_metrics"] == [metric]
        assert result["error"] is None
        assert result["query"] != ""
        assert code == 0

    def test_legacy_ratio_reads_both_queries(self, capsys, tmp_path):
        service_file = tmp_path / "ledger-api.yaml"
        service_file.write_text(_LEGACY_DISTINCT_RATIO)

        _code, doc = _run_json(capsys, service_file)

        result = _result(doc, "ledger-api-availability")
        assert sorted(result["metrics"]) == [
            "ledger_requests_succeeded_total",
            "ledger_requests_total",
        ]
        assert result["error"] is None

    def test_openslo_bad_total_ratio_reads_both_queries(self, capsys, tmp_path):
        service_file = tmp_path / "checkout-api.yaml"
        service_file.write_text(_V2_BAD_TOTAL)

        _code, doc = _run_json(capsys, service_file)

        result = _result(doc, "checkout-api-checkout-availability")
        assert sorted(result["metrics"]) == [
            "checkout_failures_total",
            "checkout_requests_total",
        ]
        assert result["error"] is None

    def test_missing_ratio_metric_fails_the_command(self, capsys, tmp_path):
        """With Prometheus reachable, a ratio metric that does not exist is
        reported missing and the command exits 1."""
        service_file = tmp_path / "ledger-api.yaml"
        service_file.write_text(_LEGACY_DISTINCT_RATIO)

        async def exists(_url, metric):
            return metric != "ledger_requests_succeeded_total"

        with patch("nthlayer_generate.cli.validate_slo.validate_metric_exists", exists):
            code, doc = _run_json(capsys, service_file, prometheus_url="http://prometheus.invalid")

        result = _result(doc, "ledger-api-availability")
        assert result["missing_metrics"] == ["ledger_requests_succeeded_total"]
        assert result["found_metrics"] == ["ledger_requests_total"]
        assert doc["all_valid"] is False
        assert code == 1
