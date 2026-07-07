# Contributing to nthlayer-generate

Thank you for considering contributing to **nthlayer-generate** — the pure,
deterministic compiler that turns OpenSRM specs into reliability artifacts
(SLOs, alerts, dashboards, deployment gates). Reliability at build time, not
incident time. We're in active development and welcome feedback from the
SRE/DevOps community.

## Ways to Contribute

- **Try it out** — run NthLayer against a real service and
  [open a Discussion](https://github.com/rsionnach/nthlayer/discussions) or
  [report bugs](https://github.com/rsionnach/nthlayer-generate/issues).
- **Code & docs** — pull requests welcome (see below).
- **Technology templates** — add support for new technologies (Kafka,
  RabbitMQ, cloud-specific metrics). See `src/nthlayer_generate/` templates.

## Development Setup

This is the **only** ecosystem repo with a `Makefile` and the only one with
mypy configured.

```bash
# Install uv (https://docs.astral.sh/uv/)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone alongside nthlayer-common (resolved as a sibling path locally)
git clone https://github.com/rsionnach/nthlayer-common.git
git clone https://github.com/rsionnach/nthlayer-generate.git
cd nthlayer-generate
git checkout develop                 # all work targets develop, not main
uv sync --extra dev                  # installs deps + test/lint/typecheck tools
make pre-commit-install              # install git hooks

# Tests / lint / typecheck / format
make test                            # pytest
make smoke                           # CLI smoke (~40s, offline)
make lint                            # ruff + see custom linters below
make typecheck                       # mypy
make format
./scripts/lint/run-all.sh            # custom golden-principle linters
```

> **The `nthlayer-common` clone above is required** for local dev — `uv sync`
> resolves it via an editable sibling path and fails without it. (CI instead
> uses `uv sync --no-sources --extra dev` to pull it from PyPI; you don't need
> that variant locally.) Requires Python 3.11+ (`uv` will provision it via
> `uv python install` if needed).

A clean clone to a green `make test` should take well under five minutes.

## Pull Request Process

This repo uses a **`develop` → `main`** flow (unlike the other ecosystem
repos, which commit to `main` directly):

1. Fork the repository.
2. Create a feature branch off `develop` (`git checkout -b feat/your-change`).
3. Make your change with tests.
4. Ensure `make test`, `make lint`, and `make typecheck` pass.
5. Commit using the message format below.
6. Open a PR targeting **`develop`**. `main` is only updated by merging
   `develop` at release time — never commit directly to `main`.

## Development Guidelines

### Code Style

- Python 3.11+, type hints required (mypy, `python_version = "3.11"`).
- Ruff config here is `select = ["E","F","I","B"]` with `E402`/`E501` ignored
  (distinct from the ecosystem floor — this repo predates it).
- Enforced golden principles (custom linters): structured logging only (no
  bare `print` outside CLI), no bare `except: pass`, every `TODO` references a
  bead ID, template system for all generated output. See
  `docs/golden-principles.md`.

### Commit Messages

```
<type>: <description> (<bead-id>)
```

Types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `lint`. When
fixing a GitHub Issue: `fix: <description> (<bead-id>, closes #<number>)`.

### Testing

- Add tests for new behaviour. Integration tests via `make test-integration`.
- Ecosystem testing conventions: [../nthlayer/docs/testing.md](../nthlayer/docs/testing.md).

## Finding Something to Work On

Browse [open issues](https://github.com/rsionnach/nthlayer-generate/issues) and
look for `good-first-issue` / `help-wanted` labels. Maintainers track detailed
work in **Beads**, a Dolt-backed board in the `opensrm` repo
(`cd ../opensrm && bd ready --json`) — you don't need it to contribute.

## Code of Conduct

Be respectful and constructive — we're all here to build better reliability
tooling.

## Questions?

- [GitHub Issues](https://github.com/rsionnach/nthlayer-generate/issues) — bugs and features.
- [GitHub Discussions](https://github.com/rsionnach/nthlayer/discussions) — general questions.

## License

nthlayer-generate is MIT licensed. By contributing, you agree that your
contributions will be licensed under the same terms (see `LICENSE`).

---

**Thank you for helping make NthLayer better!**
