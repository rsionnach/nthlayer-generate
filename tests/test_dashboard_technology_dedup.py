"""One set of technology panels per technology, however many dependencies use it.

Ported from the legacy builder's test_templates_avoid_duplicates
(opensrm-wo62.4.22, ruling J2). On the manifest path a second postgres
dependency used to add the ten PostgreSQL panels again: identical queries
for a repeated type, and for an alias (postgresql) the same queries under
that spelling's service label. The panels describe the technology, not the
instance; the first-declared spelling's set is kept.

The input is examples/services/payment-api-with-deps.yaml with its own
postgres-main entry copied under a new name, so the dependency shape is the
shipped one. No shipped manifest repeats a technology on its own, but three
shipped env overlays do once merged (examples/environments/payment-api-dev,
payment-api-prod and search-api-prod add a second Dependencies resource), and
the staged env golden cells pin that case end to end.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml
from nthlayer_common.manifest import load_manifest

from nthlayer_generate.dashboards.manifest_builder import build_dashboard_from_manifest

SHIPPED = (
    Path(__file__).resolve().parents[1] / "examples" / "services" / "payment-api-with-deps.yaml"
)


def _panel_titles(manifest_path: Path) -> list[str]:
    manifest = load_manifest(manifest_path, suppress_deprecation_warning=True)
    titles = []
    for panel in build_dashboard_from_manifest(manifest)["dashboard"]["panels"]:
        titles.append(panel["title"])
        titles.extend(child["title"] for child in panel.get("panels", []))
    return titles


def _with_postgres_twin(tmp_path: Path, twin_type: str) -> Path:
    data: dict[str, Any] = yaml.safe_load(SHIPPED.read_text(encoding="utf-8"))
    (deps,) = [r for r in data["resources"] if r["kind"] == "Dependencies"]
    databases = deps["spec"]["databases"]
    (postgres,) = [db for db in databases if db["name"] == "postgres-main"]
    twin = copy.deepcopy(postgres)
    twin["name"] = "postgres-replica"
    twin["type"] = twin_type
    databases.append(twin)
    path = tmp_path / SHIPPED.name
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


# "postgres" repeats the shipped entry's type; "postgresql" is the alias the
# other shipped examples use, which resolves to the same dashboard template.
@pytest.mark.parametrize("twin_type", ["postgres", "postgresql"])
def test_a_second_dependency_on_a_technology_adds_no_panels(tmp_path: Path, twin_type: str):
    baseline = _panel_titles(SHIPPED)
    assert "PostgreSQL Connections" in baseline  # the shipped file has postgres panels

    assert _panel_titles(_with_postgres_twin(tmp_path, twin_type)) == baseline
