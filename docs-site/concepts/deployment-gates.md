# Deployment Gates

Deployment gates block or warn about deployments when error budget is exhausted. This is the core of NthLayer's **Shift Left** approach - catching reliability issues before they reach production.

## Why Deployment Gates?

Traditional monitoring tells you **after** a deployment causes problems. Deployment gates tell you **before** - enabling you to:

- **Prevent incidents** by blocking deploys when reliability is already degraded
- **Make informed decisions** with real-time error budget visibility
- **Enforce SLO discipline** across your organization

## How It Works

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   CI/CD     │────▶│check-deploy │────▶│     SLO     │
│  Pipeline   │     │   / gate    │     │ assessments │
└─────────────┘     └─────────────┘     └─────────────┘
                           │
                           ▼
                    ┌─────────────┐
                    │   Result    │
                    │ 0=Approved  │
                    │ 1=Warning   │
                    │ 2=Blocked   │
                    └─────────────┘
```

1. **Pipeline triggers**: Your CI/CD pipeline calls `python -m nthlayer_workers.observe check-deploy` (reads a local assessment store) or `nthlayer-workers gate` (reads nthlayer-core), both from the `nthlayer-workers` package
2. **Read SLO state**: The gate reads the service's `slo_status` assessments
3. **Calculate budget**: Error budget consumption is calculated
4. **Return decision**: Exit code determines if deploy proceeds — see [the command reference](../commands/check-deploy.md) for each form's codes

## Default Thresholds

Thresholds are based on service tier:

| Tier | Warning | Blocking |
|------|---------|----------|
| Critical | ≤20% remaining | ≤10% remaining |
| Standard | ≤20% remaining | None (advisory) |
| Low | ≤30% remaining | None (advisory) |

Critical services block deploys at 10% remaining budget. Standard and low tiers only warn.

## Custom Policies

!!! warning "Not applied by the gate commands"
    Neither `python -m nthlayer_workers.observe check-deploy` nor
    `nthlayer-workers gate` reads `DeploymentGate` resources today: both
    evaluate with the tier default thresholds above. The settings below are
    accepted in a manifest but do not change a gate decision.

Override defaults with a `DeploymentGate` resource in your `service.yaml`:

```yaml
resources:
  - kind: DeploymentGate
    name: custom-gate
    spec:
      thresholds:
        warning: 30
        blocking: 5
```

### Conditional Thresholds

Apply different thresholds based on conditions:

```yaml
resources:
  - kind: DeploymentGate
    name: smart-gate
    spec:
      thresholds:
        warning: 20
        blocking: 10

      conditions:
        # Stricter during business hours
        - name: business-hours
          when: "hour >= 9 AND hour <= 17 AND weekday"
          blocking: 15

        # Complete freeze during incidents
        - name: incident-freeze
          when: "budget_remaining < 5"
          blocking: 100
```

### Team Exceptions

Allow specific teams to bypass gates:

```yaml
spec:
  exceptions:
    - team: sre-oncall
      allow: always
```

## Integration Points

### CI/CD Pipelines

NthLayer integrates with:

- **GitHub Actions** - Reusable action
- **ArgoCD** - PreSync hook
- **GitLab CI** - Reusable template
- **Tekton** - Reusable task

See [examples/cicd/](https://github.com/nthlayer/nthlayer/tree/main/examples/cicd) for templates.

### Manual Check

Test locally before integrating:

```bash
nthlayer-workers gate --service api --core-url http://nthlayer-core:8000

echo "Exit code: $?"
```

## Blast Radius Awareness

Gates consider downstream dependencies:

```yaml
resources:
  - kind: Dependencies
    name: downstream
    spec:
      services:
        - name: checkout-service
          criticality: high
        - name: analytics
          criticality: low
```

High-criticality downstream services increase the gate's caution level.

## Best Practices

The threshold snippets in practices 1 and 2 are `DeploymentGate` settings,
which the gate commands do not apply yet (see [Custom Policies](#custom-policies)).

### 1. Start with Advisory Mode

Begin with warnings only, then enable blocking:

```yaml
spec:
  thresholds:
    warning: 20
    blocking: null  # Advisory only
```

### 2. Use Environment-Specific Thresholds

Be lenient in dev, strict in prod:

```yaml
# dev environment
spec:
  thresholds:
    warning: 50
    blocking: null

# prod environment
spec:
  thresholds:
    warning: 20
    blocking: 10
```

### 3. Define SLO Queries

Gates need working SLO queries to calculate budget:

```yaml
- kind: SLO
  name: availability
  spec:
    objective: 99.95
    window: 30d
    indicator:
      query: |
        sum(rate(http_requests_total{status!~"5.."}[5m]))
        /
        sum(rate(http_requests_total[5m]))
```

## See Also

- [Deployment Gate Command](../commands/check-deploy.md) (nthlayer-workers)
- [SLO Concepts](./slos.md)
- [Shift Left Philosophy](./shift-left.md)
