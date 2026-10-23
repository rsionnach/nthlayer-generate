# blast-radius

Estimate the deployment blast radius of a service from its dependency graph.

!!! note "Ships in nthlayer-workers, not nthlayer-generate"
    Blast-radius analysis queries live systems, so it lives in the runtime tier.
    It is part of the `nthlayer-workers` package (observe module), not the
    `nthlayer` CLI that this site otherwise documents, and has no console script
    of its own. Run it as a Python module:

    ```bash
    pip install nthlayer-workers
    python -m nthlayer_workers.observe blast-radius --help
    ```

## Synopsis

```bash
python -m nthlayer_workers.observe blast-radius --service SERVICE [--prometheus-url URL]
```

## Description

`blast-radius` builds a dependency graph for the service, counts the services
that would be affected by a change to it, and assigns a risk level.

With `--prometheus-url`, the graph is discovered from Prometheus. **Without it,
the command runs against a built-in demo graph**, not your services — useful
for trying the command out, meaningless for a real service.

## Options

| Option | Required | Description |
|--------|----------|-------------|
| `--service SERVICE` | yes | Service name |
| `--prometheus-url URL` | no | Prometheus server URL; omit to use the demo graph |

## Exit Codes

| Code | Risk level |
|------|------------|
| 0 | `low` |
| 1 | `medium` |
| 2 | `high` or `critical` |

## Examples

```bash
# Real graph from Prometheus
python -m nthlayer_workers.observe blast-radius \
  --service checkout-service \
  --prometheus-url http://prometheus:9090

# Demo graph
python -m nthlayer_workers.observe blast-radius --service checkout-service
```

## Output

A JSON object with `service`, `tier`, `risk_level`, `total_services_affected`,
`critical_services_affected`, and `recommendation`.

## See Also

- [dependencies](./deps.md) - Raw dependency discovery
- [Deployment Gates](./check-deploy.md) - Error budget gates
