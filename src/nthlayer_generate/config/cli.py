"""
CLI commands for configuration and secrets management.

Commands:
    nthlayer config show          - Show current configuration
    nthlayer config set KEY VALUE - Set a configuration value
    nthlayer config init          - Interactive setup wizard
    nthlayer secrets list         - List available secrets
    nthlayer secrets verify       - Verify required secrets exist
    nthlayer secrets set PATH     - Set a secret
"""

from __future__ import annotations

import getpass
from pathlib import Path

from nthlayer_generate.config.integrations import (
    GrafanaProfile,
    GrafanaType,
    IntegrationConfig,
    PrometheusProfile,
    PrometheusType,
)
from nthlayer_generate.config.loader import (
    ConfigLoadError,
    get_config_path,
    load_config,
    save_config,
)
from nthlayer_generate.config.secrets import (
    SecretBackend,
    get_secret_resolver,
)

REQUIRED_SECRETS = [
    "grafana/api_key",
    "prometheus/password",
    "pagerduty/api_key",
    "slack/webhook_url",
]


def config_show_command(reveal_secrets: bool = False) -> int:
    """Show current configuration."""
    config_path = get_config_path()
    
    print("=" * 60)
    print("  NthLayer Configuration")
    print("=" * 60)
    print()
    
    if config_path:
        print(f"Config file: {config_path}")
    else:
        print("Config file: (using defaults)")
    print()
    
    config = load_config()
    
    print("Prometheus:")
    print(f"  Default profile: {config.prometheus.default}")
    for name, profile in config.prometheus.profiles.items():
        marker = " *" if name == config.prometheus.default else ""
        print(f"  [{name}]{marker}")
        print(f"    Type: {profile.type}")
        print(f"    URL: {profile.url}")
        if profile.username:
            print(f"    Username: {profile.username}")
        if profile.password_secret:
            if reveal_secrets:
                password = profile.get_password()
                masked = f"{password[:4]}...{password[-4:]}" if password else "(not set)"
                print(f"    Password: {masked}")
            else:
                print("    Password: ****")
    print()
    
    print("Grafana:")
    print(f"  Default profile: {config.grafana.default}")
    for name, grafana_profile in config.grafana.profiles.items():
        marker = " *" if name == config.grafana.default else ""
        print(f"  [{name}]{marker}")
        print(f"    Type: {grafana_profile.type}")
        print(f"    URL: {grafana_profile.url}")
        print(f"    Org ID: {grafana_profile.org_id}")
        if grafana_profile.api_key_secret:
            if reveal_secrets:
                key = grafana_profile.get_api_key()
                if key:
                    print(f"    API Key: {key[:8]}...{key[-4:]}")
                else:
                    print("    API Key: (not set)")
            else:
                print("    API Key: ****")
    print()
    
    print("Alerting:")
    print(f"  PagerDuty: {'enabled' if config.alerting.pagerduty.enabled else 'disabled'}")
    if config.alerting.pagerduty.enabled:
        policy = config.alerting.pagerduty.default_escalation_policy or "(not set)"
        print(f"    Escalation Policy: {policy}")
    print(f"  Slack: {'enabled' if config.alerting.slack.enabled else 'disabled'}")
    if config.alerting.slack.enabled:
        print(f"    Default Channel: {config.alerting.slack.default_channel}")
    print(f"  Datadog: {'enabled' if config.alerting.datadog.enabled else 'disabled'}")
    
    return 0


class _ConfigSetError(ValueError):
    """A `config set` key or value that cannot be applied; the message is for the user."""


def _set_default(section_name: str):
    def apply(config: IntegrationConfig, value: str | None) -> None:
        getattr(config, section_name).default = value or "local"

    return apply


def _enum_value(enum_cls, value: str | None, default, key: str):
    if not value:
        return default
    try:
        return enum_cls(value)
    except ValueError:
        valid = ", ".join(member.value for member in enum_cls)
        raise _ConfigSetError(f"Invalid value for {key}: {value!r}. Use one of: {valid}") from None


def _org_id(value: str | None, key: str) -> int:
    if not value:
        return 1
    try:
        return int(value)
    except ValueError:
        raise _ConfigSetError(f"Invalid value for {key}: {value!r}. Use a whole number") from None


_TRUE_WORDS = ("true", "1", "yes")
_FALSE_WORDS = ("false", "0", "no")


def _enabled(value: str | None, key: str) -> bool:
    if not value:
        return False
    word = value.lower()
    if word in _TRUE_WORDS:
        return True
    if word in _FALSE_WORDS:
        return False
    raise _ConfigSetError(f"Invalid value for {key}: {value!r}. Use true or false")


# What each profile field does to the profile. `key` is the full key the user
# typed, for error messages.
_PROMETHEUS_PROFILE_FIELDS = {
    "url": lambda profile, value, key: setattr(profile, "url", value or ""),
    "type": lambda profile, value, key: setattr(
        profile, "type", _enum_value(PrometheusType, value, PrometheusType.PROMETHEUS, key)
    ),
    "username": lambda profile, value, key: setattr(profile, "username", value),
    "password": lambda profile, value, key: setattr(profile, "password_secret", value),
}

_GRAFANA_PROFILE_FIELDS = {
    "url": lambda profile, value, key: setattr(profile, "url", value or ""),
    "type": lambda profile, value, key: setattr(
        profile, "type", _enum_value(GrafanaType, value, GrafanaType.GRAFANA, key)
    ),
    "api_key": lambda profile, value, key: setattr(profile, "api_key_secret", value),
    "org_id": lambda profile, value, key: setattr(profile, "org_id", _org_id(value, key)),
}

# section -> (profile class, its settable fields)
_PROFILE_SECTIONS = {
    "prometheus": (PrometheusProfile, _PROMETHEUS_PROFILE_FIELDS),
    "grafana": (GrafanaProfile, _GRAFANA_PROFILE_FIELDS),
}

# "<destination>.<field>" under alerting -> what it does to the alerting config
_ALERTING_FIELDS = {
    "pagerduty.enabled": lambda alerting, value, key: setattr(
        alerting.pagerduty, "enabled", _enabled(value, key)
    ),
    "pagerduty.api_key": lambda alerting, value, key: setattr(
        alerting.pagerduty, "api_key_secret", value
    ),
    "pagerduty.escalation_policy": lambda alerting, value, key: setattr(
        alerting.pagerduty, "default_escalation_policy", value
    ),
    "slack.enabled": lambda alerting, value, key: setattr(
        alerting.slack, "enabled", _enabled(value, key)
    ),
    "slack.webhook_url": lambda alerting, value, key: setattr(
        alerting.slack, "webhook_url_secret", value
    ),
    "slack.channel": lambda alerting, value, key: setattr(
        alerting.slack, "default_channel", value or "#alerts"
    ),
}


def _settable_keys() -> list[str]:
    """Every key `config set` accepts, with <name> for a profile name."""
    keys = []
    for section, (_profile_cls, fields) in _PROFILE_SECTIONS.items():
        keys.append(f"{section}.default")
        keys += [f"{section}.profiles.<name>.{field}" for field in fields]
    keys += [f"alerting.{field}" for field in _ALERTING_FIELDS]
    return keys


def _resolve_set_key(key: str):
    """Return the function that applies a value for ``key``.

    Raises _ConfigSetError for a key that names nothing settable, so a typo is
    reported instead of being saved as a change that did not happen
    (opensrm-bkgi). Resolving the key touches no configuration.
    """
    section, _, subkey = key.partition(".")

    if section == "alerting":
        setter = _ALERTING_FIELDS.get(subkey)
        if setter is None:
            raise _ConfigSetError(f"Unknown key: {key}")
        return lambda config, value: setter(config.alerting, value, key)

    profile_cls, fields = _PROFILE_SECTIONS[section]
    if subkey == "default":
        return _set_default(section)

    head, _, rest = subkey.partition(".")
    profile_name, _, field = rest.partition(".")
    if head != "profiles" or not profile_name or field not in fields:
        raise _ConfigSetError(f"Unknown key: {key}")

    def apply(config: IntegrationConfig, value: str | None) -> None:
        profiles = getattr(config, section).profiles
        # a new profile is added only once its value has been accepted
        profile = profiles.get(profile_name) or profile_cls(name=profile_name)
        fields[field](profile, value, key)
        profiles[profile_name] = profile

    return apply


def config_set_command(key: str, value: str | None = None, secret: bool = False) -> int:
    """Set a configuration value.

    Returns 1, with the configuration file untouched, for a key that is not
    settable, a value the key does not accept, or an existing configuration
    file that cannot be read.
    """
    parts = key.split(".")

    if len(parts) < 2:
        print(f"Invalid key format: {key}")
        print("Use: section.key (e.g., grafana.url, prometheus.default)")
        return 1

    section = parts[0]
    if section != "alerting" and section not in _PROFILE_SECTIONS:
        print(f"Unknown section: {section}")
        return 1

    try:
        apply = _resolve_set_key(key)
    except _ConfigSetError as e:
        print(str(e))
        print("Settable keys:")
        for settable in _settable_keys():
            print(f"  {settable}")
        return 1

    if secret and value is None:
        value = getpass.getpass(f"Enter value for {key}: ")

    # strict: falling back to the defaults for a file that could not be read
    # would save the defaults over it
    try:
        config = load_config(strict=True)
    except ConfigLoadError as e:
        print(f"Cannot update the configuration: {e}")
        print("Fix or remove the file, then run the command again.")
        return 1

    try:
        apply(config, value)
    except _ConfigSetError as e:
        print(str(e))
        return 1

    # OSError: the file or its directory is not writable. RecursionError: a
    # section this command keeps but does not manage is nested too deeply for
    # the YAML writer. Both are raised before the file is opened for writing.
    try:
        save_config(config)
    except (OSError, RecursionError) as e:
        print(f"Could not save the configuration: {e or type(e).__name__}")
        return 1
    print(f"Updated {key}")
    return 0


def config_init_command() -> int:
    """Interactive configuration wizard."""
    print("=" * 60)
    print("  NthLayer Configuration Wizard")
    print("=" * 60)
    print()
    
    config = IntegrationConfig.default()
    
    print("Secrets Backend Configuration")
    print("-" * 40)
    print("Available backends:")
    print("  1. env     - Environment variables (NTHLAYER_*)")
    print("  2. file    - Credentials file (~/.nthlayer/credentials.yaml)")
    print("  3. vault   - HashiCorp Vault")
    print("  4. aws     - AWS Secrets Manager")
    print("  5. azure   - Azure Key Vault")
    print("  6. gcp     - Google Cloud Secret Manager")
    print("  7. doppler - Doppler")
    print()
    
    backend_choice = input("Primary secrets backend [1-7] (1): ").strip() or "1"
    backend_map = {
        "1": "env", "env": "env",
        "2": "file", "file": "file",
        "3": "vault", "vault": "vault",
        "4": "aws", "aws": "aws",
        "5": "azure", "azure": "azure",
        "6": "gcp", "gcp": "gcp",
        "7": "doppler", "doppler": "doppler",
    }
    selected_backend = backend_map.get(backend_choice, "env")
    print(f"Using backend: {selected_backend}")
    
    if selected_backend == "vault":
        vault_addr = input("Vault address (https://vault.example.com): ").strip()
        vault_auth = input("Auth method [token/kubernetes/aws_iam/approle] (token): ").strip()
        vault_auth = vault_auth or "token"
        _vault_role = input("Vault role (optional): ").strip() or None  # noqa: F841
        print(f"Vault configured: {vault_addr} ({vault_auth} auth)")
    elif selected_backend == "aws":
        aws_region = input("AWS region (us-east-1): ").strip() or "us-east-1"
        print(f"AWS Secrets Manager configured in {aws_region}")
    elif selected_backend == "azure":
        azure_vault_url = input("Azure Key Vault URL: ").strip()
        print(f"Azure Key Vault configured: {azure_vault_url}")
    elif selected_backend == "gcp":
        gcp_project = input("GCP project ID: ").strip()
        print(f"GCP Secret Manager configured for project: {gcp_project}")
    elif selected_backend == "doppler":
        doppler_project = input("Doppler project (nthlayer): ").strip() or "nthlayer"
        doppler_config = input("Doppler config (prd): ").strip() or "prd"
        print(f"Doppler configured: {doppler_project}/{doppler_config}")
    
    print()
    
    print("Grafana Configuration")
    print("-" * 40)
    grafana_type = input("Grafana type [grafana/grafana-cloud] (grafana): ").strip()
    grafana_type = grafana_type or "grafana"
    grafana_url = input("Grafana URL (http://localhost:3000): ").strip()
    grafana_url = grafana_url or "http://localhost:3000"
    
    profile = GrafanaProfile(
        name="default",
        type=(
            GrafanaType(grafana_type)
            if grafana_type in ("grafana", "grafana-cloud")
            else GrafanaType.GRAFANA
        ),
        url=grafana_url,
    )
    
    if input("Configure API key? [y/N]: ").strip().lower() == "y":
        api_key = getpass.getpass("API Key: ")
        resolver = get_secret_resolver()
        resolver.set_secret("grafana/api_key", api_key)
        profile.api_key_secret = "grafana/api_key"
        print("API key stored")
    
    config.grafana.profiles["default"] = profile
    config.grafana.default = "default"
    print()
    
    print("Prometheus Configuration")
    print("-" * 40)
    prom_type = input("Prometheus type [prometheus/mimir/grafana-cloud] (prometheus): ").strip()
    prom_type = prom_type or "prometheus"
    prom_url = input("Prometheus URL (http://localhost:9090): ").strip()
    prom_url = prom_url or "http://localhost:9090"
    
    prom_profile = PrometheusProfile(
        name="default",
        type=(
            PrometheusType(prom_type)
            if prom_type in ("prometheus", "mimir", "grafana-cloud")
            else PrometheusType.PROMETHEUS
        ),
        url=prom_url,
    )
    
    config.prometheus.profiles["default"] = prom_profile
    config.prometheus.default = "default"
    print()
    
    print("Alerting Configuration")
    print("-" * 40)
    
    if input("Configure PagerDuty? [y/N]: ").strip().lower() == "y":
        config.alerting.pagerduty.enabled = True
        policy = input("Default escalation policy: ").strip()
        if policy:
            config.alerting.pagerduty.default_escalation_policy = policy
        
        if input("Configure API key? [y/N]: ").strip().lower() == "y":
            api_key = getpass.getpass("PagerDuty API Key: ")
            resolver = get_secret_resolver()
            resolver.set_secret("pagerduty/api_key", api_key)
            config.alerting.pagerduty.api_key_secret = "pagerduty/api_key"
    
    if input("Configure Slack? [y/N]: ").strip().lower() == "y":
        config.alerting.slack.enabled = True
        channel = input("Default channel (#alerts): ").strip() or "#alerts"
        config.alerting.slack.default_channel = channel
        
        if input("Configure webhook URL? [y/N]: ").strip().lower() == "y":
            webhook = getpass.getpass("Slack Webhook URL: ")
            resolver = get_secret_resolver()
            resolver.set_secret("slack/webhook_url", webhook)
            config.alerting.slack.webhook_url_secret = "slack/webhook_url"
    
    print()
    
    config_path = Path.home() / ".nthlayer" / "config.yaml"
    save_config(config, config_path)
    
    print("=" * 60)
    print(f"Configuration saved to: {config_path}")
    print()
    print("Next steps:")
    print("  1. Run 'nthlayer config show' to verify")
    print("  2. Run 'nthlayer secrets verify' to check secrets")
    print("  3. Run 'nthlayer apply <service>.yaml' to generate configs")
    
    return 0


def secrets_list_command() -> int:
    """List available secrets."""
    resolver = get_secret_resolver()
    secrets_by_backend = resolver.list_secrets()
    
    print("=" * 60)
    print("  Available Secrets")
    print("=" * 60)
    print()
    
    if not secrets_by_backend:
        print("No secrets found.")
        print()
        print("To add secrets:")
        print("  nthlayer secrets set grafana/api_key")
        print("  Or set environment variables: NTHLAYER_GRAFANA_API_KEY")
        return 0
    
    for backend, secrets in secrets_by_backend.items():
        print(f"[{backend}]")
        for secret in secrets:
            print(f"  {secret}")
        print()
    
    return 0


def secrets_verify_command(secrets: list[str] | None = None) -> int:
    """Verify required secrets exist."""
    required = secrets or REQUIRED_SECRETS
    resolver = get_secret_resolver()
    
    print("=" * 60)
    print("  Secret Verification")
    print("=" * 60)
    print()
    
    results = resolver.verify_secrets(required)
    
    all_found = True
    for path, (found, backend) in results.items():
        if found:
            print(f"  {path}: found ({backend})")
        else:
            print(f"  {path}: NOT FOUND")
            all_found = False
    
    print()
    
    if all_found:
        print("All required secrets are available.")
        return 0
    else:
        print("Some secrets are missing. Set them with:")
        print("  nthlayer secrets set <path>")
        print("  Or set environment variables: NTHLAYER_<PATH>")
        return 1


def secrets_set_command(path: str, value: str | None = None, backend: str | None = None) -> int:
    """Set a secret."""
    if value is None:
        value = getpass.getpass(f"Enter secret value for {path}: ")
    
    resolver = get_secret_resolver()
    
    target_backend = None
    if backend:
        try:
            target_backend = SecretBackend(backend)
        except ValueError:
            print(f"Unknown backend: {backend}")
            return 1
    
    success = resolver.set_secret(path, value, target_backend)
    
    if success:
        print(f"Secret stored: {path}")
        return 0
    else:
        print(f"Failed to store secret: {path}")
        print("Ensure the backend supports writing (file, vault)")
        return 1


def secrets_get_command(path: str, reveal: bool = False) -> int:
    """Get a secret value."""
    resolver = get_secret_resolver()
    value = resolver.resolve(path)
    
    if value is None:
        print(f"Secret not found: {path}")
        return 1
    
    if reveal:
        print(value)
    else:
        masked = f"{value[:4]}...{value[-4:]}" if len(value) > 8 else "****"
        print(f"{path}: {masked}")
    
    return 0


def secrets_migrate_command(
    source: str,
    target: str,
    secrets: list[str] | None = None,
    dry_run: bool = False
) -> int:
    """
    Migrate secrets between backends.
    
    Examples:
        nthlayer secrets migrate env vault
        nthlayer secrets migrate file aws --secrets grafana/api_key pagerduty/token
        nthlayer secrets migrate env vault --dry-run
    """
    print("=" * 60)
    print("  Secrets Migration")
    print("=" * 60)
    print()
    
    try:
        source_backend = SecretBackend(source)
        target_backend = SecretBackend(target)
    except ValueError as e:
        print(f"Invalid backend: {e}")
        print(f"Valid backends: {', '.join(b.value for b in SecretBackend)}")
        return 1
    
    resolver = get_secret_resolver()
    
    if source_backend not in resolver._backends:
        print(f"Source backend not available: {source}")
        print("Check your configuration and ensure required packages are installed.")
        return 1
    
    if target_backend not in resolver._backends:
        print(f"Target backend not available: {target}")
        print("Check your configuration and ensure required packages are installed.")
        return 1
    
    target_backend_impl = resolver._backends[target_backend]
    if not target_backend_impl.supports_write():
        print(f"Target backend does not support writing: {target}")
        return 1
    
    source_backend_impl = resolver._backends[source_backend]
    
    if secrets:
        secrets_to_migrate = secrets
    else:
        secrets_to_migrate = source_backend_impl.list_secrets()
    
    if not secrets_to_migrate:
        print(f"No secrets found in {source} backend")
        return 0
    
    print(f"Source: {source}")
    print(f"Target: {target}")
    print(f"Secrets to migrate: {len(secrets_to_migrate)}")
    print()
    
    if dry_run:
        print("[DRY RUN] Would migrate:")
        for secret_path in secrets_to_migrate:
            value = source_backend_impl.get_secret(secret_path)
            status = "found" if value else "NOT FOUND"
            print(f"  {secret_path} ({status})")
        return 0
    
    migrated = 0
    failed = 0
    
    for secret_path in secrets_to_migrate:
        value = source_backend_impl.get_secret(secret_path)
        if value is None:
            print(f"  SKIP {secret_path} (not found in source)")
            continue
        
        success = target_backend_impl.set_secret(secret_path, value)
        if success:
            print(f"  OK   {secret_path}")
            migrated += 1
        else:
            print(f"  FAIL {secret_path}")
            failed += 1
    
    print()
    print(f"Migration complete: {migrated} migrated, {failed} failed")
    
    return 0 if failed == 0 else 1
