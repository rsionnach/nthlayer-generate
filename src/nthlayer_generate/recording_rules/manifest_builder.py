"""Builder for generating Prometheus recording rules from ReliabilityManifest.

This module provides recording rule generation for:
- Standard SLOs (availability, latency, error_rate, throughput)
- AI Gate judgment SLOs (reversal_rate, high_confidence_failure)
- AI Gate judgment thresholds (calibration, feedback_latency), from nthlayer-common's
  JudgmentThreshold (opensrm-wo62.1, spec §5.3)

The generated metrics are compatible with Backstage plugins:
- SloCard expects: slo:error_budget_remaining:ratio{service="..."}
- JudgmentCard expects: ai_gate:reversal_rate:ratio{service="..."}
"""

from __future__ import annotations

from nthlayer_common.manifest import (
    FEEDBACK_LATENCY_WINDOW,
    JudgmentThreshold,
    ReliabilityManifest,
    SLODefinition,
    duration_seconds,
)
from nthlayer_common.manifest.thresholds import DURATION, THRESHOLD_BOUNDS

from nthlayer_generate.recording_rules.models import RecordingRule, RecordingRuleGroup

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
                    judgment_group.add_rule(rule)
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
                    window_group.add_rule(rule)
            if window_group.rules:
                groups.append(window_group)

        # Service health metrics
        health_group = self._build_health_rules()
        if health_group.rules:
            groups.append(health_group)

        return groups

    def _build_standard_slo_rules(self, slo: SLODefinition) -> list[RecordingRule]:
        """Build recording rules for a standard SLO.

        Args:
            slo: SLO definition

        Returns:
            List of RecordingRule objects
        """
        rules: list[RecordingRule] = []
        service = self.manifest.name
        slo_name = slo.name

        # Determine SLO type by name or explicit type
        slo_type = slo.slo_type or slo.name

        if "availability" in slo_type.lower():
            rules.extend(self._build_availability_rules(service, slo_name, slo))
        elif "latency" in slo_type.lower():
            rules.extend(self._build_latency_rules(service, slo_name, slo))
        elif "error" in slo_type.lower():
            rules.extend(self._build_error_rate_rules(service, slo_name, slo))
        elif "throughput" in slo_type.lower():
            rules.extend(self._build_throughput_rules(service, slo_name, slo))

        return rules

    def _build_availability_rules(
        self, service: str, slo_name: str, slo: SLODefinition
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

        # Error budget remaining (as ratio)
        rules.append(
            RecordingRule(
                record="slo:error_budget_remaining:ratio",
                expr=(
                    f'1 - ((1 - slo:availability:ratio{{service="{service}",slo="{slo_name}"}}) / '
                    f"(1 - {objective / 100}))"
                ),
                labels={
                    "service": service,
                    "slo": slo_name,
                    "objective": str(objective),
                },
            )
        )

        return rules

    def _build_latency_rules(
        self, service: str, slo_name: str, slo: SLODefinition
    ) -> list[RecordingRule]:
        """Build recording rules for latency SLO."""
        objective = slo.target  # Target percentage under threshold
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
                    f'le="{threshold_sec}"}}[{window}]))'
                ),
                labels={
                    "service": service,
                    "slo": slo_name,
                    "threshold": f"{threshold_ms}ms",
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
        self, service: str, slo_name: str, slo: SLODefinition
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
                    f'le="{target_seconds}"}}[5m])) / '
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
                f'sum(increase(ai_gate_feedback_latency_seconds_bucket{{{selector},le="{target_seconds}"}}'
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
