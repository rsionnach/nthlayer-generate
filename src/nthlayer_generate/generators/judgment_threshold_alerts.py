"""Alerts on judgment-threshold bounds (opensrm-wo62.2, OPENSRM-CORE-v2 §5.5.6).

Each declared bound that has a recording rule gets two alerts:

- ``AIGate<Type><Bound>Breach`` fires when the measured value is strictly
  above the bound (E1). A Duration bound is compared in seconds (E2). A
  feedback-latency quantile is tested through its within-bound fraction:
  pq > B exactly when fewer than q of the arrivals fall within B.
- ``AIGate<Type><Bound>NotEvaluable`` fires when the measurement is absent
  or NaN (E3). Without it, a missing series would look like within bounds.
  A window with no arrivals divides 0 by 0 and yields NaN, not an absent
  series, hence ``R != R``.

Both alerts read only generate's own ``ai_gate:*`` recording rules, never
raw series (design D1), so renaming a source metric does not touch alerts.
E4 (combining outcomes) is not encoded: each bound alerts on its own, and
nthlayer-workers combines them.

segments, stability and audit_backlog have no recording rule and get no
alerts (design D2).
"""

from __future__ import annotations

from nthlayer_common.manifest import JudgmentThreshold, ReliabilityManifest

from nthlayer_generate.alerts import AlertRule
from nthlayer_generate.recording_rules.manifest_builder import (
    FEEDBACK_LATENCY_QUANTILES,
    THRESHOLD_BOUND_RECORDS,
    bound_comparison_value,
)

# Design D4 (Rob, 2026-10-27): slow signals measured over about 30 days; neither pages.
# Fixed: the manifest's alerting.for_duration overrides apply to dependency
# templates only, never to these.
BREACH_SEVERITY = "warning"
BREACH_FOR = "15m"
NOT_EVALUABLE_SEVERITY = "info"
NOT_EVALUABLE_FOR = "1h"

_TYPE_NAMES = {"calibration": "Calibration", "feedback_latency": "FeedbackLatency"}
_BOUND_NAMES = {
    "maximum_expected_calibration_error": "ECE",
    "maximum_brier_score": "Brier",
    "maximum_p50": "P50",
    "maximum_p90": "P90",
}


def build_judgment_threshold_alerts(manifest: ReliabilityManifest) -> list[AlertRule]:
    """Build the Breach and NotEvaluable alerts for every declared bound, in manifest order."""
    alerts: list[AlertRule] = []
    for threshold in manifest.get_judgment_thresholds():
        records = THRESHOLD_BOUND_RECORDS.get(threshold.type, {})
        for bound in threshold.bounds:
            record = records.get(bound)
            if record is not None:
                alerts.extend(_bound_alerts(manifest.name, threshold, bound, record))
    return alerts


def alert_names(threshold_type: str, bound: str) -> tuple[str, str]:
    """The (Breach, NotEvaluable) alert names for one bound that has a recording rule."""
    name = f"AIGate{_TYPE_NAMES[threshold_type]}{_BOUND_NAMES[bound]}"
    return f"{name}Breach", f"{name}NotEvaluable"


def _bound_alerts(
    service: str, threshold: JudgmentThreshold, bound: str, record: str
) -> list[AlertRule]:
    value = bound_comparison_value(threshold.bounds, bound)
    series = f'{record}{{service="{service}",target="{value}"}}'
    breach_name, not_evaluable_name = alert_names(threshold.type, bound)
    quantile = FEEDBACK_LATENCY_QUANTILES.get(bound)
    if quantile is None:
        breach_expr = f"{series} > {value}"
        breach_description = (
            f"{record} is {{{{ $value }}}}, above the declared {bound} of "
            f"{value} (OPENSRM-CORE-v2 §5.5.6 E1)."
        )
    else:
        breach_expr = f"{series} < {quantile}"
        breach_description = (
            f"Only {{{{ $value }}}} of ground truth arrived within {value}s, below "
            f"{quantile}, so the quantile exceeds the declared {bound} "
            "(OPENSRM-CORE-v2 §5.5.6 E1)."
        )
    labels = {"threshold_type": threshold.type, "bound": bound}
    return [
        AlertRule(
            name=breach_name,
            expr=breach_expr,
            duration=BREACH_FOR,
            severity=BREACH_SEVERITY,
            labels={**labels, "severity": BREACH_SEVERITY},
            annotations={
                "summary": f"{service}: {threshold.type} {bound} breached",
                "description": breach_description,
            },
            technology="judgment_threshold",
            category="judgment",
        ),
        AlertRule(
            name=not_evaluable_name,
            expr=f"absent({series}) or ({series} != {series})",
            duration=NOT_EVALUABLE_FOR,
            severity=NOT_EVALUABLE_SEVERITY,
            labels={**labels, "severity": NOT_EVALUABLE_SEVERITY},
            annotations={
                "summary": f"{service}: {threshold.type} {bound} not evaluable",
                "description": (
                    f"{record} has no value, so {bound} cannot be evaluated. "
                    "Not evaluable is not within bounds (OPENSRM-CORE-v2 §5.5.6 E3)."
                ),
            },
            technology="judgment_threshold",
            category="judgment",
        ),
    ]
