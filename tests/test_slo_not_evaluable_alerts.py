"""One NotEvaluable alert per SLO with a recorded value (opensrm-r0bx, ruling 2).

A generated ratio is absent when there is nothing to divide by, so a
service that serves nothing breaches nothing. The NotEvaluable alert is what
makes that silence visible: always on, severity info, for 1h,
``absent(R) or (R != R)`` on generate's own series R (the D4 pattern of the
judgment-threshold alerts).

Fixture provenance: the manifests are the shipped examples in examples/,
loaded from disk unmodified. Which SLOs have a recorded value is decided here from
the manifest (its kind, its judgment type), not read back from the alert
builder. The input series follow the Prometheus client exposition, as in
test_recording_rules_evaluated.py; ``alert_rule_test`` and ``exp_alerts``
are the Prometheus "Unit testing for rules" documentation's.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import pytest
from nthlayer_common.manifest import ReliabilityManifest, load_manifest

from nthlayer_generate.core.slo_kind import slo_kind
from nthlayer_generate.generators.alerts import generate_alerts_from_manifest
from nthlayer_generate.generators.slo_not_evaluable_alerts import (
    ALERT_NAME,
    build_slo_not_evaluable_alerts,
)
from nthlayer_generate.recording_rules import build_recording_rules_from_manifest
from nthlayer_generate.validation.promtool import run_rule_tests

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
SERVICES = EXAMPLES / "services"
SHIPPED = sorted(SERVICES.glob("*.yaml")) + sorted(
    (EXAMPLES / "opensrm").glob("*.reliability.yaml")
)
# A collection-time list that came out empty would skip its tests, not fail them.
assert SHIPPED

PAYMENT_API = SERVICES / "payment-api.yaml"
CHECKOUT = SERVICES / "checkout-service.yaml"
AI_GATE = EXAMPLES / "opensrm" / "ai-gate.reliability.yaml"
WORKER = EXAMPLES / "opensrm" / "worker.reliability.yaml"

# Kinds whose SLO value is a rule generate writes; freshness, lag and custom
# get no rule (ruling D5) and so nothing to watch.
RULE_KINDS = ("availability", "latency", "error_rate", "throughput")
JUDGMENT_RATIO_TYPES = ("reversal_rate", "high_confidence_failure")


def _load(path: Path) -> ReliabilityManifest:
    return load_manifest(path, suppress_deprecation_warning=True)


def _expected_slos(manifest: ReliabilityManifest) -> list[str]:
    standard = [s.name for s in manifest.get_standard_slos() if slo_kind(s) in RULE_KINDS]
    judgment = [
        s.name for s in manifest.get_judgment_slos() if s.judgment_type in JUDGMENT_RATIO_TYPES
    ]
    return standard + judgment


@pytest.mark.parametrize("path", SHIPPED, ids=lambda p: p.name)
def test_every_slo_with_a_recorded_value_gets_exactly_one_alert(path: Path) -> None:
    manifest = _load(path)
    alerts = build_slo_not_evaluable_alerts(manifest)
    assert [a.labels["slo"] for a in alerts] == _expected_slos(manifest)
    for alert in alerts:
        assert alert.name == ALERT_NAME
        # Always on, and never a page (ruling 2, on design D4).
        assert alert.severity == "info"
        assert alert.labels["severity"] == "info"
        assert alert.duration == "1h"


def test_the_shipped_corpus_has_slos_of_every_kind() -> None:
    # The parametrised test above would pass on a corpus with no SLOs.
    kinds: set[str] = set()
    for path in SHIPPED:
        manifest = _load(path)
        kinds |= {str(slo_kind(s)) for s in manifest.get_standard_slos()}
        kinds |= {str(s.judgment_type) for s in manifest.get_judgment_slos()}
    assert kinds >= set(RULE_KINDS) | set(JUDGMENT_RATIO_TYPES)


@pytest.mark.parametrize("path", SHIPPED, ids=lambda p: p.name)
def test_each_alert_reads_a_series_generate_records(path: Path) -> None:
    # absent() on a series nothing records would fire for ever; a typo in
    # the record would look like a quiet service.
    manifest = _load(path)
    recorded = [
        (rule.record, rule.labels)
        for group in build_recording_rules_from_manifest(manifest)
        for rule in group.rules
    ]
    for alert in build_slo_not_evaluable_alerts(manifest):
        series = alert.expr.split("absent(", 1)[1].split(")", 1)[0]
        record, _, matchers = series.partition("{")
        wanted = dict(m.split("=", 1) for m in matchers.rstrip("}").split(","))
        wanted = {k: v.strip('"') for k, v in wanted.items()}
        assert alert.expr == f"absent({series}) or ({series} != {series})"
        assert any(
            name == record and all(labels.get(k) == v for k, v in wanted.items())
            for name, labels in recorded
        ), f"{alert.labels['slo']}: no rule records {series}"


def test_an_slo_with_its_own_queries_is_watched_on_its_own_ratio() -> None:
    # checkout-service's availability declares good/total queries; its
    # budget comes from slo:sli:ratio (ruling Z3), so that is the series
    # whose silence matters.
    (alert,) = [
        a for a in build_slo_not_evaluable_alerts(_load(CHECKOUT)) if a.labels["slo"] == "availability"
    ]
    assert "slo:sli:ratio{" in alert.expr
    assert "slo:availability:ratio" not in alert.expr


@pytest.mark.parametrize("tier", ["critical", "standard", "low"])
def test_the_alerts_are_written_whatever_the_tier(tier: str, tmp_path: Path) -> None:
    # Tier filtering drops info alerts for standard and low services; an
    # always-on alert must not go through it.
    manifest = dataclasses.replace(_load(PAYMENT_API), tier=tier)
    alerts = generate_alerts_from_manifest(manifest, output_file=None, quiet=True)
    mine = [a for a in alerts if a.name == ALERT_NAME]
    assert [a.labels["slo"] for a in mine] == ["availability", "latency-p95", "latency-p99"]
    assert {a.labels["service"] for a in mine} == {"payment-api"}


def test_a_manifest_with_no_dependencies_still_gets_them() -> None:
    # api-minimal.yaml declares SLOs and no Dependencies resource.
    manifest = _load(SERVICES / "api-minimal.yaml")
    alerts = generate_alerts_from_manifest(manifest, output_file=None, quiet=True)
    assert [a.name for a in alerts] == [ALERT_NAME, ALERT_NAME]


# --- what the alerts do, evaluated by promtool ------------------------------


def _groups(manifest: ReliabilityManifest) -> list[dict[str, Any]]:
    recording = [g.to_dict() for g in build_recording_rules_from_manifest(manifest)]
    alerts = [a.to_prometheus() for a in build_slo_not_evaluable_alerts(manifest)]
    return [*recording, {"name": "not_evaluable", "rules": alerts}]


def _is_firing(groups: list[dict[str, Any]], input_series: list[dict[str, str]], slo: str) -> bool:
    """Whether ``slo``'s NotEvaluable alert is firing after two hours.

    promtool can only assert an exact result, so the question is asked
    twice, firing and not firing, and exactly one answer must hold: a rule
    file that does not load fails both.
    """
    count = f'count(ALERTS{{alertname="{ALERT_NAME}",alertstate="firing",slo="{slo}"}})'
    outcomes = {}
    for state, samples in (("firing", [{"labels": "{}", "value": 1}]), ("quiet", [])):
        result = run_rule_tests(
            groups,
            [
                {
                    "interval": "1m",
                    "input_series": input_series,
                    "promql_expr_test": [
                        {"expr": count, "eval_time": "2h", "exp_samples": samples}
                    ],
                }
            ],
        )
        assert result.status.value != "unavailable", result.reason
        outcomes[state] = result.passed
    assert outcomes["firing"] != outcomes["quiet"], (slo, outcomes)
    return outcomes["firing"]


def _firing(manifest: ReliabilityManifest, input_series: list[dict[str, str]]) -> list[str]:
    """The SLOs whose NotEvaluable alert is firing, with the recording rules loaded."""
    groups = _groups(manifest)
    return [
        alert.labels["slo"]
        for alert in build_slo_not_evaluable_alerts(manifest)
        if _is_firing(groups, input_series, alert.labels["slo"])
    ]


def _counter(series: str, per_minute: int) -> dict[str, str]:
    return {"series": series, "values": f"0+{per_minute}x120"}


def _flat(series: str) -> dict[str, str]:
    return {"series": series, "values": "7+0x120"}


_HISTOGRAM = "http_request_duration_seconds"
_PAYMENT_TRAFFIC = [
    _counter('http_requests_total{service="payment-api",status="200"}', 100),
    _counter(f'{_HISTOGRAM}_bucket{{service="payment-api",le="0.5"}}', 90),
    _counter(f'{_HISTOGRAM}_bucket{{service="payment-api",le="1.0"}}', 99),
    _counter(f'{_HISTOGRAM}_count{{service="payment-api"}}', 100),
]


def test_under_traffic_no_alert_fires() -> None:
    assert _firing(_load(PAYMENT_API), _PAYMENT_TRAFFIC) == []


def test_flat_counters_fire_every_slo() -> None:
    flat = [_flat(s["series"]) for s in _PAYMENT_TRAFFIC]
    assert _firing(_load(PAYMENT_API), flat) == ["availability", "latency-p95", "latency-p99"]


def test_no_counters_fire_every_slo() -> None:
    unrelated = [_counter('http_requests_total{service="someone-else",status="200"}', 100)]
    assert _firing(_load(PAYMENT_API), unrelated) == ["availability", "latency-p95", "latency-p99"]


def test_only_the_silent_slo_fires() -> None:
    # Requests are counted; the latency histogram is missing.
    requests_only = _PAYMENT_TRAFFIC[:1]
    assert _firing(_load(PAYMENT_API), requests_only) == ["latency-p95", "latency-p99"]


def test_a_missing_throughput_rate_fires_and_a_low_one_does_not() -> None:
    # worker.reliability.yaml: availability, throughput (minimum 100/s) and
    # error_rate. Below the minimum is a breach, not a silence.
    manifest = _load(WORKER)
    slow = [_counter('http_requests_total{service="email-sender",status="200"}', 60)]
    assert _firing(manifest, slow) == []
    unrelated = [_counter('http_requests_total{service="someone-else",status="200"}', 60)]
    assert _firing(manifest, unrelated) == ["availability", "throughput", "error_rate"]


def test_an_ai_gate_with_no_decisions_fires_its_judgment_ratios() -> None:
    manifest = _load(AI_GATE)
    http_only = [
        _counter('http_requests_total{service="fraud-detector",status="200"}', 100),
        _counter(f'{_HISTOGRAM}_bucket{{service="fraud-detector",le="0.1"}}', 100),
        _counter(f'{_HISTOGRAM}_count{{service="fraud-detector"}}', 100),
    ]
    assert _firing(manifest, http_only) == ["reversal_rate", "high_confidence_failure"]


def test_a_nan_value_fires_the_alert() -> None:
    # generate's own ratios are never NaN now, but the alert reads a recorded
    # series by name, and whatever writes NaN there (an older rule file still
    # loaded, a remote-written series) leaves the SLO just as unevaluable.
    # NaN is the one value that is not equal to itself: `R != R`. Only the
    # alert rules are loaded, and the series is given directly.
    manifest = _load(PAYMENT_API)
    alerts = [a.to_prometheus() for a in build_slo_not_evaluable_alerts(manifest)]
    series = 'slo:availability:ratio{service="payment-api",slo="availability",objective="99.95"}'

    groups = [{"name": "not_evaluable", "rules": alerts}]

    def firing(values: str) -> bool:
        return _is_firing(groups, [{"series": series, "values": values}], "availability")

    assert firing("NaN+0x120")
    assert not firing("0.999+0x120")
