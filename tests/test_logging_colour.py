"""When CLI logs are coloured (opensrm-iiay R5 edge-cases).

``_colour_on_stderr`` is pure, so these run in-process without touching the
session's structlog configuration.
"""

from __future__ import annotations

import io

import pytest

from nthlayer_generate.logging import _colour_on_stderr


class _Tty(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_a_terminal_gets_colour(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setattr("sys.stderr", _Tty())
    assert _colour_on_stderr() is True


def test_a_pipe_gets_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setattr("sys.stderr", io.StringIO())
    assert _colour_on_stderr() is False


def test_a_missing_stderr_gets_none(monkeypatch: pytest.MonkeyPatch) -> None:
    # 2>&-: Python sets sys.stderr to None.
    monkeypatch.setattr("sys.stderr", None)
    assert _colour_on_stderr() is False


def test_a_closed_stderr_gets_none(monkeypatch: pytest.MonkeyPatch) -> None:
    closed = io.StringIO()
    closed.close()  # a real closed stream: isatty() raises ValueError
    monkeypatch.setattr("sys.stderr", closed)
    assert _colour_on_stderr() is False


@pytest.mark.parametrize(("value", "colour"), [("1", False), ("", True)])
def test_no_color_disables_colour_when_non_empty(
    monkeypatch: pytest.MonkeyPatch, value: str, colour: bool
) -> None:
    # https://no-color.org: present and not an empty string disables colour.
    monkeypatch.setenv("NO_COLOR", value)
    monkeypatch.setattr("sys.stderr", _Tty())
    assert _colour_on_stderr() is colour
