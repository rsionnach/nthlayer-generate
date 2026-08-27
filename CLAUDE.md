# nthlayer-generate

Reliability at build time, not incident time. Validate production
readiness in CI/CD (Generate → Validate → Gate). Pure deterministic
compiler: specs → artifacts (Python, stateless, no runtime).

## Stack

- Python ≥3.11, `uv`-managed.
- MIT licensed (note: `nthlayer-workers` — the consolidated runtime
  tier containing observe/measure/correlate/respond/learn modules — is
  Apache 2.0).
- Package: PyPI name `nthlayer-generate`, Python import name
  `nthlayer_generate` (underscore). All imports use
  `from nthlayer_generate.*` — not `from nthlayer.*`. Entry points:
  `nthlayer` and `nthlayer-generate` both map to
  `nthlayer_generate.demo:main`.
- Version: source of truth is `pyproject.toml`; read at runtime via
  `importlib.metadata.version("nthlayer-generate")`.

## Build / test / lint / typecheck commands

→ See `AGENTS.md` (existing canonical Core Commands section + project
roadmap + conventions).

Short form for quick reference:

- Local dev install: `uv sync --extra dev`.
- CI install (resolves nthlayer-common from PyPI):
  `uv sync --no-sources --extra dev`.
- Tests: `make test`. Smoke: `make smoke` (CLI smoke, ~40s offline).
  Smoke + Synology: `make smoke-full`.
- Lint: `make lint` + `./scripts/lint/run-all.sh` (custom
  golden-principle linters).
- Typecheck: `make typecheck` (mypy is configured in
  `pyproject.toml` under `[tool.mypy]`).
- Format: `make format`.

## Documentation map

| What | Where |
|------|-------|
| Architecture & package layout | `docs/architecture.md` |
| Coding conventions | `docs/conventions.md` |
| Golden principles (mechanical rules) | `docs/golden-principles.md` |
| Testing patterns | `docs/testing.md` |
| Quality grades by package | `docs/quality.md` |
| Active specs | `specs/` |
| Execution plans (spec implementations) | `plans/` |
| Technical debt backlog | `plans/tech-debt.md` |
| Design & promotion plans | `docs/plans/` |
| Ecosystem capability audit (generate migration plan) | `docs/generate-capability-audit.md` |
| Mimir move + ExplanationEngine design (nthlayer-2xe, nthlayer-hmj) | `docs/superpowers/specs/2026-04-10-mimir-move-and-explanation-engine-design.md` |
| Mimir move + ExplanationEngine implementation plan (nthlayer-2xe, nthlayer-hmj) | `docs/superpowers/plans/2026-04-10-mimir-move-and-explanation-engine.md` |
| Runtime → nthlayer-observe migration guide | `MIGRATION.md` |
| Demo improvement — accountability & portfolio story (opensrm-42y) | `plans/active/2026-04-16-demo-improvement-accountability-portfolio.md` |

Read the specific doc relevant to your task. Do **NOT** try to load
all docs at once.

MkDocs site: configuration in `mkdocs.yml`, source in `docs-site/`,
build output `site/` (gitignored). Deploy via
`.github/workflows/docs.yml` (push to `main` with `docs-site/` /
`mkdocs.yml` / workflow file changes → GitHub Pages at
rsionnach.github.io/nthlayer/).

## Hard rules

These are load-bearing — enforced by linters and structural tests.
See `docs/golden-principles.md` for the full list with rationale.

1. **Validate inputs at the boundary, not inline.** Manifests and
   templates are parsed once at entry; downstream code trusts the
   parsed dataclass shape. Do not re-validate.

2. **Use shared utilities — do not hand-roll helpers that already
   exist.** If a shape is in `nthlayer_common`, import it; do not
   re-implement.

3. **Structured logging only — no bare `print()` outside CLI
   entrypoints.** `structlog` is the canonical logger. Bare `print`
   is reserved for CLI user-facing output. Lint enforces this via
   `scripts/lint/check-no-unstructured-logging.sh`.

4. **Handle exceptions with context at module boundaries.** No bare
   `except: pass`. Catch specific types, attach context via
   structlog, re-raise or fail-open per the module's documented
   posture. Lint enforces via
   `scripts/lint/check-exception-handling.sh`.

5. **Use the template system for all generated output — no raw
   string construction.** Dashboards, alerts, and SLO YAML go
   through templated emitters; `f"…"` for output is a code smell.

6. **Every `TODO` must reference a Beads issue ID** (format
   `TODO(opensrm-XXXX)` or `TODO(bd-XXXX)`). Lint enforces via
   `scripts/lint/check-no-orphan-todos.sh`. Untagged TODOs rot.

7. **The compiler is stateless and pure.** No runtime, no
   network, no LLM in the generator path. Generated artifacts are a
   deterministic function of inputs. If a step needs external state
   (e.g. Prometheus metric existence verification), it belongs in a
   verifier subcommand, not the generation path.

8. **Branching: feature branch → PR → `main`.** Same as every other
   ecosystem repo. Feature branches are `feat/<slug>` or `fix/<slug>`,
   branched from `main` and merged back via PR. Never commit directly
   to `main`.

   This rule previously described a `develop` → `main` flow. No
   `origin/develop` ever existed; the stale local branch was archived as
   tag `archive/develop-2026-08-26` and deleted (opensrm-z9sz). Do not
   recreate it.

9. **Commit messages: `<type>: <description> (<bead-id>)`.** Types:
   `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `lint`. When
   fixing a GitHub Issue: `fix: <description> (<bead-id>, closes
   #<number>)`.

## Beads (quick reference)

```bash
bd ready              # Show tasks ready to work on
bd update <id> --status in_progress
bd close <id> --reason "What was done"
bd create --title "..." --description "..." --priority 1 --type feature
```

The beads DB for this ecosystem lives in `../opensrm/`. All `bd`
commands must run from that directory; `cd ../opensrm` first if not
already there. See `docs/conventions.md` for the full Beads workflow.

## Workflow tooling

Slash commands (in this repo's `.claude/commands/`):

- `/audit-codebase` — codebase audit.
- `/gc-sweep` — entropy cleanup.
- `/doc-garden` — doc gardening.
- `/spec-to-beads <spec-file>` — turn a spec doc into bead tasks.
- `/desloppify` — code-quality sweep (scan → fix → resolve loop for
  technical debt, dead code, code smells).

Autonomous loop: `.claude/ralph-loop.sh [max-iterations]` runs the
Ralph loop; prompt at `.claude/ralph-prompt.md`; signal completion
with `RALPH_COMPLETE`.

Release: driven by `release-please` (`.github/workflows/release-please.yml`,
`release-please-config.json`, `.release-please-manifest.json`), same as the
other ecosystem repos. Merging a conventional commit to `main` updates the
standing release PR; merging that PR tags the release and publishes to PyPI
via `release.yml`. **`CHANGELOG.md` and the version are generated — do not
hand-edit either.** A `feat!:` or a `BREAKING CHANGE:` footer drives the
major bump.

## Where to find detail

- Architecture, source layout, core modules, data flow:
  `docs/architecture.md`.
- Conventions (coding style, structured logging, beads workflow,
  release process): `docs/conventions.md`.
- Mechanical rules and lint enforcement: `docs/golden-principles.md`.
- Testing patterns: `docs/testing.md`.
- Quality grades per package: `docs/quality.md`.
- AGENTS.md (long form): project vision, roadmap, project layout,
  development patterns, git workflow, beads integration.
- nthlayer-common public API the compiler consumes:
  `../nthlayer-common/docs/architecture.md`.
- Project memory / Rob's preferences across sessions:
  `~/.claude/projects/-Users-robfox-Documents-GitHub-nthlayer-ecosystem/memory/MEMORY.md`.
- Beads: `cd ../opensrm && bd ready --json`.
