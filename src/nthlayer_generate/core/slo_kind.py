"""Which rule family an SLO belongs to, if any.

One classifier for every generator: the recording rules, the Sloth spec, the
dashboard, ``alerts evaluate`` and ``slo show/collect`` must agree on which
SLOs are read as a success ratio (opensrm-onc6).
"""

from __future__ import annotations

from nthlayer_common.manifest import SLODefinition

# Checked in order against the SLO's type, or its name when it has no type.
_KIND_BY_NEEDLE = (
    ("availability", "availability"),
    ("latency", "latency"),
    ("error", "error_rate"),
    ("throughput", "throughput"),
)


def slo_kind(slo: SLODefinition) -> str | None:
    """The rule family an SLO dispatches to, by its type (or, unset, its name).

    None means no family: a ``custom`` SLO, or one whose type names none
    (freshness, lag). Such an SLO has no canned rules and no error budget
    (ruling D5), and its target is not known to be a success percentage, so
    nothing may budget, alert on or chart it as one.
    """
    slo_type = (slo.slo_type or slo.name).lower()
    for needle, kind in _KIND_BY_NEEDLE:
        if needle in slo_type:
            return kind
    return None
