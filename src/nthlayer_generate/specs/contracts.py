"""
Contract registry and dependency validation.

Implements OpenSRM spec sections 11.2 and 11.3:
- File-based contract registry (11.3 Optional)
- Dependency expectation validation (11.3 Recommended)
- Transitive feasibility check (11.3 Optional)

All validation produces warnings (not errors) per spec.
"""

from __future__ import annotations

import math
from pathlib import Path

import structlog
from nthlayer_common.manifest import (
    Dependency,
    ReliabilityContract,
    ReliabilityManifest,
    SourceFormat,
)

logger = structlog.get_logger()

# Decimal places for comparing and printing availabilities: enough to absorb
# float noise (99.9 / 100 is 0.9990000000000001) without hiding a real gap.
# Ratios are rounded to _RATIO_PLACES; their percentage form, which is the
# ratio times 100, to two fewer.
_RATIO_PLACES = 12
_PCT_PLACES = _RATIO_PLACES - 2


class ContractRegistry:
    """
    Registry of service contracts for cross-service validation.

    Stores each service's contracts (``manifest.contracts``: one for srm/v1,
    any number for v2) indexed by service name, enabling dependency
    expectation validation and transitive feasibility checks.
    """

    def __init__(self) -> None:
        self._contracts: dict[str, list[ReliabilityContract]] = {}

    def register(self, manifest: ReliabilityManifest) -> None:
        """Register a manifest's contracts by service name.

        A manifest with no contracts is skipped, so ``has_contract`` stays
        False for it.
        """
        if manifest.contracts:
            self._contracts[manifest.name] = list(manifest.contracts)

    def get_contracts(self, name: str) -> list[ReliabilityContract]:
        """Contracts registered for a service; empty if none."""
        return list(self._contracts.get(name, []))

    def promised_availability(self, name: str) -> float | None:
        """The weakest availability a service promises, or None.

        The minimum ``promise.availability`` over the service's contracts
        that declare one: the weakest promise is the most a consumer may rely
        on (spec §5.2). None when no contract declares availability.
        """
        promised = [
            c.promise.availability
            for c in self._contracts.get(name, [])
            if c.promise.availability is not None
        ]
        return min(promised) if promised else None

    def has_contract(self, name: str) -> bool:
        """Check if a service has a registered contract."""
        return name in self._contracts

    @property
    def services(self) -> list[str]:
        """Sorted list of registered service names."""
        return sorted(self._contracts.keys())

    @classmethod
    def from_manifests(cls, manifests: list[ReliabilityManifest]) -> ContractRegistry:
        """Build registry from a list of pre-loaded manifests."""
        registry = cls()
        for manifest in manifests:
            registry.register(manifest)
        return registry

    @classmethod
    def from_directory(cls, directory: str | Path) -> ContractRegistry:
        """
        Build registry by scanning a directory for manifest files.

        Loads each manifest file found via is_manifest_file() and
        registers any contracts.
        """
        from nthlayer_common.manifest import (
            ManifestLoadError,
            is_manifest_file,
            load_manifest,
        )

        registry = cls()
        path = Path(directory)

        if not path.is_dir():
            logger.warning("Contract registry directory not found: %s", directory)
            return registry

        for pattern in ("*.yaml", "*.yml"):
            for file_path in sorted(path.rglob(pattern)):
                if not is_manifest_file(file_path):
                    continue
                try:
                    manifest = load_manifest(file_path, suppress_deprecation_warning=True)
                    registry.register(manifest)
                except (ManifestLoadError, FileNotFoundError, ValueError) as e:
                    logger.debug("Skipping %s: %s", file_path, e)

        return registry


def _expected_ratio(manifest: ReliabilityManifest, dep: Dependency) -> float | None:
    """A dependency's expected availability as a ratio, or None if undeclared.

    opensrm/v2 stores ``expected_availability`` as a Ratio (0.9995, schema.json
    ``expected_availability``) and common's parser keeps it unconverted; srm/v1
    and legacy declare a percentage (99.95).
    """
    if not (dep.slo and dep.slo.availability is not None):
        return None
    value = float(dep.slo.availability)
    if manifest.source_format == SourceFormat.OPENSRM_V2:
        return value
    return value / 100.0


def _pct(ratio: float) -> float:
    """Ratio as the percentage the warnings print, rounded to hide float noise."""
    return round(ratio * 100, _PCT_PLACES)


def validate_dependency_expectations(
    manifest: ReliabilityManifest,
    registry: ContractRegistry,
) -> list[str]:
    """
    Validate that dependency SLO expectations don't exceed provider contracts.

    For each dependency with an availability expectation, checks that:
    - The expected availability doesn't exceed the provider's contract
    - Critical dependencies have a contract in the registry

    Returns list of warning strings.
    """
    warnings: list[str] = []

    for dep in manifest.dependencies:
        promised = registry.promised_availability(dep.name)

        expected = _expected_ratio(manifest, dep)
        if (
            expected is not None
            and promised is not None
            # rounded: 99.9 / 100 is 0.9990000000000001, which must not exceed 0.999
            and round(expected, _RATIO_PLACES) > round(promised, _RATIO_PLACES)
        ):
            # Both are ratios here; the message prints percentages.
            warnings.append(
                f"Dependency '{dep.name}': expected availability "
                f"({_pct(expected)}%) exceeds provider contract "
                f"({_pct(promised)}%)"
            )

        if dep.critical and not registry.has_contract(dep.name):
            warnings.append(f"Critical dependency '{dep.name}' has no contract in registry")

    return warnings


def validate_transitive_feasibility(
    manifest: ReliabilityManifest,
    registry: ContractRegistry,
) -> list[str]:
    """
    Check if the service's contracts are feasible given dependency availabilities.

    Uses a serial chain model: theoretical_max = product(dep_availabilities).
    Checks each of the manifest's contracts that declares availability; only
    runs if at least one does. With several contracts, each infeasibility
    message names its contract (spec §5.2); with one, the message is as before.

    Returns list of warning strings.
    """
    warnings: list[str] = []

    promising = [
        (contract, availability)
        for contract in manifest.contracts
        if (availability := contract.promise.availability) is not None
    ]
    if not promising:
        return warnings

    # Collect critical dep availabilities
    availabilities: list[float] = []
    unknown_deps: list[str] = []

    for dep in manifest.dependencies:
        if not dep.critical:
            continue

        # Try registry first, then fall back to expected SLO
        promised = registry.promised_availability(dep.name)
        if promised is not None:
            availabilities.append(promised)
        elif (expected := _expected_ratio(manifest, dep)) is not None:
            availabilities.append(expected)
        else:
            unknown_deps.append(dep.name)

    for dep_name in unknown_deps:
        warnings.append(
            f"Critical dependency '{dep_name}' has unknown availability "
            f"(cannot verify transitive feasibility)"
        )

    if not availabilities:
        return warnings

    # Serial chain: P(all up) = P1 * P2 * ... * Pn
    theoretical_max = math.prod(availabilities)

    for contract, availability in promising:
        if theoretical_max < availability:
            message = (
                f"Contract availability ({availability}) may be "
                f"infeasible: critical dependency chain theoretical max is "
                f"{theoretical_max:.6f}"
            )
            if len(manifest.contracts) > 1:
                message += f" (contract '{contract.name}')"
            warnings.append(message)

    return warnings
