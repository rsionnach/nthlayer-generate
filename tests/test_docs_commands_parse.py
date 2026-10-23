"""Every documented `nthlayer` invocation must parse (opensrm-3ntg).

opensrm-noc6 found that `docs-site/commands/init.md` documented flags the
parser did not have, and `tests/test_init_documented_flags.py` now guards that
one command. The sweep that bead ran over the rest of `docs-site/commands/`
found seven documented subcommands with no subparser and eleven undefined
flags on real ones. This file generalises the guard to every page.

Direction matters, as it did in noc6: the DOCS are the fixture and the PARSER
is the authority. Nothing here lists command names expected from the docs —
every line in any fenced block (shell, yaml CI steps, Jenkins `sh`,
pre-commit `entry:`) that runs the `nthlayer` (or `nthlayer-generate`)
console script is handed to `build_parser().parse_args()`, and an argparse
error on any of them fails the test named after its page and line.

Scope: every `docs-site/**/*.md` page plus `README.md`. Lines running other
executables — `nthlayer-workers`, `nthlayer-core`, `python -m ...`,
`pip install nthlayer` — are not this parser's to judge and are not collected.

Pipeline, per page: each fenced block (`_FENCE`) is split into logical lines
(backslash continuations joined, comments and a `$ ` prompt dropped); `_unwrap`
strips CI wrappers (`run:`, `script:`, `entry:`, `- `, Jenkins `sh '...'`);
metavariables and CI templating become `PLACEHOLDER_ARG`; `_split_commands`
lexes the line into simple commands, dropping pipes, separators and
redirections; `_runner_stripped` removes shell keywords, env assignments and
runner prefixes; `_strip_synopsis_markup` removes `[options]` and bracket
syntax; and a pre-commit `entry:` gets the filenames pre-commit would append
(`_precommit_tail`). What survives, minus the entry point, is the argv the
parser checks.

Known residual — shapes NOT recognised, so an `nthlayer` call written this
way is silently not collected: `docker run IMAGE nthlayer ...`, `xargs
nthlayer ...`, backtick substitution, `"$(nthlayer ...)"` inside double
quotes (lexed as one word), `{ nthlayer ...; }` groups, Dockerfile `RUN`,
Jenkins `sh("...")` call syntax, prompts other than `$ ` (`% `, `> `, `PS>`),
non-breaking spaces between tokens, and indented (non-fenced) code blocks.
A cmd.exe `^` continuation is not joined (pinned by a test; it fails loudly).
"""

from __future__ import annotations

import argparse
import re
import shlex
from pathlib import Path

import pytest

from nthlayer_generate.demo import build_parser

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_ROOT = REPO_ROOT / "docs-site"

# Measured on the opensrm-3ntg branch after widening collection to every
# fence (yaml, groovy, unlabelled): about 250 invocations across 42 pages.
# The floor sits well under that so ordinary docs edits do not trip it, but
# far above zero so a broken extractor (a regex that matches nothing, a moved
# docs dir) cannot leave this file green and vacuous.
MIN_INVOCATIONS = 200

# Every page that yields at least one invocation, measured on the opensrm-3ntg
# branch. The total floor above has slack (a page's worth of invocations can
# vanish under it); this does not: a page dropping out — moved, emptied, or
# its fences no longer recognised — fails by name. To update after a
# deliberate docs change, print
# `sorted({page for page, _, _ in INVOCATIONS})` and paste it here.
PAGES_WITH_INVOCATIONS = (
    "README.md",
    "docs-site/commands/alerts.md",
    "docs-site/commands/apply.md",
    "docs-site/commands/config.md",
    "docs-site/commands/environments.md",
    "docs-site/commands/generate-alerts.md",
    "docs-site/commands/generate-dashboard.md",
    "docs-site/commands/generate-loki-alerts.md",
    "docs-site/commands/generate-recording-rules.md",
    "docs-site/commands/generate-slo.md",
    "docs-site/commands/identity.md",
    "docs-site/commands/index.md",
    "docs-site/commands/init.md",
    "docs-site/commands/migrate.md",
    "docs-site/commands/ownership.md",
    "docs-site/commands/recommend-metrics.md",
    "docs-site/commands/setup.md",
    "docs-site/commands/simulate.md",
    "docs-site/commands/slo.md",
    "docs-site/commands/validate-metadata.md",
    "docs-site/commands/validate-slo.md",
    "docs-site/commands/validate-spec.md",
    "docs-site/concepts/contracts.md",
    "docs-site/concepts/opensrm.md",
    "docs-site/concepts/service-specs.md",
    "docs-site/concepts/shift-left.md",
    "docs-site/concepts/slos.md",
    "docs-site/demo.md",
    "docs-site/getting-started/adoption-path.md",
    "docs-site/getting-started/first-service.md",
    "docs-site/getting-started/installation.md",
    "docs-site/getting-started/quick-start.md",
    "docs-site/index.md",
    "docs-site/integrations/cicd.md",
    "docs-site/integrations/grafana.md",
    "docs-site/integrations/mimir.md",
    "docs-site/integrations/prometheus.md",
    "docs-site/protect/index.md",
    "docs-site/reference/cli.md",
    "docs-site/reference/service-yaml.md",
    "docs-site/validate/index.md",
    "docs-site/validate/linting.md",
)

# Console scripts that reach `nthlayer_generate.demo:main` (pyproject
# [project.scripts]). Both run the same parser, so both are checked.
ENTRY_POINTS = frozenset({"nthlayer", "nthlayer-generate"})

# Any fenced block, whatever its info string: invocations also sit in yaml
# (GitHub Actions, GitLab, pre-commit, Tekton), groovy (Jenkins) and
# unlabelled fences. Leading indent is allowed (this site nests fences in
# lists), as is a trailing info string (```bash title="..."). Closing follows
# CommonMark: a bare run of the SAME character at least as long as the opening
# one, so a ````markdown block quoting a ```bash example is not closed by it.
_FENCE_OPEN = re.compile(r"^[ \t]*(`{3,}|~{3,})(.*)$")
_FENCE_CLOSE = re.compile(r"^[ \t]*(`{3,}|~{3,})[ \t]*$")

# CI wrappers around a command line, stripped before lexing: a yaml list item
# (`- nthlayer ...`), a yaml key whose value is a command (`run:`, `script:`,
# `entry:`), and Jenkins `sh '...'` / `sh "..."`.
_LIST_ITEM = re.compile(r"^-\s+")
_COMMAND_KEY = re.compile(r"^(run|script|entry):\s*")
_JENKINS_SH = re.compile(r"""^sh\s+(['"])(.*)\1$""")

# CI templating that stands for one value: `${{ secrets.X }}` (GitHub Actions,
# contains spaces) and `$(params.x)` (Tekton, would lex as a subshell).
_CI_PLACEHOLDER = re.compile(r"\$\{\{.*?\}\}|\$\((?:params|inputs|context|workspaces)\.[^)]*\)")

# Shell keywords that may lead a command without being its argv[0].
_SHELL_KEYWORDS = frozenset({"if", "then", "elif", "else", "do", "!", "time", "exec", "while", "until"})

# Characters that, in a punctuation token shlex emits (punctuation_chars=True),
# end one command and start the next. shlex groups a run of them into one
# token — `);` in `$(nthlayer ...); do` — so a token made only of these is a
# separator whatever its length. Each side is checked on its own, so
# `nthlayer x | jq .` does not hand `|` and `jq` to argparse; unlike a regex
# split, a `|` inside a quoted jq filter is left alone; and the command inside
# `for x in $(nthlayer ...)` is collected as its own invocation.
_SEPARATOR_CHARS = frozenset("|&;()")

# Redirection operators. Everything after one, up to the next separator, is
# the shell's (the target, a `$(date ...)` in its name), not argv.
_REDIRECTS = frozenset({">", ">>", "<", "<<", ">&", "&>", ">|"})

# `<service.yaml>`, `{show,list}` — a metavariable standing for one argument.
# Substituted on the raw line, before lexing: shlex would otherwise read the
# angle brackets as redirections and the `|` in `{a|b}` as a pipe. A real
# redirection has whitespace after `<`, which this does not match.
_PLACEHOLDER = re.compile(r"<[A-Za-z][^<>\s]*>|\{[^{}\s]+\}")

# Synopsis words that stand for "any options follow" rather than an argument.
_OPTIONS_MARKERS = frozenset({"[options]", "[OPTIONS]", "[flags]", "..."})

# Stands in for a metavariable (`<service.yaml>`, `${{ secrets.X }}`) or a
# filename pre-commit would pass: one argument whose value the docs leave open.
PLACEHOLDER_ARG = "placeholder"


_ENV_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=.*")

# Runner options that take a separate value (`uvx --from DIST`); any runner
# option in `--opt=value` form is skipped too.
_RUNNER_VALUE_OPTIONS = frozenset({"--from", "--with", "--python", "--spec"})


def _fenced_blocks(text: str) -> list[tuple[int, list[str]]]:
    """(1-based line number of the first body line, body lines) per fence.

    An unclosed fence runs to the end of the page, as in CommonMark.
    """
    blocks: list[tuple[int, list[str]]] = []
    lines = text.split("\n")
    index = 0
    while index < len(lines):
        opening = _FENCE_OPEN.match(lines[index].rstrip("\r"))
        index += 1
        if not opening:
            continue
        marker = opening.group(1)
        if marker[0] == "`" and "`" in opening.group(2):
            continue  # not a fence: CommonMark forbids backticks in its info string
        start = index
        while index < len(lines):
            closing = _FENCE_CLOSE.match(lines[index].rstrip("\r"))
            if closing and closing.group(1)[0] == marker[0] and len(closing.group(1)) >= len(marker):
                break
            index += 1
        blocks.append((start + 1, lines[start:index]))
        index += 1  # past the closing line
    return blocks


def _runner_stripped(argv: list[str]) -> list[str]:
    """argv with leading shell keywords, env, sudo and a runner prefix removed.

    Recognised: shell keywords (`if`, `!`, `time`, ...), `VAR=value`
    assignments, `sudo`, `env [-flags] [VAR=value ...]`, and the runners whose
    next token is the console script: `uv run`, `uvx`, `pipx run`, each with
    `--opt value` (for the options in _RUNNER_VALUE_OPTIONS) or `--opt=value`
    options. Anything else (`pip install nthlayer`,
    `python -m nthlayer_workers.observe`) keeps its own argv[0] and is
    therefore not collected.
    """
    while argv:
        head = argv[0]
        if head in _SHELL_KEYWORDS or head == "sudo" or _ENV_ASSIGNMENT.fullmatch(head):
            argv = argv[1:]
        elif head == "env":
            argv = argv[1:]
            while argv and argv[0].startswith("-"):
                argv = argv[1:]
        else:
            break
    for prefix_len, prefix in ((2, ["uv", "run"]), (2, ["pipx", "run"]), (1, ["uvx"])):
        if argv[:prefix_len] == prefix:
            argv = argv[prefix_len:]
            while argv and argv[0].startswith("--"):
                if "=" in argv[0]:
                    argv = argv[1:]
                elif argv[0] in _RUNNER_VALUE_OPTIONS:
                    argv = argv[2:]
                else:
                    break
            break
    return argv


def _strip_synopsis_markup(argv: list[str]) -> list[str]:
    """Drop synopsis option markers and optional-group brackets.

    Strips every leading and trailing `[`/`]` from a token, so nested groups
    (`[--depth [N]]`) unwrap too; a token that was only brackets is dropped.
    """
    out: list[str] = []
    for token in argv:
        if token in _OPTIONS_MARKERS:
            continue
        # Optional-group brackets in a synopsis: `[--depth N]` → `--depth N`,
        # so the flag inside is still checked against the parser.
        token = token.strip("[]") if token.startswith("[") or token.endswith("]") else token
        if not token:
            continue
        out.append(token)
    return out


class _LexError(ValueError):
    """A documented shell line shlex cannot tokenise (e.g. an unbalanced quote)."""


def _split_commands(line: str, line_no: int) -> list[list[str]]:
    """One shell line as a list of simple commands' argv, redirections removed."""
    lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    # Comments are dropped below, at token starts only: shlex's own comment
    # handling also fires mid-word and would truncate `http://host/#anchor`.
    lexer.commenters = ""
    try:
        tokens = list(lexer)
    except ValueError as exc:
        raise _LexError(f"line {line_no}: unparseable shell {line!r}: {exc}") from exc
    commands: list[list[str]] = [[]]
    redirected = False
    for token in tokens:
        if token.startswith("#"):
            break
        if token in _REDIRECTS:
            # `2>&1` lexes as `2`, `>&`, `1`: the fd number is the shell's too.
            if commands[-1] and commands[-1][-1].isdigit():
                commands[-1].pop()
            redirected = True
        elif set(token) <= _SEPARATOR_CHARS:
            commands.append([])
            redirected = False
        elif not redirected:
            commands[-1].append(token)
    return [argv for argv in commands if argv]


def _unwrap(line: str) -> tuple[str, bool]:
    """A CI line reduced to its shell command, and whether it is a pre-commit entry."""
    line = _LIST_ITEM.sub("", line)
    key = _COMMAND_KEY.match(line)
    if key:
        line = line[key.end() :]
    jenkins = _JENKINS_SH.match(line)
    if jenkins:
        line = jenkins.group(2)
    if len(line) >= 2 and line[0] == line[-1] and line[0] in "'\"":
        line = line[1:-1]  # a quoted yaml scalar
    return line, bool(key and key.group(1) == "entry")


# --- pre-commit `entry:` handling -------------------------------------------
#
# pre-commit passes every matching staged file to `entry` in one call, so a
# hook is checked with two filenames appended: a subcommand taking a single
# positional must fail that check, because it fails in real use. A hook that
# sets `pass_filenames: false` gets none, and a command inside a `bash -c`
# entry gets none (the filenames go to bash, as "$@").

_PRECOMMIT_FILES = [PLACEHOLDER_ARG, PLACEHOLDER_ARG]

_PASS_FILENAMES_FALSE = re.compile(r"^\s*pass_filenames:\s*false\s*$")


def _hook_passes_filenames(lines: list[str], entry_index: int) -> bool:
    """False if the yaml list item holding `entry:` sets `pass_filenames: false`.

    The hook's item is the nearest preceding `- ` line indented less than the
    `entry:` key; it ends at the next line indented no deeper than that `- `.
    """
    entry_indent = len(lines[entry_index]) - len(lines[entry_index].lstrip())
    start = entry_index
    while start > 0:
        start -= 1
        candidate = lines[start]
        indent = len(candidate) - len(candidate.lstrip())
        if candidate.lstrip().startswith("- ") and indent < entry_indent:
            break
    item_indent = len(lines[start]) - len(lines[start].lstrip())
    end = start + 1
    while end < len(lines):
        line = lines[end]
        if line.strip() and len(line) - len(line.lstrip()) <= item_indent:
            break
        end += 1
    return not any(_PASS_FILENAMES_FALSE.match(line) for line in lines[start:end])


def _precommit_tail(lines: list[str], entry_index: int, is_entry: bool, direct: bool) -> list[str]:
    """The filenames pre-commit appends to this command, if any."""
    if is_entry and direct and _hook_passes_filenames(lines, entry_index):
        return _PRECOMMIT_FILES
    return []


# --- end pre-commit handling -------------------------------------------------


def _entry_point_argvs(command: str, line_no: int) -> list[tuple[list[str], bool]]:
    """(argv after the entry point, ran directly) for each nthlayer command.

    Recurses into `bash -c '...'` / `sh -c '...'` scripts; a command found
    there is not run directly, so pre-commit's filenames do not reach it.
    """
    found: list[tuple[list[str], bool]] = []
    for argv in _split_commands(command, line_no):
        argv = _runner_stripped(argv)
        if argv[:1] in (["bash"], ["sh"]) and argv[1:2] == ["-c"] and len(argv) > 2:
            found.extend((inner, False) for inner, _ in _entry_point_argvs(argv[2], line_no))
        elif argv and argv[0] in ENTRY_POINTS:
            found.append((_strip_synopsis_markup(argv[1:]), True))
    return found


def extract_invocations(
    text: str, errors: list[tuple[int, str]] | None = None
) -> list[tuple[int, list[str]]]:
    """(1-based line number, argv after the entry point) for each invocation.

    A line shlex cannot tokenise is appended to `errors` as (line, message)
    and skipped; with no `errors` list it raises AssertionError instead.
    """
    found: list[tuple[int, list[str]]] = []
    for body_start_line, lines in _fenced_blocks(text):
        index = 0
        while index < len(lines):
            line_no = body_start_line + index
            entry_index = index  # the logical line's first physical line
            logical = lines[index]
            # Join backslash continuations into one logical command line.
            while logical.rstrip().endswith("\\") and index + 1 < len(lines):
                index += 1
                logical = logical.rstrip()[:-1] + " " + lines[index]
            index += 1
            stripped = logical.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith("$ "):
                stripped = stripped[2:]
            if "nthlayer" not in stripped:
                continue
            command, precommit_entry = _unwrap(stripped)
            command = _CI_PLACEHOLDER.sub(PLACEHOLDER_ARG, _PLACEHOLDER.sub(PLACEHOLDER_ARG, command))
            try:
                argvs = _entry_point_argvs(command, line_no)
            except _LexError as exc:
                if errors is None:
                    raise AssertionError(str(exc)) from exc
                errors.append((line_no, str(exc)))
                continue
            for argv, direct in argvs:
                tail = _precommit_tail(lines, entry_index, precommit_entry, direct)
                found.append((line_no, argv + tail))
    return found


def _doc_pages() -> list[Path]:
    pages = sorted(DOCS_ROOT.rglob("*.md"))
    readme = REPO_ROOT / "README.md"
    assert readme.is_file(), f"{readme} is missing; the README is part of this guard's scope"
    pages.append(readme)
    return pages


def _all_invocations() -> tuple[list[tuple[str, int, list[str]]], list[tuple[str, int, str]]]:
    """(invocations, unlexable lines) across every page, each tagged page:line."""
    invocations: list[tuple[str, int, list[str]]] = []
    unlexable: list[tuple[str, int, str]] = []
    for page in _doc_pages():
        label = page.relative_to(REPO_ROOT).as_posix()
        errors: list[tuple[int, str]] = []
        for line_no, argv in extract_invocations(page.read_text(encoding="utf-8"), errors):
            invocations.append((label, line_no, argv))
        unlexable.extend((label, line_no, message) for line_no, message in errors)
    return invocations, unlexable


INVOCATIONS, UNLEXABLE = _all_invocations()


def test_collection_is_not_vacuous() -> None:
    assert len(INVOCATIONS) >= MIN_INVOCATIONS, (
        f"only {len(INVOCATIONS)} documented invocations collected; the extractor "
        "or the docs location has probably broken"
    )


def _all_option_strings() -> set[str]:
    """Every option string the parser or any (nested) subparser accepts."""
    known: set[str] = set()
    pending = [build_parser()]
    while pending:
        parser = pending.pop()
        for action in parser._actions:  # noqa: SLF001
            known.update(action.option_strings)
            if isinstance(action, argparse._SubParsersAction):  # noqa: SLF001
                pending.extend(action.choices.values())
    return known


def test_pages_with_invocations_matches_the_docs() -> None:
    # The per-page test below cannot notice its own list shrinking (an empty
    # tuple is a silent skip) or a new page joining; this equality can.
    actual = sorted({label for label, _, _ in INVOCATIONS})
    assert actual == list(PAGES_WITH_INVOCATIONS), (
        "the pages yielding `nthlayer` invocations changed; if deliberate, replace "
        "PAGES_WITH_INVOCATIONS with sorted({page for page, _, _ in INVOCATIONS}) "
        f"— missing: {sorted(set(PAGES_WITH_INVOCATIONS) - set(actual))}, "
        f"new: {sorted(set(actual) - set(PAGES_WITH_INVOCATIONS))}"
    )


@pytest.mark.parametrize("page", PAGES_WITH_INVOCATIONS)
def test_page_still_yields_invocations(page: str) -> None:
    assert any(label == page for label, _, _ in INVOCATIONS), (
        f"{page} no longer yields any `nthlayer` invocation; if that is deliberate, "
        "update PAGES_WITH_INVOCATIONS"
    )


def parse_error(argv: list[str], capsys: pytest.CaptureFixture[str]) -> str | None:
    """argparse's error for argv, or None if the real parser accepts it."""
    capsys.readouterr()  # discard anything captured before this call
    try:
        build_parser().parse_args(argv)
    except SystemExit as exc:
        if exc.code in (0, None):  # --help / --version
            return None
        stderr = capsys.readouterr().err
        # `nthlayer <command> --help`, `nthlayer slo <subcommand>`: a placeholder
        # standing for "any choice" cannot itself be a valid choice. argparse
        # has validated every token before it, but stops there — so flags after
        # it are checked against every flag any subcommand accepts.
        if f"invalid choice: '{PLACEHOLDER_ARG}'" in stderr:
            known = _all_option_strings()
            for token in argv:
                flag = token.split("=", 1)[0]
                if flag.startswith("-") and len(flag) > 1 and not flag[1:].isdigit() and flag not in known:
                    return f"{flag}: no subcommand accepts this option"
            return None
        lines = stderr.strip().splitlines()
        return lines[-1] if lines else f"exit {exc.code}"
    return None


@pytest.mark.parametrize(
    "argv",
    [pytest.param(argv, id=f"{page}:{line_no}") for page, line_no, argv in INVOCATIONS]
    # A line shlex cannot tokenise fails as its own case, named by page:line,
    # instead of erroring every test in this module at import.
    + [pytest.param(message, id=f"{page}:{line_no}") for page, line_no, message in UNLEXABLE],
)
def test_documented_invocation_parses(argv: list[str] | str, capsys: pytest.CaptureFixture[str]) -> None:
    assert not isinstance(argv, str), argv
    error = parse_error(argv, capsys)
    assert error is None, f"`nthlayer {shlex.join(argv)}` is rejected by the parser: {error}"


class TestExtraction:
    """Positive and negative controls for the extractor the parse test trusts."""

    # Shapes taken from pages on this site, not invented to suit the extractor:
    # `$ ` prompts (concepts/shift-left.md), `\` continuations and `<...>`
    # synopses (commands/*.md), a `|` inside a quoted jq filter and a
    # `$(date ...)` redirect target (the pre-3ntg commands/portfolio.md), a
    # `$(nthlayer ...)` substitution (commands/ownership.md, commands/identity.md),
    # `[--flag VALUE] [options]` synopses (reference/cli.md), an indented
    # fence (getting-started/adoption-path.md).
    def test_shapes(self) -> None:
        markdown = "\n".join(
            [
                "```bash",
                "$ nthlayer apply svc.yaml",
                "# nthlayer not-a-command",
                "nthlayer plan <service.yaml> \\",
                "  --env prod",
                "uv run nthlayer lint svc.yaml | jq . > out.json",
                "uvx --from nthlayer-generate nthlayer validate svc.yaml",
                "pip install nthlayer",
                "python -m nthlayer_workers.observe drift --service svc",
                "nthlayer-workers gate --help",
                "```",
                "",
                "```shell",
                "nthlayer migrate svc.yaml --format json | jq -e '.x[] | select(.y)'",
                "nthlayer migrate svc.yaml > report-$(date +%Y%m%d).json 2>&1",
                "for d in $(nthlayer ownership svc.yaml --format json); do echo $d; done",
                "```",
                "",
                "  ~~~console",
                "  nthlayer-generate slo show [--format json] [options]",
                "  ~~~",
                "",
                "Prose outside any fence: nthlayer apply ignored.yaml",
            ]
        )
        assert extract_invocations(markdown) == [
            (2, ["apply", "svc.yaml"]),
            (4, ["plan", PLACEHOLDER_ARG, "--env", "prod"]),
            (6, ["lint", "svc.yaml"]),
            (7, ["validate", "svc.yaml"]),
            (14, ["migrate", "svc.yaml", "--format", "json"]),
            (15, ["migrate", "svc.yaml"]),
            (16, ["ownership", "svc.yaml", "--format", "json"]),
            (20, ["slo", "show", "--format", "json"]),
        ]

    # CI shapes from this site's yaml/groovy/unlabelled fences: GitHub Actions
    # `run:` (index.md, validate/index.md), GitLab `script:` list items
    # (integrations/cicd.md), Jenkins `sh '...'` (integrations/cicd.md),
    # pre-commit `entry:` (validate/linting.md, commands/validate-spec.md),
    # `${{ secrets.X }}` values (integrations/cicd.md) and Tekton
    # `$(params.x)` (integrations/cicd.md).
    def test_ci_wrappers_in_any_fence(self) -> None:
        markdown = "\n".join(
            [
                "```yaml",
                "      - name: Lint",
                "        run: nthlayer apply svc.yaml --lint",
                "  script:",
                "    - nthlayer validate-spec services/",
                "        entry: nthlayer validate-metadata --strict",
                "        run: nthlayer validate-slo svc.yaml --prometheus-url ${{ secrets.PROM_URL }}",
                "        nthlayer plan $(params.service-file) --env prod",
                "```",
                "",
                "```groovy",
                "                sh 'nthlayer lint svc.yaml'",
                "```",
                "",
                "```",
                "nthlayer migrate svc.yaml --dry-run",
                "```",
                "",
                "```yaml",
                '        run: "nthlayer apply double.yaml"',
                "        run: 'nthlayer apply single.yaml'",
                "```",
            ]
        )
        assert extract_invocations(markdown) == [
            (3, ["apply", "svc.yaml", "--lint"]),
            (5, ["validate-spec", "services/"]),
            # pre-commit appends ALL matching staged filenames to `entry`.
            (6, ["validate-metadata", "--strict", PLACEHOLDER_ARG, PLACEHOLDER_ARG]),
            (7, ["validate-slo", "svc.yaml", "--prometheus-url", PLACEHOLDER_ARG]),
            (8, ["plan", PLACEHOLDER_ARG, "--env", "prod"]),
            (12, ["lint", "svc.yaml"]),
            (16, ["migrate", "svc.yaml", "--dry-run"]),
            # A quoted yaml scalar is unquoted before lexing.
            (20, ["apply", "double.yaml"]),
            (21, ["apply", "single.yaml"]),
        ]

    # pre-commit hook shapes (validate/linting.md, commands/validate-spec.md,
    # commands/validate-metadata.md): `entry:` gets every staged filename
    # unless its hook sets `pass_filenames: false`; a `bash -c` loop entry is
    # checked on the nthlayer command inside it.
    def test_precommit_entries(self) -> None:
        markdown = "\n".join(
            [
                "```yaml",
                "repos:",
                "  - repo: local",
                "    hooks:",
                "      - id: passes-files",
                "        entry: nthlayer validate-spec",
                "        language: system",
                "      - id: no-files",
                "        entry: nthlayer validate-spec services/",
                "        pass_filenames: false",
                "      - id: loop",
                "        entry: bash -c 'for f in \"$@\"; do nthlayer apply \"$f\" --lint || exit 1; done' --",
                "        language: system",
                "```",
            ]
        )
        assert extract_invocations(markdown) == [
            (6, ["validate-spec", PLACEHOLDER_ARG, PLACEHOLDER_ARG]),
            (9, ["validate-spec", "services/"]),
            (12, ["apply", "$f", "--lint"]),
        ]

    # Shell keywords leading a command (adoption-path.md and cicd.md use
    # `if [ ... ]; then` around gate calls) must not hide the invocation.
    def test_leading_shell_keywords(self) -> None:
        markdown = "\n".join(
            [
                "```bash",
                "if nthlayer validate svc.yaml; then echo ok; fi",
                "! nthlayer lint svc.yaml",
                "time nthlayer apply svc.yaml",
                "while nthlayer plan svc.yaml; do sleep 1; done",
                "until exec nthlayer migrate svc.yaml; do :; done",
                "```",
            ]
        )
        assert extract_invocations(markdown) == [
            (2, ["validate", "svc.yaml"]),
            (3, ["lint", "svc.yaml"]),
            (4, ["apply", "svc.yaml"]),
            (5, ["plan", "svc.yaml"]),
            (6, ["migrate", "svc.yaml"]),
        ]

    # A four-backtick fence quoting a ```bash example (CommonMark nesting, as
    # pymdownx.superfences allows) must not be closed by the inner fence; if
    # it were, everything after it would invert and the two ordinary fences
    # below would be read as prose.
    def test_longer_fence_is_not_closed_by_shorter(self) -> None:
        markdown = "\n".join(
            [
                "````markdown",
                "```bash",
                "nthlayer apply quoted.yaml",
                "```",
                # Still inside the outer fence: only a run of four or more closes it.
                "nthlayer lint between.yaml",
                "````",
                "",
                "```bash",
                "nthlayer bogus-one svc.yaml",
                "```",
                "",
                "```bash",
                "nthlayer bogus-two svc.yaml",
                "```",
            ]
        )
        assert extract_invocations(markdown) == [
            (3, ["apply", "quoted.yaml"]),
            (5, ["lint", "between.yaml"]),
            (9, ["bogus-one", "svc.yaml"]),
            (13, ["bogus-two", "svc.yaml"]),
        ]

    # CommonMark: a backtick fence's info string cannot contain a backtick, so
    # a line like this is inline code in prose, not a fence opening.
    def test_backtick_in_info_string_does_not_open_a_fence(self) -> None:
        markdown = "\n".join(
            [
                "```nthlayer `x` is inline code",
                "nthlayer prose-line not-in-a-fence",
                "```bash",
                "nthlayer lint a.yaml",
                "```",
            ]
        )
        assert extract_invocations(markdown) == [(4, ["lint", "a.yaml"])]

    # Current behaviour, pinned: CRLF pages extract exactly like LF pages.
    def test_crlf_matches_lf(self) -> None:
        lf = "```bash\nnthlayer plan svc.yaml \\\n  --env prod\n```\n"
        assert extract_invocations(lf.replace("\n", "\r\n")) == extract_invocations(lf) == [
            (2, ["plan", "svc.yaml", "--env", "prod"])
        ]

    # Current behaviour, pinned: a cmd.exe `^` continuation is NOT joined. The
    # `^` reaches argparse as an argument, so such a line fails loudly rather
    # than being checked with its tail missing.
    def test_caret_continuation_is_not_joined(self) -> None:
        markdown = "```bat\nnthlayer apply svc.yaml ^\n  --lint\n```"
        assert extract_invocations(markdown) == [(2, ["apply", "svc.yaml", "^"])]

    # Runner prefixes this site's readers plausibly paste.
    def test_more_runner_prefixes(self) -> None:
        markdown = "\n".join(
            [
                "```bash",
                "sudo nthlayer apply a.yaml",
                "env NTHLAYER_PROFILE=prod nthlayer apply b.yaml",
                "sudo env -i A=1 nthlayer apply c.yaml",
                "uvx --from=nthlayer-generate nthlayer apply d.yaml",
                "uv run --with=rich nthlayer apply e.yaml",
                "```",
            ]
        )
        assert extract_invocations(markdown) == [
            (2, ["apply", "a.yaml"]),
            (3, ["apply", "b.yaml"]),
            (4, ["apply", "c.yaml"]),
            (5, ["apply", "d.yaml"]),
            (6, ["apply", "e.yaml"]),
        ]

    # An unbalanced quote is a broken example on one line, not a reason to
    # error every test in the module at import.
    def test_unlexable_line_is_recorded_not_raised(self) -> None:
        markdown = "```bash\nnthlayer apply 'oops.yaml\nnthlayer lint ok.yaml\n```"
        errors: list[tuple[int, str]] = []
        assert extract_invocations(markdown, errors) == [(3, ["lint", "ok.yaml"])]
        assert [line for line, _ in errors] == [2]


class TestParseCheck:
    """Controls for parse_error: it must reject what this bead removed."""

    @pytest.mark.parametrize(
        "argv",
        [
            ["check-deploy", "svc.yaml"],  # a documented command that never existed
            ["apply", "svc.yaml", "--push"],  # ambiguous prefix of --push-grafana/--push-ruler
            ["slo", "list", "svc.yaml"],  # positional on a subcommand that takes none
            ["config", "show", "--no-such-flag"],  # undefined flag on a nested subcommand
        ],
    )
    def test_rejects(self, argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
        assert parse_error(argv, capsys) is not None

    @pytest.mark.parametrize(
        "argv",
        [
            [PLACEHOLDER_ARG, "--help"],  # `nthlayer <command> --help`
            ["slo", PLACEHOLDER_ARG, PLACEHOLDER_ARG],  # `nthlayer slo <subcommand> <service.yaml>`
            ["--version"],
        ],
    )
    def test_accepts_placeholder_choices_and_help(self, argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
        assert parse_error(argv, capsys) is None

    def test_placeholder_does_not_excuse_an_unknown_flag(self, capsys: pytest.CaptureFixture[str]) -> None:
        # `nthlayer <command> --bogus-flag`: argparse stops at the placeholder
        # choice, so the flag must be checked separately.
        assert parse_error([PLACEHOLDER_ARG, "--bogus-flag"], capsys) is not None
        assert parse_error(["slo", PLACEHOLDER_ARG, "--bogus-flag=1"], capsys) is not None

    def test_placeholder_does_not_excuse_a_bad_command(self, capsys: pytest.CaptureFixture[str]) -> None:
        # The placeholder exemption covers only the choice the placeholder sits in.
        assert parse_error(["drift", PLACEHOLDER_ARG], capsys) is not None
