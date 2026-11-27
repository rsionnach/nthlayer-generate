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
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from nthlayer_common.manifest import ReliabilityManifest, load_manifest

from nthlayer_generate.recording_rules import build_recording_rules_from_manifest
from nthlayer_generate.validation.promtool import run_rule_tests

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
SERVICES = EXAMPLES / "services"
SHIPPED = sorted(SERVICES.glob("*.yaml")) + sorted(
    (EXAMPLES / "opensrm").glob("*.reliability.yaml")
)

# payment-api.yaml: availability (99.95, 30d), latency-p95 (99.0, 30d,
# threshold_ms 500) and latency-p99 (95.0, 30d, threshold_ms 1000).
PAYMENT_API = SERVICES / "payment-api.yaml"

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
