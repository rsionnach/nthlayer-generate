"""nthlayer-generate and nthlayer-common must agree on what a service type is.

The divergence this file exists to catch (opensrm-z3ab): generate kept its
own copy of the service-type rule. After opensrm-ih0v made
``spec.service.type`` a first-class field with a six-value enum plus an
``^x-[a-z][a-z0-9-]*$`` extension branch, the two copies disagreed —
generate accepted ``web`` (which schema.json rejects) and rejected
``x-web`` (which schema.json accepts, and which is exactly what
nthlayer-common's alias map now produces from a ``web`` input).

Every suite stayed green throughout, because nothing tested the boundary.
That is the whole point of this module: it is the only place the two
packages' verdicts on the same value are compared. A test that exercises
either side alone cannot see the drift.

Latent at the time of filing — no manifest in the ecosystem declared
``type: web`` — which is why it was worth closing before it bit someone.
"""

from __future__ import annotations

import pathlib

import pytest
from nthlayer_common.manifest.models import (
    SERVICE_TYPE_ALIASES,
    VALID_SERVICE_TYPES,
    resolve_service_type,
)

import nthlayer_generate
from nthlayer_generate.cli.init import SERVICE_TYPES
from nthlayer_generate.specs.manifest import ReliabilityManifest
from nthlayer_generate.specs.validator import validate_service_file

# Values that must behave identically on both sides. Canonical types and
# extension types are valid; aliases resolve; everything else is rejected.
_ACCEPTED = sorted(VALID_SERVICE_TYPES) + ["x-web", "x-ml"] + sorted(SERVICE_TYPE_ALIASES)
# NOT "web": since opensrm-ih0v it is an ALIAS that resolves to x-web, so it
# appears in _ACCEPTED via SERVICE_TYPE_ALIASES. What must be rejected is
# generate STORING it — pinned by test_generate_stores_x_web_for_a_web_input.
_REJECTED = ["ml", "Web", "x-", "x-Web", "nonsense", ""]


@pytest.mark.parametrize("service_type", _ACCEPTED)
def test_generate_accepts_what_common_accepts(service_type: str):
    """Anything nthlayer-common resolves, generate must accept.

    Includes aliases: generate has always accepted them and must keep
    doing so, because they resolve before validation on both sides.
    """
    assert resolve_service_type(service_type) is not None, (
        f"test premise broken: nthlayer-common no longer accepts {service_type!r}"
    )

    manifest = ReliabilityManifest(name="svc", team="t", tier="critical", type=service_type)

    assert manifest.type == resolve_service_type(service_type), (
        f"generate stored {manifest.type!r} for input {service_type!r}, but "
        f"nthlayer-common resolves it to {resolve_service_type(service_type)!r}"
    )


@pytest.mark.parametrize("service_type", _REJECTED)
def test_generate_rejects_what_common_rejects(service_type: str):
    """And the converse — generate must not be WIDER than common either.

    ``ml`` is the live one: cli/init.py offers it in its type menu, and
    neither generate's own validator nor nthlayer-common accepts it. That
    is a separate pre-existing defect (its own bead), but this test pins
    the boundary so closing it cannot silently widen generate.
    """
    assert resolve_service_type(service_type) is None, (
        f"test premise broken: nthlayer-common now accepts {service_type!r}"
    )

    with pytest.raises(ValueError):
        ReliabilityManifest(name="svc", team="t", tier="critical", type=service_type)


def test_generate_stores_x_web_for_a_web_input():
    """The concrete incompatibility, pinned.

    An author writing ``type: web`` gets ``x-web`` from nthlayer-common.
    Generate previously stored ``web`` and then rejected ``x-web``, so a
    manifest that round-tripped through common could not be read back.
    """
    manifest = ReliabilityManifest(name="svc", team="t", tier="critical", type="web")

    assert manifest.type == "x-web"


def test_generate_does_not_store_aliases():
    """Aliases are input conveniences, never stored values.

    generate's specs/models.py listed ``background-job`` and ``pipeline``
    as VALID types rather than merely as aliases, so generate would have
    accepted a manifest that *stored* one — which schema.json rejects and
    nthlayer-common's design explicitly prevents.
    """
    for alias, canonical in SERVICE_TYPE_ALIASES.items():
        manifest = ReliabilityManifest(name="svc", team="t", tier="critical", type=alias)
        assert manifest.type == canonical
        assert manifest.type not in SERVICE_TYPE_ALIASES


@pytest.mark.parametrize("service_type", ["x-web", "worker", "background-job"])
def test_validator_agrees_with_the_manifest_model(tmp_path, service_type: str):
    """The two live validation sites must not disagree with each other.

    specs/validator.py validated against `VALID_SERVICE_TYPES | aliases`
    while specs/manifest.py validated against VALID_SERVICE_TYPES alone —
    two rules in one package, either of which could drift from
    nthlayer-common independently.
    """
    service_file = tmp_path / "svc.yaml"
    service_file.write_text(
        f"service:\n"
        f"  name: svc\n"
        f"  team: t\n"
        f"  tier: critical\n"
        f"  type: {service_type}\n"
        f"resources: []\n"
    )

    result = validate_service_file(service_file)

    type_errors = [e for e in result.errors if "type" in str(e).lower()]
    assert not type_errors, (
        f"validator rejected {service_type!r}, which the manifest model accepts: {type_errors}"
    )


def test_service_context_normalises_its_type():
    """ServiceContext must resolve like ReliabilityManifest does.

    specs/parser.py passes the raw YAML value straight in, and
    ServiceContext did not normalise — so a `type: web` service file
    produced a context holding `web` while every downstream branch was
    updated to test for `x-web`. Web services would have silently lost
    their HTTP dashboard panels (dashboards/validator.py) and their
    latency docs section (generators/docs.py).

    Normalising here rather than teaching each branch both spellings is
    the repo's own hard rule 1: validate inputs at the boundary, not
    inline. Six copies of this rule already exist because the opposite
    was done.
    """
    from nthlayer_generate.specs.models import ServiceContext

    context = ServiceContext(name="svc", team="t", tier="critical", type="web")

    assert context.type == "x-web"


def test_service_context_keeps_an_unresolvable_type_for_the_validator():
    """Resolve-or-keep, never raise.

    Type validity is reported by specs/validator.py as a collected error,
    not by raising at construction. Raising here would turn a reported
    problem into a crash.

    This once justified itself by `ml` being offered in the CLI menu.
    opensrm-8qpd removed it, so no NthLayer entry point produces an
    unresolvable type any more — but ServiceContext is built from parsed
    YAML, and a hand-written manifest may still carry anything at all.
    The path is fed by authors now, not by our own menu.
    """
    from nthlayer_generate.specs.models import ServiceContext

    context = ServiceContext(name="svc", team="t", tier="critical", type="ml")

    assert context.type == "ml"


# =============================================================================
# cli/init.py — resolve ONCE, at the top
# =============================================================================


@pytest.mark.parametrize("menu_type", ["web", "x-web", "api"])
def test_init_emits_latency_slo_for_http_service_types(menu_type: str):
    """A silent output regression, not a validation one (opensrm-z3ab R5).

    opensrm-z3ab retargeted _build_resources_yaml's branch from
    ``("api", "web")`` to ``("api", "x-web")``, but only the ``type:``
    interpolation was resolved — every other consumer of ``service_type``
    in _generate_service_yaml_v2 still saw the raw menu value. So
    ``nthlayer init --type web`` emitted a manifest typed ``x-web`` with
    an availability SLO and NO latency SLO.

    Nothing caught it because the output is still VALID: a manifest may
    legitimately have no latency SLO. Only asserting on the generated
    content catches a resource silently going missing.

    Parametrised over both spellings because both must reach the same
    branch — that is the whole point of resolving once at the top rather
    than at each use site.
    """
    from nthlayer_generate.cli.init import _generate_service_yaml_v2

    yaml_out = _generate_service_yaml_v2("shop", "team", "critical", menu_type, [])

    assert "latency-p95" in yaml_out, f"--type {menu_type} produced a manifest with no latency SLO"


def test_manifest_module_re_exports_the_whole_rule():
    """specs/manifest.py is the import path consumers already use, so all
    three parts of the rule must be reachable from it — the two sets and
    the predicate that actually decides.

    Asserted by importing, not by inspecting ``__all__``: this module does
    not declare one, so an ``__all__``-based check would pass vacuously
    while the symbols were missing.
    """
    from nthlayer_generate.specs.manifest import (
        SERVICE_TYPE_ALIASES,
        VALID_SERVICE_TYPES,
        ReliabilityManifest,
        is_valid_service_type,
    )

    assert is_valid_service_type("x-web")
    assert "web" not in VALID_SERVICE_TYPES
    assert SERVICE_TYPE_ALIASES["web"] == "x-web"
    assert ReliabilityManifest is not None


# =============================================================================
# ${type} is a data-plane value, not a manifest field
# =============================================================================


@pytest.mark.parametrize("authored", ["web", "background-job", "pipeline", "api"])
def test_type_template_variable_keeps_the_authored_spelling(authored: str):
    """``${type}`` substitutes into user-authored PromQL, so it must not be
    silently renormalised (opensrm-z3ab R5 edge cases).

    ServiceContext.to_dict feeds template substitution, and normalising
    self.type meant an existing service.yaml with ``type: web`` and a query
    matching ``svc_type="${type}"`` began generating ``svc_type="x-web"``.
    That matcher selects ZERO series against the Prometheus the author
    already runs, so the SLO reads no-data and its burn-rate alerts never
    fire.

    Nothing catches it: the generated rules are still schema-valid and still
    parse. It is the same shape as the latency-SLO regression this bead's
    correctness pass found — valid output, wrong content, silent at runtime.

    The authored spelling is a label matcher against live data. It is not
    ours to rewrite.
    """
    from nthlayer_generate.specs.models import Resource, ServiceContext
    from nthlayer_generate.specs.parser import render_resource_spec

    context = ServiceContext(name="shop", team="t", tier="critical", type=authored)
    resource = Resource(
        kind="SLO",
        name="availability",
        spec={"query": 'sum(rate(http_total{svc_type="${type}"}[5m]))'},
        context=context,
    )

    rendered = render_resource_spec(resource)

    assert f'svc_type="{authored}"' in rendered["query"], (
        f"${{type}} rendered as {rendered['query']!r}; the authored spelling "
        f"{authored!r} must survive into the query"
    )


def test_context_still_exposes_the_resolved_type_for_branching():
    """The resolved value is what internal branches compare against — that
    is why ServiceContext normalises at all. Both must be available: the
    resolved one for code, the authored one for substitution."""
    from nthlayer_generate.specs.models import ServiceContext

    context = ServiceContext(name="s", team="t", tier="critical", type="web")

    assert context.type == "x-web"
    assert context.to_dict()["type"] == "web"


@pytest.mark.parametrize("authored", ["web", "background-job", "api"])
def test_sloth_indicator_query_keeps_the_authored_type(tmp_path, authored: str):
    """The same data-plane rule, exercised through sloth itself.

    generators/sloth.py substitutes ``${type}`` into an SLO's
    indicator_query, which becomes a Sloth spec and then recording rules
    and burn-rate alerts. That one substitution is the line this bead
    changed, so the test drives the real generator rather than asserting
    on the dataclass — an earlier version of this test constructed a
    manifest and checked ``authored_type``, which duplicated coverage
    above and left sloth.py itself untested.
    """
    from nthlayer_generate.generators.sloth import generate_sloth_from_manifest
    from nthlayer_generate.specs.manifest import ReliabilityManifest, SLODefinition

    manifest = ReliabilityManifest(
        name="shop",
        team="t",
        tier="critical",
        type=authored,
        slos=[
            SLODefinition(
                name="availability",
                slo_type="availability",
                target=99.9,
                indicator_query='sum(rate(http_total{svc_type="${type}"}[5m]))',
            )
        ],
    )

    result = generate_sloth_from_manifest(manifest, tmp_path)

    assert result.success and result.output_file, f"sloth generation failed: {result.error}"
    rendered = result.output_file.read_text()

    assert f'svc_type="{authored}"' in rendered, (
        f"sloth rendered {authored!r} as something else; the authored "
        f"spelling must survive into the SLI query"
    )


def test_authored_type_survives_manifest_to_context_conversion():
    """The manifest -> context hop must not re-derive the authored spelling.

    as_service_context() / to_service_context() built a ServiceContext from
    the RESOLVED type, so authored_type was recomputed from `x-web` and the
    authored `web` was destroyed — reopening the zero-series matcher bug on
    exactly the path specs/loader.py:load_as_legacy uses.
    """
    from nthlayer_generate.specs.manifest import ReliabilityManifest

    manifest = ReliabilityManifest(name="shop", team="t", tier="critical", type="web")

    assert manifest.authored_type == "web"
    assert manifest.as_service_context().authored_type == "web"
    assert manifest.to_service_context()["type"] == "web"


def test_authored_type_survives_dataclasses_replace():
    """authored_type must be a declared field, not an attribute set in
    __post_init__.

    As an undeclared attribute it was silently recomputed by
    dataclasses.replace() — so replacing an unrelated field like tier
    reverted the authored spelling to the resolved one.
    """
    import dataclasses

    from nthlayer_generate.specs.models import ServiceContext

    context = ServiceContext(name="s", team="t", tier="critical", type="web")

    assert dataclasses.replace(context, tier="high").authored_type == "web"


# =============================================================================
# The CLI menu is the manifest vocabulary — opensrm-8qpd
# =============================================================================
#
# Settling the question opensrm-z3ab deferred: cli/init.py kept a THIRD
# service-type vocabulary, agreeing with neither nthlayer-common nor
# generate's own validator, and offered `ml` — a value generate then
# rejected.
#
# The decision: the menu's keys ARE the values a manifest stores. Nothing
# translates. These are never typed — SERVICE_TYPES renders as
# `key - description` in an interactive list — so the spec spelling costs a
# menu user nothing, and the friendly wording lives in the description
# beside it, where it always did.


def test_the_menu_offers_only_values_a_manifest_can_store():
    """Every menu key must resolve to ITSELF, not merely resolve.

    Identity, not validity, is the invariant: an alias like `web` resolves
    fine but lands in the file spelled `x-web`, so the user is shown one
    word and given another. That mismatch is the confusion this bead
    exists to remove, and only identity catches it.
    """
    for menu_type in SERVICE_TYPES:
        assert resolve_service_type(menu_type) == menu_type, (
            f"menu entry {menu_type!r} is not a storable service type: it "
            f"resolves to {resolve_service_type(menu_type)!r}"
        )


def test_the_menu_offers_every_service_type_the_spec_defines():
    """And the converse — the menu must not be NARROWER than the spec.

    `ai-gate` and `database` were absent from the menu for as long as it
    existed, so `nthlayer init` could not produce either, despite both
    being among the six values OpenSRM v2 defines. A menu that silently
    omits a spec type is the same defect as one that invents a type,
    pointed the other way.
    """
    missing = VALID_SERVICE_TYPES - set(SERVICE_TYPES)
    assert not missing, f"menu does not offer spec service types: {sorted(missing)}"


def test_ml_is_dropped_from_the_menu_rather_than_mapped():
    """`ml` is ambiguous by construction, so it is removed, not translated.

    An ML service that MAKES decisions is an `ai-gate`; one that serves
    inference over HTTP is an `api`. The CLI cannot tell which, and
    guessing `ai-gate` would recreate the exact inversion opensrm-6w9d and
    opensrm-ih0v spent two beads eliminating. Pinned as its own test so a
    later "helpful" alias has to delete this reasoning to land.
    """
    assert "ml" not in SERVICE_TYPES


@pytest.mark.parametrize("menu_type", sorted(SERVICE_TYPES))
def test_every_menu_entry_generates_a_manifest_that_validates(tmp_path, menu_type: str):
    """The bead's acceptance criterion, over the FULL menu, not spot-checks.

    Spot-checking is how `ml` survived: every type anyone thought to test
    was one of the valid ones.

    On `spec/v2/validate.sh`: generate's CI installs nthlayer-common from
    PyPI and has no `opensrm/` checkout, so a schema.json test here would
    `pytest.skip` in exactly the environment meant to gate the merge —
    green because it never ran. `is_valid_service_type` is documented as
    the ECMA-262-parity mirror of schema.json's ServiceType (it uses
    fullmatch precisely so the two cannot disagree about `x-web\\n`), so
    asserting through nthlayer-common is equivalent for this field and
    always runs.
    """
    from nthlayer_generate.cli.init import _generate_service_yaml_v2

    service_file = tmp_path / "svc.yaml"
    service_file.write_text(_generate_service_yaml_v2("svc", "t", "critical", menu_type, []))

    result = validate_service_file(service_file)

    type_errors = [e for e in result.errors if "type" in str(e).lower()]
    assert not type_errors, f"menu entry {menu_type!r} generated an invalid manifest: {type_errors}"
    assert f"type: {menu_type}\n" in service_file.read_text(), (
        f"menu entry {menu_type!r} did not survive into the manifest verbatim"
    )


# =============================================================================
# Templates share that one vocabulary — opensrm-8qpd
# =============================================================================


@pytest.mark.parametrize(
    ("declared", "stored"),
    [("background-job", "worker"), ("pipeline", "batch"), ("web", "x-web"), ("api", "api")],
)
def test_a_template_resolves_its_type_exactly_as_a_manifest_does(declared: str, stored: str):
    """ServiceTemplate had its own `valid_types` list — a second vocabulary.

    It accepted `background-job` and `pipeline`, which are manifest
    ALIASES rather than manifest types, and rejected `worker`, `stream`
    and `ai-gate`, which are types. Resolving at construction, as
    ReliabilityManifest does, makes the two one vocabulary — which is what
    makes init.py's template-derived fallback safe by construction rather
    than by a guard at the write site.
    """
    from nthlayer_generate.specs.templates import ServiceTemplate

    template = ServiceTemplate(
        name="t", description="probe", tier="critical", type=declared, resources=[]
    )

    assert template.type == stored


@pytest.mark.parametrize("service_type", ["worker", "stream", "ai-gate", "database", "x-web"])
def test_a_template_may_declare_any_manifest_service_type(service_type: str):
    """The old `valid_types` list rejected three of the spec's six types.

    So a template for a worker, a stream processor or an AI gate could not
    be written at all — including by the custom-template loader, which
    users point at their own YAML.
    """
    from nthlayer_generate.specs.templates import ServiceTemplate

    template = ServiceTemplate(
        name="t", description="probe", tier="critical", type=service_type, resources=[]
    )

    assert template.type == service_type


def test_a_template_still_rejects_a_type_no_manifest_could_store():
    """Widening the accepted set must not mean accepting anything."""
    from nthlayer_generate.specs.templates import ServiceTemplate

    with pytest.raises(ValueError):
        ServiceTemplate(name="t", description="probe", tier="critical", type="ml", resources=[])


def test_built_in_templates_declare_types_a_manifest_can_store():
    """init_command takes `service_type = template_obj.type` when no type
    was chosen, so a template's type becomes a manifest's type directly.

    That is the bead's "second path": `background-job.yaml` and
    `pipeline.yaml` both declare manifest aliases on disk, which
    schema.json rejects. They must arrive resolved.

    Asserted against the RAW YAML, not against loaded ServiceTemplates.
    Loading them and checking `resolve_service_type(t.type) == t.type`
    cannot fail — __post_init__ enforces exactly that, so every object
    that exists already satisfies it. The real failure mode is a template
    that does not load at all: TemplateLoader.load_builtin swallows
    per-file exceptions, so a bad declaration shows up as an ABSENT
    template, which a check over whatever loaded would never see.

    Uses load_builtin(), not load_all_templates(): the latter walks
    ancestor directories for a gitignored `.nthlayer/templates`, so from a
    developer's checkout it silently pulls in untracked local templates and
    the test stops being about this repo's contents.
    """
    import yaml

    from nthlayer_generate.specs.template_loader import TemplateLoader

    template_dir = pathlib.Path(nthlayer_generate.__file__).parent / "specs" / "builtin_templates"
    yaml_files = sorted(template_dir.glob("*.yaml"))
    assert yaml_files, f"test premise broken: no built-in templates at {template_dir}"

    declared_names = set()
    for path in yaml_files:
        data = yaml.safe_load(path.read_text())
        declared = data.get("type")
        assert resolve_service_type(declared) is not None, (
            f"{path.name} declares type {declared!r}, which no manifest can store"
        )
        declared_names.add(data.get("name"))

    # And every one of them actually loaded — an unresolvable declaration
    # would be swallowed into absence rather than raised.
    #
    # Compared against the names the YAML DECLARES, not the file stems:
    # keying on stems would quietly pin a name==filename convention this
    # test has no opinion on, and renaming a template inside its own file
    # would then be reported as "one failed to load" when none did.
    registry = TemplateLoader.load_builtin()
    assert set(registry.templates) == declared_names, (
        f"built-in templates on disk {sorted(declared_names)} do not match "
        f"those loaded {sorted(registry.templates)} — one failed to load"
    )
    for template in registry.list():
        assert resolve_service_type(template.type) == template.type


def test_resolving_a_template_type_is_idempotent():
    """__post_init__ mutates self.type, so constructing a template FROM
    another's type must be a fixed point.

    init_command does exactly that round trip — `template_obj.type` becomes
    `service_type`, which _resolve_manifest_type then resolves a second
    time. That is only safe while no alias key is itself a canonical value,
    an invariant owned by nthlayer-common, not by this repo. Pinned here
    because this repo is what breaks if it changes.
    """
    from nthlayer_generate.specs.templates import ServiceTemplate

    for declared in list(SERVICE_TYPE_ALIASES) + sorted(VALID_SERVICE_TYPES):
        once = ServiceTemplate(
            name="t", description="p", tier="critical", type=declared, resources=[]
        ).type
        twice = ServiceTemplate(
            name="t", description="p", tier="critical", type=once, resources=[]
        ).type
        assert once == twice, f"{declared!r} resolved to {once!r} then {twice!r}"


def test_the_translation_table_is_gone():
    """SERVICE_TYPE_TO_TEMPLATE_TYPE is deleted, not merely unused.

    A guard, not a behaviour test — it asserts a symbol's absence so the
    table cannot quietly come back as a "convenience" while the filter
    still reads as plain equality. The behaviour it used to stand for is
    covered by test_selecting_a_type_with_no_template_offers_none in
    tests/test_init.py, which drives the filter through init_command.

    Retired alongside it: test_template_vocabulary_round_trips_with_the_
    init_filter, which pinned that the two vocabularies agreed with each
    other. There is now one.
    """
    from nthlayer_generate.cli import init

    assert not hasattr(init, "SERVICE_TYPE_TO_TEMPLATE_TYPE")
