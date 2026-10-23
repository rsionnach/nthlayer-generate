# Commands Overview

NthLayer provides a comprehensive CLI for managing your reliability stack.

## Generation Commands

| Command | Description |
|---------|-------------|
| [`nthlayer apply`](apply.md) | Generate all configs from service spec |
| `nthlayer plan` | Preview what resources would be generated (dry-run) |
| `nthlayer generate-dashboard` | Generate Grafana dashboard |
| `nthlayer generate-alerts` | Generate Prometheus alerts |
| `nthlayer generate-recording-rules` | Generate Prometheus recording rules |
| [`nthlayer generate-loki-alerts`](generate-loki-alerts.md) | Generate Loki LogQL alerts |

## Validation Commands

| Command | Description |
|---------|-------------|
| [`nthlayer validate-spec`](validate-spec.md) | Validate service.yaml against OPA policies |
| [`nthlayer validate-metadata`](validate-metadata.md) | Validate rule metadata (labels, annotations, URLs) |
| [`nthlayer validate-slo`](validate-slo.md) | Validate SLO metrics exist in Prometheus |
| [`nthlayer recommend-metrics`](recommend-metrics.md) | Recommend metrics based on service type and runtime |
| `nthlayer lint` | Lint Prometheus alert rules with pint |

## Dependency Intelligence

| Command | Description |
|---------|-------------|
| [`nthlayer ownership`](ownership.md) | Show service ownership attribution |
| [`nthlayer identity`](identity.md) | Service identity resolution and management |

## SLO & Error Budget

| Command | Description |
|---------|-------------|
| [`nthlayer slo`](slo.md) | SLO and error budget commands |

## Alerts & Monitoring

| Command | Description |
|---------|-------------|
| [`nthlayer alerts`](alerts.md) | Evaluate, simulate, and test alert rules |

## Environment Management

| Command | Description |
|---------|-------------|
| [`nthlayer list-environments`](environments.md) | List available environments |
| `nthlayer diff-envs` | Compare configurations between environments |
| `nthlayer validate-env` | Validate an environment configuration |

## Runtime Commands (nthlayer-workers)

These read live system state, so they ship in the `nthlayer-workers` package
rather than in the `nthlayer` CLI documented on the rest of this page. The
gate is a subcommand of the `nthlayer-workers` console script; the observe
commands have no console script and run as
`python -m nthlayer_workers.observe <command>`.

| Command | Description |
|---------|-------------|
| [`nthlayer-workers gate`](check-deploy.md) | Deployment gate (error budget validation) |
| [observe `drift`](drift.md) | Analyze error-budget drift for a service |
| [observe `dependencies`](deps.md) | Discover service dependencies |
| [observe `blast-radius`](blast-radius.md) | Estimate deployment blast radius |

## Setup & Configuration

| Command | Description |
|---------|-------------|
| [`nthlayer setup`](setup.md) | Interactive first-time setup |
| [`nthlayer init`](init.md) | Initialize new NthLayer service |
| [`nthlayer migrate`](migrate.md) | Migrate legacy format to OpenSRM |
| [`nthlayer config`](config.md) | Configuration management |
| `nthlayer secrets` | Secrets management |

## Quick Reference

```bash
# Generate configs
nthlayer apply service.yaml

# Validate before deployment
nthlayer validate-slo service.yaml

# Check SLO status
nthlayer slo show service.yaml
```

## Getting Help

```bash
nthlayer --help
nthlayer <command> --help
```

## See Also

- [CLI Reference](../reference/cli.md) - Complete command reference
- [Getting Started](../getting-started/quick-start.md) - First steps with NthLayer
