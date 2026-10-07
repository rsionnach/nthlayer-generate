"""CLI command for initializing new NthLayer services."""

import json
import re
from pathlib import Path

from nthlayer_common.manifest.models import resolve_service_type

from nthlayer_generate.cli.ux import (
    console,
    error,
    header,
    info,
    multi_select,
    select,
    success,
    text_input,
    warning,
)
from nthlayer_generate.core.tiers import TIER_CONFIGS
from nthlayer_generate.specs.custom_templates import CustomTemplateLoader
from nthlayer_generate.specs.manifest import is_valid_service_name

# The service-type menu. INVARIANT: every key is a value a manifest can
# store verbatim — nothing here is translated on the way out (opensrm-8qpd).
#
# The friendly wording is the description beside each key, never the key
# itself. These are never typed: the menu renders as `key - description` in
# an interactive list, so the spec spelling costs the user nothing, while a
# key of `web` against a file saying `x-web` would cost them a translation.
#
# There is deliberately no `ml` entry and no alias for one: an ML service
# that makes decisions is an `ai-gate`, one serving inference over HTTP is
# an `api`, and nothing here knows which.
SERVICE_TYPES = {
    "api": "REST/GraphQL API service",
    "worker": "Background job processor",
    "stream": "Stream processing service (Kafka, etc.)",
    "batch": "Batch processing job",
    "database": "Managed datastore or data service",
    "ai-gate": "AI/LLM service that makes or gates decisions",
    "x-web": "Web application (frontend) - NthLayer extension type",
}

# Tier descriptions derived from centralized config
TIERS = {name: config.display_name for name, config in TIER_CONFIGS.items()}

# Common dependencies
DEPENDENCIES = [
    "postgresql",
    "mysql",
    "redis",
    "mongodb",
    "elasticsearch",
    "kafka",
    "rabbitmq",
    "dynamodb",
]


def init_command(
    service_name: str | None = None,
    team: str | None = None,
    template: str | None = None,
    interactive: bool = True,
) -> int:
    """Initialize new NthLayer service.

    Creates a service YAML file from template and sets up project structure.

    Args:
        service_name: Service name (lowercase-with-hyphens)
        team: Team name
        template: Template name (critical-api, standard-api, etc.)
        interactive: Whether to prompt for missing values

    Returns:
        Exit code (0 for success, 1 for error)
    """
    header("Initialize NthLayer Service")
    console.print()
    if interactive:
        console.print("[muted]Create a new <service-name>.yaml with interactive prompts[/muted]")
    else:
        console.print("[muted]Create a new <service-name>.yaml from the given flags[/muted]")
    console.print()

    # Load templates (built-in + custom)
    try:
        registry = CustomTemplateLoader.load_all_templates()
    except Exception as e:
        error(f"Error loading templates: {e}")
        return 1

    # Interactive prompts using questionary/gum
    if not service_name and interactive:
        service_name = text_input(
            "Service name",
            placeholder="lowercase-with-hyphens (e.g., payment-api)",
        )

    if not service_name:
        error("Service name is required")
        if not interactive:
            console.print(
                "   [muted]Pass it as the first argument: nthlayer init <service-name>[/muted]"
            )
        return 1

    # Validate service name format
    if not _is_valid_service_name(service_name):
        error(f"Invalid service name '{service_name}'")
        console.print(
            "   [muted]Service name must be lowercase with hyphens (e.g., payment-api)[/muted]"
        )
        return 1

    if not team and interactive:
        team = text_input("Team name", placeholder="e.g., platform, payments")

    if not team:
        error("Team name is required")
        if not interactive:
            console.print("   [muted]Pass it with --team <team>[/muted]")
        return 1

    if not _is_valid_team(team):
        error("Invalid team name")
        console.print(
            "   [muted]Team name must not contain line breaks, tabs or control "
            "characters[/muted]"
        )
        return 1

    # Select service tier using interactive menu
    tier = None
    if interactive:
        tier_choices = [f"{k} - {v}" for k, v in TIERS.items()]
        selected_tier = select("Service tier", tier_choices, default=tier_choices[1])
        tier = selected_tier.split(" - ")[0]

    # Select service type using interactive menu
    service_type = None
    if interactive:
        type_choices = [f"{k} - {v}" for k, v in SERVICE_TYPES.items()]
        selected_type = select("Service type", type_choices, default=type_choices[0])
        service_type = selected_type.split(" - ")[0]

    # Select dependencies using multi-select
    dependencies = []
    if interactive:
        console.print()
        console.print(
            "[muted]Select service dependencies (space to toggle, enter to confirm)[/muted]"
        )
        dependencies = multi_select("Dependencies", DEPENDENCIES)

    # Template selection (optional - filter by service type if selected)
    if not template and interactive:
        templates = registry.list()
        # Filter templates by service type if one was selected
        if service_type and templates:
            # Plain equality: ServiceTemplate resolves its declared type
            # through the same rule a manifest does, so both sides of this
            # comparison are already canonical (opensrm-8qpd).
            templates = [t for t in templates if t.type == service_type]
        if templates:
            template_choices = [f"{t.name} - {t.description}" for t in templates]
            template_choices.insert(0, "none - Generate from selections above")
            selected = select("Use template?", template_choices)
            if not selected.startswith("none"):
                template = selected.split(" - ")[0]

    # Get template object if specified
    template_obj = None
    if template:
        if not registry.exists(template):
            error(f"Unknown template '{template}'")
            console.print(
                f"   [muted]Available templates: {', '.join(registry.templates.keys())}[/muted]"
            )
            return 1
        template_obj = registry.get(template)
        # Use template's tier and type if not explicitly selected
        if template_obj:
            if not tier:
                tier = template_obj.tier
            if not service_type:
                service_type = template_obj.type

    # Default values if still not set
    tier = tier or "standard"
    service_type = service_type or "api"

    # Create service file
    service_file = Path(f"{service_name}.yaml")
    if service_file.exists():
        console.print()
        error(f"{service_file} already exists")
        console.print(
            "   [muted]Remove the existing file or choose a different service name[/muted]"
        )
        return 1

    # Generate service YAML content
    service_content = _generate_service_yaml_v2(
        service_name, team, tier, service_type, dependencies, template_obj
    )

    try:
        service_file.write_text(service_content)
    except OSError as e:
        error(f"Error creating service file: {e}")
        return 1

    # Create .nthlayer directory
    nthlayer_dir = Path(".nthlayer")
    try:
        nthlayer_dir.mkdir(exist_ok=True)
    except OSError as e:
        warning(f"Could not create .nthlayer directory: {e}")

    # Create config file if it doesn't exist
    config_file = nthlayer_dir / "config.yaml"
    if not config_file.exists():
        config_content = _generate_config_yaml()
        try:
            config_file.write_text(config_content)
        except OSError as e:
            warning(f"Could not create config file: {e}")

    # Success message
    console.print()
    success(f"Created {service_file}")
    # is_dir(), NOT exists() (opensrm-t4rd). If .nthlayer is a regular FILE,
    # mkdir raises FileExistsError and the config write raises
    # NotADirectoryError; both are OSError, so both were downgraded to warnings
    # above. exists() is then True *because it is a file*, so init printed
    # "Created .nthlayer/" for a directory it had not created and returned 0.
    if nthlayer_dir.is_dir():
        success(f"Created {nthlayer_dir}/")
    else:
        # NOT fatal, including under --no-interactive. Decided deliberately
        # (opensrm-t4rd acceptance): the manifest is the primary artifact and it
        # was written correctly, so a CI gate keying on the exit code is right to
        # pass. What was wrong before was claiming the directory had been created;
        # the warning below states plainly that it was not, and names the fix.
        # Making it fatal would fail runs whose manifest is perfectly good merely
        # because .nthlayer could not be created (read-only parent, a stray file).
        warning(
            f"{nthlayer_dir}/ was not created — config was not written. "
            f"Remove or rename the existing {nthlayer_dir} entry and re-run."
        )

    console.print()
    console.print("[bold]Next steps:[/bold]")
    console.print(f"  [muted]1.[/muted] Review {service_file} and customize if needed")
    console.print(f"  [muted]2.[/muted] Validate: [info]nthlayer validate {service_file}[/info]")
    console.print(
        f"  [muted]3.[/muted] Generate SLOs: [info]nthlayer generate-slo {service_file}[/info]"
    )
    console.print(
        f"  [muted]4.[/muted] Setup PagerDuty: "
        f"[info]nthlayer setup-pagerduty {service_file} --api-key YOUR_KEY[/info]"
    )
    console.print()
    info("Pro tip: Run 'nthlayer --help' to see all commands")

    return 0


_PLAIN_SCALAR_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._-]*")


def _yaml_scalar(value: str) -> str:
    """Render *value* as a YAML scalar that cannot alter the document.

    Quoted only when it has to be, so the common case stays readable and the
    documented example output in docs-site stays byte-identical to what init
    actually writes (``test_block_is_byte_identical_to_real_output`` pins that,
    and it is the docs-vs-reality guard from opensrm-noc6 — worth not breaking
    for cosmetics).

    When quoting IS needed, ``json.dumps`` is used: a JSON string is also a valid
    YAML double-quoted scalar, and it escapes the two characters that made raw
    interpolation dangerous — ``:`` becomes quoted, and a newline becomes a
    literal ``\n`` rather than starting a new YAML line.

    This is generate's hard rule 5 (no raw string construction for generated
    output) applied at the one input that is scriptable and unvalidated
    (opensrm-t4rd). Measured before the fix, all exiting 0:
      --team 'Platform: Core'            -> the manifest failed to parse
      --team $'ops\nname: hijacked'      -> injected a second service.name
      --team $'ops\ntier: critical'      -> manifest VALIDATED CLEAN carrying a
                                            bogus tier shadowed by the real one
    A colon in a team name is ordinary, so quoting must be available, not
    optional.

    The allowlist is deliberately narrow: anything outside
    ``[A-Za-z0-9][A-Za-z0-9 ._-]*`` is quoted rather than reasoned about. That
    excludes every YAML indicator character (``:`` ``#`` ``-`` at the start,
    ``{`` ``[`` ``&`` ``*`` ``!`` ``|`` ``>`` ``%`` ``@`` `` ` ``), leading and
    trailing whitespace, and anything non-ASCII.
    """
    if _PLAIN_SCALAR_RE.fullmatch(value):
        return value
    return json.dumps(value)


def _is_valid_team(team: str) -> bool:
    """True if *team* is free of control characters.

    Quoting alone makes the document safe, so this is not what prevents
    injection — it is what turns a newline in --team into a clear error instead
    of a silently escaped ``\n`` in the output. A team name spanning lines is a
    mistake every time.
    """
    return bool(team.strip()) and not any(ch in team for ch in "\n\r\t\x00")


def _is_valid_service_name(name: str) -> bool:
    """Delegates to the one service-name rule (opensrm-t4rd).

    Kept as a thin wrapper rather than deleted: tests and callers import this
    name. The body it replaced looped over ``char.islower() or char.isdigit()``
    — UNICODE predicates — and rejected only a leading or trailing hyphen, so it
    accepted `1-svc`, `café` and fullwidth `ａbc`, all of which
    specs/validator.py then refused. `init` exited 0 having written a manifest
    its own validator rejects, and the exit code is what a CI gate keys on.
    """
    return is_valid_service_name(name)


def _generate_service_yaml_v2(
    service_name: str,
    team: str,
    tier: str,
    service_type: str,
    dependencies: list[str],
    template=None,
) -> str:
    """Generate service YAML content with all parameters.

    Args:
        service_name: Service name
        team: Team name
        tier: Service tier (critical, standard, low)
        service_type: Service type (api, worker, stream, etc.)
        dependencies: List of dependency names
        template: Optional ServiceTemplate object

    Returns:
        YAML content as string
    """
    # Resolve ONCE, here, so every consumer below sees the same spelling.
    service_type = _resolve_manifest_type(service_type)

    # Build resources section
    resources_yaml = _build_resources_yaml(service_name, tier, service_type, dependencies)

    # Template line if using a template
    template_line = f"  template: {template.name}\n" if template else ""

    return f"""# {service_name} Service Definition
# Generated by NthLayer

service:
  name: {service_name}
  team: {_yaml_scalar(team)}
  tier: {tier}
  type: {service_type}
{template_line}
resources:
{resources_yaml}
"""


def _resolve_manifest_type(service_type: str) -> str:
    """Resolve an authored type to the value a manifest may store.

    Since opensrm-8qpd the menu and the template registry both supply
    already-canonical values, so for them this is identity. It stays as the
    boundary guard for the one input that is not canonical by construction:
    a `service_type` argument passed straight to _generate_service_yaml_v2,
    which today means the tests and, if opensrm-noc6 adds it, `--type`.

    Resolving once here is hard rule 1 — the alternative is every consumer
    below _generate_service_yaml_v2 learning both spellings, which is the
    regression opensrm-z3ab's correctness pass found when only the `type:`
    interpolation was resolved and the latency-SLO branch was not.

    Falls back to the raw value when it does not resolve, so an
    unresolvable type fails loudly at validation rather than being silently
    mapped to something plausible.
    """
    return resolve_service_type(service_type) or service_type


def _build_resources_yaml(
    service_name: str,
    tier: str,
    service_type: str,
    dependencies: list[str],
) -> str:
    """Build the resources YAML section.

    Args:
        service_name: Service name
        tier: Service tier
        service_type: Service type
        dependencies: List of dependency names

    Returns:
        YAML content for resources
    """
    resources = []

    # Add SLO based on tier
    if tier == "critical":
        resources.append(
            """  # Availability SLO - critical tier
  - kind: SLO
    name: availability
    spec:
      objective: 99.95
      window: 30d
      indicator:
        type: availability"""
        )
    else:
        resources.append(
            """  # Availability SLO
  - kind: SLO
    name: availability
    spec:
      objective: 99.9
      window: 30d
      indicator:
        type: availability"""
        )

    # Add latency SLO for API types
    if service_type in ("api", "x-web"):
        resources.append(
            """
  # Latency SLO - p95
  - kind: SLO
    name: latency-p95
    spec:
      objective: 99.0
      window: 30d
      indicator:
        type: latency
        percentile: 95
        threshold_ms: 500"""
        )

    # Add PagerDuty for critical tier
    if tier == "critical":
        resources.append(
            """
  # PagerDuty integration
  - kind: PagerDuty
    name: primary
    spec:
      urgency: high
      auto_create: true"""
        )

    # Add dependencies if selected
    if dependencies:
        db_deps = [d for d in dependencies if d in ("postgresql", "mysql", "mongodb", "dynamodb")]
        cache_deps = [d for d in dependencies if d in ("redis", "elasticsearch")]
        queue_deps = [d for d in dependencies if d in ("kafka", "rabbitmq")]

        deps_yaml = """
  # Service dependencies
  - kind: Dependencies
    name: infrastructure
    spec:"""

        if db_deps:
            deps_yaml += "\n      databases:"
            for db in db_deps:
                deps_yaml += f"""
        - name: {service_name}-{db}
          type: {db}
          criticality: high"""

        if cache_deps:
            deps_yaml += "\n      caches:"
            for cache in cache_deps:
                deps_yaml += f"""
        - name: {service_name}-{cache}
          type: {cache}
          criticality: medium"""

        if queue_deps:
            deps_yaml += "\n      queues:"
            for queue in queue_deps:
                deps_yaml += f"""
        - name: {service_name}-{queue}
          type: {queue}
          criticality: high"""

        resources.append(deps_yaml)

    return "\n".join(resources)


def _generate_service_yaml(service_name: str, team: str, template) -> str:
    """Generate service YAML content (legacy).

    Args:
        service_name: Service name
        team: Team name
        template: ServiceTemplate object

    Returns:
        YAML content as string
    """
    return f"""# {service_name} Service Definition
# Generated by NthLayer

service:
  name: {service_name}
  team: {_yaml_scalar(team)}
  tier: {template.tier}     # critical | standard | low
  type: {template.type}     # api | worker | stream | batch | database | ai-gate | x-web
  template: {template.name}

# Template provides:
{_format_template_resources(template)}

# Optional: Override template defaults or add new resources
# resources:
#   - kind: SLO
#     name: latency-p95
#     spec:
#       threshold_ms: 300  # Override template default
#
#   - kind: Dependencies
#     name: upstream
#     spec:
#       services:
#         - name: user-service
#           criticality: high
"""


def _format_template_resources(template) -> str:
    """Format template resources as comments.

    Args:
        template: ServiceTemplate object

    Returns:
        Formatted comment block
    """
    lines = []
    for resource in template.resources:
        lines.append(f"#   - {resource.kind}: {resource.name}")
    return "\n".join(lines) if lines else "#   (no resources)"


def _generate_config_yaml() -> str:
    """Generate .nthlayer/config.yaml content.

    Returns:
        YAML content as string
    """
    return """# NthLayer Configuration
# This file configures project-wide settings for NthLayer

# Error budget configuration
error_budgets:
  # Enable inherited impact attribution (enterprise feature)
  # When true, attributes error budget burn to upstream service failures
  inherited_attribution: false

  # Minimum correlation confidence for attribution (0.0 to 1.0)
  min_correlation_confidence: 0.8

  # Time window for correlating incidents and deployments (minutes)
  time_window_minutes: 5

# Deployment gate thresholds (optional overrides)
# deployment_gates:
#   critical:
#     block_threshold: 0.10   # Block deploys if >10% budget consumed
#     warn_threshold: 0.20    # Warn if >20% consumed
#   standard:
#     warn_threshold: 0.20
"""
