"""
Topology export for dependency graph visualization.

Converts dependency graphs to exportable formats (JSON, Mermaid, DOT)
enriched with SLO contract data from reliability manifests.
"""

from nthlayer_generate.topology.enrichment import build_topology
from nthlayer_generate.topology.models import (
    SLOContract,
    TopologyEdge,
    TopologyGraph,
    TopologyNode,
)
from nthlayer_generate.topology.serializers import (
    serialize_dot,
    serialize_json,
    serialize_mermaid,
)

__all__ = [
    # Models
    "SLOContract",
    "TopologyNode",
    "TopologyEdge",
    "TopologyGraph",
    # Enrichment
    "build_topology",
    # Serializers
    "serialize_json",
    "serialize_mermaid",
    "serialize_dot",
]
