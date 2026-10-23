# Dependencies (observe `dependencies`)

Discover a service's upstream and downstream dependencies.

!!! note "Ships in nthlayer-workers, not nthlayer-generate"
    Dependency discovery queries live systems, so it lives in the runtime tier.
    It is part of the `nthlayer-workers` package (observe module), not the
    `nthlayer` CLI that this site otherwise documents, and has no console script
    of its own. The subcommand is named `dependencies`. Run it as a Python module:

    ```bash
    pip install nthlayer-workers
    python -m nthlayer_workers.observe dependencies --help
    ```

## Synopsis

```bash
python -m nthlayer_workers.observe dependencies --service SERVICE --prometheus-url URL [options]
```

## Description

`dependencies` asks the configured providers for the service's dependency
edges, prints the result as JSON, and stores it as a `dependency_graph`
assessment in the local assessment store (see `--store`).

Prometheus is the only provider this command configures. `--prometheus-url` is
optional to the argument parser, but without it no provider is configured and
the command exits 1 with `No providers configured. Use --prometheus-url.`

## Options

| Option | Required | Description |
|--------|----------|-------------|
| `--service SERVICE` | yes | Service name |
| `--prometheus-url URL` | in practice | Prometheus server URL (the only dependency provider) |
| `--store PATH` | no | Assessment store path (default: `assessments.db`) |
| `--decision-store PATH` | no | Also write a content-addressed decision record to this SQLite DB |
| `--legacy-store` / `--no-legacy-store` | no | Write to the assessment store (default: enabled) |

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Discovery ran and the result was printed |
| 1 | No provider configured (`--prometheus-url` missing) |

## Example

```bash
python -m nthlayer_workers.observe dependencies \
  --service checkout-service \
  --prometheus-url http://prometheus:9090
```

## Output

A JSON object with:

| Field | Description |
|-------|-------------|
| `dependencies_discovered` | Total number of dependency edges found |
| `upstream` | What this service calls: `service`, `type`, `provider` per entry |
| `downstream` | What calls this service: `service`, `type`, `provider` per entry |
| `providers_queried` | Providers that were asked |
| `errors` | Provider errors, if any |

## See Also

- [blast-radius](./blast-radius.md) - Impact of a change, computed over the dependency graph
- [ownership](./ownership.md) - Who owns a service
