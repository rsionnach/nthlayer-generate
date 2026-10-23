# drift

Analyze error-budget drift for a service by detecting degradation trends over time.

!!! note "Ships in nthlayer-workers, not nthlayer-generate"
    Drift analysis reads live Prometheus data, so it lives in the runtime tier.
    It is part of the `nthlayer-workers` package (observe module), not the
    `nthlayer` CLI that this site otherwise documents, and has no console script
    of its own. Run it as a Python module:

    ```bash
    pip install nthlayer-workers
    python -m nthlayer_workers.observe drift --help
    ```

## Synopsis

```bash
python -m nthlayer_workers.observe drift --service SERVICE --prometheus-url URL [options]
```

## Description

`drift` queries Prometheus for the `slo:error_budget_remaining:ratio` series of
one SLO over an analysis window, fits a linear trend, classifies the pattern,
projects when the budget will be exhausted, and assigns a severity.

The result is printed as JSON and also stored as a `drift_signal` assessment in
the local assessment store (see `--store`).

## Options

| Option | Required | Description |
|--------|----------|-------------|
| `--service SERVICE` | yes | Service name (matched against the `service` label) |
| `--prometheus-url URL` | yes | Prometheus server URL |
| `--tier {critical,standard,low}` | no | Service tier; selects default window and thresholds (default: `standard`) |
| `--window WINDOW` | no | Analysis window, e.g. `30d`, `14d` (default: the tier's window) |
| `--slo SLO` | no | SLO name (matched against the `slo` label; default: `availability`) |
| `--store PATH` | no | Assessment store path (default: `assessments.db`) |
| `--decision-store PATH` | no | Also write a content-addressed decision record to this SQLite DB |
| `--legacy-store` / `--no-legacy-store` | no | Write to the assessment store (default: enabled) |

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Severity NONE or INFO |
| 1 | Severity WARN, or the analysis failed (message on stderr) |
| 2 | Severity CRITICAL |

## Examples

### Basic Analysis

```bash
python -m nthlayer_workers.observe drift \
  --service payment-api \
  --prometheus-url http://prometheus:9090
```

### Critical-Tier Service, Custom Window

```bash
python -m nthlayer_workers.observe drift \
  --service payment-api \
  --tier critical \
  --window 14d \
  --prometheus-url http://prometheus:9090
```

### Analyze a Specific SLO

```bash
python -m nthlayer_workers.observe drift \
  --service payment-api \
  --slo latency_p99 \
  --prometheus-url http://prometheus:9090
```

## Output

The JSON document contains `service`, `tier`, `slo`, `window`, the data range,
`severity`, `pattern`, a `metrics` block (slope per day/week, current budget,
R², variance, data points), a `projection` block (days until exhaustion,
projected budget at 30/60/90 days, confidence), a `summary`, a
`recommendation`, and the `exit_code`.

## Drift Patterns

| Pattern | Description | Typical Cause |
|---------|-------------|---------------|
| `stable` | No significant trend | Healthy service |
| `gradual_decline` | Slow, steady budget erosion | Creeping technical debt |
| `gradual_improvement` | Slow, steady recovery | Recent fixes taking effect |
| `step_change_down` | Sudden budget drop | Incident, bad deploy |
| `step_change_up` | Sudden improvement | Fix deployed, incident resolved |
| `seasonal` | Recurring pattern (detection disabled by default) | Traffic cycles |
| `volatile` | High variance, no clear trend | Intermittent issues |

## Tier Defaults

| Tier | Default Window | Warn Threshold | Critical Threshold |
|------|----------------|----------------|-------------------|
| `critical` | 30d | -0.2%/week | -0.5%/week |
| `standard` | 30d | -0.5%/week | -1.0%/week |
| `low` | 14d | -1.0%/week | -2.0%/week |

## See Also

- [Deployment Gates](./check-deploy.md) - Error budget gates (`nthlayer-workers gate`)
- [SLOs & Error Budgets](../concepts/slos.md) - Understanding SLOs
