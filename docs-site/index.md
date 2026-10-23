# NthLayer

**Reliability at build time, not incident time.**

Shift reliability left into your CI/CD pipeline. Validate before deploy, not after incidents.

---

## The Reliability Pipeline

```
   service.yaml / *.reliability.yaml
        │
        ▼
┌───────────┐     ┌───────────┐     ┌───────────┐
│  Generate │ ──▶ │  Validate │ ──▶ │  Protect  │ ──▶ Deploy
└───────────┘     └───────────┘     └───────────┘
   apply            validate-slo     alerts
   init             validate-spec    gate (nthlayer-workers)
   migrate          --lint
```

| Stage | What Happens | Exit Code |
|-------|--------------|-----------|
| **Generate** | Create dashboards, alerts, SLOs from YAML | - |
| **Validate** | Verify specs, lint PromQL, check contracts | 1 if invalid |
| **Protect** | Block deploys when error budget exhausted | 2 if blocked |

## The Problem

Teams deploy code without reliability validation:

- Alerts created **after** the first incident
- Dashboards built **after** users complain
- SLOs defined **after** budget is exhausted
- No gates to prevent risky deploys

## The Solution

NthLayer shifts reliability left - from incident response to CI/CD:

=== "Legacy Format"

    ```yaml title="service.yaml"
    name: payment-api
    tier: critical
    type: api
    dependencies:
      - postgresql
      - redis
    ```

=== "OpenSRM Format"

    ```yaml title="payment-api.reliability.yaml"
    apiVersion: srm/v1
    kind: ServiceReliabilityManifest
    metadata:
      name: payment-api
      tier: critical
    spec:
      type: api
      slos:
        availability:
          target: 99.95
          window: 30d
      contract:
        availability: 0.999
      dependencies:
        - name: postgresql
          type: database
          critical: true
    ```

Both formats are supported. Use `nthlayer migrate` to convert legacy files.

```bash
# Generate → Validate → Protect → Deploy
nthlayer apply service.yaml --lint
nthlayer validate-slo service.yaml --prometheus-url $PROM_URL
nthlayer-workers gate --service payment-api --core-url $NTHLAYER_CORE_URL
kubectl apply -f generated/
```

## What Gets Generated

| Output | Description |
|--------|-------------|
| **Dashboards** | Grafana dashboards with technology-aware panels |
| **Alerts** | Prometheus alert rules with best-practice thresholds |
| **SLOs** | OpenSLO-compatible definitions with error budgets |
| **Recording Rules** | Pre-aggregated metrics for performance |

## Key Features

### Deployment Gates

Block deploys when error budget is exhausted. The gate ships in the
`nthlayer-workers` package and reads SLO state from nthlayer-core:

```bash
nthlayer-workers gate --service payment-api --core-url $NTHLAYER_CORE_URL
# Exit code: 0=approved (or warning), 1=could not evaluate, 2=blocked
```

### Contract Verification

Verify that the metrics your SLOs query exist before deploy:

```bash
nthlayer validate-slo service.yaml --prometheus-url $PROM_URL
```

### Intelligent Alerts

Context-aware alert evaluation and simulation:

```bash
nthlayer alerts evaluate services/ --path services/
nthlayer alerts test services/payment-api.yaml --simulate-burn 90
```

### 23 Technology Templates

Pre-built monitoring for:

- **Databases:** PostgreSQL, MySQL, MongoDB, Redis, Elasticsearch
- **Message Queues:** Kafka, RabbitMQ, NATS, Pulsar
- **Proxies:** Nginx, HAProxy, Traefik
- **Infrastructure:** Kubernetes, etcd, Consul

## CI/CD Integration

```yaml title=".github/workflows/deploy.yml"
jobs:
  deploy:
    steps:
      - name: Validate Specs
        run: nthlayer validate-spec services/

      - name: Generate & Lint
        run: nthlayer apply services/*.yaml --lint

      - name: Verify Metrics
        run: nthlayer validate-slo services/payment-api.yaml --prometheus-url $PROM_URL

      - name: Check Deploy Gate
        run: nthlayer-workers gate --service payment-api --core-url $NTHLAYER_CORE_URL

      - name: Deploy
        if: success()
        run: kubectl apply -f generated/
```

Integrates with GitHub Actions, GitLab CI, ArgoCD, Tekton, and Jenkins.

## Get Started

<div class="grid cards" markdown>

-   :material-download:{ .lg .middle } **Installation**

    ---

    Install NthLayer with pip in 30 seconds

    [:octicons-arrow-right-24: Install](getting-started/installation.md)

-   :material-rocket-launch:{ .lg .middle } **Quick Start**

    ---

    Generate your first dashboard in 5 minutes

    [:octicons-arrow-right-24: Quick Start](getting-started/quick-start.md)

-   :material-shield-check:{ .lg .middle } **Validate**

    ---

    Catch issues before they reach production

    [:octicons-arrow-right-24: Validation](validate/index.md)

-   :material-gate:{ .lg .middle } **Protect**

    ---

    Block risky deploys with error budget gates

    [:octicons-arrow-right-24: Protection](protect/index.md)

</div>

## The Google SRE Connection

NthLayer automates concepts from the [Google SRE Book](https://sre.google/sre-book/):

| SRE Concept | Manual Process | NthLayer Automation |
|-------------|----------------|---------------------|
| Production Readiness Review | Multi-week checklist | `nthlayer validate-slo` in CI |
| Error Budget Policy | Spreadsheet tracking | `nthlayer-workers gate` |
| Release Engineering | Manual runbooks | Generated artifacts + GitOps |
| Monitoring Standards | Wiki pages | `service.yaml` spec |
