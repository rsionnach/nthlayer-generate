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
