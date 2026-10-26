"""ContractRegistry over nthlayer-common's ``contracts`` list (opensrm-wo62.1).

Spec §5.2 (contracts, D4): the registry stores ``list[ReliabilityContract]``
per service; a provider's availability is the minimum ``promise.availability``
over its contracts (the weakest promise is the most a consumer may rely on);
``validate_transitive_feasibility`` checks each contract that declares
availability, with the message unchanged for one contract and naming the
contract when there are several.

Inputs are shipped files. Where a test needs a second contract, it copies the
manifest's own contract under a new name and availability, as Task 8's
multi-contract blind-spot test does: no shipped example declares two.
"""

from __future__ import annotations

import dataclasses
import math
import warnings
from pathlib import Path
from typing import Any

import pytest
import yaml
from nthlayer_common.manifest import ReliabilityManifest, load_manifest

from nthlayer_generate.specs.contracts import (
    ContractRegistry,
    validate_dependency_expectations,
    validate_transitive_feasibility,
)

REPO = Path(__file__).resolve().parents[1]
OPENSRM_EXAMPLES = REPO / "examples" / "opensrm"
# Both last changed in f252974.
API_CRITICAL = OPENSRM_EXAMPLES / "api-critical.reliability.yaml"  # payment-api
AI_GATE = OPENSRM_EXAMPLES / "ai-gate.reliability.yaml"  # fraud-detector
API_BASIC = OPENSRM_EXAMPLES / "api-basic.reliability.yaml"  # user-api, no contract


def _load(path: Path) -> ReliabilityManifest:
    # TargetConventionWarning on the srm/v1 judgment ratios (spec §5.4) is
    # not what these tests are about.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return load_manifest(path)


def _declared(path: Path) -> dict[str, Any]:
    doc: dict[str, Any] = yaml.safe_load(path.read_text())
    return doc


def _with_second_contract(
    manifest: ReliabilityManifest, name: str, availability: float
) -> ReliabilityManifest:
    """*manifest* plus a copy of its own first contract, renamed, with a
    different ``promise.availability``."""
    first = manifest.contracts[0]
    second = dataclasses.replace(
        first,
        name=name,
        promise=dataclasses.replace(first.promise, availability=availability),
    )
    return dataclasses.replace(manifest, contracts=[first, second])


def test_fixtures_are_present() -> None:
    for path in (API_CRITICAL, AI_GATE, API_BASIC):
        assert path.is_file(), path


def test_registry_from_the_examples_promises_what_each_contract_declares() -> None:
    registry = ContractRegistry.from_directory(OPENSRM_EXAMPLES)

    # Expected values read from each file's `spec.contract.availability`.
    for path in (API_CRITICAL, AI_GATE):
        doc = _declared(path)
        name = doc["metadata"]["name"]
        expected = doc["spec"]["contract"]["availability"]
        assert expected == 0.999  # anti-vacuity: the brief's stated value
        assert registry.has_contract(name)
        assert registry.promised_availability(name) == expected
        (contract,) = registry.get_contracts(name)
        assert contract.promise.availability == expected

    assert registry.promised_availability("payment-api") == 0.999
    assert registry.promised_availability("fraud-detector") == 0.999


def test_a_service_without_contracts_is_not_registered() -> None:
    assert "contract" not in _declared(API_BASIC)["spec"]
    registry = ContractRegistry.from_manifests([_load(API_BASIC)])
    assert registry.services == []
    assert not registry.has_contract("user-api")
    assert registry.get_contracts("user-api") == []
    assert registry.promised_availability("user-api") is None


def test_promised_availability_is_the_weakest_promise() -> None:
    provider = _with_second_contract(_load(API_CRITICAL), "payment-api-bulk", 0.99)
    registry = ContractRegistry.from_manifests([provider])
    assert [c.name for c in registry.get_contracts("payment-api")] == [
        provider.contracts[0].name,
        "payment-api-bulk",
    ]
    assert registry.promised_availability("payment-api") == 0.99


def test_promised_availability_ignores_a_contract_without_availability() -> None:
    manifest = _load(API_CRITICAL)
    first = manifest.contracts[0]
    silent = dataclasses.replace(
        first,
        name="payment-api-latency-only",
        promise=dataclasses.replace(first.promise, availability=None),
    )
    provider = dataclasses.replace(manifest, contracts=[first, silent])
    registry = ContractRegistry.from_manifests([provider])
    assert registry.promised_availability("payment-api") == 0.999


def test_registry_hands_out_copies() -> None:
    registry = ContractRegistry.from_manifests([_load(API_CRITICAL)])
    registry.get_contracts("payment-api").clear()
    assert len(registry.get_contracts("payment-api")) == 1


def test_dependency_expectation_is_checked_against_the_weakest_promise(tmp_path: Path) -> None:
    # Promises 0.999 and 0.99. Expecting 99.5% exceeds 99.0% but not 99.9%.
    provider = _with_second_contract(_load(API_CRITICAL), "payment-api-bulk", 0.99)
    registry = ContractRegistry.from_manifests([provider])

    consumer_doc = _declared(API_BASIC)
    consumer_doc["spec"]["dependencies"] = [
        {"name": "payment-api", "type": "api", "critical": True, "slo": {"availability": 99.5}}
    ]
    path = tmp_path / "consumer.reliability.yaml"
    path.write_text(yaml.safe_dump(consumer_doc, sort_keys=False))

    warnings_ = validate_dependency_expectations(_load(path), registry)
    assert len(warnings_) == 1
    assert "'payment-api'" in warnings_[0]
    assert "exceeds provider contract" in warnings_[0]


# api-critical's critical dependencies: postgres-primary expects 99.99%
# (ratio 0.9999); stripe-api declares nothing (unknown). The serial chain's
# theoretical max is therefore 0.9999, computed here from the file.
def _chain_max(path: Path) -> float:
    deps = _declared(path)["spec"]["dependencies"]
    known = [
        d["slo"]["availability"] / 100.0
        for d in deps
        if d.get("critical") and d.get("slo", {}).get("availability") is not None
    ]
    return math.prod(known)


def _infeasible(warnings_: list[str]) -> list[str]:
    return [w for w in warnings_ if "may be infeasible" in w]


def test_single_contract_infeasibility_message_is_unchanged() -> None:
    manifest = _load(API_CRITICAL)
    (only,) = manifest.contracts
    chain = _chain_max(API_CRITICAL)
    assert chain == pytest.approx(0.9999)  # anti-vacuity: one known critical dependency
    stricter = dataclasses.replace(
        manifest,
        contracts=[
            dataclasses.replace(
                only, promise=dataclasses.replace(only.promise, availability=0.99999)
            )
        ],
    )

    warnings_ = validate_transitive_feasibility(stricter, ContractRegistry())

    # The pre-switch message text, verbatim (specs/contracts.py before wo62.1).
    assert _infeasible(warnings_) == [
        f"Contract availability (0.99999) may be infeasible: critical dependency "
        f"chain theoretical max is {chain:.6f}"
    ]


def test_each_contract_is_checked_and_named_when_there_are_several() -> None:
    # The file's own 0.999 is feasible against 0.9999; a second contract at
    # 0.99999 is not, and only it is reported, by name.
    manifest = _with_second_contract(_load(API_CRITICAL), "payment-api-premium", 0.99999)
    chain = _chain_max(API_CRITICAL)
    assert manifest.contracts[0].promise.availability == 0.999 < chain

    warnings_ = validate_transitive_feasibility(manifest, ContractRegistry())

    assert _infeasible(warnings_) == [
        f"Contract availability (0.99999) may be infeasible: critical dependency "
        f"chain theoretical max is {chain:.6f} (contract 'payment-api-premium')"
    ]
    # The unknown dependency is still reported once, not once per contract.
    assert sum("'stripe-api'" in w for w in warnings_) == 1


def test_transitive_check_is_skipped_without_an_availability_promise() -> None:
    manifest = _load(API_CRITICAL)
    (only,) = manifest.contracts
    silent = dataclasses.replace(
        manifest,
        contracts=[
            dataclasses.replace(only, promise=dataclasses.replace(only.promise, availability=None))
        ],
    )
    assert validate_transitive_feasibility(silent, ContractRegistry()) == []
