"""What the generated recording rules evaluate to (opensrm-r0bx).

Every other recording-rule test here reads rule names and expression text.
These hand the generated rules to ``promtool test rules`` with synthetic
series and assert on the samples that come out, so a rule that is named
correctly and computes the wrong thing fails. A missing or other-version
promtool fails these tests; it never skips them (Rob, 2026-11-25).

Fixture provenance: the manifests are the shipped examples in examples/,
loaded from disk unmodified. The input series are the exposition a
Prometheus HTTP client library writes: a ``http_requests_total`` counter
labelled by ``status``, and a ``http_request_duration_seconds`` histogram
(``_bucket`` with a cumulative ``le``, ``_count``), per the Prometheus
"Metric types" and "Histograms and summaries" documentation. The unit-test
shape (``input_series``, expanding notation, ``promql_expr_test``,
``exp_samples``) is the Prometheus "Unit testing for rules" documentation.
An expression test with no ``exp_samples`` expects no sample at all.

The AI-gate source series (``ai_gate_decisions_total`` with ``reversed``,
``confidence_bucket`` and ``outcome`` labels, and the
``ai_gate_feedback_latency_seconds`` histogram) have no exposition document
to copy: the series here are the ones the generated rules select, with the
label values those rules do NOT select (``reversed="false"``,
``outcome="correct"``) chosen as the plain opposites. opensrm/spec/v1
§11.5's example reads a separate ``ai_gate_reversals_total`` counter, and
nthlayer-common's THRESHOLD_SERIES names ``gen_ai_feedback_latency_seconds``;
neither difference is settled here.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from nthlayer_common.manifest import ReliabilityManifest, load_manifest

from nthlayer_generate.recording_rules import build_recording_rules_from_manifest
from nthlayer_generate.validation.promtool import run_rule_tests

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
SERVICES = EXAMPLES / "services"
SHIPPED = sorted(SERVICES.glob("*.yaml")) + sorted(
    (EXAMPLES / "opensrm").glob("*.reliability.yaml")
)

# A collection-time list that came out empty would skip its tests, not fail them.
assert SHIPPED

# payment-api.yaml: availability (99.95, 30d), latency-p95 (99.0, 30d,
# threshold_ms 500) and latency-p99 (95.0, 30d, threshold_ms 1000).
PAYMENT_API = SERVICES / "payment-api.yaml"
# checkout-service.yaml: availability (99.95, 30d) with its own good/total
# queries: sum(rate(http_requests_total{...,status!~"5.."}[5m])) over
# sum(rate(http_requests_total{...}[5m])).
CHECKOUT = SERVICES / "checkout-service.yaml"
# api-critical.reliability.yaml (srm/v1, service payment-api): error_rate, 7d.
API_CRITICAL = EXAMPLES / "opensrm" / "api-critical.reliability.yaml"
# ai-gate.reliability.yaml (srm/v1, service fraud-detector): reversal_rate and
# high_confidence_failure over 7d; feedback_latency maximum_p50 3600s.
AI_GATE = EXAMPLES / "opensrm" / "ai-gate.reliability.yaml"

EVAL_TIME = "1h"


def _load(path: Path) -> ReliabilityManifest:
    return load_manifest(path, suppress_deprecation_warning=True)


def _rule_groups(manifest: ReliabilityManifest) -> list[dict[str, Any]]:
    return [group.to_dict() for group in build_recording_rules_from_manifest(manifest)]


def _expect(expr: str, samples: list[dict[str, Any]]) -> dict[str, Any]:
    return {"expr": expr, "eval_time": EVAL_TIME, "exp_samples": samples}


def _evaluate(
    manifest: ReliabilityManifest,
    input_series: list[dict[str, str]],
    expectations: list[dict[str, Any]],
) -> None:
    result = run_rule_tests(
        _rule_groups(manifest),
        [{"interval": "1m", "input_series": input_series, "promql_expr_test": expectations}],
    )
    assert result.passed, f"{result.status.value}: {result.reason}\n{result.output}"


def _counter(series: str, per_minute: int) -> dict[str, str]:
    """A counter that grows by ``per_minute`` every minute for an hour."""
    return {"series": series, "values": f"0+{per_minute}x60"}


def _flat(series: dict[str, str]) -> dict[str, str]:
    """The same series, scraped for an hour and never incremented."""
    return {"series": series["series"], "values": "7+0x60"}


# --- zero traffic: one behaviour, absent, for every ratio (rulings 1, 3) ----


@dataclass(frozen=True)
class Ratio:
    """One generated ratio, and healthy traffic that never fails.

    ``traffic`` is traffic with no failure series at all: every request
    succeeds, so the counter of failures has never been created.
    ``expected`` is what each expression must then evaluate to. The same
    expressions must return nothing when the counters are flat, and nothing
    when there are no counters.
    """

    manifest: Path
    traffic: tuple[dict[str, str], ...]
    expected: dict[str, float]
    # The failure counter, for the flat case: there it exists (a failure
    # happened once) and, like the rest, has stopped moving.
    failures: str = ""


_PAYMENT_HISTOGRAM = "http_request_duration_seconds"

RATIOS = {
    "availability": Ratio(
        PAYMENT_API,
        (_counter('http_requests_total{service="payment-api",status="200"}', 100),),
        {
            'slo:availability:ratio{slo="availability"}': 1,
            'slo:error_budget_remaining:ratio{slo="availability"}': 1,
        },
        failures='http_requests_total{service="payment-api",status="500"}',
    ),
    "latency": Ratio(
        PAYMENT_API,
        # Every request within 500ms.
        (
            _counter(f'{_PAYMENT_HISTOGRAM}_bucket{{service="payment-api",le="0.5"}}', 100),
            _counter(f'{_PAYMENT_HISTOGRAM}_bucket{{service="payment-api",le="+Inf"}}', 100),
            _counter(f'{_PAYMENT_HISTOGRAM}_count{{service="payment-api"}}', 100),
        ),
        {
            'slo:latency:ratio{slo="latency-p95"}': 1,
            'slo:error_budget_remaining:ratio{slo="latency-p95"}': 1,
        },
    ),
    # srm/v1 error_rate targets are maxima, so this SLO has no budget rule
    # (opensrm-t13c); the ratio is the failed fraction.
    "error_rate": Ratio(
        API_CRITICAL,
        (_counter('http_requests_total{service="payment-api",status="200"}', 100),),
        {'slo:error_rate:ratio{slo="error_rate"}': 0},
        failures='http_requests_total{service="payment-api",status="500"}',
    ),
    "own_queries": Ratio(
        CHECKOUT,
        (_counter('http_requests_total{service="checkout-service",status="200"}', 100),),
        {
            'slo:sli:ratio{slo="availability"}': 1,
            'slo:error_budget_remaining:ratio{slo="availability"}': 1,
        },
        failures='http_requests_total{service="checkout-service",status="500"}',
    ),
    "http_errors": Ratio(
        PAYMENT_API,
        (_counter('http_requests_total{service="payment-api",status="200"}', 100),),
        {"service:http_errors:rate5m": 0},
        failures='http_requests_total{service="payment-api",status="500"}',
    ),
    "reversal_rate": Ratio(
        AI_GATE,
        (
            _counter(
                'ai_gate_decisions_total{service="fraud-detector",reversed="false",'
                'confidence_bucket="high",outcome="correct"}',
                50,
            ),
        ),
        {"ai_gate:reversal_rate:ratio": 0},
        failures=(
            'ai_gate_decisions_total{service="fraud-detector",reversed="true",'
            'confidence_bucket="high",outcome="incorrect"}'
        ),
    ),
    "high_confidence_failure": Ratio(
        AI_GATE,
        (
            _counter(
                'ai_gate_decisions_total{service="fraud-detector",reversed="false",'
                'confidence_bucket="high",outcome="correct"}',
                50,
            ),
        ),
        {"ai_gate:high_confidence_failure:ratio": 0},
        failures=(
            'ai_gate_decisions_total{service="fraud-detector",reversed="true",'
            'confidence_bucket="high",outcome="incorrect"}'
        ),
    ),
    # Ground truth for every decision arrives within the hour (le="3600.0").
    "feedback_latency": Ratio(
        AI_GATE,
        (
            _counter(
                'ai_gate_feedback_latency_seconds_bucket{service="fraud-detector",le="3600.0"}', 10
            ),
            _counter(
                'ai_gate_feedback_latency_seconds_bucket{service="fraud-detector",le="+Inf"}', 10
            ),
            _counter('ai_gate_feedback_latency_seconds_count{service="fraud-detector"}', 10),
        ),
        {
            "ai_gate:feedback_latency:bucket": 1,
            "ai_gate:feedback_latency:p50_within_bound_30d": 1,
        },
    ),
}


assert sorted(RATIOS)


def _values(ratio: Ratio) -> list[dict[str, Any]]:
    # sum() drops the name and the labels: the value is the claim.
    return [
        _expect(f"sum({expr})", [{"labels": "{}", "value": value}])
        for expr, value in ratio.expected.items()
    ]


def _nothing(ratio: Ratio) -> list[dict[str, Any]]:
    return [_expect(expr, []) for expr in ratio.expected]


@pytest.mark.parametrize("name", sorted(RATIOS))
def test_traffic_with_no_failure_series_has_a_ratio_and_a_full_budget(name: str) -> None:
    ratio = RATIOS[name]
    _evaluate(_load(ratio.manifest), list(ratio.traffic), _values(ratio))


@pytest.mark.parametrize("name", sorted(RATIOS))
def test_flat_counters_leave_the_ratio_absent(name: str) -> None:
    # The service is scraped and serves nothing: 0 / 0. Absent, not NaN:
    # the same expressions that had values above return no sample.
    ratio = RATIOS[name]
    flat = [_flat(series) for series in ratio.traffic]
    if ratio.failures:
        flat.append({"series": ratio.failures, "values": "3+0x60"})
    _evaluate(_load(ratio.manifest), flat, _nothing(ratio))


@pytest.mark.parametrize("name", sorted(RATIOS))
def test_no_counters_leave_the_ratio_absent(name: str) -> None:
    # The scrape target is gone. An unrelated series keeps the test from
    # being an empty TSDB, where nothing could be anything but absent.
    ratio = RATIOS[name]
    unrelated = [_counter('http_requests_total{service="someone-else",status="200"}', 100)]
    _evaluate(_load(ratio.manifest), unrelated, _nothing(ratio))


def test_the_ratio_cases_cover_every_ratio_the_shipped_corpus_generates() -> None:
    # A new ratio rule must come with its zero-traffic case. A ratio is any
    # rule the builder guards with `> 0`.
    expected_records = {expr.split("{")[0] for r in RATIOS.values() for expr in r.expected}
    guarded = set()
    for path in SHIPPED:
        for group in build_recording_rules_from_manifest(_load(path)):
            guarded |= {rule.record for rule in group.rules if " > 0)" in rule.expr}
    assert guarded, "no guarded ratio found: the `> 0` marker moved"
    # The budget is derived from a ratio, not guarded itself.
    assert guarded == expected_records - {"slo:error_budget_remaining:ratio"}


# --- a numerator with no series is zero, when there is traffic (ruling 1) ---


def test_only_failures_is_zero_availability_not_absent() -> None:
    # Every request fails: the success selector matches no series.
    _evaluate(
        _load(PAYMENT_API),
        [_counter('http_requests_total{service="payment-api",status="503"}', 100)],
        [
            _expect('sum(slo:availability:ratio{slo="availability"})', [_value(0)]),
            _expect("sum(service:http_errors:rate5m)", [_value(1)]),
        ],
    )


def test_no_request_under_the_bound_is_zero_latency_compliance() -> None:
    # The histogram has no bucket at the declared bound (le="0.5").
    histogram = _PAYMENT_HISTOGRAM
    _evaluate(
        _load(PAYMENT_API),
        [
            _counter(f'{histogram}_bucket{{service="payment-api",le="+Inf"}}', 100),
            _counter(f'{histogram}_count{{service="payment-api"}}', 100),
        ],
        [_expect('sum(slo:latency:ratio{slo="latency-p95"})', [_value(0)])],
    )


def test_ai_gate_ratios_count_reversals_and_confident_failures() -> None:
    # 50 decisions a minute: 5 reversed, and of the 20 high-confidence ones
    # 4 were wrong.
    def decisions(reversed_: str, bucket: str, outcome: str, per_minute: int) -> dict[str, str]:
        return _counter(
            f'ai_gate_decisions_total{{service="fraud-detector",reversed="{reversed_}",'
            f'confidence_bucket="{bucket}",outcome="{outcome}"}}',
            per_minute,
        )

    _evaluate(
        _load(AI_GATE),
        [
            decisions("false", "low", "correct", 29),
            decisions("true", "low", "incorrect", 1),
            decisions("false", "high", "correct", 16),
            decisions("true", "high", "incorrect", 4),
        ],
        [
            _expect("sum(ai_gate:reversal_rate:ratio)", [_value(0.1)]),
            _expect("sum(ai_gate:high_confidence_failure:ratio)", [_value(0.2)]),
        ],
    )


def _value(value: float) -> dict[str, Any]:
    return {"labels": "{}", "value": value}


# --- latency: the ratio's two sides carry different labels (ruling 7) -------


def test_canned_latency_ratio_has_a_value_under_traffic() -> None:
    # 100 requests a minute, 82 of them within 500ms and 97 within 1s.
    # slo:latency_requests_fast carries a `threshold` label that
    # slo:latency_requests_total does not; a bare `/` matched nothing, so
    # no canned latency SLO had a ratio or a budget.
    manifest = _load(PAYMENT_API)
    histogram = "http_request_duration_seconds"
    _evaluate(
        manifest,
        [
            _counter(f'{histogram}_bucket{{service="payment-api",le="0.5"}}', 82),
            _counter(f'{histogram}_bucket{{service="payment-api",le="1.0"}}', 97),
            _counter(f'{histogram}_bucket{{service="payment-api",le="+Inf"}}', 100),
            _counter(f'{histogram}_count{{service="payment-api"}}', 100),
        ],
        [
            _expect(
                "slo:latency:ratio",
                [
                    {
                        "labels": 'slo:latency:ratio{service="payment-api",slo="latency-p95",'
                        'objective="99.0"}',
                        "value": 0.82,
                    },
                    {
                        "labels": 'slo:latency:ratio{service="payment-api",slo="latency-p99",'
                        'objective="95.0"}',
                        "value": 0.97,
                    },
                ],
            ),
            # The fast count keeps its threshold label (dashboards read it).
            _expect(
                'count(slo:latency_requests_fast:30d{threshold="500ms"})',
                [{"labels": "{}", "value": 1}],
            ),
            # 1 - ((1 - 0.97) / (1 - 0.95)) = 0.4 of the budget left.
            _expect(
                'slo:error_budget_remaining:ratio{slo="latency-p99"}',
                [
                    {
                        "labels": 'slo:error_budget_remaining:ratio{service="payment-api",'
                        'slo="latency-p99",objective="95.0"}',
                        "value": 0.4,
                    }
                ],
            ),
        ],
    )


def _ratio_operands(expr: str, records: dict[str, set[frozenset[str]]]) -> list[str]:
    """The recorded series ``expr`` reads, when it divides one by another."""
    if " / " not in expr:
        return []
    return sorted(name for name in records if f"{name}{{" in expr)


def test_no_ratio_divides_recorded_series_with_different_labels_unmatched() -> None:
    # PromQL's `/` pairs samples whose label sets are equal. Two recorded
    # series with different label keys never pair, and the ratio is absent
    # for ever, unless the expression says what to match on.
    checked = 0
    for path in SHIPPED:
        rules = [r for g in build_recording_rules_from_manifest(_load(path)) for r in g.rules]
        records: dict[str, set[frozenset[str]]] = {}
        for rule in rules:
            records.setdefault(rule.record, set()).add(frozenset(rule.labels))
        for rule in rules:
            operands = _ratio_operands(rule.expr, records)
            if len(operands) < 2:
                continue
            checked += 1
            label_keys = {keys for name in operands for keys in records[name]}
            matched = " on(" in rule.expr or " ignoring(" in rule.expr
            assert len(label_keys) == 1 or matched, (
                f"{path.name}: {rule.record} divides {operands}, whose label keys differ "
                f"({sorted(sorted(k) for k in label_keys)}), with no on()/ignoring(): "
                f"{rule.expr}"
            )
    # The shipped corpus has availability, latency and error-rate ratios;
    # a selection that found none would pass for the wrong reason.
    assert checked >= 10, checked


# --- throughput compliance: 1, 0, or nothing (ruling 4) ---------------------

# worker.reliability.yaml (srm/v1, service email-sender): throughput, target
# 100 requests a second.
WORKER = EXAMPLES / "opensrm" / "worker.reliability.yaml"

COMPLIANCE = "sum(slo:throughput:compliance)"


@pytest.mark.parametrize(
    ("per_minute", "compliant"),
    [
        (7200, 1),  # 120 a second, above the minimum of 100
        (6000, 1),  # exactly the minimum
        (3000, 0),  # 50 a second
    ],
)
def test_throughput_compliance_is_one_or_zero(per_minute: int, compliant: int) -> None:
    # It used to be the rate itself when compliant (no `bool`), so a
    # dashboard reading "1 = compliant" saw 120.
    _evaluate(
        _load(WORKER),
        [_counter('http_requests_total{service="email-sender"}', per_minute)],
        [_expect(COMPLIANCE, [_value(compliant)])],
    )


def test_a_scraped_service_doing_nothing_is_below_its_minimum() -> None:
    # Unlike a ratio, a rate of zero is a measurement: zero is below 100.
    _evaluate(
        _load(WORKER),
        [_flat(_counter('http_requests_total{service="email-sender"}', 0))],
        [_expect(COMPLIANCE, [_value(0)])],
    )


def test_throughput_compliance_is_absent_without_a_rate() -> None:
    # It used to be 0 (`or vector(0)`): no data read as a breach.
    _evaluate(
        _load(WORKER),
        [_counter('http_requests_total{service="someone-else"}', 7200)],
        [_expect("slo:throughput:compliance", []), _expect("slo:throughput:rate5m", [])],
    )


# --- the counts themselves, when the service is gone -------------------------

COUNT_RECORDS = {
    PAYMENT_API: ("slo:requests_success:30d", "slo:latency_requests_fast:30d"),
    API_CRITICAL: ("slo:error_requests_failed:7d",),
    AI_GATE: ("ai_gate:decisions_reversed:7d", "ai_gate:high_confidence_failures:7d"),
}


assert sorted(COUNT_RECORDS)


@pytest.mark.parametrize("path", sorted(COUNT_RECORDS), ids=lambda p: p.name)
def test_a_count_is_zero_filled_only_where_its_total_exists(path: Path) -> None:
    # `(count or (0 * total))` is zero where the total has a series and
    # nothing where it has none. `or vector(0)` would look the same in every
    # ratio (the guard blanks them), while recording a count of 0 for a
    # service that is not there.
    manifest = _load(path)
    unrelated = [_counter('http_requests_total{service="someone-else",status="200"}', 100)]
    _evaluate(manifest, unrelated, [_expect(record, []) for record in COUNT_RECORDS[path]])


def test_a_zero_filled_count_is_present_under_traffic() -> None:
    # The other half: with requests and no 5xx series, the failed count is a
    # recorded 0, not a missing series.
    _evaluate(
        _load(API_CRITICAL),
        [_counter('http_requests_total{service="payment-api",status="200"}', 100)],
        [_expect("sum(slo:error_requests_failed:7d)", [_value(0)])],
    )
