"""
Service definition validation.

Supports the OpenSRM formats (apiVersion: srm/v1 and opensrm.nthlayer.io/v2)
and the legacy NthLayer format, all loaded through nthlayer-common's manifest
model. Legacy files also get resource-level checks on the loaded raw data
(opensrm-wo62.4.19).
"""

from __future__ import annotations

import copy
import re
import warnings as stdlib_warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nthlayer_common.manifest import (
    LegacyFormatWarning,
    ManifestLoadError,
    load_manifest,
)
from nthlayer_common.manifest.parser import legacy as legacy_parser
from nthlayer_common.manifest.parser.v1 import is_srm_v1_format
from nthlayer_common.manifest.parser.v2 import is_opensrm_v2_format

from nthlayer_generate.specs.contracts import (
    ContractRegistry,
    validate_dependency_expectations,
    validate_transitive_feasibility,
)
from nthlayer_generate.specs.models import VALID_RESOURCE_KINDS
from nthlayer_generate.specs.names import is_valid_service_name

# The variables nthlayer-common's legacy substitution knows
# (legacy.substitute_resource_specs; ${env} only with an environment), so
# anything else in a loaded resource spec is still as written. Keep in sync.
_TEMPLATE_VARIABLE = re.compile(r"\$\{(\w+)\}")
_KNOWN_TEMPLATE_VARIABLES = {"service", "team", "tier", "type", "language", "framework", "env"}


@dataclass
class ValidationResult:
    """Result of service file validation."""

    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    service: str | None = None
    resource_count: int = 0

    def __str__(self) -> str:
        """Format validation result as string."""
        lines = []

        if self.valid:
            lines.append(f"✅ Valid service definition: {self.service}")
            lines.append(f"   Resources: {self.resource_count}")
        else:
            lines.append("❌ Invalid service definition")

        if self.errors:
            lines.append("\nErrors:")
            for error in self.errors:
                lines.append(f"  • {error}")

        if self.warnings:
            lines.append("\nWarnings:")
            for warning in self.warnings:
                lines.append(f"  ⚠️  {warning}")

        return "\n".join(lines)


class _MockContext:
    """The service fields validation reads, from an OpenSRM manifest."""

    def __init__(self, m: Any) -> None:
        self.name = m.name
        self.team = m.team
        self.tier = m.tier
        self.type = m.type
        self.template = m.template


def _unknown_template_variables(value: Any) -> list[str]:
    """The unknown ``${var}`` names anywhere in *value*, sorted and unique."""
    unknown: set[str] = set()
    if isinstance(value, str):
        unknown.update(
            m.group(1)
            for m in _TEMPLATE_VARIABLE.finditer(value)
            if m.group(1) not in _KNOWN_TEMPLATE_VARIABLES
        )
    elif isinstance(value, dict):
        for v in value.values():
            unknown.update(_unknown_template_variables(v))
    elif isinstance(value, list):
        for item in value:
            unknown.update(_unknown_template_variables(item))
    return sorted(unknown)


def _legacy_resources(manifest: Any) -> list[dict[str, Any]]:
    """A legacy manifest's resources, as loaded: after the env overlay,
    template expansion and ${var} substitution (opensrm-wo62.4.1)."""
    resources = manifest.raw_data.get("resources") or []
    return [r for r in resources if isinstance(r, dict)]


def _first_nameless_resource(raw_data: Any) -> int | None:
    """Index of the first resource with no name in ``raw_data``'s
    ``resources:`` list (the file after its env overlay), or None.

    The legacy parser rejected such a file ("Resource name is required"),
    indexing the overlaid list before template expansion; any falsy name
    counts, as in its ``Resource`` model.
    """
    if not isinstance(raw_data, dict):
        return None
    resources = raw_data.get("resources")
    if not isinstance(resources, list):
        return None
    for index, resource in enumerate(resources):
        if isinstance(resource, dict) and not resource.get("name"):
            return index
    return None


def _is_non_numeric(value: Any) -> bool:
    """Whether *value* is a set availability that is not a number."""
    return value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)))


def _non_numeric_availability_error(
    manifest: Any, registry: ContractRegistry | None
) -> str | None:
    """The error for a contract check that hit a non-numeric availability.

    Names the service, contract and value: the manifest's own contracts first,
    then the registry's. None when every availability is a number, so the
    TypeError the caller caught is a bug, not bad input.
    """
    sources = [(manifest.name, manifest.contracts)]
    if registry is not None:
        sources += [(name, registry.get_contracts(name)) for name in registry.services]
    for service, contracts in sources:
        for contract in contracts:
            value = contract.promise.availability
            if _is_non_numeric(value):
                where = "" if service == manifest.name else " (contract registry)"
                return (
                    f"Service '{service}' contract '{contract.name}'{where}: "
                    f"promise.availability must be a number (a ratio such as "
                    f"0.9995), got {value!r}"
                )
    return None


def validate_service_file(
    file_path: str | Path,
    environment: str | None = None,
    strict: bool = False,
    validate_filename: bool = True,
    contract_registry: ContractRegistry | None = None,
) -> ValidationResult:
    """
    Validate service YAML file.

    Checks:
    1. File loads through nthlayer-common (which rejects an invalid tier or
       type, so the first such error is the only one reported)
    2. Filename matches service name (optional)
    3. Service name is valid format
    4. (legacy files) Resource names are present and unique
    5. (legacy files) Resource kinds are valid
    6. (legacy files) Resource specs use only known ${var}s (warning)
    7. (srm/v1, v2) Contracts, and the registry's expectations if given
    8. A template, if set, is noted (warning)

    Args:
        file_path: Path to service YAML file
        environment: Optional environment name (dev, staging, prod)
        strict: If True, treat warnings as errors
        validate_filename: Check if filename matches service name

    Returns:
        ValidationResult with errors and warnings
    """
    errors: list[str] = []
    warnings: list[str] = []

    # Try to parse file - supports both OpenSRM and legacy formats
    file_path = Path(file_path)

    # First, detect the format to use appropriate parser
    import yaml

    try:
        with open(file_path) as f:
            raw_data = yaml.safe_load(f)
    except Exception as e:
        return ValidationResult(
            valid=False,
            errors=[f"Failed to parse YAML: {e}"],
        )

    # Every format loads through nthlayer-common. srm/v1 and v2 also get the
    # contract checks; legacy files keep their resource-level checks, run on
    # the loaded raw data (opensrm-wo62.4.19).
    use_opensrm = isinstance(raw_data, dict) and (
        is_srm_v1_format(raw_data) or is_opensrm_v2_format(raw_data)
    )

    try:
        if not use_opensrm:
            # Before the load: common loads a nameless resource (an SLO named
            # '') or crashes on it. The parser checked the list after the env
            # overlay, so the check reads common's own overlay merge.
            overlaid = (
                legacy_parser.apply_environment_overlay(
                    copy.deepcopy(raw_data), file_path, environment
                )
                if isinstance(raw_data, dict)
                else raw_data
            )
            nameless = _first_nameless_resource(overlaid)
            if nameless is not None:
                return ValidationResult(
                    valid=False,
                    errors=[
                        f"Invalid resource {nameless} in {file_path}: Resource name is required"
                    ],
                )

        with stdlib_warnings.catch_warnings():
            stdlib_warnings.simplefilter("ignore", LegacyFormatWarning)
            manifest = load_manifest(
                file_path, environment=environment, suppress_deprecation_warning=True
            )
    except (ManifestLoadError, OSError, ValueError) as e:
        # OSError: a missing or unreadable file, or an env overlay that is a
        # directory or unreadable.
        return ValidationResult(valid=False, errors=[str(e)])
    except (AttributeError, TypeError) as e:
        # common's legacy loader on a non-mapping resource spec
        # (opensrm-wo62.4.10).
        return ValidationResult(valid=False, errors=[f"Unexpected error parsing file: {e}"])

    service_context = _MockContext(manifest)
    resources: list[dict[str, Any]] = []

    if use_opensrm:
        resource_count = len(manifest.slos) + len(manifest.dependencies)

        # Contract validation (OpenSRM only). TypeError here only: common's
        # v2 parser keeps a quoted ``availability`` ("0.9995") as a string
        # and these checks then compare it with a float. A TypeError
        # anywhere else, or here with every availability a number, is a
        # bug and propagates.
        try:
            warnings.extend(manifest.validate_contracts())
            if contract_registry is not None:
                warnings.extend(validate_dependency_expectations(manifest, contract_registry))
                warnings.extend(validate_transitive_feasibility(manifest, contract_registry))
        except TypeError:
            message = _non_numeric_availability_error(manifest, contract_registry)
            if message is None:
                raise
            return ValidationResult(valid=False, errors=[message])
    else:
        resources = _legacy_resources(manifest)
        resource_count = len(resources)

    # Validate filename matches service name
    if validate_filename:
        # Accept both .yaml and .reliability.yaml extensions
        expected_filenames = [
            f"{service_context.name}.yaml",
            f"{service_context.name}.reliability.yaml",
        ]
        actual_filename = file_path.name
        if actual_filename not in expected_filenames:
            # Don't error for OpenSRM files with different naming conventions
            # Many OpenSRM files use descriptive names like api-basic.reliability.yaml
            if not actual_filename.endswith(".reliability.yaml"):
                errors.append(
                    f"Filename mismatch: expected '{expected_filenames[0]}' for service '{service_context.name}', "
                    f"got '{actual_filename}'"
                )

    # Validate service name format
    # Shared with cli/init.py's guard via specs/names (opensrm-t4rd). Two
    # copies disagreed, so init exited 0 writing names this rejected.
    if not is_valid_service_name(service_context.name):
        errors.append(
            f"Invalid service name: '{service_context.name}'. "
            "Must start with a lowercase letter, contain only lowercase letters, "
            "numbers and hyphens, and not end with a hyphen."
        )

    # Check for duplicate resource names (legacy resources only)
    resource_names = [str(r["name"]) for r in resources if r.get("name")]
    duplicates = sorted(n for n in set(resource_names) if resource_names.count(n) > 1)
    if duplicates:
        errors.append(f"Duplicate resource names: {', '.join(duplicates)}")

    # Validate each legacy resource
    for resource in resources:
        kind = resource.get("kind")
        name = resource.get("name")
        if not isinstance(kind, str) or kind not in VALID_RESOURCE_KINDS:
            errors.append(
                f"Resource {kind}/{name}: "
                f"Invalid kind '{kind}'. "
                f"Must be one of: {', '.join(sorted(VALID_RESOURCE_KINDS))}"
            )

        invalid_vars = _unknown_template_variables(resource.get("spec"))
        if invalid_vars:
            warnings.append(
                f"Resource '{kind}/{name}': "
                f"Uses unknown template variables: {', '.join(invalid_vars)}"
            )

    # Template warning (can't validate existence without template loader)
    if service_context.template:
        warnings.append(
            f"Service uses template '{service_context.template}'. "
            "Ensure template exists and is valid."
        )

    # Determine if valid
    valid = len(errors) == 0
    if strict and warnings:
        valid = False
        errors.extend(warnings)
        warnings = []

    return ValidationResult(
        valid=valid,
        errors=errors,
        warnings=warnings,
        service=service_context.name,
        resource_count=resource_count,
    )
