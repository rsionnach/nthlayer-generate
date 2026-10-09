import pytest

"""Root test configuration."""

import logging

import structlog


def pytest_configure(config):
    """Configure structlog for tests to suppress debug/info output."""
    logging.basicConfig(level=logging.WARNING, force=True)
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.processors.add_log_level,
            structlog.processors.format_exc_info,
            structlog.dev.ConsoleRenderer(),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )


@pytest.fixture(autouse=True)
def _never_write_the_real_home(monkeypatch, tmp_path):
    """Redirect HOME for every test, so none can touch the developer's dotfiles.

    Added after `test_the_command_propagates_the_failure` ran the real
    `_quick_setup()` and wrote `~/.nthlayer/config.yaml` and `credentials.yaml`
    in an actual home directory (opensrm-h9fq). Patching that one call site
    fixes the instance; this closes the class, which is the move this codebase
    prefers -- any future test that reaches a `Path.home()` writer lands in
    `tmp_path` instead of a real machine.

    `Path.home()` reads HOME on POSIX and USERPROFILE on Windows, and
    `os.path.expanduser` consults both, so all three are redirected.
    """
    # A dotted name, so it cannot collide with a directory a test chooses for
    # itself. test_config_loader.py already creates `tmp_path / "home"` and
    # patches HOME locally, which this fixture broke on its first attempt.
    home = tmp_path / ".fake-home"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    return home
