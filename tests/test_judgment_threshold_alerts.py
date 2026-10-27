"""Judgment-threshold alerts (opensrm-wo62.2, design §5).

Each declared bound with a data source gets two alerts:
- ``…Breach``, which fires when the measured value is strictly above the
  bound (OPENSRM-CORE-v2 §5.5.6 E1), with durations compared in seconds (E2);
- ``…NotEvaluable``, which fires when the measurement is absent or NaN (E3).

Bounds come from the spec examples. The record each alert reads is looked up
in the recording rules generate actually emits, so an alert cannot quietly
point at a series no rule produces.
"""

from __future__ import annotations

import dataclasses
import warnings
from pathlib import Path
from typing import Any

import pytest
import yaml
from nthlayer_common.manifest import (
    THRESHOLD_SERIES,
    ReliabilityManifest,
    duration_seconds,
    load_manifest,
)
from nthlayer_common.manifest.thresholds import DURATION, THRESHOLD_BOUNDS

from nthlayer_generate.generators.alerts import generate_alerts_from_manifest
from nthlayer_generate.generators.judgment_threshold_alerts import (
    build_judgment_threshold_alerts,
)
from nthlayer_generate.recording_rules.manifest_builder import (
    build_recording_rules_from_manifest,
)
from nthlayer_generate.recording_rules.models import create_rule_groups

# parents: [0]=tests/ [1]=nthlayer-generate/ [2]=<ecosystem>/
THRESHOLDS = (
    Path(__file__).resolve().parents[2]
    / "opensrm"
    / "spec"
    / "v2"
    / "examples"
    / ("judgment-thresholds")
)
ALL_FIVE = THRESHOLDS / "all-five-types.yaml"
CALIBRATION_BOTH = THRESHOLDS / "calibration-both-bounds.yaml"
P50_ONLY = THRESHOLDS / "feedback-latency-p50-only.yaml"
SINGLE_BOUNDS = THRESHOLDS / "single-bounds.yaml"
SEGMENTS = THRESHOLDS / "segments-two-dimensions.yaml"
WITH_SOURCE = (ALL_FIVE, CALIBRATION_BOTH, P50_ONLY, SINGLE_BOUNDS)

# OPENSRM-CORE-v2 §5.5.5: maximum_p50 caps the median, maximum_p90 the 90th percentile.
QUANTILE = {"maximum_p50": 0.5, "maximum_p90": 0.9}

# Design §2 D4 (Rob, 2026-10-27).
BREACH = {"severity": "warning", "for": "15m"}
NOT_EVALUABLE = {"severity": "info", "for": "1h"}


def _load(path: Path) -> ReliabilityManifest:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return load_manifest(path)


def _declared(path: Path) -> list[tuple[str, str, Any]]:
    """(type, bound, value) for every declared bound whose type has a data source."""
    doc = yaml.safe_load(path.read_text())
    return [
        (t["type"], bound, value)
        for t in doc["spec"]["judgment_threshold"]
        if THRESHOLD_SERIES[t["type"]]
        for bound, value in t["bounds"].items()
    ]


def _comparison(threshold_type: str, bound: str, value: Any) -> float:
    # E2: a Duration bound is compared in seconds; a Ratio as declared.
    if THRESHOLD_BOUNDS[threshold_type][bound] == DURATION:
        return duration_seconds(value)
    return float(value)


def _emitted_records(manifest: ReliabilityManifest) -> set[tuple[str, str]]:
    """(record, target label) for every recording rule generate emits."""
    doc = yaml.safe_load(create_rule_groups(build_recording_rules_from_manifest(manifest)))
    return {
        (r["record"], r.get("labels", {}).get("target", ""))
        for g in doc["groups"]
        for r in g["rules"]
    }


def _alerts(manifest: ReliabilityManifest) -> dict[tuple[str, str], dict[str, Any]]:
    """(alert name, bound label) -> Prometheus rule dict."""
    return {
        (a.name, a.labels["bound"]): a.to_prometheus()
        for a in build_judgment_threshold_alerts(manifest)
    }


def test_fixtures_declare_every_bound_with_a_data_source():
    """Anti-vacuity: the corpus exercises all four bounds that have a series."""
    covered = {(t, b) for p in WITH_SOURCE for t, b, _ in _declared(p)}
    with_source = {(t, b) for t, series in THRESHOLD_SERIES.items() for b in series}
    assert covered == with_source


@pytest.mark.parametrize("path", WITH_SOURCE, ids=lambda p: p.stem)
def test_every_bound_gets_a_breach_alert_strictly_above_the_bound(path: Path):
    manifest = _load(path)
    alerts = _alerts(manifest)
    records = _emitted_records(manifest)

    for threshold_type, bound, value in _declared(path):
        compared = _comparison(threshold_type, bound, value)
        (rule,) = [r for (name, b), r in alerts.items() if b == bound and name.endswith("Breach")]
        record = rule["expr"].split("{", 1)[0]
        # The alert reads a record generate emits, with the bound as its target.
        assert (record, str(compared)) in records
        series = f'{record}{{service="{manifest.name}",target="{compared}"}}'
        if bound in QUANTILE:
            # E1: pq > B exactly when fewer than q of the arrivals are within B.
            assert rule["expr"] == f"{series} < {QUANTILE[bound]}"
        else:
            assert rule["expr"] == f"{series} > {compared}"
        assert rule["for"] == BREACH["for"]
        assert rule["labels"]["severity"] == BREACH["severity"]
        assert rule["labels"]["threshold_type"] == threshold_type


@pytest.mark.parametrize("path", WITH_SOURCE, ids=lambda p: p.stem)
def test_every_bound_gets_a_not_evaluable_alert_on_absent_or_nan(path: Path):
    manifest = _load(path)
    alerts = _alerts(manifest)

    for _threshold_type, bound, _value in _declared(path):
        (breach,) = [r for (n, b), r in alerts.items() if b == bound and n.endswith("Breach")]
        (rule,) = [r for (n, b), r in alerts.items() if b == bound and n.endswith("NotEvaluable")]
        series = breach["expr"].rsplit(" ", 2)[0]
        assert rule["expr"] == f"absent({series}) or ({series} != {series})"
        assert rule["for"] == NOT_EVALUABLE["for"]
        assert rule["labels"]["severity"] == NOT_EVALUABLE["severity"]


def test_e1_equality_is_within_bounds():
    """§5.5.6 E1: a value equal to the bound is within bounds.

    A ratio breaches on '> B'. A quantile breaches on 'fraction within B < q',
    and the le="B" bucket counts a latency of exactly B as within.
    """
    for alert in build_judgment_threshold_alerts(_load(ALL_FIVE)):
        if not alert.name.endswith("Breach"):
            continue
        assert ">=" not in alert.expr and "<=" not in alert.expr
        if alert.labels["bound"] in QUANTILE:
            assert " < " in alert.expr
        else:
            assert " > " in alert.expr


def test_alert_names_name_the_type_and_bound():
    names = {a.name for a in build_judgment_threshold_alerts(_load(ALL_FIVE))}
    assert names == {
        "AIGateCalibrationBrierBreach",
        "AIGateCalibrationBrierNotEvaluable",
        "AIGateFeedbackLatencyP50Breach",
        "AIGateFeedbackLatencyP50NotEvaluable",
        "AIGateFeedbackLatencyP90Breach",
        "AIGateFeedbackLatencyP90NotEvaluable",
    }


def test_types_without_a_data_source_get_no_alerts():
    assert build_judgment_threshold_alerts(_load(SEGMENTS)) == []


def test_threshold_alerts_survive_low_tier_filtering():
    """Design §3 Q2: a declared bound is an explicit request, whatever the tier."""
    manifest = dataclasses.replace(_load(ALL_FIVE), tier="low")
    expected = {a.name for a in build_judgment_threshold_alerts(manifest)}
    assert {a.severity for a in build_judgment_threshold_alerts(manifest)} == {"warning", "info"}

    emitted = {a.name for a in generate_alerts_from_manifest(manifest, quiet=True)}

    assert expected <= emitted


def test_threshold_alerts_are_written_without_any_dependency_alerts(tmp_path: Path):
    manifest = _load(ALL_FIVE)
    out = tmp_path / "alerts.yaml"

    generate_alerts_from_manifest(manifest, output_file=out, quiet=True)

    doc = yaml.safe_load(out.read_text())
    written = {r["alert"] for g in doc["groups"] for r in g["rules"]}
    assert written == {a.name for a in build_judgment_threshold_alerts(manifest)}


def test_no_declared_thresholds_means_no_threshold_alerts():
    manifest = _load(ALL_FIVE)
    plain = dataclasses.replace(manifest, judgment_thresholds=[])
    assert build_judgment_threshold_alerts(plain) == []


def test_alerting_for_duration_overrides_do_not_apply_to_threshold_alerts():
    """Rob, 2026-10-27: D4's durations are fixed; the manifest's for_duration is for templates."""
    manifest = dataclasses.replace(
        _load(ALL_FIVE), alerting={"for_duration": {"page": "1m", "ticket": "2m"}}
    )
    expected = {"warning": BREACH["for"], "info": NOT_EVALUABLE["for"]}

    for alert in generate_alerts_from_manifest(manifest, quiet=True):
        if alert.technology == "judgment_threshold":
            assert alert.duration == expected[alert.severity]


def test_duplicate_entries_do_not_duplicate_alerts():
    manifest = _load(CALIBRATION_BOTH)
    (threshold,) = manifest.judgment_thresholds
    manifest = dataclasses.replace(manifest, judgment_thresholds=[threshold, threshold])

    alerts = [(a.name, a.expr) for a in build_judgment_threshold_alerts(manifest)]

    assert alerts and len(alerts) == len(set(alerts))


def test_no_dependencies_skips_the_template_path(monkeypatch: pytest.MonkeyPatch):
    """R5 provenance: with thresholds and no dependencies the template path is not entered.

    Entering it prints "No dependencies found", which contradicts the threshold
    alerts written right after. Patched at alerts.py's own lookup.
    """
    import nthlayer_generate.generators.alerts as alerts_module

    manifest = _load(ALL_FIVE)
    assert not manifest.dependencies and manifest.judgment_thresholds
    calls: list[Any] = []
    monkeypatch.setattr(
        alerts_module, "_load_and_customize_alerts", lambda **kw: calls.append(kw) or []
    )

    generate_alerts_from_manifest(manifest, quiet=True)

    assert calls == []


def test_threshold_alerts_carry_the_services_context_labels():
    """R5 provenance: customize_for_service was pinned only by regenerated goldens."""
    manifest = _load(ALL_FIVE)

    threshold_alerts = [
        a
        for a in generate_alerts_from_manifest(manifest, quiet=True)
        if a.technology == "judgment_threshold"
    ]

    assert threshold_alerts
    for alert in threshold_alerts:
        assert alert.labels["service"] == manifest.name
        assert alert.labels["team"] == manifest.team
        assert alert.labels["tier"] == str(manifest.tier)
        assert alert.labels["routing"] == manifest.support_model
