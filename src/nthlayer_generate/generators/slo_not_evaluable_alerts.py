"""One NotEvaluable alert per SLO that generate records a value for (opensrm-r0bx).

A generated ratio is absent when there is nothing to divide by: a service
that serves nothing has no availability, and so breaches nothing. That is
the right value and a dangerous silence, because the gap opens during a
total outage. ``SLONotEvaluable`` makes it visible: it fires when the SLO's
series is absent or NaN for an hour.

Rob, 2026-11-25 (ruling 2), on the judgment-threshold alerts' design D4:
always on, severity info, ``for: 1h``, never a page. It reads only
generate's own recorded series, never raw metrics. There is no
``slo:sli:no_data`` series. opensrm-razq may later let an author turn the
alert off for an SLO that is expected to go quiet.

Not evaluable is not the same as below a minimum: a throughput SLO whose
rate is zero records compliance 0 and is a breach, not a silence.
"""

from __future__ import annotations

from nthlayer_common.manifest import ReliabilityManifest

from nthlayer_generate.alerts import AlertRule
from nthlayer_generate.generators.judgment_threshold_alerts import (
    NOT_EVALUABLE_FOR,
    NOT_EVALUABLE_SEVERITY,
)
from nthlayer_generate.recording_rules.manifest_builder import slo_value_series

ALERT_NAME = "SLONotEvaluable"


def build_slo_not_evaluable_alerts(manifest: ReliabilityManifest) -> list[AlertRule]:
    """Build one alert per SLO with a recorded value, in manifest order."""
    return [
        AlertRule(
            name=ALERT_NAME,
            expr=f"absent({series}) or ({series} != {series})",
            duration=NOT_EVALUABLE_FOR,
            severity=NOT_EVALUABLE_SEVERITY,
            labels={"slo": slo_name, "severity": NOT_EVALUABLE_SEVERITY},
            annotations={
                "summary": f"{manifest.name}: SLO {slo_name} not evaluable",
                "description": (
                    f"{series.split('{', 1)[0]} has no value or is NaN, so the SLO cannot be "
                    "evaluated. The service may be receiving no traffic, or its metrics "
                    "are missing. Not evaluable is not within objective."
                ),
            },
            technology="slo",
            category="slo",
        )
        for slo_name, series in slo_value_series(manifest)
    ]
