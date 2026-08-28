"""The init docs and the init parser must not drift (opensrm-noc6).

`docs-site/commands/init.md` promised `--name`, `--tier`, `--type` and
`--no-interactive`; the parser had none of them, so the documented
non-interactive invocation exited 2 on `unrecognized arguments`. Nothing
caught it because no test read the docs.

These tests take the DOCS as the fixture and the PARSER as the thing under
test, deliberately in that direction. A test that enumerated the parser's
flags and looked for them in prose would pass against a page documenting
four flags that do not exist — which is exactly the state this bead found.

Two pages document `init`, and the first version of this file guarded only
one of them; `docs-site/reference/cli.md` was still promising `--name` after
`commands/init.md` had been corrected. Every page that documents `init` is
listed in `DOC_PAGES`, and the same defect on a third page would be caught
only by adding it here.
"""

import argparse
import re
import shlex
from pathlib import Path

import pytest

from nthlayer_generate.demo import build_parser, main
from nthlayer_generate.specs.custom_templates import CustomTemplateLoader

DOCS_ROOT = Path(__file__).resolve().parents[1] / "docs-site"

# Every page documenting `nthlayer init`. `commands/init.md` is entirely about
# init; `reference/cli.md` covers every command, so only its `init` section is
# read — the rest of that page's flags belong to other subparsers.
DOC_PAGES = (
    DOCS_ROOT / "commands" / "init.md",
    DOCS_ROOT / "reference" / "cli.md",
)

# A fenced shell block. Leading whitespace is allowed because this docs-site
# nests fences inside numbered lists, and a trailing info string is allowed
# because it uses attributes like ```bash title="...".
# The closing marker is back-referenced so a ``` block cannot be closed by a
# ~~~ one. `~~~` is accepted because mkdocs.yml enables pymdownx.superfences,
# for which it is an equivalent fence.
_SHELL_FENCE = re.compile(
    r"^[ \t]*(```|~~~)[ \t]*(?:bash|sh|shell|console)\b[^\n]*\n(.*?)^[ \t]*\1",
    re.M | re.S,
)

# A flag token: one or two leading dashes then a letter. Deliberately does
# not match a bare `-`, so the ` - ` separators in the menu transcript and
# the option tables are not mistaken for flags.
_FLAG = re.compile(r"-{1,2}[A-Za-z][A-Za-z0-9-]*")

# `[options]`, `<path>`, `SERVICE_NAME` — a metavariable, not a real argument.
# Used with `search`, so the bracket class fires anywhere in a token while
# the anchored branch only fires on a token that is entirely upper-case.
_PLACEHOLDER = re.compile(r"[\[\]<>]|^[A-Z][A-Z0-9_]*$")

_HEADING = re.compile(r"^(#+)[ \t]+(.*?)[ \t]*$", re.M)

# Console scripts that reach demo:main. pyproject declares both, so an example
# spelled with either runs the same parser and must be checked the same way.
_ENTRY_POINTS = ("nthlayer", "nthlayer-generate")

# How many leading tokens may precede the entry point — `uv run nthlayer`,
# `uvx --from nthlayer-generate nthlayer`. Scanning for the entry point beats
# stripping a list of known runners: `python -m nthlayer` would have been
# accepted and run despite there being no __main__, and
# `uvx --from x nthlayer` would have been skipped.
_MAX_RUNNER_TOKENS = 5

# Shell operators that chain two commands on one line. Each side is treated as
# its own invocation; without this the tail lands in argv and argparse reports
# `unrecognized arguments` on a line that is perfectly valid shell.
_SHELL_OPERATOR = re.compile(r"\s*(?:&&|\|\||;|\|)\s*")

# A fence opening or closing line, capturing the marker run so a four-backtick
# superfence is not closed by the three-backtick fence it wraps.
_FENCE_LINE = re.compile(r"^[ \t]*(`{3,}|~{3,})([^\n]*)$", re.M)

# Any fenced block, whatever its language — the masking counterpart of
# _SHELL_FENCE above. Edit the two together; this one accepts any info
# string, requires a bare closing line, and captures no body.
_ANY_FENCE = re.compile(r"^[ \t]*(```|~~~).*?^[ \t]*\1[ \t]*$", re.M | re.S)

# The heading that opens an init section: `# nthlayer init`, `### init`, or
# either wrapped in backticks.
_INIT_HEADING = re.compile(r"`?(?:nthlayer[ \t]+)?init`?", re.I)


def _init_parser() -> argparse.ArgumentParser:
    """The `init` subparser out of the real top-level parser."""
    parser = build_parser()
    subparsers = next(
        action
        for action in parser._actions  # noqa: SLF001
        if isinstance(action, argparse._SubParsersAction)  # noqa: SLF001
    )
    return subparsers.choices["init"]


def _parser_flags() -> set[str]:
    """Every option string `nthlayer init` accepts."""
    return {
        option
        for action in _init_parser()._actions  # noqa: SLF001
        for option in action.option_strings
    }


def _mask_fences(text: str) -> str:
    """The same text with fenced-block bodies blanked, offsets preserved.

    Headings have to be found outside code. `commands/init.md` opens a shell
    block with `# List available templates`; read as a heading, that single
    line ends the page's only section and takes Non-Interactive Mode — the
    part this bead exists to guard — out of range.
    """
    masked = list(text)
    for match in _ANY_FENCE.finditer(text):
        for index in range(match.start(), match.end()):
            if masked[index] != "\n":
                masked[index] = " "
    return "".join(masked)


def _init_section(text: str) -> str:
    """The slice of a page that documents `init`.

    Runs from its heading to the next heading of the same or higher level, so
    a per-command reference page contributes only its own `init` section.
    """
    masked = _mask_fences(text)
    for heading in _HEADING.finditer(masked):
        level = len(heading.group(1))
        if not _INIT_HEADING.fullmatch(heading.group(2)):
            continue
        for later in _HEADING.finditer(masked, heading.end()):
            if len(later.group(1)) <= level:
                return text[heading.start() : later.start()]
        return text[heading.start() :]
    raise AssertionError("no heading introducing an `init` section")


def _init_docs() -> list[tuple[str, str]]:
    """(label, markdown) for every place documenting `nthlayer init`."""
    docs = []
    for page in DOC_PAGES:
        label = page.relative_to(DOCS_ROOT).as_posix()
        assert page.is_file(), f"{label} is listed in DOC_PAGES but does not exist"
        # CRLF would defeat every `[ \t]*$` anchor below — fences would stop
        # masking and headings would stop matching — so normalise once here.
        text = page.read_text().replace("\r\n", "\n")
        try:
            docs.append((label, _init_section(text)))
        except AssertionError as exc:
            raise AssertionError(f"{label}: {exc}") from exc
    return docs


def _documented_invocations(text: str) -> list[list[str]]:
    """Every `nthlayer init ...` command line in a shell block, as argv.

    argv is returned in the shape `main()` takes: the leading `nthlayer` is
    stripped and `init` retained, so a result can be passed straight to
    `main(argv)` or `build_parser().parse_args(argv)`. `_service_name` reads
    the positional out of it.

    Backslash continuations are joined, `#` comment lines dropped, and a
    `console`-style `$ ` prompt stripped, so a multi-line example comes back
    as the single command a reader would run.
    """
    invocations = []
    for _marker, block in _SHELL_FENCE.findall(text):
        for line in block.replace("\\\n", " ").splitlines():
            line = line.strip().removeprefix("$ ")
            for command in _SHELL_OPERATOR.split(line):
                try:
                    argv = shlex.split(command, comments=True)
                except ValueError as exc:
                    # An unbalanced quote is a broken example, not a test bug.
                    raise AssertionError(f"unparseable shell line {command!r}: {exc}") from exc
                argv = _strip_runner(argv)
                if len(argv) >= 2 and argv[0] in _ENTRY_POINTS and argv[1] == "init":
                    invocations.append(argv[1:])
    return invocations


def _strip_runner(argv: list[str]) -> list[str]:
    """Drop any runner prefix so the entry point running `init` leads argv.

    Anchoring on the entry point *followed by* `init` matters: in
    `uvx --from nthlayer-generate nthlayer init`, the dist name appears first
    as the `--from` value, and matching that would leave `init` at argv[2]
    where the caller looks for it at argv[1] — a silent skip.
    """
    for index, token in enumerate(argv[:_MAX_RUNNER_TOKENS]):
        if argv[index - 1 : index] == ["-m"]:
            # `python -m nthlayer` is not runnable — the package ships two
            # console scripts and no __main__ — so it must not be recognised
            # and then executed by the end-to-end test, which would certify a
            # command that raises ModuleNotFoundError as pasteable.
            continue
        if token in _ENTRY_POINTS and argv[index + 1 : index + 2] == ["init"]:
            return argv[index:]
    return argv


def _unclosed_fence(text: str) -> str | None:
    """The opening line of the first fence never closed, or None.

    Pairs markers rather than counting them. A count is even for two unclosed
    fences and odd for a page that merely quotes fence syntax, so it both
    misses real breakage and fires on correct pages.
    """
    opening: tuple[str, str] | None = None
    for match in _FENCE_LINE.finditer(text):
        marker, info = match.group(1), match.group(2).strip()
        if opening is None:
            opening = (marker, match.group(0).strip())
        elif marker[0] == opening[0][0] and len(marker) >= len(opening[0]) and not info:
            opening = None
    return opening[1] if opening else None


def _runnable_invocations(text: str) -> list[list[str]]:
    """The documented invocations a reader could paste and run.

    Excludes the synopsis and anything else carrying a `[optional]` or
    `<placeholder>` metavariable — those describe a shape rather than a
    command, so parsing or running them proves nothing.
    """
    return [
        argv
        for argv in _documented_invocations(text)
        if not any(_PLACEHOLDER.search(arg) for arg in argv)
    ]


def _value_taking_flags() -> set[str]:
    """Init's option strings that consume a following token."""
    return {
        option
        for action in _init_parser()._actions  # noqa: SLF001
        for option in action.option_strings
        if action.nargs != 0
    }


def _service_name(argv: list[str]) -> str | None:
    """The positional service name in an argv, or None for a bare `init`.

    A flag's value is not a positional: in `init --team platform`, `platform`
    belongs to `--team`. Which flags consume a token is read off the parser
    rather than hardcoded, so adding one cannot silently break this.
    """
    takes_value = _value_taking_flags()
    remaining = iter(argv[1:])
    for arg in remaining:
        if arg in takes_value:
            next(remaining, None)
        elif not arg.startswith("-"):
            return arg
    return None


def _flag_value(argv: list[str], flag: str) -> str | None:
    """The value following `flag` in argv, or None if absent or trailing."""
    if flag not in argv:
        return None
    value_at = argv.index(flag) + 1
    return argv[value_at] if value_at < len(argv) else None


def _documented_flags(text: str) -> set[str]:
    """Flags the docs claim `init` takes: from the examples and the table."""
    flags = {arg for argv in _documented_invocations(text) for arg in argv if _FLAG.fullmatch(arg)}

    # The Options table renders each option in the first cell, e.g.
    # `| `--output, -o PATH` | Output file path |`. Only the first cell is
    # read; a prose description may legitimately name another command's flag.
    # `lstrip` because this docs-site indents tables under list items, the same
    # reason the fence regex allows a leading indent. Read over the masked text
    # for the same reason _init_section is: a `|` line inside a fence is table
    # syntax to this loop but output to a reader.
    for line in _mask_fences(text).splitlines():
        stripped = line.lstrip()
        if not stripped.startswith("|"):
            continue
        first_cell = stripped.split("|")[1]
        for token in re.split(r"[\s,`]+", first_cell):
            if _FLAG.fullmatch(token):
                flags.add(token)

    return flags


def _all_runnable_invocations() -> list[tuple[str, list[str]]]:
    """(label, argv) for every runnable example across every page."""
    return [(label, argv) for label, text in _init_docs() for argv in _runnable_invocations(text)]


class TestMarkdownExtraction:
    """Positive controls for the helpers above.

    Every other test in this file is only as good as this extraction. A regex
    that silently matched nothing would leave them green and vacuous, which is
    the same failure mode as the bug they exist to catch.
    """

    MARKDOWN = """
# nthlayer init

```bash
nthlayer init plain-service --team platform
```

1. Indented inside a list, as this docs-site already does elsewhere:

   ```bash
   nthlayer init indented-service --team platform
   ```

```bash title="attributed fence"
nthlayer init attributed-service --team platform
```

```console
$ nthlayer init prompted-service --team platform
```

```bash
# A comment line, and a continuation:
nthlayer init continued-service \\
  --team platform \\
  --no-interactive
```

~~~bash
nthlayer init tilde-service --team platform
~~~

```bash
nthlayer-generate init sibling-entrypoint-service --team platform
uv run nthlayer init runner-prefixed-service --team platform
```

An Options table indented under a list item:

1. Like so:

   | Option | Description |
   |--------|-------------|
   | `--indented-table-flag` | Must still be seen |

```yaml
nthlayer init not-a-shell-block --team platform
```

# validate

```bash
nthlayer init wrong-section --team platform
```
"""

    def test_every_fence_form_is_seen(self):
        names = [
            _service_name(argv) for argv in _documented_invocations(_init_section(self.MARKDOWN))
        ]
        assert names == [
            "plain-service",
            "indented-service",
            "attributed-service",
            "prompted-service",
            "continued-service",
            "tilde-service",
            "sibling-entrypoint-service",
            "runner-prefixed-service",
        ], "a shell-block form or command spelling is being skipped"

    def test_continuations_are_joined(self):
        continued = next(
            argv
            for argv in _documented_invocations(_init_section(self.MARKDOWN))
            if _service_name(argv) == "continued-service"
        )
        assert continued == [
            "init",
            "continued-service",
            "--team",
            "platform",
            "--no-interactive",
        ]

    def test_sections_of_other_commands_are_excluded(self):
        section = _init_section(self.MARKDOWN)
        assert "wrong-section" not in section
        assert "not-a-shell-block" in section  # in range, but not a shell fence

    def test_section_stops_at_a_higher_level_heading(self):
        """The `<` half of `<=`, which neither real page exercises today.

        `reference/cli.md` happens to follow `### init` with another `###`.
        Were init its last command before a `## Environment Variables`, an
        equality-only stop would swallow the rest of the page.
        """
        markdown = (
            "## Commands\n\n### init\n\n```bash\nnthlayer init mine --team platform\n```\n\n"
            "## Environment Variables\n\n```bash\nnthlayer init leaked --team platform\n```\n"
        )
        names = [_service_name(argv) for argv in _documented_invocations(_init_section(markdown))]
        assert names == ["mine"]

    def test_indented_option_tables_are_read(self):
        """The table half of _documented_flags had no positive control.

        It is also where the phantom flags this bead removed actually lived,
        so a silently-vacuous table scan is the likeliest way they come back.
        """
        assert "--indented-table-flag" in _documented_flags(_init_section(self.MARKDOWN))

    def test_an_unbalanced_quote_names_the_offending_line(self):
        markdown = "# init\n\n```bash\nnthlayer init 'unclosed --team platform\n```\n"
        with pytest.raises(AssertionError, match="unparseable shell line"):
            _documented_invocations(markdown)

    def test_crlf_pages_are_normalised(self, tmp_path, monkeypatch):
        """CRLF defeats every `[ \\t]*$` anchor: fences stop masking, headings
        stop matching. _init_docs normalises at read; without it this raises.
        """
        page = tmp_path / "commands" / "init.md"
        page.parent.mkdir(parents=True)
        page.write_text(self.MARKDOWN.replace("\n", "\r\n"))
        monkeypatch.setattr("test_init_documented_flags.DOCS_ROOT", tmp_path)
        monkeypatch.setattr("test_init_documented_flags.DOC_PAGES", (page,))

        ((label, text),) = _init_docs()
        assert label == "commands/init.md"
        assert "plain-service" in text

    def test_a_missing_page_names_itself(self, tmp_path, monkeypatch):
        missing = tmp_path / "commands" / "gone.md"
        monkeypatch.setattr("test_init_documented_flags.DOCS_ROOT", tmp_path)
        monkeypatch.setattr("test_init_documented_flags.DOC_PAGES", (missing,))

        with pytest.raises(AssertionError, match="commands/gone.md is listed in DOC_PAGES"):
            _init_docs()

    def test_a_missing_init_heading_is_diagnosable(self):
        with pytest.raises(AssertionError, match="no heading introducing"):
            _init_section("# validate\n\nNothing about init here.\n")

    def test_runner_prefixes_and_entry_points(self):
        """Pin what leads an invocation, so the constants cannot drift silently."""
        assert _strip_runner(["uv", "run", "nthlayer", "init"]) == ["nthlayer", "init"]
        assert _strip_runner(["uvx", "--from", "nthlayer-generate", "nthlayer", "init"]) == [
            "nthlayer",
            "init",
        ]
        assert _strip_runner(["nthlayer-generate", "init"]) == ["nthlayer-generate", "init"]
        # `pip install nthlayer` is not an invocation of init.
        assert _strip_runner(["pip", "install", "nthlayer"]) == ["pip", "install", "nthlayer"]
        # No __main__ module exists, so `python -m nthlayer` is not runnable and
        # must not be certified as such by the end-to-end test.
        assert (
            _documented_invocations("# init\n\n```bash\npython -m nthlayer init a --team p\n```\n")
            == []
        )

    def test_chained_commands_are_split(self):
        markdown = (
            "# init\n\n```bash\n"
            "nthlayer init chained --team platform && nthlayer validate chained.yaml\n"
            "```\n"
        )
        invocations = _documented_invocations(markdown)
        assert invocations == [["init", "chained", "--team", "platform"]]
        # The `&&` tail must not survive into argv, where argparse would report
        # `unrecognized arguments` on a line that is valid shell.
        build_parser().parse_args(invocations[0])

    def test_service_name_ignores_flag_values(self):
        assert _service_name(["init", "--team", "platform"]) is None
        assert _service_name(["init", "--team=platform"]) is None
        assert _service_name(["init", "--team=platform", "svc"]) == "svc"
        assert _service_name(["init", "--no-interactive", "svc"]) == "svc"
        assert _service_name(["init", "--template", "critical-api", "svc"]) == "svc"

    def test_unclosed_fences_are_detected_and_correct_pages_are_not(self):
        """The negative control for test_every_fence_is_closed.

        Both real pages are balanced, so without this nothing proves the
        assertion can fire — nor that it stays quiet on a page that merely
        quotes fence syntax.
        """
        assert _unclosed_fence("```bash\nnthlayer init a\n```\n") is None
        assert _unclosed_fence("```bash\nnthlayer init a\n") == "```bash"
        # Two unclosed fences: an even marker count that a parity check passed.
        assert _unclosed_fence("```bash\nfirst\n```bash\nsecond\n") == "```bash"
        # A block quoting fence syntax is odd-counted but correctly closed.
        assert _unclosed_fence("```text\n```bash\n```\n") is None
        # A four-backtick superfence is not closed by the fence it wraps.
        assert _unclosed_fence("````md\n```bash\nx\n```\n````\n") is None

    def test_placeholders_are_not_runnable(self):
        markdown = "# init\n\n```bash\nnthlayer init [SERVICE_NAME] [options]\n```\n"
        assert _documented_invocations(markdown)
        assert not _runnable_invocations(markdown)


@pytest.mark.parametrize(
    "label,text", [pytest.param(label, text, id=label) for label, text in _init_docs()]
)
class TestDocumentedFlagsExist:
    """Every flag the docs promise is a flag the parser accepts."""

    def test_the_page_documents_some_flags(self, label, text):
        # Guards the guard: a page that stopped mentioning flags at all, or a
        # regex that stopped matching, would otherwise make the tests below
        # vacuously green.
        assert _documented_flags(text), f"no flags parsed out of {label}"

    def test_every_fence_is_closed(self, label, text):
        """An unclosed fence pairs with the NEXT fence's opening line.

        Everything between them stops being read, and nothing fails — the
        silent-coverage-loss case the extraction tests cannot see.
        """
        unclosed = _unclosed_fence(text)
        assert unclosed is None, f"{label} has an unclosed code fence: {unclosed}"

    def test_every_documented_flag_is_accepted(self, label, text):
        undefined = _documented_flags(text) - _parser_flags()
        assert not undefined, (
            f"{label} documents flags the init parser does not define: {sorted(undefined)}"
        )

    def test_documented_invocations_parse(self, label, text):
        # Not asserted non-empty per page: `reference/cli.md` is a synopsis
        # index with no runnable example, by that page's house style.
        # Non-vacuity is covered by the other tests here and below.
        parser = build_parser()
        for argv in _runnable_invocations(text):
            parser.parse_args(argv)


class TestNonInteractiveFlag:
    """`--no-interactive` reaches `init_command(interactive=False)`.

    The last test here is docs-driven rather than unit-ish; it lives in this
    class because it needs the `no_prompting` fixture.
    """

    @pytest.fixture
    def no_prompting(self, monkeypatch):
        """Turn any prompt into a failure rather than a hang."""

        def _refuse(*args, **kwargs):
            raise AssertionError("init prompted in non-interactive mode")

        for name in ("text_input", "select", "multi_select"):
            monkeypatch.setattr(f"nthlayer_generate.cli.init.{name}", _refuse)

    def test_writes_a_manifest_without_prompting(self, tmp_path, monkeypatch, no_prompting):
        monkeypatch.chdir(tmp_path)

        with pytest.raises(SystemExit) as exit_info:
            main(["init", "my-service", "--team", "platform", "--no-interactive"])

        assert exit_info.value.code == 0

        # Assert on the file, not on stdout: a run that never prompted but
        # wrote nothing would satisfy "did not hang" and still be broken.
        manifest = tmp_path / "my-service.yaml"
        assert manifest.exists()
        content = manifest.read_text()
        assert "name: my-service" in content
        assert "team: platform" in content
        # The defaults init falls back to when no menu ran (cli/init.py).
        assert "tier: standard" in content
        assert "type: api" in content

    def test_omitting_the_flag_still_prompts(self, tmp_path, monkeypatch, no_prompting):
        """The flag's absence must not silently mean non-interactive.

        Without this, defaulting `interactive` the wrong way round would leave
        every assertion above passing.
        """
        monkeypatch.chdir(tmp_path)

        with pytest.raises(AssertionError, match="prompted in non-interactive mode"):
            main(["init", "--team", "platform"])

    def test_documented_non_interactive_commands_succeed(self, tmp_path, monkeypatch, no_prompting):
        """Run the docs' own non-interactive examples, verbatim."""
        examples = [
            (label, argv)
            for label, argv in _all_runnable_invocations()
            if "--no-interactive" in argv
        ]
        assert examples, "the init docs no longer show a --no-interactive example"

        for index, (label, argv) in enumerate(examples):
            # A fresh directory per example: init refuses to overwrite, so two
            # examples naming the same service would fail on the second.
            workdir = tmp_path / f"example-{index}"
            workdir.mkdir()
            monkeypatch.chdir(workdir)

            with pytest.raises(SystemExit) as exit_info:
                main(argv)
            assert exit_info.value.code == 0, f"{label}: `nthlayer init {argv}` failed"
            assert list(workdir.glob("*.yaml")), f"{label}: wrote no manifest"


class TestDocumentedTemplatesExist:
    """`--template TEMPLATE` examples must name templates the registry has."""

    def test_documented_template_names_resolve(self, tmp_path, monkeypatch):
        # CustomTemplateLoader walks up from cwd looking for .nthlayer/templates,
        # so without this the result depends on where pytest was invoked — and
        # could disagree with the sibling test, which runs from tmp_path.
        monkeypatch.chdir(tmp_path)
        registry = CustomTemplateLoader.load_all_templates()
        documented = {
            name
            for _label, argv in _all_runnable_invocations()
            if (name := _flag_value(argv, "--template")) is not None
        }
        assert documented, "the init docs no longer show a --template example"

        unknown = {name for name in documented if not registry.exists(name)}
        assert not unknown, (
            f"the init docs show templates that do not exist: {sorted(unknown)}; "
            f"available: {sorted(registry.templates)}"
        )
