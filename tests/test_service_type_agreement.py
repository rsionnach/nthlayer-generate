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

import pytest
from nthlayer_common.manifest.models import (
    SERVICE_TYPE_ALIASES,
    VALID_SERVICE_TYPES,
    resolve_service_type,
)

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
        f"validator rejected {service_type!r}, which the manifest model "
        f"accepts: {type_errors}"
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
    problem into a crash — and `ml` is currently offered by the CLI menu
    (opensrm-8qpd), so this path is live.
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

    assert "latency-p95" in yaml_out, (
        f"--type {menu_type} produced a manifest with no latency SLO"
    )


def test_init_writes_a_resolved_type_for_every_menu_entry():
    """Whatever the menu offers, the file must carry a resolved value.

    `ml` is the exception and is deliberately left alone (opensrm-8qpd) —
    it resolves to nothing, so it is written raw and stays loudly invalid
    rather than being silently mapped to something plausible.
    """
    from nthlayer_common.manifest.models import resolve_service_type

    from nthlayer_generate.cli.init import SERVICE_TYPES, _generate_service_yaml_v2

    for menu_type in SERVICE_TYPES:
        resolved = resolve_service_type(menu_type)
        if resolved is None:
            continue  # opensrm-8qpd
        yaml_out = _generate_service_yaml_v2("s", "t", "critical", menu_type, [])
        type_line = next(
            line.strip() for line in yaml_out.splitlines() if line.strip().startswith("type:")
        )
        assert type_line == f"type: {resolved}", (
            f"menu entry {menu_type!r} wrote {type_line!r}, expected type: {resolved}"
        )


def test_template_vocabulary_round_trips_with_the_init_filter():
    """specs/templates.py and cli/init.py must agree on TEMPLATE types.

    These are a separate vocabulary from manifest service types — the table
    also carries `background-job` and `pipeline`, which are manifest aliases,
    not manifest types. opensrm-z3ab half-migrated it, changing only the
    `web` entry to `x-web`, which broke both ends: a custom template
    declaring `type: web` stopped loading, and one declaring `x-web` was
    never matched, because SERVICE_TYPE_TO_TEMPLATE_TYPE still maps the menu
    entry to `"web"`.

    Whatever the table accepts must be what the filter looks for. Settling
    which vocabulary it should use at all is opensrm-8qpd.
    """
    from nthlayer_generate.cli.init import SERVICE_TYPE_TO_TEMPLATE_TYPE
    from nthlayer_generate.specs.templates import ServiceTemplate

    for template_type in set(SERVICE_TYPE_TO_TEMPLATE_TYPE.values()):
        # A template declaring the type init will search for must construct.
        ServiceTemplate(
            name=f"t-{template_type}",
            description="probe",
            tier="critical",
            type=template_type,
            resources=[],
        )


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
