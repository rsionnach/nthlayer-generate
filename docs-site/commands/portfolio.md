# portfolio

Aggregate SLO health across every service in the assessment store.

!!! note "Ships in nthlayer-workers, not nthlayer-generate"
    This command reads live or collected state, so it lives in the runtime tier.
    It is part of the `nthlayer-workers` package (observe module), not the
    `nthlayer` CLI that this site otherwise documents, and has no console script
    of its own. Run it as a Python module:

    ```bash
    pip install nthlayer-workers
    python -m nthlayer_workers.observe portfolio --help
    ```

## Synopsis

```bash
python -m nthlayer_workers.observe portfolio [--store PATH] [--format {table,json}]
```

## Description

`portfolio` reads `slo_status` assessments from a local assessment store, which
`python -m nthlayer_workers.observe collect --specs-dir DIR --prometheus-url URL`
writes (default store: `assessments.db`). With no such assessments it prints
`No slo_status assessments found. Run 'collect' first.` and exits 0.

Each service gets an overall status, the worst of its SLOs' statuses
(`HEALTHY`, `WARNING`, `CRITICAL`, `EXHAUSTED`). Services whose status is
unknown or has no data are listed but not counted in any bucket.

## Options

| Option | Required | Description |
|--------|----------|-------------|
| `--store PATH` | no | Assessment store path (default: `assessments.db`) |
| `--format {table,json}` | no | Output format (default: `table`) |

## Exit Codes

Always 0. `portfolio` reports; it does not gate.

## Examples

```bash
# Collect first, then aggregate
python -m nthlayer_workers.observe collect \
  --specs-dir services/ \
  --prometheus-url http://prometheus:9090
python -m nthlayer_workers.observe portfolio

# JSON for dashboards or scripts
python -m nthlayer_workers.observe portfolio --format json
```

## Output

Table output prints the service count, the healthy/warning/critical/exhausted
counts, and each service with its SLOs' status and current SLI.

JSON output has `total_services`, `healthy`, `warning`, `critical`,
`exhausted`, and a `services` list; each entry has `service`,
`overall_status`, and `slos` (`name`, `status`, `current_sli`,
`percent_consumed`).

## See Also

- [scorecard](./scorecard.md) - Per-service score from the same data
- [Deployment Gates](./check-deploy.md) - Gate on the same assessments
