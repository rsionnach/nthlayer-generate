"""The golden corpus: every shipped example, classified (spec §6.1).

The lists are explicit rather than globbed so that a new example cannot join
the corpus unclassified: ``test_golden_harness`` compares them with the
directory globs and fails until the new file is placed in exactly one list.

Inputs come from shipped files only — generate's ``examples/`` and the
OpenSRM spec's ``spec/v2/examples/`` in the sibling ``opensrm`` checkout —
never from the code under test.
"""

from __future__ import annotations

from pathlib import Path

import yaml

# parents: [0]=golden/ [1]=tests/ [2]=nthlayer-generate/ [3]=<ecosystem>/
REPO = Path(__file__).resolve().parents[2]
OPENSRM = Path(__file__).resolve().parents[3] / "opensrm"
EX = REPO / "examples"
V2_EXAMPLES = OPENSRM / "spec" / "v2" / "examples"

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


def manifest_id(path: Path) -> str:
    """Stable, checkout-independent id for a corpus file.

    ``examples/opensrm/ai-gate.reliability.yaml`` -> ``opensrm__ai-gate.reliability``;
    ``<opensrm>/spec/v2/examples/services/api.yaml`` -> ``v2__services__api``.
    Only ``.yaml`` is dropped: ``uat/payment-api.reliability.yaml`` and
    ``uat/payment-api.yaml`` are different manifests and must not collide.
    """
    path = path.resolve()
    if path.is_relative_to(EX):
        prefix, rel = "", path.relative_to(EX)
    elif path.is_relative_to(V2_EXAMPLES):
        prefix, rel = "v2__", path.relative_to(V2_EXAMPLES)
    else:
        raise ValueError(f"{path} is not in the golden corpus")
    if rel.suffix != ".yaml":
        raise ValueError(f"{path} is not a .yaml file")
    return prefix + "__".join(rel.with_suffix("").parts)


ALL: tuple[Path, ...] = SRM_V1 + LEGACY + NON_MANIFESTS + V2
