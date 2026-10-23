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
"""

from __future__ import annotations

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

# Console scripts that reach `nthlayer_generate.demo:main` (pyproject
# [project.scripts]). Both run the same parser, so both are checked.
ENTRY_POINTS = frozenset({"nthlayer", "nthlayer-generate"})

# Any fenced block, whatever its info string: invocations also sit in yaml
# (GitHub Actions, GitLab, pre-commit, Tekton), groovy (Jenkins) and
# unlabelled fences. Leading indent is allowed (this site nests fences in
# lists), as is a trailing info string (```bash title="..."). The closing
# marker is back-referenced so ``` is not closed by ~~~.
_FENCE = re.compile(r"^[ \t]*(```|~~~)[^\n]*\n(.*?)^[ \t]*\1", re.M | re.S)

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


def _runner_stripped(argv: list[str]) -> list[str]:
    """argv with leading shell keywords, env assignments and a runner prefix removed.

    Only the runners whose next token is the console script are recognised:
    `uv run nthlayer`, `uvx nthlayer`, `uvx --from <dist> nthlayer`,
    `pipx run nthlayer`. Anything else (`pip install nthlayer`,
    `python -m nthlayer_workers.observe`) keeps its own argv[0] and is
    therefore not collected.
    """
    while argv and (argv[0] in _SHELL_KEYWORDS or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", argv[0])):
        argv = argv[1:]
    for prefix_len, prefix in ((2, ["uv", "run"]), (2, ["pipx", "run"]), (1, ["uvx"])):
        if argv[:prefix_len] == prefix:
            argv = argv[prefix_len:]
            if argv[:1] == ["--from"]:
                argv = argv[2:]
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
        raise AssertionError(f"line {line_no}: unparseable shell {line!r}: {exc}") from exc
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


def extract_invocations(text: str) -> list[tuple[int, list[str]]]:
    """(1-based line number, argv after the entry point) for each invocation."""
    found: list[tuple[int, list[str]]] = []
    for fence in _FENCE.finditer(text):
        body_start_line = text.count("\n", 0, fence.start(2)) + 1
        lines = fence.group(2).split("\n")
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
            for argv, direct in _entry_point_argvs(command, line_no):
                tail = _precommit_tail(lines, entry_index, precommit_entry, direct)
                found.append((line_no, argv + tail))
    return found


def _doc_pages() -> list[Path]:
    pages = sorted(DOCS_ROOT.rglob("*.md"))
    readme = REPO_ROOT / "README.md"
    if readme.is_file():
        pages.append(readme)
    return pages


def _all_invocations() -> list[tuple[str, int, list[str]]]:
    return [
        (page.relative_to(REPO_ROOT).as_posix(), line_no, argv)
        for page in _doc_pages()
        for line_no, argv in extract_invocations(page.read_text())
    ]


INVOCATIONS = _all_invocations()


def test_collection_is_not_vacuous() -> None:
    assert len(INVOCATIONS) >= MIN_INVOCATIONS, (
        f"only {len(INVOCATIONS)} documented invocations collected; the extractor "
        "or the docs location has probably broken"
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
        # has already validated every token before it to get this far.
        if f"invalid choice: '{PLACEHOLDER_ARG}'" in stderr:
            return None
        lines = stderr.strip().splitlines()
        return lines[-1] if lines else f"exit {exc.code}"
    return None


@pytest.mark.parametrize(
    "argv",
    [pytest.param(argv, id=f"{page}:{line_no}") for page, line_no, argv in INVOCATIONS],
)
def test_documented_invocation_parses(argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
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

    def test_placeholder_does_not_excuse_a_bad_command(self, capsys: pytest.CaptureFixture[str]) -> None:
        # The placeholder exemption covers only the choice the placeholder sits in.
        assert parse_error(["drift", PLACEHOLDER_ARG], capsys) is not None
