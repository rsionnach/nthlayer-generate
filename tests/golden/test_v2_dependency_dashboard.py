"""An opensrm.nthlayer.io/v2 dependency in the dashboard builder (opensrm-ip9r).

opensrm/spec/v2/AUTHORING.md 7.5, "Dependencies lose `critical` and `type`": a
v2 dependency has no type, so nthlayer-common loads it as an api dependency
and the builder's technology skip rule never sees it. The input is the spec's
committed migration example, found through the corpus's V2_EXAMPLES like
every other spec file these tests read.
"""

from __future__ import annotations

import warnings

import structlog
from nthlayer_common.manifest import load_manifest

from nthlayer_generate.dashboards.manifest_builder import ManifestDashboardBuilder

from ._corpus import V2_EXAMPLES

API_FULL_V2 = V2_EXAMPLES / "migration" / "api-full-v2.yaml"


def test_v2_dependencies_are_not_technology_dependencies() -> None:
    """The example names a dependency postgresql. It is listed as a service,
    not a database, and nothing is reported as skipped."""
    assert API_FULL_V2.is_file(), "the spec's migration example moved: this must not skip"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        manifest = load_manifest(API_FULL_V2)
    assert "postgresql" in {d.name for d in manifest.dependencies}
    assert {d.type for d in manifest.dependencies} == {"api"}

    builder = ManifestDashboardBuilder(manifest=manifest)
    with structlog.testing.capture_logs() as logs:
        resources = builder._manifest_to_resources(builder._manifest_to_context())
    spec = next(r.spec for r in resources if r.kind == "Dependencies")

    assert spec["databases"] == []
    assert "postgresql" in {d["name"] for d in spec["services"]}
    assert [e for e in logs if e["event"] == "dashboard_dependency_skipped"] == []
