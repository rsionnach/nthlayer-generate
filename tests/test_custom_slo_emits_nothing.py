"""An SLO with no rule family is not read as a success ratio (opensrm-onc6).

Rob, 2026-11-23: a custom SLO must emit nothing; not crash, not fall back to
a default. The recording rules already write it no budget (ruling D5); these
tests cover the other places that read an SLO: the Sloth spec, the dashboard,
`alerts evaluate` and `slo show/collect`.

Fixture provenance: the manifests are the shipped legacy examples in
examples/services/, loaded from disk unmodified. Each declares one SLO with
``indicator.type: custom`` beside request-ratio SLOs: analytics-stream
``stream-lag`` and notification-worker ``queue-lag`` (no query), search-api
``search-quality`` (with a query).
"""

from __future__ import annotations

import asyncio
import dataclasses
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import yaml
from nthlayer_common.manifest import ReliabilityManifest, load_manifest

from nthlayer_generate.cli.generate import generate_slo_command
from nthlayer_generate.cli.slo import _collect_slo_metrics, _is_objective
from nthlayer_generate.core.slo_kind import slo_kind
from nthlayer_generate.dashboards.manifest_builder import build_dashboard_from_manifest
from nthlayer_generate.generators.sloth import generate_sloth_from_manifest
from nthlayer_generate.slos.pipeline import AlertPipeline

SERVICES = Path(__file__).resolve().parents[1] / "examples" / "services"

# (file, the custom SLO, the request-ratio SLOs beside it)
CUSTOM = [
    ("analytics-stream.yaml", "stream-lag", {"processing-availability", "event-latency-p99"}),
    ("notification-worker.yaml", "queue-lag", {"delivery-success", "processing-latency-p95"}),
    ("search-api.yaml", "search-quality", {"search-availability", "search-latency-p95"}),
]
assert CUSTOM, "no custom-SLO fixtures"
IDS = [c[0] for c in CUSTOM]


def _load(name: str) -> ReliabilityManifest:
    return load_manifest(SERVICES / name, suppress_deprecation_warning=True)


@pytest.mark.parametrize(("name", "custom", "others"), CUSTOM, ids=IDS)
def test_the_fixture_is_what_the_tests_assume(name: str, custom: str, others: set[str]):
    manifest = _load(name)
    by_name = {s.name: s for s in manifest.slos}
    assert set(by_name) == {custom} | others
    assert by_name[custom].slo_type == "custom"
    assert slo_kind(by_name[custom]) is None
    assert all(slo_kind(by_name[o]) is not None for o in others)
    # Inside (0, 100): only the kind keeps it from being read as an objective.
    assert 0 < by_name[custom].target < 100


@pytest.mark.parametrize(("name", "custom", "others"), CUSTOM, ids=IDS)
def test_sloth_spec_has_no_entry_for_it(name: str, custom: str, others: set[str], tmp_path: Path):
    result = generate_sloth_from_manifest(_load(name), tmp_path)
    assert result.success, result.error
    assert result.output_file is not None
    spec = yaml.safe_load(result.output_file.read_text(encoding="utf-8"))
    assert {s["name"] for s in spec["slos"]} == others
    assert result.slo_count == len(others)


def _only_the_custom_slo(name: str, custom: str) -> ReliabilityManifest:
    """The shipped manifest with its request-ratio SLOs removed."""
    manifest = _load(name)
    return dataclasses.replace(manifest, slos=[s for s in manifest.slos if s.name == custom])


@pytest.mark.parametrize(("name", "custom", "others"), CUSTOM, ids=IDS)
def test_sloth_writes_no_file_when_every_slo_is_skipped(
    name: str, custom: str, others: set[str], tmp_path: Path
):
    manifest = _only_the_custom_slo(name, custom)
    assert [s.name for s in manifest.slos] == [custom]
    result = generate_sloth_from_manifest(manifest, tmp_path / "sloth")
    assert result.success, result.error
    assert result.slo_count == 0
    assert result.output_file is None
    assert not (tmp_path / "sloth").exists()


@pytest.mark.parametrize(("name", "custom", "others"), CUSTOM, ids=IDS)
def test_alert_pipeline_with_only_a_custom_slo_evaluates_nothing(
    name: str, custom: str, others: set[str]
):
    manifest = _only_the_custom_slo(name, custom)
    result = AlertPipeline(dry_run=True).evaluate_service(manifest, simulate_burn_pct=90.0)
    assert not result.errors
    assert result.budgets == []
    assert result.budgets_evaluated == 0
    assert result.events == []


@pytest.mark.parametrize(("name", "custom", "others"), CUSTOM, ids=IDS)
def test_dashboard_with_only_a_custom_slo_still_builds(name: str, custom: str, others: set[str]):
    titles = _panel_titles(build_dashboard_from_manifest(_only_the_custom_slo(name, custom)))
    assert titles
    assert custom not in titles


@pytest.mark.parametrize(("name", "custom", "others"), CUSTOM, ids=IDS)
def test_generate_slo_command_succeeds_and_writes_nothing_for_only_a_custom_slo(
    name: str, custom: str, others: set[str], tmp_path: Path
):
    # The shipped file with its request-ratio SLO resources removed.
    doc = yaml.safe_load((SERVICES / name).read_text(encoding="utf-8"))
    doc["resources"] = [
        r for r in doc["resources"] if not (r["kind"] == "SLO" and r["name"] in others)
    ]
    service_file = tmp_path / name
    service_file.write_text(yaml.safe_dump(doc), encoding="utf-8")
    assert [
        s.name for s in load_manifest(service_file, suppress_deprecation_warning=True).slos
    ] == [custom]

    out = tmp_path / "out"
    # It reports "nothing written", not "Generated SLOs" with no output path.
    with patch("nthlayer_generate.cli.generate.success") as said_generated:
        assert generate_slo_command(str(service_file), output_dir=str(out)) == 0
    said_generated.assert_not_called()
    assert not out.exists() or not list(out.rglob("*.yaml"))


def _panel_titles(dashboard: dict) -> set[str]:
    titles: set[str] = set()
    stack = list(dashboard["dashboard"]["panels"])
    while stack:
        panel = stack.pop()
        titles.add(panel.get("title", ""))
        stack.extend(panel.get("panels") or [])
    return titles


@pytest.mark.parametrize(("name", "custom", "others"), CUSTOM, ids=IDS)
def test_dashboard_has_no_panel_for_it(name: str, custom: str, others: set[str]):
    titles = _panel_titles(build_dashboard_from_manifest(_load(name)))
    assert custom not in titles
    assert others <= titles


@pytest.mark.parametrize(("name", "custom", "others"), CUSTOM, ids=IDS)
def test_alert_pipeline_gives_it_no_budget_and_no_alert(name: str, custom: str, others: set[str]):
    manifest = _load(name)
    # 90% burned: before the fix this fired warning and critical budget
    # alerts for the custom SLO.
    result = AlertPipeline(dry_run=True).evaluate_service(manifest, simulate_burn_pct=90.0)
    assert not result.errors
    budget_ids = {b.slo_id for b in result.budgets}
    assert budget_ids == {f"{manifest.name}-{o}" for o in others}
    assert result.budgets_evaluated == len(others)
    assert {e.slo_id for e in result.events} <= budget_ids
    # The others still alert, so the assertion above is not vacuous.
    assert result.events


@pytest.mark.parametrize(("name", "custom", "others"), CUSTOM, ids=IDS)
def test_slo_cli_does_not_treat_it_as_an_objective(name: str, custom: str, others: set[str]):
    manifest = _load(name)
    by_name = {s.name: s for s in manifest.slos}
    assert _is_objective(manifest, by_name[custom]) is False
    assert all(_is_objective(manifest, by_name[o]) for o in others)


def test_slo_collect_does_not_query_or_budget_it():
    # search-quality has a query, so only the kind stops collect running it.
    manifest = _load("search-api.yaml")
    queries: list[str] = []

    async def get_sli_value(query: str) -> float:
        queries.append(query)
        return 0.999

    with patch("nthlayer_generate.providers.prometheus.PrometheusProvider") as provider_cls:
        provider_cls.return_value.get_sli_value = AsyncMock(side_effect=get_sli_value)
        results = asyncio.run(_collect_slo_metrics(manifest, "http://prometheus:9090"))

    by_name = {r["name"]: r for r in results}
    row = by_name["search-quality"]
    assert row["status"] == "NOT_APPLICABLE"
    assert row["total_budget_minutes"] is None
    assert row["burned_minutes"] is None
    assert row["current_sli"] is None
    assert not any("search_results_total" in q for q in queries)
    # The request-ratio SLOs beside it were queried and budgeted.
    assert by_name["search-availability"]["status"] != "NOT_APPLICABLE"
    assert queries
