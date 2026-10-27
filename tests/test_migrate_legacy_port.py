"""cli.migrate._legacy_to_srm_v1 is a faithful port of to_dict (opensrm-wo62.1, D7).

The expected document for each legacy example is the ``cli_migrate`` golden,
read from disk, never restated. Until Checkpoint C those goldens were what
``nthlayer migrate`` wrote with generate's own ``ReliabilityManifest.to_dict``,
and this test allowed exactly one difference, spec §6.3 G5 (common's legacy
loader reads ``Dependencies.spec.services``, so six manifests gained
dependencies). Checkpoint C re-pinned the goldens on common's model, with that
G5 difference recorded in the approved list (checkpoint-C-golden-diff.md), so
the port must now equal every golden exactly.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from nthlayer_common.manifest import load_manifest

from nthlayer_generate.cli.migrate import _legacy_to_srm_v1

REPO = Path(__file__).resolve().parents[1]
GOLDENS = REPO / "tests" / "golden" / "data" / "cli_migrate"


def _migrated_goldens() -> list[tuple[str, Path, Any]]:
    """(golden id, example path, migrated document) for every golden that
    wrote a file — the legacy examples; srm/v1 ones write nothing."""
    cases = []
    for golden in sorted(GOLDENS.glob("*.json")):
        files = json.loads(golden.read_text(encoding="utf-8"))["files"]
        if not files:
            continue
        ((_name, text),) = files.items()
        folder, stem = golden.stem.split("__", 1)
        cases.append(
            (golden.stem, REPO / "examples" / folder / f"{stem}.yaml", yaml.safe_load(text))
        )
    return cases


CASES = _migrated_goldens()


def test_every_legacy_golden_is_covered() -> None:
    # 19 loadable legacy examples (checkpoint-B-coverage.md §1); guards
    # against a moved golden directory silently emptying the parametrisation.
    assert len(CASES) == 19


@pytest.mark.parametrize(("mid", "path", "golden"), CASES, ids=[c[0] for c in CASES])
def test_port_matches_the_cli_migrate_golden(mid: str, path: Path, golden: Any) -> None:
    ported = _legacy_to_srm_v1(load_manifest(path, suppress_deprecation_warning=True))

    assert ported == golden


def test_port_writes_the_resolved_type(tmp_path: Path) -> None:
    """A written file carries the canonical spelling the spec accepts
    (README "Upgrading": "manifests rewritten by `nthlayer migrate`" carry
    x-web). Fixture: examples/services/api-minimal.yaml @0331eff with ``service.type``
    rewritten to the alias ``web``."""
    source = REPO / "examples" / "services" / "api-minimal.yaml"
    data = yaml.safe_load(source.read_text(encoding="utf-8"))
    data["service"]["type"] = "web"
    path = tmp_path / "api-minimal.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    ported = _legacy_to_srm_v1(load_manifest(path, suppress_deprecation_warning=True))

    assert ported["spec"]["type"] == "x-web"


# Every shipped legacy manifest: the 17 under examples/services/ plus the three
# legacy files under examples/uat/ (the srm/v1 one there is excluded by name).
_SHIPPED_LEGACY = sorted((REPO / "examples" / "services").glob("*.yaml")) + [
    REPO / "examples" / "uat" / n
    for n in ("payment-api.yaml", "payment-api-with-slas.yaml", "payment-api-partial-slas.yaml")
]
# examples/services/analytics-stream.yaml declares ``type: stream-processor``,
# which common's legacy loader rejects before migrate ever runs
# (checkpoint-B-coverage.md §1). Named, not filtered by catching errors, so a
# second unloadable example fails the count below instead of vanishing.
_UNLOADABLE = {REPO / "examples" / "services" / "analytics-stream.yaml"}
_ROUND_TRIP = [p for p in _SHIPPED_LEGACY if p not in _UNLOADABLE]


def test_round_trip_covers_every_loadable_legacy_example() -> None:
    assert all(p.is_file() for p in _SHIPPED_LEGACY)
    assert len(_ROUND_TRIP) >= 19
    for path in _UNLOADABLE:
        with pytest.raises(ValueError, match="stream-processor"):
            load_manifest(path, suppress_deprecation_warning=True)
    # Template-only examples (api-minimal, ...) declare no SLOs, so the SLO
    # assertion below is vacuous for them; most examples must still carry some.
    with_slos = [p for p in _ROUND_TRIP if load_manifest(p, suppress_deprecation_warning=True).slos]
    assert len(with_slos) >= 10


def _slo_set(manifest: Any) -> set[tuple[str, str, float, str]]:
    return {(s.name, s.slo_type, s.target, s.window) for s in manifest.slos}


@pytest.mark.parametrize(
    "path", _ROUND_TRIP, ids=[f"{p.parent.name}/{p.stem}" for p in _ROUND_TRIP]
)
def test_migrated_file_loads_in_common_with_the_same_slos(path: Path, tmp_path: Path) -> None:
    """opensrm-wo62.1 correctness C1: common's srm/v1 parser requires an SLO
    ``type`` it cannot infer from the name (parser/v1.py ``_infer_slo_type``),
    so the written file must carry it or ``load_manifest`` rejects it."""
    legacy = load_manifest(path, suppress_deprecation_warning=True)

    out = tmp_path / f"{legacy.name}.reliability.yaml"
    out.write_text(yaml.safe_dump(_legacy_to_srm_v1(legacy), sort_keys=False), encoding="utf-8")
    migrated = load_manifest(out)

    assert _slo_set(migrated) == _slo_set(legacy)


def test_migrated_ai_gate_judgment_slos_load_as_thresholds(tmp_path: Path) -> None:
    """opensrm-wo62.1 R5 edge-cases: srm/v1 lifts ``calibration`` and
    ``feedback_latency`` into JudgmentThresholds and rejects an explicit
    ``type`` on them (SRM_V1_JUDGMENT_THRESHOLD_TYPES, nthlayer_common
    manifest/models.py; "srm/v1 'calibration' does not take 'type'",
    manifest/thresholds.py). Fixture: the legacy ``resources: - kind: SLO``
    shape of examples/services/payment-api.yaml with ``service.type: ai-gate``
    and SLO names/values from examples/opensrm/ai-gate.reliability.yaml
    (calibration 0.05 / 30d, feedback_latency 3600 / 30d)."""
    data = yaml.safe_load(
        (REPO / "examples" / "services" / "payment-api.yaml").read_text(encoding="utf-8")
    )
    data["service"]["type"] = "ai-gate"
    data["resources"] = [
        {
            "kind": "SLO",
            "name": name,
            "spec": {
                "objective": objective,
                "window": "30d",
                "indicator": {"type": name, "query": f"{name}{{service=\"${{service}}\"}}"},
            },
        }
        for name, objective in (("calibration", 0.05), ("feedback_latency", 3600))
    ]
    src = tmp_path / "gate.yaml"
    src.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    legacy = load_manifest(src, suppress_deprecation_warning=True)
    out = tmp_path / "gate.reliability.yaml"
    out.write_text(yaml.safe_dump(_legacy_to_srm_v1(legacy), sort_keys=False), encoding="utf-8")
    migrated = load_manifest(out)

    assert {t.type for t in migrated.get_judgment_thresholds()} == {
        "calibration",
        "feedback_latency",
    }


def _legacy_ai_gate(tmp_path: Path) -> Path:
    """Same fixture provenance as the test above: payment-api.yaml's legacy shape
    with ai-gate.reliability.yaml's calibration 0.05 / 30d and feedback_latency 3600 / 30d."""
    data = yaml.safe_load(
        (REPO / "examples" / "services" / "payment-api.yaml").read_text(encoding="utf-8")
    )
    data["service"]["type"] = "ai-gate"
    data["resources"] = [
        {"kind": "SLO", "name": name, "spec": {"objective": objective, "window": "30d"}}
        for name, objective in (("calibration", 0.05), ("feedback_latency", 3600))
    ]
    src = tmp_path / "gate.yaml"
    src.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return src


def test_migrated_thresholds_round_trip_with_equal_bounds_and_window(tmp_path: Path):
    legacy = load_manifest(_legacy_ai_gate(tmp_path), suppress_deprecation_warning=True)
    assert legacy.judgment_thresholds, "fixture no longer yields thresholds"
    lost: list[str] = []
    out = tmp_path / "gate.reliability.yaml"
    out.write_text(yaml.safe_dump(_legacy_to_srm_v1(legacy, lost), sort_keys=False), encoding="utf-8")

    migrated = load_manifest(out)

    assert lost == []
    assert migrated.judgment_thresholds == legacy.judgment_thresholds


def test_threshold_srm_v1_cannot_carry_is_reported_not_dropped(tmp_path: Path):
    import dataclasses

    legacy = load_manifest(_legacy_ai_gate(tmp_path), suppress_deprecation_warning=True)
    (latency,) = [t for t in legacy.judgment_thresholds if t.type == "feedback_latency"]
    legacy.judgment_thresholds = [
        dataclasses.replace(latency, bounds={**latency.bounds, "maximum_p95": "2h"})
    ]
    lost: list[str] = []

    doc = _legacy_to_srm_v1(legacy, lost)

    assert doc["spec"]["slos"]["feedback_latency"]["target"] == 3600
    assert len(lost) == 1
    assert "feedback_latency" in lost[0] and "maximum_p95" in lost[0]


def _legacy_gate_with(tmp_path: Path, resources: list[dict[str, Any]]) -> Path:
    """payment-api.yaml's legacy shape (service.type ai-gate), with *resources*
    as its only ``kind: SLO`` resources."""
    data = yaml.safe_load(
        (REPO / "examples" / "services" / "payment-api.yaml").read_text(encoding="utf-8")
    )
    data["service"]["type"] = "ai-gate"
    data["resources"] = resources
    src = tmp_path / "gate.yaml"
    src.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return src


# (target, unit) for a legacy feedback_latency resource. The unit is any of
# schema.json's Duration units (``^[0-9]+(ms|s|m|h|d|w)$``), which common's
# srm/v1 lift (thresholds._srm_v1_feedback_latency_bound) accepts and writes
# back as ``f"{int(target)}{unit}"``; 10**15 d is under the lift's 2**53 cap
# but 8.64e19 seconds, past it.
_FEEDBACK_LATENCY_CASES = [(90, "m"), (1500, "ms"), (24, "h"), (1, "d"), (10**15, "d")]


@pytest.mark.parametrize(("target", "unit"), _FEEDBACK_LATENCY_CASES)
def test_feedback_latency_round_trips_in_its_own_unit(
    tmp_path: Path, target: int, unit: str
) -> None:
    """R5 correctness (opensrm-wo62.1): migrate must invert the lift exactly,
    so ``90m`` is written as target 90 unit m, not re-spelled as 5400s."""
    src = _legacy_gate_with(
        tmp_path,
        [{"kind": "SLO", "name": "feedback_latency",
          "spec": {"objective": target, "unit": unit, "window": "30d"}}],
    )
    legacy = load_manifest(src, suppress_deprecation_warning=True)
    assert [t.bounds for t in legacy.judgment_thresholds] == [
        {"maximum_p50": f"{target}{unit}"}
    ], "fixture no longer yields the threshold"
    lost: list[str] = []
    out = tmp_path / "gate.reliability.yaml"
    out.write_text(yaml.safe_dump(_legacy_to_srm_v1(legacy, lost), sort_keys=False), encoding="utf-8")

    migrated = load_manifest(out)

    assert lost == []
    assert migrated.judgment_thresholds == legacy.judgment_thresholds


@pytest.mark.parametrize("name", ["stability", "segments", "audit_backlog"])
def test_slo_name_srm_v1_rejects_is_reported_and_omitted(tmp_path: Path, name: str) -> None:
    """R5 correctness (opensrm-wo62.1): common's legacy loader keeps
    stability/segments/audit_backlog as classical SLOs (loader.py
    _extract_slos_from_resources), but srm/v1 routes every
    V2_JUDGMENT_THRESHOLD_TYPES name to srm_v1_threshold, which rejects these
    three (manifest/thresholds.py). Fixture: objective 0.02 / window 14d, the
    ``max_increase`` and ``lookback`` of opensrm/spec/v1/specification.md §5.8."""
    src = _legacy_gate_with(
        tmp_path,
        [
            {"kind": "SLO", "name": name, "spec": {"objective": 0.02, "window": "14d"}},
            {"kind": "SLO", "name": "feedback_latency",
             "spec": {"objective": 3600, "window": "30d"}},
        ],
    )
    legacy = load_manifest(src, suppress_deprecation_warning=True)
    assert [s.name for s in legacy.slos] == [name], "fixture no longer yields the SLO"
    lost: list[str] = []
    doc = _legacy_to_srm_v1(legacy, lost)
    out = tmp_path / "gate.reliability.yaml"
    out.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")

    migrated = load_manifest(out)

    assert name not in doc["spec"]["slos"]
    assert migrated.judgment_thresholds == legacy.judgment_thresholds
    assert len(lost) == 1 and name in lost[0]


def test_non_duration_maximum_p50_is_reported_once(tmp_path: Path) -> None:
    import dataclasses

    legacy = load_manifest(_legacy_ai_gate(tmp_path), suppress_deprecation_warning=True)
    (latency,) = [t for t in legacy.judgment_thresholds if t.type == "feedback_latency"]
    legacy.judgment_thresholds = [dataclasses.replace(latency, bounds={"maximum_p50": 3600})]
    lost: list[str] = []

    doc = _legacy_to_srm_v1(legacy, lost)

    assert "slos" not in doc["spec"]
    assert len(lost) == 1 and "maximum_p50" in lost[0]


@pytest.mark.parametrize("name", ["calibration", "feedback_latency"])
def test_threshold_description_and_labels_are_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    """common's lift accepts and drops ``description`` and ``labels``
    (thresholds._SRM_V1_THRESHOLD_KEYS: "accepted and dropped"), so the
    JudgmentThreshold migrate serialises no longer has them; migrate reports
    them from the source. Fixture: _legacy_ai_gate's values, with the
    description/labels keys every legacy SLO resource may carry."""
    from nthlayer_generate.cli import migrate

    objective = 0.05 if name == "calibration" else 3600
    src = _legacy_gate_with(
        tmp_path,
        [{"kind": "SLO", "name": name,
          "spec": {"objective": objective, "window": "30d",
                   "description": "judgment quality", "labels": {"team": "payments"}}}],
    )
    messages: list[str] = []
    monkeypatch.setattr(migrate, "warning", messages.append)

    assert migrate.migrate_command(str(src), output_dir=str(tmp_path / "out")) == 0

    lost = [m for m in messages if name in m]
    assert any("description" in m for m in lost)
    assert any("labels" in m for m in lost)
