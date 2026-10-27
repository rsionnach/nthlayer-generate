"""Tests for alerting configuration parsing and tier defaults."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import yaml

from nthlayer_generate.specs.alerting import (
    TIER_DEFAULT_RULES,
    AlertChannels,
    AlertingConfig,
    ForDuration,
    SpecAlertRule,
    parse_alerting_config,
    resolve_effective_rules,
)

# -------------------------------------------------------------------------
# parse_alerting_config
# -------------------------------------------------------------------------


class TestParseAlertingConfig:
    def test_returns_none_for_none(self) -> None:
        assert parse_alerting_config(None) is None

    def test_returns_none_for_empty_dict(self) -> None:
        assert parse_alerting_config({}) is None

    def test_parses_channels(self) -> None:
        data = {
            "channels": {
                "slack_webhook": "https://hooks.slack.com/test",
                "pagerduty_key": "abc123",
            },
            "rules": [],
        }
        cfg = parse_alerting_config(data)
        assert cfg is not None
        assert cfg.channels.slack_webhook == "https://hooks.slack.com/test"
        assert cfg.channels.pagerduty_key == "abc123"

    def test_parses_rules(self) -> None:
        data = {
            "rules": [
                {
                    "name": "budget-warning",
                    "type": "budget_threshold",
                    "slo": "availability",
                    "threshold": 0.75,
                    "severity": "warning",
                },
                {
                    "name": "high-burn",
                    "type": "burn_rate",
                    "slo": "*",
                    "threshold": 3.0,
                    "severity": "critical",
                },
            ],
        }
        cfg = parse_alerting_config(data)
        assert cfg is not None
        assert len(cfg.rules) == 2
        assert cfg.rules[0].name == "budget-warning"
        assert cfg.rules[0].type == "budget_threshold"
        assert cfg.rules[0].slo == "availability"
        assert cfg.rules[0].threshold == 0.75
        assert cfg.rules[1].slo == "*"

    def test_auto_rules_defaults_to_true(self) -> None:
        cfg = parse_alerting_config({"rules": []})
        assert cfg is not None
        assert cfg.auto_rules is True

    def test_auto_rules_can_be_disabled(self) -> None:
        cfg = parse_alerting_config({"auto_rules": False, "rules": []})
        assert cfg is not None
        assert cfg.auto_rules is False

    def test_parses_for_duration(self) -> None:
        data = {
            "rules": [],
            "for_duration": {
                "page": "1m",
                "ticket": "10m",
            },
        }
        cfg = parse_alerting_config(data)
        assert cfg is not None
        assert cfg.for_duration.page == "1m"
        assert cfg.for_duration.ticket == "10m"

    def test_for_duration_defaults_when_absent(self) -> None:
        data = {"rules": []}
        cfg = parse_alerting_config(data)
        assert cfg is not None
        assert cfg.for_duration.page == "2m"
        assert cfg.for_duration.ticket == "15m"

    def test_for_duration_partial_override(self) -> None:
        data = {
            "rules": [],
            "for_duration": {"page": "30s"},
        }
        cfg = parse_alerting_config(data)
        assert cfg is not None
        assert cfg.for_duration.page == "30s"
        assert cfg.for_duration.ticket == "15m"  # default kept


# -------------------------------------------------------------------------
# AlertChannels env var resolution
# -------------------------------------------------------------------------


class TestAlertChannelsEnv:
    def test_resolve_env_vars(self) -> None:
        with patch.dict(os.environ, {"SLACK_URL": "https://resolved.slack"}):
            channels = AlertChannels(
                slack_webhook="${SLACK_URL}",
                pagerduty_key=None,
            )
            resolved = channels.resolve_env_vars()
            assert resolved.slack_webhook == "https://resolved.slack"
            assert resolved.pagerduty_key is None

    def test_unresolved_env_var_kept(self) -> None:
        channels = AlertChannels(slack_webhook="${NONEXISTENT}")
        resolved = channels.resolve_env_vars()
        assert resolved.slack_webhook == "${NONEXISTENT}"


# -------------------------------------------------------------------------
# Tier default rules
# -------------------------------------------------------------------------


class TestTierDefaults:
    @pytest.mark.parametrize("tier", ["critical", "high", "standard", "low"])
    def test_tier_has_defaults(self, tier: str) -> None:
        assert tier in TIER_DEFAULT_RULES
        assert len(TIER_DEFAULT_RULES[tier]) >= 1

    def test_critical_has_four_rules(self) -> None:
        assert len(TIER_DEFAULT_RULES["critical"]) == 4

    def test_low_has_one_rule(self) -> None:
        assert len(TIER_DEFAULT_RULES["low"]) == 1

    def test_standard_has_no_exhaustion(self) -> None:
        types = [r[1] for r in TIER_DEFAULT_RULES["standard"]]
        assert "budget_exhaustion" not in types

    def test_critical_thresholds_tighter_than_standard(self) -> None:
        critical_warning = next(
            r for r in TIER_DEFAULT_RULES["critical"] if r[0] == "budget-warning"
        )
        standard_warning = next(
            r for r in TIER_DEFAULT_RULES["standard"] if r[0] == "budget-warning"
        )
        assert critical_warning[2] < standard_warning[2]  # 0.50 < 0.80


# -------------------------------------------------------------------------
# resolve_effective_rules
# -------------------------------------------------------------------------


class TestResolveEffectiveRules:
    def test_wildcard_expansion(self) -> None:
        cfg = AlertingConfig(
            rules=[
                SpecAlertRule(
                    name="high-burn",
                    type="burn_rate",
                    slo="*",
                    threshold=3.0,
                ),
            ],
            auto_rules=False,
        )
        result = resolve_effective_rules(cfg, "standard", ["avail", "latency"])
        assert len(result) == 2
        assert {r.slo for r in result} == {"avail", "latency"}

    def test_auto_rules_added(self) -> None:
        cfg = AlertingConfig(rules=[], auto_rules=True)
        result = resolve_effective_rules(cfg, "critical", ["availability"])
        # Should have tier-critical defaults for one SLO
        assert len(result) == len(TIER_DEFAULT_RULES["critical"])

    def test_auto_rules_not_added_when_disabled(self) -> None:
        cfg = AlertingConfig(rules=[], auto_rules=False)
        result = resolve_effective_rules(cfg, "critical", ["availability"])
        assert result == []

    def test_explicit_overrides_auto(self) -> None:
        cfg = AlertingConfig(
            rules=[
                SpecAlertRule(
                    name="budget-warning",
                    type="budget_threshold",
                    slo="availability",
                    threshold=0.60,
                ),
            ],
            auto_rules=True,
        )
        result = resolve_effective_rules(cfg, "critical", ["availability"])
        # budget-warning for availability already present, so auto-default
        # for that (name, slo) pair should NOT be duplicated
        budget_warnings = [
            r for r in result if r.name == "budget-warning" and r.slo == "availability"
        ]
        assert len(budget_warnings) == 1
        assert budget_warnings[0].threshold == 0.60

    def test_unknown_tier_no_auto_rules(self) -> None:
        cfg = AlertingConfig(rules=[], auto_rules=True)
        result = resolve_effective_rules(cfg, "nonexistent", ["availability"])
        assert result == []


# -------------------------------------------------------------------------
# get_rules_for_slo
# -------------------------------------------------------------------------


class TestGetRulesForSlo:
    def test_exact_match(self) -> None:
        cfg = AlertingConfig(
            rules=[
                SpecAlertRule(name="a", type="budget_threshold", slo="avail", threshold=0.5),
                SpecAlertRule(name="b", type="budget_threshold", slo="latency", threshold=0.5),
            ],
        )
        result = cfg.get_rules_for_slo("avail")
        assert len(result) == 1
        assert result[0].name == "a"

    def test_wildcard_matches_any(self) -> None:
        cfg = AlertingConfig(
            rules=[
                SpecAlertRule(name="a", type="burn_rate", slo="*", threshold=3.0),
            ],
        )
        result = cfg.get_rules_for_slo("whatever")
        assert len(result) == 1

    def test_disabled_rules_excluded(self) -> None:
        cfg = AlertingConfig(
            rules=[
                SpecAlertRule(
                    name="a",
                    type="budget_threshold",
                    slo="avail",
                    threshold=0.5,
                    enabled=False,
                ),
            ],
        )
        assert cfg.get_rules_for_slo("avail") == []


# -------------------------------------------------------------------------
# ForDuration configuration
# -------------------------------------------------------------------------


class TestForDuration:
    def test_default_for_duration(self) -> None:
        cfg = AlertingConfig(rules=[])
        assert cfg.for_duration is not None
        assert cfg.for_duration.page == "2m"
        assert cfg.for_duration.ticket == "15m"

    def test_custom_for_duration(self) -> None:
        cfg = AlertingConfig(
            rules=[],
            for_duration=ForDuration(page="1m", ticket="10m"),
        )
        assert cfg.for_duration.page == "1m"
        assert cfg.for_duration.ticket == "10m"

    def test_get_for_severity_critical(self) -> None:
        cfg = AlertingConfig(rules=[])
        assert cfg.for_duration.get_for_severity("critical") == "2m"

    def test_get_for_severity_warning(self) -> None:
        cfg = AlertingConfig(rules=[])
        assert cfg.for_duration.get_for_severity("warning") == "15m"

    def test_get_for_severity_info(self) -> None:
        cfg = AlertingConfig(rules=[])
        assert cfg.for_duration.get_for_severity("info") == "15m"


# -------------------------------------------------------------------------
# OpenSRM integration
# -------------------------------------------------------------------------


class TestOpenSRMParsing:
    def test_parse_opensrm_with_alerting(self) -> None:
        from nthlayer_common.manifest.parser.v1 import parse_srm_v1

        from nthlayer_generate.specs.alerting import manifest_alerting

        data = {
            "apiVersion": "srm/v1",
            "kind": "ServiceReliabilityManifest",
            "metadata": {"name": "test-svc", "team": "eng", "tier": "high"},
            "spec": {
                "type": "api",
                "slos": {"availability": {"target": 99.9, "window": "30d"}},
                "alerting": {
                    "channels": {"slack_webhook": "${SLACK_URL}"},
                    "rules": [
                        {
                            "name": "budget-warn",
                            "type": "budget_threshold",
                            "slo": "availability",
                            "threshold": 0.75,
                            "severity": "warning",
                        }
                    ],
                    "auto_rules": False,
                },
            },
        }
        alerting = manifest_alerting(parse_srm_v1(data))
        assert alerting is not None
        assert len(alerting.rules) == 1
        assert alerting.channels.slack_webhook == "${SLACK_URL}"
        assert alerting.auto_rules is False

    def test_parse_opensrm_with_for_duration(self) -> None:
        from nthlayer_common.manifest.parser.v1 import parse_srm_v1

        from nthlayer_generate.specs.alerting import manifest_alerting

        data = {
            "apiVersion": "srm/v1",
            "kind": "ServiceReliabilityManifest",
            "metadata": {"name": "test-svc", "team": "eng", "tier": "critical"},
            "spec": {
                "type": "api",
                "alerting": {
                    "for_duration": {"page": "1m", "ticket": "10m"},
                    "rules": [],
                },
            },
        }
        alerting = manifest_alerting(parse_srm_v1(data))
        assert alerting is not None
        assert alerting.for_duration.page == "1m"
        assert alerting.for_duration.ticket == "10m"

    def test_parse_opensrm_without_alerting(self) -> None:
        from nthlayer_common.manifest.parser.v1 import parse_srm_v1

        from nthlayer_generate.specs.alerting import manifest_alerting

        data = {
            "apiVersion": "srm/v1",
            "kind": "ServiceReliabilityManifest",
            "metadata": {"name": "test-svc", "team": "eng", "tier": "standard"},
            "spec": {"type": "api"},
        }
        assert manifest_alerting(parse_srm_v1(data)) is None


# -------------------------------------------------------------------------
# Legacy format integration
# -------------------------------------------------------------------------


class TestLegacyParsing:
    """A legacy ``kind: Alerts`` resource reaches generate's parser through
    nthlayer-common's legacy loader (opensrm-wo62.1, D3). The ``service:``
    header is examples/uat/payment-api.yaml's shape (the one shipped legacy
    example with an Alerts resource)."""

    @staticmethod
    def _load(tmp_path: Path, resources: list[dict[str, Any]]) -> Any:
        from nthlayer_common.manifest import load_manifest

        from nthlayer_generate.specs.alerting import manifest_alerting

        path = tmp_path / "svc.yaml"
        path.write_text(
            yaml.safe_dump(
                {
                    "service": {"name": "svc", "team": "eng", "tier": "high", "type": "api"},
                    "resources": resources,
                }
            ),
            encoding="utf-8",
        )
        return manifest_alerting(load_manifest(path, suppress_deprecation_warning=True))

    def test_extract_alerting_from_legacy_resources(self, tmp_path: Path) -> None:
        resources = [
            {"kind": "SLO", "name": "avail", "spec": {}},
            {
                "kind": "Alerts",
                "name": "alerts",
                "spec": {
                    "channels": {"slack_webhook": "https://hooks.slack.com/x"},
                    "rules": [
                        {
                            "name": "warn",
                            "type": "budget_threshold",
                            "slo": "*",
                            "threshold": 0.80,
                        }
                    ],
                    "auto_rules": True,
                },
            },
        ]
        alerting = self._load(tmp_path, resources)
        assert alerting is not None
        assert len(alerting.rules) == 1
        assert alerting.channels.slack_webhook == "https://hooks.slack.com/x"

    def test_no_alerts_resource_returns_none(self, tmp_path: Path) -> None:
        resources = [{"kind": "SLO", "name": "avail", "spec": {}}]
        assert self._load(tmp_path, resources) is None


# -------------------------------------------------------------------------
# manifest_alerting over nthlayer-common's model (opensrm-wo62.1, D3)
# -------------------------------------------------------------------------

_EX = Path(__file__).resolve().parents[1] / "examples"
# The one shipped example with an alerting block: a legacy `kind: Alerts`
# resource (examples/uat/payment-api.yaml @6e71305).
_UAT_LEGACY = _EX / "uat" / "payment-api.yaml"
_API_BASIC = _EX / "opensrm" / "api-basic.reliability.yaml"  # f252974


def _alerts_block(path: Path) -> dict[str, Any]:
    resources = yaml.safe_load(path.read_text(encoding="utf-8"))["resources"]
    (block,) = [r["spec"] for r in resources if r["kind"] == "Alerts"]
    return block  # type: ignore[no-any-return]


class TestManifestAlerting:
    def test_parses_the_raw_block_common_keeps(self) -> None:
        from nthlayer_common.manifest import load_manifest

        from nthlayer_generate.specs.alerting import manifest_alerting

        manifest = load_manifest(_UAT_LEGACY, suppress_deprecation_warning=True)
        expected = parse_alerting_config(_alerts_block(_UAT_LEGACY))

        parsed = manifest_alerting(manifest)

        assert expected is not None
        assert parsed is not None
        assert parsed.channels == expected.channels
        assert parsed == expected

    def test_none_without_a_block(self) -> None:
        from nthlayer_common.manifest import load_manifest

        from nthlayer_generate.specs.alerting import manifest_alerting

        assert manifest_alerting(load_manifest(_API_BASIC)) is None


def test_malformed_block_fails_nthlayer_alerts_evaluate(tmp_path: Path) -> None:
    """Review Focus 6: ``alerts evaluate`` fails on a malformed block, before
    the switch (at load) and after it (at use). Run as the console script
    runs, so the exit code is the process's.

    Fixture: examples/opensrm/api-basic.reliability.yaml @f252974 plus
    ``spec.alerting: [1]`` (a list where the block's mapping belongs).
    """
    data = yaml.safe_load(_API_BASIC.read_text(encoding="utf-8"))
    data["spec"]["alerting"] = [1]
    path = tmp_path / "user-api.reliability.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "from nthlayer_generate.demo import main; main()",
            "alerts",
            "evaluate",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert proc.returncode == 1
