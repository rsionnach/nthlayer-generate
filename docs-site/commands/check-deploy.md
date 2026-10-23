# Deployment Gate (`nthlayer-workers gate`)

Decide whether a deployment should proceed, based on the service's error budget.

!!! note "Ships in nthlayer-workers, not nthlayer-generate"
    The deployment gate reads live SLO state, so it lives in the runtime tier.
    It is the `gate` subcommand of the `nthlayer-workers` console script from the
    `nthlayer-workers` package, not part of the `nthlayer` CLI that this site
    otherwise documents. There is no `nthlayer check-deploy` command.

    ```bash
    pip install nthlayer-workers
    nthlayer-workers gate --help
    ```

## Synopsis

```bash
nthlayer-workers gate --service SERVICE [--tier TIER] [--commit-sha SHA] [--core-url URL]
```

## Description

`gate` talks to a running nthlayer-core API, not to Prometheus directly:

1. If `--tier` is not given, it fetches the service's manifest from core and
   uses its `tier` (falling back to `standard` when the manifest has none).
2. It fetches the service's `slo_status` assessments from core.
3. It computes the remaining error budget across the service's SLOs and
   compares it with the tier's warning and blocking thresholds.
4. It submits a `deploy_gate` assessment back to core, recording the decision,
   the thresholds, the commit SHA, and the SLO assessments it was based on.
5. It prints the result as JSON.

A service with no `slo_status` assessments is approved by default.

## Options

| Option | Required | Description |
|--------|----------|-------------|
| `--service SERVICE` | yes | Service name |
| `--tier TIER` | no | Service tier (default: resolved from the manifest in core) |
| `--commit-sha SHA` | no | Commit SHA, recorded in the `deploy_gate` assessment (informational) |
| `--core-url URL` | no | nthlayer-core API URL (default: `http://localhost:8000`) |

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | APPROVED or WARNING — deploy allowed (a WARNING also prints a `WARNING:` line on stderr) |
| 1 | The gate could not be evaluated (core unreachable, manifest or assessments unavailable) — your deploy script decides |
| 2 | BLOCKED — do not deploy |

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

### Basic Check

```bash
nthlayer-workers gate --service payment-api --core-url http://nthlayer-core:8000
```

### CI/CD Integration

```bash
nthlayer-workers gate \
  --service payment-api \
  --commit-sha "$GITHUB_SHA" \
  --core-url "$NTHLAYER_CORE_URL"
status=$?

if [ "$status" -eq 2 ]; then
  echo "Deployment blocked - error budget exhausted"
  exit 1
elif [ "$status" -eq 1 ]; then
  echo "Gate could not be evaluated"
  exit 1   # or 0, if your policy is to fail open
fi
```

## See Also

- [Deployment Gates Concept](../concepts/deployment-gates.md)
- [drift](./drift.md) - Error-budget trend analysis
- [SLO Command](./slo.md)
