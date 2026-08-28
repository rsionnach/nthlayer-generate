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
    return [
        (page.relative_to(DOCS_ROOT).as_posix(), _init_section(page.read_text()))
        for page in DOC_PAGES
    ]


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
            argv = shlex.split(line.strip().removeprefix("$ "), comments=True)
            if argv[:2] == ["nthlayer", "init"]:
                invocations.append(argv[1:])
    return invocations


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


def _service_name(argv: list[str]) -> str:
    """The positional service name out of an argv from _documented_invocations."""
    return argv[1]


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
    # Read over the masked text for the same reason _init_section is: a `|`
    # line inside a fence is table syntax to this loop but output to a reader.
    for line in _mask_fences(text).splitlines():
        if not line.startswith("|"):
            continue
        first_cell = line.split("|")[1]
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
        ], "a shell-block form this docs-site uses is being skipped"

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

    def test_documented_template_names_resolve(self):
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
