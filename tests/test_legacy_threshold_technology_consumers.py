"""Generate's consumers of nthlayer-common 5.7.0's legacy fields (opensrm-wo62.4.3).

common's legacy loader now carries a latency SLO's bound in
``SLODefinition.threshold_ms`` and a cache's or queue's declared ``type:`` in
``Dependency.database_type`` (opensrm-wo62.4.7). Before, the manifest path
used the 0-100 objective as the bound ("99% under 100ms" became "> 0.099")
and guessed queue technology from the name (email-queue became "email").

Every manifest below is a committed example; expected values are what the
example declares, and the legacy defaults are cited from the legacy builders
(generators/sloth.py convert_indicator_to_sli: 1000 ms;
recording_rules/builder.py: 500 ms).
"""

from __future__ import annotations

import dataclasses
import warnings
from pathlib import Path

import pytest
import yaml
from nthlayer_common.manifest import Dependency, ReliabilityManifest, load_manifest

from nthlayer_generate.dashboards.manifest_builder import ManifestDashboardBuilder
from nthlayer_generate.generators.sloth import generate_sloth_from_manifest
from nthlayer_generate.recording_rules.manifest_builder import (
    build_recording_rules_from_manifest,
)
from nthlayer_generate.specs.helpers import dependency_technology

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
SERVICES = EXAMPLES / "services"


def _load(path: Path) -> ReliabilityManifest:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return load_manifest(path)


def _sloth_error_queries(manifest: ReliabilityManifest, tmp_path: Path) -> dict[str, str]:
    result = generate_sloth_from_manifest(manifest, tmp_path)
    assert result.success, result.error
    doc = yaml.safe_load(result.output_file.read_text())
    return {s["name"]: s["sli"]["events"]["error_query"] for s in doc["slos"]}


def _latency_fast_rule(manifest: ReliabilityManifest, slo: str) -> dict:
    for group in build_recording_rules_from_manifest(manifest):
        for rule in group.rules:
            if (
                rule.record.startswith("slo:latency_requests_fast:")
                and rule.labels.get("slo") == slo
            ):
                return {"expr": rule.expr, "threshold": rule.labels["threshold"]}
    raise AssertionError(f"no latency_requests_fast rule for {slo}")


# =============================================================================
# Latency bound
# =============================================================================


@pytest.mark.parametrize(
    ("example", "slo", "bound_seconds"),
    [
        # indicator.threshold_ms: 100, objective 99.0
        pytest.param("auth-api.yaml", "token-generation-latency", 0.1, id="auth-api"),
        # critical-api template: indicator.threshold_ms: 500, objective 99.0
        pytest.param("api-minimal.yaml", "latency-p95", 0.5, id="api-minimal-template"),
        # indicator.threshold_ms: 300
        pytest.param("search-api.yaml", "search-latency-p95", 0.3, id="search-api"),
    ],
)
def test_sloth_bound_is_the_declared_threshold(tmp_path, example, slo, bound_seconds):
    queries = _sloth_error_queries(_load(SERVICES / example), tmp_path)

    assert queries[slo].endswith(f"> {bound_seconds}")


def test_sloth_legacy_without_a_bound_keeps_the_legacy_default(tmp_path):
    """payment-api's latency-p95 with its threshold_ms removed: no committed
    legacy example has a query and no bound, so this one is derived. The legacy
    builder defaulted to 1000 ms; the objective (99.0) must not stand in."""
    doc = yaml.safe_load((SERVICES / "payment-api.yaml").read_text())
    for resource in doc["resources"]:
        if resource.get("kind") == "SLO" and resource.get("name") == "latency-p95":
            del resource["spec"]["indicator"]["threshold_ms"]
    path = tmp_path / "payment-api.yaml"
    path.write_text(yaml.safe_dump(doc, sort_keys=False))
    manifest = _load(path)
    assert {s.name: s.threshold_ms for s in manifest.slos}["latency-p95"] is None

    queries = _sloth_error_queries(manifest, tmp_path / "out")

    assert queries["latency-p95"].endswith("> 1.0")


@pytest.mark.parametrize(
    ("path", "slo", "le", "label"),
    [
        # legacy: indicator.threshold_ms: 100
        pytest.param(
            SERVICES / "auth-api.yaml",
            "token-generation-latency",
            "0.1",
            "100ms",
            id="legacy-declared",
        ),
        # legacy: no bound declared, no query; the legacy builder's 500 ms default
        pytest.param(
            SERVICES / "checkout-service.yaml", "latency-p95", "0.5", "500ms", id="legacy-default"
        ),
        # srm/v1: target 100, unit ms — the bound is the target, unchanged
        pytest.param(
            EXAMPLES / "opensrm" / "ai-gate.reliability.yaml",
            "latency",
            "0.1",
            "100ms",
            id="srm-v1-target",
        ),
    ],
)
def test_recording_rule_bound(path, slo, le, label):
    rule = _latency_fast_rule(_load(path), slo)

    assert f'le="{le}"' in rule["expr"]
    assert rule["threshold"] == label


# =============================================================================
# Cache and queue technology
# =============================================================================


@pytest.mark.parametrize(
    ("dep", "expected"),
    [
        # Declared technology wins over the name.
        pytest.param(
            Dependency(name="email-queue", type="queue", database_type="rabbitmq"),
            "rabbitmq",
            id="queue-declared",
        ),
        pytest.param(
            Dependency(name="redis-cache", type="cache", database_type="memcached"),
            "memcached",
            id="cache-declared-beats-name",
        ),
        # Undeclared: name inference, then the shared rule's redis/kafka defaults.
        pytest.param(Dependency(name="events-kafka", type="queue"), "kafka", id="queue-name"),
        pytest.param(Dependency(name="jobs", type="queue"), "kafka", id="queue-default"),
        pytest.param(Dependency(name="sessions", type="cache"), "redis", id="cache-default"),
        # APIs map to no template whatever they carry.
        pytest.param(
            Dependency(name="billing", type="api", database_type="postgresql"),
            None,
            id="api-ignores-database-type",
        ),
        pytest.param(Dependency(name="orders-db", type="database"), None, id="untyped-database"),
    ],
)
def test_dependency_technology(dep, expected):
    assert dependency_technology(dep) == expected


def test_email_worker_queue_and_dashboard_use_the_declared_type():
    """examples/services/email-worker.yaml: email-queue (type: rabbitmq) and
    email-templates-db (type: postgresql). The dashboard used to name the queue
    "email" (its name prefix), which has no template."""
    manifest = _load(SERVICES / "email-worker.yaml")
    deps = {d.name: d for d in manifest.dependencies}
    assert dependency_technology(deps["email-queue"]) == "rabbitmq"

    builder = ManifestDashboardBuilder(manifest=manifest)
    resources = builder._manifest_to_resources(builder._manifest_to_context())
    spec = next(r.spec for r in resources if r.kind == "Dependencies")

    assert {q["name"]: q["type"] for q in spec["queues"]} == {"email-queue": "rabbitmq"}


def test_search_api_cache_uses_the_declared_type():
    """examples/services/search-api.yaml: query-cache (type: redis)."""
    manifest = _load(SERVICES / "search-api.yaml")
    builder = ManifestDashboardBuilder(manifest=manifest)
    resources = builder._manifest_to_resources(builder._manifest_to_context())
    spec = next(r.spec for r in resources if r.kind == "Dependencies")

    assert {c["name"]: c["type"] for c in spec["caches"]} == {"query-cache": "redis"}


def test_recording_rule_le_is_formatted_as_exporters_write_it():
    """A bound of 1e9 ms is le 1e+06 in exporters' formatting (prometheus_le,
    Go's %g), not "1000000.0"; the label drops the float's trailing .0."""
    manifest = _load(SERVICES / "auth-api.yaml")
    slos = [
        dataclasses.replace(s, threshold_ms=1e9) if s.name == "token-generation-latency" else s
        for s in manifest.slos
    ]

    rule = _latency_fast_rule(dataclasses.replace(manifest, slos=slos), "token-generation-latency")

    assert 'le="1e+06"' in rule["expr"]
    assert rule["threshold"] == "1e+09ms"


@pytest.mark.parametrize(
    ("declared", "expected"),
    [
        pytest.param(" Redis ", "redis", id="whitespace-and-case"),
        pytest.param("   ", "redis", id="blank-falls-back-to-name"),
    ],
)
def test_declared_technology_is_normalised(declared, expected):
    dep = Dependency(name="redis-sessions", type="cache", database_type=declared)

    assert dependency_technology(dep) == expected


def test_queue_without_a_dashboard_template_is_skipped():
    """examples/services/notification-service.yaml declares a queue with
    type: sqs, for which no dashboard template exists. Rob, 2026-10-28: leave
    it out with a warning, as alerts do, rather than fail the dashboard (the
    legacy builder failed here too)."""
    manifest = _load(SERVICES / "notification-service.yaml")
    assert "sqs" in {dependency_technology(d) for d in manifest.dependencies}
    builder = ManifestDashboardBuilder(manifest=manifest)
    resources = builder._manifest_to_resources(builder._manifest_to_context())
    spec = next(r.spec for r in resources if r.kind == "Dependencies")

    assert "sqs" not in {q["type"] for q in spec["queues"]}
    assert builder.build()["dashboard"]["panels"]


def test_cache_declaring_an_untemplated_technology_is_skipped():
    """srm/v1 carries database_type on any dependency (common parser/v1.py).
    examples/opensrm/api-critical.reliability.yaml's redis cache, re-declared
    as elasticache: base drew redis panels from the name, then the declared
    technology made the dashboard fail outright."""
    manifest = _load(EXAMPLES / "opensrm" / "api-critical.reliability.yaml")
    caches = [d for d in manifest.dependencies if d.type == "cache"]
    assert caches
    deps = [
        dataclasses.replace(d, database_type="elasticache") if d.type == "cache" else d
        for d in manifest.dependencies
    ]
    builder = ManifestDashboardBuilder(manifest=dataclasses.replace(manifest, dependencies=deps))

    assert builder.build()["dashboard"]["panels"]
