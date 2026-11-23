"""A saved configuration loads back as what was saved (opensrm-p520).

`ConfigLoader.save` used to write each profile's `type`, a StrEnum member,
with `yaml.dump`, which emits a `!!python/object/apply:` tag. `load` reads with
the safe loader, which refuses that tag, so every saved file fell back to the
defaults: what a user entered in `nthlayer setup` was discarded on the next
read, and `nthlayer config set` then saved the defaults over it.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from nthlayer_generate.cli.setup import _quick_setup
from nthlayer_generate.config.cli import config_set_command
from nthlayer_generate.config.integrations import (
    GrafanaProfile,
    GrafanaType,
    IntegrationConfig,
    PrometheusProfile,
    PrometheusType,
)
from nthlayer_generate.config.loader import load_config, load_secrets_config, save_config
from nthlayer_generate.config.secrets import SecretBackend, SecretConfig, SecretResolver

PROMETHEUS_TYPES = list(PrometheusType)
GRAFANA_TYPES = list(GrafanaType)
assert PROMETHEUS_TYPES
assert GRAFANA_TYPES


def _a_config_unlike_the_defaults(prometheus_type, grafana_type) -> IntegrationConfig:
    """Every field differs from `IntegrationConfig.default()`, so a load that
    fell back to the defaults cannot compare equal to it."""
    config = IntegrationConfig()
    config.prometheus.default = "prod"
    config.prometheus.profiles["prod"] = PrometheusProfile(
        name="prod",
        type=prometheus_type,
        url="https://metrics.example.test",
        username="reader",
        password_secret="prometheus/password",
        tenant_id="team-a",
    )
    config.grafana.default = "prod"
    config.grafana.profiles["prod"] = GrafanaProfile(
        name="prod",
        type=grafana_type,
        url="https://dashboards.example.test",
        org_id=7,
        api_key_secret="grafana/api_key",
    )
    config.alerting.pagerduty.api_key_secret = "pagerduty/api_key"
    config.alerting.pagerduty.default_escalation_policy = "P123"
    config.alerting.slack.default_channel = "#payments"
    config.alerting.datadog.enabled = True
    return config


class TestASavedConfigLoadsBack:
    @pytest.mark.parametrize("prometheus_type", PROMETHEUS_TYPES)
    def test_every_prometheus_type_round_trips(self, prometheus_type, tmp_path):
        saved = _a_config_unlike_the_defaults(prometheus_type, GrafanaType.GRAFANA)
        path = tmp_path / "config.yaml"

        save_config(saved, path)

        assert load_config(path) == saved

    @pytest.mark.parametrize("grafana_type", GRAFANA_TYPES)
    def test_every_grafana_type_round_trips(self, grafana_type, tmp_path):
        saved = _a_config_unlike_the_defaults(PrometheusType.PROMETHEUS, grafana_type)
        path = tmp_path / "config.yaml"

        save_config(saved, path)

        assert load_config(path) == saved

    def test_the_saved_file_is_plain_yaml(self, tmp_path):
        """The bead's second acceptance point: `yaml.safe_load` accepts it."""
        path = tmp_path / "config.yaml"

        save_config(_a_config_unlike_the_defaults(PrometheusType.MIMIR, GrafanaType.GRAFANA), path)

        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert data["prometheus"]["profiles"]["prod"]["type"] == "mimir"
        assert type(data["prometheus"]["profiles"]["prod"]["type"]) is str
        assert type(data["grafana"]["profiles"]["prod"]["type"]) is str

    def test_a_value_the_safe_loader_could_not_read_is_refused_before_the_file_is_touched(
        self, tmp_path
    ):
        path = tmp_path / "config.yaml"
        path.write_text("version: 1\n", encoding="utf-8")
        config = IntegrationConfig()
        config.alerting.slack.default_channel = PrometheusType.MIMIR  # not a plain str

        with pytest.raises(yaml.YAMLError):
            save_config(config, path)

        assert path.read_text(encoding="utf-8") == "version: 1\n"


class TestWhatSetupSavesLoadsBack:
    def test_the_profiles_entered_in_quick_setup_are_read_back(self, tmp_path):
        """The bead's first acceptance point, through the real wizard."""
        home = tmp_path / "home"
        home.mkdir()
        answers = iter([True, True, False])  # Prometheus auth, Grafana, not PagerDuty
        prompts = iter(
            ["https://metrics.example.test", "reader", "https://dashboards.example.test"]
        )
        with (
            patch.object(Path, "home", return_value=home),
            patch("nthlayer_generate.cli.setup._prompt", side_effect=lambda *a, **k: next(prompts)),
            patch("nthlayer_generate.cli.setup._prompt_secret", return_value="s3cret"),
            patch(
                "nthlayer_generate.cli.setup._confirm", side_effect=lambda *a, **k: next(answers)
            ),
        ):
            resolver = SecretResolver(SecretConfig())
            with patch("nthlayer_generate.cli.setup.get_secret_resolver", return_value=resolver):
                assert _quick_setup() == 0

        loaded = load_config(home / ".nthlayer" / "config.yaml")

        prometheus = loaded.prometheus.profiles[loaded.prometheus.default]
        assert prometheus.url == "https://metrics.example.test"
        assert prometheus.username == "reader"
        assert prometheus.password_secret == "prometheus/password"
        grafana = loaded.grafana.profiles[loaded.grafana.default]
        assert grafana.url == "https://dashboards.example.test"
        assert grafana.api_key_secret == "grafana/api_key"


# Written by `save_config` on nthlayer-generate main ab1fafb, before the fix,
# for a config with a Mimir profile and a Grafana Cloud profile; copied from
# the file it produced. This is the form every config saved so far has.
A_FILE_THE_OLD_SAVE_WROTE = """\
version: 1
prometheus:
  default: prod
  profiles:
    prod:
      name: prod
      type: !!python/object/apply:nthlayer_generate.config.integrations.PrometheusType
      - mimir
      url: https://metrics.example.test
      username: reader
      password_secret: prometheus/password
      tenant_id: team-a
grafana:
  default: prod
  profiles:
    prod:
      name: prod
      type: !!python/object/apply:nthlayer_generate.config.integrations.GrafanaType
      - grafana-cloud
      url: https://dashboards.example.test
      org_id: 7
      api_key_secret: grafana/api_key
alerting:
  pagerduty:
    api_key_secret: pagerduty/api_key
    default_escalation_policy: P123
    enabled: true
  slack:
    webhook_url_secret: null
    default_channel: '#payments'
    enabled: true
  datadog:
    api_key_secret: null
    app_key_secret: null
    site: datadoghq.com
    enabled: true
"""

# Tagged values that must NOT be read: each makes the whole file unreadable,
# as any python tag did before.
REFUSED_TAGGED_VALUES = [
    pytest.param("!!python/object/apply:os.getcwd []", id="another-callable"),
    pytest.param(
        "!!python/object/apply:nthlayer_generate.config.integrations.IntegrationConfig []",
        id="another-class-in-the-same-module",
    ),
    pytest.param(
        "!!python/object/apply:nthlayer_generate.config.integrations.PrometheusType\n"
        "      - mimir\n      - extra",
        id="legacy-tag-with-two-arguments",
    ),
    pytest.param(
        "!!python/object/apply:nthlayer_generate.config.integrations.PrometheusType\n"
        "      - [mimir]",
        id="legacy-tag-with-a-non-string-argument",
    ),
    pytest.param(
        "!!python/object/apply:nthlayer_generate.config.integrations.PrometheusType mimir",
        id="legacy-tag-on-a-scalar",
    ),
    pytest.param(
        "!!python/object/new:nthlayer_generate.config.integrations.PrometheusType\n      - mimir",
        id="object-new-instead-of-apply",
    ),
]
assert REFUSED_TAGGED_VALUES


class TestAFileTheOldSaveWroteIsStillRead:
    def test_the_fixture_is_what_the_safe_loader_refuses(self):
        """Otherwise the tests below would pass against a file that always loaded."""
        with pytest.raises(yaml.constructor.ConstructorError):
            yaml.safe_load(A_FILE_THE_OLD_SAVE_WROTE)

    def test_its_profiles_are_loaded(self, tmp_path):
        path = tmp_path / "config.yaml"
        path.write_text(A_FILE_THE_OLD_SAVE_WROTE, encoding="utf-8")

        loaded = load_config(path)

        assert loaded == _a_config_unlike_the_defaults(
            PrometheusType.MIMIR, GrafanaType.GRAFANA_CLOUD
        )

    def test_its_secrets_section_is_read_without_falling_back(self, tmp_path):
        path = tmp_path / "config.yaml"
        path.write_text(
            A_FILE_THE_OLD_SAVE_WROTE + "secrets:\n  backend: file\n  strict: true\n",
            encoding="utf-8",
        )

        secrets = load_secrets_config(path)

        assert secrets.backend is SecretBackend.FILE
        assert secrets.strict is True

    def test_config_set_keeps_the_profiles_it_did_not_change(self, tmp_path, monkeypatch):
        """Before the fix, `config set` loaded the defaults and saved them over the file."""
        monkeypatch.chdir(tmp_path)
        path = tmp_path / ".nthlayer" / "config.yaml"
        path.parent.mkdir()
        path.write_text(A_FILE_THE_OLD_SAVE_WROTE, encoding="utf-8")

        assert config_set_command("alerting.slack.channel", "#on-call") == 0

        expected = _a_config_unlike_the_defaults(PrometheusType.MIMIR, GrafanaType.GRAFANA_CLOUD)
        expected.alerting.slack.default_channel = "#on-call"
        assert load_config(path) == expected
        # and the rewrite is in the new, plain form
        assert yaml.safe_load(path.read_text(encoding="utf-8"))["prometheus"]["default"] == "prod"

    @pytest.mark.parametrize("tagged", REFUSED_TAGGED_VALUES)
    def test_any_other_tagged_value_is_still_refused(self, tagged, tmp_path):
        path = tmp_path / "config.yaml"
        path.write_text(
            "prometheus:\n  default: prod\n  profiles:\n    prod:\n"
            f"      type: {tagged}\n      url: https://metrics.example.test\n",
            encoding="utf-8",
        )

        loaded = load_config(path)

        # the documented fallback for an unreadable file
        assert loaded == IntegrationConfig.default()
