# verify

Verify that the metrics your SLOs declare exist in Prometheus (contract verification).

!!! note "Ships in nthlayer-workers, not nthlayer-generate"
    This command reads live or collected state, so it lives in the runtime tier.
    It is part of the `nthlayer-workers` package (observe module), not the
    `nthlayer` CLI that this site otherwise documents, and has no console script
    of its own. Run it as a Python module:

    ```bash
    pip install nthlayer-workers
    python -m nthlayer_workers.observe verify --help
    ```

## Synopsis

```bash
python -m nthlayer_workers.observe verify --specs-dir DIR --prometheus-url URL [options]
```

## Description

`verify` loads every OpenSRM spec (`.yaml`/`.yml`) in `--specs-dir`, extracts the
metrics each service's SLO queries reference, and checks each against
Prometheus. For every service with at least one declared metric it prints

```
<service>: <found>/<declared> metrics verified (OK|MISSING)
```

and stores a `verification` assessment (declared and found counts, missing
critical and missing optional metric names) in the assessment store.

If the directory contains no SLO definitions it says so on stderr and exits 0.

## Options

| Option | Required | Description |
|--------|----------|-------------|
| `--specs-dir DIR` | yes | Directory of OpenSRM spec YAMLs |
| `--prometheus-url URL` | yes | Prometheus server URL |
| `--store PATH` | no | Assessment store path (default: `assessments.db`) |
| `--decision-store PATH` | no | Also write a content-addressed decision record to this SQLite DB |
| `--legacy-store` / `--no-legacy-store` | no | Write to the assessment store (default: enabled) |

## Exit Codes

The worst result across all services:

| Code | Meaning |
|------|---------|
| 0 | All declared metrics found |
| 1 | Only optional metrics missing |
| 2 | Critical metrics missing |

## Example

```bash
python -m nthlayer_workers.observe verify \
  --specs-dir services/ \
  --prometheus-url http://prometheus:9090
```

## See Also

- [validate-slo](./validate-slo.md) - Per-file SLO metric check in the `nthlayer` CLI
- [Contracts & Assumptions](../concepts/contracts.md) - What "metric exists" means
