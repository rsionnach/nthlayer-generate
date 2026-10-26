"""v2 manifests at ``migrate`` and ``validate`` after the switch (opensrm-wo62.1).

Two spec rulings:

- ``migrate`` (spec §5.2 ruling on ``source_format``; plan Review Focus 5):
  only legacy needs migrating. A v2 manifest is "already OpenSRM": exit 0,
  nothing written. Comparing with ``SRM_V1`` alone would "migrate" v2 down.
- ``validate`` (spec §5.2, "validator"): srm/v1 **and** v2 take the manifest
  path, so ``resource_count`` is ``len(manifest.slos) + len(dependencies)``
  and ``parse_service_file`` is never called for them.

Fixtures are opensrm spec examples from the sibling checkout.
"""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any

import pytest
import yaml

from nthlayer_generate.cli.migrate import migrate_command
from nthlayer_generate.specs import validator as validator_module
from nthlayer_generate.specs.validator import validate_service_file

# parents: [0]=tests/ [1]=nthlayer-generate/ [2]=<ecosystem>/
V2_EXAMPLES = Path(__file__).resolve().parents[2] / "opensrm" / "spec" / "v2" / "examples"
MINIMAL = V2_EXAMPLES / "minimal.yaml"  # 0530688
API_FULL_V2 = V2_EXAMPLES / "migration" / "api-full-v2.yaml"  # 0530688


def _read(path: Path) -> dict[str, Any]:
    doc: dict[str, Any] = yaml.safe_load(path.read_text())
    return doc


def _minimal_with_tier(directory: Path) -> Path:
    """opensrm/spec/v2/examples/minimal.yaml @0530688 with
    ``metadata.labels.tier: standard`` injected.

    The shipped file is the smallest manifest the v2 schema accepts, but
    nthlayer-common's v2 parser also requires ``metadata.labels.tier``. That
    divergence is opensrm-ta0m; the injection follows the ruling made for the
    same file shape in plan Task 1 (option (a)). Everything else is the file's.
    """
    data = _read(MINIMAL)
    data["metadata"].setdefault("labels", {})["tier"] = "standard"
    path = directory / "minimal.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return path


def test_fixtures_are_present() -> None:
    for path in (MINIMAL, API_FULL_V2):
        assert path.is_file(), f"missing opensrm sibling checkout file: {path}"


@pytest.mark.parametrize("which", ["minimal", "api-full-v2"])
def test_migrate_leaves_a_v2_manifest_alone(which: str, tmp_path: Path) -> None:
    source = tmp_path / "src"
    source.mkdir()
    if which == "minimal":
        path = _minimal_with_tier(source)
    else:
        path = source / API_FULL_V2.name
        path.write_text(API_FULL_V2.read_text())
    out = tmp_path / "out"
    out.mkdir()
    before = sorted(source.iterdir())

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        code = migrate_command(str(path), output_dir=str(out))

    assert code == 0
    assert list(out.iterdir()) == []
    assert sorted(source.iterdir()) == before


@pytest.mark.parametrize("which", ["minimal", "api-full-v2"])
def test_validate_takes_the_manifest_path_for_v2(
    which: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _minimal_with_tier(tmp_path) if which == "minimal" else API_FULL_V2
    doc = _read(path)

    def _legacy_parser_must_not_run(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("v2 routed to parse_service_file")

    monkeypatch.setattr(validator_module, "parse_service_file", _legacy_parser_must_not_run)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        result = validate_service_file(path, validate_filename=False)

    assert result.valid, result.errors
    assert result.service == doc["metadata"]["name"]
    # Manifest path: SLOs plus dependencies, counted from the file.
    spec = doc["spec"]
    assert result.resource_count == len(spec.get("slo", [])) + len(spec.get("dependencies", []))
    if which == "api-full-v2":
        assert result.resource_count == 8  # anti-vacuity: 4 SLOs + 4 dependencies
