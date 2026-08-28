"""The init docs page and the init parser must not drift (opensrm-noc6).

`docs-site/commands/init.md` promised `--name`, `--tier`, `--type` and
`--no-interactive`; the parser had none of them, so the documented
non-interactive invocation exited 2 on `unrecognized arguments`. Nothing
caught it because no test read the docs.

These tests take the DOC as the fixture and the PARSER as the thing under
test, deliberately in that direction. A test that enumerated the parser's
flags and looked for them in prose would pass against a page documenting
four flags that do not exist — which is exactly the state this bead found.
"""

import argparse
import re
import shlex
from pathlib import Path

import pytest

from nthlayer_generate.demo import build_parser, main

DOC_PATH = Path(__file__).resolve().parents[1] / "docs-site" / "commands" / "init.md"

# Fenced blocks whose info string marks them as shell. The page also has
# unfenced-language blocks (the transcript of an interactive session, the
# generated YAML) which are output, not invocations.
_SHELL_FENCE = re.compile(r"^```(?:bash|sh|shell|console)\n(.*?)^```", re.M | re.S)

# A flag token: one or two leading dashes then a letter. Deliberately does
# not match a bare `-`, so the ` - ` separators in the menu transcript and
# the option tables are not mistaken for flags.
_FLAG = re.compile(r"^-{1,2}[A-Za-z][A-Za-z0-9-]*$")

# `[options]`, `<path>`, `SERVICE_NAME` — a metavariable, not a real argument.
_PLACEHOLDER = re.compile(r"[\[\]<>]|^[A-Z][A-Z0-9_]*$")


def _init_parser() -> argparse.ArgumentParser:
    """The `init` subparser out of the real top-level parser."""
    parser = build_parser()
    subparsers = next(
        action
        for action in parser._actions
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


def _doc_text() -> str:
    return DOC_PATH.read_text()


def _documented_invocations(text: str) -> list[list[str]]:
    """Every `nthlayer init ...` command line in a shell block, as argv.

    Backslash continuations are joined and `#` comment lines dropped, so a
    multi-line example is returned as the single command a user would run.
    """
    invocations = []
    for block in _SHELL_FENCE.findall(text):
        for line in block.replace("\\\n", " ").splitlines():
            argv = shlex.split(line, comments=True)
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


def _documented_flags(text: str) -> set[str]:
    """Flags the page claims `init` takes: from its examples and its table."""
    flags = {arg for argv in _documented_invocations(text) for arg in argv if _FLAG.match(arg)}

    # The Options table renders each option in the first cell, e.g.
    # `| `--output, -o PATH` | Output file path |`. Only the first cell is
    # read; a prose description may legitimately name another command's flag.
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        first_cell = line.split("|")[1]
        for token in re.split(r"[\s,`]+", first_cell):
            if _FLAG.match(token):
                flags.add(token)

    return flags


class TestDocumentedFlagsExist:
    """Every flag the page promises is a flag the parser accepts."""

    def test_the_page_documents_some_flags(self):
        # Guards the guard: a page that stopped mentioning flags at all, or a
        # regex that stopped matching, would otherwise make the test below
        # vacuously green.
        assert _documented_flags(_doc_text()), "no flags parsed out of the init docs"

    def test_every_documented_flag_is_accepted(self):
        undefined = _documented_flags(_doc_text()) - _parser_flags()
        assert not undefined, (
            f"{DOC_PATH.name} documents flags the init parser does not define: {sorted(undefined)}"
        )

    def test_documented_invocations_parse(self):
        parser = build_parser()
        for argv in _runnable_invocations(_doc_text()):
            parser.parse_args(argv)


class TestNonInteractiveFlag:
    """`--no-interactive` reaches `init_command(interactive=False)`."""

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

    def test_the_documented_non_interactive_command_succeeds(
        self, tmp_path, monkeypatch, no_prompting
    ):
        """Run the page's own non-interactive example, verbatim."""
        monkeypatch.chdir(tmp_path)

        examples = [
            argv for argv in _runnable_invocations(_doc_text()) if "--no-interactive" in argv
        ]
        assert examples, "the init docs no longer show a --no-interactive example"

        for index, argv in enumerate(examples):
            # A fresh directory per example: init refuses to overwrite, so two
            # examples naming the same service would fail on the second.
            workdir = tmp_path / f"example-{index}"
            workdir.mkdir()
            monkeypatch.chdir(workdir)

            with pytest.raises(SystemExit) as exit_info:
                main(argv)
            assert exit_info.value.code == 0, f"documented command failed: nthlayer init {argv}"
            assert list(workdir.glob("*.yaml")), f"wrote no manifest: nthlayer init {argv}"


class TestDocumentedTemplatesExist:
    """`--template NAME` examples must name templates the registry has."""

    def test_documented_template_names_resolve(self):
        from nthlayer_generate.specs.custom_templates import CustomTemplateLoader

        registry = CustomTemplateLoader.load_all_templates()
        documented = {
            argv[argv.index("--template") + 1]
            for argv in _runnable_invocations(_doc_text())
            if "--template" in argv and argv.index("--template") + 1 < len(argv)
        }
        unknown = {name for name in documented if not registry.exists(name)}
        assert not unknown, (
            f"{DOC_PATH.name} shows templates that do not exist: {sorted(unknown)}; "
            f"available: {sorted(registry.templates)}"
        )
