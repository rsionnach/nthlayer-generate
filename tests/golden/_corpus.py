"""The golden corpus: every shipped example, classified (spec §6.1).

The lists are explicit rather than globbed so that a new example cannot join
the corpus unclassified: ``test_golden_harness`` compares them with the
directory globs and fails until the new file is placed in exactly one list.

Inputs come from shipped files — generate's ``examples/`` and the OpenSRM
spec's ``spec/v2/examples/`` in the sibling ``opensrm`` checkout — never from
the code under test. The one exception is ``LEGACY_FIXTURES``: test-only
inputs, each adapted from a shipped example, that exist only to reach a
legacy branch no shipped file reaches. Each names that branch and its source
example in its header comment.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml
from nthlayer_common.manifest import ReliabilityManifest, load_manifest

from nthlayer_generate.dependencies.models import (
    DependencyGraph,
    DependencyType,
    ResolvedDependency,
)
from nthlayer_generate.identity import ServiceIdentity
from nthlayer_generate.specs.custom_templates import CustomTemplateLoader

# parents: [0]=golden/ [1]=tests/ [2]=nthlayer-generate/ [3]=<ecosystem>/
REPO = Path(__file__).resolve().parents[2]
OPENSRM = Path(__file__).resolve().parents[3] / "opensrm"
EX = REPO / "examples"
V2_EXAMPLES = OPENSRM / "spec" / "v2" / "examples"
FIXTURES = Path(__file__).resolve().parent / "fixtures"

# apiVersion: srm/v1 manifests (7).
SRM_V1: tuple[Path, ...] = tuple(
    EX / p
    for p in (
        "opensrm/ai-gate.reliability.yaml",
        "opensrm/api-basic.reliability.yaml",
        "opensrm/api-critical.reliability.yaml",
        "opensrm/batch.reliability.yaml",
        "opensrm/stream.reliability.yaml",
        "opensrm/worker.reliability.yaml",
        "uat/payment-api.reliability.yaml",
    )
)

# Legacy NthLayer ``service:`` manifests (17 + 3). Globbed, but the harness
# pins the count, so a new file under examples/services/ still fails the
# suite until someone confirms it is a legacy manifest.
LEGACY: tuple[Path, ...] = tuple(sorted((EX / "services").glob("*.yaml"))) + tuple(
    EX / "uat" / n
    for n in (
        "payment-api.yaml",
        "payment-api-with-slas.yaml",
        "payment-api-partial-slas.yaml",
    )
)

# Fragments (environment overrides, standalone SLO files) that are not
# manifests; both loaders reject them. Load record only (12).
NON_MANIFESTS: tuple[Path, ...] = tuple(
    sorted((EX / "environments").glob("*.yaml"))
    + sorted((EX / "services" / "environments").glob("*.yaml"))
    + sorted((EX / "slos").glob("*.yaml"))
)

# YAML under examples/ that is not a manifest of any kind, by design.
# Paths are relative to EX; a directory entry covers everything below it.
NOT_MANIFESTS_BY_DESIGN: tuple[tuple[str, str], ...] = (
    ("policies.yaml", "policy rules for `nthlayer validate --policies`, the policies cell's input"),
    ("cicd", "CI/CD pipeline definitions (Argo CD, Tekton, GitLab, GitHub Action)"),
    ("workflows", "GitHub Actions workflow examples"),
)


def _is_service_manifest(path: Path) -> bool:
    with path.open() as f:
        data = yaml.safe_load(f)
    return isinstance(data, dict) and data.get("kind") == "ServiceManifest"


# OpenSRM v2 spec examples whose kind is ServiceManifest (templates and
# JudgmentSLO documents are excluded). Empty when the sibling is missing;
# test_golden_harness asserts it is present rather than skipping.
V2: tuple[Path, ...] = tuple(
    p for p in sorted(V2_EXAMPLES.rglob("*.yaml")) if _is_service_manifest(p)
)


# Test-only legacy ``service:`` manifests under fixtures/legacy/ (R5
# provenance, wo62.4.2). Not part of the shipped corpus: each reaches a
# legacy branch (named in its header comment) that no example reaches, so a
# mutant there would otherwise leave every golden green. Explicit, and
# test_golden_legacy_generators asserts the directory holds nothing else.
LEGACY_FIXTURES: tuple[Path, ...] = tuple(
    FIXTURES / "legacy" / n
    for n in (
        "checkout-db-deps.yaml",
        "checkout-env-vars.yaml",
        "notification-observability-only.yaml",
    )
)


def manifest_id(path: Path) -> str:
    """Stable, checkout-independent id for a corpus file.

    ``examples/opensrm/ai-gate.reliability.yaml`` -> ``opensrm__ai-gate.reliability``;
    ``<opensrm>/spec/v2/examples/services/api.yaml`` -> ``v2__services__api``.
    Only ``.yaml`` is dropped: ``uat/payment-api.reliability.yaml`` and
    ``uat/payment-api.yaml`` are different manifests and must not collide.
    A test fixture is ``fixture__legacy__<stem>``.
    """
    path = path.resolve()
    if path.is_relative_to(EX):
        prefix, rel = "", path.relative_to(EX)
    elif path.is_relative_to(V2_EXAMPLES):
        prefix, rel = "v2__", path.relative_to(V2_EXAMPLES)
    elif path.is_relative_to(FIXTURES):
        prefix, rel = "fixture__", path.relative_to(FIXTURES)
    else:
        raise ValueError(f"{path} is not in the golden corpus")
    if rel.suffix != ".yaml":
        raise ValueError(f"{path} is not a .yaml file")
    return prefix + "__".join(rel.with_suffix("").parts)


ALL: tuple[Path, ...] = SRM_V1 + LEGACY + NON_MANIFESTS + V2


# --- helpers shared by the generator and CLI cells ---------------------------


def _load(path: Path) -> ReliabilityManifest:
    # Same call as the load cell (test_golden_load.load_record).
    return load_manifest(path, suppress_deprecation_warning=True)


def _error(e: Exception) -> dict[str, Any]:
    return {"error": [type(e).__name__, str(e)]}


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


# --- legacy-format cases (moved from test_golden_legacy_generators, wo62.4.6) --

# Every manifest, loadable or not, for the legacy CLI cells. The test-only
# fixtures come last, so every corpus id is unchanged.
CASES: tuple[tuple[str, Path], ...] = tuple(
    (manifest_id(p), p) for p in SRM_V1 + LEGACY + V2 + LEGACY_FIXTURES
)
IDS = [i for i, _ in CASES]

ENVIRONMENTS = ("dev", "staging", "prod")
# Under the temp dir; kept apart so a cell listing what it wrote can skip it.
STAGING = "_staged"


class EnvCase:
    """A service file run with ``environment`` set.

    ``staged`` cases copy the service file into ``<tmp>/_staged/services/`` next to a
    copy of ``examples/environments/``: that directory has no service file
    beside it, so the overlay lookup (``{service_dir}/environments/...``,
    nthlayer-common's ``legacy.find_environment_file``) can only reach it from
    a staged layout. The layout is the one its README prescribes; the files
    are copied unchanged.
    """

    def __init__(self, base: Path, environment: str, *, staged: bool) -> None:
        self.base = base
        self.environment = environment
        self.staged = staged
        prefix = f"staged__{base.stem}" if staged else manifest_id(base)
        self.id = f"{prefix}__env-{environment}"

    def target(self, tmp: Path) -> Path:
        """The service file to pass to the command, staging it if needed."""
        if not self.staged:
            return self.base
        services = tmp / STAGING / "services"
        env_dir = services / "environments"
        env_dir.mkdir(parents=True, exist_ok=True)
        for overlay in sorted((EX / "environments").glob("*.yaml")):
            shutil.copy(overlay, env_dir / overlay.name)
        target = services / self.base.name
        shutil.copy(self.base, target)
        return target


ENV_CASES: tuple[EnvCase, ...] = (
    # examples/services/environments/{dev,staging,prod}.yaml, found in place.
    *(
        EnvCase(EX / "services" / "payment-api-with-envs.yaml", e, staged=False)
        for e in ENVIRONMENTS
    ),
    # examples/environments/: payment-api-{dev,prod}.yaml and search-api-prod.yaml
    # are service-specific; the rest fall through to the shared {env}.yaml.
    *(EnvCase(EX / "services" / "payment-api.yaml", e, staged=True) for e in ENVIRONMENTS),
    *(EnvCase(EX / "services" / "search-api.yaml", e, staged=True) for e in ENVIRONMENTS),
    # Test-only: fixtures/legacy/environments/checkout-env-vars-prod.yaml, found
    # in place. Reaches the ${env}/${team} substitution, which no shipped file
    # reaches.
    EnvCase(FIXTURES / "legacy" / "checkout-env-vars.yaml", "prod", staged=False),
)
ENV_IDS = [c.id for c in ENV_CASES]


def rules_as_sets(doc: Any) -> Any:
    """Sort each group's rules, and the groups, by full content.

    The legacy dependency extractors returned ``list(set(...))``, so rule order
    followed PYTHONHASHSEED and the goldens were recorded in this sorted form.
    The manifest path is declaration-ordered
    (specs/helpers.extract_dependency_technologies), so this now normalises an
    order that is already deterministic; dropping it is a golden-only diff.
    """
    if not isinstance(doc, dict) or not isinstance(doc.get("groups"), list):
        return doc
    for group in doc["groups"]:
        if isinstance(group, dict) and isinstance(group.get("rules"), list):
            group["rules"] = sorted(group["rules"], key=lambda r: json.dumps(r, sort_keys=True))
    doc["groups"] = sorted(doc["groups"], key=lambda g: json.dumps(g, sort_keys=True))
    return doc


def no_user_templates(mp: pytest.MonkeyPatch) -> None:
    """Hide any user ``.nthlayer/templates`` from both template lookups.

    nthlayer-common's ``_find_template_dir`` walks up to ten levels from the
    *manifest*, and corpus files live in the checkout, so a templates dir in
    the user's home or above the checkout would change, and be pinned into,
    the goldens. ``CustomTemplateLoader.find_templates_directory`` walks up
    from the *cwd* without limit. No golden uses custom templates; builtin
    templates do not go through either lookup.

    The common lookup is patched on the loader module, where both of its
    callers look it up by name.
    """
    import nthlayer_common.manifest.parser.loader as common_loader

    mp.setattr(CustomTemplateLoader, "find_templates_directory", staticmethod(lambda: None))
    mp.setattr(common_loader, "_find_template_dir", lambda manifest_path: None)
