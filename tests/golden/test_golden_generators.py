"""Library-generator cells: every manifest-path generator over the corpus (spec §6.2).

One test function per cell, each parametrised over the srm/v1, legacy and
OpenSRM v2 manifests that load today. The loadable set is found by loading
the corpus (the same call the ``load`` cell pins), not hard-coded, so a manifest that
starts or stops loading moves in or out of these cells — and the ``load``
golden for it changes in the same diff.

A generator that raises (``{"error": [type, message]}``) or reports failure
in its result (``{"error": message}``) has that failure pinned: today's failure is part of today's behaviour,
and a manifest that starts or stops failing a generator is a golden diff.

Inputs are the shipped manifests themselves, ``examples/policies.yaml`` and
``examples/opensrm/`` (the contract registry) — never anything derived from
the code under test. The one constructed input is the topology cell's
``DependencyGraph``; see ``_graph_from_declared_dependencies``.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml
from nthlayer_common.manifest import ReliabilityManifest, load_manifest

from nthlayer_generate.dashboards.manifest_builder import build_dashboard_from_manifest
from nthlayer_generate.dependencies.models import (
    DependencyGraph,
    DependencyType,
    ResolvedDependency,
)
from nthlayer_generate.generators.alerts import generate_alerts_from_manifest
from nthlayer_generate.generators.backstage import generate_backstage_entity
from nthlayer_generate.generators.docs import generate_service_docs
from nthlayer_generate.generators.sloth import generate_sloth_from_manifest
from nthlayer_generate.identity import ServiceIdentity
from nthlayer_generate.loki.generator import generate_loki_alerts_from_manifest
from nthlayer_generate.metrics.recommender import recommend_metrics_from_manifest
from nthlayer_generate.policies.engine import PolicyEngine
from nthlayer_generate.recording_rules.manifest_builder import (
    build_recording_rules_from_manifest,
)
from nthlayer_generate.recording_rules.models import create_rule_groups
from nthlayer_generate.simulate.engine import run_simulation
from nthlayer_generate.simulate.graph import build_dependency_models, build_failure_models
from nthlayer_generate.slos.pipeline import AlertPipeline
from nthlayer_generate.specs.contracts import ContractRegistry
from nthlayer_generate.specs.validator import validate_service_file
from nthlayer_generate.topology.enrichment import build_topology

from ._corpus import EX, LEGACY, SRM_V1, V2, manifest_id
from ._golden import check


def _load(path: Path) -> ReliabilityManifest:
    # Same call as the load cell (test_golden_load.load_record).
    return load_manifest(path, suppress_deprecation_warning=True)


def _loads(path: Path) -> bool:
    try:
        _load(path)
    except Exception:  # noqa: BLE001 — the load cell pins why it failed
        return False
    return True


CASES: tuple[tuple[str, Path], ...] = tuple(
    (manifest_id(p), p) for p in SRM_V1 + LEGACY + V2 if _loads(p)
)
IDS = [i for i, _ in CASES]


def _error(e: Exception) -> dict[str, Any]:
    return {"error": [type(e).__name__, str(e)]}


def _read_yaml(path: Path | None) -> Any:
    """A written YAML file as structure; ``None`` when nothing was written."""
    if path is None or not path.is_file():
        return None
    return yaml.safe_load(path.read_text(encoding="utf-8"))


# --- cells: (manifest path, tmp dir) -> golden value -------------------------


def recording_rules(path: Path, tmp: Path) -> Any:
    groups = build_recording_rules_from_manifest(_load(path))
    return yaml.safe_load(create_rule_groups(groups))


def sloth(path: Path, tmp: Path) -> Any:
    result = generate_sloth_from_manifest(_load(path), tmp)
    if not result.success:
        return {"error": result.error}
    return _read_yaml(result.output_file)


def alerts(path: Path, tmp: Path) -> Any:
    # No file is written when no alerts are generated; that pins as null.
    out = tmp / "alerts.yaml"
    generate_alerts_from_manifest(_load(path), output_file=out, quiet=True)
    return _read_yaml(out)


def dashboard(path: Path, tmp: Path) -> Any:
    return build_dashboard_from_manifest(_load(path))


def loki(path: Path, tmp: Path) -> Any:
    _alerts, ruler_file = generate_loki_alerts_from_manifest(_load(path), tmp)
    ruler = _read_yaml(ruler_file)
    # Rule order follows set iteration over the dependency technologies
    # (specs/helpers.py:94, ``list(set(technologies))``), so it varies with
    # PYTHONHASHSEED. Pin the rules as a set: sorted by their full content.
    # Every rule's content is still pinned; only today's arbitrary order is not.
    for group in (ruler or {}).get("groups", []):
        group["rules"] = sorted(group["rules"], key=lambda r: json.dumps(r, sort_keys=True))
    return ruler


def metrics(path: Path, tmp: Path) -> Any:
    return recommend_metrics_from_manifest(_load(path)).to_dict()


def backstage(path: Path, tmp: Path) -> Any:
    result = generate_backstage_entity(path, tmp)
    if not result.success:
        return {"error": result.error}
    assert result.output_file is not None
    return json.loads(result.output_file.read_text(encoding="utf-8"))


def docs(path: Path, tmp: Path) -> Any:
    result = generate_service_docs(path, tmp, include_adr=True, include_api=True)
    if not result.success:
        return {"error": result.error}
    # Every file written, not just the ones the result lists.
    return {
        p.relative_to(tmp).as_posix(): p.read_text(encoding="utf-8")
        for p in sorted(tmp.rglob("*"))
        if p.is_file()
    }


def policies(path: Path, tmp: Path) -> Any:
    report = PolicyEngine.from_yaml(EX / "policies.yaml").evaluate(_load(path))
    return dataclasses.asdict(report)


def validate(path: Path, tmp: Path) -> Any:
    # The brief names ``validate_manifest``; no such function exists. The
    # manifest-path validator is ``validate_service_file`` (specs/validator.py:68).
    result = validate_service_file(
        path, contract_registry=ContractRegistry.from_directory(EX / "opensrm")
    )
    return {"valid": result.valid, "errors": result.errors, "warnings": result.warnings}


def pipeline(path: Path, tmp: Path) -> Any:
    return AlertPipeline().evaluate_service(_load(path), simulate_burn_pct=50.0).to_dict()


def simulate(path: Path, tmp: Path) -> Any:
    m = _load(path)
    failure_models = build_failure_models([m])
    dependency_models = build_dependency_models([m])
    result = run_simulation(
        failure_models, dependency_models, num_runs=200, horizon_days=90, seed=42
    )
    return {
        "failure_models": failure_models,
        "dependency_models": dependency_models,
        "result": result.to_dict(),
    }


def _graph_from_declared_dependencies(m: ReliabilityManifest) -> DependencyGraph:
    """The service plus one edge per dependency the manifest declares.

    This is constructed input, not a manifest fixture: it is derived only
    from the manifest's own ``dependencies``, so ``build_topology`` has an
    edge to enrich for each one. Every edge is ``SERVICE`` with confidence
    1.0 from a ``"manifest"`` provider — fixed values, so the golden varies
    only with what the manifest declares (names, critical, SLO contracts).
    """
    graph = DependencyGraph()
    source = ServiceIdentity(canonical_name=m.name)
    graph.add_service(source)
    for dep in m.dependencies:
        target = ServiceIdentity(canonical_name=dep.name)
        graph.add_service(target)
        graph.add_edge(
            ResolvedDependency(
                source=source,
                target=target,
                dep_type=DependencyType.SERVICE,
                confidence=1.0,
                providers=["manifest"],
            )
        )
    return graph


def topology(path: Path, tmp: Path) -> Any:
    m = _load(path)
    return build_topology(_graph_from_declared_dependencies(m), manifests=[m]).to_dict()


CELLS: dict[str, Callable[[Path, Path], Any]] = {
    "recording_rules": recording_rules,
    "sloth": sloth,
    "alerts": alerts,
    "dashboard": dashboard,
    "loki": loki,
    "metrics": metrics,
    "backstage": backstage,
    "docs": docs,
    "policies": policies,
    "validate": validate,
    "pipeline": pipeline,
    "simulate": simulate,
    "topology": topology,
}
GOLDEN_CELLS = {cell: tuple(IDS) for cell in CELLS}


def _run(cell: str, mid: str, path: Path, tmp: Path) -> None:
    try:
        value = CELLS[cell](path, tmp)
    except Exception as e:  # noqa: BLE001 — today's failure is the golden
        value = _error(e)
    check(cell, mid, value, tmp=tmp)


_cases = pytest.mark.parametrize(("mid", "path"), CASES, ids=IDS)


def test_corpus_has_loadable_manifests() -> None:
    # A loader regression that rejected everything would otherwise empty
    # every cell below and leave a green, zero-case suite.
    assert len(CASES) >= len(SRM_V1)


@_cases
def test_recording_rules(mid: str, path: Path, tmp_path: Path) -> None:
    _run("recording_rules", mid, path, tmp_path)


@_cases
def test_sloth(mid: str, path: Path, tmp_path: Path) -> None:
    _run("sloth", mid, path, tmp_path)


@_cases
def test_alerts(mid: str, path: Path, tmp_path: Path) -> None:
    _run("alerts", mid, path, tmp_path)


@_cases
def test_dashboard(mid: str, path: Path, tmp_path: Path) -> None:
    _run("dashboard", mid, path, tmp_path)


@_cases
def test_loki(mid: str, path: Path, tmp_path: Path) -> None:
    _run("loki", mid, path, tmp_path)


@_cases
def test_metrics(mid: str, path: Path, tmp_path: Path) -> None:
    _run("metrics", mid, path, tmp_path)


@_cases
def test_backstage(mid: str, path: Path, tmp_path: Path) -> None:
    _run("backstage", mid, path, tmp_path)


@_cases
def test_docs(mid: str, path: Path, tmp_path: Path) -> None:
    _run("docs", mid, path, tmp_path)


@_cases
def test_policies(mid: str, path: Path, tmp_path: Path) -> None:
    _run("policies", mid, path, tmp_path)


@_cases
def test_validate(mid: str, path: Path, tmp_path: Path) -> None:
    _run("validate", mid, path, tmp_path)


@_cases
def test_pipeline(mid: str, path: Path, tmp_path: Path) -> None:
    _run("pipeline", mid, path, tmp_path)


@_cases
def test_simulate(mid: str, path: Path, tmp_path: Path) -> None:
    _run("simulate", mid, path, tmp_path)


@_cases
def test_topology(mid: str, path: Path, tmp_path: Path) -> None:
    _run("topology", mid, path, tmp_path)
