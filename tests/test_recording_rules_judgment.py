"""Judgment recording rules built from common's model (opensrm-wo62.1, spec §5.3).

``ai_gate:calibration:*`` and ``ai_gate:feedback_latency:*`` are built from
nthlayer-common's ``JudgmentThreshold``; judgment SLOs dispatch on
``judgment_type``, not on the SLO's name.

Every input is a shipped file: generate's ai-gate example, or the OpenSRM v2
spec examples in the sibling ``opensrm`` checkout. Every expected value is read
from a file (the Checkpoint B golden, or the spec example's declared bound),
never restated here and never taken from the code under test.
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path
from typing import Any

import pytest
import yaml
from nthlayer_common.manifest import ReliabilityManifest, duration_seconds, load_manifest
from nthlayer_common.manifest.parser.v2 import parse_opensrm_v2

from nthlayer_generate.recording_rules.manifest_builder import (
    build_recording_rules_from_manifest,
)
from nthlayer_generate.recording_rules.models import create_rule_groups

# parents: [0]=tests/ [1]=nthlayer-generate/ [2]=<ecosystem>/
REPO = Path(__file__).resolve().parents[1]
OPENSRM = Path(__file__).resolve().parents[2] / "opensrm"
V2_EXAMPLES = OPENSRM / "spec" / "v2" / "examples"
THRESHOLDS = V2_EXAMPLES / "judgment-thresholds"

AI_GATE = REPO / "examples" / "opensrm" / "ai-gate.reliability.yaml"
AI_GATE_GOLDEN = (
    REPO / "tests" / "golden" / "data" / "recording_rules" / "opensrm__ai-gate.reliability.json"
)
P50_ONLY = THRESHOLDS / "feedback-latency-p50-only.yaml"
CALIBRATION_BOTH = THRESHOLDS / "calibration-both-bounds.yaml"
ALL_FIVE = THRESHOLDS / "all-five-types.yaml"
REVERSAL_RATE_SLO = V2_EXAMPLES / "judgment-slos" / "01-reversal-rate.yaml"

FIXTURES = (AI_GATE, AI_GATE_GOLDEN, P50_ONLY, CALIBRATION_BOTH, ALL_FIVE, REVERSAL_RATE_SLO)


def _load(path: Path) -> ReliabilityManifest:
    # The srm/v1 judgment ratios trip TargetConventionWarning (spec §5.4);
    # that warning is not what these tests are about.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return load_manifest(path)


def _judgment_rules(manifest: ReliabilityManifest) -> list[dict[str, Any]]:
    """The judgment group's rules, normalised exactly as the golden cell does."""
    groups = build_recording_rules_from_manifest(manifest)
    doc = yaml.safe_load(create_rule_groups(groups))
    judgment = [g for g in doc["groups"] if g["name"] == f"{manifest.name}_judgment_metrics"]
    if not judgment:
        return []
    assert len(judgment) == 1
    rules: list[dict[str, Any]] = judgment[0]["rules"]
    return rules


def _by_record(rules: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {r["record"]: r for r in rules}


def _declared_bounds(path: Path, threshold_type: str) -> dict[str, Any]:
    doc = yaml.safe_load(path.read_text())
    (entry,) = [t for t in doc["spec"]["judgment_threshold"] if t["type"] == threshold_type]
    bounds: dict[str, Any] = entry["bounds"]
    return bounds


def test_fixtures_are_present():
    """Guard against the silent-skip layout (CLAUDE.md): no fixture may be missing."""
    missing = [str(p) for p in FIXTURES if not p.is_file()]
    assert not missing, f"missing fixtures: {missing}"


def test_ai_gate_judgment_group_matches_the_checkpoint_b_golden():
    golden = json.loads(AI_GATE_GOLDEN.read_text())
    manifest = _load(AI_GATE)
    (expected,) = [g for g in golden["groups"] if g["name"] == f"{manifest.name}_judgment_metrics"]
    # Anti-vacuity: the golden holds both ported families.
    records = [r["record"] for r in expected["rules"]]
    assert "ai_gate:calibration:ece" in records
    assert "ai_gate:feedback_latency:bucket" in records

    assert _judgment_rules(manifest) == expected["rules"]


def test_feedback_latency_p50_only_emits_percentiles_and_bucket():
    bound = _declared_bounds(P50_ONLY, "feedback_latency")["maximum_p50"]
    expected_seconds = str(duration_seconds(bound))
    manifest = _load(P50_ONLY)

    rules = _by_record(_judgment_rules(manifest))

    for p in ("p50", "p95", "p99"):
        assert f"ai_gate:feedback_latency:{p}" in rules
    bucket = rules["ai_gate:feedback_latency:bucket"]
    assert bucket["labels"]["target"] == expected_seconds
    assert f'le="{expected_seconds}"' in bucket["expr"]
    assert bucket["labels"]["service"] == manifest.name


def test_calibration_with_both_bounds_emits_ece_from_the_ece_bound():
    bound = _declared_bounds(CALIBRATION_BOTH, "calibration")["maximum_expected_calibration_error"]
    manifest = _load(CALIBRATION_BOTH)

    rules = _by_record(_judgment_rules(manifest))

    assert rules["ai_gate:calibration:ece"]["labels"]["target"] == str(bound)
    for bucket in ("low", "medium", "high"):
        assert f"ai_gate:calibration_bucket:{bucket}" in rules


def test_all_five_types_emits_only_the_ported_families():
    declared = yaml.safe_load(ALL_FIVE.read_text())["spec"]["judgment_threshold"]
    calibration = next(t for t in declared if t["type"] == "calibration")
    # The fixture is the case under test: Brier only, no ECE bound.
    assert "maximum_expected_calibration_error" not in calibration["bounds"]
    assert {t["type"] for t in declared} >= {"segments", "stability", "audit_backlog"}

    manifest = _load(ALL_FIVE)
    rules = _by_record(_judgment_rules(manifest))

    assert not [r for r in rules if r.startswith("ai_gate:calibration")]
    feedback = _declared_bounds(ALL_FIVE, "feedback_latency")
    expected_seconds = str(duration_seconds(feedback["maximum_p50"]))
    assert rules["ai_gate:feedback_latency:bucket"]["labels"]["target"] == expected_seconds
    # segments / stability / audit_backlog: nothing emitted (wo62.2).
    assert set(rules) == {
        "ai_gate:feedback_latency:p50",
        "ai_gate:feedback_latency:p95",
        "ai_gate:feedback_latency:p99",
        "ai_gate:feedback_latency:bucket",
    }


def test_judgment_slo_dispatches_on_judgment_type_not_name():
    document = yaml.safe_load(REVERSAL_RATE_SLO.read_text())
    name = document["metadata"]["name"]
    judgment_type = document["spec"]["judgment_type"]
    service = document["spec"]["service"]
    assert name != judgment_type, "fixture no longer exercises a free-form name"

    # The fragment is a JudgmentSLO document; splice it into a minimal v2
    # envelope, as nthlayer-common's test_judgment_targets_against_spec_examples
    # does. The envelope is scaffolding; name and type come from the file.
    envelope = {
        "apiVersion": "opensrm.nthlayer.io/v2",
        "kind": "ServiceManifest",
        "metadata": {"name": service, "labels": {"tier": "critical"}},
        "spec": {
            "owner": {"group": "group:default/t"},
            "service": {"name": service, "type": "ai-gate"},
            "judgment_slo": [{"metadata": document["metadata"], "spec": document["spec"]}],
        },
    }
    manifest = parse_opensrm_v2(envelope, base_dir=None)
    assert [s.name for s in manifest.slos] == [name]

    rules = _by_record(_judgment_rules(manifest))

    assert f"ai_gate:{judgment_type}:ratio" in rules
    assert rules[f"ai_gate:{judgment_type}:ratio"]["labels"]["slo"] == judgment_type


@pytest.mark.parametrize("path", [P50_ONLY, CALIBRATION_BOTH, ALL_FIVE], ids=lambda p: p.stem)
def test_threshold_only_manifest_has_no_slo_group(path: Path):
    manifest = _load(path)
    assert manifest.slos == []
    names = [g.name for g in build_recording_rules_from_manifest(manifest)]
    assert f"{manifest.name}_slo_metrics" not in names
    assert f"{manifest.name}_judgment_metrics" in names
