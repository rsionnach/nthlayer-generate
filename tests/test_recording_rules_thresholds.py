"""Threshold recording rules added by opensrm-wo62.2.

Brier calibration and the 30-day feedback-latency within-bound fractions
(``:p50_within_bound_30d`` / ``:p90_within_bound_30d``). Design:
``nthlayer/docs/superpowers/specs/2026-10-27-wo62-2-judgment-threshold-rules-design.md`` §4.

Every expected value comes from somewhere other than the code under test:
- the bound values come from the OpenSRM v2 spec examples;
- the quantile for each bound comes from the bound's name (OPENSRM-CORE-v2
  §5.5.5: p50 and p90);
- the window comes from common's series contract, which §5.5.5 fixes at 30
  days.
"""

from __future__ import annotations

import dataclasses
import warnings
from pathlib import Path
from typing import Any

import pytest
import yaml
from nthlayer_common.manifest import (
    FEEDBACK_LATENCY_WINDOW,
    THRESHOLD_SERIES,
    ReliabilityManifest,
    duration_seconds,
    load_manifest,
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
FIXTURES = (ALL_FIVE, CALIBRATION_BOTH, P50_ONLY, SINGLE_BOUNDS, SEGMENTS)

# OPENSRM-CORE-v2 §5.5.5: maximum_p50 bounds the median, maximum_p90 the 90th percentile.
QUANTILE = {"maximum_p50": 0.5, "maximum_p90": 0.9}
WINDOW_RECORD = {
    "maximum_p50": "ai_gate:feedback_latency:p50_within_bound_30d",
    "maximum_p90": "ai_gate:feedback_latency:p90_within_bound_30d",
}


def _load(path: Path) -> ReliabilityManifest:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return load_manifest(path)


def _groups(manifest: ReliabilityManifest) -> dict[str, dict[str, Any]]:
    doc = yaml.safe_load(create_rule_groups(build_recording_rules_from_manifest(manifest)))
    return {g["name"]: g for g in doc["groups"]}


def _rules(manifest: ReliabilityManifest) -> dict[str, dict[str, Any]]:
    """Rules from both threshold-bearing groups, keyed by record."""
    groups = _groups(manifest)
    names = (
        f"{manifest.name}_judgment_metrics",
        f"{manifest.name}_judgment_thresholds_{FEEDBACK_LATENCY_WINDOW}",
    )
    return {r["record"]: r for n in names if n in groups for r in groups[n]["rules"]}


def _bounds(path: Path, threshold_type: str) -> dict[str, Any]:
    doc = yaml.safe_load(path.read_text())
    (entry,) = [t for t in doc["spec"]["judgment_threshold"] if t["type"] == threshold_type]
    bounds: dict[str, Any] = entry["bounds"]
    return bounds


def test_fixtures_are_present():
    """Guard against the silent-skip layout (CLAUDE.md): no fixture may be missing."""
    missing = [str(p) for p in FIXTURES if not p.is_file()]
    assert not missing, f"missing fixtures: {missing}"


def test_the_spec_fixes_the_feedback_latency_window_at_30_days():
    # §5.5.5: "computed over the decisions whose ground truth arrived in the last 30 days".
    assert FEEDBACK_LATENCY_WINDOW == "30d"


@pytest.mark.parametrize("path", [ALL_FIVE, CALIBRATION_BOTH], ids=lambda p: p.stem)
def test_declared_brier_bound_emits_a_brier_rule(path: Path):
    bound = _bounds(path, "calibration")["maximum_brier_score"]
    manifest = _load(path)

    rule = _rules(manifest)["ai_gate:calibration:brier"]

    assert rule["expr"] == f'avg(ai_gate_calibration_brier{{service="{manifest.name}"}})'
    assert rule["labels"] == {
        "service": manifest.name,
        "target": str(bound),
        "slo": "calibration",
    }


def test_ece_only_calibration_emits_no_brier_rule():
    assert set(_bounds(SINGLE_BOUNDS, "calibration")) == {"maximum_expected_calibration_error"}
    assert "ai_gate:calibration:brier" not in _rules(_load(SINGLE_BOUNDS))


def test_both_calibration_bounds_keep_ece_rules_before_brier():
    records = list(_rules(_load(CALIBRATION_BOTH)))
    assert records.index("ai_gate:calibration:ece") < records.index("ai_gate:calibration:brier")


def _feedback_cases() -> list[tuple[Path, str]]:
    cases = [
        (path, bound)
        for path in (ALL_FIVE, P50_ONLY, SINGLE_BOUNDS)
        for bound in _bounds(path, "feedback_latency")
    ]
    # Anti-vacuity: both bounds are exercised, so a missing bound cannot
    # quietly empty this list.
    assert {b for _, b in cases} == set(QUANTILE)
    return cases


@pytest.mark.parametrize(
    "path,bound", _feedback_cases(), ids=lambda v: v.stem if isinstance(v, Path) else v
)
def test_declared_feedback_bound_emits_a_30_day_within_bound_fraction(path: Path, bound: str):
    """The fraction of arrivals within the bound, not a quantile (R5 pass 1, Rob: option A).

    pq <= B exactly when that fraction is at least q, so the alert needs no
    interpolation. Unlike histogram_quantile, a quantile in the +Inf bucket
    cannot read as within bounds.
    """
    declared = _bounds(path, "feedback_latency")[bound]
    seconds = duration_seconds(declared)
    manifest = _load(path)

    rule = _rules(manifest)[WINDOW_RECORD[bound]]

    selector = f'service="{manifest.name}"'
    window = f"[{FEEDBACK_LATENCY_WINDOW}]"
    assert rule["expr"] == (
        f'sum(increase(ai_gate_feedback_latency_seconds_bucket{{{selector},le="{seconds}"}}'
        f"{window})) / sum(increase(ai_gate_feedback_latency_seconds_count{{{selector}}}"
        f"{window}))"
    )
    assert "histogram_quantile" not in rule["expr"]
    # E2: a Duration bound is carried in seconds.
    assert rule["labels"] == {
        "service": manifest.name,
        "target": str(seconds),
        "quantile": str(QUANTILE[bound]),
        "slo": "feedback_latency",
    }


@pytest.mark.parametrize("path", [P50_ONLY, SINGLE_BOUNDS], ids=lambda p: p.stem)
def test_undeclared_feedback_bound_emits_no_30_day_rule(path: Path):
    declared = set(_bounds(path, "feedback_latency"))
    undeclared = set(QUANTILE) - declared
    assert undeclared, "fixture must leave one bound undeclared"

    rules = _rules(_load(path))

    for bound in undeclared:
        assert WINDOW_RECORD[bound] not in rules


def test_types_without_a_data_source_emit_nothing():
    no_source = {t for t, series in THRESHOLD_SERIES.items() if not series}
    # D2 rests on common's contract: these three have no series.
    assert no_source == {"segments", "stability", "audit_backlog"}
    declared = {
        t["type"] for t in yaml.safe_load(SEGMENTS.read_text())["spec"]["judgment_threshold"]
    }
    assert declared == {"segments"}

    assert _rules(_load(SEGMENTS)) == {}


def test_non_duration_maximum_p90_raises_type_error():
    manifest = _load(SINGLE_BOUNDS)
    bad = [
        dataclasses.replace(t, bounds={**t.bounds, "maximum_p90": 86400.0})
        if t.type == "feedback_latency"
        else t
        for t in manifest.get_judgment_thresholds()
    ]
    manifest.get_judgment_thresholds = lambda: bad  # type: ignore[method-assign]
    with pytest.raises(TypeError, match="maximum_p90 is not a Duration"):
        build_recording_rules_from_manifest(manifest)


def test_30_day_rules_have_their_own_5m_group():
    """A 30-day range query every 30s is needless load (Rob, Checkpoint B)."""
    manifest = _load(ALL_FIVE)
    groups = _groups(manifest)

    window = groups[f"{manifest.name}_judgment_thresholds_{FEEDBACK_LATENCY_WINDOW}"]
    judgment = groups[f"{manifest.name}_judgment_metrics"]

    assert window["interval"] == "5m"
    assert {r["record"] for r in window["rules"]} == set(WINDOW_RECORD.values())
    assert judgment["interval"] == "30s"
    assert not set(WINDOW_RECORD.values()) & {r["record"] for r in judgment["rules"]}


def test_no_feedback_bound_means_no_30_day_group():
    manifest = _load(CALIBRATION_BOTH)
    assert "feedback_latency" not in {t.type for t in manifest.get_judgment_thresholds()}

    assert not [n for n in _groups(manifest) if "judgment_thresholds" in n]
