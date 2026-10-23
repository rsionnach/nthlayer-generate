# Reliability Shift Left

## What is Shift Left?

"Shift Left" means moving validation and testing earlier in the software development lifecycle. Instead of discovering issues in production, you catch them during development or CI/CD.

**Traditional approach:**
```
Code → Deploy → Monitor → Incident → Fix → Repeat
                           ↑
                   "We found out the hard way"
```

**Shift Left approach:**
```
Code → Validate → Verify → Gate → Deploy → Monitor
         ↑          ↑        ↑
   "Is it valid?" "Does it exist?" "Is it safe?"
```

## How NthLayer Shifts Reliability Left

### 1. Contract Verification (`nthlayer validate-slo`)

Before deploying, verify that the metrics your SLOs depend on actually exist in Prometheus:

```bash
nthlayer validate-slo service.yaml --prometheus-url $PROM_URL
```

**Pipeline integration:**
```yaml
# GitHub Actions
- name: Verify SLO Metrics
  run: nthlayer validate-slo service.yaml --prometheus-url $PROM_URL
  # Fails pipeline if metrics don't exist
```

### 2. Deployment Gates (`nthlayer-workers gate`)

Block deployments when error budget is exhausted. The gate ships in the
`nthlayer-workers` package and reads SLO state from a running nthlayer-core:

```bash
nthlayer-workers gate --service payment-api --core-url $NTHLAYER_CORE_URL
```

**Exit codes:**
- `0` - Deploy approved (or approved with a warning)
- `1` - Gate could not be evaluated
- `2` - Blocked (budget exhausted)

### 3. PromQL Validation (`nthlayer apply --lint`)

Catch syntax errors before they reach Prometheus:

```bash
$ nthlayer apply service.yaml --lint

Applied 4 resources in 0.3s → generated/payment-api/

Validating alerts with pint...
  ✓ 12 rules validated

  ⚠ [promql/series] Line 45: metric "http_errors_total" not found
```

## The Google SRE Connection

NthLayer automates concepts from the [Google SRE Book](https://sre.google/sre-book/):

| SRE Concept | Manual Process | NthLayer Automation |
|-------------|----------------|---------------------|
| **Production Readiness Review** | Multi-week checklist | `nthlayer validate-slo` in CI |
| **Error Budget Policy** | Spreadsheet tracking | `nthlayer-workers gate` |
| **Release Engineering** | Manual runbooks | Generated artifacts + GitOps |
| **Monitoring Standards** | Wiki pages | `service.yaml` spec |

## CI/CD Pipeline Example

### Tekton Pipeline

```yaml
apiVersion: tekton.dev/v1
kind: Pipeline
metadata:
  name: deploy-with-reliability-gates
spec:
  tasks:
    - name: generate
      taskRef:
        name: nthlayer-apply
      params:
        - name: service-file
          value: service.yaml

    - name: verify-metrics
      taskRef:
        name: nthlayer-validate-slo
      runAfter: [generate]

    - name: check-budget
      taskRef:
        name: nthlayer-gate
      runAfter: [verify-metrics]

    - name: deploy
      taskRef:
        name: kubectl-apply
      runAfter: [check-budget]
      # Only runs if all gates pass
```

### GitHub Actions

```yaml
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install NthLayer
        run: pip install nthlayer nthlayer-workers

      - name: Generate & Lint
        run: nthlayer apply service.yaml --lint

      - name: Verify Metrics Exist
        run: nthlayer validate-slo service.yaml --prometheus-url $PROM_URL
        env:
          PROM_URL: ${{ secrets.PROMETHEUS_URL }}

      - name: Check Deployment Gate
        run: nthlayer-workers gate --service payment-api --commit-sha $GITHUB_SHA --core-url $NTHLAYER_CORE_URL
        env:
          NTHLAYER_CORE_URL: ${{ secrets.NTHLAYER_CORE_URL }}

      - name: Deploy
        if: success()
        run: kubectl apply -f generated/
```

## Benefits

### Prevent, Don't React

| Traditional | Shift Left |
|-------------|------------|
| Deploy first, monitor later | Validate before deploy |
| Alert after incident | Block risky deploys |
| SLOs as documentation | SLOs as enforcement |
| Manual PRR checklist | Automated verification |

### Measurable Outcomes

Teams using reliability shift left typically see:

- **60% reduction** in incidents caused by missing monitoring
- **80% faster** SLO setup (5 min vs 20 hours)
- **Zero** deploys with missing metrics
- **Reduced MTTR** - dashboards exist from day 1

## See Also

- [validate-slo](../commands/validate-slo.md) - SLO metric verification reference
- [Deployment Gates](../commands/check-deploy.md) - Full `nthlayer-workers gate` reference
- [SLO Concepts](./slos.md) - Understanding SLOs and error budgets
