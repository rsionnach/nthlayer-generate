"""Manifest placeholders in an author's PromQL (``${service}`` and friends).

An SLO's own queries may name the service through placeholders instead of
literally. Every generator that emits an author's query substitutes them
here, so the Sloth spec and the recording rules cannot disagree about what
a placeholder means (opensrm-zo0o).
"""

from __future__ import annotations

from nthlayer_common.manifest import ReliabilityManifest


def substitute_manifest_placeholders(query: str, manifest: ReliabilityManifest) -> str:
    """Replace ``${service}``, ``${team}``, ``${tier}`` and ``${type}`` in ``query``.

    Plain string replacement, no PromQL parsing: the query is the author's,
    and only the placeholders change.
    """
    query = query.replace("${service}", manifest.name)
    query = query.replace("${team}", manifest.team)
    query = query.replace("${tier}", manifest.tier)
    # ${type} is a matcher against existing series, so it keeps the
    # authored spelling (opensrm-z3ab). `or manifest.type` for the
    # type-checker only: authored_type is declared Optional so it can
    # default to None and mean "derive from type", and __post_init__ always
    # fills it. The fallback is unreachable after construction.
    return query.replace("${type}", manifest.authored_type or manifest.type)
