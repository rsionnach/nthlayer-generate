"""wo62.4.4's own fixes, beyond moving the commands onto nthlayer-common.

- opensrm-2ykh: validate-slo read spec.query / spec.objectives[0]...query,
  which no shipped legacy manifest has, so every SLO validated an empty query.
- wo62.4 D6: ownership passed getattr(context, "owner"), which ServiceContext
  never had, so the declared owner was always None.
- diff-envs must report, not raise, on a resource spec common's loader cannot
  read (opensrm-wo62.4.10). The legacy path exited 0 on these.

Manifests are committed examples unless stated.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from nthlayer_generate.cli.environments import diff_envs_command
from nthlayer_generate.cli.ownership import ownership_command
from nthlayer_generate.cli.validate_slo import (
    SLOValidationResult,
    extract_metric_names,
    validate_slo_command,
)

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


# =============================================================================
# opensrm-2ykh: validate-slo validates the SLO's real query
# =============================================================================


def test_validate_slo_checks_each_slos_indicator_query():
    """examples/services/payment-api.yaml: availability and latency-p95 carry
    spec.indicator.query; latency-p99 has none. The legacy read gave "" for all."""
    seen: dict[str, str] = {}

    async def record(slo_name, query, prometheus_url=None):
        seen[slo_name] = query
        return SLOValidationResult(slo_name=slo_name, query=query, metrics=[])

    with patch("nthlayer_generate.cli.validate_slo.validate_slo_metrics", side_effect=record):
        validate_slo_command(str(EXAMPLES / "services" / "payment-api.yaml"), output_format="json")

    assert set(seen) == {
        "payment-api-availability",
        "payment-api-latency-p95",
        "payment-api-latency-p99",
    }
    assert seen["payment-api-latency-p99"] == ""
    # ${service} is substituted by common's loader, and the metrics are real.
    assert 'service="payment-api"' in seen["payment-api-latency-p95"]
    assert extract_metric_names(seen["payment-api-availability"]) == {"http_requests"}
    assert extract_metric_names(seen["payment-api-latency-p95"]) == {
        "http_request_duration_seconds_bucket"
    }


# =============================================================================
# wo62.4 D6: ownership's declared owner is the manifest's ownership email
# =============================================================================


@pytest.mark.parametrize(
    ("path", "owner"),
    [
        # srm/v1 spec.ownership.email
        pytest.param(
            EXAMPLES / "opensrm" / "api-critical.reliability.yaml",
            "payments-oncall@example.com",
            id="srm-v1-email",
        ),
        # no email declared
        pytest.param(EXAMPLES / "services" / "payment-api.yaml", None, id="legacy-none"),
    ],
)
def test_ownership_passes_the_declared_owner(path, owner):
    # The resolver fails after recording its arguments; the command reports
    # that as exit 2, so no provider or output path runs.
    resolve = AsyncMock(side_effect=RuntimeError("stop after the call"))
    with patch("nthlayer_generate.cli.ownership.OwnershipResolver") as resolver_cls:
        resolver_cls.return_value.resolve = resolve
        assert ownership_command(str(path), output_format="json") == 2

    assert resolve.call_args.kwargs["declared_owner"] == owner


# =============================================================================
# diff-envs on a malformed resource spec
# =============================================================================

_MALFORMED = {
    "dependencies-spec-str": "  - kind: Dependencies\n    name: upstream\n    spec: oops\n",
    "database-entry-str": (
        "  - kind: Dependencies\n    name: upstream\n    spec:\n      databases: [pg]\n"
    ),
    "resources-str": None,
}


@pytest.mark.parametrize("resources", _MALFORMED.values(), ids=_MALFORMED.keys())
def test_diff_envs_reports_a_malformed_spec(resources, tmp_path):
    head = "service:\n  name: bad-service\n  team: platform\n  tier: standard\n  type: api\n"
    body = "resources: oops\n" if resources is None else "resources:\n" + resources
    path = tmp_path / "bad-service.yaml"
    path.write_text(head + body)

    assert diff_envs_command(str(path), "dev", "prod") == 1
