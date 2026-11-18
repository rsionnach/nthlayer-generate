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
import structlog
import yaml
from nthlayer_common.manifest import Dependency, ReliabilityManifest, load_manifest

from nthlayer_generate.dashboards.manifest_builder import ManifestDashboardBuilder
from nthlayer_generate.dashboards.templates import get_template_or_none
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


def _payment_api_without_a_latency_bound(tmp_path):
    """payment-api.yaml loaded with latency-p95's threshold_ms removed."""
    doc = yaml.safe_load((SERVICES / "payment-api.yaml").read_text())
    for resource in doc["resources"]:
        if resource.get("kind") == "SLO" and resource.get("name") == "latency-p95":
            del resource["spec"]["indicator"]["threshold_ms"]
    path = tmp_path / "payment-api.yaml"
    path.write_text(yaml.safe_dump(doc, sort_keys=False))
    manifest = _load(path)
    assert {s.name: s.threshold_ms for s in manifest.slos}["latency-p95"] is None
    return manifest


def test_sloth_legacy_without_a_bound_keeps_the_legacy_default(tmp_path):
    """payment-api's latency-p95 with its threshold_ms removed: no committed
    legacy example has a query and no bound, so this one is derived. The legacy
    builder defaulted to 1000 ms; the objective (99.0) must not stand in."""
    manifest = _payment_api_without_a_latency_bound(tmp_path)

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
        # legacy: checkout-service declares threshold_ms: 800 inside a plural
        # indicators: list, which nthlayer-common reads since 5.12.1
        # (opensrm-wo62.4.24).
        pytest.param(
            SERVICES / "checkout-service.yaml",
            "latency-p95",
            "0.8",
            "800ms",
            id="legacy-plural-indicators",
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


def test_recording_rule_without_a_bound_keeps_the_500_ms_default(tmp_path):
    """Derived, as the sloth case above: no committed legacy example has a
    latency SLO with no bound."""
    rule = _latency_fast_rule(_payment_api_without_a_latency_bound(tmp_path), "latency-p95")

    assert 'le="0.5"' in rule["expr"]
    assert rule["threshold"] == "500ms"


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
        # Name keywords: the alerts/loki rule this was moved from
        # (specs/helpers.py extract_dependency_technologies @88057bb).
        pytest.param(Dependency(name="events-kafka", type="queue"), "kafka", id="queue-name"),
        pytest.param(Dependency(name="rabbit-jobs", type="queue"), "rabbitmq", id="queue-rabbit"),
        pytest.param(
            Dependency(name="memcache-sessions", type="cache"), "memcached", id="cache-memcache"
        ),
        # examples/opensrm/worker.reliability.yaml: an untyped "sqs-queue".
        pytest.param(Dependency(name="sqs-queue", type="queue"), "sqs", id="queue-sqs"),
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
    with structlog.testing.capture_logs() as logs:
        resources = builder._manifest_to_resources(builder._manifest_to_context())
    spec = next(r.spec for r in resources if r.kind == "Dependencies")

    assert "sqs" not in {q["type"] for q in spec["queues"]}
    sqs_queues = {d.name for d in manifest.dependencies if dependency_technology(d) == "sqs"}
    assert _skipped_dependencies(logs, "queue") == dict.fromkeys(sqs_queues, (NO_TEMPLATE, "sqs"))
    assert builder.build()["dashboard"]["panels"]


def test_cache_declaring_an_untemplated_technology_is_skipped():
    """Derived, and from the implementation: opensrm/spec/v1/specification.md
    §7.2 has no database_type, but NthLayer's srm/v1 parser reads one as an
    extension (common parser/v1.py), so a file can declare it.
    examples/opensrm/api-critical.reliability.yaml's cache, re-declared as
    elasticache: base drew redis panels from the name, the declared technology
    then failed the dashboard. The real artefact for the skip is
    notification-service's sqs queue (the test above)."""
    manifest = _load(EXAMPLES / "opensrm" / "api-critical.reliability.yaml")
    caches = [d for d in manifest.dependencies if d.type == "cache"]
    assert caches
    deps = [
        dataclasses.replace(d, database_type="elasticache") if d.type == "cache" else d
        for d in manifest.dependencies
    ]
    builder = ManifestDashboardBuilder(manifest=dataclasses.replace(manifest, dependencies=deps))

    assert builder.build()["dashboard"]["panels"]


# --- untemplated database technologies (opensrm-wo62.4.16) ------------------
#
# Every manifest is a committed file, loaded unmodified. The expectations are
# what each file declares: `kept` are its database dependencies whose declared
# technology has a dashboard template (dashboards/templates/__init__.py,
# TECHNOLOGY_TEMPLATES); `skipped` maps the others to why they are left out
# and the technology the file declares for them: one with no template, or none.

NO_TEMPLATE = "no_dashboard_template"
NO_TECHNOLOGY = "no_technology_declared"

GOLDEN_FIXTURES = Path(__file__).resolve().parent / "golden" / "fixtures"

UNTEMPLATED_DATABASE_MANIFESTS = [
    pytest.param(
        SERVICES / "analytics-pipeline.yaml",
        {},
        {"analytics-warehouse": (NO_TEMPLATE, "bigquery"), "raw-data-lake": (NO_TEMPLATE, "s3")},
        id="bigquery-and-s3",
    ),
    pytest.param(
        SERVICES / "batch-reports.yaml",
        {"analytics-db": "postgresql"},
        {"reports-storage": (NO_TEMPLATE, "s3")},
        id="s3-beside-postgresql",
    ),
    pytest.param(
        GOLDEN_FIXTURES / "legacy" / "checkout-db-deps.yaml",
        {"postgres-main": "postgres", "postgres-replica": "postgres"},
        {"mysql-orders": (NO_TECHNOLOGY, None)},
        id="untyped-beside-postgres",
    ),
    pytest.param(
        EXAMPLES / "opensrm" / "ai-gate.reliability.yaml",
        {},
        {"feature-store": (NO_TECHNOLOGY, None)},
        id="untyped",
    ),
    pytest.param(
        EXAMPLES / "opensrm" / "batch.reliability.yaml",
        {},
        {"redshift": (NO_TEMPLATE, "redshift"), "s3-bucket": (NO_TEMPLATE, "s3")},
        id="redshift-and-s3",
    ),
    pytest.param(
        EXAMPLES / "opensrm" / "stream.reliability.yaml",
        {},
        {"clickhouse": (NO_TEMPLATE, "clickhouse")},
        id="clickhouse",
    ),
]


def _skipped_dependencies(logs: list, dependency_type: str) -> dict[str, tuple[str, str | None]]:
    """``{dependency name: (reason, technology)}`` for the
    ``dashboard_dependency_skipped`` warnings of one dependency type among
    captured structlog entries."""
    return {
        entry["dependency"]: (entry["reason"], entry["technology"])
        for entry in logs
        if entry["event"] == "dashboard_dependency_skipped"
        and entry["log_level"] == "warning"
        and entry["dependency_type"] == dependency_type
    }


def test_untemplated_database_manifests_are_listed():
    """Guard the parametrize list: an empty one collects nothing."""
    assert len(UNTEMPLATED_DATABASE_MANIFESTS) == 6
    for param in UNTEMPLATED_DATABASE_MANIFESTS:
        assert param.values[0].is_file()


@pytest.mark.parametrize(("path", "kept", "skipped"), UNTEMPLATED_DATABASE_MANIFESTS)
def test_database_without_a_dashboard_template_is_skipped(path, kept, skipped):
    """Ruling E6 (Rob, 2026-10-29): a database technology with no dashboard
    template is left out with a warning, as a cache or queue is, and the
    dashboard is written without its panels. It used to fail the dashboard
    with "No template found for technology"."""
    manifest = _load(path)
    declared = {d.name for d in manifest.dependencies if d.type == "database"}
    assert declared == set(kept) | set(skipped), "the file's databases changed"

    builder = ManifestDashboardBuilder(manifest=manifest)
    with structlog.testing.capture_logs() as logs:
        resources = builder._manifest_to_resources(builder._manifest_to_context())
    spec = next(r.spec for r in resources if r.kind == "Dependencies")

    assert {d["name"]: d["type"] for d in spec["databases"]} == kept
    assert _skipped_dependencies(logs, "database") == skipped
    # Only a dependency that declares no technology is told how to get panels.
    hinted = {
        e["dependency"]
        for e in logs
        if e.get("hint") or e.get("technology_key") or e.get("example_technology")
    }
    assert hinted == {name for name, (reason, _) in skipped.items() if reason == NO_TECHNOLOGY}

    assert builder.build()["dashboard"]["panels"]


def test_declared_database_technology_is_normalised_like_a_cache_or_queue():
    """Derived: examples/services/batch-reports.yaml's analytics-db (type:
    postgresql), re-declared with the spelling " PostgreSQL ". The legacy
    format's `type:` is a free string, so a file can carry it. A database now
    goes through dependency_technology, as a cache or queue does (wo62.4 D5),
    so the dashboard gets the technology stripped and lower-cased; the raw
    spelling used to reach the panels' service label, and with the padding it
    matched no template at all."""
    manifest = _load(SERVICES / "batch-reports.yaml")
    assert "analytics-db" in {d.name for d in manifest.dependencies}
    deps = [
        dataclasses.replace(d, database_type=" PostgreSQL ") if d.name == "analytics-db" else d
        for d in manifest.dependencies
    ]
    builder = ManifestDashboardBuilder(manifest=dataclasses.replace(manifest, dependencies=deps))
    resources = builder._manifest_to_resources(builder._manifest_to_context())
    spec = next(r.spec for r in resources if r.kind == "Dependencies")

    assert {d["name"]: d["type"] for d in spec["databases"]} == {"analytics-db": "postgresql"}


# The hint names the key each format's parser reads the technology from
# (nthlayer-common: the legacy loader takes a database's `type:`,
# parser/loader.py; the srm/v1 parser takes `database_type`, parser/v1.py).
# Each case is a committed file with an untyped database, and the edit that
# follows the hint, applied to the file's parsed YAML.


def _legacy_database_entry(data, name):
    (deps,) = [r for r in data["resources"] if r.get("kind") == "Dependencies"]
    (entry,) = [d for d in deps["spec"]["databases"] if d["name"] == name]
    return entry


def _srm_v1_dependency(data, name):
    (entry,) = [d for d in data["spec"]["dependencies"] if d["name"] == name]
    return entry


# (file, untyped database, the key its format declares a technology with,
#  where that key goes, how to find the database's entry in the parsed YAML)
UNTYPED_DATABASE_HINT_CASES = [
    pytest.param(
        GOLDEN_FIXTURES / "legacy" / "checkout-db-deps.yaml",
        "mysql-orders",
        "type",
        "the database entry",
        _legacy_database_entry,
        id="legacy",
    ),
    pytest.param(
        EXAMPLES / "opensrm" / "ai-gate.reliability.yaml",
        "feature-store",
        "database_type",
        "the dependency",
        _srm_v1_dependency,
        id="srm-v1",
    ),
]


@pytest.mark.parametrize(
    ("path", "name", "key", "where", "find_entry"), UNTYPED_DATABASE_HINT_CASES
)
def test_skip_event_says_which_key_to_set_and_to_what(path, name, key, where, find_entry, tmp_path):
    """opensrm-ip9r, opensrm-sjgi: a database that declares no technology is
    skipped with the key its manifest format reads and a technology that has
    a template, and setting that key to that technology gets it its panels."""
    builder = ManifestDashboardBuilder(manifest=_load(path))
    with structlog.testing.capture_logs() as logs:
        builder._manifest_to_resources(builder._manifest_to_context())
    (entry,) = [e for e in logs if e.get("dependency") == name]
    assert entry["reason"] == NO_TECHNOLOGY
    assert entry["technology_key"] == key
    example = entry["example_technology"]
    assert get_template_or_none(example) is not None, "the example has no template"
    # The sentence an operator reads is made of the same parts.
    assert entry["hint"] == (
        f"set {key} on {where} to the database's technology; "
        f"one with a dashboard template, such as {example}, gets panels"
    )

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    find_entry(data, name)[entry["technology_key"]] = example
    declared = tmp_path / path.name
    declared.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    builder = ManifestDashboardBuilder(manifest=_load(declared))
    with structlog.testing.capture_logs() as logs:
        resources = builder._manifest_to_resources(builder._manifest_to_context())
    spec = next(r.spec for r in resources if r.kind == "Dependencies")
    assert {d["name"]: d["type"] for d in spec["databases"]}[name] == example
    assert name not in _skipped_dependencies(logs, "database")
