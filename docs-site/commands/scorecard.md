# scorecard

Score each service's reliability from the assessment store.

!!! note "Ships in nthlayer-workers, not nthlayer-generate"
    This command reads live or collected state, so it lives in the runtime tier.
    It is part of the `nthlayer-workers` package (observe module), not the
    `nthlayer` CLI that this site otherwise documents, and has no console script
    of its own. Run it as a Python module:

    ```bash
    pip install nthlayer-workers
    python -m nthlayer_workers.observe scorecard --help
    ```

## Synopsis

```bash
python -m nthlayer_workers.observe scorecard [--store PATH] [--format {table,json}]
```

## Description

`scorecard` reads `slo_status` assessments from a local assessment store, which
`python -m nthlayer_workers.observe collect --specs-dir DIR --prometheus-url URL`
writes (default store: `assessments.db`). With no such assessments it prints
`No slo_status assessments found. Run 'collect' first.` and exits 0.

The score is the share of a service's SLOs whose status is `HEALTHY`, as
0-100. A service with three SLOs, two healthy, scores 66.7 in JSON output
(rounded to one decimal) and shows as 67 in table output (rounded to a whole
number). Services are listed
highest score first.

## Options

| Option | Required | Description |
|--------|----------|-------------|
| `--store PATH` | no | Assessment store path (default: `assessments.db`) |
| `--format {table,json}` | no | Output format (default: `table`) |

## Exit Codes

Always 0. `scorecard` reports; it does not gate.

## Examples

```bash
python -m nthlayer_workers.observe scorecard
python -m nthlayer_workers.observe scorecard --format json
```

## Output

Table output: one line per service, `<service>: <score>/100 (<status>, <n> SLOs)`.

JSON output: a list of `{service, score, status, slo_count}`.

## See Also

- [portfolio](./portfolio.md) - SLO health from the same data
