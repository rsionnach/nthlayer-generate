"""`nthlayer config set` changes one value and nothing else (opensrm-bkgi).

Three ways it used to lose or misreport things:

- `ConfigLoader.save` wrote only the integration config, so a `secrets:`
  section in the same file, which `load_secrets_config` reads, was dropped.
- A key that named nothing settable printed "Updated <key>" and exited 0.
- A file that could not be read loaded as the defaults, which were then saved
  over it.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from nthlayer_generate.config.cli import _resolve_set_key, _settable_keys, config_set_command
from nthlayer_generate.config.integrations import IntegrationConfig
from nthlayer_generate.config.loader import (
    ConfigLoadError,
    load_config,
    load_secrets_config,
    save_config,
)
from nthlayer_generate.config.secrets import SecretBackend
from nthlayer_generate.user_config import NthLayerConfig

# A hand-written file: two sections the integration config owns, and two it
# does not. `secrets:` uses the keys `ConfigLoader._parse_secrets_config`
# reads; `error_budget:` uses the keys `NthLayerConfig` reads.
A_HAND_WRITTEN_CONFIG = """\
prometheus:
  default: prod
  profiles:
    prod:
      type: mimir
      url: https://metrics.example.test
grafana:
  default: prod
  profiles:
    prod:
      type: grafana-cloud
      url: https://dashboards.example.test
secrets:
  backend: vault
  strict: true
  vault:
    address: https://vault.example.test
    role: nthlayer
error_budget:
  inherited_attribution: true
  time_window_minutes: 15
"""


@pytest.fixture
def config_file(tmp_path, monkeypatch) -> Path:
    """The project config `config set` finds first: ./.nthlayer/config.yaml."""
    monkeypatch.chdir(tmp_path)
    path = tmp_path / ".nthlayer" / "config.yaml"
    path.parent.mkdir()
    path.write_text(A_HAND_WRITTEN_CONFIG, encoding="utf-8")
    return path


class TestSectionsTheConfigDoesNotOwnAreKept:
    def test_config_set_keeps_the_secrets_section(self, config_file):
        before = load_secrets_config(config_file)
        # the fixture is only meaningful if the section is really read
        assert before.backend is SecretBackend.VAULT
        assert before.vault_address == "https://vault.example.test"

        assert config_set_command("alerting.slack.channel", "#on-call") == 0

        assert load_secrets_config(config_file) == before
        assert load_config(config_file).alerting.slack.default_channel == "#on-call"

    def test_config_set_keeps_every_other_section_as_it_was(self, config_file):
        before = yaml.safe_load(A_HAND_WRITTEN_CONFIG)

        assert config_set_command("prometheus.profiles.prod.username", "reader") == 0

        after = yaml.safe_load(config_file.read_text(encoding="utf-8"))
        assert after["secrets"] == before["secrets"]
        assert after["error_budget"] == before["error_budget"]
        assert NthLayerConfig.load(config_file).error_budget.time_window_minutes == 15

    def test_save_config_replaces_the_sections_it_owns_and_keeps_the_rest(self, config_file):
        save_config(IntegrationConfig.default(), config_file)

        after = yaml.safe_load(config_file.read_text(encoding="utf-8"))
        assert after["prometheus"]["default"] == "local"
        assert after["secrets"] == yaml.safe_load(A_HAND_WRITTEN_CONFIG)["secrets"]

    def test_a_new_file_holds_only_the_integration_config(self, tmp_path):
        """The control: with nothing to keep, nothing extra is written."""
        path = tmp_path / "config.yaml"

        save_config(IntegrationConfig.default(), path)

        assert set(yaml.safe_load(path.read_text(encoding="utf-8"))) == set(
            IntegrationConfig.default().to_dict()
        )


# Keys a user could plausibly type that name nothing settable. The first is the
# one that prompted this bead: the field is `default_channel`, the key is not.
KEYS_THAT_NAME_NOTHING = [
    "alerting.slack.default_channel",
    "alerting.slack.colour",
    "alerting.datadog.enabled",
    "alerting.pagerduty",
    "alerting.email.enabled",
    "prometheus.url",
    "prometheus.profiles",
    "prometheus.profiles.prod",
    "prometheus.profiles.prod.token",
    "prometheus.profiles..url",
    "prometheus.profile.prod.url",
    "grafana.profiles.prod.password",
    "grafana.profiles.prod.url.extra",
]
assert KEYS_THAT_NAME_NOTHING

# (key, value) pairs where the key is settable and the value is not one it takes.
VALUES_A_KEY_DOES_NOT_TAKE = [
    ("prometheus.profiles.prod.type", "victoria"),
    ("prometheus.profiles.fresh.type", "victoria"),
    ("grafana.profiles.prod.type", "kibana"),
    ("grafana.profiles.prod.org_id", "seven"),
    ("grafana.profiles.prod.org_id", "1.5"),
    ("alerting.slack.enabled", "maybe"),
    ("alerting.pagerduty.enabled", "on"),
]
assert VALUES_A_KEY_DOES_NOT_TAKE


class TestAKeyOrValueThatCannotBeAppliedIsAnError:
    @pytest.mark.parametrize("key", KEYS_THAT_NAME_NOTHING)
    def test_an_unknown_key_exits_1_and_leaves_the_file_alone(self, key, config_file):
        assert config_set_command(key, "value") == 1

        assert config_file.read_text(encoding="utf-8") == A_HAND_WRITTEN_CONFIG

    @pytest.mark.parametrize(("key", "value"), VALUES_A_KEY_DOES_NOT_TAKE)
    def test_a_refused_value_exits_1_and_leaves_the_file_alone(self, key, value, config_file):
        assert config_set_command(key, value) == 1

        assert config_file.read_text(encoding="utf-8") == A_HAND_WRITTEN_CONFIG

    def test_an_unknown_key_is_refused_before_a_secret_is_asked_for(self, config_file):
        with patch("nthlayer_generate.config.cli.getpass.getpass") as asked:
            assert config_set_command("grafana.profiles.prod.api_token", secret=True) == 1

        asked.assert_not_called()


# Every key docs-site/commands/config.md lists as settable, written out by
# hand from that table with `staging` as the profile name: the value to set,
# the one place in the saved file that must then hold it, and what it holds.
# Each value differs from what the fixture and the defaults have there.
DOCUMENTED_KEYS = [
    ("prometheus.default", "staging", "prometheus.default", "staging"),
    (
        "prometheus.profiles.staging.url",
        "https://m.example.test",
        "prometheus.profiles.staging.url",
        "https://m.example.test",
    ),
    ("prometheus.profiles.staging.type", "thanos", "prometheus.profiles.staging.type", "thanos"),
    (
        "prometheus.profiles.staging.username",
        "reader",
        "prometheus.profiles.staging.username",
        "reader",
    ),
    (
        "prometheus.profiles.staging.password",
        "prometheus/password",
        "prometheus.profiles.staging.password_secret",
        "prometheus/password",
    ),
    ("grafana.default", "staging", "grafana.default", "staging"),
    (
        "grafana.profiles.staging.url",
        "https://g.example.test",
        "grafana.profiles.staging.url",
        "https://g.example.test",
    ),
    (
        "grafana.profiles.staging.type",
        "grafana-enterprise",
        "grafana.profiles.staging.type",
        "grafana-enterprise",
    ),
    (
        "grafana.profiles.staging.api_key",
        "grafana/api_key",
        "grafana.profiles.staging.api_key_secret",
        "grafana/api_key",
    ),
    ("grafana.profiles.staging.org_id", "7", "grafana.profiles.staging.org_id", 7),
    ("alerting.pagerduty.enabled", "false", "alerting.pagerduty.enabled", False),
    (
        "alerting.pagerduty.api_key",
        "pagerduty/api_key",
        "alerting.pagerduty.api_key_secret",
        "pagerduty/api_key",
    ),
    (
        "alerting.pagerduty.escalation_policy",
        "P123",
        "alerting.pagerduty.default_escalation_policy",
        "P123",
    ),
    ("alerting.slack.enabled", "false", "alerting.slack.enabled", False),
    (
        "alerting.slack.webhook_url",
        "slack/webhook_url",
        "alerting.slack.webhook_url_secret",
        "slack/webhook_url",
    ),
    ("alerting.slack.channel", "#on-call", "alerting.slack.default_channel", "#on-call"),
]
assert DOCUMENTED_KEYS


def _leaves(value, prefix=""):
    """Flatten nested dicts to {dotted.path: leaf}."""
    if not isinstance(value, dict):
        return {prefix: value}
    flat = {}
    for key, inner in value.items():
        flat.update(_leaves(inner, f"{prefix}.{key}" if prefix else key))
    return flat


class TestEverySettableKeyChangesTheSavedConfig:
    @pytest.mark.parametrize(
        ("key", "value", "saved_at", "saved_as"),
        DOCUMENTED_KEYS,
        ids=[entry[0] for entry in DOCUMENTED_KEYS],
    )
    def test_the_value_lands_in_its_own_field_and_nowhere_else(
        self, key, value, saved_at, saved_as, config_file
    ):
        before = _leaves(load_config(config_file, strict=True).to_dict())
        # the entry is only meaningful if it is a change
        assert before.get(saved_at) != saved_as

        assert config_set_command(key, value) == 0

        after = _leaves(load_config(config_file, strict=True).to_dict())
        assert after[saved_at] == saved_as
        # A profile key creates the `staging` profile, whose other fields are
        # new too. Everything outside that profile and the field itself must
        # be what it was.
        section = key.split(".", 1)[0]
        elsewhere = [
            path
            for path in before | after
            if path != saved_at and not path.startswith(f"{section}.profiles.staging.")
        ]
        assert {path: after.get(path) for path in elsewhere} == {
            path: before.get(path) for path in elsewhere
        }

    def test_the_documented_keys_are_exactly_the_settable_ones(self):
        documented = {key.replace(".staging.", ".<name>.") for key, *_ in DOCUMENTED_KEYS}

        assert documented == set(_settable_keys())

    def test_a_refused_value_does_not_add_the_profile_it_named(self):
        config = IntegrationConfig.default()

        with pytest.raises(ValueError):
            _resolve_set_key("prometheus.profiles.fresh.type")(config, "victoria")

        assert "fresh" not in config.prometheus.profiles

    def test_without_a_file_the_value_is_saved_to_the_home_config(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        home = tmp_path / "home"
        home.mkdir()

        with patch.object(Path, "home", return_value=home):
            assert config_set_command("prometheus.profiles.prod.url", "https://m.example.test") == 0

        saved = load_config(home / ".nthlayer" / "config.yaml", strict=True)
        assert saved.prometheus.profiles["prod"].url == "https://m.example.test"


def _a_directory(path: Path) -> None:
    path.unlink()
    path.mkdir()


def _text(content: str):
    return lambda path: path.write_text(content, encoding="utf-8")


# Files that exist and are not a readable configuration. Each entry puts its
# state at the path it is given.
UNREADABLE_CONFIGS = [
    pytest.param(_text("prometheus: [unclosed\n"), id="yaml-syntax-error"),
    pytest.param(_text("- a\n- list\n"), id="top-level-list"),
    pytest.param(_text("just a sentence\n"), id="top-level-string"),
    pytest.param(_text("prometheus: null\n"), id="a-null-section"),
    pytest.param(
        _text("prometheus:\n  profiles:\n    prod: a-string\n"),
        id="a-profile-that-is-not-a-mapping",
    ),
    pytest.param(
        _text("prometheus:\n  profiles:\n    prod:\n      type: victoria\n"),
        id="an-unknown-backend-type",
    ),
    pytest.param(
        lambda path: path.write_bytes(b"prometheus:\n  default: caf\xe9\n"), id="not-utf-8"
    ),
    pytest.param(_text("url: !!python/object/apply:os.getcwd []\n"), id="a-python-tag"),
    # deep enough that PyYAML exhausts the stack (RecursionError, not YAMLError)
    pytest.param(_text("a: " + "[" * 5000 + "]" * 5000 + "\n"), id="nested-too-deeply"),
    pytest.param(_a_directory, id="a-directory"),
]
assert UNREADABLE_CONFIGS


# The same states without the directory, which no write can replace.
UNREADABLE_FILES = [case for case in UNREADABLE_CONFIGS if case.id != "a-directory"]
assert len(UNREADABLE_FILES) == len(UNREADABLE_CONFIGS) - 1


def _snapshot(path: Path):
    return "directory" if path.is_dir() else path.read_bytes()


class TestAConfigThatCannotBeReadIsNotOverwritten:
    @pytest.mark.parametrize("write", UNREADABLE_CONFIGS)
    def test_config_set_exits_1_and_leaves_the_file_alone(self, write, config_file):
        write(config_file)
        before = _snapshot(config_file)

        assert config_set_command("alerting.slack.channel", "#on-call") == 1

        assert _snapshot(config_file) == before

    @pytest.mark.parametrize("write", UNREADABLE_CONFIGS)
    def test_a_strict_load_raises_and_a_plain_load_returns_the_defaults(self, write, config_file):
        write(config_file)

        with pytest.raises(ConfigLoadError):
            load_config(config_file, strict=True)
        assert load_config(config_file) == IntegrationConfig.default()

    @pytest.mark.parametrize("write", UNREADABLE_FILES)
    def test_an_explicit_save_replaces_it(self, write, config_file):
        """`nthlayer setup` asks before overwriting; having asked, it must be able to."""
        write(config_file)

        save_config(IntegrationConfig.default(), config_file)

        assert load_config(config_file, strict=True) == IntegrationConfig.default()

    def test_an_empty_file_is_readable(self, config_file):
        """The control: emptiness is not unreadability."""
        config_file.write_text("", encoding="utf-8")

        assert config_set_command("alerting.slack.channel", "#on-call") == 0

        assert load_config(config_file, strict=True).alerting.slack.default_channel == "#on-call"


# A file an earlier version saved (the profile `type` carries a python tag,
# opensrm-p520), with the section `NthLayerConfig` reads added by hand.
AN_OLD_FORM_FILE_WITH_AN_ERROR_BUDGET = """\
prometheus:
  default: prod
  profiles:
    prod:
      name: prod
      type: !!python/object/apply:nthlayer_generate.config.integrations.PrometheusType
      - mimir
      url: https://metrics.example.test
error_budget:
  inherited_attribution: true
  time_window_minutes: 15
"""


class TestTheErrorBudgetReaderSharesTheFile:
    def test_the_fixture_is_what_the_safe_loader_refuses(self):
        with pytest.raises(yaml.constructor.ConstructorError):
            yaml.safe_load(AN_OLD_FORM_FILE_WITH_AN_ERROR_BUDGET)

    def test_it_reads_its_section_from_an_old_form_file(self, config_file):
        config_file.write_text(AN_OLD_FORM_FILE_WITH_AN_ERROR_BUDGET, encoding="utf-8")

        loaded = NthLayerConfig.load(config_file)

        assert loaded.error_budget.inherited_attribution is True
        assert loaded.error_budget.time_window_minutes == 15


def _a_kept_section_the_writer_cannot_dump() -> str:
    """A config whose `extra:` section loads but is nested too deeply to dump.

    PyYAML's reader uses fewer stack frames per level than its writer, so
    there is a band of depths that load and then raise RecursionError on
    dump. The band depends on the interpreter's recursion limit, so it is
    searched for here, against PyYAML itself, not assumed.
    """
    for depth in range(100, 3000, 50):
        text = A_HAND_WRITTEN_CONFIG + "extra: " + "[" * depth + "]" * depth + "\n"
        try:
            data = yaml.safe_load(text)
        except RecursionError:
            break
        try:
            yaml.safe_dump(data)
        except RecursionError:
            return text
    raise AssertionError("no nesting depth loads and then fails to dump; the fixture is void")


class TestASaveThatFailsIsReported:
    def test_a_kept_section_too_deep_to_write_exits_1_and_leaves_the_file_alone(self, config_file):
        text = _a_kept_section_the_writer_cannot_dump()
        config_file.write_text(text, encoding="utf-8")

        assert config_set_command("alerting.slack.channel", "#on-call") == 1

        assert config_file.read_text(encoding="utf-8") == text

    def test_a_read_only_file_exits_1_and_leaves_the_file_alone(self, config_file):
        config_file.chmod(0o444)
        try:
            # the state is only meaningful if the file really refuses writes
            with pytest.raises(OSError):
                config_file.open("a", encoding="utf-8")

            assert config_set_command("alerting.slack.channel", "#on-call") == 1
        finally:
            config_file.chmod(0o644)

        assert config_file.read_text(encoding="utf-8") == A_HAND_WRITTEN_CONFIG


# Values in a kept section that YAML reads as something other than a string,
# a number or a list: each must come back equal after `config set`.
KEPT_SECTIONS_WITH_UNUSUAL_VALUES = [
    pytest.param("extra:\n  since: 2024-05-01\n", id="a-date"),
    pytest.param("extra:\n  1: one\n  true: yes\n", id="non-string-keys"),
    pytest.param("extra:\n  blob: !!binary aGVsbG8=\n", id="binary"),
    pytest.param("extra:\n  tags: !!set {a, b}\n", id="a-set"),
    pytest.param("extra:\n  base: &b {x: 1}\n  copy: *b\n", id="an-alias"),
]
assert KEPT_SECTIONS_WITH_UNUSUAL_VALUES


class TestAKeptSectionComesBackEqual:
    @pytest.mark.parametrize("section", KEPT_SECTIONS_WITH_UNUSUAL_VALUES)
    def test_its_values_survive_config_set(self, section, config_file):
        config_file.write_text(A_HAND_WRITTEN_CONFIG + section, encoding="utf-8")
        before = yaml.safe_load(section)["extra"]

        assert config_set_command("alerting.slack.channel", "#on-call") == 0

        assert yaml.safe_load(config_file.read_text(encoding="utf-8"))["extra"] == before
