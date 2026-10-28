"""Shared helpers for working with ReliabilityManifest.

Provides utility functions used across multiple generators.
"""

from __future__ import annotations

import structlog
from nthlayer_common.manifest import Dependency, ReliabilityManifest

logger = structlog.get_logger()

# Shared technology keywords for name-based inference
TECH_KEYWORDS: dict[str, str] = {
    "redis": "redis",
    "postgres": "postgres",
    "postgresql": "postgres",
    "mysql": "mysql",
    "mongo": "mongodb",
    "mongodb": "mongodb",
    "kafka": "kafka",
    "rabbit": "rabbitmq",
    "rabbitmq": "rabbitmq",
    "nginx": "nginx",
    "haproxy": "haproxy",
    "elasticsearch": "elasticsearch",
    "elastic": "elasticsearch",
    "memcache": "memcached",
    "memcached": "memcached",
    "sqs": "sqs",
}


def infer_technology_from_name(name: str) -> str | None:
    """Infer technology from a service/dependency name using keyword matching."""
    name_lower = name.lower()
    for keyword, tech in TECH_KEYWORDS.items():
        if keyword in name_lower:
            return tech
    return None


def dependency_technology(dep: Dependency) -> str | None:
    """The technology one dependency maps to, or None (APIs, untyped databases).

    A declared technology wins: ``database_type``, which nthlayer-common also
    fills from a legacy cache's or queue's ``type:`` (opensrm-wo62.4.7). Only
    without one is a cache or queue inferred from its name, then defaulted.
    """
    if dep.type in ("database", "cache", "queue") and dep.database_type:
        return dep.database_type.lower()
    if dep.type == "cache":
        name_lower = dep.name.lower()
        if "redis" in name_lower:
            return "redis"
        if "memcache" in name_lower or "memcached" in name_lower:
            return "memcached"
        logger.warning(
            "Could not infer cache technology for dependency '%s', "
            "defaulting to redis. Set database_type explicitly.",
            dep.name,
        )
        return "redis"
    if dep.type == "queue":
        name_lower = dep.name.lower()
        if "kafka" in name_lower:
            return "kafka"
        if "rabbit" in name_lower:
            return "rabbitmq"
        if "sqs" in name_lower:
            return "sqs"
        logger.warning(
            "Could not infer queue technology for dependency '%s', "
            "defaulting to kafka. Set database_type explicitly.",
            dep.name,
        )
        return "kafka"
    # Databases without database_type, and APIs, map to no alert template.
    return None


def extract_dependency_technologies(manifest: ReliabilityManifest) -> list[str]:
    """Extract technology names from manifest dependencies.

    Consolidates dependency extraction logic previously duplicated in
    generators/alerts.py and loki/generator.py.

    Args:
        manifest: ReliabilityManifest instance

    Returns:
        Deduplicated technology names in declaration order (e.g.,
        ["postgresql", "redis"]). Ordered, not a set: the list reaches
        generated output, which must not depend on string-hash seeding.
    """
    technologies = [dependency_technology(dep) for dep in manifest.dependencies]
    return list(dict.fromkeys(t for t in technologies if t))
