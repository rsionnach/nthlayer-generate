"""An error budget for every request-ratio classical SLO (opensrm-zo0o).

Rulings (Rob, 2026-11-03/04):

- Z1: every classical SLO is good/total against its objective, so generate
  writes nthlayer-common's ERROR_BUDGET_REMAINING for each.
- D5: only the request-ratio kinds (availability, latency, error_rate) get
  one; throughput, freshness, lag and custom do not (opensrm-vcxm).
- Z3: an SLO with its own good/total (or bad/total) queries — OpenSLO's
  ratioMetric, or the legacy indicators[].success_ratio — has them recorded
  as-is, and its budget is built from them, whatever its kind. Otherwise the
  budget comes from the kind's canned good ratio.

Fixture provenance: the legacy manifests are the shipped examples in
examples/services/ (loaded from disk, unmodified). The v2 manifests below
are the envelope of opensrm/spec/v2/examples/services/api.yaml with inline
OpenSLO v1 SLO documents; each ratioMetric follows the vendored OpenSLO
excerpt nthlayer-common/tests/fixtures/openslo/ratio-metric-v1.md ("{good,
total}, {bad, total} or raw"; a Prometheus metricSource's spec.query).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from nthlayer_common.manifest import ERROR_BUDGET_REMAINING, ReliabilityManifest, load_manifest

from nthlayer_generate.recording_rules import build_recording_rules_from_manifest
from nthlayer_generate.recording_rules.models import RecordingRule

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
SERVICES = EXAMPLES / "services"
SHIPPED = sorted(SERVICES.glob("*.yaml")) + sorted(
    (EXAMPLES / "opensrm").glob("*.reliability.yaml")
)

REQUEST_RATIO_KINDS = ("availability", "latency", "error_rate")


def _load(path: Path) -> ReliabilityManifest:
    return load_manifest(path, suppress_deprecation_warning=True)


def _rules(manifest: ReliabilityManifest) -> list[RecordingRule]:
    return [r for g in build_recording_rules_from_manifest(manifest) for r in g.rules]


def _budgets(manifest: ReliabilityManifest) -> dict[str, list[RecordingRule]]:
    out: dict[str, list[RecordingRule]] = {}
    for rule in _rules(manifest):
        if rule.record == ERROR_BUDGET_REMAINING.metric:
            out.setdefault(str(rule.labels["slo"]), []).append(rule)
    return out


def _sel(record: str, service: str, slo: str) -> str:
    return f'{record}{{service="{service}",slo="{slo}"}}'


def _budget_expr(ratio: str, target: float) -> str:
    # The availability formula as generate has written it since h0at.
    return f"1 - ((1 - {ratio}) / (1 - {target / 100}))"


# --- v2 manifests: api.yaml's envelope, inline OpenSLO documents -----------

_V2_ENVELOPE = """\
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
{slos}
"""

# bad/total, with ${{service}} placeholders the author left for generate.
_V2_BAD_TOTAL_AVAILABILITY = """\
    - apiVersion: openslo/v1
      kind: SLO
      metadata:
        name: checkout-availability
      spec:
        service: checkout-api
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
                    query: sum(rate(http_requests_total{service="${service}",code=~"5.."}[5m]))
              total:
                metricSource:
                  type: Prometheus
                  spec:
                    query: sum(rate(http_requests_total{service="${service}"}[5m]))
        timeWindow:
          - duration: 28d
            isRolling: true
        objectives:
          - displayName: "99.95% of checkout sessions served successfully"
            target: 0.9995
"""

# good/total on a latency SLO: Z3 takes precedence over the canned ratio.
_V2_GOOD_TOTAL_LATENCY = """\
    - apiVersion: openslo/v1
      kind: SLO
      metadata:
        name: checkout-latency-p99
      spec:
        service: checkout-api
        indicator:
          metadata:
            name: latency
          spec:
            ratioMetric:
              counter: true
              good:
                metricSource:
                  type: Prometheus
                  spec:
                    query: sum(rate(http_request_duration_seconds_bucket{service="checkout-api",le="0.5"}[5m]))
              total:
                metricSource:
                  type: Prometheus
                  spec:
                    query: sum(rate(http_request_duration_seconds_count{service="checkout-api"}[5m]))
        timeWindow:
          - duration: 30d
            isRolling: true
        objectives:
          - displayName: "99% of checkout sessions created within 500ms"
            target: 0.99
"""

# No indicator: an error_rate SLO by name, with an OpenSLO good-ratio target.
_V2_ERROR_RATE = """\
    - apiVersion: openslo/v1
      kind: SLO
      metadata:
        name: checkout-error-rate
      spec:
        service: checkout-api
        objectives:
          - displayName: "99.9% of requests do not error"
            target: 0.999
"""

# opensrm/spec/v2/examples/migration/api-full-v2.yaml's payment-api-throughput,
# copied (service renamed to the envelope's): a v2 throughput SLO whose
# objective, 99.0, passes the [50, 100) guard, so only ruling D5 keeps its
# budget out.
_V2_THROUGHPUT = """\
    - apiVersion: openslo/v1
      kind: SLO
      metadata:
        name: checkout-throughput
      spec:
        service: checkout-api
        objectives:
          - displayName: "Sustains 1000 rps over a 1 hour window"
            target: 0.99
"""


def _v2(tmp_path: Path, *slos: str) -> ReliabilityManifest:
    path = tmp_path / "checkout-api.yaml"
    path.write_text(_V2_ENVELOPE.format(slos="".join(slos)))
    return _load(path)


# --- canned budgets --------------------------------------------------------


def test_availability_budget_is_unchanged():
    # payment-api's availability SLO has an indicator query, not a
    # good/total pair, so its budget stays on slo:availability:ratio.
    budgets = _budgets(_load(SERVICES / "payment-api.yaml"))
    (rule,) = budgets["availability"]
    assert rule.expr == (
        '1 - ((1 - slo:availability:ratio{service="payment-api",slo="availability"}) / '
        "(1 - 0.9995))"
    )
    assert rule.labels == {"service": "payment-api", "slo": "availability", "objective": "99.95"}


def test_latency_budget_reads_the_fraction_fast():
    # payment-api latency-p95: legacy latency, objective 99.0, 500ms bound.
    budgets = _budgets(_load(SERVICES / "payment-api.yaml"))
    (rule,) = budgets["latency-p95"]
    assert rule.expr == _budget_expr(_sel("slo:latency:ratio", "payment-api", "latency-p95"), 99.0)
    assert rule.labels == {"service": "payment-api", "slo": "latency-p95", "objective": "99.0"}


def test_error_rate_budget_reads_the_complement_of_the_error_rate(tmp_path: Path):
    manifest = _v2(tmp_path, _V2_ERROR_RATE)
    (rule,) = _budgets(manifest)["checkout-error-rate"]
    complement = f"(1 - {_sel('slo:error_rate:ratio', 'checkout-api', 'checkout-error-rate')})"
    assert rule.expr == _budget_expr(complement, 99.9)
    assert rule.labels["objective"] == "99.9"


def test_canned_paths_write_no_sli_records():
    records = {r.record for r in _rules(_load(SERVICES / "payment-api.yaml"))}
    assert not records & {"slo:sli_good:rate", "slo:sli_total:rate", "slo:sli:ratio"}


# --- Z3: the SLO's own queries ---------------------------------------------


def test_legacy_success_ratio_is_recorded_as_is():
    # analytics-stream processing-availability: indicators[].success_ratio.
    manifest = _load(SERVICES / "analytics-stream.yaml")
    slo = next(s for s in manifest.slos if s.name == "processing-availability")
    by_record = {
        r.record: r for r in _rules(manifest) if r.labels.get("slo") == "processing-availability"
    }

    good = by_record["slo:sli_good:rate"]
    total = by_record["slo:sli_total:rate"]
    # Recorded as-is inside sum(), so each is one series per (service, slo).
    total_expr = f"sum({slo.total_query}\n)"
    assert total.expr == total_expr
    # A good query that matches nothing is zero good, not missing.
    assert good.expr == f"(sum({slo.good_query}\n) or (0 * {total_expr}))"
    assert (
        good.labels
        == total.labels
        == {
            "service": "analytics-stream",
            "slo": "processing-availability",
        }
    )

    ratio = by_record["slo:sli:ratio"]
    assert ratio.expr == (
        f"sum_over_time({_sel('slo:sli_good:rate', 'analytics-stream', 'processing-availability')}[30d])"
        f" / sum_over_time({_sel('slo:sli_total:rate', 'analytics-stream', 'processing-availability')}[30d])"
    )
    assert ratio.labels == {
        "service": "analytics-stream",
        "slo": "processing-availability",
        "objective": "99.5",
    }

    (budget,) = _budgets(manifest)["processing-availability"]
    assert budget.expr == _budget_expr(
        _sel("slo:sli:ratio", "analytics-stream", "processing-availability"), 99.5
    )


def test_own_queries_win_over_the_canned_availability_budget():
    # checkout-service's availability SLO carries a success_ratio; its canned
    # dashboard rules stay, but the budget reads its own queries.
    manifest = _load(SERVICES / "checkout-service.yaml")
    records = {r.record for r in _rules(manifest) if r.labels.get("slo") == "availability"}
    assert "slo:availability:ratio" in records
    (budget,) = _budgets(manifest)["availability"]
    assert "slo:sli:ratio" in budget.expr
    assert "slo:availability:ratio" not in budget.expr


def test_openslo_bad_over_total_records_total_minus_bad(tmp_path: Path):
    manifest = _v2(tmp_path, _V2_BAD_TOTAL_AVAILABILITY)
    by_record = {
        r.record: r for r in _rules(manifest) if r.labels.get("slo") == "checkout-availability"
    }
    total = 'sum(rate(http_requests_total{service="checkout-api"}[5m]))'
    bad = 'sum(rate(http_requests_total{service="checkout-api",code=~"5.."}[5m]))'
    assert by_record["slo:sli_total:rate"].expr == f"sum({total}\n)"
    # A bad query with no series is no errors, not no data (`or vector(0)`).
    assert by_record["slo:sli_good:rate"].expr == (
        f"sum({total}\n) - (sum({bad}\n) or vector(0))"
    )
    # W is the SLO's own window, 28d here, not the 30d default.
    assert "[28d]" in by_record["slo:sli:ratio"].expr
    (budget,) = _budgets(manifest)["checkout-availability"]
    assert budget.expr == _budget_expr(
        _sel("slo:sli:ratio", "checkout-api", "checkout-availability"), 99.95
    )


def test_service_placeholders_are_substituted(tmp_path: Path):
    manifest = _v2(tmp_path, _V2_BAD_TOTAL_AVAILABILITY)
    for rule in _rules(manifest):
        assert "${" not in rule.expr, rule


def test_own_queries_win_over_the_canned_latency_budget(tmp_path: Path):
    manifest = _v2(tmp_path, _V2_GOOD_TOTAL_LATENCY)
    records = {r.record for r in _rules(manifest) if r.labels.get("slo") == "checkout-latency-p99"}
    assert {"slo:latency:ratio", "slo:sli_good:rate", "slo:sli_total:rate", "slo:sli:ratio"} <= (
        records
    )
    (budget,) = _budgets(manifest)["checkout-latency-p99"]
    assert budget.expr == _budget_expr(
        _sel("slo:sli:ratio", "checkout-api", "checkout-latency-p99"), 99.0
    )


# --- which SLOs get one, and how many --------------------------------------


@pytest.mark.parametrize("path", SHIPPED, ids=lambda p: p.name)
def test_exactly_one_budget_per_request_ratio_slo(path: Path):
    manifest = _load(path)
    expected = {
        str(s.name)
        for s in manifest.get_standard_slos()
        if s.slo_type in REQUEST_RATIO_KINDS
        # A canned latency ratio needs the bound the manifest declares; an SLO
        # with its own queries carries it in the good query.
        and not (s.slo_type == "latency" and s.threshold_ms is None and not s.total_query)
    } - V1_UNUSABLE.get(path.name, set())
    budgets = _budgets(manifest)
    assert set(budgets) == expected
    for slo, rules in budgets.items():
        assert len(rules) == 1, (slo, rules)


def test_the_shipped_corpus_covers_every_kind():
    # Guards the parametrised test above against a corpus that stopped
    # exercising a kind: each request-ratio kind, and each kind that must
    # get NO budget, appears at least once.
    kinds = {s.slo_type for p in SHIPPED for s in _load(p).get_standard_slos()}
    assert {*REQUEST_RATIO_KINDS, "throughput", "custom"} <= kinds


@pytest.mark.parametrize(
    ("path", "slo"),
    [
        (EXAMPLES / "opensrm" / "stream.reliability.yaml", "throughput"),
        (SERVICES / "analytics-stream.yaml", "stream-lag"),
        (SERVICES / "search-api.yaml", "search-quality"),
    ],
    ids=["throughput", "custom-lag", "custom-with-query"],
)
def test_non_request_ratio_kinds_get_no_budget(path: Path, slo: str):
    manifest = _load(path)
    assert slo in {s.name for s in manifest.slos}
    assert slo not in _budgets(manifest)


def test_a_v2_throughput_slo_inside_the_guard_still_gets_no_budget(tmp_path: Path):
    """The shipped throughput SLOs (5000, 100) are outside [50, 100), so the
    guard alone would hide a broken D5 branch; this one is inside it."""
    manifest = _v2(tmp_path, _V2_THROUGHPUT)
    (slo,) = [s for s in manifest.slos if s.name == "checkout-throughput"]
    assert slo.slo_type == "throughput" and 50 <= slo.target < 100
    assert "checkout-throughput" not in _budgets(manifest)


def test_every_manifest_placeholder_is_substituted():
    """The helper the Sloth spec and the recording rules share: each of the
    four placeholders becomes the manifest's value. payment-api.yaml is
    team payments, tier critical, type api."""
    from nthlayer_generate.core.placeholders import substitute_manifest_placeholders

    manifest = _load(SERVICES / "payment-api.yaml")
    out = substitute_manifest_placeholders(
        'x{service="${service}",team="${team}",tier="${tier}",type="${type}"}', manifest
    )
    assert out == 'x{service="payment-api",team="payments",tier="critical",type="api"}'


@pytest.mark.parametrize("path", SHIPPED, ids=lambda p: p.name)
def test_budget_labels_are_the_contract(path: Path):
    for rules in _budgets(_load(path)).values():
        for rule in rules:
            assert tuple(rule.labels) == ERROR_BUDGET_REMAINING.labels, rule.labels


# --- the guard against srm/v1 targets that are not objectives (opensrm-t13c) -

# Listed by hand from examples/opensrm/*.reliability.yaml, NOT derived from the
# guard: srm/v1 writes latency as `target: <ms>` with `unit: ms` (the bound,
# not an objective) and error_rate as a maximum error rate (0.1 = 0.1%).
# common passes both through unconverted until opensrm-t13c.
V1_UNUSABLE: dict[str, set[str]] = {
    "ai-gate.reliability.yaml": {"latency"},  # target: 100, unit: ms
    "api-basic.reliability.yaml": {"latency"},  # target: 200, unit: ms
    "api-critical.reliability.yaml": {"latency", "error_rate"},  # 200ms; 0.1
    "batch.reliability.yaml": {"error_rate"},  # 1.0
    "stream.reliability.yaml": {"error_rate"},  # 0.01
    "worker.reliability.yaml": {"error_rate"},  # 0.5
}

_CANNED_RATIO = {"latency": "slo:latency:ratio", "error_rate": "slo:error_rate:ratio"}


@pytest.mark.parametrize(
    ("name", "slo"),
    [(n, s) for n, slos in sorted(V1_UNUSABLE.items()) for s in sorted(slos)],
)
def test_srm_v1_targets_that_are_not_objectives_get_no_budget(name: str, slo: str):
    manifest = _load(EXAMPLES / "opensrm" / name)
    assert slo in {s.name for s in manifest.slos}
    assert slo not in _budgets(manifest)
    # Only the budget is skipped: the canned ratio is still written.
    assert _CANNED_RATIO[slo] in {r.record for r in _rules(manifest) if r.labels.get("slo") == slo}


def test_srm_v1_availability_keeps_its_budget():
    # The guard is per SLO: api-critical's availability (99.95) is usable.
    manifest = _load(EXAMPLES / "opensrm" / "api-critical.reliability.yaml")
    assert "availability" in _budgets(manifest)


# A canned v2 latency SLO: no indicator, so no unit and no bound in target.
_V2_CANNED_LATENCY = """\
    - apiVersion: openslo/v1
      kind: SLO
      metadata:
        name: checkout-latency-p99
      spec:
        service: checkout-api
        objectives:
          - displayName: "99% of checkout sessions created within 500ms"
            target: 0.99
"""


def test_v2_latency_without_a_declared_bound_gets_no_budget(tmp_path: Path):
    """The parser reads no bound from "99% under 200ms" (opensrm-8jpp), so the
    canned ratio counts requests under a guessed one; no budget on that."""
    manifest = _v2(tmp_path, _V2_CANNED_LATENCY)
    assert "checkout-latency-p99" not in _budgets(manifest)


def test_v2_error_rate_at_99_9_gets_a_budget(tmp_path: Path):
    assert "checkout-error-rate" in _budgets(_v2(tmp_path, _V2_ERROR_RATE))


def _v2_availability(target: float) -> str:
    # api.yaml's inline checkout-availability, with the target varied.
    return f"""\
    - apiVersion: openslo/v1
      kind: SLO
      metadata:
        name: checkout-availability
      spec:
        service: checkout-api
        objectives:
          - displayName: "checkout sessions served successfully"
            target: {target}
"""


@pytest.mark.parametrize(
    ("ratio", "budget"),
    [(0.5, True), (0.499, False), (0.9999, True), (1.0, False)],
    ids=["50", "49.9", "99.99", "100"],
)
def test_objective_bounds(tmp_path: Path, ratio: float, budget: bool):
    manifest = _v2(tmp_path, _v2_availability(ratio))
    assert ("checkout-availability" in _budgets(manifest)) is budget
    # The canned ratio is written either way.
    assert "slo:availability:ratio" in {r.record for r in _rules(manifest)}


def test_z3_path_is_guarded_too(tmp_path: Path):
    # analytics-stream's processing-availability has its own queries; a
    # copy with an unusable objective keeps its sli records but no budget.
    text = (SERVICES / "analytics-stream.yaml").read_text()
    assert "objective: 99.5" in text
    path = tmp_path / "analytics-stream.yaml"
    path.write_text(text.replace("objective: 99.5", "objective: 40.0", 1))
    manifest = _load(path)
    records = {
        r.record for r in _rules(manifest) if r.labels.get("slo") == "processing-availability"
    }
    assert "slo:sli:ratio" in records
    assert "processing-availability" not in _budgets(manifest)


def test_srm_v1_latency_bound_in_range_still_gets_no_budget(tmp_path: Path):
    # api-basic's latency with an 80ms bound: 80 sits inside the 50-100
    # objective range, so only the latency_bound_not_declared rule keeps it out.
    text = (EXAMPLES / "opensrm" / "api-basic.reliability.yaml").read_text()
    assert "      target: 200\n      unit: ms\n" in text
    path = tmp_path / "api-basic.reliability.yaml"
    path.write_text(
        text.replace("      target: 200\n      unit: ms\n", "      target: 80\n      unit: ms\n")
    )
    manifest = _load(path)
    assert next(s for s in manifest.slos if s.name == "latency").target == 80
    assert "latency" not in _budgets(manifest)
    assert "slo:latency:ratio" in {r.record for r in _rules(manifest)}


def test_a_trailing_comment_in_an_author_query_cannot_swallow_the_wrapper(tmp_path: Path):
    """PromQL comments run to end of line. Each author query is closed on a
    new line, so a trailing `# ...` cannot eat the closing paren and make
    Prometheus refuse the whole rule file."""
    manifest = _v2(
        tmp_path,
        # Single-quoted, so YAML keeps the `#` as part of the query.
        _V2_BAD_TOTAL_AVAILABILITY.replace(
            'query: sum(rate(http_requests_total{service="${service}",code=~"5.."}[5m]))',
            """query: 'sum(rate(http_requests_total{service="${service}",code=~"5.."}[5m]))  # 5xx only'""",
        ),
    )
    good = next(r for r in _rules(manifest) if r.record == "slo:sli_good:rate")
    assert "# 5xx only" in good.expr, good.expr
    for line in good.expr.splitlines():
        if "#" in line:
            assert line.rstrip().endswith("# 5xx only"), line
