<div align="center">
  <a href="https://github.com/rsionnach/nthlayer">
    <img src="presentations/public/nthlayer_dark_banner.png" alt="NthLayer" width="400">
  </a>
  <br><br>
</div>

# NthLayer

**Reliability as code. Pure compiler.**

Define reliability requirements in a manifest. Generate dashboards, alerts, SLOs, and documentation — deterministically, every time.

[![Status: Alpha](https://img.shields.io/badge/Status-Alpha-orange?style=for-the-badge)](https://github.com/rsionnach/nthlayer)
[![PyPI](https://img.shields.io/pypi/v/nthlayer?style=for-the-badge&logo=pypi&logoColor=white)](https://pypi.org/project/nthlayer/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](LICENSE.txt)
[![Alert Rules](https://img.shields.io/badge/Alert_Rules-593+-red?style=for-the-badge&logo=prometheus&logoColor=white)](https://github.com/samber/awesome-prometheus-alerts)

## TL;DR

```bash
pip install nthlayer
nthlayer init
nthlayer apply service.yaml
```

---

## ⚠️ The Problem

Reliability decisions happen too late. Teams set SLOs in isolation, deploy without checking error budgets, and discover missing metrics during incidents. Dashboards are inconsistent. Alerts are copy-pasted. Nobody validates whether a 99.99% target is even achievable given dependencies.

## 💡 The Solution

NthLayer is a **pure compiler** for reliability infrastructure. Write a manifest, get artifacts:

```
service.yaml → validate → apply
                  │          │
                  │          └── Grafana dashboards, Prometheus alerts,
                  │              recording rules, SLOs, PagerDuty config,
                  │              Backstage entities, service docs
                  │
                  └── SLO feasible? Dependencies support it? Metrics exist?
                      Policies pass? Ceiling valid?
```

NthLayer generates. The [nthlayer-workers](https://github.com/rsionnach/nthlayer-workers) runtime (Tier 2) enforces, observes, and responds at runtime, with state held in [nthlayer-core](https://github.com/rsionnach/nthlayer-core) (Tier 1) and operator interaction via [nthlayer-bench](https://github.com/rsionnach/nthlayer-bench) (Tier 3).

---

## ⚡ Core Features

### Artifact Generation

Generate dashboards, alerts, and SLOs from a single spec.

```bash
$ nthlayer apply service.yaml

Generated:
  → dashboard.json (Grafana)
  → alerts.yaml (Prometheus)
  → recording-rules.yaml (Prometheus)
  → slos.yaml (OpenSLO)
  → backstage.json (Backstage entity)
```

### Dependency-Aware SLO Validation

Your SLO ceiling is your weakest dependency chain. NthLayer calculates it.

```bash
$ nthlayer validate-slo payment-api

Target: 99.99% availability
Dependencies:
  → postgresql (99.95%)
  → redis (99.99%)
  → user-service (99.9%)

Serial availability: 99.84%
✗ INFEASIBLE: Target exceeds dependency ceiling by 0.15%

Recommendation: Reduce target to 99.8% or improve user-service SLO
```

### Metric Recommendations

Enforce OpenTelemetry conventions. Know what's missing before production.

```bash
$ nthlayer recommend-metrics payment-api

Required (SLO-critical):
  ✓ http.server.request.duration    FOUND
  ✗ http.server.active_requests     MISSING

Run with --show-code for instrumentation examples.
```

### Monte Carlo SLO Simulation

Model failure scenarios before they happen.

```bash
$ nthlayer simulate service.yaml --scenarios 10000

Monte Carlo Simulation (10,000 runs)
  SLO: availability ≥ 99.9%
  Result: 94.2% of scenarios meet target
  P50 availability: 99.95%
  P99 availability: 99.82%
  Risk: 5.8% chance of SLO breach in 30d window
```

### Topology Export

Export dependency graphs for correlation engines.

```bash
$ nthlayer topology export service.yaml --format json
$ nthlayer topology export service.yaml --format mermaid
$ nthlayer topology export service.yaml --format dot
```

### Policy Validation

Enforce organizational standards at build time.

```bash
$ nthlayer validate service.yaml --policies policies.yaml

✓ required_fields: ownership.runbook present
✗ tier_constraint: critical services require deployment gates
✓ dependency_rule: all critical deps have SLOs
```

---

## 🚀 Quick Start

```bash
# Install
pip install nthlayer

# Create a service spec
nthlayer init

# Validate and generate
nthlayer apply service.yaml
```

### Minimal `service.yaml`

```yaml
name: payment-api
tier: critical
type: api
team: payments

dependencies:
  - postgresql
  - redis
```

NthLayer also supports the [OpenSRM format](https://rsionnach.github.io/nthlayer/concepts/opensrm/) (`apiVersion: opensrm/v1`) for contracts, deployment gates, and more. See [full spec reference](https://rsionnach.github.io/nthlayer/reference/service-yaml/) for all options.

---

## 🔄 CI/CD Integration

```yaml
# GitHub Actions
- name: Validate reliability
  run: |
    nthlayer validate service.yaml
    nthlayer validate-slo service.yaml
    nthlayer apply service.yaml --output-dir generated/
```

For runtime enforcement (deployment gates, drift detection, error budget checks), use [`nthlayer-workers`](https://github.com/rsionnach/nthlayer-workers) — the runtime tier:

```yaml
- name: Gate deployment
  run: |
    nthlayer-workers gate --service payment-api
```

The runtime tier reads SLOs and dependency declarations from the same OpenSRM manifests this generator consumes. Verdicts and assessments flow through [`nthlayer-core`](https://github.com/rsionnach/nthlayer-core)'s HTTP API.

Works with: **GitHub Actions**, **GitLab CI**, **ArgoCD**, **Tekton**, **Jenkins**

---

## 🎯 How It's Different

| Traditional Approach | NthLayer |
|---------------------|----------|
| Set SLOs in isolation | Validate against dependency chains |
| Manual dashboard creation | Generate from spec |
| Copy-paste alerts | 593+ alert templates, auto-selected |
| Discover missing metrics in incidents | Enforce before deployment |
| "Is this ready?" = opinion | "Is this ready?" = deterministic check |

---

## 📚 Documentation

**[Full Documentation](https://rsionnach.github.io/nthlayer/)** - Comprehensive guides and reference.

[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/rsionnach/nthlayer)

| Guide | Description |
|-------|-------------|
| [Quick Start](https://rsionnach.github.io/nthlayer/getting-started/quick-start/) | Get running in 5 minutes |
| [Dependency Discovery](https://rsionnach.github.io/nthlayer/features/dependencies/) | Automatic dependency mapping |
| [CI/CD Integration](https://rsionnach.github.io/nthlayer/guides/cicd/) | Pipeline setup |
| [CLI Reference](https://rsionnach.github.io/nthlayer/reference/cli/) | All commands |

---

## 🗺️ Roadmap

### Generate (this repo)
- [x] Artifact generation (dashboards, alerts, SLOs, recording rules, Loki alerts)
- [x] Dependency-aware SLO validation
- [x] Metric recommendations (OpenTelemetry conventions)
- [x] Monte Carlo SLO simulation
- [x] Policy validation (build-time)
- [x] Topology export (JSON, Mermaid, DOT)
- [x] OpenSRM manifest format (`opensrm/v1`)
- [x] Identity resolution & ownership
- [x] Backstage entity generation
- [x] Service documentation generation
- [x] CI/CD GitHub Action
- [ ] Agentic inference (`nthlayer infer`)
- [ ] MCP server integration
- [ ] Backstage plugin

### Runtime tier ([nthlayer-workers](https://github.com/rsionnach/nthlayer-workers))

What was previously the standalone `nthlayer-observe` repo plus four agentic components is now consolidated into a single Tier-2 worker process with five modules:

- [x] **observe** — SLO collection, drift detection, dependency/topology discovery, deploy gate
- [x] **measure** — judgment SLO evaluation, governance ratchet, autonomy-level reduction
- [x] **correlate** — session-window event correlation, topology drift, contract divergence
- [x] **respond** — incident response coordinator (situation-shaped triggers, capture-at-write-time escalation)
- [x] **learn** — outcome resolution, calibration signals, retrospective generation

Backed by [nthlayer-core](https://github.com/rsionnach/nthlayer-core) (Tier 1: HTTP API, verdict store, case management, manifest catalogue) and operated via [nthlayer-bench](https://github.com/rsionnach/nthlayer-bench) (Tier 3: Textual TUI for SREs).

---

## Agentic Inference (Planned)

`nthlayer infer` will use a model to analyse a codebase and propose an OpenSRM manifest for it. The model examines the code, identifies services, infers appropriate SLO targets, and generates a draft `service.reliability.yaml` that NthLayer then validates and generates artifacts from.

This follows the **Zero Framework Cognition** boundary applied across the OpenSRM ecosystem: the model provides judgment (what SLOs does this service need?), and NthLayer provides transport (validate the manifest, generate the monitoring artifacts). Clean boundary between reasoning and deterministic transformation. Architectural context: [opensrm/docs/superpowers/](https://github.com/rsionnach/opensrm/tree/main/docs/superpowers).

---

## OpenSRM Ecosystem

NthLayer is one piece of a six-repo ecosystem. The architecture has three runtime tiers; this repo (`nthlayer-generate`) sits outside the runtime tiers as a build-time compiler, feeding manifests forward.

```
                  ┌──────────────────────────┐
                  │      OpenSRM Manifest    │
                  │  (the shared contract)   │
                  └────────────┬─────────────┘
                               │
              ┌────────────────┴────────────────┐
              ▼                                 ▼
    ┌──────────────────┐               ┌─────────────────┐
    │ nthlayer-generate│               │ nthlayer-core   │
    │  (build-time)    │               │  (Tier 1)       │
    │                  │               │ HTTP API ·      │
    │ specs → Grafana, │               │ verdict store · │
    │ Prometheus, SLOs,│               │ case mgmt ·     │
    │ Backstage, docs  │               │ manifests       │
    └────────┬─────────┘               └────────▲────────┘
             │                                  │ HTTP only
             │ deployed                ┌────────┴──────────────┐
             ▼                         │                       │
    ┌──────────────────┐      ┌────────┴────────┐    ┌─────────┴────────┐
    │  Live infra      │      │ nthlayer-workers│    │ nthlayer-bench   │
    │  (Prometheus,    │ obs  │   (Tier 2)      │    │   (Tier 3)       │
    │   Grafana, etc.) │ ─────│                 │    │ Textual TUI for  │
    └──────────────────┘      │ observe·measure │    │ SREs: situation  │
                              │ correlate·respond│    │ board, case      │
                              │ ·learn          │    │ bench, approvals │
                              └─────────────────┘    └──────────────────┘

    Learning loop:
    workers.learn retrospectives → manifest updates → nthlayer-generate
    regenerates → workers refine thresholds → operators ratify in bench
```

**How nthlayer-generate fits in:**

- Reads OpenSRM manifests and emits the monitoring infrastructure (Prometheus rules, Grafana dashboards, recording rules, Backstage entities, service docs) that the runtime tier and live observability stack rely on
- Pure compiler — deterministic, stateless, no LLM, no runtime side effects
- Verdicts and assessments produced by `nthlayer-workers` modules emit OTel side-effects (`gen_ai.decision.*`, `gen_ai.override.*`) that flow into Prometheus; this generator can be configured to produce dashboards for those metrics alongside service dashboards
- Exports service topology that `workers.correlate` uses for topology-aware signal correlation
- Post-incident retrospectives produced by `workers.learn` feed back into manifest updates that regenerate via this compiler — closing the loop

Each component works alone. Someone who just needs reliability-as-code adopts `nthlayer-generate` without needing the rest of the ecosystem.

| Repo | Role |
|---|---|
| [`opensrm`](https://github.com/rsionnach/opensrm) | The OpenSRM specification — the manifest format and language for declaring reliability |
| [`nthlayer`](https://github.com/rsionnach/nthlayer) | Project front door — documentation hub, GitHub Action delegating to this repo, docs site |
| [`nthlayer-common`](https://github.com/rsionnach/nthlayer-common) | Shared library: verdict model, manifest parser, LLM wrapper, error hierarchy, CoreAPIClient |
| [`nthlayer-generate`](https://github.com/rsionnach/nthlayer-generate) | The deterministic compiler (this repo) — specs to artefacts |
| [`nthlayer-core`](https://github.com/rsionnach/nthlayer-core) | **Tier 1** — HTTP API server, verdict store, case management, manifest catalogue (`pip install nthlayer`) |
| [`nthlayer-workers`](https://github.com/rsionnach/nthlayer-workers) | **Tier 2** — five worker modules: observe, measure, correlate, respond, learn |
| [`nthlayer-bench`](https://github.com/rsionnach/nthlayer-bench) | **Tier 3** — Textual TUI for SREs |

---

## 🤝 Contributing

```bash
# Install uv (https://docs.astral.sh/uv/)
curl -LsSf https://astral.sh/uv/install.sh | sh

git clone https://github.com/rsionnach/nthlayer-generate.git
cd nthlayer-generate
make setup    # Install deps, start services
make test     # Run tests
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for details.

---

## 📄 License

MIT - See [LICENSE.txt](LICENSE.txt)

---

## 🙏 Acknowledgments

Built on [grafana-foundation-sdk](https://github.com/grafana/grafana-foundation-sdk), [awesome-prometheus-alerts](https://github.com/samber/awesome-prometheus-alerts), [pint](https://github.com/cloudflare/pint), and [OpenSLO](https://github.com/openslo/openslo). Inspired by [Sloth](https://github.com/slok/sloth) and [autograf](https://github.com/FUSAKLA/autograf).
