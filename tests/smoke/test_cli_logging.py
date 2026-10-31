"""What the CLI's logging setup puts on stderr (opensrm-iiay R5 provenance).

Subprocesses throughout: tests/conftest.py configures structlog and pytest
installs root handlers, so in-process the CLI's own configure_logging either
never runs or has basicConfig turn into a no-op. These assert on stderr text,
because the property is the rendered line itself; there is no structured
value to check instead.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from _helpers import ANALYTICS_STREAM, PAYMENT_API, PROJECT_ROOT, run_nthlayer

pytestmark = pytest.mark.smoke


def _python(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(PROJECT_ROOT),
    )


def test_warnings_on_stderr_have_their_arguments_filled_in(tmp_path: Path) -> None:
    # generators/sloth.py logs "SLO '%s' in manifest '%s' has no
    # indicator_query..." for each analytics-stream SLO.
    result = run_nthlayer(
        "apply", ANALYTICS_STREAM, "--output", "json", "--output-dir", str(tmp_path)
    )
    assert result.exit_code == 0, result
    json.loads(result.stdout)
    assert (
        "SLO 'processing-availability' in manifest 'analytics-stream' has no indicator_query"
        in result.stderr
    ), result.stderr
    assert "positional_args" not in result.stderr, result.stderr


def test_tracebacks_carry_no_local_variables() -> None:
    # structlog's rich default renders locals (which can hold API keys) and
    # colour codes even into a pipe; the CLI uses plain_traceback.
    sentinel = "sentinel-value-0x5ec7e7"
    result = _python(
        f"""
import structlog
from nthlayer_generate.logging import configure_logging

configure_logging()

def fail():
    api_key = {sentinel!r}
    raise ZeroDivisionError(len(api_key))

try:
    fail()
except ZeroDivisionError:
    structlog.get_logger().exception("boom")
"""
    )
    assert result.returncode == 0, result.stderr
    assert "Traceback (most recent call last)" in result.stderr, result.stderr
    assert "ZeroDivisionError" in result.stderr, result.stderr
    assert sentinel not in result.stderr, result.stderr
    assert "\x1b[" not in result.stderr, result.stderr


@pytest.mark.parametrize(("flags", "level"), [((), 30), (("-v",), 20)], ids=["default", "verbose"])
def test_main_sets_warning_by_default_and_info_with_verbose(
    flags: tuple[str, ...], level: int
) -> None:
    result = _python(
        f"""
import contextlib, io, logging, sys
from nthlayer_generate.demo import main

# The root logger already defaults to WARNING; start from NOTSET so the
# default case cannot pass without main() setting a level.
logging.getLogger().setLevel(logging.NOTSET)
with contextlib.redirect_stdout(io.StringIO()):
    try:
        main(["plan", {PAYMENT_API!r}, "--format", "json", *{list(flags)!r}])
    except SystemExit:
        pass
print(logging.getLogger().level)
"""
    )
    assert result.returncode == 0, result.stderr
    assert int(result.stdout.strip().splitlines()[-1]) == level, result.stdout
