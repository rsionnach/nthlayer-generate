"""Smoke test: console-script entry points resolve and run `--help`
without crashing.

Catches:
  - ``[project.scripts]`` entry point misconfigured in pyproject.toml
  - import-time crash in the entry-point module
  - missing CLI dep that the wheel didn't declare as required
"""
from __future__ import annotations

import shutil
import subprocess

import pytest


# nthlayer-generate registers two entry points: a primary and a legacy
# alias. Both must work post-install.
CONSOLE_SCRIPTS = ["nthlayer-generate", "nthlayer"]


@pytest.mark.parametrize("script", CONSOLE_SCRIPTS)
def test_console_script_on_path(script: str):
    assert shutil.which(script), (
        f"{script} not on PATH after wheel install — "
        "[project.scripts] entry point likely misconfigured"
    )


@pytest.mark.parametrize("script", CONSOLE_SCRIPTS)
def test_help_runs_clean(script: str):
    result = subprocess.run(
        [script, "--help"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, (
        f"`{script} --help` exited {result.returncode}\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
    assert result.stdout.strip(), (
        f"`{script} --help` produced no stdout — "
        "argparse/click likely didn't render help text"
    )
