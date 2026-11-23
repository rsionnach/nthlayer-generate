# nthlayer config

Manage NthLayer configuration.

## Commands

```bash
nthlayer config show              # Show current configuration
nthlayer config init              # Interactive configuration wizard
nthlayer config set KEY VALUE     # Set a configuration value
```

## nthlayer config show

Display current configuration:

```bash
nthlayer config show
```

```
============================================================
  NthLayer Configuration
============================================================

Config file: /Users/you/.nthlayer/config.yaml

Prometheus:
  Default profile: default
  [default] *
    Type: prometheus
    URL: http://localhost:9090

Grafana:
  Default profile: default
  [default] *
    Type: grafana
    URL: http://localhost:3000
    Org ID: 1
    API Key: ****

Alerting:
  Slack: disabled
  Datadog: disabled
```

### Reveal Secrets

```bash
nthlayer config show --reveal-secrets
```

## nthlayer config init

Interactive wizard for advanced configuration:

```bash
nthlayer config init
```

This is the advanced version of `nthlayer setup` with options for:

- Multiple environment profiles
- Cloud secret backends (Vault, AWS, Azure, GCP, Doppler)
- Detailed alerting configuration

## nthlayer config set

Set individual configuration values:

```bash
# Set Prometheus URL
nthlayer config set prometheus.profiles.default.url http://prometheus:9090

# Set Grafana API key (prompts for secret)
nthlayer config set grafana.profiles.default.api_key --secret
```

Settable keys (`<name>` is a profile name; a profile that does not exist yet is created):

| Key | Value |
|-----|-------|
| `prometheus.default`, `grafana.default` | Name of the default profile |
| `prometheus.profiles.<name>.url` | Prometheus URL |
| `prometheus.profiles.<name>.type` | `prometheus`, `mimir`, `cortex`, `thanos` or `grafana-cloud` |
| `prometheus.profiles.<name>.username` | Username |
| `prometheus.profiles.<name>.password` | Secret path of the password |
| `grafana.profiles.<name>.url` | Grafana URL |
| `grafana.profiles.<name>.type` | `grafana`, `grafana-cloud` or `grafana-enterprise` |
| `grafana.profiles.<name>.api_key` | Secret path of the API key |
| `grafana.profiles.<name>.org_id` | Organisation id, a whole number |
| `alerting.pagerduty.enabled`, `alerting.slack.enabled` | `true` or `false` |
| `alerting.pagerduty.api_key` | Secret path of the API key |
| `alerting.pagerduty.escalation_policy` | Default escalation policy |
| `alerting.slack.webhook_url` | Secret path of the webhook URL |
| `alerting.slack.channel` | Default channel |

Any other key, or a value the key does not take, is reported and the command exits 1 without changing the file. The same happens if the existing configuration file cannot be read: fix or remove it first.

`config set` rewrites the file. Sections it does not manage, such as `secrets:`, are kept; comments are not.

## Configuration File

Located at `~/.nthlayer/config.yaml`:

```yaml
prometheus:
  default: default
  profiles:
    default:
      name: default
      type: prometheus
      url: http://localhost:9090
    production:
      name: production
      type: grafana-cloud
      url: https://prometheus-prod.grafana.net
      username: 12345
      password_secret: prometheus/prod/password

grafana:
  default: default
  profiles:
    default:
      name: default
      type: grafana
      url: http://localhost:3000
      org_id: 1
      api_key_secret: grafana/api_key

alerting:
  slack:
    enabled: false
    webhook_url_secret: slack/webhook_url
    default_channel: "#alerts"
  datadog:
    enabled: false
```

Earlier versions wrote each profile's `type` in a form that could not be read back, so a saved configuration was replaced by the defaults on the next load. Those files are read correctly again after upgrading, and the next `config set` rewrites them in the form above. If `config set` was run on such a file before upgrading, the profiles in it were already replaced by the defaults: check `nthlayer config show` and re-run `nthlayer setup` if they are.

## Environment Variables

Override configuration with environment variables:

```bash
# Prometheus
export NTHLAYER_PROMETHEUS_URL=http://prometheus:9090

# Grafana
export NTHLAYER_GRAFANA_URL=http://grafana:3000
export NTHLAYER_GRAFANA_API_KEY=glsa_xxxxx
export NTHLAYER_GRAFANA_ORG_ID=1
```

## Multiple Profiles

Use different configurations for different environments:

```bash
# Use production profile
export NTHLAYER_PROFILE=production
nthlayer apply service.yaml
```

## See Also

- [nthlayer setup](setup.md) - Quick setup wizard
- [Integrations](../integrations/prometheus.md) - Integration guides
