"""Every text read and write in the package names its encoding (opensrm-may6).

`open(path)`, `read_text()` and `write_text()` use the locale's encoding when
none is given. Under a single-byte locale a UTF-8 custom template then loads
with its non-ASCII names garbled, or not at all, and a write of non-ASCII text
fails after the file has been created (opensrm-t4rd's zero-byte manifest).

The structural test covers every module under `src/nthlayer_generate`. It
replaces a count of "about 40 bare open() sites": the walk found 48, and all
of them now pass `encoding="utf-8"`. The behavioural test runs the template
loader in a child process whose default encoding really is ASCII.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

import nthlayer_generate

PACKAGE_DIR = Path(nthlayer_generate.__file__).resolve().parent
PACKAGE_MODULES = sorted(PACKAGE_DIR.rglob("*.py"))
assert PACKAGE_MODULES

# Calls that open a file as text and default to the locale's encoding.
_TEXT_IO_NAMES = {
    "open",
    "read_text",
    "write_text",
    "fdopen",
    "NamedTemporaryFile",
    "TemporaryFile",
    "SpooledTemporaryFile",
}

# `<module>.open(...)` calls that are not file opens, or take no encoding.
# `os.open` returns a file descriptor.
_NOT_A_TEXT_OPEN = {("os", "open"), ("webbrowser", "open")}


def _mode_of(call: ast.Call) -> str | None:
    """The literal mode string of an ``open``-like call, if it has one."""
    for keyword in call.keywords:
        if keyword.arg == "mode":
            value = keyword.value
            return value.value if isinstance(value, ast.Constant) else None
    name = call.func.attr if isinstance(call.func, ast.Attribute) else call.func.id
    # builtin open(path, mode); Path.open(mode) and os.fdopen(fd, mode) differ
    position = 0 if isinstance(call.func, ast.Attribute) and name == "open" else 1
    if name in ("NamedTemporaryFile", "TemporaryFile"):
        position = 0
    if len(call.args) > position:
        value = call.args[position]
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return value.value
    return None


def text_io_without_encoding(source: str) -> tuple[list[int], int]:
    """Lines of text-IO calls with no ``encoding=``, and how many calls were seen.

    A call whose literal mode contains ``b`` is binary and is skipped. The
    temporary-file helpers default to binary, so they are checked only when
    their literal mode is a text mode. Anything else that is called ``open``
    is checked: the check fails closed, and a new non-file ``open`` is added
    to ``_NOT_A_TEXT_OPEN`` by hand.
    """
    offenders: list[int] = []
    seen = 0
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute):
            name = func.attr
            owner = getattr(func.value, "id", None)
            if (owner, name) in _NOT_A_TEXT_OPEN:
                continue
        elif isinstance(func, ast.Name):
            name = func.id
        else:
            continue
        if name not in _TEXT_IO_NAMES:
            continue
        mode = _mode_of(node)
        if mode is not None and "b" in mode:
            continue
        if name.endswith("TemporaryFile") and mode is None:
            continue  # binary by default
        seen += 1
        if not any(keyword.arg == "encoding" for keyword in node.keywords):
            offenders.append(node.lineno)
    return offenders, seen


FLAGGED = [
    pytest.param("open(p)\n", id="bare-open"),
    pytest.param("open(p, 'w')\n", id="open-for-writing"),
    pytest.param("open(p, mode='a')\n", id="mode-keyword"),
    pytest.param("p.open()\n", id="path-open"),
    pytest.param("p.read_text()\n", id="read-text"),
    pytest.param("p.write_text(s)\n", id="write-text"),
    pytest.param("os.fdopen(fd, 'w')\n", id="fdopen"),
    pytest.param("tempfile.NamedTemporaryFile('w')\n", id="text-temporary-file"),
    pytest.param("tempfile.NamedTemporaryFile(mode='w+')\n", id="text-temporary-file-keyword"),
    pytest.param("open(p, mode)\n", id="mode-not-a-literal"),
]
assert FLAGGED

ACCEPTED = [
    pytest.param("open(p, encoding='utf-8')\n", 1, id="open-with-encoding"),
    pytest.param("p.write_text(s, encoding='utf-8')\n", 1, id="write-text-with-encoding"),
    pytest.param("open(p, 'rb')\n", 0, id="binary-read"),
    pytest.param("p.open('wb')\n", 0, id="binary-path-open"),
    pytest.param("open(p, mode='ab')\n", 0, id="binary-mode-keyword"),
    pytest.param("os.open(p, flags)\n", 0, id="file-descriptor"),
    pytest.param("tempfile.NamedTemporaryFile()\n", 0, id="binary-temporary-file"),
    pytest.param("webbrowser.open(url)\n", 0, id="not-a-file"),
]
assert ACCEPTED


class TestTheGuardItself:
    @pytest.mark.parametrize("source", FLAGGED)
    def test_a_text_call_without_an_encoding_is_flagged(self, source):
        assert text_io_without_encoding(source) == ([1], 1)

    @pytest.mark.parametrize(("source", "seen"), ACCEPTED)
    def test_an_encoded_or_binary_call_is_accepted(self, source, seen):
        assert text_io_without_encoding(source) == ([], seen)


class TestNoTextIoUsesTheLocaleEncoding:
    def test_every_text_io_call_in_the_package_names_its_encoding(self):
        offenders = []
        total = 0
        for module in PACKAGE_MODULES:
            lines, seen = text_io_without_encoding(module.read_text(encoding="utf-8"))
            total += seen
            offenders += [f"{module.relative_to(PACKAGE_DIR)}:{line}" for line in lines]

        # 48 calls gained an encoding under opensrm-may6 and init.py already
        # had its own; far fewer means the walk has stopped matching.
        assert total >= 48, f"only {total} text-IO calls found under {PACKAGE_DIR}"
        assert not offenders, (
            "text IO without an explicit encoding=: "
            + ", ".join(offenders)
            + ". Pass encoding='utf-8'; the locale's encoding is not UTF-8 everywhere."
        )


# Prints the default text encoding, then the template's name as code points,
# so the parent compares ASCII and never depends on the pipe's own encoding.
_LOAD_A_TEMPLATE = (
    "import locale, sys\n"
    "from pathlib import Path\n"
    "from nthlayer_generate.specs.template_loader import TemplateLoader\n"
    "template = TemplateLoader.load_from_file(Path(sys.argv[1]))\n"
    "print(locale.getencoding())\n"
    "print(' '.join(str(ord(ch)) for ch in template.name))\n"
)


class TestATemplateIsReadAsUtf8WhateverTheLocale:
    def test_a_non_ascii_template_name_survives_an_ascii_locale(self, tmp_path):
        template = tmp_path / "t.yaml"
        template.write_bytes(
            "name: café\ndescription: d\ntier: standard\ntype: api\nresources: []\n".encode()
        )
        # PYTHONUTF8=0 and PYTHONCOERCECLOCALE=0 stop Python from quietly
        # turning the C locale back into UTF-8.
        env = {**os.environ, "LC_ALL": "C", "PYTHONUTF8": "0", "PYTHONCOERCECLOCALE": "0"}
        env.pop("PYTHONIOENCODING", None)

        done = subprocess.run(
            [sys.executable, "-c", _LOAD_A_TEMPLATE, str(template)],
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )

        assert done.returncode == 0, done.stderr
        default_encoding, name = done.stdout.splitlines()
        # the run is only meaningful if the child's default really is not UTF-8
        assert default_encoding.lower().replace("-", "") not in ("utf8", "utf8sig")
        assert name == " ".join(str(ord(ch)) for ch in "café")
