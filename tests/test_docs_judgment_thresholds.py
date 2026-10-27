"""The "Judgment thresholds" section of an ai-gate's api.md (opensrm-wo62.2, design §6).

The section has one table row per declared (entry, bound). A bound with a
recording rule names the rule and its two alerts; the others say
nthlayer-workers evaluates them. Declared values come from the spec examples,
and rule and alert names come from what generate actually emits.
"""

from __future__ import annotations

import dataclasses
import warnings
from pathlib import Path
from typing import Any

import pytest
import yaml
from nthlayer_common.manifest import THRESHOLD_SERIES, ReliabilityManifest, load_manifest

from nthlayer_generate.generators.docs import _api_docs_ai_gate, generate_service_docs
from nthlayer_generate.generators.judgment_threshold_alerts import (
    build_judgment_threshold_alerts,
)

# parents: [0]=tests/ [1]=nthlayer-generate/ [2]=<ecosystem>/
THRESHOLDS = (
    Path(__file__).resolve().parents[2]
    / "opensrm"
    / "spec"
    / "v2"
    / "examples"
    / ("judgment-thresholds")
)
FIXTURES = tuple(
    THRESHOLDS / f"{name}.yaml"
    for name in (
        "all-five-types",
        "calibration-both-bounds",
        "feedback-latency-p50-only",
        "single-bounds",
        "segments-two-dimensions",
    )
)
HEADING = "## Judgment thresholds"


def _load(path: Path) -> ReliabilityManifest:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return load_manifest(path)


def _api_md(path: Path, tmp: Path) -> str:
    result = generate_service_docs(path, tmp, include_api=True)
    assert result.success, result.error
    return (tmp / "api.md").read_text(encoding="utf-8")


def _section(md: str) -> list[str]:
    lines = md.splitlines()
    start = lines.index(HEADING)
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    return lines[start:end]


def _rows(section: list[str]) -> list[list[str]]:
    """Table body rows, as stripped cells (header and separator dropped)."""
    table = [line for line in section if line.startswith("|")]
    return [[c.strip() for c in line.strip("|").split("|")] for line in table[2:]]


def _declared(path: Path) -> list[tuple[str, str, Any]]:
    doc = yaml.safe_load(path.read_text())
    return [
        (t["type"], bound, value)
        for t in doc["spec"]["judgment_threshold"]
        for bound, value in t["bounds"].items()
    ]


def test_fixtures_are_present_and_cover_both_kinds_of_bound():
    missing = [str(p) for p in FIXTURES if not p.is_file()]
    assert not missing, f"missing fixtures: {missing}"
    types = {t for p in FIXTURES for t, _, _ in _declared(p)}
    assert {t for t in types if THRESHOLD_SERIES[t]} and {
        t for t in types if not THRESHOLD_SERIES[t]
    }


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_one_row_per_declared_bound_with_its_declared_value(path: Path, tmp_path: Path):
    rows = _rows(_section(_api_md(path, tmp_path)))

    assert [(r[0], r[1], r[2]) for r in rows] == [(t, b, str(v)) for t, b, v in _declared(path)]


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_evaluated_by_names_the_emitted_rule_and_alerts_or_workers(path: Path, tmp_path: Path):
    manifest = _load(path)
    alerts_by_bound: dict[str, set[str]] = {}
    records_by_bound: dict[str, str] = {}
    for alert in build_judgment_threshold_alerts(manifest):
        alerts_by_bound.setdefault(alert.labels["bound"], set()).add(alert.name)
        if alert.name.endswith("Breach"):
            records_by_bound[alert.labels["bound"]] = alert.expr.split("{", 1)[0]

    for threshold_type, bound, _value, evaluated_by in (
        r[:4] for r in _rows(_section(_api_md(path, tmp_path)))
    ):
        if THRESHOLD_SERIES[threshold_type]:
            assert f"`{records_by_bound[bound]}`" in evaluated_by
            for name in alerts_by_bound[bound]:
                assert f"`{name}`" in evaluated_by
        else:
            assert evaluated_by == "nthlayer-workers; no Prometheus rule"


def test_measurement_fields_are_shown(tmp_path: Path):
    path = THRESHOLDS / "segments-two-dimensions.yaml"
    entries = yaml.safe_load(path.read_text())["spec"]["judgment_threshold"]

    rows = _rows(_section(_api_md(path, tmp_path)))

    for entry, row in zip(entries, rows, strict=True):
        measurement = row[4]
        # OPENSRM-CORE-v2 §5.5.1: segment_dimension/values sit on the entry itself.
        assert entry["segment_dimension"] in measurement
        for value in entry["segment_values"]:
            assert value in measurement


def test_section_follows_judgment_slos(tmp_path: Path):
    md = _api_md(FIXTURES[0], tmp_path).splitlines()
    assert md.index("## Judgment SLOs") < md.index(HEADING)


def test_no_thresholds_means_no_section():
    manifest = dataclasses.replace(_load(FIXTURES[0]), judgment_thresholds=[])
    assert manifest.is_ai_gate()

    assert HEADING not in _api_docs_ai_gate(manifest).splitlines()


def test_a_pipe_in_a_declared_value_does_not_split_the_row():
    """R5 pass 1: an unescaped '|' would shift every later column."""
    manifest = _load(THRESHOLDS / "segments-two-dimensions.yaml")
    first = manifest.judgment_thresholds[0]
    measurement = dataclasses.replace(first.measurement, segment_values=["a|b", "c"])
    manifest = dataclasses.replace(
        manifest,
        judgment_thresholds=[dataclasses.replace(first, measurement=measurement)],
    )

    (row,) = [
        line for line in _api_docs_ai_gate(manifest).splitlines() if line.startswith("| segments")
    ]

    # Five cells: the escaped pipe is not a separator.
    assert len(row.replace("\\|", "").strip("|").split("|")) == 5
    assert "a\\|b" in row
