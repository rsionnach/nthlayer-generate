"""What the goldens cannot see across the manifest-model switch (opensrm-wo62.1).

Spec §6.3 ("Undetectable by goldens") and the Checkpoint B kill checks name
divergences no golden pins: D6 (``${type}``), D3 (``alerting``), D4
(contracts beyond the single srm/v1 one), G5 at ``validate`` and G1 in the
sloth and dashboard SLI. These tests are the only check on them.

They are written against the pre-switch consumers (generate's own manifest
stack) and must pass UNCHANGED after plan Task 11 moves every consumer onto
nthlayer-common's model. ``SWITCHED`` tells the two runs apart by whether
generate's loader still exists, so the one file serves both; a test asserts
a different value on each side only where the spec sanctions the change
(spec §5.2 for docs/backstage, §6.3 G1 and G5), and says so.

Expected values come from shipped examples, the OpenSRM schema and spec, and
documented formats — never from running the code under test. Every fixture
is a shipped file, or a shipped file with a stated edit (source path, the
commit it was last changed in, and what was edited).
"""

from __future__ import annotations

import copy
import importlib.util
import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
import yaml

from nthlayer_generate.alerts.loader import AlertTemplateLoader
from nthlayer_generate.cli.alerts import (
    alerts_evaluate_command,
    alerts_show_command,
    alerts_test_command,
)
from nthlayer_generate.dashboards.manifest_builder import build_dashboard_from_manifest
from nthlayer_generate.generators.alerts import generate_alerts_from_manifest
from nthlayer_generate.generators.backstage import generate_backstage_entity
from nthlayer_generate.generators.docs import generate_service_docs
from nthlayer_generate.generators.sloth import generate_sloth_from_manifest
from nthlayer_generate.slos.pipeline import AlertPipeline
from nthlayer_generate.specs.alerting import (
    TIER_DEFAULT_RULES,
    AlertChannels,
    AlertingConfig,
    ForDuration,
    SpecAlertRule,
)
from nthlayer_generate.specs.contracts import (
    ContractRegistry,
    validate_dependency_expectations,
    validate_transitive_feasibility,
)
from nthlayer_generate.specs.validator import validate_service_file

REPO = Path(__file__).resolve().parents[1]
EX = REPO / "examples"
OPENSRM = REPO.parent / "opensrm"

# Shipped inputs. Commits are each file's last change at the time of writing.
UAT_SRM = EX / "uat" / "payment-api.reliability.yaml"  # 9e3b2aa
UAT_LEGACY = EX / "uat" / "payment-api.yaml"  # 6e71305 — the one `kind: Alerts` example
API_BASIC = EX / "opensrm" / "api-basic.reliability.yaml"  # f252974
API_CRITICAL = EX / "opensrm" / "api-critical.reliability.yaml"  # f252974
LEGACY_WITH_DEPS = EX / "services" / "payment-api-with-deps.yaml"  # 0331eff
V2_API_FULL = OPENSRM / "spec" / "v2" / "examples" / "migration" / "api-full-v2.yaml"  # 0530688

# True once plan Task 11 has deleted generate's loader and every consumer
# takes nthlayer-common's ReliabilityManifest.
SWITCHED = importlib.util.find_spec("nthlayer_generate.specs.loader") is None


def load(path: Path) -> Any:
    """Load *path* with the loader the consumers take on this side of the switch."""
    if SWITCHED:
        from nthlayer_common.manifest import load_manifest
    else:
        from nthlayer_generate.specs.loader import load_manifest  # type: ignore[no-redef]
    return load_manifest(path, suppress_deprecation_warning=True)


def parsed_alerting(manifest: Any) -> AlertingConfig | None:
    """The manifest's parsed alerting block: at load before, at use after (D3)."""
    if SWITCHED:
        from nthlayer_generate.specs.alerting import manifest_alerting

        return manifest_alerting(manifest)
    return manifest.alerting  # type: ignore[no-any-return]


def test_switch_detection_agrees_across_the_retired_stack() -> None:
    # Task 11 deletes specs/manifest.py, specs/loader.py and
    # specs/opensrm_parser.py together; a half-done switch would make SWITCHED
    # pick the wrong side's expectations.
    retired = [
        importlib.util.find_spec(f"nthlayer_generate.specs.{m}") is None
        for m in ("manifest", "loader", "opensrm_parser")
    ]
    assert retired == [SWITCHED] * 3


def _read(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _write(directory: Path, name: str, data: Any) -> Path:
    path = directory / name
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def _with_both_query_forms(slo: dict[str, Any], query: str) -> None:
    """Put *query* where both loaders read it.

    generate's srm/v1 parser reads only a top-level ``query``
    (specs/opensrm_parser.py:237); common's reads only ``indicator.query``
    (nthlayer_common parser/v1.py, opensrm-0i5h). Plan Task 11 moves the
    shipped UAT example to the nested form in the switch commit (spec §4.2);
    a fixture that must pass on both sides carries the identical text in
    both places, so the query itself never differs between the two runs.
    """
    slo["query"] = query
    slo["indicator"] = {"query": query}


# =============================================================================
# D6 — `${type}` substitutes the AUTHORED spelling (spec §4.1, §6.3)
# =============================================================================

# nthlayer-common's documented input aliases (SERVICE_TYPE_ALIASES,
# nthlayer_common/manifest/models.py; spec §7 "common's SERVICE_TYPE_ALIASES,
# the documented input conveniences"), and the spelling each resolves to.
ALIAS_RESOLVES_TO = {
    "background-job": "worker",
    "pipeline": "batch",
    "web": "x-web",
}


def _type_templated_manifest(directory: Path, authored: str) -> Path:
    """examples/uat/payment-api.reliability.yaml @9e3b2aa, edited.

    Edits: ``spec.type`` -> *authored*; every ``service="payment-api"``
    selector in both SLO queries gains ``,svc_type="${type}"`` (the README's
    documented example, "If you author `type: web` and query
    `svc_type="${type}"`, you still get `svc_type="web"`"); each query is
    carried in both srm/v1 query forms (see _with_both_query_forms).
    """
    data = _read(UAT_SRM)
    data["spec"]["type"] = authored
    for slo in data["spec"]["slos"].values():
        query = slo["query"].replace(
            'service="payment-api"', 'service="payment-api",svc_type="${type}"'
        )
        _with_both_query_forms(slo, query)
    return _write(directory, "payment-api.reliability.yaml", data)


@pytest.mark.parametrize("authored", sorted(ALIAS_RESOLVES_TO))
def test_sloth_sli_query_gets_the_authored_type_and_labels_get_the_resolved(
    authored: str, tmp_path: Path
) -> None:
    resolved = ALIAS_RESOLVES_TO[authored]
    manifest = load(_type_templated_manifest(tmp_path, authored))

    result = generate_sloth_from_manifest(manifest, tmp_path / "out")
    assert result.success and result.output_file, result.error
    spec = _read(result.output_file)

    # The emitted label carries the canonical spelling (README "Upgrading":
    # "the `type` label on generated Sloth rules" becomes x-web).
    assert spec["labels"]["type"] == resolved

    # Every SLI query matches existing series with the authored spelling.
    queries = [q for slo in spec["slos"] for q in slo["sli"]["events"].values() if q]
    assert queries, "no SLI query rendered; the check below would be vacuous"
    for query in queries:
        assert "${type}" not in query
        assert f'svc_type="{authored}"' in query
        assert f'svc_type="{resolved}"' not in query


# =============================================================================
# D3 — the `alerting` block: valid, missing, malformed (spec §5.2)
# =============================================================================

# The documented alerting format: the `kind: Alerts` resource of
# examples/uat/payment-api.yaml @6e71305 (the shipped example of the block),
# plus `for_duration` from docs/plans/2026-03-10-alert-for-budget-policy.md
# @f5cd744 Task 2 (`for_duration: {page: 1m, ticket: 10m}`; defaults 2m/15m
# when absent).
FOR_DURATION = {"page": "1m", "ticket": "10m"}


def _documented_alerts_block() -> dict[str, Any]:
    resources = _read(UAT_LEGACY)["resources"]
    (block,) = [r["spec"] for r in resources if r["kind"] == "Alerts"]
    return copy.deepcopy(block)  # type: ignore[no-any-return]


def _documented_rules() -> list[SpecAlertRule]:
    # The three rules of examples/uat/payment-api.yaml's Alerts resource.
    return [
        SpecAlertRule("budget-warning", "budget_threshold", "availability", 0.75, "warning"),
        SpecAlertRule("budget-critical", "budget_threshold", "availability", 0.90, "critical"),
        SpecAlertRule("high-burn", "burn_rate", "*", 3.0, "warning"),
    ]


def _srm_with_alerting(directory: Path, block: Any) -> Path:
    """examples/opensrm/api-critical.reliability.yaml @f252974, plus
    ``spec.alerting: <block>`` (srm/v1 reads it there: generate
    specs/opensrm_parser.py:143, common parser/v1.py:124)."""
    data = _read(API_CRITICAL)
    data["spec"]["alerting"] = block
    return _write(directory, "payment-api.reliability.yaml", data)


def _srm_valid(directory: Path) -> Path:
    block = _documented_alerts_block()
    block["for_duration"] = dict(FOR_DURATION)
    return _srm_with_alerting(directory, block)


def _srm_missing(directory: Path) -> Path:
    # examples/opensrm/api-critical.reliability.yaml @f252974, unedited (it has
    # no alerting block), copied so it sits where _srm_valid writes.
    return _write(directory, "payment-api.reliability.yaml", _read(API_CRITICAL))


def _srm_malformed(directory: Path) -> Path:
    # Review Focus 6's malformed block: a list where a mapping belongs.
    return _srm_with_alerting(directory, [1])


def _legacy_valid(directory: Path) -> Path:
    return UAT_LEGACY  # shipped, with its `kind: Alerts` resource


# SLO names each fixture declares (from the files), and its tier.
API_CRITICAL_SLOS = ["availability", "latency", "error_rate"]
UAT_LEGACY_SLOS = ["availability", "latency-p95"]

# case id -> (fixture, tier, slo names, expected parsed config or None)
ALERTING_CASES: dict[str, tuple[Any, str, list[str], AlertingConfig | None]] = {
    "srm-valid": (
        _srm_valid,
        "critical",
        API_CRITICAL_SLOS,
        AlertingConfig(
            channels=AlertChannels(slack_webhook="${NTHLAYER_SLACK_WEBHOOK_ALERT}"),
            rules=_documented_rules(),
            auto_rules=False,
            for_duration=ForDuration(**FOR_DURATION),
        ),
    ),
    "legacy-valid": (
        _legacy_valid,
        "critical",
        UAT_LEGACY_SLOS,
        AlertingConfig(
            channels=AlertChannels(slack_webhook="${NTHLAYER_SLACK_WEBHOOK_ALERT}"),
            rules=_documented_rules(),
            auto_rules=False,
            for_duration=ForDuration(page="2m", ticket="15m"),  # documented defaults
        ),
    ),
    "srm-missing": (_srm_missing, "critical", API_CRITICAL_SLOS, None),
}


def _expected_effective_rules(case: str) -> Counter[tuple[str, str, float, str]]:
    """(name, slo, threshold, severity) of the rules that should be in force.

    Valid blocks: the explicit rules, a ``slo: "*"`` rule once per SLO
    (SpecAlertRule: "SLO name or '*' for all"), and nothing auto-generated
    because the block sets ``auto_rules: false``. Missing block: the tier's
    auto-generated defaults for every SLO (docs-site/commands/alerts.md:
    "auto-generated rules based on service tier"; TIER_DEFAULT_RULES is
    their single definition).

    PROVENANCE LIMIT: the tier-default table is not documented anywhere a
    test could cite (alerts.md's example table shows rule names the code has
    never used), so the missing-block expectation is read from
    TIER_DEFAULT_RULES. It detects a change in what a missing block MEANS
    across the switch, not a change to the defaults themselves.
    """
    _fixture, tier, slos, config = ALERTING_CASES[case]
    if config is None:
        return Counter(
            (name, slo, threshold, severity)
            for name, _type, threshold, severity in TIER_DEFAULT_RULES[tier]
            for slo in slos
        )
    out: Counter[tuple[str, str, float, str]] = Counter()
    for rule in config.rules:
        for slo in slos if rule.slo == "*" else [rule.slo]:
            out[(rule.name, slo, rule.threshold, rule.severity)] += 1
    return out


@pytest.fixture(autouse=True)
def _no_webhook_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # The documented block references ${NTHLAYER_SLACK_WEBHOOK_ALERT}; keep it
    # unresolved so no run depends on (or reaches) a real webhook.
    monkeypatch.delenv("NTHLAYER_SLACK_WEBHOOK_ALERT", raising=False)


@pytest.mark.parametrize("case", sorted(ALERTING_CASES))
def test_alerting_block_parses_to_the_documented_config(case: str, tmp_path: Path) -> None:
    fixture, _tier, _slos, expected = ALERTING_CASES[case]
    assert parsed_alerting(load(fixture(tmp_path))) == expected


@pytest.mark.parametrize("case", sorted(ALERTING_CASES))
def test_pipeline_evaluates_the_rules_the_block_puts_in_force(case: str, tmp_path: Path) -> None:
    fixture = ALERTING_CASES[case][0]
    result = AlertPipeline().evaluate_service(load(fixture(tmp_path)), simulate_burn_pct=50.0)
    assert result.rules_evaluated == sum(_expected_effective_rules(case).values())


@pytest.mark.parametrize("case", sorted(ALERTING_CASES))
def test_alerts_show_lists_the_rules_the_block_puts_in_force(
    case: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = ALERTING_CASES[case][0](tmp_path)
    capsys.readouterr()
    assert alerts_show_command(str(path), output_format="json") == 0
    shown = json.loads(capsys.readouterr().out)
    assert Counter(
        (r["name"], r["slo"], r["threshold"], r["severity"]) for r in shown
    ) == _expected_effective_rules(case)


@pytest.mark.parametrize("case", sorted(ALERTING_CASES))
def test_alerts_evaluate_counts_the_rules_the_block_puts_in_force(
    case: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = ALERTING_CASES[case][0](tmp_path)
    capsys.readouterr()
    alerts_evaluate_command(str(path), no_notify=True, output_format="json")
    (result,) = json.loads(capsys.readouterr().out)
    assert result["rules_evaluated"] == sum(_expected_effective_rules(case).values())


# Exit codes (docs-site/commands/alerts.md): 0 healthy, 1 warning, 2 critical.
# At 80% of the budget consumed:
#   valid blocks  budget-warning (0.75, warning) fires, budget-critical (0.90)
#                 does not, and high-burn (burn rate 3.0) does not, because the
#                 simulated burn rate is 80/50 = 1.6 (slos/pipeline.py
#                 _calculate_budget, ">50% -> >1x"). Worst is warning, so 1.
#   missing block the critical tier's defaults include a critical
#                 budget_threshold at 0.75 (TIER_DEFAULT_RULES), which fires,
#                 so 2.
# Matches the Checkpoint B goldens cli_alerts_test uat__payment-api (1) and
# opensrm__api-critical.reliability (2).
ALERTS_TEST_EXIT = {"srm-valid": 1, "legacy-valid": 1, "srm-missing": 2}


@pytest.mark.parametrize("case", sorted(ALERTING_CASES))
def test_alerts_test_exit_code_follows_the_block(case: str, tmp_path: Path) -> None:
    path = ALERTING_CASES[case][0](tmp_path)
    exit_code = alerts_test_command(str(path), simulate_burn=80.0, no_notify=True)
    assert exit_code == ALERTS_TEST_EXIT[case]


@pytest.mark.parametrize("case", sorted(ALERTING_CASES))
def test_generated_alert_for_durations_follow_the_block(case: str, tmp_path: Path) -> None:
    """for_duration overrides each alert's ``for`` by severity: page for
    critical, ticket otherwise (docs/plans/2026-03-10-alert-for-budget-policy.md:
    "overrides AlertRule.duration by severity"). With no block, each alert
    keeps its template's own duration — except a template ``for: 0m``, which
    AlertRule.validate_and_fix documents raising to the 1m minimum.

    PROVENANCE LIMIT (no-block case): the template durations and the 0m->1m
    rule are read from AlertTemplateLoader and a src docstring; neither is in
    user documentation. This detects the block's effect changing across the
    switch, not a change to the templates or to that rule."""
    config = ALERTING_CASES[case][3]
    alerts = generate_alerts_from_manifest(load(ALERTING_CASES[case][0](tmp_path)), quiet=True)
    assert alerts, "no alerts generated; the check below would be vacuous"

    if config is not None:
        fd = config.for_duration
        for alert in alerts:
            expected = fd.page if alert.severity == "critical" else fd.ticket
            assert alert.duration == expected, alert.name
        return

    loader = AlertTemplateLoader()
    template = {
        (a.technology, a.name): a.duration
        for tech in {a.technology for a in alerts}
        for a in loader.load_technology(tech)
    }
    assert {a.duration for a in alerts} - {"2m", "15m"}, (
        "every template duration equals a for_duration default, so this case "
        "cannot tell 'no block' from 'block without for_duration'"
    )
    for alert in alerts:
        own = template[(alert.technology, alert.name)]
        assert alert.duration == ("1m" if own == "0m" else own), alert.name


# --- malformed: fails where it is used, at every use site --------------------
#
# Before the switch generate parses `alerting` at load, so the load raises.
# After it, load succeeds and the use site's parse raises. The observable is
# the same either way: using the manifest at an alerting site raises
# parse_alerting_config's AttributeError on a non-mapping block. (That a
# crash, not a ValueError, is today's behaviour is pinned here, not endorsed.)


def _pipeline(path: Path) -> None:
    AlertPipeline().evaluate_service(load(path), simulate_burn_pct=50.0)


def _generate_alerts(path: Path) -> None:
    generate_alerts_from_manifest(load(path), quiet=True)


def _show(path: Path) -> None:
    alerts_show_command(str(path), output_format="json")


def _evaluate(path: Path) -> None:
    alerts_evaluate_command(str(path), no_notify=True, output_format="json")


def _test(path: Path) -> None:
    alerts_test_command(str(path), no_notify=True)


@pytest.mark.parametrize(
    "use", [_pipeline, _generate_alerts, _show, _evaluate, _test], ids=lambda f: f.__name__
)
def test_malformed_block_fails_at_every_alerting_use_site(use: Any, tmp_path: Path) -> None:
    with pytest.raises(AttributeError):
        use(_srm_malformed(tmp_path))


# --- docs and backstage: the one sanctioned difference (spec §5.2, RF 6) ------


def _strip(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return {k: _strip(v, key) for k, v in value.items() if k != key}
    if isinstance(value, list):
        return [_strip(v, key) for v in value]
    return value


def test_docs_and_backstage_ignore_a_valid_alerting_block(tmp_path: Path) -> None:
    """``alerting`` is not an input to docs or backstage: a valid block and no
    block produce the same documents, on both sides of the switch. Both
    fixtures are written to the same path in turn, so the entity's
    ``serviceManifest`` link is equal too."""
    outputs = []
    for name, fixture in (("valid", _srm_valid), ("missing", _srm_missing)):
        path = fixture(tmp_path)
        docs = generate_service_docs(
            path, tmp_path / name / "docs", include_adr=True, include_api=True
        )
        stage = generate_backstage_entity(path, tmp_path / name / "backstage")
        assert docs.success, docs.error
        assert stage.success and stage.output_file, stage.error
        readme = (tmp_path / name / "docs" / "README.md").read_text(encoding="utf-8")
        entity = _strip(json.loads(stage.output_file.read_text(encoding="utf-8")), "generatedAt")
        outputs.append((readme, entity))
    assert outputs[0] == outputs[1]


def test_malformed_block_at_docs_and_backstage(tmp_path: Path) -> None:
    """Before: rejected at load. After: accepted, because load no longer parses
    ``alerting`` and neither generator reads it (spec §5.2, Review Focus 6)."""
    path = _srm_malformed(tmp_path)
    docs = generate_service_docs(path, tmp_path / "docs")
    stage = generate_backstage_entity(path, tmp_path / "backstage")
    if SWITCHED:
        assert docs.success, docs.error
        assert stage.success, stage.error
    else:
        assert not docs.success
        assert not stage.success


# =============================================================================
# D4 — contracts (OpenSRM v1 §6.2-6.3, §11.3; v2 `spec.contracts`)
# =============================================================================
#
# srm/v1 declares ONE contract: opensrm/spec/v1/schema.json @d39818b,
# #/definitions/Spec/properties/contract -> #/definitions/Contract
# (availability is a Ratio, 0-1). v2 declares a LIST:
# opensrm/spec/v2/schema.json @d114d3d,
# #/definitions/ServiceManifest/properties/spec/properties/contracts/items ->
# #/definitions/Contract (name, promise.availability Ratio). Spec v1 §11.3:
# "Dependency expectation check — Warn if expects > provider promises".
#
# Dependency expectations use the shipped examples' form (`name`, `critical`,
# `slo.availability` in percent; examples/opensrm/api-critical.reliability.yaml),
# because both loaders read that form. NOTE: the v1 schema's own
# Dependency shape (`service`, `expects.availability`) is read by neither
# loader — a schema-valid dependency is dropped (reported with this task).


def _consumer(directory: Path, deps: list[dict[str, Any]], name: str = "consumer.yaml") -> Path:
    """examples/opensrm/api-basic.reliability.yaml @f252974 (service user-api),
    plus ``spec.dependencies: <deps>``."""
    data = _read(API_BASIC)
    data["spec"]["dependencies"] = deps
    return _write(directory, name, data)


def _dep(name: str, availability_pct: float | None = None) -> dict[str, Any]:
    dep: dict[str, Any] = {"name": name, "type": "api", "critical": True}
    if availability_pct is not None:
        dep["slo"] = {"availability": availability_pct}
    return dep


# PROVENANCE LIMIT: warnings are plain strings, so the two predicates below
# match substrings of contracts.py's messages. They detect a warning appearing
# or disappearing across the switch; a reworded message turns them red, which
# is a signal to re-check, not a behaviour change.
def _exceeds(warnings: list[str], dep: str) -> list[str]:
    return [w for w in warnings if f"'{dep}'" in w and "exceeds provider contract" in w]


def _no_contract(warnings: list[str], dep: str) -> list[str]:
    return [w for w in warnings if f"'{dep}'" in w and "has no contract" in w]


def test_srm_v1_contract_is_registered_under_its_service() -> None:
    # api-critical's `contract: {availability: 0.999, ...}`, service payment-api.
    registry = ContractRegistry.from_manifests([load(API_CRITICAL)])
    assert registry.services == ["payment-api"]
    assert registry.has_contract("payment-api")


def test_srm_v1_contract_bounds_a_dependency_expectation(tmp_path: Path) -> None:
    # Promise 0.999 = 99.9%. Expecting 99.95% exceeds it; expecting 99.9% does
    # not (spec §11.3: warn if expects > promises). A critical dependency with
    # no registered contract is warned about separately.
    registry = ContractRegistry.from_manifests([load(API_CRITICAL)])

    over = load(_consumer(tmp_path, [_dep("payment-api", 99.95), _dep("ledger-api")]))
    warnings = validate_dependency_expectations(over, registry)
    assert len(_exceeds(warnings, "payment-api")) == 1
    assert len(_no_contract(warnings, "ledger-api")) == 1
    assert len(warnings) == 2

    at = load(_consumer(tmp_path, [_dep("payment-api", 99.9)], name="at.yaml"))
    assert validate_dependency_expectations(at, registry) == []


def test_srm_v1_contract_transitive_feasibility_names_the_unknown_dependency() -> None:
    # api-critical promises 0.999 and has two critical dependencies:
    # postgres-primary (slo.availability 99.99 -> 0.9999) and stripe-api (no
    # expectation, not in the registry). The serial chain is 0.9999 >= 0.999,
    # so the promise is feasible; stripe-api is unknown (spec §11.3, MAY).
    manifest = load(API_CRITICAL)
    registry = ContractRegistry.from_manifests([manifest])
    warnings = validate_transitive_feasibility(manifest, registry)
    assert len(warnings) == 1
    assert "'stripe-api'" in warnings[0]
    assert "unknown availability" in warnings[0]


def _two_contract_provider(directory: Path) -> Path:
    """opensrm/spec/v2/examples/migration/api-full-v2.yaml @0530688 (service
    payment-api, one contract at availability 0.9995), plus a SECOND contract:
    a copy of the first renamed ``payment-api-bulk`` with availability 0.99.
    No spec example declares two contracts; the example's own comment says
    why the list exists: "a service may promise different things on
    different APIs"."""
    data = _read(V2_API_FULL)
    second = copy.deepcopy(data["spec"]["contracts"][0])
    second["name"] = "payment-api-bulk"
    second["promise"]["availability"] = 0.99
    data["spec"]["contracts"].append(second)
    return _write(directory, "payment-api.yaml", data)


# raises=AttributeError: the expected failure is the registry reading generate's
# single `contract`; any other failure (a fixture that no longer loads, say)
# must not hide behind the marker.
def test_multi_contract_provider_is_bounded_by_its_weakest_promise(tmp_path: Path) -> None:
    """Spec §5.2: provider availability is the minimum promise over the
    service's contracts. Promises 0.9995 and 0.99: expecting 99.5% exceeds the
    weaker one (99.0%) though not the stronger (99.95%), so it warns.

    Loaded with nthlayer-common directly: generate's model has a single
    ``contract`` and cannot represent this, so it fails until the registry
    reads ``contracts`` (plan Task 11, which absorbed Task 9). Removing this
    marker when it XPASSes is the one edit Task 11 may make to this file.
    """
    from nthlayer_common.manifest import load_manifest

    provider = load_manifest(_two_contract_provider(tmp_path))
    assert [c.promise.availability for c in provider.contracts] == [0.9995, 0.99]
    registry = ContractRegistry.from_manifests([provider])
    assert registry.has_contract("payment-api")

    consumer = load_manifest(_consumer(tmp_path, [_dep("payment-api", 99.5)]))
    warnings = validate_dependency_expectations(consumer, registry)
    assert len(_exceeds(warnings, "payment-api")) == 1
    assert len(warnings) == 1


# =============================================================================
# G5 — legacy dependencies and the critical-dependency-without-contract check
# =============================================================================
#
# examples/services/payment-api-with-deps.yaml @0331eff (shipped) declares, in
# the legacy Dependencies format (documentation/SCHEMA.md, "Dependencies"):
#   databases: postgres-main (criticality high), redis-cache (medium)
#   services:  auth-service (criticality high)
# Both loaders map criticality critical/high to a critical dependency.
# Spec §6.3 G5: before the switch generate's legacy loader does not read
# `services`; after it, common's does.


def test_legacy_critical_dependencies_without_contract_are_warned() -> None:
    manifest = load(LEGACY_WITH_DEPS)
    warnings = validate_dependency_expectations(manifest, ContractRegistry())

    expected = {"postgres-main", "auth-service"} if SWITCHED else {"postgres-main"}
    warned = {
        d for d in ("postgres-main", "redis-cache", "auth-service") if _no_contract(warnings, d)
    }
    assert warned == expected
    assert len(warnings) == len(expected)


def test_validate_never_runs_contract_checks_on_a_legacy_file() -> None:
    """``validate`` routes only srm/v1 (and, after the switch, v2) to the
    manifest path (specs/validator.py:107-118; spec §5.2 "validator"). A
    legacy file goes through ``parse_service_file`` and gets no dependency or
    contract check on either side of the switch — so G5's "validate
    ('critical dependency has no contract')" entry in spec §6.3 cannot show
    at ``validate``; it shows only where the check runs (test above)."""
    result = validate_service_file(
        LEGACY_WITH_DEPS, contract_registry=ContractRegistry(), validate_filename=False
    )
    # validate really parsed the file. Without this, an early failure would
    # trivially satisfy "no contract warning".
    assert result.valid, result.errors
    assert result.service == "payment-api"
    # At least the file's own resources; its `template: critical-api` adds
    # the template's resources on top.
    assert result.resource_count >= len(_read(LEGACY_WITH_DEPS)["resources"])
    assert not [w for w in result.warnings + result.errors if "contract" in w]


# =============================================================================
# G1 — explicit vs absent SLO `type` in the sloth and dashboard SLI
# =============================================================================
#
# examples/uat/payment-api.reliability.yaml @9e3b2aa declares
# `availability` (type: availability) and `latency-p95` (type: latency).
# Spec §6.3 G1: before the switch an absent type stays None; after it,
# common infers it — and the sloth SLI branch changes "where the name was not
# an exact type (e.g. latency-p95 -> latency branch)". `availability` is an
# exact type name, so it must not change.


def _uat(directory: Path, *, explicit_type: bool) -> Path:
    """examples/uat/payment-api.reliability.yaml @9e3b2aa; queries carried in
    both srm/v1 forms (_with_both_query_forms); with ``explicit_type=False``
    each SLO's ``type:`` line removed."""
    data = _read(UAT_SRM)
    for slo in data["spec"]["slos"].values():
        _with_both_query_forms(slo, slo["query"])
        if not explicit_type:
            del slo["type"]
    name = "explicit" if explicit_type else "absent"
    target = directory / name
    target.mkdir()
    return _write(target, "payment-api.reliability.yaml", data)


def _sloth_slis(path: Path, out: Path) -> dict[str, dict[str, str]]:
    result = generate_sloth_from_manifest(load(path), out)
    assert result.success and result.output_file, result.error
    return {s["name"]: s["sli"]["events"] for s in _read(result.output_file)["slos"]}


def test_sloth_availability_sli_does_not_depend_on_an_explicit_type(tmp_path: Path) -> None:
    explicit = _sloth_slis(_uat(tmp_path, explicit_type=True), tmp_path / "e")
    absent = _sloth_slis(_uat(tmp_path, explicit_type=False), tmp_path / "a")
    assert absent["availability"] == explicit["availability"]

    # Documented availability form (docs-site/commands/generate-slo.md): an
    # events SLI whose total_query is the ratio's denominator.
    query = _read(UAT_SRM)["spec"]["slos"]["availability"]["query"]
    assert explicit["availability"]["total_query"].strip() == query.split("/")[1].strip()


def test_sloth_latency_sli_with_and_without_an_explicit_type(tmp_path: Path) -> None:
    explicit = _sloth_slis(_uat(tmp_path, explicit_type=True), tmp_path / "e")
    absent = _sloth_slis(_uat(tmp_path, explicit_type=False), tmp_path / "a")

    # Sloth's events SLI needs both an error and a total query; the declared
    # latency type gives both.
    assert explicit["latency-p95"]["error_query"]
    assert explicit["latency-p95"]["total_query"]

    if SWITCHED:
        # G1: `latency-p95` is now inferred `latency` — the declared form.
        assert absent["latency-p95"] == explicit["latency-p95"]
    else:
        # Before: no type, so the name is the indicator type, which is not
        # `latency`; the generic branch leaves the error query empty.
        assert absent["latency-p95"]["error_query"] == ""
        assert absent["latency-p95"] != explicit["latency-p95"]


def test_dashboard_slo_panels_do_not_depend_on_an_explicit_type(tmp_path: Path) -> None:
    """The SLO's type reaches the dashboard only as a field the panel builder
    never reads: a panel plots the SLO's declared query
    (documentation/OBSERVABILITY.md, "SLO Panels — auto-generated from SLO
    resources"). So spec §6.3 G1's "dashboard indicator type" change has no
    observable effect, on either side of the switch."""
    explicit = build_dashboard_from_manifest(load(_uat(tmp_path, explicit_type=True)))
    absent = build_dashboard_from_manifest(load(_uat(tmp_path, explicit_type=False)))
    assert absent == explicit

    slos = _read(UAT_SRM)["spec"]["slos"]
    panels = {p.get("title"): p for p in explicit["dashboard"]["panels"]}
    for name, slo in slos.items():
        assert [t["expr"] for t in panels[name]["targets"]] == [slo["query"]]
