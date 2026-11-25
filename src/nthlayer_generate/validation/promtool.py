"""Run ``promtool test rules`` on generated rules (opensrm-r0bx).

promtool evaluates rule expressions against synthetic series, offline. It is
the one harness for checking what a generated rule *does*, as opposed to
what it is called: this repo's tests use it, and ``verify-rules``
(opensrm-zcuk) will.

Unlike the pint and promruval wrappers beside this module, a missing binary
is never a pass. ``PromtoolResult.passed`` is True only when promtool ran,
at the pinned version, and every test passed. A missing or other-version
binary is ``UNAVAILABLE``, which a test must treat as a failure and a CLI
must report.

Install the pinned version with ``make promtool``
(``scripts/install_promtool.py``), which reads ``PROMTOOL_VERSION`` below.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

# The one place the version is written. scripts/install_promtool.py (used by
# CI and `make promtool`) installs this version and the runner refuses any
# other, so a test result always names the engine that produced it.
PROMTOOL_VERSION = "3.16.0"

_RULES_FILE = "rules.yml"
_TESTS_FILE = "tests.yml"
_TIMEOUT_SECONDS = 120


class PromtoolStatus(Enum):
    """What happened when the tests were handed to promtool."""

    PASSED = "passed"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class PromtoolResult:
    """Outcome of one ``promtool test rules`` run.

    ``reason`` says why the run is UNAVAILABLE (and is empty otherwise);
    ``output`` is promtool's own stdout and stderr; ``version`` is the
    version of the binary found, if one was.
    """

    status: PromtoolStatus
    output: str = ""
    reason: str = ""
    version: str | None = None

    @property
    def passed(self) -> bool:
        """True only when promtool ran and every test passed."""
        return self.status is PromtoolStatus.PASSED


def find_promtool() -> Path | None:
    """The promtool on PATH, or None."""
    found = shutil.which("promtool")
    return Path(found) if found else None


def promtool_version(binary: Path) -> str | None:
    """The version ``binary --version`` reports, or None if it cannot say.

    The first line reads ``promtool, version 3.16.0 (branch: HEAD, ...)``.
    """
    try:
        proc = subprocess.run(
            [str(binary), "--version"],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    marker = "version "
    for line in (proc.stdout + proc.stderr).splitlines():
        if marker in line:
            words = line.split(marker, 1)[1].split()
            return words[0] if words else None
    return None


def run_rule_tests(
    rule_groups: Sequence[Mapping[str, Any]],
    tests: Sequence[Mapping[str, Any]],
    *,
    evaluation_interval: str = "1m",
) -> PromtoolResult:
    """Evaluate ``tests`` against ``rule_groups`` with ``promtool test rules``.

    Args:
        rule_groups: Prometheus rule groups, as the ``groups:`` list of a
            rules file (each a mapping with ``name`` and ``rules``).
        tests: promtool unit tests, as the ``tests:`` list of a test file
            (``interval``, ``input_series``, ``promql_expr_test``,
            ``alert_rule_test``).
        evaluation_interval: how often promtool evaluates the rules.

    Returns:
        PASSED or FAILED when the pinned promtool ran, UNAVAILABLE when it
        is missing or another version (never PASSED in that case).
    """
    binary = find_promtool()
    if binary is None:
        return PromtoolResult(
            status=PromtoolStatus.UNAVAILABLE,
            reason=f"promtool is not installed (need {PROMTOOL_VERSION}; run `make promtool`)",
        )
    version = promtool_version(binary)
    if version != PROMTOOL_VERSION:
        return PromtoolResult(
            status=PromtoolStatus.UNAVAILABLE,
            reason=(
                f"promtool at {binary} is version {version or 'unknown'}, "
                f"need {PROMTOOL_VERSION} (run `make promtool`)"
            ),
            version=version,
        )

    with tempfile.TemporaryDirectory(prefix="nthlayer-promtool-") as tmp:
        workdir = Path(tmp)
        (workdir / _RULES_FILE).write_text(
            yaml.safe_dump({"groups": [dict(g) for g in rule_groups]}, sort_keys=False),
            encoding="utf-8",
        )
        (workdir / _TESTS_FILE).write_text(
            yaml.safe_dump(
                {
                    "rule_files": [_RULES_FILE],
                    "evaluation_interval": evaluation_interval,
                    "tests": [dict(t) for t in tests],
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        try:
            proc = subprocess.run(
                [str(binary), "test", "rules", _TESTS_FILE],
                cwd=workdir,
                capture_output=True,
                text=True,
                timeout=_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return PromtoolResult(
                status=PromtoolStatus.FAILED,
                output=f"promtool timed out after {exc.timeout}s",
                version=version,
            )
        except OSError as exc:
            return PromtoolResult(
                status=PromtoolStatus.UNAVAILABLE,
                reason=f"promtool at {binary} could not be run: {exc}",
                version=version,
            )

    return PromtoolResult(
        status=PromtoolStatus.PASSED if proc.returncode == 0 else PromtoolStatus.FAILED,
        output=proc.stdout + proc.stderr,
        version=version,
    )
