"""Shared helpers for working with ReliabilityManifest.

Provides utility functions used across multiple generators.
"""

from __future__ import annotations

import structlog
from nthlayer_common.manifest import Dependency, ReliabilityManifest

logger = structlog.get_logger()


def dependency_technology(dep: Dependency) -> str | None:
    """The technology one dependency maps to, or None (APIs, untyped databases).

    A declared technology wins: ``database_type``, which nthlayer-common also
    fills from a legacy cache's or queue's ``type:`` (opensrm-wo62.4.7). Only
    without one is a cache or queue inferred from its name, then defaulted.
    """
    if dep.type in ("database", "cache", "queue") and dep.database_type:
        declared = dep.database_type.strip().lower()
        if declared:
            return declared
    if dep.type == "cache":
        name_lower = dep.name.lower()
        if "redis" in name_lower:
            return "redis"
        if "memcache" in name_lower:
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

    The per-dependency rule is dependency_technology; this applies it to the
    whole manifest for alerts and loki.

    Args:
        manifest: ReliabilityManifest instance

    Returns:
        Deduplicated technology names in declaration order (e.g.,
        ["postgresql", "redis"]). Ordered, not a set: the list reaches
        generated output, which must not depend on string-hash seeding.
    """
    technologies = [dependency_technology(dep) for dep in manifest.dependencies]
    return list(dict.fromkeys(t for t in technologies if t))
