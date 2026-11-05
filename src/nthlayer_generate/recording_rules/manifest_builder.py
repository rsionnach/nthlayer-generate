"""Builder for generating Prometheus recording rules from ReliabilityManifest.

This module provides recording rule generation for:
- Standard SLOs (availability, latency, error_rate, throughput), with an
  error budget for each request-ratio SLO (opensrm-zo0o)
- AI Gate judgment SLOs (reversal_rate, high_confidence_failure)
- AI Gate judgment thresholds (calibration, feedback_latency), from nthlayer-common's
  JudgmentThreshold (opensrm-wo62.1, spec §5.3)

The generated metrics are compatible with Backstage plugins:
- SloCard expects: slo:error_budget_remaining:ratio{service="..."}
- JudgmentCard expects: ai_gate:reversal_rate:ratio{service="..."}
"""

from __future__ import annotations

from decimal import Decimal

import structlog
from nthlayer_common.manifest import (
    ERROR_BUDGET_REMAINING,
    FEEDBACK_LATENCY_WINDOW,
    JudgmentThreshold,
    ReliabilityManifest,
    SLODefinition,
    duration_seconds,
)
from nthlayer_common.manifest.thresholds import DURATION, THRESHOLD_BOUNDS

from nthlayer_generate.core.placeholders import substitute_manifest_placeholders
from nthlayer_generate.recording_rules.models import RecordingRule, RecordingRuleGroup

logger = structlog.get_logger()

# The recording rule a threshold bound's alerts compare against, per type and
# bound (wo62.2). Only types with a data source in common's THRESHOLD_SERIES
# appear; the alert builder reads the same table, so the two cannot drift.
THRESHOLD_BOUND_RECORDS: dict[str, dict[str, str]] = {
    "calibration": {
        "maximum_expected_calibration_error": "ai_gate:calibration:ece",
        "maximum_brier_score": "ai_gate:calibration:brier",
    },
    "feedback_latency": {
        "maximum_p50": f"ai_gate:feedback_latency:p50_within_bound_{FEEDBACK_LATENCY_WINDOW}",
        "maximum_p90": f"ai_gate:feedback_latency:p90_within_bound_{FEEDBACK_LATENCY_WINDOW}",
    },
}

# OPENSRM-CORE-v2 §5.5.5: the quantile each feedback_latency bound caps.
FEEDBACK_LATENCY_QUANTILES: dict[str, float] = {"maximum_p50": 0.5, "maximum_p90": 0.9}


class ManifestRecordingRuleBuilder:
    """Builds Prometheus recording rules from ReliabilityManifest.

    Supports both standard SLOs and AI gate judgment SLOs.
    """

    def __init__(self, manifest: ReliabilityManifest):
        """Initialize builder with manifest.

        Args:
            manifest: ReliabilityManifest instance
        """
        self.manifest = manifest

    def build(self) -> list[RecordingRuleGroup]:
        """Build recording rule groups.

        Returns:
            List of RecordingRuleGroup objects
        """
        groups = []

        # Standard SLO metrics
        standard_slos = self.manifest.get_standard_slos()
        if standard_slos:
            slo_group = RecordingRuleGroup(
                name=f"{self.manifest.name}_slo_metrics",
                interval="30s",
            )
            for slo in standard_slos:
                rules = self._build_standard_slo_rules(slo)
                for rule in rules:
                    slo_group.add_rule(rule)
            if slo_group.rules:
                groups.append(slo_group)

        # AI gate judgment metrics: judgment SLOs, then judgment thresholds
        if self.manifest.is_ai_gate():
            judgment_group = RecordingRuleGroup(
                name=f"{self.manifest.name}_judgment_metrics",
                interval="30s",
            )
            for slo in self.manifest.get_judgment_slos():
                for rule in self._build_judgment_slo_rules(slo):
                    judgment_group.add_rule(rule)
            for threshold in self.manifest.get_judgment_thresholds():
                for rule in self._build_judgment_threshold_rules(threshold):
                    _add_unique(judgment_group, rule)
            if judgment_group.rules:
                groups.append(judgment_group)

            # 30-day within-bound fractions: 30-day range queries, so a
            # slower interval than the 30s judgment group (wo62.2).
            window_group = RecordingRuleGroup(
                name=f"{self.manifest.name}_judgment_thresholds_{FEEDBACK_LATENCY_WINDOW}",
                interval="5m",
            )
            for threshold in self.manifest.get_judgment_thresholds():
                for rule in self._build_judgment_threshold_window_rules(threshold):
                    _add_unique(window_group, rule)
            if window_group.rules:
                groups.append(window_group)

        # Service health metrics
        health_group = self._build_health_rules()
        if health_group.rules:
            groups.append(health_group)

        return groups

    def _build_standard_slo_rules(self, slo: SLODefinition) -> list[RecordingRule]:
        """Build recording rules for a standard SLO, dispatched on its kind.

        Availability, latency and error_rate get their canned rules and one
        error budget: from the SLO's own queries if it has them (ruling Z3),
        else from the kind's canned good ratio. Throughput, freshness, lag
        and custom get no budget (ruling D5).
        """
        rules: list[RecordingRule] = []
        service = self.manifest.name
        slo_name = slo.name

        kind = _slo_kind(slo)

        # Ruling Z3 (opensrm-zo0o): an SLO with its own good/total queries
        # gets its budget from them, whatever its request-ratio kind; the
        # kind's canned rules are still written, for dashboards, but without
        # a budget, so no SLO has two.
        own_queries = _has_own_queries(slo)
        canned_budget = not own_queries

        if kind == "availability":
            rules.extend(
                self._build_availability_rules(service, slo_name, slo, with_budget=canned_budget)
            )
        elif kind == "latency":
            rules.extend(
                self._build_latency_rules(service, slo_name, slo, with_budget=canned_budget)
            )
        elif kind == "error_rate":
            rules.extend(
                self._build_error_rate_rules(service, slo_name, slo, with_budget=canned_budget)
            )
        elif kind == "throughput":
            # Ruling D5: not a request ratio, so no budget (opensrm-vcxm).
            return self._build_throughput_rules(service, slo_name, slo)
        else:
            # freshness, lag, custom: no rules and no budget (D5).
            return rules

        if own_queries:
            rules.extend(self._build_own_query_rules(service, slo_name, slo))

        return rules

    def _build_own_query_rules(
        self, service: str, slo_name: str, slo: SLODefinition
    ) -> list[RecordingRule]:
        """Record an SLO's own good/total queries and its budget (ruling Z3).

        The author's queries are recorded as-is inside sum(), placeholders
        substituted and nothing else rewritten. With only a bad query
        (OpenSLO's {bad, total} form), good is total minus bad. The ratio
        sums both over the SLO's window, and the budget is built from it
        with the same formula as every other path.
        """
        objective = slo.target
        window = slo.window
        # _has_own_queries guarantees total and one of good/bad.
        # sum(): one series per (service, slo) whatever labels the author's
        # query leaves, so the ratio's `/` always matches exactly one pair.
        total = self._summed(slo.total_query)
        if slo.good_query:
            # `or (0 * total)`: a good query that matches nothing (a typo, or
            # no success yet) is zero good, an exhausted budget, rather than
            # no series at all, which readers take as no data.
            good = f"({self._summed(slo.good_query)} or (0 * {total}))"
        else:
            # `or vector(0)`: a bad query with no series yet (no errors since
            # the exporter started) sums to nothing, and total - nothing is
            # nothing; every clean sample would then count as zero good.
            good = f"{total} - ({self._summed(slo.bad_query)} or vector(0))"
        series_labels = {"service": service, "slo": slo_name}

        return [
            RecordingRule(record="slo:sli_good:rate", expr=good, labels=dict(series_labels)),
            RecordingRule(record="slo:sli_total:rate", expr=total, labels=dict(series_labels)),
            RecordingRule(
                record="slo:sli:ratio",
                expr=(
                    f"sum_over_time({_slo_selector('slo:sli_good:rate', service, slo_name)}"
                    f"[{window}]) / "
                    f"sum_over_time({_slo_selector('slo:sli_total:rate', service, slo_name)}"
                    f"[{window}])"
                ),
                labels={**series_labels, "objective": str(objective)},
            ),
            *_error_budget_rules(service, slo, _slo_selector("slo:sli:ratio", service, slo_name)),
        ]

    def _substitute(self, query: str) -> str:
        return substitute_manifest_placeholders(query, self.manifest)

    def _summed(self, query: str | None) -> str:
        """``sum(<author query>)``, the closing paren on its own line: a
        trailing ``# comment`` in the author's query would otherwise swallow
        it, and Prometheus would refuse the whole rule file."""
        return f"sum({self._substitute(query or '')}\n)"

    def _build_availability_rules(
        self, service: str, slo_name: str, slo: SLODefinition, *, with_budget: bool
    ) -> list[RecordingRule]:
        """Build recording rules for availability SLO."""
        objective = slo.target
        window = slo.window

        rules = []

        # Total requests over window
        rules.append(
            RecordingRule(
                record=f"slo:requests_total:{window}",
                expr=f'sum(increase(http_requests_total{{service="{service}"}}[{window}]))',
                labels={
                    "service": service,
                    "slo": slo_name,
                },
            )
        )

        # Successful requests (non-5xx)
        rules.append(
            RecordingRule(
                record=f"slo:requests_success:{window}",
                expr=f'sum(increase(http_requests_total{{service="{service}",status!~"5.."}}[{window}]))',
                labels={
                    "service": service,
                    "slo": slo_name,
                },
            )
        )

        # Availability percentage
        rules.append(
            RecordingRule(
                record="slo:availability:ratio",
                expr=(
                    f'slo:requests_success:{window}{{service="{service}",slo="{slo_name}"}} / '
                    f'slo:requests_total:{window}{{service="{service}",slo="{slo_name}"}}'
                ),
                labels={
                    "service": service,
                    "slo": slo_name,
                    "objective": str(objective),
                },
            )
        )

        if with_budget:
            rules.extend(
                _error_budget_rules(
                    service,
                    slo,
                    _slo_selector("slo:availability:ratio", service, slo_name),
                )
            )

        return rules

    def _build_latency_rules(
        self, service: str, slo_name: str, slo: SLODefinition, *, with_budget: bool
    ) -> list[RecordingRule]:
        """Build recording rules for latency SLO."""
        objective = slo.target  # Target percentage under threshold
        # The legacy bound is declared apart from the objective (common's
        # threshold_ms, opensrm-wo62.4.7); srm/v1 puts it in target with unit.
        if slo.threshold_ms is not None:
            threshold_ms = slo.threshold_ms
        else:
            threshold_ms = slo.target if slo.unit == "ms" else 500
        threshold_sec = threshold_ms / 1000
        window = slo.window

        rules = []

        # Total requests
        rules.append(
            RecordingRule(
                record=f"slo:latency_requests_total:{window}",
                expr=f'sum(increase(http_request_duration_seconds_count{{service="{service}"}}[{window}]))',
                labels={
                    "service": service,
                    "slo": slo_name,
                },
            )
        )

        # Requests under threshold
        rules.append(
            RecordingRule(
                record=f"slo:latency_requests_fast:{window}",
                expr=(
                    f'sum(increase(http_request_duration_seconds_bucket{{service="{service}",'
                    f'le="{prometheus_le(threshold_sec)}"}}[{window}]))'
                ),
                labels={
                    "service": service,
                    "slo": slo_name,
                    # %g: 500.0 renders "500ms", as the legacy builder wrote it.
                    "threshold": f"{threshold_ms:g}ms",
                },
            )
        )

        # Latency SLO compliance
        rules.append(
            RecordingRule(
                record="slo:latency:ratio",
                expr=(
                    f'slo:latency_requests_fast:{window}{{service="{service}",slo="{slo_name}"}} / '
                    f'slo:latency_requests_total:{window}{{service="{service}",slo="{slo_name}"}}'
                ),
                labels={
                    "service": service,
                    "slo": slo_name,
                    "objective": str(objective),
                },
            )
        )

        # Good is the fraction of requests under the threshold.
        if with_budget:
            rules.extend(
                _error_budget_rules(
                    service,
                    slo,
                    _slo_selector("slo:latency:ratio", service, slo_name),
                )
            )

        # Percentiles for dashboards
        for quantile in [0.50, 0.95, 0.99]:
            rules.append(
                RecordingRule(
                    record=f"slo:http_request_duration_seconds:p{int(quantile * 100)}",
                    expr=(
                        f"histogram_quantile({quantile}, "
                        f'rate(http_request_duration_seconds_bucket{{service="{service}"}}[5m]))'
                    ),
                    labels={
                        "service": service,
                        "slo": slo_name,
                    },
                )
            )

        return rules

    def _build_error_rate_rules(
        self, service: str, slo_name: str, slo: SLODefinition, *, with_budget: bool
    ) -> list[RecordingRule]:
        """Build recording rules for error rate SLO."""
        objective = slo.target
        window = slo.window

        rules = []

        # Total requests
        rules.append(
            RecordingRule(
                record=f"slo:error_requests_total:{window}",
                expr=f'sum(increase(http_requests_total{{service="{service}"}}[{window}]))',
                labels={
                    "service": service,
                    "slo": slo_name,
                },
            )
        )

        # Error requests (5xx)
        rules.append(
            RecordingRule(
                record=f"slo:error_requests_failed:{window}",
                expr=f'sum(increase(http_requests_total{{service="{service}",status=~"5.."}}[{window}]))',
                labels={
                    "service": service,
                    "slo": slo_name,
                },
            )
        )

        # Error rate
        rules.append(
            RecordingRule(
                record="slo:error_rate:ratio",
                expr=(
                    f'slo:error_requests_failed:{window}{{service="{service}",slo="{slo_name}"}} / '
                    f'slo:error_requests_total:{window}{{service="{service}",slo="{slo_name}"}}'
                ),
                labels={
                    "service": service,
                    "slo": slo_name,
                    "objective": str(objective),
                },
            )
        )

        # slo:error_rate:ratio is the BAD fraction; good is its complement.
        if with_budget:
            rules.extend(
                _error_budget_rules(
                    service,
                    slo,
                    f"(1 - {_slo_selector('slo:error_rate:ratio', service, slo_name)})",
                )
            )

        return rules

    def _build_throughput_rules(
        self, service: str, slo_name: str, slo: SLODefinition
    ) -> list[RecordingRule]:
        """Build recording rules for throughput SLO."""
        minimum_rps = slo.target

        rules = []

        # Current throughput (requests per second)
        rules.append(
            RecordingRule(
                record="slo:throughput:rate5m",
                expr=f'sum(rate(http_requests_total{{service="{service}"}}[5m]))',
                labels={
                    "service": service,
                    "slo": slo_name,
                    "minimum": str(minimum_rps),
                },
            )
        )

        # Throughput SLO compliance (1 if above minimum, 0 otherwise)
        rules.append(
            RecordingRule(
                record="slo:throughput:compliance",
                expr=(
                    f'(slo:throughput:rate5m{{service="{service}",slo="{slo_name}"}} >= {minimum_rps}) '
                    f"or vector(0)"
                ),
                labels={
                    "service": service,
                    "slo": slo_name,
                    "minimum": str(minimum_rps),
                },
            )
        )

        return rules

    def _build_judgment_slo_rules(self, slo: SLODefinition) -> list[RecordingRule]:
        """Build recording rules for AI gate judgment SLOs.

        Dispatches on ``slo.judgment_type``: v2 judgment SLO names are
        free-form (spec D12). Types without rules here emit nothing.

        These metrics are expected by Backstage JudgmentCard:
        - ai_gate:reversal_rate:ratio{service="..."}
        - ai_gate:high_confidence_failure:ratio{service="..."}
        """
        service = self.manifest.name
        target = slo.target
        window = slo.window
        # calibration and feedback_latency are JudgmentThresholds in common's
        # model, never judgment SLOs: _build_judgment_threshold_rules owns them.
        if slo.judgment_type == "reversal_rate":
            return self._build_reversal_rate_rules(service, target, window)
        if slo.judgment_type == "high_confidence_failure":
            return self._build_high_confidence_failure_rules(service, target, window)
        return []

    def _build_judgment_threshold_rules(self, threshold: JudgmentThreshold) -> list[RecordingRule]:
        """Build recording rules for one judgment threshold (spec §5.3, wo62.2 §4).

        - calibration: the ECE rules when ``maximum_expected_calibration_error``
          is declared, then ``:brier`` when ``maximum_brier_score`` is; each
          rule's ``target`` is ``str(bound)``.
        - feedback_latency: ``:p50/:p95/:p99`` always; ``:bucket`` when
          ``maximum_p50`` is declared, with ``le`` and ``target`` both
          ``str(duration_seconds(maximum_p50))``. The 30-day within-bound fractions are
          built separately, by ``_build_judgment_threshold_window_rules``.

        segments, stability and audit_backlog have no data source in
        common's THRESHOLD_SERIES and emit nothing (wo62.2 ruling D2).
        """
        service = self.manifest.name
        bounds = threshold.bounds

        if threshold.type == "calibration":
            rules: list[RecordingRule] = []
            ece = bounds.get("maximum_expected_calibration_error")
            if ece is not None:
                rules.extend(self._build_calibration_rules(service, float(ece)))
            brier = bounds.get("maximum_brier_score")
            if brier is not None:
                rules.append(self._build_brier_rule(service, float(brier)))
            return rules
        if threshold.type == "feedback_latency":
            return self._build_feedback_latency_rules(
                service, _bound_seconds(bounds, "maximum_p50")
            )
        return []

    def _build_judgment_threshold_window_rules(
        self, threshold: JudgmentThreshold
    ) -> list[RecordingRule]:
        """Build the 30-day within-bound fraction rule per declared p50/p90 bound.

        These use the window §5.5.5 defines, and they are what the threshold
        alerts compare against. Every other type emits nothing here.
        """
        if threshold.type != "feedback_latency":
            return []
        service = self.manifest.name
        rules = []
        for bound, quantile in FEEDBACK_LATENCY_QUANTILES.items():
            seconds = _bound_seconds(threshold.bounds, bound)
            if seconds is not None:
                rules.append(
                    self._build_feedback_latency_window_rule(service, bound, quantile, seconds)
                )
        return rules

    def _build_reversal_rate_rules(
        self, service: str, target: float, window: str
    ) -> list[RecordingRule]:
        """Build rules for reversal rate (human override tracking).

        Measures how often AI decisions are reversed by humans.
        Lower is better - indicates AI decisions are trusted.
        """
        rules = []

        # Total AI decisions
        rules.append(
            RecordingRule(
                record=f"ai_gate:decisions_total:{window}",
                expr=f'sum(increase(ai_gate_decisions_total{{service="{service}"}}[{window}]))',
                labels={"service": service},
            )
        )

        # Reversed decisions (human overrides)
        rules.append(
            RecordingRule(
                record=f"ai_gate:decisions_reversed:{window}",
                expr=f'sum(increase(ai_gate_decisions_total{{service="{service}",reversed="true"}}[{window}]))',
                labels={"service": service},
            )
        )

        # Reversal rate ratio
        rules.append(
            RecordingRule(
                record="ai_gate:reversal_rate:ratio",
                expr=(
                    f'ai_gate:decisions_reversed:{window}{{service="{service}"}} / '
                    f'ai_gate:decisions_total:{window}{{service="{service}"}}'
                ),
                labels={
                    "service": service,
                    "target": str(target),
                    "slo": "reversal_rate",
                },
            )
        )

        return rules

    def _build_high_confidence_failure_rules(
        self, service: str, target: float, window: str
    ) -> list[RecordingRule]:
        """Build rules for high confidence failure rate.

        Measures failures in decisions where the model was highly confident.
        Critical indicator of model reliability.
        """
        rules = []

        # High confidence decisions
        rules.append(
            RecordingRule(
                record=f"ai_gate:high_confidence_decisions:{window}",
                expr=(
                    f'sum(increase(ai_gate_decisions_total{{service="{service}",'
                    f'confidence_bucket="high"}}[{window}]))'
                ),
                labels={"service": service},
            )
        )

        # High confidence failures
        rules.append(
            RecordingRule(
                record=f"ai_gate:high_confidence_failures:{window}",
                expr=(
                    f'sum(increase(ai_gate_decisions_total{{service="{service}",'
                    f'confidence_bucket="high",outcome="incorrect"}}[{window}]))'
                ),
                labels={"service": service},
            )
        )

        # High confidence failure ratio
        rules.append(
            RecordingRule(
                record="ai_gate:high_confidence_failure:ratio",
                expr=(
                    f'ai_gate:high_confidence_failures:{window}{{service="{service}"}} / '
                    f'ai_gate:high_confidence_decisions:{window}{{service="{service}"}}'
                ),
                labels={
                    "service": service,
                    "target": str(target),
                    "slo": "high_confidence_failure",
                },
            )
        )

        return rules

    def _build_calibration_rules(self, service: str, target: float) -> list[RecordingRule]:
        """Build rules for calibration (Expected Calibration Error).

        Measures how well confidence scores match actual accuracy.
        E.g., predictions at 80% confidence should be correct ~80% of the time.
        """
        rules = []

        # ECE (Expected Calibration Error) - typically computed externally
        # This creates a recording rule that aggregates pre-computed ECE
        rules.append(
            RecordingRule(
                record=THRESHOLD_BOUND_RECORDS["calibration"]["maximum_expected_calibration_error"],
                expr=(f'avg(ai_gate_calibration_error{{service="{service}"}})'),
                labels={
                    "service": service,
                    "target": str(target),
                    "slo": "calibration",
                },
            )
        )

        # Calibration by confidence bucket (for detailed analysis)
        for bucket in ["low", "medium", "high"]:
            rules.append(
                RecordingRule(
                    record=f"ai_gate:calibration_bucket:{bucket}",
                    expr=(
                        f'avg(ai_gate_calibration_error{{service="{service}",'
                        f'confidence_bucket="{bucket}"}})'
                    ),
                    labels={
                        "service": service,
                        "confidence_bucket": bucket,
                    },
                )
            )

        return rules

    def _build_brier_rule(self, service: str, target: float) -> RecordingRule:
        """Build the Brier score rule; the source gauge is computed externally."""
        return RecordingRule(
            record=THRESHOLD_BOUND_RECORDS["calibration"]["maximum_brier_score"],
            expr=f'avg(ai_gate_calibration_brier{{service="{service}"}})',
            labels={
                "service": service,
                "target": str(target),
                "slo": "calibration",
            },
        )

    def _build_feedback_latency_rules(
        self, service: str, target_seconds: float | None
    ) -> list[RecordingRule]:
        """Build rules for feedback latency (time to ground truth).

        Measures how long until we know if a decision was correct.
        Important for model improvement and trust building. The ``:bucket``
        rule is emitted only when ``target_seconds`` is given.
        """
        rules = []

        # Feedback latency histogram (for percentiles)
        for quantile in [0.50, 0.95, 0.99]:
            rules.append(
                RecordingRule(
                    record=f"ai_gate:feedback_latency:p{int(quantile * 100)}",
                    expr=(
                        f"histogram_quantile({quantile}, "
                        f'rate(ai_gate_feedback_latency_seconds_bucket{{service="{service}"}}[5m]))'
                    ),
                    labels={
                        "service": service,
                        "slo": "feedback_latency",
                    },
                )
            )

        if target_seconds is None:
            return rules

        # Feedback latency bucket recording (for Backstage JudgmentCard)
        # Records what percentage of feedback arrives within target time
        rules.append(
            RecordingRule(
                record="ai_gate:feedback_latency:bucket",
                expr=(
                    f'sum(rate(ai_gate_feedback_latency_seconds_bucket{{service="{service}",'
                    f'le="{prometheus_le(target_seconds)}"}}[5m])) / '
                    f'sum(rate(ai_gate_feedback_latency_seconds_count{{service="{service}"}}[5m]))'
                ),
                labels={
                    "service": service,
                    "target": str(target_seconds),
                    "slo": "feedback_latency",
                },
            )
        )

        return rules

    def _build_health_rules(self) -> RecordingRuleGroup:
        """Build recording rules for general service health metrics."""
        service = self.manifest.name
        group = RecordingRuleGroup(name=f"{service}_health_metrics", interval="30s")

        # For AI gates, add AI-specific health metrics
        if self.manifest.is_ai_gate():
            # Decision rate
            group.add_rule(
                RecordingRule(
                    record="service:ai_gate_decisions:rate5m",
                    expr=f'sum(rate(ai_gate_decisions_total{{service="{service}"}}[5m]))',
                    labels={"service": service},
                )
            )

            # Average confidence
            group.add_rule(
                RecordingRule(
                    record="service:ai_gate_confidence:avg",
                    expr=f'avg(ai_gate_confidence_score{{service="{service}"}})',
                    labels={"service": service},
                )
            )

        # Standard HTTP metrics (applicable to all service types)
        group.add_rule(
            RecordingRule(
                record="service:http_requests:rate5m",
                expr=f'sum(rate(http_requests_total{{service="{service}"}}[5m]))',
                labels={"service": service},
            )
        )

        group.add_rule(
            RecordingRule(
                record="service:http_errors:rate5m",
                expr=(
                    f'sum(rate(http_requests_total{{service="{service}",status=~"5.."}}[5m])) / '
                    f'sum(rate(http_requests_total{{service="{service}"}}[5m]))'
                ),
                labels={"service": service},
            )
        )

        group.add_rule(
            RecordingRule(
                record="service:http_request_duration_seconds:p95",
                expr=(
                    f"histogram_quantile(0.95, "
                    f'rate(http_request_duration_seconds_bucket{{service="{service}"}}[5m]))'
                ),
                labels={"service": service},
            )
        )

        group.add_rule(
            RecordingRule(
                record="service:http_request_duration_seconds:p99",
                expr=(
                    f"histogram_quantile(0.99, "
                    f'rate(http_request_duration_seconds_bucket{{service="{service}"}}[5m]))'
                ),
                labels={"service": service},
            )
        )

        return group

    def _build_feedback_latency_window_rule(
        self, service: str, bound: str, quantile: float, target_seconds: float
    ) -> RecordingRule:
        """Build the fraction of ground truth that arrived within the bound, over 30 days.

        The quantile is at most the bound exactly when this fraction is at
        least ``quantile``, so the alert compares the fraction and needs no
        interpolation. ``histogram_quantile`` is deliberately not used: it
        reports a quantile in the +Inf bucket as the highest finite ``le``,
        so a breach above the top bucket would read as within bounds (the
        reason common's contract and workers' sampler avoid it too).

        Needs a bucket at exactly ``le`` = the bound, as the ``:bucket`` rule
        does. Without one the series is absent; with no arrivals it is NaN.
        Either way the NotEvaluable alert fires (E3).
        """
        selector = f'service="{service}"'
        window = f"[{FEEDBACK_LATENCY_WINDOW}]"
        return RecordingRule(
            record=THRESHOLD_BOUND_RECORDS["feedback_latency"][bound],
            expr=(
                f'sum(increase(ai_gate_feedback_latency_seconds_bucket{{{selector},le="{prometheus_le(target_seconds)}"}}'
                f"{window})) / sum(increase(ai_gate_feedback_latency_seconds_count{{{selector}}}"
                f"{window}))"
            ),
            labels={
                "service": service,
                "target": str(target_seconds),
                "quantile": str(quantile),
                "slo": "feedback_latency",
            },
        )


def build_recording_rules_from_manifest(
    manifest: ReliabilityManifest,
) -> list[RecordingRuleGroup]:
    """Convenience function to build recording rules from manifest.

    Args:
        manifest: ReliabilityManifest instance

    Returns:
        List of RecordingRuleGroup objects

    Example:
        >>> from nthlayer_common.manifest import load_manifest
        >>> manifest = load_manifest("payment-api.yaml")
        >>> groups = build_recording_rules_from_manifest(manifest)
        >>> yaml_output = create_rule_groups(groups)
    """
    builder = ManifestRecordingRuleBuilder(manifest)
    return builder.build()


def prometheus_le(value: float) -> str:
    """``value`` as exporters write an ``le`` label, so a selector on it matches.

    Go's shortest ``%g`` (exponent form below 1e-4 and from 1e6), plus ".0"
    on a plain integer, which is what the Go and Python clients and
    Prometheus 3's ``le`` normalisation produce: 3600 is "3600.0", but two
    weeks is "1.2096e+06", not "1209600.0".
    """
    if value == 0:
        return "0.0"
    shortest = Decimal(repr(float(value)))
    exponent = shortest.adjusted()
    if -4 <= exponent < 6:
        text = format(shortest, "f")
        return text if "." in text else f"{text}.0"
    digits = "".join(map(str, shortest.as_tuple().digits)).rstrip("0") or "0"
    mantissa = digits[0] + (f".{digits[1:]}" if len(digits) > 1 else "")
    return f"{mantissa}e{'+' if exponent >= 0 else '-'}{abs(exponent):02d}"


def _has_own_queries(slo: SLODefinition) -> bool:
    """True when the SLO declares its own total query and a good or bad one.

    nthlayer-common fills these from OpenSLO's ratioMetric or the legacy
    indicators[].success_ratio, and refuses good and bad together.
    """
    return bool(slo.total_query) and bool(slo.good_query or slo.bad_query)


def _slo_selector(record: str, service: str, slo_name: str) -> str:
    """``record{service="...",slo="..."}``, as every SLO rule here selects."""
    return f'{record}{{service="{service}",slo="{slo_name}"}}'


def _slo_kind(slo: SLODefinition) -> str | None:
    """The rule family an SLO dispatches to, by its type (or, unset, its name)."""
    slo_type = (slo.slo_type or slo.name).lower()
    for needle, kind in (
        ("availability", "availability"),
        ("latency", "latency"),
        ("error", "error_rate"),
        ("throughput", "throughput"),
    ):
        if needle in slo_type:
            return kind
    return None


def _budget_skip_reason(slo: SLODefinition) -> str | None:
    """Why ``slo`` must get no error budget, or None when it may have one.

    Applies to every manifest format. (a) An objective outside [50, 100)
    is not a usable success percentage; it catches srm/v1 error_rate
    targets, which are maxima. (b) A canned latency SLO with no declared
    threshold_ms counts requests under a guessed bound: srm/v1 keeps the
    bound in its target, v2 reads "99ms" from "under 200ms", and the
    legacy plural indicators[].threshold_ms is not read. An SLO with its
    own queries is exempt from (b): its bound is in the good query.
    Writing no budget is better than writing a wrong one: a reader treats
    a missing series as no data.

    TODO(opensrm-t13c): drop (a)'s error_rate case and (b)'s srm/v1 case
    once common converts srm/v1 targets.
    TODO(opensrm-8jpp): drop (b)'s v2 case once common reads the bound.
    """
    # opensrm-t13c: a request-ratio objective is a success percentage. Under
    # 50 it is not one -- srm/v1 error_rate targets are MAXIMUM error rates
    # (0.1 means at most 0.1% errors) -- and 100 or more leaves no budget
    # to divide by.
    if not 50 <= slo.target < 100:
        return "objective_not_a_success_percentage"
    # A canned latency ratio counts requests under a bound; without one the
    # manifest declared (threshold_ms), the builder falls back to the target
    # (srm/v1 writes the bound there, opensrm-t13c; v2 gets "99ms" for
    # "under 200ms", opensrm-8jpp) or to 500ms (a legacy plural indicators[]
    # threshold_ms is not read). A budget on a guessed bound is confidently
    # wrong. An SLO with its own queries carries its bound in the good query.
    if _slo_kind(slo) == "latency" and slo.threshold_ms is None and not _has_own_queries(slo):
        return "latency_bound_not_declared"
    return None


def _error_budget_rules(
    service: str, slo: SLODefinition, ratio_selector: str
) -> list[RecordingRule]:
    """The error budget remaining for one SLO, from its GOOD ratio, or none.

    Every path writes its budget here, so the formula, the labels and the
    guard against unusable targets (``_budget_skip_reason``) live once.
    The name is nthlayer-common's contract, which measure, correlate and
    drift read back (opensrm-h0at); the label keys must stay the
    contract's labels, pinned by
    test_error_budget_rule_follows_the_shared_contract. ``ratio_selector``
    must evaluate to the fraction of good events, 0-1.
    """
    reason = _budget_skip_reason(slo)
    if reason is not None:
        logger.debug(
            "error budget skipped",
            component="recording_rules",
            service=service,
            slo=slo.name,
            reason=reason,
            target=slo.target,
        )
        return []
    objective = slo.target
    return [
        RecordingRule(
            record=ERROR_BUDGET_REMAINING.metric,
            expr=f"1 - ((1 - {ratio_selector}) / (1 - {objective / 100}))",
            labels={
                "service": service,
                "slo": slo.name,
                "objective": str(objective),
            },
        )
    ]


def _add_unique(group: RecordingRuleGroup, rule: RecordingRule) -> None:
    """Add ``rule`` unless an identical one is already there.

    §5.5 lets a manifest repeat a threshold type; two identical rules in one
    group would write the same series twice.
    """
    if rule not in group.rules:
        group.add_rule(rule)


def bound_comparison_value(bounds: dict[str, float | str], name: str) -> float:
    """A declared bound as the rules compare it: a Ratio as declared, a Duration in seconds (E2).

    Its ``str()`` is the ``target`` label of the bound's recording rule.
    """
    (threshold_type,) = [t for t, kinds in THRESHOLD_BOUNDS.items() if name in kinds]
    if THRESHOLD_BOUNDS[threshold_type][name] == DURATION:
        seconds = _bound_seconds(bounds, name)
        if seconds is None:
            raise KeyError(name)
        return seconds
    return float(bounds[name])


def _bound_seconds(bounds: dict[str, float | str], name: str) -> float | None:
    """A declared Duration bound in seconds (E2), or None when undeclared."""
    value = bounds.get(name)
    if value is None:
        return None
    # A Duration string such as "1h" (validated by common); a float here
    # must fail loudly, not stringify to "3600.0".
    if not isinstance(value, str):
        raise TypeError(f"{name} is not a Duration: {value!r}")
    return duration_seconds(value)
