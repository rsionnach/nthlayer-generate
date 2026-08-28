# nthlayer init

Create a new service specification file, interactively or from flags.

## Synopsis

```bash
nthlayer init [SERVICE_NAME] [options]
```

## Description

The `init` command guides you through creating a service YAML file with interactive prompts, auto-generating resources from your selections. For CI and scripts, [`--no-interactive`](#non-interactive-mode) skips the prompts entirely.

The file is written to `<service-name>.yaml` in the current directory, alongside a `.nthlayer/config.yaml`. There is no output-path option; `cd` to where you want the file. `init` never overwrites an existing manifest — it errors instead.

## Options

| Option | Description |
|--------|-------------|
| `SERVICE_NAME` | Positional. Service name, lowercase-with-hyphens. Prompted for if omitted. |
| `--team TEAM` | Team name. Prompted for if omitted. |
| `--template TEMPLATE` | Use a pre-built template (see [Templates](#templates)) |
| `--no-interactive` | Skip every prompt and take the defaults (tier `standard`, type `api`) |

## Interactive Mode

```bash
nthlayer init
```

The wizard prompts for:

1. **Service name** - e.g., `payment-api`
2. **Team** - e.g., `platform`
3. **Tier** - critical, standard, or low
4. **Type** - api, worker, stream, batch, database, ai-gate, or x-web
5. **Dependencies** - databases, caches, queues

### Example Session

```
╭──────────────────────────────────────────────────────────────╮
│  NthLayer Service Generator                                  │
╰──────────────────────────────────────────────────────────────╯

Service name: payment-api
Team: payments

Select service tier:
    critical - Tier 1 - Critical
  ❯ standard - Tier 2 - Standard
    low - Tier 3 - Low Priority

Select service type:
  ❯ api       - REST/GraphQL API service
    worker    - Background job processor
    stream    - Stream processing service (Kafka, etc.)
    batch     - Batch processing job
    database  - Managed datastore or data service
    ai-gate   - AI/LLM service that makes or gates decisions
    x-web     - Web application (frontend) - NthLayer extension type

Select dependencies (space to toggle):
  ◉ postgresql
  ○ mysql
  ◉ redis
  ○ mongodb
  ○ elasticsearch
  ○ kafka
  ○ rabbitmq
  ○ dynamodb

✓ Created payment-api.yaml
✓ Created .nthlayer/
```

## Generated Output

Based on your selections, `init` generates appropriate resources. Both blocks below are verbatim output, comments included.

### Critical Tier API

```yaml
service:
  name: payment-api
  team: payments
  tier: critical
  type: api

resources:
  # Availability SLO - critical tier
  - kind: SLO
    name: availability
    spec:
      objective: 99.95
      window: 30d
      indicator:
        type: availability

  # Latency SLO - p95
  - kind: SLO
    name: latency-p95
    spec:
      objective: 99.0
      window: 30d
      indicator:
        type: latency
        percentile: 95
        threshold_ms: 500

  # PagerDuty integration
  - kind: PagerDuty
    name: primary
    spec:
      urgency: high
      auto_create: true

  # Service dependencies
  - kind: Dependencies
    name: infrastructure
    spec:
      databases:
        - name: payment-api-postgresql
          type: postgresql
          criticality: high
      caches:
        - name: payment-api-redis
          type: redis
          criticality: medium
```

### Standard Tier Worker

```yaml
service:
  name: email-worker
  team: notifications
  tier: standard
  type: worker

resources:
  # Availability SLO
  - kind: SLO
    name: availability
    spec:
      objective: 99.9
      window: 30d
      indicator:
        type: availability
```

## Resource Auto-Generation

| Selection | Generated Resources |
|-----------|---------------------|
| Tier: critical | 99.95% availability SLO, plus a PagerDuty resource |
| Tier: standard, low | 99.9% availability SLO |
| Type: api, x-web | Latency SLO (p95, 500ms) |
| Dependencies | Dependencies resource |

Only `critical` currently differs: `standard` and `low` generate the same 99.9% objective.

## Templates

Use pre-built templates for common patterns:

```bash
# List available templates (a separate command, not a flag on init)
nthlayer list-templates

# Use a template
nthlayer init payment-api --team payments --template critical-api
```

### Built-in Templates

| Template | Tier | Type | Description |
|----------|------|------|-------------|
| `critical-api` | critical | api | High-traffic API with 99.9% availability SLO and critical PagerDuty escalation |
| `standard-api` | standard | api | Standard API with 99.5% availability SLO and low urgency PagerDuty |
| `low-api` | low | api | Low-priority API with 99.0% availability SLO |
| `background-job` | standard | worker | Background worker service with success rate SLO |
| `pipeline` | standard | batch | Data pipeline with 95% success rate SLO |

Custom templates are discovered alongside these; `nthlayer list-templates` shows the full set for your project.

## Non-Interactive Mode

For CI, scripts, or any context without a TTY, `--no-interactive` skips every prompt:

```bash
nthlayer init my-service --team platform --no-interactive
```

Because nothing is prompted for, the two required values must be supplied on the command line: the positional service name and `--team`. Omitting either is an error, not a prompt.

Everything else takes a default:

| Value | Default without prompts |
|-------|-------------------------|
| Tier | `standard` |
| Type | `api` |
| Dependencies | none |

`--template` overrides the tier and type defaults with the template's own, so a fully-specified non-interactive run looks like:

```bash
nthlayer init my-service --team platform --template critical-api --no-interactive
```

That writes a `critical`-tier `api` manifest. Tier and type are not otherwise settable from the command line — pick a template, or edit the generated file.

## See Also

- [nthlayer apply](./apply.md) - Generate configs from service spec
- [Service YAML Schema](../reference/service-yaml.md) - Full specification
- [Quick Start](../getting-started/quick-start.md) - Getting started guide
