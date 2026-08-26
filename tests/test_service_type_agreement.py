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
