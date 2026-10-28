"""extract_dependency_technologies is ordered, not a set (opensrm-wo62.4.3).

Its list reaches generated output (generate-loki-alerts prints it and orders
alert groups by it), so a ``list(set(...))`` made that output depend on
PYTHONHASHSEED: the loki dry-run golden failed on roughly two runs in three.

Within one process a set's iteration order follows the hashes, not insertion,
so at most one of the 24 declaration orders below could match by chance.
"""

from __future__ import annotations

import dataclasses
import itertools
import warnings
from pathlib import Path

import pytest
from nthlayer_common.manifest import Dependency, ReliabilityManifest, load_manifest

from nthlayer_generate.specs.helpers import extract_dependency_technologies

API_CRITICAL = (
    Path(__file__).resolve().parents[1] / "examples" / "opensrm" / "api-critical.reliability.yaml"
)

# One dependency per extraction branch, each yielding a distinct technology.
DEPENDENCIES = {
    "postgresql": Dependency(name="orders-db", type="database", database_type="postgresql"),
    "mysql": Dependency(name="legacy-db", type="database", database_type="mysql"),
    "redis": Dependency(name="redis-sessions", type="cache"),
    "kafka": Dependency(name="kafka-events", type="queue"),
}


def _base() -> ReliabilityManifest:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return load_manifest(API_CRITICAL)


@pytest.mark.parametrize(
    "order", list(itertools.permutations(DEPENDENCIES)), ids=lambda o: "-".join(o)
)
def test_technologies_follow_declaration_order(order: tuple[str, ...]):
    manifest = dataclasses.replace(_base(), dependencies=[DEPENDENCIES[t] for t in order])

    assert extract_dependency_technologies(manifest) == list(order)


def test_duplicates_keep_first_occurrence():
    deps = [
        DEPENDENCIES["redis"],
        DEPENDENCIES["postgresql"],
        dataclasses.replace(DEPENDENCIES["redis"], name="redis-cache"),
        DEPENDENCIES["mysql"],
    ]
    manifest = dataclasses.replace(_base(), dependencies=deps)

    assert extract_dependency_technologies(manifest) == ["redis", "postgresql", "mysql"]
