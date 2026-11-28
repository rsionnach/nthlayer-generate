"""A registry file that does not load is reported, not dropped (opensrm-ohs1).

``validate --registry-dir`` scans a directory for provider manifests. A file
there that fails to load used to be logged at debug level and left out, so
every contract check that would have read it silently did not run: measured
on the first fixture below, a consumer expecting 99.95% from a provider that
promises 90% validated with no warning at all.

Fixture provenance:

- Consumer: opensrm/spec/v2/examples/migration/api-full-v2.yaml, unmodified
  (payment-api; its first dependency is postgresql, expected_availability
  0.9995).
- Provider: the same file renamed ``postgresql`` (``metadata.name`` and
  ``spec.service.name``, which common's v2 parser reads), promising 0.9.
  The broken provider quotes that value: the v2 schema's
  ``promise.availability`` is a Ratio, a number from 0 to 1
  (opensrm/spec/v2/schema.json), and common refuses a string at load
  (opensrm-f0co).
- srm/v1: examples/opensrm/api-critical.reliability.yaml with ``metadata`` a
  list. srm/v1 is NthLayer's own dialect and has no schema file; the
  published schema it derives from makes ``metadata`` an object
  (opensrm/spec/v1/schema.json, definitions/Metadata), as every shipped
  srm/v1 example writes it.
- Published OpenSRM v1 (``apiVersion: opensrm/v1``): the format NthLayer
  does not load and sends to migrate-manifest; common's is_manifest_file
  counts it as a manifest so that a scan reaches that refusal.
"""

from __future__ import annotations

import warnings
from collections.abc import Callable
from pathlib import Path

import pytest
import yaml
from golden._corpus import V2_EXAMPLES
from nthlayer_common.manifest import ManifestLoadError, load_manifest
from rich.text import Text

from nthlayer_generate.cli.validate import _bullet, _registry_line, validate_command
from nthlayer_generate.specs.contracts import (
    ContractRegistry,
    UnloadedRegistryFile,
    unloaded_registry_file_warnings,
)
from nthlayer_generate.specs.validator import validate_service_file

V2_EXAMPLE = V2_EXAMPLES / "migration" / "api-full-v2.yaml"
SRM_V1_EXAMPLE = (
    Path(__file__).resolve().parents[1] / "examples" / "opensrm" / "api-critical.reliability.yaml"
)
PROVIDER = "postgresql"


def test_the_fixtures_exist() -> None:
    assert V2_EXAMPLE.is_file(), V2_EXAMPLE
    assert SRM_V1_EXAMPLE.is_file(), SRM_V1_EXAMPLE
    # The consumer must depend on the provider these tests break.
    assert load_manifest(V2_EXAMPLE).dependencies[0].name == PROVIDER


def _consumer(directory: Path) -> Path:
    path = directory / "payment-api.yaml"
    path.write_text(V2_EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
    return path


def _provider(directory: Path, availability: object) -> Path:
    doc = yaml.safe_load(V2_EXAMPLE.read_text(encoding="utf-8"))
    doc["metadata"]["name"] = PROVIDER
    doc["spec"]["service"]["name"] = PROVIDER
    doc["spec"]["dependencies"] = []
    doc["spec"]["contracts"][0]["promise"]["availability"] = availability
    path = directory / f"{PROVIDER}.yaml"
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return path


def _load_error(path: Path) -> str:
    """What common says about ``path``, asked directly."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with pytest.raises(ManifestLoadError) as refused:
            load_manifest(path, suppress_deprecation_warning=True)
    return str(refused.value)


# --- the registry records what it could not load -----------------------------


def test_a_provider_that_loads_is_registered_and_nothing_is_unloaded(tmp_path: Path) -> None:
    _consumer(tmp_path)
    _provider(tmp_path, 0.9)
    registry = ContractRegistry.from_directory(tmp_path)
    assert registry.services == ["payment-api", PROVIDER]
    assert registry.unloaded == []
    assert unloaded_registry_file_warnings(registry) == []


def test_a_provider_that_does_not_load_is_recorded_with_its_error(tmp_path: Path) -> None:
    _consumer(tmp_path)
    provider = _provider(tmp_path, "0.9")
    registry = ContractRegistry.from_directory(tmp_path)
    assert registry.services == ["payment-api"]
    assert registry.unloaded == [UnloadedRegistryFile(path=provider, error=_load_error(provider))]


def _srm_v1_metadata_is_a_list(directory: Path) -> Path:
    doc = yaml.safe_load(SRM_V1_EXAMPLE.read_text(encoding="utf-8"))
    doc["metadata"] = []
    path = directory / "broken.reliability.yaml"
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return path


def _published_opensrm_v1(directory: Path) -> Path:
    doc = yaml.safe_load(SRM_V1_EXAMPLE.read_text(encoding="utf-8"))
    doc["apiVersion"] = "opensrm/v1"
    path = directory / "published-v1.yaml"
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return path


def _yaml_that_does_not_parse(directory: Path) -> Path:
    path = directory / "torn.reliability.yaml"
    path.write_text("metadata: [1, 2\n", encoding="utf-8")
    return path


def _directory_named_like_a_manifest(directory: Path) -> Path:
    path = directory / "folder.reliability.yaml"
    path.mkdir()
    return path


BROKEN_FILES = [
    pytest.param(_srm_v1_metadata_is_a_list, id="srm-v1-metadata-is-a-list"),
    pytest.param(_published_opensrm_v1, id="published-opensrm-v1"),
    pytest.param(_yaml_that_does_not_parse, id="yaml-does-not-parse"),
    pytest.param(_directory_named_like_a_manifest, id="directory-named-like-a-manifest"),
]
# A collection-time list that came out empty would skip its tests, not fail them.
assert BROKEN_FILES


@pytest.mark.parametrize("write", BROKEN_FILES)
def test_every_kind_of_load_failure_is_recorded_and_none_raises(
    write: Callable[[Path], Path], tmp_path: Path
) -> None:
    _consumer(tmp_path)
    broken = write(tmp_path)
    registry = ContractRegistry.from_directory(tmp_path)
    # The file that loads is still registered: one bad file costs one file.
    assert registry.services == ["payment-api"]
    assert [u.path for u in registry.unloaded] == [broken]
    assert registry.unloaded[0].error


def test_a_yaml_file_that_is_not_a_manifest_is_not_reported(tmp_path: Path) -> None:
    # A registry directory may hold other YAML (here a Kubernetes object);
    # only a file common recognises as a manifest is expected to load.
    _consumer(tmp_path)
    (tmp_path / "deployment.yaml").write_text(
        "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: payment-api\n",
        encoding="utf-8",
    )
    assert ContractRegistry.from_directory(tmp_path).unloaded == []


def test_unloaded_files_are_listed_in_scan_order(tmp_path: Path) -> None:
    _consumer(tmp_path)
    second = _yaml_that_does_not_parse(tmp_path)
    first = _srm_v1_metadata_is_a_list(tmp_path)
    assert first < second
    registry = ContractRegistry.from_directory(tmp_path)
    assert [u.path for u in registry.unloaded] == [first, second]


def test_a_registry_built_from_manifests_has_nothing_unloaded() -> None:
    registry = ContractRegistry.from_manifests([load_manifest(V2_EXAMPLE)])
    assert registry.unloaded == []


# --- the validator says so ---------------------------------------------------


def test_the_checks_the_provider_feeds_warn_when_it_loads(tmp_path: Path) -> None:
    # The control: what the broken provider below takes away.
    consumer = _consumer(tmp_path)
    _provider(tmp_path, 0.9)
    result = validate_service_file(
        consumer, contract_registry=ContractRegistry.from_directory(tmp_path)
    )
    assert result.valid
    # Expected 99.95% from a provider that promises 90%.
    assert len(result.warnings) == 1
    assert result.warnings != unloaded_registry_file_warnings(
        ContractRegistry.from_directory(tmp_path)
    )


def test_an_unloaded_provider_is_a_warning_naming_the_file_and_the_error(tmp_path: Path) -> None:
    consumer = _consumer(tmp_path)
    provider = _provider(tmp_path, "0.9")
    registry = ContractRegistry.from_directory(tmp_path)

    result = validate_service_file(consumer, contract_registry=registry)

    # A warning, as every contract finding is (spec 11.3): the file is valid.
    assert result.valid
    assert result.warnings == unloaded_registry_file_warnings(registry)
    (warning,) = result.warnings
    assert str(provider) in warning
    assert _load_error(provider) in warning


def test_every_unloaded_file_gets_its_own_warning(tmp_path: Path) -> None:
    consumer = _consumer(tmp_path)
    broken = [_provider(tmp_path, "0.9"), _yaml_that_does_not_parse(tmp_path)]
    registry = ContractRegistry.from_directory(tmp_path)

    result = validate_service_file(consumer, contract_registry=registry)

    assert len(result.warnings) == 2
    for path, warning in zip(sorted(broken), result.warnings, strict=True):
        assert str(path) in warning
        assert _load_error(path) in warning


def test_validating_without_a_registry_is_unchanged(tmp_path: Path) -> None:
    consumer = _consumer(tmp_path)
    _provider(tmp_path, "0.9")
    result = validate_service_file(consumer)
    assert result.valid
    assert result.warnings == []


# --- the command's exit code -------------------------------------------------


def test_validate_passes_by_default_and_fails_under_strict(tmp_path: Path) -> None:
    consumer = _consumer(tmp_path)
    _provider(tmp_path, "0.9")
    assert validate_command(str(consumer), registry_dir=str(tmp_path)) == 0
    assert validate_command(str(consumer), registry_dir=str(tmp_path), strict=True) == 1


def test_strict_passes_when_every_registry_file_loads(tmp_path: Path) -> None:
    # Without this, the strict failure above could come from anywhere.
    consumer = _consumer(tmp_path)
    assert validate_command(str(consumer), registry_dir=str(tmp_path), strict=True) == 0


def test_a_registry_file_that_cannot_be_read_does_not_stop_validate(tmp_path: Path) -> None:
    # Measured before the fix: IsADirectoryError out of from_directory, a
    # traceback instead of a result.
    consumer = _consumer(tmp_path)
    _directory_named_like_a_manifest(tmp_path)
    assert validate_command(str(consumer), registry_dir=str(tmp_path)) == 0
    assert validate_command(str(consumer), registry_dir=str(tmp_path), strict=True) == 1


# --- what the console is given -----------------------------------------------
#
# A finding quotes paths and manifest values, and the console reads square
# brackets as style tags. Measured before the fix: a registry directory named
# ``team[prod]`` was printed as ``team``, and a provider whose availability
# was quoted as "[/bold]" ended validate with rich's MarkupError.

MARKUP_LIKE = [
    "Registry file services/team[prod]/postgresql.yaml did not load",
    "promise.availability must be a ratio from 0 to 1, got '[/bold]'",
    "a backslash before a bracket \\[bold] stays as written",
]
assert MARKUP_LIKE


@pytest.mark.parametrize("message", MARKUP_LIKE)
@pytest.mark.parametrize("style", ["warning", "error"])
def test_a_finding_is_printed_as_written(style: str, message: str) -> None:
    # Text.from_markup is what console.print does with a string.
    assert Text.from_markup(_bullet(style, message)).plain == f"  \u2022 {message}"


REGISTRY_DIRS = ["services", "services/team[prod]", "services/[/bold]"]
assert REGISTRY_DIRS


@pytest.mark.parametrize("registry_dir", REGISTRY_DIRS)
def test_the_registry_directory_is_printed_as_written(registry_dir: str) -> None:
    assert Text.from_markup(_registry_line(registry_dir)).plain == (
        f"Contract registry: {registry_dir}"
    )


def test_brackets_in_the_registry_path_and_the_load_error_do_not_stop_validate(
    tmp_path: Path,
) -> None:
    registry_dir = tmp_path / "team[prod]"
    registry_dir.mkdir()
    consumer = _consumer(registry_dir)
    _provider(registry_dir, "[/bold]")
    assert validate_command(str(consumer), registry_dir=str(registry_dir)) == 0
    assert validate_command(str(consumer), registry_dir=str(registry_dir), strict=True) == 1


def test_brackets_in_the_validated_files_own_error_do_not_stop_validate(tmp_path: Path) -> None:
    # The same print path, for errors: the validated file is the broken one.
    broken = _provider(tmp_path, "[/bold]")
    assert validate_command(str(broken)) == 1
