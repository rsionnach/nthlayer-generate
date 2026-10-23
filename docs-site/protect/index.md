# Protect

**Block risky deploys before they cause incidents.**

NthLayer's protection layer enforces reliability policies in production. When error budget is exhausted, deployments are blocked - automatically.

## The Protection Stack

| Feature | Command | What It Does |
|---------|---------|--------------|
| **Deployment Gates** | `nthlayer-workers gate` | Block deploys when budget exhausted |
| **Drift Detection** | `python -m nthlayer_workers.observe drift` | Detect reliability degradation trends |
| **Intelligent Alerts** | `nthlayer alerts` | Context-aware alert evaluation and budget explanations |
| **Metric Recommendations** | `nthlayer recommend-metrics` | Validate instrumentation coverage |
| **Error Budgets** | `nthlayer slo collect` | Real-time budget consumption |

Deployment gates and drift detection read live state, so they ship in the
`nthlayer-workers` package rather than the `nthlayer` CLI.

## Why Deployment Gates?

Traditional monitoring tells you **after** a deployment causes problems:

```
Deploy → Incident → Page → Investigate → Rollback → Postmortem
                      ↑
               "The deploy broke it"
```

Deployment gates tell you **before**:

```
Check Budget → Block/Allow → Deploy
      ↑
  "Budget exhausted - don't deploy"
```

## Quick Start

### Check Before Deploy

```bash
nthlayer-workers gate --service payment-api --core-url http://nthlayer-core:8000
```

The gate reads the service's SLO assessments from nthlayer-core, prints its
decision as JSON, and records a `deploy_gate` assessment.

## Exit Codes

Deployment gates use exit codes for CI/CD integration:

| Code | Decision | Pipeline Action |
|------|----------|-----------------|
| `0` | Approved or Warning | Deploy proceeds (a warning is printed on stderr) |
| `1` | Not evaluated | Gate could not reach core or read state — your pipeline decides |
| `2` | Blocked | Fail pipeline |

## Tier-Based Thresholds

Default thresholds vary by service tier:

| Tier | Warning | Blocking |
|------|---------|----------|
| Critical | ≤20% remaining | ≤10% remaining |
| Standard | ≤20% remaining | None (advisory) |
| Low | ≤30% remaining | None (advisory) |

Critical services block deploys at 10% remaining budget. Lower tiers only warn.

## Custom Policies

!!! warning "Not applied by the gate commands"
    Neither `python -m nthlayer_workers.observe check-deploy` nor
    `nthlayer-workers gate` reads `DeploymentGate` resources today: both
    evaluate with the tier-based thresholds above. The settings below are
    accepted in a manifest but do not change a gate decision.

Override defaults with a `DeploymentGate` resource:

```yaml
resources:
  - kind: DeploymentGate
    name: strict-gate
    spec:
      thresholds:
        warning: 30
        blocking: 15

      conditions:
        # Stricter during business hours
        - name: business-hours
          when: "hour >= 9 AND hour <= 17 AND weekday"
          blocking: 20

        # Complete freeze during incidents
        - name: low-budget
          when: "budget_remaining < 5"
          blocking: 100
```

## CI/CD Integration

### GitHub Actions

```yaml
jobs:
  deploy:
    steps:
      - name: Check Deployment Gate
        run: |
          nthlayer-workers gate --service api \
            --commit-sha ${{ github.sha }} \
            --core-url ${{ secrets.NTHLAYER_CORE_URL }}

      - name: Deploy
        if: success()  # Only if gate passed
        run: kubectl apply -f generated/
```

### ArgoCD PreSync Hook

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: deployment-gate
  annotations:
    argocd.argoproj.io/hook: PreSync
spec:
  template:
    spec:
      containers:
        - name: check
          image: ghcr.io/nthlayer/nthlayer:latest
          command:
            - nthlayer-workers
            - gate
            - --service
            - payment-api
            - --core-url
            - $(NTHLAYER_CORE_URL)
```

## Drift Detection

Deployment gates check the **current** budget state. Drift detection looks at **trends** over time:

```
┌─────────────────────────────────────────────────────────────────────┐
│  Deployment Gate: "Is budget OK right now?"                         │
│  Drift Detection: "Is budget trending toward exhaustion?"           │
└─────────────────────────────────────────────────────────────────────┘
```

### Analyze Drift

```bash
python -m nthlayer_workers.observe drift \
  --service payment-api \
  --prometheus-url http://prometheus:9090
```

The result is printed as JSON with the severity, pattern, trend, and projected
days to exhaustion. Exit code 0 = none/info, 1 = warn, 2 = critical.

### Drift Patterns

| Pattern | What It Means | Action |
|---------|---------------|--------|
| Gradual Decline | Slow erosion over time | Investigate technical debt |
| Step Change Down | Sudden drop (incident/bad deploy) | Immediate investigation |
| Volatile | High variance, no trend | Check for intermittent issues |
| Stable | No significant trend | Continue monitoring |

## The Google SRE Connection

NthLayer automates the [Error Budget Policy](https://sre.google/sre-book/embracing-risk/) from the Google SRE Book:

> "If our SLO says we can have 0.1% downtime per month, and we've already used 0.08%, we should be very careful about deploying new features."

| SRE Concept | Manual Process | NthLayer Automation |
|-------------|----------------|---------------------|
| Error Budget Policy | Spreadsheet tracking | `nthlayer-workers gate` |
| Release Freeze | Calendar reminders | Automatic blocking |

## Intelligent Alerts

Evaluate alert rules and get context-aware explanations:

```bash
# Evaluate alerts against live data
nthlayer alerts evaluate services/payment-api.yaml \
  --prometheus-url http://prometheus:9090

# Simulate burn and see what would fire
nthlayer alerts test services/payment-api.yaml --simulate-burn 90
```

The explanation engine provides technology-specific investigation actions based on your service's dependencies and type.

See [nthlayer alerts](../commands/alerts.md) for full reference.

## Next Steps

- [Deployment Gates](../commands/check-deploy.md) - Full command reference
- [Drift Detection](../commands/drift.md) - Trend analysis command
- [SLO Portfolio](../commands/portfolio.md) - Organization-wide view
- [Reliability Scorecard](../commands/scorecard.md) - Per-service scoring
- [Intelligent Alerts](../commands/alerts.md) - Alert evaluation and simulation
- [Error Budgets](../concepts/slos.md) - Understanding SLOs
- [CI/CD Integration](../integrations/cicd.md) - Pipeline examples
