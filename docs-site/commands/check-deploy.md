# check-deploy

Decide whether a deployment should proceed, based on the service's error budget.

!!! note "Ships in nthlayer-workers, not nthlayer-generate"
    The deployment gate reads collected SLO state, so it lives in the runtime
    tier. It is part of the `nthlayer-workers` package, not the `nthlayer` CLI
    that this site otherwise documents; there is no `nthlayer check-deploy`.
    It comes in two forms:

    - `python -m nthlayer_workers.observe check-deploy` (this page) reads a
      local assessment store. The observe module has no console script.
    - `nthlayer-workers gate` reads from a running nthlayer-core instead
      (see [below](#nthlayer-workers-gate)).

    ```bash
    pip install nthlayer-workers
    python -m nthlayer_workers.observe check-deploy --help
    ```

## Synopsis

```bash
python -m nthlayer_workers.observe check-deploy --service SERVICE [options]
```

## Description

`check-deploy` reads the service's latest `slo_status` assessments from the
local assessment store (written by
`python -m nthlayer_workers.observe collect --specs-dir DIR --prometheus-url URL`),
computes the remaining error budget, and compares it with the tier's warning
and blocking thresholds. It stores a `deploy_gate` assessment recording the
decision and prints the result as JSON.

A service with no `slo_status` assessments is approved by default.

Thresholds are the tier defaults. Custom `DeploymentGate` thresholds or
conditions in a manifest are **not** applied by this command.

## Options

| Option | Required | Description |
|--------|----------|-------------|
| `--service SERVICE` | yes | Service name |
| `--tier {critical,standard,low}` | no | Service tier; selects thresholds (default: `standard`) |
| `--store PATH` | no | Assessment store path (default: `assessments.db`) |
| `--decision-store PATH` | no | Also write a content-addressed decision record to this SQLite DB |
| `--legacy-store` / `--no-legacy-store` | no | Write to the assessment store (default: enabled) |

## Exit Codes

| Code | Decision | Meaning |
|------|----------|---------|
| 0 | APPROVED | Budget healthy, safe to deploy |
| 1 | WARNING | Budget below the warning threshold |
| 2 | BLOCKED | Budget below the blocking threshold, do not deploy |

## Output

```json
{
  "service": "payment-api",
  "tier": "critical",
  "decision": "WARNING",
  "budget_remaining_pct": 18.4,
  "message": "...",
  "recommendations": ["..."]
}
```

## Examples

```bash
python -m nthlayer_workers.observe collect \
  --specs-dir services/ \
  --prometheus-url http://prometheus:9090

python -m nthlayer_workers.observe check-deploy \
  --service payment-api \
  --tier critical

if [ $? -eq 2 ]; then
  echo "Deployment blocked - error budget exhausted"
  exit 1
fi
```

## nthlayer-workers gate

The same evaluation, backed by nthlayer-core instead of a local store. It
fetches the service's `slo_status` assessments (and, without `--tier`, the
tier from its manifest, falling back to `standard`) from core, and submits the
`deploy_gate` assessment back to core.

```bash
nthlayer-workers gate --service SERVICE [--tier TIER] [--commit-sha SHA] [--core-url URL]
```

| Option | Required | Description |
|--------|----------|-------------|
| `--service SERVICE` | yes | Service name |
| `--tier TIER` | no | Service tier (default: resolved from the manifest in core) |
| `--commit-sha SHA` | no | Commit SHA, recorded in the `deploy_gate` assessment |
| `--core-url URL` | no | nthlayer-core API URL (default: `http://localhost:8000`) |

Its exit codes differ from `check-deploy`'s: **0** = APPROVED or WARNING (a
WARNING also prints a `WARNING:` line on stderr), **1** = the gate could not be
evaluated (core unreachable, manifest or assessments unavailable), **2** =
BLOCKED. Like `check-deploy`, it applies tier default thresholds only.

## See Also

- [Deployment Gates Concept](../concepts/deployment-gates.md)
- [drift](./drift.md) - Error-budget trend analysis
- [portfolio](./portfolio.md) - SLO health across services
